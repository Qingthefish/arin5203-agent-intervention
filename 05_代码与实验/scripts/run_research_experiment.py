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

from platform_agent_eval.dataset_audit import audit_scenario_set
from platform_agent_eval.baselines import build_baseline_predictions
from platform_agent_eval.model_routing import (
    GenerationConfig,
    ModelRouter,
    OllamaClient,
    SCOPED_PROMPT_TEMPLATE_VERSION,
    generation_for_sample,
)
from platform_agent_eval.research_metrics import (
    grouped_bootstrap_intervals,
    summarize_predictions,
)
from platform_agent_eval.research_pipeline import (
    ABLATION_EXCLUSIONS,
    ablate_prepared_cases,
    fit_three_way_policy,
    hard_guard_predictions,
    predict_prepared,
    prepare_cases,
)
from platform_agent_eval.research_scenarios import build_research_scenarios
from platform_agent_eval.scenarios import stratified_grouped_split, validate_scenario_set
from platform_agent_eval.simulator import check_hard_constraints
from platform_agent_eval.uncertainty import aggregate_critic_samples

MIN_RECOMMENDED_BOOTSTRAP_FAMILIES = 5


def _json_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_scenarios_and_splits(
    config: dict[str, object],
):
    scenarios = build_research_scenarios()
    selected_ids = config.get("base_task_ids")
    if selected_ids is not None:
        selected = {str(item) for item in selected_ids}
        scenarios = [
            case for case in scenarios if case.gold.base_task_id in selected
        ]
        found = {case.gold.base_task_id for case in scenarios}
        if found != selected:
            raise ValueError(
                f"Unknown or missing base_task_ids: {sorted(selected - found)}"
            )
    validate_scenario_set(scenarios)

    fixed = config.get("fixed_family_splits")
    if fixed is None:
        splits = stratified_grouped_split(scenarios, seed=int(config["seed"]))
    else:
        family_splits = {str(key): str(value) for key, value in fixed.items()}
        families = {case.gold.base_task_id for case in scenarios}
        if set(family_splits) != families:
            raise ValueError("fixed_family_splits must cover every selected family")
        if set(family_splits.values()) != {"train", "dev", "test"}:
            raise ValueError("fixed_family_splits must include train, dev, and test")
        splits = {
            case.gold.scenario_id: family_splits[case.gold.base_task_id]
            for case in scenarios
        }
    return scenarios, splits


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != "research_v3":
        raise ValueError("Formal runner requires scenario_set=research_v3")
    if config.get("provider") != "ollama":
        raise ValueError("Formal runner currently supports local Ollama only")
    if config.get("prompt_template") != SCOPED_PROMPT_TEMPLATE_VERSION:
        raise ValueError("Formal runner requires the scoped v3 prompt")
    if list(config.get("routing_modes", [])) != ["three_way"]:
        raise ValueError("Formal runner samples exactly one three-way critic")

    scenarios, _ = select_scenarios_and_splits(config)
    audit = audit_scenario_set(scenarios)
    if audit.errors:
        raise ValueError(f"Dataset audit has {len(audit.errors)} error(s)")
    hard = sum(bool(check_hard_constraints(case.policy_input)) for case in scenarios)
    eligible = len(scenarios) - hard
    repeats = int(config["repeats"])
    prefix = str(config["output_prefix"])
    return {
        "status": "EXPERIMENT_PLAN_NO_MODEL_CALLS_YET",
        "dataset": "research_v3",
        "dataset_sha256": _json_hash([asdict(case) for case in scenarios]),
        "config_sha256": _json_hash(config),
        "model": config["model"],
        "provider": "ollama",
        "location": "local_machine",
        "base_tasks": len({case.gold.base_task_id for case in scenarios}),
        "cases": len(scenarios),
        "hard_guarded_cases": hard,
        "critic_eligible_cases": eligible,
        "samples_per_case": repeats,
        "measured_generation_calls": eligible * repeats,
        "warmup_calls": 1,
        "temperature": config["temperature"],
        "base_seed": config["seed"],
        "external_api_cost_usd": 0.0,
        "planning_estimates": config.get("planning_estimates", {}),
        "outputs_if_run": [
            f"results/{prefix}_samples.jsonl",
            f"results/{prefix}_aggregates.jsonl",
            f"results/{prefix}_predictions.csv",
            f"results/{prefix}_metrics.json",
            f"results/{prefix}_policy.json",
            f"results/{prefix}_manifest.json",
        ],
    }


