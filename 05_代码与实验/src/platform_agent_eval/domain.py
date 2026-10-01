from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


class Operation(str, Enum):
    CHANGE_GPU_QUOTA = "CHANGE_GPU_QUOTA"
    PREEMPT_WORKLOAD = "PREEMPT_WORKLOAD"
    TRANSFER_RESOURCE = "TRANSFER_RESOURCE"
    ROLLOUT_MODEL = "ROLLOUT_MODEL"
    RECLAIM_CAPACITY = "RECLAIM_CAPACITY"


class Decision(str, Enum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    HANDOFF = "HANDOFF"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class WorldState:
    """Small, operation-agnostic state used by the deterministic smoke test."""

    gpu_quota: int = 0
    hard_quota_cap: int = 64
    running_workloads: int = 0
    resource_owner: str = ""
    resource_location: str = "default"
    resource_busy: bool = False
    model_version: str = "v1"
    production_traffic_percent: int = 0
    active_nodes: int = 1


@dataclass(frozen=True)
class ToolCall:
    operation: Operation
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalEvidence:
    """Raw approval evidence visible to a scoped-approval router.

    No derived validity flag is stored here.  Validity depends on the private
    requirement used by the evaluator and is computed by a separate matcher.
    """

    approver_id: str
    stance: Literal["approved", "ambiguous"]
    authenticity: Literal["verified", "unverified"]
    operation_scope: Operation | None
    resource_owner_scope: str | None
    tenant_scope: tuple[str, ...]
    blast_radius_limit: int | None


@dataclass(frozen=True)
class ApprovalRequirement:
    """Private approval requirement used only by the safety oracle."""

    requirement_kind: str
    acceptable_approvers: tuple[str, ...]
    operation_scope: Operation
    resource_owner_scope: str
    tenant_scope: tuple[str, ...]
    required_blast_radius: int


@dataclass(frozen=True)
class PolicyInput:
    """Information a routing policy is allowed to observe.

    Dataset identifiers, variant names, and gold decisions deliberately do not
    live in this object. A future model prompt must be built from this object,
    not from EvaluationCase or GoldAnnotation.
    """

    operation: Operation
    request: str
    actor_tenant: str
    actor_role: str
    resource_owner: str
    affected_tenants: tuple[str, ...]
    consent_present: bool
    production: bool
    reversible: bool
    checkpoint_available: bool
    rollback_available: bool
    migration_target_available: bool
    quota_borrowing: bool
    active_incident: bool
    blast_radius: int
    world_state: WorldState
    tool_call: ToolCall
    # ``None`` keeps the legacy Boolean-consent protocol used by the frozen v1
    # pilot.  A tuple (including an empty tuple) activates scoped approvals.
    approval_evidence: tuple[ApprovalEvidence, ...] | None = None

    def __post_init__(self) -> None:
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be positive")
        if self.operation is not self.tool_call.operation:
            raise ValueError("PolicyInput.operation must match ToolCall.operation")
        if self.resource_owner != self.world_state.resource_owner:
            raise ValueError("resource_owner must match WorldState.resource_owner")

    @property
    def cross_tenant(self) -> bool:
        return any(
            tenant not in {self.actor_tenant, "platform"}
            for tenant in self.affected_tenants
        )


@dataclass(frozen=True)
class GoldAnnotation:
    """Private evaluation metadata that must never be passed to a policy."""

    scenario_id: str
    base_task_id: str
    variant: str
    expected_decision: Decision

    def __post_init__(self) -> None:
        if self.variant not in {"low", "medium", "high"}:
            raise ValueError(f"Unknown variant: {self.variant}")


@dataclass(frozen=True)
class OracleContext:
    """Private policy facts used for scoring, never exposed to a router."""

    observed_state: str = ""
    required_approver: str | None = None
    operator_review_required: bool = False
    approval_requirements: tuple[ApprovalRequirement, ...] = ()


@dataclass(frozen=True)
class EvaluationCase:
    policy_input: PolicyInput
    oracle: OracleContext
    gold: GoldAnnotation


@dataclass(frozen=True)
class MutationOutcome:
    after_state: WorldState
    state_diff: dict[str, dict[str, Any]]
    task_completed: bool
    unsafe: bool
    harmful_mutation: bool
    prohibited_attempt: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationRecord:
    policy: str
    split: str
    scenario_id: str
    base_task_id: str
    variant: str
    operation: str
    expected_decision: str
    decision: str
    decision_source: str
    format_valid: bool
    reason_codes: tuple[str, ...]
    risk_score: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float | None
    model_id: str | None
    model_digest: str | None
    prompt_template: str | None
    prompt_hash: str | None
    raw_output: str | None
    correct_route: bool
    auto_executed: bool
    mutation_applied: bool
    unsafe_mutation: bool
    prohibited_attempt: bool
    policy_violations: tuple[str, ...]
    counterfactual_unsafe_if_executed: bool
    counterfactual_prohibited_attempt: bool
    counterfactual_policy_violations: tuple[str, ...]
    state_diff: dict[str, dict[str, Any]]
    safe_autonomous_completion: bool
    authorized_task_completion: bool
    human_cost: float
    unnecessary_intervention: bool
    missed_block: bool
    correct_confirmation: bool
    correct_handoff: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouterResult:
    """A routing decision plus the provenance needed for reproducible evals."""

    decision: Decision
    decision_source: str
    raw_output: str | None = None
    format_valid: bool = True
    reason_codes: tuple[str, ...] = ()
    risk_score: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    model_id: str | None = None
    model_digest: str | None = None
    prompt_template: str | None = None
    prompt_hash: str | None = None

    def __post_init__(self) -> None:
        if self.risk_score is not None and not 0.0 <= self.risk_score <= 1.0:
            raise ValueError("risk_score must be between zero and one")
