from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from index_experiment_artifacts import build_index, render_index


class ExperimentIndexTests(unittest.TestCase):
    def test_every_manifest_is_indexed_once(self) -> None:
        payload = build_index()
        manifests = list((ROOT / "results").glob("*_manifest.json"))
        prefixes = [run["prefix"] for run in payload["runs"]]
        self.assertEqual(len(manifests), len(prefixes))
        self.assertEqual(len(prefixes), len(set(prefixes)))

    def test_proof_card_gate_is_a_complete_frozen_bundle(self) -> None:
        payload = build_index()
        run = next(
            item
            for item in payload["runs"]
            if item["prefix"] == "proof_cards_deterministic_v1"
        )
        self.assertEqual("COMPLETED", run["status"])
        self.assertEqual("FROZEN_GATE_BUNDLE", run["evidence_tier"])
        self.assertEqual(0, run["measured_generation_calls"])
        self.assertTrue(all(run["artifacts"].values()))

    def test_failed_run_cannot_be_promoted_by_artifact_presence(self) -> None:
        payload = build_index()
        failed = [run for run in payload["runs"] if run["status"] == "FAILED"]
        self.assertTrue(failed)
        self.assertTrue(
            all(run["evidence_tier"] == "FAILED_OR_ABORTED" for run in failed)
        )

    def test_index_is_deterministic_and_contains_no_absolute_paths(self) -> None:
        first = render_index(build_index())
        second = render_index(build_index())
        self.assertEqual(first, second)
        self.assertNotIn(str(ROOT), first)

    def test_missing_status_is_visible_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            (results / "legacy_manifest.json").write_text(
                json.dumps({"model": "old"}), encoding="utf-8"
            )
            payload = build_index(results)
        self.assertEqual("MISSING", payload["runs"][0]["status"])
        self.assertEqual("MISSING_MANIFEST_STATUS", payload["warnings"][0]["code"])


if __name__ == "__main__":
    unittest.main()
