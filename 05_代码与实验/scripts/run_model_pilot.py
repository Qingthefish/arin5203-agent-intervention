from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.evaluation import evaluate_policy, summarize
from platform_agent_eval.model_routing import (
    GenerationConfig,
    ModelRouter,
    OllamaClient,
    PROMPT_TEMPLATE_VERSION,
    SCOPED_PROMPT_TEMPLATE_VERSION,
    generation_for_sample,
)
from platform_agent_eval.policies import PolicyDefinition
from platform_agent_eval.research_scenarios import build_research_scenarios
from platform_agent_eval.scenarios import (
    build_expanded_scenarios,
    build_mock_scenarios,
    build_scoped_approval_scenarios,
    stratified_grouped_split,
    validate_scenario_set,
)
from platform_agent_eval.simulator import check_hard_constraints


def load_config(path: Path) -> dict[str, object]:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def scenario_set(config: dict[str, object]):
    name = str(config.get("scenario_set", "mock"))
    if name == "mock":
        return build_mock_scenarios()
    if name == "expanded":
        scenarios = build_expanded_scenarios()
        validate_scenario_set(scenarios)
        return scenarios
    if name == "scoped_v2":
        if config.get("prompt_template") != SCOPED_PROMPT_TEMPLATE_VERSION:
            raise ValueError(
                "scoped_v2 requires platform-intervention-v3-scoped"
            )
        scenarios = build_scoped_approval_scenarios()
        validate_scenario_set(scenarios)
        return scenarios
    if name == "research_v3":
        if config.get("prompt_template") != SCOPED_PROMPT_TEMPLATE_VERSION:
            raise ValueError(
                "research_v3 requires platform-intervention-v3-scoped"
            )
        scenarios = build_research_scenarios()
        validate_scenario_set(scenarios)
        return scenarios
    raise ValueError(f"Unknown scenario_set: {name}")


def scenario_set_hash(scenarios) -> str:
    def canonicalize(value):
        if isinstance(value, dict):
            return {
                key: canonicalize(item)
                for key, item in value.items()
                if not (
                    (key == "approval_evidence" and item is None)
                    or (key == "approval_requirements" and item == ())
                )
            }
        if isinstance(value, (list, tuple)):
            return [canonicalize(item) for item in value]
        return value

    # Additive v2 fields with their legacy defaults are omitted so hashes from
    # the frozen v1 pilot remain reproducible after the schema extension.
    payload = [canonicalize(asdict(case)) for case in scenarios]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def experiment_plan(config: dict[str, object]) -> dict[str, object]:
    scenarios = scenario_set(config)
    guarded = sum(bool(check_hard_constraints(case.policy_input)) for case in scenarios)
    eligible = len(scenarios) - guarded
    modes = list(config["routing_modes"])
    repeats = int(config["repeats"])
    inference_calls = eligible * len(modes) * repeats
    output_prefix = str(config.get("output_prefix", "model_pilot"))
    plan = {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "model": config["model"],
        "provider": config["provider"],
        "location": "local_machine",
        "base_tasks": len({case.gold.base_task_id for case in scenarios}),
        "cases": len(scenarios),
        "scenario_set_sha256": scenario_set_hash(scenarios),
        "hard_guarded_cases_per_policy": guarded,
        "llm_eligible_cases_per_policy": eligible,
        "routing_modes": modes,
        "repeats": repeats,
        "planned_measured_generation_calls": inference_calls,
        "warmup_calls": 1,
        "planned_total_generation_calls": inference_calls + 1,
        "planned_metadata_requests": 1,
        "planned_total_local_http_requests": inference_calls + 2,
        "temperature": config["temperature"],
        "seed": config["seed"],
        "max_output_tokens_per_call": config["max_tokens"],
        "prompt_template": config.get(
            "prompt_template",
            PROMPT_TEMPLATE_VERSION,
        ),
        "api_cost_usd": 0.0,
        "outputs_if_run": [
            f"results/{output_prefix}_raw.jsonl",
            f"results/{output_prefix}_summary.csv",
            f"results/{output_prefix}_manifest.json",
        ],
        "claim_scope": config.get(
            "claim_scope",
            "LLM routing feasibility and failure-mode pilot only",
        ),
    }
    if "planning_estimates" in config:
        plan["planning_estimates"] = config["planning_estimates"]
    return plan


