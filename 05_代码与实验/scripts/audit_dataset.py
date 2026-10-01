from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.dataset_audit import audit_scenario_set
from platform_agent_eval.research_scenarios import build_research_scenarios
from platform_agent_eval.scenarios import (
    build_expanded_scenarios,
    build_scoped_approval_scenarios,
    validate_scenario_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit scenario semantics and shortcuts")
    parser.add_argument(
        "--scenario-set",
        choices=("expanded", "scoped_v2", "research_v3"),
        default="research_v3",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    builders = {
        "expanded": build_expanded_scenarios,
        "scoped_v2": build_scoped_approval_scenarios,
        "research_v3": build_research_scenarios,
    }
    scenarios = builders[args.scenario_set]()
    validate_scenario_set(scenarios)
    audit = audit_scenario_set(scenarios)
    rendered = json.dumps(audit.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.strict and audit.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
