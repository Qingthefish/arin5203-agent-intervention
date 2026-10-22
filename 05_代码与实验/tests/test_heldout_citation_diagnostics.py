from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plot_typed_heldout_presentation import (
    DEFAULT_DEV_RAW,
    DEFAULT_DURABLE_AUDIT,
    DEFAULT_INDEX,
    DEFAULT_RAW,
    DEFAULT_SWEEP_RAW,
    DEFAULT_SWEEP_SUMMARY,
    compute_citation_diagnostics,
    compute_metrics,
    load_records,
    write_summary,
)


class HeldoutCitationDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metrics = compute_metrics(load_records(DEFAULT_RAW))
        cls.by_method = {
            row["method"]: row for row in cls.metrics["method_metrics"]
        }

    def test_existence_and_proof_membership_have_distinct_denominators(self) -> None:
        # Counts are occurrences across records, not globally unique event IDs.
        expected = {
            "full_context_ceiling": (103, 100, 0),
            "recent_window": (18, 0, 15),
            "neutral_summary": (167, 110, 0),
            "task_aware_summary": (190, 108, 0),
            "generic_pinning": (93, 75, 0),
            "ufold_lite": (104, 101, 0),
            "typed_card_retention": (112, 112, 0),
        }
        for method, (cited, proof_cited, empty) in expected.items():
            with self.subTest(method=method):
                row = self.by_method[method]
                diagnostic = row["citation_diagnostics"]
                self.assertEqual(33, diagnostic["records"])
                self.assertEqual(cited, diagnostic["parsed_cited_ids"])
                self.assertEqual(cited, diagnostic["cited_ids_present_in_active_memory"])
                self.assertEqual(0, diagnostic["cited_ids_absent_from_active_memory"])
                self.assertEqual(0, diagnostic["records_with_absent_cited_ids"])
                self.assertEqual(1.0, diagnostic["cited_id_existence_rate"])
                self.assertEqual(proof_cited, diagnostic["proof_source_cited_ids"])
                self.assertEqual(cited - proof_cited, diagnostic["non_proof_source_cited_ids"])
                self.assertEqual(empty, diagnostic["zero_citation_records"])
                self.assertEqual(empty, diagnostic["zero_citation_handoff_records"])
                self.assertEqual(0, diagnostic["zero_citation_other_records"])
                self.assertEqual(
                    row["proof_citation_precision"],
                    diagnostic["proof_source_selection_macro"],
                )
                self.assertAlmostEqual(
                    proof_cited / cited, diagnostic["proof_source_selection_micro"]
                )

    def test_macro_preserves_empty_handoff_convention_not_source_grounding(self) -> None:
        recent = self.by_method["recent_window"]["citation_diagnostics"]
        self.assertAlmostEqual(15 / 33, recent["proof_source_selection_macro"])
        self.assertEqual(0.0, recent["proof_source_selection_micro"])
        self.assertEqual(18, recent["imperfect_proof_source_records"])
        neutral = self.by_method["neutral_summary"]["citation_diagnostics"]
        self.assertAlmostEqual(0.7574203574203573, neutral["proof_source_selection_macro"])
        self.assertEqual(22, neutral["imperfect_proof_source_records"])
        self.assertNotAlmostEqual(
            neutral["proof_source_selection_macro"],
            neutral["proof_source_selection_micro"],
        )

    def test_all_context_routes_preserve_ufold_advantage_and_stable_tie(self) -> None:
        for method in ("neutral_summary", "task_aware_summary", "ufold_lite", "typed_card_retention"):
            self.assertEqual(22, self.by_method[method]["audited_stable_correct"])
            self.assertEqual(33, self.by_method[method]["all_cases"])
        self.assertEqual(31, self.by_method["ufold_lite"]["audited_all_correct"])
        self.assertEqual(30, self.by_method["typed_card_retention"]["audited_all_correct"])

    def test_parsed_id_check_detects_absence_independently_of_proof_score(self) -> None:
        diagnostic = compute_citation_diagnostics([
            {
                "source_event_ids": ["visible-noise"],
                "direct": {
                    "evidence_event_ids": ["visible-noise", "absent"],
                    "proof_citation_precision": 0.0,
                    "decision": "HANDOFF",
                },
            }
        ])
        self.assertEqual(1, diagnostic["cited_ids_absent_from_active_memory"])
        self.assertEqual(1, diagnostic["records_with_absent_cited_ids"])
        self.assertEqual(0.5, diagnostic["cited_id_existence_rate"])
        self.assertEqual(0, diagnostic["proof_source_cited_ids"])

    def test_zero_denominators_and_inconsistent_saved_fraction_are_explicit(self) -> None:
        rows = [
            {
                "source_event_ids": [],
                "direct": {
                    "evidence_event_ids": [],
                    "proof_citation_precision": float(decision == "HANDOFF"),
                    "decision": decision,
                },
            }
            for decision in ("HANDOFF", "AUTO_EXECUTE")
        ]
        diagnostic = compute_citation_diagnostics(rows)
        self.assertIsNone(diagnostic["cited_id_existence_rate"])
        self.assertIsNone(diagnostic["proof_source_selection_micro"])
        self.assertEqual(0.5, diagnostic["proof_source_selection_macro"])
        self.assertEqual(1, diagnostic["zero_citation_other_records"])
        rows[0]["direct"]["evidence_event_ids"] = ["a", "b"]
        rows[0]["direct"]["proof_citation_precision"] = 0.3
        with self.assertRaisesRegex(ValueError, "integer numerator"):
            compute_citation_diagnostics(rows)

    def test_summary_labels_post_hoc_scope_and_keeps_source_hashes(self) -> None:
        before_hash = hashlib.sha256(DEFAULT_RAW.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics.json"
            write_summary(
                self.metrics, {}, {}, {}, {}, {},
                DEFAULT_RAW, DEFAULT_DEV_RAW, DEFAULT_SWEEP_RAW,
                DEFAULT_SWEEP_SUMMARY, DEFAULT_DURABLE_AUDIT, DEFAULT_INDEX, output,
            )
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(before_hash, saved["sources"]["heldout_raw"]["sha256"])
        self.assertEqual(before_hash, hashlib.sha256(DEFAULT_RAW.read_bytes()).hexdigest())
        diagnostic = saved["analysis"]["post_hoc_citation_diagnostics"]
        self.assertEqual("POST_HOC_DERIVED_NO_MODEL_CALLS", diagnostic["status"])
        self.assertEqual(787, diagnostic["parsed_cited_ids"])
        self.assertEqual(0, diagnostic["cited_ids_absent_from_active_memory"])
        self.assertIn("zero-citation HANDOFF", diagnostic["metric_definitions"]["proof_source_selection_macro"])
        self.assertTrue(any("semantic entailment" in boundary for boundary in diagnostic["boundaries"]))


if __name__ == "__main__":
    unittest.main()
