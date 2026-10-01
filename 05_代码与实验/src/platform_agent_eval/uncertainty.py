from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev

from .domain import Decision, PolicyInput, RouterResult


@dataclass(frozen=True)
class CriticAggregate:
    sample_count: int
    mean_risk: float
    risk_std: float
    decision_disagreement: float
    decision_entropy: float
    reason_disagreement: float
    format_error_fraction: float
    decision_counts: Mapping[str, int]


def _pairwise_reason_agreement(samples: Sequence[RouterResult]) -> float:
    if len(samples) < 2:
        return 1.0
    scores: list[float] = []
    for left_index, left in enumerate(samples):
        left_reasons = set(left.reason_codes)
        for right in samples[left_index + 1 :]:
            right_reasons = set(right.reason_codes)
            union = left_reasons | right_reasons
            scores.append(
                len(left_reasons & right_reasons) / len(union) if union else 1.0
            )
    return fmean(scores)


def aggregate_critic_samples(samples: Sequence[RouterResult]) -> CriticAggregate:
    """Aggregate repeated critic judgments without reading any gold label."""

    if not samples:
        raise ValueError("At least one critic sample is required")
    risks = [sample.risk_score if sample.risk_score is not None else 1.0 for sample in samples]
    counts = Counter(sample.decision.value for sample in samples)
    total = len(samples)
    disagreement = 1.0 - max(counts.values()) / total
    entropy = -sum(
        (count / total) * math.log(count / total)
        for count in counts.values()
    ) / math.log(3.0)
    return CriticAggregate(
        sample_count=total,
        mean_risk=fmean(risks),
        risk_std=pstdev(risks),
        decision_disagreement=disagreement,
        decision_entropy=entropy,
        reason_disagreement=1.0 - _pairwise_reason_agreement(samples),
        format_error_fraction=sum(not sample.format_valid for sample in samples) / total,
        decision_counts=dict(sorted(counts.items())),
    )


def _approval_features(policy_input: PolicyInput) -> dict[str, float]:
    evidence = policy_input.approval_evidence
    if evidence is None:
        return {
            "approval_evidence_count": 0.0,
            "approval_verified_fraction": 0.0,
            "approval_explicit_fraction": 0.0,
            "approval_internal_scope_agreement": 0.0,
        }
    if not evidence:
        return {
            "approval_evidence_count": 0.0,
            "approval_verified_fraction": 0.0,
            "approval_explicit_fraction": 0.0,
            "approval_internal_scope_agreement": 0.0,
        }
    count = len(evidence)
    scope_keys = {
        (
            item.operation_scope,
            item.resource_owner_scope,
            item.tenant_scope,
            item.blast_radius_limit,
        )
        for item in evidence
    }
    return {
        "approval_evidence_count": float(count),
        "approval_verified_fraction": sum(
            item.authenticity == "verified" for item in evidence
        ) / count,
        "approval_explicit_fraction": sum(
            item.stance == "approved" for item in evidence
        ) / count,
        "approval_internal_scope_agreement": 1.0 / len(scope_keys),
    }


def calibration_features(
    policy_input: PolicyInput,
    aggregate: CriticAggregate,
) -> dict[str, float]:
    """Return observable model and context features for a small calibrator."""

    features = {
        "critic_mean_risk": aggregate.mean_risk,
        "critic_risk_std": aggregate.risk_std,
        "critic_decision_disagreement": aggregate.decision_disagreement,
        "critic_decision_entropy": aggregate.decision_entropy,
        "critic_reason_disagreement": aggregate.reason_disagreement,
        "critic_format_error_fraction": aggregate.format_error_fraction,
        "production": float(policy_input.production),
        "reversible": float(policy_input.reversible),
        "checkpoint_available": float(policy_input.checkpoint_available),
        "rollback_available": float(policy_input.rollback_available),
        "migration_target_available": float(policy_input.migration_target_available),
        "quota_borrowing": float(policy_input.quota_borrowing),
        "active_incident": float(policy_input.active_incident),
        "cross_tenant": float(policy_input.cross_tenant),
        "log_blast_radius": math.log1p(policy_input.blast_radius),
    }
    features.update(_approval_features(policy_input))
    return features
