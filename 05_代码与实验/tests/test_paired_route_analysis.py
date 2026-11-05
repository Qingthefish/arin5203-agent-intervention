from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_paired_routes import (  # noqa: E402
    METHODS,
    SPLITS,
    analyze_split,
    cluster_sign_flip,
    family_cards,
    holm,
    mcnemar_exact,
)


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class PairedStatisticsTest(unittest.TestCase):
    def test_mcnemar_exact_matches_binomial(self) -> None:
        self.assertEqual(mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar_exact(4, 0), 0.125)
        self.assertAlmostEqual(mcnemar_exact(6, 0), 0.03125)
        self.assertAlmostEqual(mcnemar_exact(3, 3), 1.0)

    def test_sign_flip_is_exact_and_symmetric(self) -> None:
        self.assertEqual(cluster_sign_flip([0, 0, 0]), 1.0)
        self.assertAlmostEqual(cluster_sign_flip([1, 1, 1]), 2 / 8)
        self.assertAlmostEqual(cluster_sign_flip([2, -2]), 1.0)
        self.assertEqual(cluster_sign_flip([1, 1, 1]), cluster_sign_flip([-1, -1, -1]))

    def test_holm_is_monotone_and_bounded(self) -> None:
        adjusted = holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(adjusted["a"], 0.03)
        self.assertAlmostEqual(adjusted["c"], 0.06)
        self.assertAlmostEqual(adjusted["b"], 0.06)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in adjusted.values()))


class FrozenTraceAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        families = family_cards()
        cls.blocks = {split: analyze_split(_load(path), families) for split, path in SPLITS.items()}

    def test_replayed_audit_reproduces_every_frozen_decision(self) -> None:
        self.assertEqual(self.blocks["development"]["hold_reread_replay"]["audit_decisions_reproduced"], "189/189")
        self.assertEqual(self.blocks["heldout"]["hold_reread_replay"]["audit_decisions_reproduced"], "231/231")

    def test_hold_reread_never_adds_harm_or_interventions(self) -> None:
        for block in self.blocks.values():
            for method in METHODS:
                row = block["hold_reread_replay"]["by_method"][method]
                self.assertLessEqual(row["reread_harmful"], row["audit_harmful"])
                self.assertLessEqual(
                    row["reread_unnecessary_intervention"], row["audit_unnecessary_intervention"]
                )
                self.assertGreaterEqual(row["reread_correct"], row["audit_correct"])

    def test_heldout_headline_counts(self) -> None:
        heldout = self.blocks["heldout"]
        typed = heldout["paired_tests"]["correct"]["typed_card_retention"]
        self.assertEqual((typed["audit_better"], typed["audit_worse"]), (10, 0))
        harm = heldout["paired_tests"]["harmful"]["typed_card_retention"]
        self.assertEqual((harm["audit_better"], harm["audit_worse"]), (4, 0))
        self.assertEqual(heldout["paired_tests"]["correct"]["typed_card_retention"]["families"], 11)


if __name__ == "__main__":
    unittest.main()
