from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .compaction import render_events
from .compaction_scenarios import ContextEvent
from .model_routing import GenerationConfig, ModelClient, ModelResponse
from .protocol_falsification import (
    ProtocolCompactionDraft,
    build_generic_pinning_draft,
    build_summary_draft,
)
from .proof_cards import ProofCard, ProofCardKind
from .token_budget import TokenCounter
from .typed_compaction_dev import TypedCompactionContext


TYPED_BUDGET_COMPACTION_VERSION = "typed-budget-compaction-v1"
METHODS = (
    "full_context_ceiling",
    "recent_window",
    "neutral_summary",
    "task_aware_summary",
    "generic_pinning",
    "ufold_lite",
    "typed_card_retention",
)
BUDGETED_METHODS = METHODS[1:]


@dataclass(frozen=True)
class TypedCompactionDraft:
    method: str
    summary: str
    priority_event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...] = ()
    format_valid: bool = True
    response: ModelResponse | None = None
    raw_output: str | None = None


@dataclass(frozen=True)
class TypedBudgetContext:
    method: str
    text: str
    exact_raw_tokens: int
    budget_tokens: int | None
    retained_event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    neutral_fill_event_ids: tuple[str, ...]
    format_valid: bool = True
    response: ModelResponse | None = None
    raw_output: str | None = None
    base_was_truncated: bool = False


_BRACKETED_REF = re.compile(r"\[([^\[\]\s]+)\]")


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


def _truncate_words(text: str, budget: int, counter: TokenCounter) -> str:
    words = text.split()
    low, high, best = 1, len(words), ""
    while low <= high:
        middle = (low + high) // 2
        candidate = " ".join(words[:middle])
        if counter.count(candidate).token_count <= budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if not best:
        raise ValueError("budget cannot fit the active-memory header")
    return best


def _pad_to_floor(
    text: str,
    *,
    minimum: int,
    budget: int,
    counter: TokenCounter,
) -> str:
    padding_words = (
        "Routine telemetry remained available and added no new proof."
    ).split()
    while counter.count(text).token_count < minimum:
        progressed = False
        for word in padding_words:
            separator = "\n" if word == padding_words[0] else " "
            candidate = text + separator + word
            if counter.count(candidate).token_count > budget:
                return text
            if candidate != text:
                text = candidate
                progressed = True
            if counter.count(text).token_count >= minimum:
                return text
        if not progressed:
            return text
    return text


def _render(
    context: TypedCompactionContext,
    selected_ids: set[str],
    summary: str,
) -> str:
    selected = [
        event for event in context.active_events if event.event_id in selected_ids
    ]
    parts = ["ACTIVE MEMORY"]
    if summary:
        parts.append(summary)
    if selected:
        parts.append(render_events(selected))
    return "\n".join(parts)


def _neutral_events(context: TypedCompactionContext) -> list[ContextEvent]:
    card_sources = {
        source for card in context.visible_cards for source in card.source_event_ids
    }
    return [
        event
        for event in reversed(context.active_events)
        if event.role not in {"system", "user"} and event.event_id not in card_sources
    ]


def deterministic_drafts(
    context: TypedCompactionContext,
) -> dict[str, TypedCompactionDraft]:
    scenario = context.scenario
    generic = build_generic_pinning_draft(scenario)
    card_sources = tuple(
        source for card in context.visible_cards for source in card.source_event_ids
    )
    return {
        "recent_window": TypedCompactionDraft(
            method="recent_window",
            summary="",
            priority_event_ids=tuple(
                event.event_id
                for event in reversed(context.active_events)
                if event.role != "system"
            ),
        ),
        "generic_pinning": TypedCompactionDraft(
            method="generic_pinning",
            summary="",
            priority_event_ids=tuple(
                event.event_id for event in generic.priority_events
            ),
        ),
        "typed_card_retention": TypedCompactionDraft(
            method="typed_card_retention",
            summary="",
            priority_event_ids=card_sources,
            source_event_ids=card_sources,
        ),
    }


def summary_draft(
    context: TypedCompactionContext,
    method: str,
    client: ModelClient,
    config: GenerationConfig,
) -> TypedCompactionDraft:
    draft: ProtocolCompactionDraft = build_summary_draft(
        context.scenario, method, client, config
    )
    return TypedCompactionDraft(
        method=method,
        summary=draft.summary,
        priority_event_ids=(),
        source_event_ids=draft.summary_source_event_ids,
        format_valid=draft.format_valid,
        response=draft.response,
        raw_output=draft.raw_output,
    )


def build_ufold_prompt(context: TypedCompactionContext) -> str:
    schema = {
        "intent_summary": "short current goal and unresolved decision",
        "proof_log": [
            {
                "event_id": "one visible source event ID",
                "fact": "one exact action-relevant fact",
            }
        ],
    }
    return (
        f"PROMPT_TEMPLATE={TYPED_BUDGET_COMPACTION_VERSION}-ufold-lite\n"
        "Fold completed reasoning into an intent summary. Keep a separate proof log "
        "for current authority, clearance, active holds, delegation, recovery, and "
        "repair channels. Cite only visible event IDs and never infer proof from "
        "silence. Return exactly one JSON object matching:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"HISTORY:\n{context.active_context}"
    )


