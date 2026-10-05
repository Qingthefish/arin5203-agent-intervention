from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from serve_memory_crash_test import build_demo_payload


class MemoryCrashDemoTests(unittest.TestCase):
    def test_payload_replays_all_frozen_cases(self) -> None:
        payload = build_demo_payload()
        scenarios = payload["scenarios"]
        self.assertEqual(9, len(scenarios))
        self.assertEqual("COMPLETED", payload["trace"]["status"])
        self.assertEqual("deterministic", payload["trace"]["provider"])
        self.assertIsNone(payload["trace"]["model"])

    def test_each_domain_exposes_all_three_routes(self) -> None:
        payload = build_demo_payload()
        counts = Counter((item["domain"], item["decision"]) for item in payload["scenarios"])
        for domain in ("platform", "financial", "mas_travel"):
            for decision in ("AUTO_EXECUTE", "REQUEST_CONFIRMATION", "HANDOFF"):
                self.assertEqual(1, counts[(domain, decision)])

    def test_only_execute_projects_a_state_change(self) -> None:
        payload = build_demo_payload()
        for scenario in payload["scenarios"]:
            with self.subTest(case=scenario["case_id"]):
                changed = scenario["state_before"] != scenario["state_after"]
                self.assertEqual(scenario["decision"] == "AUTO_EXECUTE", changed)

    def test_debug_view_has_provenance_for_every_card(self) -> None:
        payload = build_demo_payload()
        for scenario in payload["scenarios"]:
            for card in scenario["cards"]:
                self.assertTrue(card["source_event_ids"])
                self.assertTrue(card["issuer_id"])
                self.assertTrue(card["target_id"])


if __name__ == "__main__":
    unittest.main()
