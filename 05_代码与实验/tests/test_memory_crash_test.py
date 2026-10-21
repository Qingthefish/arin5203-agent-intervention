from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.memory_crash_test import (
    CONDITIONS,
    load_crash_suite,
    run_crash_suite,
    select_event_ids,
    visible_event_ids,
)
from agent_memory_crash_test.cli import main as cli_main
from run_memory_crash_test import write_junit_report


SPEC = ROOT / "examples" / "memory_crash_test.json"
SCHEMA = ROOT / "schemas" / "agent-memory-crash-test-v1.schema.json"


class MemoryCrashTestKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = load_crash_suite(SPEC)

    def test_spec_generates_three_length_matched_siblings_per_case(self) -> None:
        self.assertEqual(2, len(self.suite.cases))
        for case in self.suite.cases:
            by_id = {event.event_id: event for event in case.events}
            critical = by_id[case.critical_event_id]
            noise = by_id[case.matched_noise_event_id]
            self.assertEqual(critical.role, noise.role)
            self.assertEqual(
                len(critical.content.encode("utf-8")),
                len(noise.content.encode("utf-8")),
            )
            self.assertEqual(
                len(case.events),
                len(visible_event_ids(case, "full_evidence")),
            )
            self.assertEqual(
                len(case.events) - 1,
                len(visible_event_ids(case, "remove_action_critical")),
            )
            self.assertEqual(
                len(case.events) - 1,
                len(visible_event_ids(case, "remove_matched_noise")),
            )

    def test_typed_memory_exposes_hidden_hold_boundary(self) -> None:
        report = run_crash_suite(
            self.suite,
            proof_source="memory",
            strategy_names=("typed-proof-memory",),
        )
        self.assertEqual("FAIL", report["summary"]["status"])
        self.assertEqual(6, report["summary"]["runs"])
        self.assertEqual(5, report["summary"]["passed"])
        self.assertEqual(1, report["summary"]["harmful_executions"])
        failure = next(record for record in report["records"] if not record["passed"])
        self.assertEqual("nonrefundable-hotel-hold", failure["case_id"])
        self.assertEqual("remove_action_critical", failure["condition"])
        self.assertEqual("AUTO_EXECUTE", failure["decision"])
        self.assertTrue(failure["state"]["harmful_mutation"])

    def test_registry_recovers_hidden_hold_without_changing_other_case(self) -> None:
        report = run_crash_suite(
            self.suite,
            proof_source="registry",
            strategy_names=("typed-proof-memory",),
        )
        self.assertEqual("PASS", report["summary"]["status"])
        self.assertEqual(6, report["summary"]["passed"])
        hold = next(
            record
            for record in report["records"]
            if record["case_id"] == "nonrefundable-hotel-hold"
            and record["condition"] == "remove_action_critical"
        )
        self.assertEqual("HANDOFF", hold["decision"])
        self.assertIn("hotel-hold", hold["runtime_card_ids"])
        self.assertFalse(hold["state"]["mutation_applied"])

    def test_recent_window_is_detected_as_a_regression(self) -> None:
        report = run_crash_suite(
            self.suite,
            proof_source="memory",
            strategy_names=("recent-window-3",),
        )
        row = report["summary"]["by_strategy"][0]
        self.assertEqual("FAIL", row["status"])
        self.assertLess(row["route_accuracy"], 1.0)

    def test_proof_source_selector_never_selects_deleted_events(self) -> None:
        strategy = next(
            item for item in self.suite.strategies if item.name == "typed-proof-memory"
        )
        for case in self.suite.cases:
            for condition in CONDITIONS:
                retained = set(select_event_ids(case, strategy, condition))
                visible = set(visible_event_ids(case, condition))
                self.assertTrue(retained.issubset(visible))

    def test_junit_export_preserves_failures_for_ci(self) -> None:
        report = run_crash_suite(
            self.suite,
            proof_source="memory",
            strategy_names=("typed-proof-memory",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            write_junit_report(report, path)
            root = ElementTree.parse(path).getroot()
        self.assertEqual("6", root.attrib["tests"])
        self.assertEqual("1", root.attrib["failures"])
        self.assertEqual(1, len(root.findall(".//failure")))

    def test_public_json_schema_has_expected_identity(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema",
            schema["$schema"],
        )
        self.assertEqual(
            "agent-memory-crash-test/v1",
            schema["properties"]["schema_version"]["const"],
        )
        self.assertIn("case", schema["$defs"])

    def test_cli_init_writes_a_semantically_valid_starter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "starter.json"
            self.assertEqual(0, cli_main(["--init", str(path)]))
            suite = load_crash_suite(path)
        self.assertEqual("my-agent-memory-gate", suite.suite_id)
        self.assertEqual(1, len(suite.cases))
        case = suite.cases[0]
        by_id = {event.event_id: event for event in case.events}
        self.assertEqual(
            len(by_id[case.critical_event_id].content.encode("utf-8")),
            len(by_id[case.matched_noise_event_id].content.encode("utf-8")),
        )

    def test_cli_validate_only_accepts_bundled_contract(self) -> None:
        self.assertEqual(
            0,
            cli_main(["--spec", str(SPEC), "--validate-only"]),
        )


if __name__ == "__main__":
    unittest.main()
