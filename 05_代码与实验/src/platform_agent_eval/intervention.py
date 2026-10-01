from __future__ import annotations

from dataclasses import dataclass, replace

from .approvals import canonical_evidence
from .domain import EvaluationCase, MutationOutcome
from .simulator import check_hard_constraints, execute_and_score


@dataclass(frozen=True)
class ConfirmationResolution:
    attempted: bool
    supplied_evidence_items: int
    resolved: bool
    outcome: MutationOutcome | None


@dataclass(frozen=True)
class CounterfactualTargets:
    hard_block: bool
    unsafe_if_executed: bool
    resolvable_by_confirmation: bool


def counterfactual_targets(case: EvaluationCase) -> CounterfactualTargets:
    """Derive private evaluation targets from execution, never route labels."""

    hard_block = bool(check_hard_constraints(case.policy_input))
    outcome = execute_and_score(case.policy_input, case.oracle)
    resolution = resolve_after_confirmation(case)
    return CounterfactualTargets(
        hard_block=hard_block,
        unsafe_if_executed=outcome.prohibited_attempt,
        resolvable_by_confirmation=(
            not hard_block
            and outcome.prohibited_attempt
            and resolution.resolved
        ),
    )


def resolve_after_confirmation(
    case: EvaluationCase,
    *,
    supply_valid_approval: bool = True,
) -> ConfirmationResolution:
    """Simulate one user/owner confirmation round trip and safe re-evaluation.

    The action is never applied before the new evidence is validated. Hard
    guard failures cannot be repaired through confirmation. A residual
    operational hazard remains prohibited even after perfect approval.
    """

    if check_hard_constraints(case.policy_input):
        return ConfirmationResolution(False, 0, False, None)

    if case.policy_input.approval_evidence is None:
        updated = replace(
            case.policy_input,
            consent_present=(True if supply_valid_approval else case.policy_input.consent_present),
        )
        supplied = int(supply_valid_approval and not case.policy_input.consent_present)
    else:
        evidence = case.policy_input.approval_evidence
        if supply_valid_approval:
            evidence = tuple(
                canonical_evidence(requirement)
                for requirement in case.oracle.approval_requirements
            )
        updated = replace(case.policy_input, approval_evidence=evidence)
        supplied = len(evidence) if supply_valid_approval else 0

    outcome = execute_and_score(updated, case.oracle)
    resolved = outcome.task_completed and not outcome.prohibited_attempt
    return ConfirmationResolution(True, supplied, resolved, outcome)