def run(config: dict[str, object]) -> None:
    if config["provider"] != "ollama":
        raise ValueError("The current pilot runner supports local Ollama only")
    started_at_utc = datetime.now(timezone.utc)
    timer_start = time.perf_counter()
    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = str(config.get("output_prefix", "model_pilot"))
    raw_path = results_dir / f"{output_prefix}_raw.jsonl"
    summary_path = results_dir / f"{output_prefix}_summary.csv"
    manifest_path = results_dir / f"{output_prefix}_manifest.json"
    all_records = []
    summaries = []
    base_manifest = {
        **experiment_plan(config),
        "status": "RUNNING",
        "started_at_utc": started_at_utc.isoformat(),
        "started_at_hong_kong": started_at_utc.astimezone(
            ZoneInfo("Asia/Hong_Kong")
        ).isoformat(),
        "python_version": platform.python_version(),
        "prompt_template": config.get(
            "prompt_template",
            PROMPT_TEMPLATE_VERSION,
        ),
        "config_snapshot": config,
    }
    manifest_path.write_text(
        json.dumps(base_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    generation = GenerationConfig(
        model=str(config["model"]),
        temperature=float(config["temperature"]),
        seed=int(config["seed"]),
        max_tokens=int(config["max_tokens"]),
        timeout_seconds=float(config["timeout_seconds"]),
    )
    client = OllamaClient(str(config["base_url"]))
    try:
        warmup = client.generate(
            'Return exactly {"ready": true} as JSON.',
            generation,
        )
        scenarios = scenario_set(config)
        if str(config.get("scenario_set", "mock")) in {
            "expanded",
            "scoped_v2",
            "research_v3",
        }:
            splits = stratified_grouped_split(scenarios, seed=int(config["seed"]))
        else:
            splits = {case.gold.scenario_id: "pilot" for case in scenarios}
        for repeat in range(1, int(config["repeats"]) + 1):
            # Repeated samples must be independent enough to measure routing
            # disagreement. Reusing the same seed would create pseudo-repeats.
            repeat_generation = generation_for_sample(generation, repeat - 1)
            for mode in config["routing_modes"]:
                policy_name = f"prompt_{mode}_critic_r{repeat:02d}"
                policy = PolicyDefinition(
                    ModelRouter(
                        client,
                        repeat_generation,
                        str(mode),
                        prompt_template=str(
                            config.get("prompt_template", PROMPT_TEMPLATE_VERSION)
                        ),
                    ),
                    use_shared_hard_guard=True,
                )
                records = evaluate_policy(
                    policy_name,
                    policy,
                    scenarios,
                    splits,
                    config["human_costs"],
                )
                all_records.extend(records)
                summaries.append(summarize(records, split="all"))
                if str(config.get("scenario_set", "mock")) in {
                    "expanded",
                    "scoped_v2",
                    "research_v3",
                }:
                    for split_name in ("train", "dev", "test"):
                        split_records = [
                            record for record in records if record.split == split_name
                        ]
                        summaries.append(summarize(split_records, split=split_name))
    except Exception as exc:
        with raw_path.open("w", encoding="utf-8") as handle:
            for record in all_records:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        failed_at_utc = datetime.now(timezone.utc)
        failure_manifest = {
            **base_manifest,
            "status": "FAILED",
            "failed_at_utc": failed_at_utc.isoformat(),
            "failed_at_hong_kong": failed_at_utc.astimezone(
                ZoneInfo("Asia/Hong_Kong")
            ).isoformat(),
            "duration_seconds": time.perf_counter() - timer_start,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "partial_evaluation_records": len(all_records),
        }
        manifest_path.write_text(
            json.dumps(failure_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise

    with raw_path.open("w", encoding="utf-8") as handle:
        for record in all_records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    finished_at_utc = datetime.now(timezone.utc)
    manifest = {
        **base_manifest,
        "status": "COMPLETED",
        "finished_at_utc": finished_at_utc.isoformat(),
        "finished_at_hong_kong": finished_at_utc.astimezone(
            ZoneInfo("Asia/Hong_Kong")
        ).isoformat(),
        "duration_seconds": time.perf_counter() - timer_start,
        "warmup": asdict(warmup),
        "actual_evaluation_records": len(all_records),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(all_records)} model evaluation records to {raw_path}")
    print(f"Wrote {len(summaries)} summaries to {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan or explicitly run a local model intervention pilot."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "model_pilot.json",
        help="Pilot configuration JSON (default: configs/model_pilot.json).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run local inference instead of printing the plan.",
    )
    parser.add_argument(
        "--acknowledge-experiment-plan",
        action="store_true",
        help="Second guard required with --run after the plan is reviewed.",
    )
    args = parser.parse_args()
    config = load_config(args.config.resolve())
    if not args.run:
        print(json.dumps(experiment_plan(config), ensure_ascii=False, indent=2))
        return
    if not args.acknowledge_experiment_plan:
        parser.error("--run also requires --acknowledge-experiment-plan")
    run(config)


if __name__ == "__main__":
    main()
