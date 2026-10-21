from __future__ import annotations

import json
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stderr, redirect_stdout
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

    def _load_payload(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_crash_suite(path)

    def test_nonboolean_security_flags_are_rejected_instead_of_coerced(self) -> None:
        paths = [
            ("cases", 0, "policy", "requires_clearance"),
            ("cases", 0, "policy", "requires_delegation"),
            ("cases", 0, "policy", "requires_recovery"),
            ("cases", 0, "proof_cards", 0, "authenticated"),
            ("cases", 0, "proof_cards", 0, "transferable"),
            ("cases", 1, "durable_store", "records", 0, "integrity_verified"),
        ]
        for path in paths:
            for value in ("false", "true", 0, 1, None, [], {}):
                payload = json.loads(SPEC.read_text())
                cursor = payload
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = value
                with self.subTest(path=path, value=value), self.assertRaisesRegex(ValueError, "Boolean"):
                    self._load_payload(payload)

    def test_real_false_authentication_is_not_promoted_to_authority(self) -> None:
        payload = json.loads(SPEC.read_text())
        for card in payload["cases"][0]["proof_cards"]:
            if card["kind"] == "DELEGATION":
                card["authenticated"] = False
        report = run_crash_suite(self._load_payload(payload), strategy_names=("typed-proof-memory",))
        record = next(r for r in report["records"] if r["case_id"] == payload["cases"][0]["case_id"]
                      and r["condition"] == "full_evidence")
        self.assertEqual("HANDOFF", record["decision"])

    def test_unknown_fields_and_missing_obligations_are_rejected(self) -> None:
        for path in ((), ("cases", 0), ("cases", 0, "policy"),
                     ("cases", 0, "action"), ("cases", 0, "proof_cards", 0),
                     ("cases", 0, "events", 0), ("cases", 0, "state"),
                     ("strategies", 0), ("cases", 1, "durable_store"),
                     ("cases", 1, "durable_store", "records", 0)):
            payload = json.loads(SPEC.read_text())
            cursor = payload
            for key in path:
                cursor = cursor[key]
            cursor["typo"] = True
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "unknown fields"):
                self._load_payload(payload)
        payload = json.loads(SPEC.read_text())
        del payload["cases"][0]["policy"]["requires_delegation"]
        with self.assertRaisesRegex(ValueError, "missing fields"):
            self._load_payload(payload)

    def test_deletion_events_must_distinguish_proof_from_noise(self) -> None:
        payload = json.loads(SPEC.read_text())
        case = payload["cases"][0]
        for card in case["proof_cards"]:
            if case["critical_event_id"] in card["source_event_ids"]:
                card["source_event_ids"] = [case["matched_noise_event_id"]]
        with self.assertRaisesRegex(ValueError, "critical event must support"):
            self._load_payload(payload)
        payload = json.loads(SPEC.read_text())
        case = payload["cases"][0]
        case["proof_cards"][0]["source_event_ids"].append(case["matched_noise_event_id"])
        with self.assertRaisesRegex(ValueError, "matched noise must not support"):
            self._load_payload(payload)

    def test_validate_only_checks_snapshot_sources_and_returns_input_error(self) -> None:
        payload = json.loads(SPEC.read_text())
        payload["strategies"] = [{
            "name": "bad-import", "selector": "snapshot",
            "snapshots": {condition: ["not-in-trace"] for condition in CONDITIONS},
        }]
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            path = Path(directory) / "spec.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(SystemExit) as raised:
                cli_main(["--spec", str(path), "--validate-only"])
        self.assertEqual(2, raised.exception.code)

    def test_report_label_cannot_escape_output_directory(self) -> None:
        payload = json.loads(SPEC.read_text())
        payload["suite_id"] = "../escaped"
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            path = root / "spec.json"
            path.write_text(json.dumps(payload))
            out = root / "reports"
            self.assertEqual(0, cli_main(["--spec", str(path), "--output-dir", str(out), "--allow-fail"]))
            self.assertEqual(2, len(list(out.iterdir())))
            self.assertTrue(all(p.parent == out for p in out.iterdir()))
            self.assertFalse((root / "escaped_memory.json").exists())


if __name__ == "__main__":
    unittest.main()
