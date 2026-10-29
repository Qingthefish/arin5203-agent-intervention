"""Small adapters joining field grounding, confirmation and commit-time proof.

The source callable and the mutation executor are trusted application code.
Extraction is an input, not implemented here. Authentication remains a fixture,
and the commit gate supplies only its declared in-process simulator guarantees.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass

from .commit_time_gate import CommitResult, CommitTimeGate
from .domain import Decision
from .evidence_grounding import GroundingGateResult, ground_extraction
from .human_intervention_workflow import (
    ActionBinding, EvidenceSnapshot, EvidenceUnavailable, MutationResult,
)
from .natural_language_evidence import ExtractionParse, claims_to_cards
from .proof_cards import (
    ActionRequest, ProofCard, ProofCardInput, ProofPolicy, validate_proof_cards,
)


@dataclass(frozen=True)
class GroundingInput:
    policy: ProofPolicy
    extraction: ExtractionParse
    events: Mapping[str, str]
    pre_verified_cards: tuple[ProofCard, ...] = ()
    source_receipt: str = ""


class GroundedEvidenceProvider:
    """Turn a grounding result into workflow evidence without dropping a veto.

Returning only admitted cards is unsafe: an omitted hold can force Handoff
without producing a hold card. Preserve that decision at this boundary.
"""

    def __init__(self, source: Callable[[ActionRequest], GroundingInput]) -> None:
        self._source = source
        self._last_result: GroundingGateResult | None = None

    @property
    def last_result(self) -> GroundingGateResult | None:
        return deepcopy(self._last_result)

    def __call__(self, action: ActionRequest) -> EvidenceSnapshot:
        self._last_result = None
        supplied = self._source(action)
        result = ground_extraction(
            action, supplied.policy, supplied.extraction, supplied.events,
            pre_verified_cards=supplied.pre_verified_cards,
        )
        self._last_result = deepcopy(result)
        if result.decision not in {Decision.AUTO_EXECUTE, Decision.REQUEST_CONFIRMATION}:
            reason = "GROUNDING_GATE_" + result.failure_layer
            raise EvidenceUnavailable(reason, reason_code=reason)
        candidates = supplied.pre_verified_cards + claims_to_cards(supplied.extraction.claims)
        admitted = frozenset(result.admitted_card_ids)
        cards = tuple(card for card in candidates if card.card_id in admitted)
        # A future change to grounding may encode another conservative veto.
        # Never reconstruct a more permissive workflow route from card IDs alone.
        validation = validate_proof_cards(ProofCardInput(action, supplied.policy, cards))
        if validation.decision is not result.decision:
            reason = "GROUNDING_ROUTE_NOT_REPRESENTABLE_BY_CARDS"
            raise EvidenceUnavailable(reason, reason_code=reason)
        return EvidenceSnapshot(supplied.policy, cards, supplied.source_receipt)


class CommitBoundExecutor:
    """Execute one declared operation through the atomic-revalidate simulator.

The original action and transition are detached and fixed at construction.
Keeping its original action timestamp gives the commit gate a stable binding
across workflow retries, even when evidence is re-read at a later clock time.
This is not a cross-process idempotency service. Use a new adapter for a new
business operation and a real tool's operation key outside this simulator.

    ``before_commit`` is an optional deterministic scheduling fixture, invoked
    after prepare and before commit. It is never run inside the atomic section.
"""

    def __init__(
        self,
        gate: CommitTimeGate,
        action: ActionRequest,
        transition: Mapping[str, object],
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> None:
        self._gate = gate
        self._action = deepcopy(action)
        self._binding = ActionBinding.of(self._action)
        self._transition = deepcopy(dict(transition))
        self._before_commit = before_commit
        self._last_result: CommitResult | None = None

    @property
    def last_result(self) -> CommitResult | None:
        return deepcopy(self._last_result)

    def __call__(
        self, action: ActionRequest, policy: ProofPolicy,
        cards: tuple[ProofCard, ...], at: str,
    ) -> MutationResult:
        self._last_result = None
        if ActionBinding.of(action) != self._binding:
            return MutationResult(False, "ACTION_DIFFERS_FROM_DECLARED_OPERATION")
        prepared = self._gate.prepare(
            self._action, policy, cards, self._transition, at=at)
        if self._before_commit is not None:
            self._before_commit()
        result = self._gate.commit(
            prepared, action=self._action, transition=self._transition,
            at=at, mode="atomic_revalidate",
        )
        self._last_result = deepcopy(result)
        if not result.executed:
            validation = result.commit_check.result if result.commit_check else None
            details = tuple(code for code in validation.reason_codes
                            if code.endswith(("MISSING", "BLOCKED"))) if validation else ()
            return MutationResult(False, "+".join(dict.fromkeys(result.reason_codes + details)))
        assert result.execution is not None and result.commit_check is not None
        assert result.commit_check.result is not None
        before, after = result.execution.state_before, result.execution.state_after
        diff = tuple((key, repr(before.get(key)), repr(after.get(key)))
                     for key in sorted(set(before) | set(after))
                     if before.get(key) != after.get(key))
        return MutationResult(
            True, "EXECUTED_BY_COMMIT_GATE", diff,
            result.commit_check.result.decisive_card_ids,
        )
