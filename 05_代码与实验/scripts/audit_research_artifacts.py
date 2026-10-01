from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.artifact_audit import audit_research_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit completeness and claim scope for a research run"
    )
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    audit = audit_research_artifacts(ROOT / "results", args.prefix)
    payload = json.dumps(audit.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if audit.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
