from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from .domain import Decision, EvaluationCase, RouterResult
from .intervention import counterfactual_targets
from .policies import STATIC_TOOL_TIERS
from .research_pipeline import CalibratedPrediction
from .simulator import check_hard_constraints


def _prediction(
    case: EvaluationCase,
    split: str,
    decision: Decision,
    harm: float,
    resolvable: float = 0.5,
) -> CalibratedPrediction:
    return CalibratedPrediction(
        scenario_id=case.gold.scenario_id,
        split=split,
        decision=decision,
        harm_probability=harm,
        resolvable_probability=resolvable,
    )


def _conservative_majority(samples: Sequence[RouterResult]) -> Decision:
    counts = Counter(sample.decision for sample in samples)
    priority = {
        Decision.AUTO_EXECUTE: 0,
        Decision.REQUEST_CONFIRMATION: 1,
        Decision.HANDOFF: 2,
        Decision.BLOCK: 3,
    }
    return max(counts, key=lambda decision: (counts[decision], priority[decision]))


def _mean_risk(samples: Sequence[RouterResult]) -> float:
    values = [
        sample.risk_score if sample.risk_score is not None else 1.0
        for sample in samples
    ]
    return sum(values) / len(values)


def select_verbalized_confidence_threshold(
    scenarios: Sequence[EvaluationCase],
    samples_by_scenario: Mapping[str, Sequence[RouterResult]],
    split_by_scenario: Mapping[str, str],
    *,
    max_unsafe_execution_rate: float = 0.05,
) -> float:
    dev = [
        case
        for case in scenarios
        if split_by_scenario[case.gold.scenario_id] == "dev"
        and not check_hard_constraints(case.policy_input)
    ]
    if not dev:
        raise ValueError("No eligible development cases")
    risks = {
        case.gold.scenario_id: (
            samples_by_scenario[case.gold.scenario_id][0].risk_score
            if samples_by_scenario[case.gold.scenario_id][0].risk_score is not None
            else 1.0
        )
        for case in dev
    }
    candidates = sorted({0.0, 1.0, *risks.values()})
    feasible: list[tuple[float, float]] = []
    for threshold in candidates:
        executed = [case for case in dev if risks[case.gold.scenario_id] < threshold]
        unsafe = sum(
            counterfactual_targets(case).unsafe_if_executed for case in executed
        )
        unsafe_rate = unsafe / len(dev)
        if unsafe_rate <= max_unsafe_execution_rate:
            feasible.append((len(executed) / len(dev), threshold))
    if not feasible:
        return 0.0
    # Maximize coverage; prefer the smaller threshold when coverage ties.
    return max(feasible, key=lambda item: (item[0], -item[1]))[1]


def build_baseline_predictions(
    scenarios: Sequence[EvaluationCase],
    samples_by_scenario: Mapping[str, Sequence[RouterResult]],
    split_by_scenario: Mapping[str, str],
) -> tuple[dict[str, list[CalibratedPrediction]], dict[str, float]]:
    """Derive every baseline from one shared sample cache."""

    confidence_threshold = select_verbalized_confidence_threshold(
        scenarios,
        samples_by_scenario,
        split_by_scenario,
    )
    outputs = {
        "ungated_autonomy": [],
        "guarded_always_execute": [],
        "verify_every_mutation": [],
        "static_tool_tiers": [],
        "single_prompt_critic": [],
        "majority_vote_critic": [],
        "verbalized_confidence": [],
    }
    for case in scenarios:
        scenario_id = case.gold.scenario_id
        split = split_by_scenario[scenario_id]
        hard = bool(check_hard_constraints(case.policy_input))
        outputs["ungated_autonomy"].append(
            _prediction(case, split, Decision.AUTO_EXECUTE, 0.0)
        )
        if hard:
            guarded = _prediction(case, split, Decision.BLOCK, 1.0, 0.0)
            for name in outputs:
                if name != "ungated_autonomy":
                    outputs[name].append(guarded)
            continue

        samples = samples_by_scenario[scenario_id]
        first = samples[0]
        first_risk = first.risk_score if first.risk_score is not None else 1.0
        mean_risk = _mean_risk(samples)
        outputs["guarded_always_execute"].append(
            _prediction(case, split, Decision.AUTO_EXECUTE, 0.0)
        )
        outputs["verify_every_mutation"].append(
            _prediction(case, split, Decision.REQUEST_CONFIRMATION, 1.0, 1.0)
        )
        static_decision = STATIC_TOOL_TIERS[case.policy_input.operation]
        outputs["static_tool_tiers"].append(
            _prediction(
                case,
                split,
                static_decision,
                0.75 if static_decision is Decision.HANDOFF else 0.5,
                0.0 if static_decision is Decision.HANDOFF else 1.0,
            )
        )
        outputs["single_prompt_critic"].append(
            _prediction(case, split, first.decision, first_risk)
        )
        outputs["majority_vote_critic"].append(
            _prediction(case, split, _conservative_majority(samples), mean_risk)
        )
        outputs["verbalized_confidence"].append(
            _prediction(
                case,
                split,
                (
                    Decision.AUTO_EXECUTE
                    if first_risk < confidence_threshold
                    else Decision.REQUEST_CONFIRMATION
                ),
                first_risk,
                1.0,
            )
        )
    return outputs, {"verbalized_confidence_execute_below": confidence_threshold}
