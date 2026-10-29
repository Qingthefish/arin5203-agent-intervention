"""Closed-loop handling of REQUEST_CONFIRMATION for proof-card actions.

``validate_proof_cards`` already decides when a missing authority can be
repaired: an applicable ``REPAIR_CHANNEL`` card names a responder listed in
``ProofPolicy.confirmable_authority_actors``. Nothing at run time consumes that
decision. ``intervention.resolve_after_confirmation`` is an evaluator-side
counterfactual that builds a perfect approval from private oracle requirements;
it never validates a real reply.

This module adds the missing lifecycle as a small deterministic state machine:

    validator says REQUEST_CONFIRMATION
      -> request bound to one action and one authorized responder
      -> structured responses checked (identity, authority, binding, time, state)
      -> an accepted approval becomes one AUTHORITY proof card with provenance
      -> the unchanged validator re-runs on evidence read at execution time
      -> execute once, or stop, or escalate (Handoff)

States: ``PENDING_CONFIRMATION`` and ``CONFIRMED`` are open. ``COMPLETED``,
``REJECTED``, ``EXPIRED``, ``CANCELLED`` and ``ESCALATED`` are terminal.
``ESCALATED`` means the existing Handoff route; no new route is added.

Trust model (simulation only). A response is attributed to the principal bound
to its delivery channel in a ``ResponderDirectory`` fixture. Identity, role or
"verified" fields inside the response body are recorded but never trusted. This
stands in for an authenticated session; it is not real identity verification.

Time is a logical clock owned by the workflow. Callers advance it forward only.
Response timestamps are never read, so a backdated reply cannot beat a deadline.

Consistency boundary. The default ledger mutates in one synchronous simulator
call, after an optional ``pre_commit_check`` hook. A trusted ``executor`` can
replace that ledger, so the commit-time gate owns the only mutation. Custom
execution requires all workflow checks. Neither path guarantees atomicity
against a real external system; production tools need their own boundary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum

from .domain import Decision
from .durable_proof_store import DurableProofStore, lookup_durable_cards
from .proof_cards import (
    ActionRequest,
    ProofCard,
    ProofCardInput,
    ProofCardKind,
    ProofCardResult,
    ProofPolicy,
    _card_applies,
    stable_hash,
    validate_proof_cards,
)


HUMAN_INTERVENTION_VERSION = "human-intervention-v1.3"


class RequestState(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


OPEN_STATES = frozenset({RequestState.PENDING_CONFIRMATION, RequestState.CONFIRMED})


class ResponseDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CLARIFY = "CLARIFY"


class EvidenceUnavailable(RuntimeError):
    """Raised by an evidence provider that cannot answer; the workflow fails closed."""

    def __init__(self, message: str = "", *, reason_code: str = "EVIDENCE_SOURCE_UNAVAILABLE") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class MutationOutcomeUnknown(RuntimeError):
    """No authoritative mutation result is available; do not resume automatically."""


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("workflow timestamps must be timezone-aware ISO strings")
    return parsed


@dataclass(frozen=True)
class ActionBinding:
    """What a confirmation approves. ``effective_at`` is excluded on purpose:
    evidence is evaluated at the workflow clock when the action is executed."""

    actor_id: str
    operation: str
    target_id: str
    scope: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, action: ActionRequest) -> ActionBinding:
        return cls(action.actor_id, action.operation, action.target_id,
                   tuple(sorted(action.scope)))

    @property
    def sha256(self) -> str:
        return stable_hash(self)


@dataclass(frozen=True)
class TrustedChannel:
    channel_id: str
    principal_id: str


@dataclass(frozen=True)
class ResponderDirectory:
    """Simulated authenticated channels. Not a real identity system."""

    channels: tuple[TrustedChannel, ...]

    def __post_init__(self) -> None:
        ids = [c.channel_id for c in self.channels]
        if len(ids) != len(set(ids)):
            raise ValueError("channel IDs must be unique")

    def principal(self, channel_id: str) -> str | None:
        return next((c.principal_id for c in self.channels if c.channel_id == channel_id), None)

    def channel_for(self, principal_id: str) -> str | None:
        return next((c.channel_id for c in self.channels if c.principal_id == principal_id), None)


@dataclass(frozen=True)
class ConfirmationRequest:
    request_id: str
    binding: ActionBinding
    action_sha256: str
    missing_obligation: str
    supplies: str
    responder_id: str
    delivery_channel_id: str
    repair_card_ids: tuple[str, ...]
    issued_at: str
    expires_at: str
    challenge: str
    message: str


@dataclass(frozen=True)
class HumanResponse:
    """A structured reply. Only ``channel_id`` is used for identity."""

    response_id: str
    request_id: str
    channel_id: str
    decision: ResponseDecision
    challenge: str
    action_sha256: str
    operation: str
    target_id: str
    scope: tuple[tuple[str, str], ...]
    claimed_responder_id: str | None = None
    claimed_verified: bool = False
    claimed_sent_at: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ResponseDecision):
            raise ValueError("decision must be a ResponseDecision enum value")


@dataclass(frozen=True)
class EvidenceSnapshot:
    policy: ProofPolicy
    cards: tuple[ProofCard, ...]
    source_receipt: str = ""


EvidenceProvider = Callable[[ActionRequest], EvidenceSnapshot]


@dataclass(frozen=True)
class MutationResult:
    """Outcome from the trusted mutation adapter; not a model-generated claim."""

    executed: bool
    reason: str
    state_diff: tuple[tuple[str, str, str], ...] = ()
    decisive_card_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


MutationExecutor = Callable[
    [ActionRequest, ProofPolicy, tuple[ProofCard, ...], str], MutationResult
]


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: str
    request_id: str | None
    event: str
    outcome: str
    reason: str
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class StartOutcome:
    decision: Decision
    validation: ProofCardResult | None
    request: ConfirmationRequest | None
    reason: str


@dataclass(frozen=True)
class ResponseOutcome:
    accepted: bool
    reason: str
    state: RequestState | None


@dataclass(frozen=True)
class ExecutionReceipt:
    request_id: str
    action_sha256: str
    executed_at: str
    state_diff: tuple[tuple[str, str, str], ...]
    decisive_card_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionOutcome:
    executed: bool
    reason: str
    state: RequestState | None
    validation: ProofCardResult | None = None
    receipt: ExecutionReceipt | None = None


@dataclass(frozen=True)
class ProtocolChecks:
    """All checks are on by default. Switching one off exists only for the
    ablation study in ``scripts/run_human_intervention_evaluation.py``."""

    authenticate_channel: bool = True
    enforce_responder_authority: bool = True
    bind_action: bool = True
    enforce_time: bool = True
    revalidate_evidence: bool = True
    deduplicate: bool = True


# ---------------------------------------------------------------------------
# Evidence and simulated side effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineEvidenceProvider:
    """Evidence at a point in time: a policy timeline, static cards, and an
    optional durable store queried with the existing point-in-time lookup."""

    policy_versions: tuple[tuple[str, ProofPolicy], ...]
    static_cards: tuple[ProofCard, ...] = ()
    store: DurableProofStore | None = None
    outages: tuple[tuple[str, str], ...] = ()

    def __call__(self, action: ActionRequest) -> EvidenceSnapshot:
        moment = _aware(action.effective_at)
        if any(_aware(start) <= moment < _aware(end) for start, end in self.outages):
            raise EvidenceUnavailable("evidence source unavailable at " + action.effective_at)
        active = [p for start, p in self.policy_versions if _aware(start) <= moment]
        if not active:
            raise EvidenceUnavailable("no policy in force at " + action.effective_at)
        cards = list(self.static_cards)
        receipt = "static"
        if self.store is not None:
            lookup = lookup_durable_cards(self.store, action)
            cards.extend(lookup.cards)
            receipt = f"{self.store.store_id}:{','.join(lookup.receipt.returned_record_ids)}"
        return EvidenceSnapshot(active[-1], tuple(cards), receipt)


@dataclass
class SimulatedActionLedger:
    """Applies a declared state transition, at most once per action binding."""

    state: dict[str, object]
    transitions: Mapping[str, Mapping[str, object]]
    deduplicate: bool = True
    applied: list[str] = field(default_factory=list)

    def apply(self, action_sha256: str) -> tuple[tuple[str, str, str], ...]:
        if self.deduplicate and action_sha256 in self.applied:
            raise RuntimeError("action binding already executed")
        after = self.transitions.get(action_sha256)
        if after is None:
            raise KeyError("no declared transition for this action binding")
        diff = tuple(
            (key, repr(self.state.get(key)), repr(value))
            for key, value in sorted(after.items()) if self.state.get(key) != value
        )
        self.state.update(after)
        self.applied.append(action_sha256)
        return diff

    def mutations(self, action_sha256: str) -> int:
        return self.applied.count(action_sha256)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@dataclass
class _Record:
    request: ConfirmationRequest
    action: ActionRequest
    state: RequestState
    approval_card: ProofCard | None = None
    approved_by_response: str | None = None
    receipt: ExecutionReceipt | None = None
    terminal_reason: str = ""
    execution_unknown: bool = False


class InterventionWorkflow:
    def __init__(
        self,
        provider: EvidenceProvider,
        directory: ResponderDirectory,
        ledger: SimulatedActionLedger | None = None,
        *,
        start_time: str,
        confirmation_issuer: str,
        request_ttl: timedelta = timedelta(minutes=30),
        approval_ttl: timedelta = timedelta(minutes=15),
        challenge_seed: str = "simulation-seed",
        checks: ProtocolChecks = ProtocolChecks(),
        pre_commit_check: Callable[[ActionRequest, ProofCardResult], str | None] | None = None,
        executor: MutationExecutor | None = None,
    ) -> None:
        if (ledger is None) == (executor is None):
            raise ValueError("supply exactly one of ledger or executor")
        if executor is not None and checks != ProtocolChecks():
            raise ValueError("a mutation executor requires every workflow check enabled")
        self._provider = provider
        self._directory = directory
        self._ledger = ledger
        self._executor = executor
        self._now = _aware(start_time)
        self._issuer = confirmation_issuer
        self._request_ttl = request_ttl
        self._approval_ttl = approval_ttl
        self._seed = challenge_seed
        self.checks = checks
        self._pre_commit = pre_commit_check
        self._records: dict[str, _Record] = {}
        self._responses: dict[str, ResponseOutcome] = {}
        self.audit: list[AuditEntry] = []

    # -- clock and audit ----------------------------------------------------

    @property
    def now(self) -> str:
        return self._now.isoformat()

    def advance_to(self, moment: str) -> None:
        target = _aware(moment)
        if target < self._now:
            raise ValueError("the logical clock cannot move backwards")
        self._now = target
        self._expire_due()

    def _log(self, request_id: str | None, event: str, outcome: str, reason: str,
             **details: object) -> None:
        self.audit.append(AuditEntry(
            len(self.audit) + 1, self.now, request_id, event, outcome, reason,
            tuple(sorted((k, str(v)) for k, v in details.items())),
        ))

    def _expire_due(self) -> None:
        if not self.checks.enforce_time:
            return
        for record in self._records.values():
            if record.state is RequestState.PENDING_CONFIRMATION and self._now > _aware(
                record.request.expires_at
            ):
                self._close(record, RequestState.EXPIRED, "REQUEST_EXPIRED_WITHOUT_VALID_RESPONSE")
            elif record.state is RequestState.CONFIRMED and record.approval_card and (
                self._now > _aware(record.approval_card.valid_until)
            ):
                self._close(record, RequestState.EXPIRED, "APPROVAL_STALE_BEFORE_EXECUTION")

    def _close(self, record: _Record, state: RequestState, reason: str) -> None:
        record.state = state
        record.terminal_reason = reason
        self._log(record.request.request_id, "STATE", state.value, reason)

    def state_of(self, request_id: str) -> RequestState:
        return self._records[request_id].state

    def record_summary(self, request_id: str) -> dict[str, object]:
        record = self._records[request_id]
        return {"state": record.state.value, "reason": record.terminal_reason,
                "approved_by_response": record.approved_by_response,
                "approval_card_id": record.approval_card.card_id if record.approval_card else None,
                "executed": None if record.execution_unknown
                else record.receipt is not None}

    # -- evidence -------------------------------------------------------------

    def _evidence(self, action: ActionRequest) -> tuple[ActionRequest, EvidenceSnapshot]:
        at_now = replace(action, effective_at=self.now)
        return at_now, self._provider(at_now)

    # -- phase 1: request creation ------------------------------------------

    def request_confirmation(self, action: ActionRequest, *,
                             responder_id: str | None = None) -> StartOutcome:
        try:
            at_now, snapshot = self._evidence(action)
        except EvidenceUnavailable as exc:
            self._log(None, "START", "NO_REQUEST", exc.reason_code, error=exc)
            return StartOutcome(Decision.HANDOFF, None, None, exc.reason_code)
        result = validate_proof_cards(ProofCardInput(at_now, snapshot.policy, snapshot.cards))
        if result.decision is not Decision.REQUEST_CONFIRMATION:
            # Execute needs no confirmation; Handoff is never converted into one.
            self._log(None, "START", "NO_REQUEST", f"ROUTE_{result.decision.value}")
            return StartOutcome(result.decision, result, None, f"ROUTE_{result.decision.value}")
        if self._issuer not in snapshot.policy.authority_issuers:
            self._log(None, "START", "NO_REQUEST", "CONFIRMATION_ISSUER_NOT_TRUSTED_BY_POLICY")
            return StartOutcome(Decision.HANDOFF, result, None,
                                "CONFIRMATION_ISSUER_NOT_TRUSTED_BY_POLICY")
        repairs = self._repair_cards(at_now, snapshot)
        authorized = sorted({card.subject_id for card in repairs})
        chosen = responder_id if responder_id is not None else authorized[0]
        if chosen not in authorized:
            self._log(None, "START", "NO_REQUEST", "ADDRESSEE_NOT_AUTHORIZED_FOR_GAP",
                      addressee=chosen)
            return StartOutcome(Decision.HANDOFF, result, None, "ADDRESSEE_NOT_AUTHORIZED_FOR_GAP")
        channel = self._directory.channel_for(chosen)
        if channel is None:
            self._log(None, "START", "NO_REQUEST", "NO_TRUSTED_CHANNEL_FOR_RESPONDER")
            return StartOutcome(Decision.HANDOFF, result, None, "NO_TRUSTED_CHANNEL_FOR_RESPONDER")

        binding = ActionBinding.of(action)
        request_id = f"hir-{len(self._records) + 1:04d}"
        challenge = hashlib.sha256(
            f"{self._seed}:{request_id}:{binding.sha256}".encode("utf-8")
        ).hexdigest()[:16]
        scope_text = ", ".join(f"{k}={v}" for k, v in binding.scope)
        supplies = (f"AUTHORITY for {binding.actor_id} to {binding.operation} on "
                    f"{binding.target_id} with {scope_text}")
        request = ConfirmationRequest(
            request_id=request_id, binding=binding, action_sha256=binding.sha256,
            missing_obligation="authority", supplies=supplies, responder_id=chosen,
            delivery_channel_id=channel,
            repair_card_ids=tuple(c.card_id for c in repairs if c.subject_id == chosen),
            issued_at=self.now, expires_at=(self._now + self._request_ttl).isoformat(),
            challenge=challenge,
            message=(f"{chosen}: please approve or reject exactly this action. Missing "
                     f"obligation: {supplies}. Request {request_id}, expires "
                     f"{(self._now + self._request_ttl).isoformat()}."),
        )
        self._records[request_id] = _Record(request, action, RequestState.PENDING_CONFIRMATION)
        self._log(request_id, "START", RequestState.PENDING_CONFIRMATION.value,
                  "AUTHORITY_REPAIRABLE_GAP", responder=chosen, action_sha256=binding.sha256)
        return StartOutcome(result.decision, result, request, "REQUEST_ISSUED")

    @staticmethod
    def _repair_cards(action: ActionRequest, snapshot: EvidenceSnapshot) -> list[ProofCard]:
        return [c for c in snapshot.cards if c.kind is ProofCardKind.REPAIR_CHANNEL
                and _card_applies(c, action, snapshot.policy)]

    # -- phases 2 and 3: response reception and validation -------------------

    def receive(self, response: HumanResponse) -> ResponseOutcome:
        if self.checks.deduplicate and response.response_id in self._responses:
            record = self._records.get(response.request_id)
            self._log(response.request_id, "RESPONSE", "IGNORED", "DUPLICATE_RESPONSE",
                      response_id=response.response_id)
            return ResponseOutcome(False, "DUPLICATE_RESPONSE",
                                   record.state if record else None)
        outcome = self._validate_and_apply(response)
        self._responses[response.response_id] = outcome
        self._log(response.request_id, "RESPONSE", "ACCEPTED" if outcome.accepted else "REJECTED",
                  outcome.reason, response_id=response.response_id,
                  decision=response.decision.value,
                  claimed_responder=response.claimed_responder_id,
                  claimed_verified=response.claimed_verified)
        return outcome

    def _validate_and_apply(self, response: HumanResponse) -> ResponseOutcome:
        record = self._records.get(response.request_id)
        if record is None:
            return ResponseOutcome(False, "UNKNOWN_REQUEST", None)
        request = record.request

        if self.checks.authenticate_channel:
            principal = self._directory.principal(response.channel_id)
            if principal is None:
                return ResponseOutcome(False, "UNAUTHENTICATED_CHANNEL", record.state)
            if response.claimed_responder_id not in (None, principal):
                return ResponseOutcome(False, "CLAIMED_IDENTITY_DIFFERS_FROM_CHANNEL", record.state)
        else:
            principal = response.claimed_responder_id or self._directory.principal(
                response.channel_id) or "unknown"

        if self.checks.bind_action:
            if response.challenge != request.challenge:
                return ResponseOutcome(False, "CHALLENGE_MISMATCH_POSSIBLE_REPLAY", record.state)
            if response.operation != request.binding.operation:
                return ResponseOutcome(False, "OPERATION_MISMATCH", record.state)
            if response.target_id != request.binding.target_id:
                return ResponseOutcome(False, "TARGET_MISMATCH", record.state)
            if tuple(sorted(response.scope)) != request.binding.scope:
                return ResponseOutcome(False, "SCOPE_MISMATCH", record.state)
            if response.action_sha256 != request.action_sha256:
                return ResponseOutcome(False, "ACTION_HASH_MISMATCH", record.state)

        if record.state not in OPEN_STATES:
            return ResponseOutcome(False, f"REQUEST_NOT_OPEN_{record.state.value}", record.state)

        if self.checks.enforce_responder_authority:
            if principal != request.responder_id:
                return ResponseOutcome(False, "RESPONDER_NOT_ADDRESSED", record.state)
            try:
                at_now, snapshot = self._evidence(record.action)
            except EvidenceUnavailable as exc:
                self._close(record, RequestState.ESCALATED, exc.reason_code)
                return ResponseOutcome(False, exc.reason_code, record.state)
            if principal not in {c.subject_id for c in self._repair_cards(at_now, snapshot)}:
                self._close(record, RequestState.ESCALATED, "RESPONDER_AUTHORITY_LAPSED")
                return ResponseOutcome(False, "RESPONDER_AUTHORITY_LAPSED", record.state)

        decision = response.decision
        if record.state is RequestState.CONFIRMED:
            if decision is ResponseDecision.APPROVE:
                return ResponseOutcome(False, "ALREADY_CONFIRMED", record.state)
            # A later rejection or question never silently loses to an approval.
            self._close(record, RequestState.ESCALATED, "CONFLICTING_RESPONSES")
            return ResponseOutcome(True, "CONFLICTING_RESPONSES", record.state)
        if decision is ResponseDecision.REJECT:
            self._close(record, RequestState.REJECTED, "RESPONDER_REJECTED")
            return ResponseOutcome(True, "RESPONDER_REJECTED", record.state)
        if decision is ResponseDecision.CLARIFY:
            return ResponseOutcome(True, "CLARIFICATION_REQUESTED", record.state)

        valid_until = self._now + self._approval_ttl
        record.approval_card = ProofCard(
            card_id=f"hic-{request.request_id}-{response.response_id}",
            kind=ProofCardKind.AUTHORITY,
            source_event_ids=(request.request_id, response.response_id),
            issuer_id=self._issuer,
            subject_id=request.binding.actor_id,
            operation=request.binding.operation,
            target_id=request.binding.target_id,
            scope=request.binding.scope,
            valid_from=self.now,
            valid_until=valid_until.isoformat(),
            # True only inside the simulated trust model (channel-bound principal).
            authenticated=True,
        )
        record.approved_by_response = response.response_id
        record.state = RequestState.CONFIRMED
        return ResponseOutcome(True, "APPROVAL_RECORDED", record.state)

    def cancel(self, request_id: str, reason: str = "CANCELLED_BY_REQUESTER") -> RequestState:
        record = self._records[request_id]
        if record.state in OPEN_STATES:
            self._close(record, RequestState.CANCELLED, reason)
        return record.state

    # -- phases 4 and 5: revalidation and simulated execution ---------------

    def execute(self, request_id: str, action: ActionRequest) -> ExecutionOutcome:
        record = self._records.get(request_id)
        if record is None:
            return self._refuse(request_id, "UNKNOWN_REQUEST", None)
        if record.state is RequestState.COMPLETED and self.checks.deduplicate:
            return self._refuse(request_id, "ALREADY_EXECUTED", record.state)
        reexecution = record.state is RequestState.COMPLETED and not self.checks.deduplicate
        if record.state is not RequestState.CONFIRMED and not reexecution:
            return self._refuse(request_id, f"NOT_CONFIRMED_{record.state.value}", record.state)
        if self.checks.bind_action and ActionBinding.of(action) != record.request.binding:
            return self._refuse(request_id, "ACTION_CHANGED_REAUTHORIZATION_REQUIRED", record.state)
        assert record.approval_card is not None

        validation: ProofCardResult | None = None
        decisive: tuple[str, ...] = (record.approval_card.card_id,)
        if self.checks.revalidate_evidence:
            try:
                at_now, snapshot = self._evidence(action)
            except EvidenceUnavailable as exc:
                self._close(record, RequestState.ESCALATED, exc.reason_code)
                return ExecutionOutcome(False, exc.reason_code, record.state)
            validation = validate_proof_cards(ProofCardInput(
                at_now, snapshot.policy, snapshot.cards + (record.approval_card,)))
            if validation.decision is not Decision.AUTO_EXECUTE:
                reason = ("CONFIRMATION_DID_NOT_RESOLVE_GAP"
                          if validation.decision is Decision.REQUEST_CONFIRMATION
                          else "REVALIDATION_" + "+".join(
                              c for c in validation.reason_codes
                              if c.endswith(("MISSING", "BLOCKED"))))
                self._close(record, RequestState.ESCALATED, reason)
                return ExecutionOutcome(False, reason, record.state, validation)
            decisive = validation.decisive_card_ids
            if self._pre_commit is not None:
                blocked = self._pre_commit(at_now, validation)
                if blocked:
                    self._close(record, RequestState.ESCALATED, "PRE_COMMIT_CHECK_" + blocked)
                    return ExecutionOutcome(False, "PRE_COMMIT_CHECK_" + blocked, record.state,
                                            validation)

        completion_reason = ("EXECUTED_AFTER_REVALIDATION" if self.checks.revalidate_evidence
                             else "EXECUTED_WITHOUT_REVALIDATION")
        if self._executor is not None:
            try:
                dispatch = self._executor(
                    action, snapshot.policy, snapshot.cards + (record.approval_card,), self.now)
            except Exception as error:
                record.execution_unknown = True
                self._log(request_id, "EXECUTOR", "ERROR", "EXECUTION_OUTCOME_UNKNOWN",
                          error=f"{type(error).__name__}: {error}")
                self._close(record, RequestState.ESCALATED, "EXECUTION_OUTCOME_UNKNOWN")
                if isinstance(error, MutationOutcomeUnknown):
                    raise
                raise MutationOutcomeUnknown("mutation executor returned no authoritative result") from error
            if not dispatch.executed:
                reason = "EXECUTOR_REFUSED_" + dispatch.reason
                self._close(record, RequestState.ESCALATED, reason)
                return ExecutionOutcome(False, reason, record.state, validation)
            diff, decisive = dispatch.state_diff, dispatch.decisive_card_ids
            completion_reason = dispatch.reason
            if dispatch.warnings:
                self._log(request_id, "EXECUTOR", "WARNING", dispatch.reason,
                          warnings="; ".join(dispatch.warnings))
        else:
            assert self._ledger is not None
            try:
                diff = self._ledger.apply(record.request.action_sha256)
            except RuntimeError:
                self._close(record, RequestState.ESCALATED, "LEDGER_REFUSED_DUPLICATE_BINDING")
                return ExecutionOutcome(False, "LEDGER_REFUSED_DUPLICATE_BINDING", record.state)
        record.receipt = ExecutionReceipt(request_id, record.request.action_sha256, self.now,
                                          diff, decisive)
        self._close(record, RequestState.COMPLETED, completion_reason)
        return ExecutionOutcome(True, record.terminal_reason, record.state, validation,
                                record.receipt)

    def _refuse(self, request_id: str, reason: str,
                state: RequestState | None) -> ExecutionOutcome:
        self._log(request_id, "EXECUTE", "REFUSED", reason)
        return ExecutionOutcome(False, reason, state)


def response_for(
    request: ConfirmationRequest,
    response_id: str,
    channel_id: str,
    decision: ResponseDecision = ResponseDecision.APPROVE,
    **overrides: object,
) -> HumanResponse:
    """Build a response that echoes the request exactly; tests override fields."""

    values: dict[str, object] = dict(
        response_id=response_id, request_id=request.request_id, channel_id=channel_id,
        decision=decision, challenge=request.challenge, action_sha256=request.action_sha256,
        operation=request.binding.operation, target_id=request.binding.target_id,
        scope=request.binding.scope,
    )
    values.update(overrides)
    return HumanResponse(**values)  # type: ignore[arg-type]
