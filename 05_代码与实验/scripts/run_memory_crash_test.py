from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_agent_eval.memory_crash_test import (  # noqa: E402
    load_crash_suite,
    run_crash_suite,
    write_json_report,
)


def _failure_message(record: dict[str, Any]) -> str:
    reasons: list[str] = []
    if not record["route_correct"]:
        reasons.append(
            f"expected {record['expected_decision']}, got {record['decision']}"
        )
    if record["harmful_execution"]:
        reasons.append("unsafe state-changing action was executed")
    if not record["decisive_provenance_complete"]:
        reasons.append("decisive proof lacks retained source provenance")
    return "; ".join(reasons) or "memory crash-test assertion failed"


def write_junit_report(report: dict[str, Any], path: Path) -> None:
    records = report["records"]
    failures = sum(not record["passed"] for record in records)
    root = ElementTree.Element(
        "testsuite",
        {
            "name": str(report["suite_id"]),
            "tests": str(len(records)),
            "failures": str(failures),
            "errors": "0",
        },
    )
    properties = ElementTree.SubElement(root, "properties")
    for name in ("schema_version", "proof_source", "source_sha256"):
        ElementTree.SubElement(
            properties,
            "property",
            {"name": name, "value": str(report[name])},
        )
    for record in records:
        case = ElementTree.SubElement(
            root,
            "testcase",
            {
                "classname": f"memory.{record['strategy']}.{record['case_id']}",
                "name": str(record["condition"]),
            },
        )
        if not record["passed"]:
            failure = ElementTree.SubElement(
                case,
                "failure",
                {
                    "type": "MemoryCrashRegression",
                    "message": _failure_message(record),
                },
            )
            failure.text = json.dumps(
                {
                    "expected_decision": record["expected_decision"],
                    "decision": record["decision"],
                    "retained_event_ids": record["retained_event_ids"],
                    "memory_card_ids": record["memory_card_ids"],
                    "state": record["state"],
                },
                ensure_ascii=False,
                indent=2,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.indent(root, space="  ")
    ElementTree.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


def _print_summary(report: dict[str, Any], json_path: Path, junit_path: Path) -> None:
    summary = report["summary"]
    print(f"Agent Memory Crash Test · {report['title']}")
    print(f"Proof source: {report['proof_source']}")
    print(
        f"Result: {summary['status']} · {summary['passed']}/{summary['runs']} passed · "
        f"{summary['harmful_executions']} harmful executions"
    )
    print("")
    print("Strategy                 Pass       Route acc.  Harmful  Noise changes")
    print("-----------------------  ---------  ----------  -------  -------------")
    for row in summary["by_strategy"]:
        print(
            f"{row['strategy'][:23]:23}  "
            f"{row['passed']:>3}/{row['runs']:<3}    "
            f"{row['route_accuracy'] * 100:>8.1f}%  "
            f"{row['harmful_executions']:>7}  "
            f"{row['noise_induced_route_changes']:>13}"
        )
    print("")
    print(f"JSON:  {json_path}")
    print(f"JUnit: {junit_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate matched memory siblings, validate action proof, and export "
            "machine-readable CI reports without calling a model."
        )
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--proof-source",
        choices=("memory", "registry"),
        default="memory",
        help="Validate compacted memory alone or augment it from the declared durable registry.",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="Run only this named strategy; repeat the flag to select several.",
    )
    parser.add_argument(
        "--allow-fail",
        action="store_true",
        help="Write reports but return exit code 0 even when a crash-test assertion fails.",
    )
    args = parser.parse_args()

    suite = load_crash_suite(args.spec)
    report = run_crash_suite(
        suite,
        proof_source=args.proof_source,
        strategy_names=tuple(args.strategies) if args.strategies else None,
    )
    stem = f"{suite.suite_id}_{args.proof_source}"
    json_path = args.output_dir / f"{stem}.json"
    junit_path = args.output_dir / f"{stem}.junit.xml"
    write_json_report(report, json_path)
    write_junit_report(report, junit_path)
    _print_summary(report, json_path, junit_path)
    if report["summary"]["status"] != "PASS" and not args.allow_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
