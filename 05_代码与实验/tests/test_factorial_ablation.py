from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("factorial", ROOT / "scripts/analyze_factorial_ablation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FactorialAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load()
        cls.result = cls.module.analyze()

    def cell(self, method: str, verifier: str) -> dict:
        return self.result["cells"][f"{method}|{verifier}"]

    def test_two_by_two_matches_frozen_heldout_records(self) -> None:
        expected = {  # (correct, harmful) of 33, from the frozen held-out raw trace
            ("task_aware_summary", "direct"): (11, 18),
            ("task_aware_summary", "audit"): (30, 3),
            ("typed_card_retention", "direct"): (20, 7),
            ("typed_card_retention", "audit"): (30, 3),
        }
        for (method, verifier), (correct, harmful) in expected.items():
            with self.subTest(method=method, verifier=verifier):
                cell = self.cell(method, verifier)
                self.assertEqual((cell["correct"], cell["harmful"]), (correct, harmful))
                self.assertEqual(cell["contexts"], 33)

    def test_memory_effect_vanishes_under_audit(self) -> None:
        interaction = self.result["interaction_correct"]
        self.assertGreater(interaction["memory_effect_without_audit"], 0)
        self.assertEqual(interaction["memory_effect_with_audit"], 0)

    def test_residual_audit_harm_is_only_hidden_holds_and_registry_removes_it(self) -> None:
        residual = self.result["residual_harmful_after_audit"]
        self.assertTrue(residual)
        for row in residual:
            self.assertEqual(row["critical_kind"], "ACTIVE_HOLD")
            self.assertEqual(row["condition"], "remove_action_critical")
            self.assertEqual(row["after_registry"], "HANDOFF")
        for method in ("task_aware_summary", "typed_card_retention"):
            self.assertEqual(self.cell(method, "audit+registry")["harmful"], 0)

    def test_registry_reread_never_reduces_safe_autonomy(self) -> None:
        for method in self.module.METHODS:
            with self.subTest(method=method):
                self.assertGreaterEqual(self.cell(method, "audit+registry")["safe_autonomous"],
                                        self.cell(method, "audit")["safe_autonomous"])
                self.assertLessEqual(self.cell(method, "audit+registry")["harmful"],
                                     self.cell(method, "audit")["harmful"])

    def test_secondary_ablation_is_a_different_build_and_kept_separate(self) -> None:
        secondary = self.result["secondary_router_ablation"]
        self.assertNotIn(self.result["primary_model_digest"], secondary["model_digests"])

    def test_written_bundle_matches_current_analysis(self) -> None:
        audit_path = ROOT / "results/factorial_ablation_heldout_posthoc_v1_audit.json"
        if not audit_path.exists():
            self.skipTest("bundle not written")
        saved = json.loads(audit_path.read_text(encoding="utf-8"))["result"]
        self.assertEqual(saved["cells"], self.result["cells"])
        self.assertEqual(saved["contrasts"], self.result["contrasts"])
        self.assertEqual(saved["primary_source_sha256"], self.result["primary_source_sha256"])


if __name__ == "__main__":
    unittest.main()
