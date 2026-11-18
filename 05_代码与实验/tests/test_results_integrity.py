from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("integrity", ROOT / "scripts/verify_results_integrity.py")
integrity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(integrity)


class ResultsIntegrityTests(unittest.TestCase):
    def test_repository_results_match_ledger(self) -> None:
        self.assertEqual(integrity.check(), [])

    def test_tampering_is_detected_and_append_refuses_to_launder_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            ledger = results / "SHA256SUMS"
            (results / "run_v1_raw.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
            self.assertEqual(integrity.append(results, ledger), ["run_v1_raw.jsonl"])
            self.assertEqual(integrity.check(results, ledger), [])

            (results / "run_v2_raw.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertTrue(any("not in ledger" in p for p in integrity.check(results, ledger)))
            integrity.append(results, ledger)

            (results / "run_v1_raw.jsonl").write_text('{"a": 2}\n', encoding="utf-8")
            self.assertIn("changed frozen file: run_v1_raw.jsonl", integrity.check(results, ledger))
            with self.assertRaises(SystemExit):
                integrity.append(results, ledger)

            (results / "run_v1_raw.jsonl").unlink()
            self.assertIn("missing ledgered file: run_v1_raw.jsonl", integrity.check(results, ledger))


if __name__ == "__main__":
    unittest.main()
