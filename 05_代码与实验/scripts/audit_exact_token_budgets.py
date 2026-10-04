from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.token_budget import OllamaRawTokenCounter, TokenCounter


COMPACTED_STRATEGIES = frozenset(
    {"tail_truncation", "generic_summary", "rule_pinning", "selective_hitl"}
)


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def git_provenance() -> dict[str, object]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_worktree_dirty_at_start": None}
    return {
        "git_commit": revision,
        "git_worktree_dirty_at_start": bool(dirty),
    }


def output_paths(prefix: str, *, results_dir: Path | None = None) -> dict[str, Path]:
    directory = ROOT / "results" if results_dir is None else results_dir
    return {
        "raw": directory / f"{prefix}_raw.jsonl",
        "summary": directory / f"{prefix}_summary.csv",
        "audit": directory / f"{prefix}_audit.json",
        "manifest": directory / f"{prefix}_manifest.json",
    }


def assert_paths_available(paths: dict[str, Path]) -> None:
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite token audit artifacts: {existing}")


def input_records(config: dict[str, object]) -> list[dict[str, object]]:
    raw_paths = config.get("input_artifacts")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("input_artifacts must be a non-empty list")
    records: list[dict[str, object]] = []
    for relative in raw_paths:
        path = ROOT / str(relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            payload = json.loads(line)
            required = {
                "scenario_id",
                "strategy",
                "active_context",
                "active_context_estimated_tokens",
                "model_id",
                "model_digest",
            }
            if not isinstance(payload, dict) or not required.issubset(payload):
                raise ValueError(f"invalid source record {path}:{index + 1}")
            records.append(
                {
                    "source_artifact": str(path.relative_to(ROOT)),
                    "source_row": index + 1,
                    **payload,
                }
            )
    expected = int(config["expected_records"])
    if len(records) != expected:
        raise ValueError(f"expected {expected} source records, found {len(records)}")
    keys = {
        (record["source_artifact"], record["scenario_id"], record["strategy"])
        for record in records
    }
    if len(keys) != len(records):
        raise ValueError("source artifacts contain duplicate scenario/strategy records")
    return records


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("provider") != "ollama_raw_generate":
        raise ValueError("exact token audit supports Ollama raw generate only")
    records = input_records(config)
    if {str(record["strategy"]) for record in records} != {
        "full_context",
        *COMPACTED_STRATEGIES,
    }:
        raise ValueError("unexpected compaction strategy set")
    source_models = {str(record["model_id"]) for record in records}
    source_digests = {str(record["model_digest"]) for record in records}
    if source_models != {str(config["model"])} or len(source_digests) != 1:
        raise ValueError("source artifacts must use one matching model and digest")
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    if int(estimates["raw_token_count_calls"]) != len(records):
        raise ValueError("raw_token_count_calls must equal source record count")
    if int(estimates["generated_probe_tokens"]) != len(records):
        raise ValueError("one discarded probe token is required per count")
    threshold = config.get("fairness_threshold")
    if not isinstance(threshold, dict) or set(threshold) != {
        "maximum_compacted_strategy_mean_token_ratio"
    }:
        raise ValueError("invalid fairness_threshold")
    maximum_ratio = float(threshold["maximum_compacted_strategy_mean_token_ratio"])
    if maximum_ratio < 1.0:
        raise ValueError("fairness ratio threshold must be at least one")
    prefix = str(config["output_prefix"])
    return {
        "status": "PLAN_ONLY_NO_TOKEN_COUNT_CALLS",
        "experiment": config["experiment"],
        "provider": config["provider"],
        "model": config["model"],
        "source_model_digest": next(iter(source_digests)),
        "source_artifacts": config["input_artifacts"],
        "source_records": len(records),
        "raw_token_count_calls": len(records),
        "generated_probe_tokens": len(records),
        "location": "local_machine",
        "external_api_cost_usd": 0.0,
        "fairness_threshold": threshold,
        "planning_estimates": estimates,
        "claim_scope": config["claim_scope"],
        "outputs_if_run": [
            str(path.relative_to(ROOT)) for path in output_paths(prefix).values()
        ],
    }


def count_records(
    records: list[dict[str, object]], counter: TokenCounter
) -> list[dict[str, object]]:
    counted: list[dict[str, object]] = []
    for record in records:
        text = str(record["active_context"])
        result = counter.count(text)
        estimated = int(record["active_context_estimated_tokens"])
        counted.append(
            {
                "source_artifact": record["source_artifact"],
                "source_row": record["source_row"],
                "scenario_id": record["scenario_id"],
                "strategy": record["strategy"],
                "heuristic_estimated_tokens": estimated,
                "exact_raw_tokens": result.token_count,
                "heuristic_to_exact_ratio": estimated / result.token_count,
                "text_sha256": result.text_sha256,
                "latency_ms": result.latency_ms,
                "counter_model_id": result.model_id,
                "source_model_digest": record["model_digest"],
            }
        )
    return counted


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = sorted(
        {
            (str(record["source_artifact"]), str(record["strategy"]))
            for record in records
        }
    )
    rows: list[dict[str, object]] = []
    for source, strategy in groups:
        items = [
            record
            for record in records
            if record["source_artifact"] == source and record["strategy"] == strategy
        ]
        exact = [int(item["exact_raw_tokens"]) for item in items]
        estimated = [int(item["heuristic_estimated_tokens"]) for item in items]
        rows.append(
            {
                "source_artifact": source,
                "strategy": strategy,
                "cases": len(items),
                "mean_exact_raw_tokens": statistics.mean(exact),
                "min_exact_raw_tokens": min(exact),
                "max_exact_raw_tokens": max(exact),
                "mean_heuristic_tokens": statistics.mean(estimated),
                "mean_heuristic_to_exact_ratio": statistics.mean(
                    estimated[index] / exact[index] for index in range(len(items))
                ),
            }
        )
    return rows


def token_budget_audit(
    records: list[dict[str, object]],
    *,
    expected_records: int,
    maximum_ratio: float,
) -> dict[str, object]:
    if len(records) != expected_records:
        raise ValueError("token audit record count mismatch")
    keys = {
        (record["source_artifact"], record["scenario_id"], record["strategy"])
        for record in records
    }
    if len(keys) != len(records):
        raise ValueError("token audit contains duplicate source keys")
    summaries = summarize(records)
    source_checks: list[dict[str, object]] = []
    for source in sorted({str(row["source_artifact"]) for row in summaries}):
        compacted = [
            row
            for row in summaries
            if row["source_artifact"] == source
            and row["strategy"] in COMPACTED_STRATEGIES
        ]
        means = {str(row["strategy"]): float(row["mean_exact_raw_tokens"]) for row in compacted}
        ratio = max(means.values()) / min(means.values())
        source_checks.append(
            {
                "source_artifact": source,
                "compacted_strategy_mean_tokens": means,
                "largest_to_smallest_mean_ratio": ratio,
                "budget_matched_within_threshold": ratio <= maximum_ratio,
            }
        )
    fair = all(bool(check["budget_matched_within_threshold"]) for check in source_checks)
    errors = [
        abs(float(record["heuristic_to_exact_ratio"]) - 1.0)
        for record in records
    ]
    return {
        "status": "BUDGET_MATCH_CONFIRMED" if fair else "BUDGET_MISMATCH_CONFIRMED",
        "analysis_scope": "exact raw-token re-audit of completed development pilots",
        "observations": {
            "records": len(records),
            "sources": len(source_checks),
            "maximum_absolute_heuristic_ratio_error": max(errors),
            "mean_absolute_heuristic_ratio_error": statistics.mean(errors),
        },
        "fairness_threshold": {
            "maximum_compacted_strategy_mean_token_ratio": maximum_ratio
        },
        "source_checks": source_checks,
        "strategy_summaries": summaries,
        "recommendation": (
            "OLD_PILOTS_MAY_SUPPORT_BUDGET_MATCHED_COMPARISON"
            if fair
            else "DO_NOT_USE_OLD_PILOTS_TO_RANK_COMPACTION_METHODS"
        ),
        "limitations": [
            "Counts cover raw active-context text only, excluding the shared downstream routing prompt and chat template.",
            "One discarded output token is generated per count because Ollama has no standalone tokenizer endpoint.",
            "This audit measures context length, not information retention or task quality.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal token audit requires a clean pre-committed worktree")
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    base_manifest = {
        **plan,
        **provenance,
        "status": "RUNNING",
        "started_at_utc": started.isoformat(),
        "started_at_hong_kong": started.astimezone(
            ZoneInfo("Asia/Hong_Kong")
        ).isoformat(),
        "python_version": platform.python_version(),
        "config_snapshot": config,
    }
    with paths["manifest"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(base_manifest, ensure_ascii=False, indent=2) + "\n")
    paths["raw"].touch(exist_ok=False)
    counted: list[dict[str, object]] = []
    try:
        counter = OllamaRawTokenCounter(
            model=str(config["model"]),
            base_url=str(config["base_url"]),
            timeout_seconds=float(config["timeout_seconds"]),
            seed=int(config["seed"]),
        )
        counted = count_records(input_records(config), counter)
        with paths["raw"].open("a", encoding="utf-8") as handle:
            for record in counted:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        summary = summarize(counted)
        with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
        maximum_ratio = float(
            config["fairness_threshold"][
                "maximum_compacted_strategy_mean_token_ratio"
            ]
        )
        audit = token_budget_audit(
            counted,
            expected_records=int(config["expected_records"]),
            maximum_ratio=maximum_ratio,
        )
        paths["audit"].write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        finished = datetime.now(timezone.utc)
        manifest = {
            **base_manifest,
            "status": "COMPLETED",
            "finished_at_utc": finished.isoformat(),
            "finished_at_hong_kong": finished.astimezone(
                ZoneInfo("Asia/Hong_Kong")
            ).isoformat(),
            "duration_seconds": time.perf_counter() - timer,
            "raw_token_count_calls_completed": len(counted),
            "generated_probe_tokens": len(counted),
            "total_exact_raw_tokens_counted": sum(
                int(record["exact_raw_tokens"]) for record in counted
            ),
            "counter_model_id": counted[0]["counter_model_id"],
            "external_api_cost_usd": 0.0,
            "direction_recommendation": audit["recommendation"],
        }
        paths["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (Exception, KeyboardInterrupt) as exc:
        failed = {
            **base_manifest,
            "status": "ABORTED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
            "duration_seconds": time.perf_counter() - timer,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_records": len(counted),
        }
        paths["manifest"].write_text(
            json.dumps(failed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "token_budget_audit.json",
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    print(json.dumps(build_plan(config), ensure_ascii=False, indent=2))
    if args.run != args.acknowledge_experiment_plan:
        raise SystemExit("Both run flags must be supplied together")
    if args.run:
        run(config)


if __name__ == "__main__":
    main()