def ufold_draft(
    context: TypedCompactionContext,
    client: ModelClient,
    config: GenerationConfig,
) -> TypedCompactionDraft:
    response = client.generate(build_ufold_prompt(context), config)
    visible = {event.event_id for event in context.active_events}
    valid = True
    source_ids: list[str] = []
    try:
        payload = _json_object(response.text)
        if set(payload) != {"intent_summary", "proof_log"}:
            raise ValueError("unexpected U-Fold-lite schema")
        intent = str(payload["intent_summary"]).strip()
        log = payload["proof_log"]
        if not intent or not isinstance(log, list):
            raise ValueError("invalid intent or proof log")
        facts: list[str] = []
        for item in log:
            if not isinstance(item, dict) or set(item) != {"event_id", "fact"}:
                raise ValueError("invalid proof-log item")
            event_id = str(item["event_id"])
            fact = str(item["fact"]).strip()
            if event_id not in visible or not fact:
                raise ValueError("proof log cites an invalid event")
            source_ids.append(event_id)
            facts.append(f"[{event_id}] {fact}")
        summary = "INTENT: " + intent
        if facts:
            summary += "\nPROOF LOG:\n" + "\n".join(facts)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        summary = "Compaction output was invalid; no derived proof is reliable."
        source_ids = []
        valid = False
    return TypedCompactionDraft(
        method="ufold_lite",
        summary=summary,
        priority_event_ids=(),
        source_event_ids=tuple(dict.fromkeys(source_ids)),
        format_valid=valid,
        response=response,
        raw_output=response.text,
    )


def build_budget_context(
    context: TypedCompactionContext,
    draft: TypedCompactionDraft,
    *,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> TypedBudgetContext:
    if draft.method not in BUDGETED_METHODS:
        raise ValueError(f"unsupported budgeted method: {draft.method}")
    if budget_tokens <= 0 or not 0.0 < minimum_utilization <= 1.0:
        raise ValueError("invalid token budget or utilization")
    system_ids = {
        event.event_id for event in context.active_events if event.role == "system"
    }
    selected_ids = set(system_ids)
    text = _render(context, selected_ids, draft.summary)
    truncated = False
    if counter.count(text).token_count > budget_tokens:
        text = _truncate_words(text, budget_tokens, counter)
        selected_ids = set()
        truncated = True
    by_id = {event.event_id: event for event in context.active_events}
    for event_id in draft.priority_event_ids:
        if event_id not in by_id:
            continue
        candidate_ids = {*selected_ids, event_id}
        candidate = _render(context, candidate_ids, draft.summary)
        if counter.count(candidate).token_count <= budget_tokens:
            selected_ids = candidate_ids
            text = candidate
    fill_ids: list[str] = []
    if draft.method != "recent_window":
        for event in _neutral_events(context):
            if event.event_id in selected_ids:
                continue
            candidate_ids = {*selected_ids, event.event_id}
            candidate = _render(context, candidate_ids, draft.summary)
            if counter.count(candidate).token_count <= budget_tokens:
                selected_ids = candidate_ids
                fill_ids.append(event.event_id)
                text = candidate
    minimum = int(budget_tokens * minimum_utilization)
    text = _pad_to_floor(
        text,
        minimum=minimum,
        budget=budget_tokens,
        counter=counter,
    )
    exact = counter.count(text).token_count
    if exact > budget_tokens:
        raise AssertionError("typed budget context exceeded token budget")
    retained = tuple(
        event.event_id
        for event in context.active_events
        if event.event_id in selected_ids
    )
    sources = tuple(
        dict.fromkeys(
            [*_BRACKETED_REF.findall(text), *retained]
        )
    )
    return TypedBudgetContext(
        method=draft.method,
        text=text,
        exact_raw_tokens=exact,
        budget_tokens=budget_tokens,
        retained_event_ids=retained,
        source_event_ids=sources,
        neutral_fill_event_ids=tuple(fill_ids),
        format_valid=draft.format_valid,
        response=draft.response,
        raw_output=draft.raw_output,
        base_was_truncated=truncated,
    )


def full_context(
    context: TypedCompactionContext,
    counter: TokenCounter,
) -> TypedBudgetContext:
    text = context.active_context
    ids = tuple(event.event_id for event in context.active_events)
    return TypedBudgetContext(
        method="full_context_ceiling",
        text=text,
        exact_raw_tokens=counter.count(text).token_count,
        budget_tokens=None,
        retained_event_ids=ids,
        source_event_ids=ids,
        neutral_fill_event_ids=(),
    )


def rehydrate_cards(
    context: TypedCompactionContext,
    compacted: TypedBudgetContext,
) -> tuple[ProofCard, ...]:
    visible_sources = set(compacted.source_event_ids)
    return tuple(
        card
        for card in context.visible_cards
        if set(card.source_event_ids).issubset(visible_sources)
    )


def retained_card_kinds(
    context: TypedCompactionContext,
    compacted: TypedBudgetContext,
) -> tuple[ProofCardKind, ...]:
    return tuple(card.kind for card in rehydrate_cards(context, compacted))