def _output_paths(prefix: str) -> dict[str, Path]:
    results = ROOT / "results"
    return {
        "samples": results / f"{prefix}_samples.jsonl",
        "aggregates": results / f"{prefix}_aggregates.jsonl",
        "predictions": results / f"{prefix}_predictions.csv",
        "metrics": results / f"{prefix}_metrics.json",
        "policy": results / f"{prefix}_policy.json",
        "manifest": results / f"{prefix}_manifest.json",
    }


def _grouped_bootstrap_report(
    scenarios,
    prediction_sets,
    *,
    split: str,
    samples: int,
    seed: int,
) -> dict[str, object]:
    reference_predictions = next(iter(prediction_sets.values()))
    prediction_split_by_id = {
        item.scenario_id: item.split for item in reference_predictions
    }
    family_ids = {
        case.gold.base_task_id
        for case in scenarios
        if prediction_split_by_id.get(case.gold.scenario_id) == split
    }
    family_count = len(family_ids)
    if family_count < MIN_RECOMMENDED_BOOTSTRAP_FAMILIES:
        return {
            "status": "NOT_ESTIMABLE",
            "split": split,
            "family_count": family_count,
            "minimum_recommended_families": MIN_RECOMMENDED_BOOTSTRAP_FAMILIES,
            "reason": (
                "Too few independent task families for an interpretable grouped "
                "bootstrap interval. Point estimates remain descriptive only."
            ),
            "intervals_by_policy": None,
        }
    return {
        "status": "ESTIMATED",
        "split": split,
        "family_count": family_count,
        "minimum_recommended_families": MIN_RECOMMENDED_BOOTSTRAP_FAMILIES,
        "bootstrap_samples": samples,
        "intervals_by_policy": {
            policy_name: grouped_bootstrap_intervals(
                scenarios,
                predictions,
                split=split,
                samples=samples,
                seed=seed,
            )
            for policy_name, predictions in prediction_sets.items()
        },
    }


