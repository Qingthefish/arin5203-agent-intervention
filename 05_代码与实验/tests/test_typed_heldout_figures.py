from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plot_typed_heldout_presentation import (
    compute_benchmark_design,
    compute_budget_sensitivity,
    compute_durable_store_rescue,
    compute_case_story,
    compute_experiment_scale,
    compute_metrics,
    load_index,
    load_csv,
    load_jsonl,
    load_records,
)


RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"
DEV_RAW = ROOT / "results" / "typed_exact_budget_dev_qwen_v6_raw.jsonl"
INDEX = ROOT / "results" / "index.json"
SWEEP_RAW = ROOT / "results" / "typed_budget_sweep_dev_qwen_v1_raw.jsonl"
SWEEP_SUMMARY = ROOT / "results" / "typed_budget_sweep_dev_qwen_v1_summary.csv"
DURABLE_AUDIT = ROOT / "results" / "durable_proof_store_deterministic_v1_audit.json"


class TypedHeldoutPresentationFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(RAW)
        cls.metrics = compute_metrics(cls.records)
        cls.index = load_index(INDEX)
        cls.experiment_scale = compute_experiment_scale(cls.index)
        cls.benchmark_design = compute_benchmark_design(load_jsonl(DEV_RAW), cls.records)
        cls.case_story = compute_case_story(cls.records)
        cls.budget_sensitivity = compute_budget_sensitivity(
            load_csv(SWEEP_SUMMARY), load_jsonl(SWEEP_RAW)
        )
        cls.durable_store_rescue = compute_durable_store_rescue(
            __import__("json").loads(DURABLE_AUDIT.read_text(encoding="utf-8"))
        )

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
        # This index grows with new diagnostics; held-out assertions above stay frozen.
        self.assertEqual(len(self.index["runs"]), scale["recorded_runs"])
        self.assertEqual(sum(int(r.get("measured_generation_calls") or 0) for r in self.index["runs"]), scale["measured_calls"])
        self.assertEqual(sum(int(r.get("prompt_tokens") or 0) + int(r.get("completion_tokens") or 0) for r in self.index["runs"]), scale["recorded_tokens"])
        self.assertGreaterEqual(scale["recorded_runs"], 40)
        self.assertGreaterEqual(scale["measured_calls"], 2069)
        self.assertGreaterEqual(scale["recorded_tokens"], 1999916)
        self.assertEqual(0.0, scale["external_api_cost_usd"])
        heldout = next(
            row
            for row in scale["turning_points"]
            if row["prefix"] == "typed_exact_budget_heldout_qwen_v1"
        )
        self.assertEqual(330, heldout["calls"])
        self.assertAlmostEqual(103.2, heldout["minutes"], places=1)
        sweep = next(
            row
            for row in scale["turning_points"]
            if row["prefix"] == "typed_budget_sweep_dev_qwen_v1"
        )
        self.assertEqual(324, sweep["calls"])
        self.assertAlmostEqual(123.3, sweep["minutes"], places=1)

    def test_new_diagnostic_changes_archive_totals_not_frozen_turning_points(self) -> None:
        index = copy.deepcopy(self.index)
        index["runs"].append({"prefix": "fixture-new-diagnostic", "measured_generation_calls": 7,
                              "prompt_tokens": 10, "completion_tokens": 11,
                              "external_api_cost_usd": 0.0})
        index["totals"]["runs"] += 1
        updated = compute_experiment_scale(index)
        self.assertEqual(self.experiment_scale["recorded_runs"] + 1, updated["recorded_runs"])
        self.assertEqual(self.experiment_scale["measured_calls"] + 7, updated["measured_calls"])
        self.assertEqual(self.experiment_scale["recorded_tokens"] + 21, updated["recorded_tokens"])
        self.assertEqual(self.experiment_scale["turning_points"], updated["turning_points"])

    def test_durable_store_rescue_preserves_benefit_and_controls(self) -> None:
        rescue = self.durable_store_rescue
        self.assertEqual(12, rescue["memory_correct"])
        self.assertEqual(18, rescue["durable_correct"])
        self.assertEqual(3, rescue["memory_harmful_executions"])
        self.assertEqual(0, rescue["durable_harmful_executions"])
        self.assertEqual(6, rescue["helpful_route_changes"])
        self.assertEqual(0, rescue["harmful_route_changes"])
        self.assertEqual(12, rescue["negative_control_cases"])
        self.assertEqual(0, rescue["control_route_changes"])

    def test_budget_sensitivity_keeps_typed_decisive_evidence(self) -> None:
        sensitivity = self.budget_sensitivity
        typed = next(
            row
            for row in sensitivity["methods"]
            if row["method"] == "typed_card_retention"
        )
        at_192 = next(
            point for point in typed["points"] if point["budget_tokens"] == 192
        )
        self.assertEqual(1.0, at_192["audited_stable_route_accuracy"])
        self.assertEqual(1.0, at_192["critical_retention_rate"])
        self.assertAlmostEqual(0.9777777777777779, at_192["stable_visible_card_recall"])
        self.assertEqual(2, sensitivity["typed_192_missing_nondecisive_card_records"])

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
