from __future__ import annotations

from .domain import ApprovalEvidence, ApprovalRequirement


def evidence_satisfies_requirement(
    evidence: ApprovalEvidence,
    requirement: ApprovalRequirement,
) -> bool:
    """Match raw evidence to one requirement without reading a route label."""

    if evidence.stance != "approved" or evidence.authenticity != "verified":
        return False
    if evidence.approver_id not in requirement.acceptable_approvers:
        return False
    if evidence.operation_scope is not requirement.operation_scope:
        return False
    if evidence.resource_owner_scope != requirement.resource_owner_scope:
        return False
    if not set(requirement.tenant_scope).issubset(evidence.tenant_scope):
        return False
    if evidence.blast_radius_limit is None:
        return False
    return evidence.blast_radius_limit >= requirement.required_blast_radius


def missing_requirements(
    evidence_items: tuple[ApprovalEvidence, ...],
    requirements: tuple[ApprovalRequirement, ...],
) -> tuple[ApprovalRequirement, ...]:
    """Return every requirement for which no single evidence item is valid."""

    return tuple(
        requirement
        for requirement in requirements
        if not any(
            evidence_satisfies_requirement(evidence, requirement)
            for evidence in evidence_items
        )
    )


def canonical_evidence(requirement: ApprovalRequirement) -> ApprovalEvidence:
    """Construct a fully valid item for counterfactual validator checks."""

    return ApprovalEvidence(
        approver_id=requirement.acceptable_approvers[0],
        stance="approved",
        authenticity="verified",
        operation_scope=requirement.operation_scope,
        resource_owner_scope=requirement.resource_owner_scope,
        tenant_scope=requirement.tenant_scope,
        blast_radius_limit=requirement.required_blast_radius,
    )
