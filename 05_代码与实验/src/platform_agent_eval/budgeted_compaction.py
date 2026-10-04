from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .compaction import CompactedContext, render_events
from .compaction_scenarios import CompactionScenario, ContextEvent
from .model_routing import GenerationConfig, ModelClient, ModelResponse
from .token_budget import TokenCounter


BUDGETED_COMPACTION_VERSION = "fixed-budget-compaction-dev-v1"


@dataclass(frozen=True)
class BudgetedContext:
    strategy: str
    text: str
    exact_raw_tokens: int
    budget_tokens: int | None
    retained_event_ids: tuple[str, ...]
    review_event_ids: tuple[str, ...] = ()
    format_valid: bool = True
    response: ModelResponse | None = None
    raw_output: str | None = None
    base_was_truncated: bool = False
    partial_event_id: str | None = None


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("model output is not a JSON object")
    return payload


def _truncate_words(text: str, budget: int, counter: TokenCounter) -> tuple[str, int]:
    words = text.split()
    if not words:
        raise ValueError("cannot fit empty text")
    low, high = 1, len(words)
    best = ""
    best_count = 0
    while low <= high:
        middle = (low + high) // 2
        candidate = " ".join(words[:middle])
        count = counter.count(candidate).token_count
        if count <= budget:
            best, best_count = candidate, count
            low = middle + 1
        else:
            high = middle - 1
    if not best:
        raise ValueError("budget is too small for even one word")
    return best, best_count


def _ordered_unique(
    events: tuple[ContextEvent, ...], candidates: list[ContextEvent]
) -> list[ContextEvent]:
    wanted = {event.event_id for event in candidates}
    return [event for event in events if event.event_id in wanted]


def pack_to_exact_budget(
    scenario: CompactionScenario,
    *,
    strategy: str,
    base_text: str,
    priority_events: list[ContextEvent],
    fill_events: list[ContextEvent],
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
    response: ModelResponse | None = None,
    raw_output: str | None = None,
    review_event_ids: tuple[str, ...] = (),
    format_valid: bool = True,
) -> BudgetedContext:
    if budget_tokens <= 0 or not 0.0 < minimum_utilization <= 1.0:
        raise ValueError("invalid token budget or utilization")
    base = base_text.strip()
    base_count = counter.count(base).token_count
    base_truncated = False
    if base_count > budget_tokens:
        base, base_count = _truncate_words(base, budget_tokens, counter)
        base_truncated = True

    selected: list[ContextEvent] = []
    seen: set[str] = set()
    all_candidates = [*priority_events, *fill_events]
    for event in all_candidates:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        trial_selected = _ordered_unique(scenario.history, [*selected, event])
        trial = base
        if trial_selected:
            trial += "\n" + render_events(trial_selected)
        count = counter.count(trial).token_count
        if count <= budget_tokens:
            selected = trial_selected

    text = base
    if selected:
        text += "\n" + render_events(selected)
    exact = counter.count(text).token_count
    partial_event_id: str | None = None
    minimum_tokens = int(budget_tokens * minimum_utilization)
    if exact < minimum_tokens:
        remaining = [
            event for event in reversed(scenario.history)
            if event.event_id not in {item.event_id for item in selected}
        ]
        if remaining:
            event = remaining[0]
            prefix = f"\n[{event.event_id}] {event.role.upper()} [PARTIAL]: "
            allowance = budget_tokens - counter.count(text + prefix).token_count
            if allowance > 0:
                try:
                    fragment, _ = _truncate_words(event.content, allowance, counter)
                except ValueError:
                    fragment = ""
                if fragment:
                    candidate = text + prefix + fragment
                    count = counter.count(candidate).token_count
                    if count <= budget_tokens:
                        text, exact = candidate, count
                        partial_event_id = event.event_id
    if exact < minimum_tokens:
        padding = (
            "\n[BUDGET-FILL] Routine telemetry remained available but contained no "
            "new authority, policy, ownership, or recovery evidence."
        )
        repeated = text
        while counter.count(repeated + padding).token_count <= budget_tokens:
            repeated += padding
        if repeated != text:
            text = repeated
            exact = counter.count(text).token_count
        if exact < minimum_tokens:
            allowance = budget_tokens - exact
            if allowance > 0:
                try:
                    fragment, _ = _truncate_words(padding, allowance, counter)
                except ValueError:
                    fragment = ""
                if fragment:
                    candidate = text + "\n" + fragment
                    count = counter.count(candidate).token_count
                    if count <= budget_tokens:
                        text, exact = candidate, count
    if exact > budget_tokens:
        raise AssertionError("budget packer exceeded the exact raw-token budget")
    return BudgetedContext(
        strategy=strategy,
        text=text,
        exact_raw_tokens=exact,
        budget_tokens=budget_tokens,
        retained_event_ids=tuple(event.event_id for event in selected),
        review_event_ids=review_event_ids,
        format_valid=format_valid,
        response=response,
        raw_output=raw_output,
        base_was_truncated=base_truncated,
        partial_event_id=partial_event_id,
    )


