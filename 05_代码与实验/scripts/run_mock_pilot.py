from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.evaluation import evaluate_policy, summarize
from platform_agent_eval.policies import POLICIES
from platform_agent_eval.scenarios import (
    build_expanded_scenarios,
    build_mock_scenarios,
    grouped_split,
    stratified_grouped_split,
    validate_scenario_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic local baselines.")
    parser.add_argument(
        "--expanded",
        action="store_true",
        help="Use the 20-base-task set and operation-stratified split.",
    )
    args = parser.parse_args()
    started_at_utc = datetime.now(timezone.utc)
    started_at_hk = started_at_utc.astimezone(ZoneInfo("Asia/Hong_Kong"))
    timer_start = time.perf_counter()
    config_path = ROOT / "configs" / "mock_pilot.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if args.expanded:
        scenarios = build_expanded_scenarios()
        validate_scenario_set(scenarios)
        splits = stratified_grouped_split(scenarios, seed=int(config["seed"]))
        output_prefix = "expanded_baselines"
        claim_scope = (
            "deterministic baselines on the expanded synthetic set; "
            "not language-model evidence"
        )
    else:
        scenarios = build_mock_scenarios()
        ratios = config["split_ratios"]
        splits = grouped_split(
            scenarios,
            seed=int(config["seed"]),
            train_ratio=float(ratios["train"]),
            dev_ratio=float(ratios["dev"]),
        )
        output_prefix = "mock_pilot"
        claim_scope = "plumbing validation only; not model-performance evidence"

    all_records = []
    summaries = []
    for name, policy in POLICIES.items():
        records = evaluate_policy(
            name,
            policy,
            scenarios,
            splits,
            config["human_costs"],
        )
        all_records.extend(records)
        summaries.append(summarize(records, split="all"))
        for split_name in ("train", "dev", "test"):
            split_records = [row for row in records if row.split == split_name]
            summaries.append(summarize(split_records, split=split_name))

    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    raw_path = results_dir / f"{output_prefix}_raw.jsonl"
    summary_path = results_dir / f"{output_prefix}_summary.csv"
    manifest_path = results_dir / f"{output_prefix}_manifest.json"

    with raw_path.open("w", encoding="utf-8") as handle:
        for record in all_records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    finished_at_utc = datetime.now(timezone.utc)
    finished_at_hk = finished_at_utc.astimezone(ZoneInfo("Asia/Hong_Kong"))
    duration_seconds = time.perf_counter() - timer_start
    manifest = {
        "pilot_type": "deterministic_mock",
        "claim_scope": claim_scope,
        "started_at_utc": started_at_utc.isoformat(),
        "finished_at_utc": finished_at_utc.isoformat(),
        "started_at_hong_kong": started_at_hk.isoformat(),
        "finished_at_hong_kong": finished_at_hk.isoformat(),
        "duration_seconds": duration_seconds,
        "python_version": platform.python_version(),
        "config_snapshot": config,
        "base_tasks": len({scenario.gold.base_task_id for scenario in scenarios}),
        "scenarios": len(scenarios),
        "scenario_set_sha256": hashlib.sha256(
            json.dumps(
                [asdict(scenario) for scenario in scenarios],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "policies": list(POLICIES),
        "split_by_scenario": splits,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(all_records)} raw evaluations to {raw_path}")
    print(f"Wrote {len(summaries)} policy/split summaries to {summary_path}")
    print("Mock results validate evaluation plumbing; they are not research findings.")


if __name__ == "__main__":
    main()
