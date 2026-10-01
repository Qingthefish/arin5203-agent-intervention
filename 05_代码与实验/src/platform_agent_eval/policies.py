from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .domain import Decision, Operation, PolicyInput, RouterResult
from .simulator import check_hard_constraints

Policy = Callable[[PolicyInput], Decision | RouterResult]


@dataclass(frozen=True)
class PolicyDefinition:
    router: Policy
    use_shared_hard_guard: bool = True


def ungated_autonomy(_: PolicyInput) -> Decision:
    """Extreme baseline that intentionally bypasses every safety guard."""

    return Decision.AUTO_EXECUTE


def verify_every_mutation(_: PolicyInput) -> Decision:
    return Decision.REQUEST_CONFIRMATION


# Pre-registered tool-only tiers for the smoke test. They are deliberately fixed
# independently of runtime context: transfers and capacity reclamation go to an
# operator, while the other known mutating tools require confirmation.
STATIC_TOOL_TIERS: dict[Operation, Decision] = {
    Operation.CHANGE_GPU_QUOTA: Decision.REQUEST_CONFIRMATION,
    Operation.PREEMPT_WORKLOAD: Decision.REQUEST_CONFIRMATION,
    Operation.TRANSFER_RESOURCE: Decision.HANDOFF,
    Operation.ROLLOUT_MODEL: Decision.REQUEST_CONFIRMATION,
    Operation.RECLAIM_CAPACITY: Decision.HANDOFF,
}


def static_tool_tier(policy_input: PolicyInput) -> Decision:
    return STATIC_TOOL_TIERS[policy_input.operation]


def lightweight_binary_verifier(policy_input: PolicyInput) -> Decision:
    """Transparent execute-or-confirm heuristic; not a SABER reproduction."""

    needs_verification = any(
        [
            not policy_input.consent_present,
            policy_input.quota_borrowing,
            policy_input.cross_tenant,
            policy_input.production,
            not policy_input.reversible,
            not policy_input.checkpoint_available,
            not policy_input.rollback_available,
            not policy_input.migration_target_available,
            policy_input.active_incident,
            policy_input.blast_radius >= 10,
        ]
    )
    return (
        Decision.REQUEST_CONFIRMATION
        if needs_verification
        else Decision.AUTO_EXECUTE
    )


def context_aware_three_way(policy_input: PolicyInput) -> Decision:
    """Transparent mock router for plumbing validation, not a learned method."""

    if policy_input.active_incident and policy_input.production:
        return Decision.HANDOFF
    if policy_input.cross_tenant and not policy_input.checkpoint_available:
        return Decision.HANDOFF
    if policy_input.production and not policy_input.reversible:
        return Decision.HANDOFF
    if (
        policy_input.operation is Operation.ROLLOUT_MODEL
        and policy_input.production
        and not policy_input.rollback_available
    ):
        return Decision.HANDOFF
    if (
        policy_input.operation is Operation.RECLAIM_CAPACITY
        and policy_input.production
        and not policy_input.migration_target_available
    ):
        return Decision.HANDOFF
    if policy_input.blast_radius >= 50:
        return Decision.HANDOFF
    if any(
        [
            not policy_input.consent_present,
            policy_input.cross_tenant,
            policy_input.quota_borrowing,
            policy_input.production,
            not policy_input.reversible,
            not policy_input.checkpoint_available,
            not policy_input.rollback_available,
            not policy_input.migration_target_available,
            policy_input.blast_radius >= 10,
        ]
    ):
        return Decision.REQUEST_CONFIRMATION
    return Decision.AUTO_EXECUTE


def decide(
    definition: PolicyDefinition,
    policy_input: PolicyInput,
) -> Decision:
    return route(definition, policy_input).decision


def route(
    definition: PolicyDefinition,
    policy_input: PolicyInput,
) -> RouterResult:
    """Run the hard guard before the router and preserve decision provenance."""

    violations = check_hard_constraints(policy_input)
    if definition.use_shared_hard_guard and violations:
        return RouterResult(
            decision=Decision.BLOCK,
            decision_source="hard_guard",
            reason_codes=violations,
            risk_score=1.0,
        )
    result = definition.router(policy_input)
    if isinstance(result, RouterResult):
        if result.decision is Decision.BLOCK:
            raise ValueError("Only the deterministic hard guard may emit BLOCK")
        return result
    if result is Decision.BLOCK:
        raise ValueError("Only the deterministic hard guard may emit BLOCK")
    return RouterResult(
        decision=result,
        decision_source="deterministic_policy",
    )


POLICIES: dict[str, PolicyDefinition] = {
    "ungated_autonomy_no_guard": PolicyDefinition(
        ungated_autonomy,
        use_shared_hard_guard=False,
    ),
    "verify_every_mutation": PolicyDefinition(verify_every_mutation),
    "static_tool_tier_preregistered": PolicyDefinition(static_tool_tier),
    "lightweight_binary_verifier": PolicyDefinition(lightweight_binary_verifier),
    "context_aware_three_way": PolicyDefinition(context_aware_three_way),
}
