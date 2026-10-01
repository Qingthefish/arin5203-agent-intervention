from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.calibration import (
    RoutingThresholds,
    area_under_risk_coverage,
    brier_score,
    calibrated_three_way_decision,
    expected_calibration_error,
    fit_logistic_calibrator,
    risk_coverage_curve,
    select_three_way_thresholds,
)
from platform_agent_eval.domain import Decision, RouterResult
from platform_agent_eval.scenarios import build_scoped_approval_scenarios
from platform_agent_eval.uncertainty import (
    aggregate_critic_samples,
    calibration_features,
)


class UncertaintyTests(unittest.TestCase):
    def test_aggregate_captures_routing_and_reason_disagreement(self) -> None:
        samples = [
            RouterResult(Decision.AUTO_EXECUTE, "llm", reason_codes=("safe",), risk_score=0.1),
            RouterResult(Decision.AUTO_EXECUTE, "llm", reason_codes=("safe",), risk_score=0.2),
            RouterResult(Decision.HANDOFF, "llm", reason_codes=("incident",), risk_score=0.9),
        ]
        aggregate = aggregate_critic_samples(samples)
        self.assertAlmostEqual(0.4, aggregate.mean_risk)
        self.assertAlmostEqual(1 / 3, aggregate.decision_disagreement)
        self.assertGreater(aggregate.decision_entropy, 0.0)
        self.assertGreater(aggregate.reason_disagreement, 0.0)

    def test_calibration_features_are_observable_and_finite(self) -> None:
        case = build_scoped_approval_scenarios()[0]
        aggregate = aggregate_critic_samples(
            [RouterResult(Decision.AUTO_EXECUTE, "llm", risk_score=0.1)]
        )
        features = calibration_features(case.policy_input, aggregate)
        self.assertIn("critic_mean_risk", features)
        self.assertIn("approval_evidence_count", features)
        self.assertNotIn("expected_decision", features)
        self.assertTrue(all(value == value for value in features.values()))


class CalibrationTests(unittest.TestCase):
    def test_logistic_calibrator_separates_simple_training_data(self) -> None:
        rows = [{"risk": value} for value in (0.0, 0.1, 0.2, 0.8, 0.9, 1.0)]
        labels = [False, False, False, True, True, True]
        model = fit_logistic_calibrator(rows, labels)
        self.assertLess(model.predict_proba({"risk": 0.1}), 0.5)
        self.assertGreater(model.predict_proba({"risk": 0.9}), 0.5)

    def test_three_way_policy_uses_two_distinct_axes(self) -> None:
        thresholds = RoutingThresholds(0.3, 0.6)
        self.assertIs(Decision.AUTO_EXECUTE, calibrated_three_way_decision(0.1, 0.1, thresholds))
        self.assertIs(Decision.REQUEST_CONFIRMATION, calibrated_three_way_decision(0.8, 0.9, thresholds))
        self.assertIs(Decision.HANDOFF, calibrated_three_way_decision(0.8, 0.2, thresholds))

    def test_thresholds_are_selected_from_aligned_development_arrays(self) -> None:
        harm = [0.05, 0.1, 0.8, 0.9]
        resolvable = [0.9, 0.8, 0.9, 0.1]
        unsafe = [False, False, True, True]
        can_confirm = [False, False, True, False]
        thresholds = select_three_way_thresholds(
            harm,
            resolvable,
            unsafe,
            can_confirm,
            max_unsafe_execution_rate=0.0,
        )
        decisions = [
            calibrated_three_way_decision(h, r, thresholds)
            for h, r in zip(harm, resolvable)
        ]
        self.assertEqual(Decision.REQUEST_CONFIRMATION, decisions[2])
        self.assertEqual(Decision.HANDOFF, decisions[3])
        self.assertEqual(Decision.AUTO_EXECUTE, decisions[0])
        self.assertEqual(Decision.AUTO_EXECUTE, decisions[1])

    def test_threshold_ties_choose_a_stable_interior_margin(self) -> None:
        thresholds = select_three_way_thresholds(
            [0.02, 0.04, 0.28, 0.9],
            [0.99, 0.98, 0.95, 0.01],
            [False, False, True, True],
            [False, False, True, False],
            max_unsafe_execution_rate=0.0,
        )
        self.assertAlmostEqual(0.15, thresholds.execute_below)
        self.assertAlmostEqual(0.5, thresholds.confirm_if_resolvable_at_least)

    def test_calibration_and_selective_metrics_have_known_values(self) -> None:
        probabilities = [0.0, 0.25, 0.75, 1.0]
        labels = [False, False, True, True]
        self.assertAlmostEqual(0.03125, brier_score(probabilities, labels))
        self.assertAlmostEqual(0.125, expected_calibration_error(probabilities, labels, bins=4))
        curve = risk_coverage_curve(probabilities, labels)
        self.assertEqual((0.25, 0.0), curve[0])
        self.assertAlmostEqual(sum(risk for _, risk in curve) / 4, area_under_risk_coverage(probabilities, labels))


if __name__ == "__main__":
    unittest.main()
