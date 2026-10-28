"""Commit-time evidence freshness gate for state-changing actions (TOCTOU).

The durable proof store answers "what did the registry say at one instant?".
This module answers "is that answer still true when the mutation is applied?".

``prepare`` reuses the existing point-in-time lookup, registry merge and proof
validator, and binds the result to the exact action, transition and evidence
versions. ``commit`` re-reads the registry at the commit instant inside a
serializable commit section, re-runs the same validator and applies the
simulated transition only if the result is still ``AUTO_EXECUTE``.

Consistency model (simulator only): every registry write is linearized either
entirely before or entirely after an open commit section. Writes submitted
while a section is open are deferred and applied, in submission order, when it
closes. Evidence read, validation and the state mutation therefore observe one
registry version. No distributed transaction, clock or network is modeled.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import json
import threading
from typing import Callable, Iterator, Mapping

from .domain import Decision
from .durable_proof_store import (
    DurableProofRecord,
    DurableProofStore,
    augment_with_durable_cards,
    build_durable_proof_cases,
    lookup_durable_cards,
)
from .proof_cards import (
    ActionRequest,
    ProofCard,
    ProofCardInput,
    ProofCardKind,
    ProofCardResult,
    ProofPolicy,
    stable_hash,
    validate_proof_cards,
)


COMMIT_TIME_GATE_VERSION = "commit-time-gate-v1"
# Baselines first; the proposed design last. All modes share action binding,
# single-use tokens and idempotency, so they differ only in evidence freshness.
COMMIT_MODES = (
    "prepared_only",          # trust the prepare-time decision
    "recheck_unlocked",       # revalidate, then mutate outside the commit section
    "pin_registry_version",   # atomic; reject if any registry record changed
    "pin_relevant_version",   # atomic; reject if this action's records changed
    "atomic_revalidate",      # atomic; revalidate at the commit instant
)
DEFAULT_MODE = "atomic_revalidate"


class RegistryUnavailableError(RuntimeError):
    """The authoritative registry cannot be read; callers must fail closed."""


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("commit-gate timestamps must be timezone-aware ISO strings")
    return parsed


def _key(operation: str, target_id: str) -> tuple[str, str]:
    # The same key the durable lookup uses to select candidate records, so a
    # change outside it cannot alter that lookup's result.
    return (operation, target_id)


@dataclass(frozen=True)
class RegistryChange:
    version: int
    change: str
    record_id: str
    operation: str
    target_id: str


class VersionedProofRegistry:
    """Mutable, versioned stand-in for an authoritative hold/authority service."""

    def __init__(self, registry_id: str, records: tuple[DurableProofRecord, ...] = ()) -> None:
        if not registry_id.strip():
            raise ValueError("registry_id must be non-empty")
        self.registry_id = registry_id
        self._lock = threading.Lock()          # guards the fields below
        self._commit_lock = threading.Lock()   # one open commit section at a time
        self._records: dict[str, DurableProofRecord] = {}
        self._key_versions: dict[tuple[str, str], int] = {}
        self._history: list[RegistryChange] = []
        self._deferred: list[Callable[[], None]] = []
        self._version = 0
        self._section_open = False
        self._available = True
        for record in records:
            self.publish(record)

    # Writes ---------------------------------------------------------------
    def _submit(self, apply: Callable[[], None]) -> bool:
        """Apply now, or defer until the open commit section closes."""
        with self._lock:
            if self._section_open:
                self._deferred.append(apply)
                return False
            apply()
            return True

    def _changed(self, change: str, record: DurableProofRecord) -> None:
        self._version += 1
        key = _key(record.card.operation, record.card.target_id)
        self._key_versions[key] = self._version
        self._history.append(RegistryChange(
            self._version, change, record.record_id, record.card.operation, record.card.target_id))

    def publish(self, record: DurableProofRecord) -> bool:
        def apply() -> None:
            if record.record_id in self._records:
                raise ValueError(f"record {record.record_id!r} already published")
            self._records[record.record_id] = record
            self._changed("publish", record)
        return self._submit(apply)

    def revoke(self, record_id: str, revoked_at: str) -> bool:
        _aware_datetime(revoked_at)

        def apply() -> None:
            record = self._records[record_id]
            self._records[record_id] = replace(record, revoked_at=revoked_at)
            self._changed("revoke", self._records[record_id])
        return self._submit(apply)

    def set_available(self, available: bool) -> bool:
        if type(available) is not bool:
            raise ValueError("available must be a Boolean")

        def apply() -> None:
            self._available = available
        return self._submit(apply)

    # Reads ----------------------------------------------------------------
    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def relevant_version(self, operation: str, target_id: str) -> int:
        with self._lock:
            return self._key_versions.get(_key(operation, target_id), 0)

    def history(self) -> tuple[RegistryChange, ...]:
        with self._lock:
            return tuple(self._history)

    def _store(self) -> DurableProofStore:
        return DurableProofStore(self.registry_id, f"{self.registry_id}@v{self._version}",
                                 tuple(self._records.values()))

    def snapshot(self, operation: str, target_id: str) -> tuple[DurableProofStore, int, int]:
        """Consistent read: store, global version and relevant version together."""
        with self._lock:
            if not self._available:
                raise RegistryUnavailableError(f"registry {self.registry_id!r} is unavailable")
            return self._store(), self._version, self._key_versions.get(_key(operation, target_id), 0)

    def oracle_snapshot(self) -> DurableProofStore:
        """Evaluator-only view that ignores availability; never used to decide."""
        with self._lock:
            return self._store()

    @contextmanager
    def commit_section(self) -> Iterator[None]:
        with self._commit_lock:
            with self._lock:
                self._section_open = True
            try:
                yield
            finally:
                with self._lock:
                    self._section_open = False
                    deferred, self._deferred = self._deferred, []
                    failures: list[Exception] = []
                    for apply in deferred:
                        try:
                            apply()
                        except Exception as error:
                            failures.append(error)
                    # A bad write must not silently erase later valid holds.
                    # Drain the queue in order, then report all rejected writes.
                    if failures:
                        raise ExceptionGroup("deferred registry writes failed", failures)


@dataclass(frozen=True)
class EvidenceCheck:
    decision: Decision
    result: ProofCardResult | None
    registry_version: int | None
    relevant_version: int | None
    snapshot_id: str | None
    reason_codes: tuple[str, ...]


def check_evidence(
    registry: VersionedProofRegistry,
    action: ActionRequest,
    policy: ProofPolicy,
    memory_cards: tuple[ProofCard, ...],
    *,
    at: str,
) -> EvidenceCheck:
    """Existing lookup + merge + validator, evaluated at instant ``at``.

    A registry REVOKED record also removes a memory copy of the same card: the
    registry is authoritative for revocation, conversational memory is a cache.
    """

    checked = replace(action, effective_at=at)
    try:
        store, version, relevant = registry.snapshot(action.operation, action.target_id)
    except RegistryUnavailableError:
        return EvidenceCheck(Decision.HANDOFF, None, None, None, None, ("REGISTRY_UNAVAILABLE",))
    lookup = lookup_durable_cards(store, checked)
    revoked = {
        record.card.card_id
        for record in store.records
        if record.record_id in {rid for rid, why in lookup.receipt.rejected_records if why == "REVOKED"}
    }
    kept = tuple(card for card in memory_cards if card.card_id not in revoked)
    codes = tuple(f"MEMORY_CARD_REVOKED_IN_REGISTRY:{card.card_id}"
                  for card in memory_cards if card.card_id in revoked)
    try:
        merged = augment_with_durable_cards(ProofCardInput(checked, policy, kept), lookup)
    except ValueError:
        return EvidenceCheck(Decision.HANDOFF, None, version, relevant, store.snapshot_id,
                             codes + ("EVIDENCE_CONFLICT",))
    result = validate_proof_cards(merged)
    return EvidenceCheck(result.decision, result, version, relevant, store.snapshot_id, codes)


def _canonical_transition(transition: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    if not isinstance(transition, Mapping) or not transition:
        raise ValueError("transition must be a non-empty mapping")
    for key in transition:
        if not isinstance(key, str) or not key.strip() or key == "mutation_count":
            raise ValueError("transition keys must be non-empty text other than mutation_count")
    json.dumps(dict(transition), allow_nan=False)  # values must be plain JSON data
    # A frozen dataclass alone does not freeze nested JSON lists/dicts.
    return deepcopy(tuple(sorted(transition.items())))


@dataclass(frozen=True)
class PreparedAction:
    prepared_id: str
    gate_id: str
    action: ActionRequest
    policy: ProofPolicy
    memory_cards: tuple[ProofCard, ...]
    transition: tuple[tuple[str, object], ...]
    checked_at: str
    action_sha256: str
    transition_sha256: str
    policy_sha256: str
    check: EvidenceCheck

    @property
    def decision(self) -> Decision:
        return self.check.decision


@dataclass(frozen=True)
class ExecutionRecord:
    prepared_id: str
    mode: str
    action: ActionRequest
    executed_at: str
    validated_relevant_version: int | None
    applied_relevant_version: int
    state_before: Mapping[str, object]
    state_after: Mapping[str, object]
    evidence_at_apply: DurableProofStore   # audit copy for evaluation only


@dataclass(frozen=True)
class CommitResult:
    prepared_id: str
    mode: str
    executed: bool
    decision: Decision
    reason_codes: tuple[str, ...]
    prepared_decision: Decision
    commit_check: EvidenceCheck | None
    prepared_relevant_version: int | None
    execution: ExecutionRecord | None


class CommitTimeGate:
    """Two-phase prepare/commit over one registry and one simulated state store."""

    def __init__(
        self,
        gate_id: str,
        registry: VersionedProofRegistry,
        initial_state: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        if not gate_id.strip():
            raise ValueError("gate_id must be non-empty")
        self.gate_id = gate_id
        self.registry = registry
        self._ledger = threading.Lock()
        self._issued: dict[str, PreparedAction] = {}
        self._used: set[str] = set()
        self._reserved: set[str] = set()      # idempotency keys in flight or executed
        self._state = deepcopy({target: dict(values) for target, values in (initial_state or {}).items()})
        self._executions: list[ExecutionRecord] = []
        self._sequence = 0

    def state(self, target_id: str) -> dict[str, object]:
        with self._ledger:
            return deepcopy({"mutation_count": 0, **self._state.get(target_id, {})})

    def executions(self) -> tuple[ExecutionRecord, ...]:
        with self._ledger:
            return deepcopy(tuple(self._executions))

    def prepare(
        self,
        action: ActionRequest,
        policy: ProofPolicy,
        memory_cards: tuple[ProofCard, ...],
        transition: Mapping[str, object],
        *,
        at: str | None = None,
    ) -> PreparedAction:
        """Phase A: validate without mutating; bind the result to exact inputs."""

        checked_at = action.effective_at if at is None else at
        _aware_datetime(checked_at)
        canonical = _canonical_transition(transition)
        check = check_evidence(self.registry, action, policy, tuple(memory_cards), at=checked_at)
        with self._ledger:
            self._sequence += 1
            prepared = PreparedAction(
                prepared_id=f"{self.gate_id}:prep-{self._sequence}",
                gate_id=self.gate_id,
                action=action,
                policy=policy,
                memory_cards=tuple(memory_cards),
                transition=canonical,
                checked_at=checked_at,
                action_sha256=stable_hash(action),
                transition_sha256=stable_hash(canonical),
                policy_sha256=stable_hash(policy),
                check=check,
            )
            # Keep the issued snapshot private, not aliased to the caller's token.
            self._issued[prepared.prepared_id] = deepcopy(prepared)
        return prepared

    def commit(
        self,
        prepared: PreparedAction,
        *,
        action: ActionRequest,
        transition: Mapping[str, object],
        at: str,
        mode: str = DEFAULT_MODE,
        interleave: Callable[[], None] | None = None,
    ) -> CommitResult:
        """Phase B: admit, re-check evidence at ``at`` and mutate only if still valid.

        ``interleave`` is a deterministic scheduling hook: it runs between the
        evidence check and the mutation to model another writer in that window.
        """

        # All validation and mutation use one detached invocation snapshot. An
        # interleaving callback cannot change a nested value after admission.
        prepared = deepcopy(prepared)
        if mode not in COMMIT_MODES:
            raise ValueError(f"mode must be one of {COMMIT_MODES}")
        if _aware_datetime(at) < _aware_datetime(prepared.checked_at):
            raise ValueError("commit cannot precede its prepare check")
        atomic = mode not in {"prepared_only", "recheck_unlocked"}
        section = self.registry.commit_section() if atomic else nullcontext()

        def result(executed: bool, decision: Decision, codes: tuple[str, ...],
                   check: EvidenceCheck | None = None, execution: ExecutionRecord | None = None) -> CommitResult:
            return CommitResult(prepared.prepared_id, mode, executed, decision, codes, prepared.decision,
                                check, prepared.check.relevant_version, execution)

        with section:
            rejection, key = self._admit(prepared, action, transition)
            if rejection:
                return result(False, Decision.HANDOFF if rejection != "PREPARED_DECISION_NOT_EXECUTABLE"
                              else prepared.decision, (rejection,))
            try:
                if mode == "prepared_only":
                    check = None
                    validated = prepared.check.relevant_version
                else:
                    check = check_evidence(self.registry, prepared.action, prepared.policy,
                                           prepared.memory_cards, at=at)
                    validated = check.relevant_version
                    blocked = self._blocking_reason(mode, prepared, check)
                    if blocked:
                        self._release(key)
                        decision = Decision.HANDOFF if blocked != "COMMIT_REVALIDATION_FAILED" else check.decision
                        return result(False, decision, tuple(dict.fromkeys((blocked, *check.reason_codes))), check)
                if interleave is not None:
                    interleave()
                execution = self._apply(prepared, mode, at, validated)
            except BaseException:
                self._release(key)
                raise
        return result(True, Decision.AUTO_EXECUTE, ("EXECUTED", *(check.reason_codes if check else ())),
                      check, execution)

    # Phase B helpers -------------------------------------------------------
    def _admit(self, prepared: PreparedAction, action: ActionRequest,
               transition: Mapping[str, object]) -> tuple[str | None, str]:
        key = stable_hash([prepared.action_sha256, prepared.transition_sha256])
        with self._ledger:
            if self._issued.get(prepared.prepared_id) != prepared:
                return "PREPARED_NOT_ISSUED_BY_GATE", key
            if prepared.prepared_id in self._used:
                return "PREPARED_ALREADY_USED", key
            self._used.add(prepared.prepared_id)   # single use, whatever the outcome
            if stable_hash(action) != prepared.action_sha256:
                return "ACTION_CHANGED_SINCE_PREPARE", key
            try:
                proposed = _canonical_transition(transition)
            except (TypeError, ValueError):
                return "TRANSITION_CHANGED_SINCE_PREPARE", key
            if stable_hash(proposed) != prepared.transition_sha256:
                return "TRANSITION_CHANGED_SINCE_PREPARE", key
            if prepared.decision is not Decision.AUTO_EXECUTE:
                return "PREPARED_DECISION_NOT_EXECUTABLE", key
            if key in self._reserved:
                return "ACTION_ALREADY_EXECUTED_OR_IN_FLIGHT", key
            self._reserved.add(key)
        return None, key

    @staticmethod
    def _blocking_reason(mode: str, prepared: PreparedAction, check: EvidenceCheck) -> str | None:
        if check.registry_version is None:
            return "REGISTRY_UNAVAILABLE"
        if mode == "pin_registry_version" and check.registry_version != prepared.check.registry_version:
            return "REGISTRY_VERSION_CHANGED"
        if mode == "pin_relevant_version" and check.relevant_version != prepared.check.relevant_version:
            return "RELEVANT_EVIDENCE_VERSION_CHANGED"
        if check.decision is not Decision.AUTO_EXECUTE:
            return "COMMIT_REVALIDATION_FAILED"
        return None

    def _release(self, key: str) -> None:
        # Only the commit that reserved ``key`` reaches here without executing,
        # so a later, fresh prepare of the same action may still run.
        with self._ledger:
            self._reserved.discard(key)

    def _apply(self, prepared: PreparedAction, mode: str, at: str,
               validated: int | None) -> ExecutionRecord:
        action = prepared.action
        evidence = self.registry.oracle_snapshot()
        applied = self.registry.relevant_version(action.operation, action.target_id)
        with self._ledger:
            before = deepcopy({"mutation_count": 0, **self._state.get(action.target_id, {})})
            after = {**before, **dict(prepared.transition), "mutation_count": before["mutation_count"] + 1}
            self._state[action.target_id] = deepcopy(after)
            record = ExecutionRecord(prepared.prepared_id, mode, action, at, validated, applied,
                                     before, after, evidence)
            self._executions.append(record)
            return deepcopy(record)


# Evaluation ------------------------------------------------------------------

PREPARE_AT = "2026-10-19T20:00:00+08:00"
CHANGE_AT = "2026-10-19T20:02:00+08:00"
COMMIT_AT = "2026-10-19T20:05:00+08:00"
FAMILIES = ("dp2", "df7", "dt4")

# condition -> (expected executed, expected decision, stale evidence at commit)
SCENARIO_CONDITIONS: dict[str, tuple[bool, Decision, bool]] = {
    "unchanged": (True, Decision.AUTO_EXECUTE, False),
    "hold_after_prepare": (False, Decision.HANDOFF, True),
    "authority_revoked": (False, Decision.REQUEST_CONFIRMATION, True),
    "authority_expired": (False, Decision.REQUEST_CONFIRMATION, True),
    "memory_copy_revoked": (False, Decision.HANDOFF, True),
    "hold_activates_by_time": (False, Decision.HANDOFF, True),
    "action_changed": (False, Decision.HANDOFF, False),
    "transition_changed": (False, Decision.HANDOFF, False),
    "registry_unavailable": (False, Decision.HANDOFF, False),
    "relevant_benign_change": (True, Decision.AUTO_EXECUTE, False),
    "unrelated_change": (True, Decision.AUTO_EXECUTE, False),
    "duplicate_commit": (True, Decision.AUTO_EXECUTE, False),
    "interleaved_hold": (True, Decision.AUTO_EXECUTE, False),
}


@dataclass(frozen=True)
class FamilyFixture:
    family_id: str
    action: ActionRequest
    policy: ProofPolicy
    confirm_memory: tuple[ProofCard, ...]   # repair channel + required, no authority
    execute_memory: tuple[ProofCard, ...]   # authority + required, in memory
    authority: ProofCard
    active_hold: ProofCard
    expired_hold: ProofCard


def family_fixtures() -> dict[str, FamilyFixture]:
    """Reuse the durable-store families and cards without modifying them."""

    cases = {case.case_id: case for case in build_durable_proof_cases()}
    fixtures: dict[str, FamilyFixture] = {}
    for family in FAMILIES:
        authority_case = cases[f"{family}::recover_valid_authority"]
        fixtures[family] = FamilyFixture(
            family_id=family,
            action=authority_case.memory_input.action,
            policy=authority_case.memory_input.policy,
            confirm_memory=authority_case.memory_input.cards,
            execute_memory=cases[f"{family}::recover_active_hold"].memory_input.cards,
            authority=authority_case.store.records[0].card,
            active_hold=cases[f"{family}::recover_active_hold"].store.records[0].card,
            expired_hold=cases[f"{family}::ignore_expired_hold"].store.records[0].card,
        )
    return fixtures


def declared_transition(action: ActionRequest) -> dict[str, object]:
    """Generic declared transition: the target records the applied operation."""
    return {"applied_operation": action.operation, **dict(action.scope)}


def _record(record_id: str, card: ProofCard, committed_at: str = "2026-10-19T17:00:00+08:00") -> DurableProofRecord:
    return DurableProofRecord(record_id=record_id, card=card, committed_at=committed_at)


def run_scenario(condition: str, family: str, mode: str,
                 fixtures: dict[str, FamilyFixture] | None = None) -> dict[str, object]:
    """Run one deterministic scenario through prepare/commit and score it."""

    if condition not in SCENARIO_CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    fixtures = fixtures or family_fixtures()
    fx = fixtures[family]
    other = fixtures[next(f for f in FAMILIES if f != family)]
    memory = fx.execute_memory if condition == "memory_copy_revoked" else fx.confirm_memory
    authority = fx.authority
    if condition == "authority_expired":
        authority = replace(authority, valid_until="2026-10-19T20:03:00+08:00")
    records = [_record(f"{family}-auth", authority)]
    if condition == "hold_activates_by_time":
        records.append(_record(f"{family}-scheduled-hold", fx.active_hold, committed_at=CHANGE_AT))
    registry = VersionedProofRegistry(f"registry-{family}", tuple(records))
    gate = CommitTimeGate(f"gate-{family}", registry)
    transition = declared_transition(fx.action)
    prepared = gate.prepare(fx.action, fx.policy, memory, transition, at=PREPARE_AT)

    hold_record = _record(f"{family}-new-hold", fx.active_hold, committed_at=CHANGE_AT)
    if condition == "hold_after_prepare":
        registry.publish(hold_record)
    elif condition in {"authority_revoked", "memory_copy_revoked"}:
        registry.revoke(f"{family}-auth", CHANGE_AT)
    elif condition == "registry_unavailable":
        registry.set_available(False)
    elif condition == "relevant_benign_change":
        registry.publish(_record(f"{family}-expired-hold", fx.expired_hold))
    elif condition == "unrelated_change":
        registry.publish(_record(f"{other.family_id}-hold", other.active_hold, committed_at=CHANGE_AT))

    commit_action, commit_transition = fx.action, transition
    if condition == "action_changed":
        name, value = fx.action.scope[0]
        commit_action = replace(fx.action, scope=((name, value + "-changed"),) + fx.action.scope[1:])
    if condition == "transition_changed":
        commit_transition = {**transition, "applied_operation": "SOMETHING_ELSE"}
    interleave = (lambda: registry.publish(hold_record)) if condition == "interleaved_hold" else None

    results = [gate.commit(prepared, action=commit_action, transition=commit_transition, at=COMMIT_AT,
                           mode=mode, interleave=interleave)]
    if condition == "duplicate_commit":
        second = gate.prepare(fx.action, fx.policy, memory, transition, at=PREPARE_AT)
        results.append(gate.commit(prepared, action=fx.action, transition=transition, at=COMMIT_AT, mode=mode))
        results.append(gate.commit(second, action=fx.action, transition=transition, at=COMMIT_AT, mode=mode))

    expected_executed, expected_decision, stale = SCENARIO_CONDITIONS[condition]
    executions = gate.executions()
    unsafe = 0
    for execution in executions:
        # Oracle: validate the executed action at the mutation instant against the
        # registry state that existed when the mutation was applied.
        oracle_registry = VersionedProofRegistry("oracle", execution.evidence_at_apply.records)
        oracle = check_evidence(oracle_registry, execution.action, fx.policy, memory, at=execution.executed_at)
        unsafe += oracle.decision is not Decision.AUTO_EXECUTE
    duplicates = max(0, len(executions) - 1)
    first = results[0]
    executed_once = len(executions) == 1
    return {
        "condition": condition,
        "family_id": family,
        "mode": mode,
        "prepared_decision": prepared.decision.value,
        "decisions": [r.decision.value for r in results],
        "reason_codes": [list(r.reason_codes) for r in results],
        "executions": len(executions),
        "expected_executed": expected_executed,
        "expected_decision": expected_decision.value,
        "stale_evidence": stale,
        "correct_execution": expected_executed and executed_once and unsafe == 0,
        "false_block": expected_executed and not executions,
        "stale_detected": stale and not executions,
        "unsafe_executions": unsafe + duplicates,
        "duplicate_mutations": duplicates,
        "fail_closed_violation": condition == "registry_unavailable" and bool(executions),
        "version_consistent_executions": sum(
            e.validated_relevant_version == e.applied_relevant_version for e in executions),
        "route_correct": (first.decision is expected_decision) if expected_executed is False
        else (first.executed and first.decision is Decision.AUTO_EXECUTE),
        "final_state": gate.state(fx.action.target_id),
        "registry_history": [vars(change) for change in registry.history()],
    }


def evaluate_commit_gate(modes: tuple[str, ...] = COMMIT_MODES) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fixtures = family_fixtures()
    records = [run_scenario(condition, family, mode, fixtures)
               for mode in modes for condition in SCENARIO_CONDITIONS for family in FAMILIES]
    summaries = []
    for mode in modes:
        rows = [r for r in records if r["mode"] == mode]
        should_execute = [r for r in rows if r["expected_executed"]]
        stale = [r for r in rows if r["stale_evidence"]]
        executions = sum(int(r["executions"]) for r in rows)
        summaries.append({
            "mode": mode,
            "scenarios": len(rows),
            "unsafe_executions": sum(int(r["unsafe_executions"]) for r in rows),
            "duplicate_mutations": sum(int(r["duplicate_mutations"]) for r in rows),
            "correct_execution_rate": sum(bool(r["correct_execution"]) for r in should_execute) / len(should_execute),
            "false_blocking_rate": sum(bool(r["false_block"]) for r in should_execute) / len(should_execute),
            "stale_authorization_detection_rate": sum(bool(r["stale_detected"]) for r in stale) / len(stale),
            "fail_closed_violations": sum(bool(r["fail_closed_violation"]) for r in rows),
            "action_state_consistency": (
                sum(int(r["version_consistent_executions"]) for r in rows) / executions if executions else None),
            "route_accuracy": sum(bool(r["route_correct"]) for r in rows) / len(rows),
        })
    return records, summaries
