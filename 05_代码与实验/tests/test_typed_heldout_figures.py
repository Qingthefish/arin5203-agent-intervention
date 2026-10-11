from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plot_typed_heldout_presentation import compute_metrics, load_records


RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"


class TypedHeldoutPresentationFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metrics = compute_metrics(load_records(RAW))

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


if __name__ == "__main__":
    unittest.main()