def budgeted_full_context(
    scenario: CompactionScenario,
    counter: TokenCounter,
) -> BudgetedContext:
    text = render_events(scenario.history)
    return BudgetedContext(
        strategy="full_context_ceiling",
        text=text,
        exact_raw_tokens=counter.count(text).token_count,
        budget_tokens=None,
        retained_event_ids=tuple(event.event_id for event in scenario.history),
    )


def budgeted_recent_window(
    scenario: CompactionScenario,
    *,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> BudgetedContext:
    system = [event for event in scenario.history if event.role == "system"]
    recent = list(reversed([event for event in scenario.history if event.role != "system"]))
    return pack_to_exact_budget(
        scenario,
        strategy="recent_window",
        base_text="RECENT-WINDOW CONTEXT",
        priority_events=system,
        fill_events=recent,
        counter=counter,
        budget_tokens=budget_tokens,
        minimum_utilization=minimum_utilization,
    )


_NOISE_CUES = (
    "repeated diagnostic rows",
    "continuing routine diagnostics",
    "do not change authority",
)
_PIN_CUES = re.compile(
    r"\b(APR-[A-Z0-9-]+|FREEZE-[A-Z0-9-]+|EXC-[A-Z0-9-]+|"
    r"CONSENT-[A-Z0-9-]+|AUTH-[A-Z0-9-]+|RB-[A-Z0-9-]+|"
    r"BOUNDARY-[A-Z0-9-]+|DELEGATION-[A-Z0-9-]+|"
    r"CHANGE-WINDOW-[A-Z0-9-]+|signed|staging-only|must not|"
    r"does not authorize|only a platform operator|valid checkpoint|"
    r"migration target|rollback|no restorable snapshot|operator-only|"
    r"explicitly closes)\b",
    flags=re.IGNORECASE,
)


def _pin_score(event: ContextEvent) -> int:
    lower = event.content.lower()
    if any(cue in lower for cue in _NOISE_CUES):
        return 0
    return len(_PIN_CUES.findall(event.content))


def budgeted_precise_pinning(
    scenario: CompactionScenario,
    *,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> BudgetedContext:
    system = [event for event in scenario.history if event.role == "system"]
    scored = sorted(
        (
            (event, _pin_score(event), index)
            for index, event in enumerate(scenario.history)
            if event.role != "system"
        ),
        key=lambda item: (-item[1], item[2]),
    )
    priority = [event for event, score, _ in scored if score > 0]
    recent = list(reversed([event for event in scenario.history if event.role != "system"]))
    return pack_to_exact_budget(
        scenario,
        strategy="precise_pinning",
        base_text="PRECISELY PINNED CONTEXT",
        priority_events=[*system, *priority],
        fill_events=recent,
        counter=counter,
        budget_tokens=budget_tokens,
        minimum_utilization=minimum_utilization,
    )


def _generic_prompt(scenario: CompactionScenario) -> str:
    return (
        f"PROMPT_TEMPLATE={BUDGETED_COMPACTION_VERSION}-generic\n"
        "Summarize this agent history for the next state-changing decision. Preserve "
        "current goal, authority scope, prohibitions, validity, ownership, and "
        "recovery facts; remove routine telemetry. Keep the summary below 120 words. "
        "Return exactly one JSON object with one string field named summary.\n\n"
        f"HISTORY:\n{render_events(scenario.history)}"
    )


def budgeted_generic_summary(
    scenario: CompactionScenario,
    *,
    client: ModelClient,
    config: GenerationConfig,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> BudgetedContext:
    prompt = _generic_prompt(scenario)
    response = client.generate(prompt, config)
    valid = True
    try:
        payload = _json_object(response.text)
        if set(payload) != {"summary"}:
            raise ValueError("generic summary must contain only summary")
        summary = str(payload["summary"]).strip()
        if not summary:
            raise ValueError("empty summary")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        summary = "The summary output was invalid; preserve recent raw context."
        valid = False
    system = [event for event in scenario.history if event.role == "system"]
    recent = list(reversed([event for event in scenario.history if event.role != "system"]))
    return pack_to_exact_budget(
        scenario,
        strategy="generic_summary",
        base_text=f"GENERIC SUMMARY:\n{summary}",
        priority_events=system,
        fill_events=recent,
        counter=counter,
        budget_tokens=budget_tokens,
        minimum_utilization=minimum_utilization,
        response=response,
        raw_output=response.text,
        format_valid=valid,
    )


def _ufold_prompt(scenario: CompactionScenario) -> str:
    schema = {
        "intent_summary": "short current goal and unresolved decision",
        "tool_log": [
            {"event_id": "visible event ID", "fact": "exact decision-relevant fact"}
        ],
    }
    return (
        f"PROMPT_TEMPLATE={BUDGETED_COMPACTION_VERSION}-ufold-lite\n"
        "Fold completed reasoning into a short intent summary, but preserve a "
        "separate cited log of authority, policy, state, validity, and recovery "
        "facts needed before a state change. Do not treat routine telemetry as "
        "decision evidence. Return exactly one JSON object matching:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"HISTORY:\n{render_events(scenario.history)}"
    )


def budgeted_ufold_lite(
    scenario: CompactionScenario,
    *,
    client: ModelClient,
    config: GenerationConfig,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> BudgetedContext:
    prompt = _ufold_prompt(scenario)
    response = client.generate(prompt, config)
    valid_ids = {event.event_id for event in scenario.history}
    valid = True
    cited_ids: list[str] = []
    try:
        payload = _json_object(response.text)
        if set(payload) != {"intent_summary", "tool_log"}:
            raise ValueError("U-Fold-lite output uses an unexpected schema")
        intent = str(payload["intent_summary"]).strip()
        raw_log = payload["tool_log"]
        if not intent or not isinstance(raw_log, list):
            raise ValueError("invalid intent summary or tool log")
        facts: list[str] = []
        for item in raw_log:
            if not isinstance(item, dict) or set(item) != {"event_id", "fact"}:
                raise ValueError("invalid tool-log item")
            event_id = str(item["event_id"])
            fact = str(item["fact"]).strip()
            if event_id not in valid_ids or not fact:
                raise ValueError("invalid cited event or empty fact")
            cited_ids.append(event_id)
            facts.append(f"[{event_id}] {fact}")
        base = "FOLDED INTENT:\n" + intent + "\nCITED TOOL LOG:\n" + "\n".join(facts)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        base = "U-Fold-lite output was invalid; preserve recent raw context."
        cited_ids = []
        valid = False
    lookup = {event.event_id: event for event in scenario.history}
    cited = [lookup[event_id] for event_id in dict.fromkeys(cited_ids)]
    system = [event for event in scenario.history if event.role == "system"]
    recent = list(reversed([event for event in scenario.history if event.role != "system"]))
    return pack_to_exact_budget(
        scenario,
        strategy="ufold_lite",
        base_text=base,
        priority_events=[*system, *cited],
        fill_events=recent,
        counter=counter,
        budget_tokens=budget_tokens,
        minimum_utilization=minimum_utilization,
        response=response,
        raw_output=response.text,
        format_valid=valid,
    )


def _selective_prompt(scenario: CompactionScenario) -> str:
    schema = {
        "summary": "short progress summary",
        "preserve_event_ids": ["events that must remain verbatim"],
        "review_event_ids": ["ambiguous authority or validity requiring review"],
    }
    return (
        f"PROMPT_TEMPLATE={BUDGETED_COMPACTION_VERSION}-selective-audit\n"
        "Audit the history before compaction. Preserve raw events carrying exact "
        "authority, policy, ownership, validity, or recovery evidence. Mark an "
        "event for review only when one human answer could resolve its ambiguity. "
        "Do not request review for routine telemetry and do not invent an answer. "
        "Return exactly one JSON object matching:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"HISTORY:\n{render_events(scenario.history)}"
    )


def budgeted_selective_audit(
    scenario: CompactionScenario,
    *,
    client: ModelClient,
    config: GenerationConfig,
    counter: TokenCounter,
    budget_tokens: int,
    minimum_utilization: float,
) -> BudgetedContext:
    prompt = _selective_prompt(scenario)
    response = client.generate(prompt, config)
    valid_ids = {event.event_id for event in scenario.history}
    valid = True
    preserve_ids: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    try:
        payload = _json_object(response.text)
        if set(payload) != {"summary", "preserve_event_ids", "review_event_ids"}:
            raise ValueError("selective audit output uses an unexpected schema")
        summary = str(payload["summary"]).strip()
        preserve = payload["preserve_event_ids"]
        review = payload["review_event_ids"]
        if not summary or not isinstance(preserve, list) or not isinstance(review, list):
            raise ValueError("invalid selective summary or event lists")
        if not all(isinstance(item, str) for item in [*preserve, *review]):
            raise ValueError("event IDs must be strings")
        if any(item not in valid_ids for item in [*preserve, *review]):
            raise ValueError("selective audit cited an invisible event")
        preserve_ids = tuple(dict.fromkeys(preserve))
        review_ids = tuple(dict.fromkeys(review))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        summary = "Selective audit output was invalid; preserve recent raw context."
        valid = False
    lookup = {event.event_id: event for event in scenario.history}
    selected = [lookup[item] for item in [*review_ids, *preserve_ids]]
    system = [event for event in scenario.history if event.role == "system"]
    recent = list(reversed([event for event in scenario.history if event.role != "system"]))
    return pack_to_exact_budget(
        scenario,
        strategy="selective_audit",
        base_text=f"SELECTIVE SUMMARY:\n{summary}",
        priority_events=[*system, *selected],
        fill_events=recent,
        counter=counter,
        budget_tokens=budget_tokens,
        minimum_utilization=minimum_utilization,
        response=response,
        raw_output=response.text,
        review_event_ids=review_ids,
        format_valid=valid,
    )


def as_compacted_context(context: BudgetedContext) -> CompactedContext:
    return CompactedContext(
        strategy=context.strategy,
        text=context.text,
        format_valid=context.format_valid,
        retained_event_ids=context.retained_event_ids,
        review_event_ids=context.review_event_ids,
        response=context.response,
        raw_output=context.raw_output,
    )