def run(config: dict[str, object]) -> dict[str, object]:
    plan = build_plan(config)
    prefix = str(config["output_prefix"])
    paths = _output_paths(prefix)
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    collisions = [str(path) for path in paths.values() if path.exists()]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite formal artifacts; choose a new output_prefix: "
            + ", ".join(collisions)
        )

    scenarios, splits = select_scenarios_and_splits(config)
    started = datetime.now(timezone.utc)
    started_timer = time.perf_counter()
    manifest = {
        **plan,
        "status": "RUNNING",
        "started_at_utc": started.isoformat(),
        "started_at_hong_kong": started.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "python_version": platform.python_version(),
        "config_snapshot": config,
        "split_by_scenario": splits,
    }
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    base_generation = GenerationConfig(
        model=str(config["model"]),
        temperature=float(config["temperature"]),
        seed=int(config["seed"]),
        max_tokens=int(config["max_tokens"]),
        timeout_seconds=float(config["timeout_seconds"]),
    )
    client = OllamaClient(str(config["base_url"]))
    samples_by_scenario = {}
    sample_rows: list[dict[str, object]] = []
    warmup = None
    try:
        warmup = client.generate(
            'Return exactly {"ready": true} as JSON.',
            base_generation,
        )
        with paths["samples"].open("x", encoding="utf-8") as sample_handle:
            for case in scenarios:
                if check_hard_constraints(case.policy_input):
                    continue
                scenario_samples = []
                for sample_index in range(int(config["repeats"])):
                    generation = generation_for_sample(base_generation, sample_index)
                    result = ModelRouter(
                        client,
                        generation,
                        "three_way",
                        prompt_template=SCOPED_PROMPT_TEMPLATE_VERSION,
                    )(case.policy_input)
                    scenario_samples.append(result)
                    row = {
                        "scenario_id": case.gold.scenario_id,
                        "base_task_id": case.gold.base_task_id,
                        "split": splits[case.gold.scenario_id],
                        "sample_index": sample_index,
                        "seed": generation.seed,
                        **asdict(result),
                    }
                    sample_rows.append(row)
                    sample_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    sample_handle.flush()
                samples_by_scenario[case.gold.scenario_id] = scenario_samples

        prepared = prepare_cases(scenarios, samples_by_scenario, splits)
        fitted = fit_three_way_policy(prepared)
        calibrated_predictions = [
            *predict_prepared(fitted, prepared),
            *hard_guard_predictions(scenarios, splits),
        ]
        baseline_predictions, baseline_thresholds = build_baseline_predictions(
            scenarios,
            samples_by_scenario,
            splits,
        )
        prediction_sets = {
            **baseline_predictions,
            "calibrated_three_way": calibrated_predictions,
        }
        fitted_policies = {"calibrated_three_way": fitted}
        for ablation_name, excluded in ABLATION_EXCLUSIONS.items():
            ablated = ablate_prepared_cases(
                prepared,
                excluded_features=excluded,
            )
            ablated_policy = fit_three_way_policy(ablated)
            fitted_policies[ablation_name] = ablated_policy
            prediction_sets[ablation_name] = [
                *predict_prepared(ablated_policy, ablated),
                *hard_guard_predictions(scenarios, splits),
            ]
        critic_only = ablate_prepared_cases(
            prepared,
            keep_prefixes=("critic_",),
        )
        critic_only_policy = fit_three_way_policy(critic_only)
        fitted_policies["ablation_critic_only"] = critic_only_policy
        prediction_sets["ablation_critic_only"] = [
            *predict_prepared(critic_only_policy, critic_only),
            *hard_guard_predictions(scenarios, splits),
        ]

        with paths["aggregates"].open("x", encoding="utf-8") as handle:
            for item in prepared:
                aggregate = aggregate_critic_samples(
                    samples_by_scenario[item.case.gold.scenario_id]
                )
                handle.write(
                    json.dumps(
                        {
                            "scenario_id": item.case.gold.scenario_id,
                            "base_task_id": item.case.gold.base_task_id,
                            "split": item.split,
                            "aggregate": asdict(aggregate),
                            "features": dict(item.features),
                            "targets": asdict(item.targets),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        prediction_rows = []
        for policy_name, predictions in prediction_sets.items():
            prediction_rows.extend(
                {
                    "policy": policy_name,
                    **asdict(prediction),
                    "decision": prediction.decision.value,
                }
                for prediction in predictions
            )
        with paths["predictions"].open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0]))
            writer.writeheader()
            writer.writerows(prediction_rows)

        summaries = {
            policy_name: {
                split: summarize_predictions(scenarios, predictions, split=split)
                for split in ("train", "dev", "test")
            }
            for policy_name, predictions in prediction_sets.items()
        }
        split_family_counts = {
            split: len(
                {
                    case.gold.base_task_id
                    for case in scenarios
                    if splits[case.gold.scenario_id] == split
                }
            )
            for split in ("train", "dev", "test")
        }
        metrics = {
            "claim_scope": config.get("claim_scope", "unspecified"),
            "split_family_counts": split_family_counts,
            "summaries": summaries,
            "test_family_bootstrap_ci": _grouped_bootstrap_report(
                scenarios,
                prediction_sets,
                split="test",
                samples=1000,
                seed=int(config["seed"]),
            ),
            "baseline_thresholds_selected_on_dev": baseline_thresholds,
        }
        paths["metrics"].write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        paths["policy"].write_text(
            json.dumps(
                {
                    name: asdict(policy)
                    for name, policy in fitted_policies.items()
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        finished = datetime.now(timezone.utc)
        manifest.update(
            {
                "status": "COMPLETE",
                "finished_at_utc": finished.isoformat(),
                "finished_at_hong_kong": finished.astimezone(
                    ZoneInfo("Asia/Hong_Kong")
                ).isoformat(),
                "duration_seconds": time.perf_counter() - started_timer,
                "measured_generation_calls_completed": len(sample_rows),
                "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in sample_rows),
                "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in sample_rows),
                "warmup_prompt_tokens": warmup.prompt_tokens,
                "warmup_completion_tokens": warmup.completion_tokens,
                "model_digest": next(
                    (row.get("model_digest") for row in sample_rows if row.get("model_digest")),
                    None,
                ),
                "frozen_thresholds": {
                    name: asdict(policy.thresholds)
                    for name, policy in fitted_policies.items()
                },
            }
        )
        paths["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception as exc:
        manifest.update(
            {
                "status": "FAILED",
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": time.perf_counter() - started_timer,
                "measured_generation_calls_completed": len(sample_rows),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        paths["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen calibrated research protocol")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "research_plan.json",
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    plan = build_plan(config)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.run:
        return
    if not args.acknowledge_experiment_plan:
        raise SystemExit(
            "Refusing to run: add --acknowledge-experiment-plan after reviewing the plan."
        )
    manifest = run(config)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "output_prefix": config["output_prefix"],
                "measured_generation_calls_completed": manifest[
                    "measured_generation_calls_completed"
                ],
                "duration_seconds": manifest["duration_seconds"],
                "prompt_tokens": manifest["prompt_tokens"],
                "completion_tokens": manifest["completion_tokens"],
                "external_api_cost_usd": manifest["external_api_cost_usd"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
