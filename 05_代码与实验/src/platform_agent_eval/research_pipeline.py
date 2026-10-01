from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .calibration import (
    LogisticCalibrator,
    RoutingThresholds,
    calibrated_three_way_decision,
    fit_logistic_calibrator,
    select_three_way_thresholds,
)
from .domain import Decision, EvaluationCase, RouterResult
from .intervention import CounterfactualTargets, counterfactual_targets
from .simulator import check_hard_constraints
from .uncertainty import aggregate_critic_samples, calibration_features


@dataclass(frozen=True)
class PreparedCase:
    case: EvaluationCase
    split: str
    sample_count: int
    features: Mapping[str, float]
    targets: CounterfactualTargets


@dataclass(frozen=True)
class FittedThreeWayPolicy:
    harm_calibrator: LogisticCalibrator
    resolvability_calibrator: LogisticCalibrator
    thresholds: RoutingThresholds
    sample_count: int


@dataclass(frozen=True)
class CalibratedPrediction:
    scenario_id: str
    split: str
    decision: Decision
    harm_probability: float
    resolvable_probability: float


ABLATION_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "ablation_no_disagreement": (
        "critic_risk_std",
        "critic_decision_disagreement",
        "critic_decision_entropy",
        "critic_reason_disagreement",
    ),
    "ablation_no_critic_score": (
        "critic_mean_risk",
        "critic_risk_std",
    ),
    "ablation_no_approval_features": (
        "approval_evidence_count",
        "approval_verified_fraction",
        "approval_explicit_fraction",
        "approval_internal_scope_agreement",
    ),
}


def prepare_cases(
    scenarios: Sequence[EvaluationCase],
    samples_by_scenario: Mapping[str, Sequence[RouterResult]],
    split_by_scenario: Mapping[str, str],
) -> list[PreparedCase]:
    """Create label-separated rows after all critic samples are cached."""

    prepared: list[PreparedCase] = []
    sample_counts: set[int] = set()
    for case in scenarios:
        scenario_id = case.gold.scenario_id
        if scenario_id not in split_by_scenario:
            raise ValueError(f"Missing split for {scenario_id}")
        targets = counterfactual_targets(case)
        if targets.hard_block:
            continue
        samples = samples_by_scenario.get(scenario_id)
        if not samples:
            raise ValueError(f"Missing critic samples for {scenario_id}")
        aggregate = aggregate_critic_samples(samples)
        sample_counts.add(aggregate.sample_count)
        prepared.append(
            PreparedCase(
                case=case,
                split=split_by_scenario[scenario_id],
                sample_count=aggregate.sample_count,
                features=calibration_features(case.policy_input, aggregate),
                targets=targets,
            )
        )
    if len(sample_counts) != 1:
        raise ValueError(f"Inconsistent samples per case: {sorted(sample_counts)}")
    return prepared


def fit_three_way_policy(prepared: Sequence[PreparedCase]) -> FittedThreeWayPolicy:
    """Fit on train only and choose routing thresholds on dev only."""

    train = [item for item in prepared if item.split == "train"]
    dev = [item for item in prepared if item.split == "dev"]
    if not train or not dev:
        raise ValueError("Both train and dev rows are required")

    harm_model = fit_logistic_calibrator(
        [item.features for item in train],
        [item.targets.unsafe_if_executed for item in train],
    )
    unsafe_train = [item for item in train if item.targets.unsafe_if_executed]
    resolvability_model = fit_logistic_calibrator(
        [item.features for item in unsafe_train],
        [item.targets.resolvable_by_confirmation for item in unsafe_train],
    )
    dev_harm = [harm_model.predict_proba(item.features) for item in dev]
    dev_resolvable = [
        resolvability_model.predict_proba(item.features) for item in dev
    ]
    thresholds = select_three_way_thresholds(
        dev_harm,
        dev_resolvable,
        [item.targets.unsafe_if_executed for item in dev],
        [item.targets.resolvable_by_confirmation for item in dev],
    )
    sample_counts = {item.sample_count for item in prepared}
    if len(sample_counts) != 1:
        raise ValueError(f"Inconsistent prepared sample counts: {sorted(sample_counts)}")
    return FittedThreeWayPolicy(
        harm_calibrator=harm_model,
        resolvability_calibrator=resolvability_model,
        thresholds=thresholds,
        sample_count=next(iter(sample_counts)),
    )


def ablate_prepared_cases(
    prepared: Sequence[PreparedCase],
    *,
    excluded_features: Sequence[str] = (),
    keep_prefixes: Sequence[str] = (),
) -> list[PreparedCase]:
    """Create a feature ablation without changing cached model judgments."""

    if not prepared:
        raise ValueError("Prepared cases cannot be empty")
    available = set(prepared[0].features)
    unknown = set(excluded_features) - available
    if unknown:
        raise ValueError(f"Unknown excluded features: {sorted(unknown)}")
    ablated: list[PreparedCase] = []
    for item in prepared:
        features = {
            name: value
            for name, value in item.features.items()
            if name not in excluded_features
            and (
                not keep_prefixes
                or any(name.startswith(prefix) for prefix in keep_prefixes)
            )
        }
        if not features:
            raise ValueError("Ablation removed every feature")
        ablated.append(replace(item, features=features))
    return ablated


def predict_prepared(
    policy: FittedThreeWayPolicy,
    prepared: Sequence[PreparedCase],
) -> list[CalibratedPrediction]:
    predictions: list[CalibratedPrediction] = []
    for item in prepared:
        harm = policy.harm_calibrator.predict_proba(item.features)
        resolvable = policy.resolvability_calibrator.predict_proba(item.features)
        predictions.append(
            CalibratedPrediction(
                scenario_id=item.case.gold.scenario_id,
                split=item.split,
                decision=calibrated_three_way_decision(
                    harm,
                    resolvable,
                    policy.thresholds,
                ),
                harm_probability=harm,
                resolvable_probability=resolvable,
            )
        )
    return predictions


def hard_guard_predictions(
    scenarios: Sequence[EvaluationCase],
    split_by_scenario: Mapping[str, str],
) -> list[CalibratedPrediction]:
    return [
        CalibratedPrediction(
            scenario_id=case.gold.scenario_id,
            split=split_by_scenario[case.gold.scenario_id],
            decision=Decision.BLOCK,
            harm_probability=1.0,
            resolvable_probability=0.0,
        )
        for case in scenarios
        if check_hard_constraints(case.policy_input)
    ]
