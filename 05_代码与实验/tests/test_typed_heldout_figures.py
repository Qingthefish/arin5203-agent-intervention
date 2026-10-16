from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plot_typed_heldout_presentation import (
    compute_benchmark_design,
    compute_case_story,
    compute_experiment_scale,
    compute_metrics,
    load_index,
    load_jsonl,
    load_records,
)


RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"
DEV_RAW = ROOT / "results" / "typed_exact_budget_dev_qwen_v6_raw.jsonl"
INDEX = ROOT / "results" / "index.json"


class TypedHeldoutPresentationFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(RAW)
        cls.metrics = compute_metrics(cls.records)
        cls.experiment_scale = compute_experiment_scale(load_index(INDEX))
        cls.benchmark_design = compute_benchmark_design(load_jsonl(DEV_RAW), cls.records)
        cls.case_story = compute_case_story(cls.records)

    def test_typed_stable_metrics_match_frozen_audit(self) -> None:
        typed = next(
            row
            for row in self.metrics["method_metrics"]
            if row["method"] == "typed_card_retention"
        )
        self.assertEqual(22, typed["stable_cases"])
        self.assertEqual(14, typed["direct_stable_correct"])
        self.assertEqual(22, typed["audited_stable_correct"])
        self.assertEqual(4, typed["direct_stable_harm"])
        self.assertEqual(0, typed["audited_stable_harm"])
        self.assertEqual(1.0, typed["visible_card_recall"])
        self.assertEqual(1.0, typed["proof_citation_precision"])

    def test_strong_summary_tie_and_grounding_gap_are_preserved(self) -> None:
        by_method = {row["method"]: row for row in self.metrics["method_metrics"]}
        for method in ("neutral_summary", "task_aware_summary", "ufold_lite"):
            self.assertEqual(22, by_method[method]["audited_stable_correct"])
        self.assertLess(by_method["neutral_summary"]["proof_citation_precision"], 0.8)
        self.assertLess(by_method["task_aware_summary"]["proof_citation_precision"], 0.7)
        self.assertGreater(by_method["ufold_lite"]["proof_citation_precision"], 0.98)

    def test_hidden_hold_boundary_is_not_erased(self) -> None:
        boundary = self.metrics["typed_boundary"]
        self.assertEqual(8, boundary["non_hold_deletions"])
        self.assertEqual(8, boundary["non_hold_fail_closed"])
        self.assertEqual(3, boundary["hidden_hold_deletions"])
        self.assertEqual(3, boundary["hidden_hold_harmful_executes"])
        self.assertEqual(10, boundary["audit_helpful"])
        self.assertEqual(0, boundary["audit_harmful"])

    def test_experiment_scale_comes_from_indexed_manifests(self) -> None:
        scale = self.experiment_scale
        self.assertEqual(38, scale["recorded_runs"])
        self.assertEqual(1745, scale["measured_calls"])
        self.assertEqual(1762343, scale["recorded_tokens"])
        self.assertEqual(0.0, scale["external_api_cost_usd"])
        heldout = next(
            row
            for row in scale["turning_points"]
            if row["prefix"] == "typed_exact_budget_heldout_qwen_v1"
        )
        self.assertEqual(330, heldout["calls"])
        self.assertAlmostEqual(103.2, heldout["minutes"], places=1)

    def test_benchmark_design_preserves_frozen_split(self) -> None:
        design = self.benchmark_design
        self.assertEqual(9, design["development_bases"])
        self.assertEqual(27, design["development_cases"])
        self.assertEqual(11, design["heldout_bases"])
        self.assertEqual(33, design["heldout_cases"])
        self.assertEqual(20, design["total_bases"])
        self.assertEqual(60, design["total_cases"])
        self.assertEqual(7, design["methods"])
        self.assertEqual(384, design["budget_tokens"])
        self.assertEqual(
            {"platform": 7, "financial": 7, "mas_travel": 6},
            design["domain_bases"],
        )
        self.assertEqual(
            {"AUTO_EXECUTE": 5, "REQUEST_CONFIRMATION": 3, "HANDOFF": 3},
            design["heldout_route_mix"],
        )

    def test_matched_case_story_retains_hidden_hold_failure(self) -> None:
        conditions = {
            row["condition"]: row for row in self.case_story["conditions"]
        }
        self.assertEqual("HANDOFF", conditions["full_evidence"]["decision"])
        self.assertFalse(conditions["full_evidence"]["harmful_execution"])
        self.assertEqual("AUTO_EXECUTE", conditions["remove_action_critical"]["decision"])
        self.assertTrue(conditions["remove_action_critical"]["harmful_execution"])
        self.assertEqual("HANDOFF", conditions["remove_matched_noise"]["decision"])
        self.assertFalse(conditions["remove_matched_noise"]["harmful_execution"])


if __name__ == "__main__":
    unittest.main()
