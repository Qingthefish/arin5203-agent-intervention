from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .domain import Decision
from .durable_proof_store import (
    DurableProofRecord,
    DurableProofStore,
    augment_with_durable_cards,
    lookup_durable_cards,
)
from .proof_cards import (
    ActionRequest,
    ProofCard,
    ProofCardInput,
    ProofCardKind,
    ProofPolicy,
    validate_proof_cards,
)


MEMORY_CRASH_TEST_VERSION = "agent-memory-crash-test/v1"
CONDITIONS = (
    "full_evidence",
    "remove_action_critical",
    "remove_matched_noise",
)
PROOF_SOURCES = ("memory", "registry")


@dataclass(frozen=True)
class CrashEvent:
    event_id: str
    role: str
    content: str


@dataclass(frozen=True)
class StrategySpec:
    name: str
    selector: str
    event_count: int | None = None
    snapshots: Mapping[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class CrashCase:
    case_id: str
    title: str
    action: ActionRequest
    policy: ProofPolicy
    events: tuple[CrashEvent, ...]
    proof_cards: tuple[ProofCard, ...]
    critical_event_id: str
    matched_noise_event_id: str
    expected_decisions: Mapping[str, Decision]
    unsafe_if_executed: Mapping[str, bool]
    state_before: Mapping[str, object]
    state_after: Mapping[str, object]
    durable_store: DurableProofStore | None = None


@dataclass(frozen=True)
class CrashSuite:
    suite_id: str
    title: str
    cases: tuple[CrashCase, ...]
    strategies: tuple[StrategySpec, ...]


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _string_tuple(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{field} must be a JSON list of strings")
    result = tuple(_required_text(item, field) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _scope(value: object, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field} must be a non-empty JSON object")
    return tuple(
        sorted(
            (
                _required_text(key, f"{field} key"),
                _required_text(item, f"{field}.{key}"),
            )
            for key, item in value.items()
        )
    )


def _action(value: object) -> ActionRequest:
    if not isinstance(value, dict):
        raise ValueError("action must be an object")
    return ActionRequest(
        actor_id=_required_text(value.get("actor_id"), "action.actor_id"),
        operation=_required_text(value.get("operation"), "action.operation"),
        target_id=_required_text(value.get("target_id"), "action.target_id"),
        scope=_scope(value.get("scope"), "action.scope"),
        effective_at=_required_text(value.get("effective_at"), "action.effective_at"),
    )


def _policy(value: object) -> ProofPolicy:
    if not isinstance(value, dict):
        raise ValueError("policy must be an object")
    return ProofPolicy(
        authority_issuers=_string_tuple(value.get("authority_issuers"), "authority_issuers"),
        clearance_issuers=_string_tuple(value.get("clearance_issuers"), "clearance_issuers"),
        hold_issuers=_string_tuple(value.get("hold_issuers"), "hold_issuers"),
        delegation_issuers=_string_tuple(value.get("delegation_issuers"), "delegation_issuers"),
        recovery_issuers=_string_tuple(value.get("recovery_issuers"), "recovery_issuers"),
        repair_channel_issuers=_string_tuple(
            value.get("repair_channel_issuers"), "repair_channel_issuers"
        ),
        confirmable_authority_actors=_string_tuple(
            value.get("confirmable_authority_actors", []),
            "confirmable_authority_actors",
            allow_empty=True,
        ),
        requires_clearance=bool(value.get("requires_clearance", True)),
        requires_delegation=bool(value.get("requires_delegation", False)),
        requires_recovery=bool(value.get("requires_recovery", True)),
    )


def _proof_card(value: object) -> ProofCard:
    if not isinstance(value, dict):
        raise ValueError("proof card must be an object")
    try:
        kind = ProofCardKind(_required_text(value.get("kind"), "proof_card.kind"))
    except ValueError as exc:
        raise ValueError(f"unsupported proof-card kind: {value.get('kind')!r}") from exc
    return ProofCard(
        card_id=_required_text(value.get("card_id"), "proof_card.card_id"),
        kind=kind,
        source_event_ids=_string_tuple(
            value.get("source_event_ids"), "proof_card.source_event_ids"
        ),
        issuer_id=_required_text(value.get("issuer_id"), "proof_card.issuer_id"),
        subject_id=_required_text(value.get("subject_id"), "proof_card.subject_id"),
        operation=_required_text(value.get("operation"), "proof_card.operation"),
        target_id=_required_text(value.get("target_id"), "proof_card.target_id"),
        scope=_scope(value.get("scope"), "proof_card.scope"),
        valid_from=_required_text(value.get("valid_from"), "proof_card.valid_from"),
        valid_until=_required_text(value.get("valid_until"), "proof_card.valid_until"),
        authenticated=bool(value.get("authenticated", True)),
        transferable=bool(value.get("transferable", False)),
    )


def _store(value: object, cards_by_id: Mapping[str, ProofCard]) -> DurableProofStore:
    if not isinstance(value, dict):
        raise ValueError("durable_store must be an object")
    records_value = value.get("records")
    if not isinstance(records_value, list):
        raise ValueError("durable_store.records must be a list")
    records: list[DurableProofRecord] = []
    for item in records_value:
        if not isinstance(item, dict):
            raise ValueError("durable_store record must be an object")
        card_id = _required_text(item.get("card_id"), "durable_store.card_id")
        try:
            card = cards_by_id[card_id]
        except KeyError as exc:
            raise ValueError(f"durable store references unknown card {card_id!r}") from exc
        records.append(
            DurableProofRecord(
                record_id=_required_text(item.get("record_id"), "durable_store.record_id"),
                card=card,
                committed_at=_required_text(
                    item.get("committed_at"), "durable_store.committed_at"
                ),
                revoked_at=item.get("revoked_at"),
                integrity_verified=bool(item.get("integrity_verified", True)),
            )
        )
    return DurableProofStore(
        store_id=_required_text(value.get("store_id"), "durable_store.store_id"),
        snapshot_id=_required_text(value.get("snapshot_id"), "durable_store.snapshot_id"),
        records=tuple(records),
    )


def _strategy(value: object) -> StrategySpec:
    if not isinstance(value, dict):
        raise ValueError("strategy must be an object")
    name = _required_text(value.get("name"), "strategy.name")
    selector = _required_text(value.get("selector"), f"strategy {name}.selector")
    if selector not in {"all_visible", "proof_sources", "recent_events", "snapshot"}:
        raise ValueError(f"unsupported selector {selector!r} for strategy {name!r}")
    event_count = value.get("event_count")
    if selector == "recent_events" and (
        not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 1
    ):
        raise ValueError(f"strategy {name!r} requires positive event_count")
    snapshots_value = value.get("snapshots")
    snapshots: dict[str, tuple[str, ...]] | None = None
    if selector == "snapshot":
        if not isinstance(snapshots_value, dict) or set(snapshots_value) != set(CONDITIONS):
            raise ValueError(
                f"strategy {name!r} snapshots must define exactly {', '.join(CONDITIONS)}"
            )
        snapshots = {
            condition: _string_tuple(
                snapshots_value[condition],
                f"strategy {name}.snapshots.{condition}",
                allow_empty=True,
            )
            for condition in CONDITIONS
        }
    return StrategySpec(name, selector, event_count, snapshots)


def _decisions(value: object, field: str) -> dict[str, Decision]:
    if not isinstance(value, dict) or set(value) != set(CONDITIONS):
        raise ValueError(f"{field} must define exactly {', '.join(CONDITIONS)}")
    try:
        return {condition: Decision(value[condition]) for condition in CONDITIONS}
    except ValueError as exc:
        raise ValueError(f"{field} contains an unsupported decision") from exc


def _booleans(value: object, field: str) -> dict[str, bool]:
    if not isinstance(value, dict) or set(value) != set(CONDITIONS):
        raise ValueError(f"{field} must define exactly {', '.join(CONDITIONS)}")
    if not all(isinstance(value[condition], bool) for condition in CONDITIONS):
        raise ValueError(f"{field} values must be Boolean")
    return {condition: value[condition] for condition in CONDITIONS}


def _case(value: object) -> CrashCase:
    if not isinstance(value, dict):
        raise ValueError("case must be an object")
    case_id = _required_text(value.get("case_id"), "case.case_id")
    events_value = value.get("events")
    if not isinstance(events_value, list) or len(events_value) < 3:
        raise ValueError(f"case {case_id!r} needs at least three events")
    events = tuple(
        CrashEvent(
            event_id=_required_text(item.get("event_id"), "event.event_id"),
            role=_required_text(item.get("role"), "event.role"),
            content=_required_text(item.get("content"), "event.content"),
        )
        for item in events_value
        if isinstance(item, dict)
    )
    if len(events) != len(events_value):
        raise ValueError(f"case {case_id!r} contains a non-object event")
    event_ids = tuple(event.event_id for event in events)
    if len(event_ids) != len(set(event_ids)):
        raise ValueError(f"case {case_id!r} event IDs must be unique")
    cards_value = value.get("proof_cards")
    if not isinstance(cards_value, list):
        raise ValueError(f"case {case_id!r} proof_cards must be a list")
    cards = tuple(_proof_card(item) for item in cards_value)
    if len({card.card_id for card in cards}) != len(cards):
        raise ValueError(f"case {case_id!r} proof-card IDs must be unique")
    unknown_sources = {
        source
        for card in cards
        for source in card.source_event_ids
        if source not in event_ids
    }
    if unknown_sources:
        raise ValueError(f"case {case_id!r} has unknown proof sources: {sorted(unknown_sources)}")
    critical_id = _required_text(value.get("critical_event_id"), "critical_event_id")
    noise_id = _required_text(value.get("matched_noise_event_id"), "matched_noise_event_id")
    if critical_id == noise_id or critical_id not in event_ids or noise_id not in event_ids:
        raise ValueError(f"case {case_id!r} needs two distinct, existing deletion events")
    by_id = {event.event_id: event for event in events}
    critical = by_id[critical_id]
    noise = by_id[noise_id]
    if critical.role != noise.role:
        raise ValueError(f"case {case_id!r} critical and noise events must share a role")
    if len(critical.content.encode("utf-8")) != len(noise.content.encode("utf-8")):
        raise ValueError(f"case {case_id!r} critical and noise events must match in UTF-8 bytes")
    state = value.get("state", {})
    if not isinstance(state, dict):
        raise ValueError(f"case {case_id!r} state must be an object")
    before = state.get("before", {})
    after = state.get("after", {})
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError(f"case {case_id!r} state.before/after must be objects")
    cards_by_id = {card.card_id: card for card in cards}
    store_value = value.get("durable_store")
    return CrashCase(
        case_id=case_id,
        title=_required_text(value.get("title"), "case.title"),
        action=_action(value.get("action")),
        policy=_policy(value.get("policy")),
        events=events,
        proof_cards=cards,
        critical_event_id=critical_id,
        matched_noise_event_id=noise_id,
        expected_decisions=_decisions(value.get("expected_decisions"), "expected_decisions"),
        unsafe_if_executed=_booleans(
            value.get("unsafe_if_executed"), "unsafe_if_executed"
        ),
        state_before=before,
        state_after=after,
        durable_store=_store(store_value, cards_by_id) if store_value is not None else None,
    )


def load_crash_suite(path: Path) -> CrashSuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("crash-test spec must be a JSON object")
    if payload.get("schema_version") != MEMORY_CRASH_TEST_VERSION:
        raise ValueError(f"schema_version must be {MEMORY_CRASH_TEST_VERSION!r}")
    cases_value = payload.get("cases")
    strategies_value = payload.get("strategies")
    if not isinstance(cases_value, list) or not cases_value:
        raise ValueError("cases must be a non-empty list")
    if not isinstance(strategies_value, list) or not strategies_value:
        raise ValueError("strategies must be a non-empty list")
    cases = tuple(_case(item) for item in cases_value)
    strategies = tuple(_strategy(item) for item in strategies_value)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("case IDs must be unique")
    if len({strategy.name for strategy in strategies}) != len(strategies):
        raise ValueError("strategy names must be unique")
    return CrashSuite(
        suite_id=_required_text(payload.get("suite_id"), "suite_id"),
        title=_required_text(payload.get("title"), "title"),
        cases=cases,
        strategies=strategies,
    )


def visible_event_ids(case: CrashCase, condition: str) -> tuple[str, ...]:
    if condition not in CONDITIONS:
        raise ValueError(f"unsupported condition: {condition}")
    deleted = {
        "full_evidence": None,
        "remove_action_critical": case.critical_event_id,
        "remove_matched_noise": case.matched_noise_event_id,
    }[condition]
    return tuple(event.event_id for event in case.events if event.event_id != deleted)


def select_event_ids(
    case: CrashCase,
    strategy: StrategySpec,
    condition: str,
) -> tuple[str, ...]:
    visible = visible_event_ids(case, condition)
    visible_set = set(visible)
    if strategy.selector == "all_visible":
        return visible
    if strategy.selector == "proof_sources":
        proof_sources = {
            source for card in case.proof_cards for source in card.source_event_ids
        }
        return tuple(event_id for event_id in visible if event_id in proof_sources)
    if strategy.selector == "recent_events":
        assert strategy.event_count is not None
        return visible[-strategy.event_count :]
    assert strategy.selector == "snapshot" and strategy.snapshots is not None
    selected = strategy.snapshots[condition]
    unavailable = set(selected) - visible_set
    if unavailable:
        raise ValueError(
            f"strategy {strategy.name!r} selects unavailable events for {case.case_id}/"
            f"{condition}: {sorted(unavailable)}"
        )
    return tuple(event_id for event_id in visible if event_id in set(selected))


def _rehydrated_cards(case: CrashCase, retained_event_ids: tuple[str, ...]) -> tuple[ProofCard, ...]:
    retained = set(retained_event_ids)
    return tuple(
        card
        for card in case.proof_cards
        if set(card.source_event_ids).issubset(retained)
    )


def _state_replay(case: CrashCase, decision: Decision, unsafe: bool) -> dict[str, object]:
    mutation_applied = decision is Decision.AUTO_EXECUTE
    after = dict(case.state_after if mutation_applied else case.state_before)
    keys = sorted(set(case.state_before) | set(after))
    diff = {
        key: {"before": case.state_before.get(key), "after": after.get(key)}
        for key in keys
        if case.state_before.get(key) != after.get(key)
    }
    return {
        "before": dict(case.state_before),
        "after": after,
        "diff": diff,
        "mutation_applied": mutation_applied,
        "harmful_mutation": mutation_applied and unsafe,
    }


def _record(
    case: CrashCase,
    strategy: StrategySpec,
    condition: str,
    proof_source: str,
) -> dict[str, object]:
    visible_ids = visible_event_ids(case, condition)
    retained_ids = select_event_ids(case, strategy, condition)
    memory_cards = _rehydrated_cards(case, retained_ids)
    runtime_input = ProofCardInput(case.action, case.policy, memory_cards)
    lookup_receipt: dict[str, object] | None = None
    if proof_source == "registry":
        if case.durable_store is None:
            raise ValueError(
                f"case {case.case_id!r} has no durable_store for registry mode"
            )
        lookup = lookup_durable_cards(case.durable_store, case.action)
        runtime_input = augment_with_durable_cards(runtime_input, lookup)
        lookup_receipt = asdict(lookup.receipt)
    result = validate_proof_cards(runtime_input)
    expected = case.expected_decisions[condition]
    unsafe = case.unsafe_if_executed[condition]
    route_correct = result.decision is expected
    harmful_execution = unsafe and result.decision is Decision.AUTO_EXECUTE
    retained_set = set(retained_ids)
    decisive_cards = {
        card.card_id: card for card in runtime_input.cards if card.card_id in result.decisive_card_ids
    }
    decisive_provenance_complete = all(
        card.source_event_ids
        and (
            proof_source == "registry"
            or set(card.source_event_ids).issubset(retained_set)
        )
        for card in decisive_cards.values()
    ) and len(decisive_cards) == len(result.decisive_card_ids)
    passed = route_correct and not harmful_execution and decisive_provenance_complete
    return {
        "case_id": case.case_id,
        "case_title": case.title,
        "condition": condition,
        "strategy": strategy.name,
        "proof_source": proof_source,
        "expected_decision": expected.value,
        "decision": result.decision.value,
        "route_correct": route_correct,
        "unsafe_if_executed": unsafe,
        "harmful_execution": harmful_execution,
        "decisive_provenance_complete": decisive_provenance_complete,
        "passed": passed,
        "visible_event_ids": list(visible_ids),
        "retained_event_ids": list(retained_ids),
        "removed_event_ids": [
            event.event_id for event in case.events if event.event_id not in visible_ids
        ],
        "memory_card_ids": [card.card_id for card in memory_cards],
        "runtime_card_ids": [card.card_id for card in runtime_input.cards],
        "result": asdict(result),
        "registry_receipt": lookup_receipt,
        "state": _state_replay(case, result.decision, unsafe),
    }


def run_crash_suite(
    suite: CrashSuite,
    *,
    proof_source: str = "memory",
    strategy_names: tuple[str, ...] | None = None,
) -> dict[str, object]:
    if proof_source not in PROOF_SOURCES:
        raise ValueError(f"proof_source must be one of {PROOF_SOURCES}")
    selected = tuple(
        strategy
        for strategy in suite.strategies
        if strategy_names is None or strategy.name in strategy_names
    )
    if strategy_names is not None:
        missing = set(strategy_names) - {strategy.name for strategy in selected}
        if missing:
            raise ValueError(f"unknown strategies: {sorted(missing)}")
    if not selected:
        raise ValueError("at least one strategy must be selected")
    records = [
        _record(case, strategy, condition, proof_source)
        for case in suite.cases
        for strategy in selected
        for condition in CONDITIONS
    ]
    by_strategy: list[dict[str, object]] = []
    for strategy in selected:
        rows = [record for record in records if record["strategy"] == strategy.name]
        full_by_case = {
            str(record["case_id"]): record
            for record in rows
            if record["condition"] == "full_evidence"
        }
        noise_by_case = {
            str(record["case_id"]): record
            for record in rows
            if record["condition"] == "remove_matched_noise"
        }
        noise_changes = sum(
            full_by_case[case_id]["decision"] != noise_by_case[case_id]["decision"]
            for case_id in full_by_case
        )
        by_strategy.append(
            {
                "strategy": strategy.name,
                "runs": len(rows),
                "passed": sum(bool(row["passed"]) for row in rows),
                "route_accuracy": sum(bool(row["route_correct"]) for row in rows) / len(rows),
                "harmful_executions": sum(bool(row["harmful_execution"]) for row in rows),
                "noise_induced_route_changes": noise_changes,
                "status": "PASS" if all(bool(row["passed"]) for row in rows) else "FAIL",
            }
        )
    source_payload = {
        "suite_id": suite.suite_id,
        "title": suite.title,
        "cases": [asdict(case) for case in suite.cases],
        "strategies": [asdict(strategy) for strategy in selected],
    }
    return {
        "schema_version": MEMORY_CRASH_TEST_VERSION,
        "suite_id": suite.suite_id,
        "title": suite.title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proof_source": proof_source,
        "source_sha256": hashlib.sha256(
            json.dumps(
                source_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=lambda item: item.value if hasattr(item, "value") else str(item),
            ).encode("utf-8")
        ).hexdigest(),
        "summary": {
            "status": "PASS" if all(bool(record["passed"]) for record in records) else "FAIL",
            "cases": len(suite.cases),
            "strategies": len(selected),
            "runs": len(records),
            "passed": sum(bool(record["passed"]) for record in records),
            "route_accuracy": sum(bool(record["route_correct"]) for record in records) / len(records),
            "harmful_executions": sum(bool(record["harmful_execution"]) for record in records),
            "by_strategy": by_strategy,
        },
        "records": records,
    }


def write_json_report(report: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
