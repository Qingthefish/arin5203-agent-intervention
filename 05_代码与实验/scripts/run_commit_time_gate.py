from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.commit_time_gate import (
    COMMIT_MODES,
    COMMIT_TIME_GATE_VERSION,
    FAMILIES,
    SCENARIO_CONDITIONS,
    evaluate_commit_gate,
    family_fixtures,
)
from platform_agent_eval.proof_cards import stable_hash


GATE_FIELDS = {
    "proposed_mode",
    "maximum_unsafe_executions",
    "maximum_duplicate_mutations",
    "maximum_false_blocking_rate",
    "minimum_stale_authorization_detection_rate",
    "maximum_fail_closed_violations",
    "minimum_action_state_consistency",
    "minimum_route_accuracy",
    "required_prepared_only_unsafe_executions",
    "required_unlocked_window_unsafe_executions",
}


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        raise FileExistsError(f"Refusing to overwrite commit-gate artifacts: {existing}")


def git_provenance() -> dict[str, object]:
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                               check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_worktree_dirty_at_start": None}
    return {"git_commit": revision, "git_worktree_dirty_at_start": bool(dirty)}


def _gate(config: dict[str, object]) -> dict[str, object]:
    raw = config.get("commit_gate")
    if not isinstance(raw, dict) or set(raw) != GATE_FIELDS:
        raise ValueError(f"commit_gate fields must be exactly {sorted(GATE_FIELDS)}")
    if raw["proposed_mode"] not in COMMIT_MODES:
        raise ValueError("proposed_mode must be a supported commit mode")
    return {key: value if key == "proposed_mode" else (float(value) if "rate" in key or "consistency" in key
                                                       or "accuracy" in key else int(value))
            for key, value in raw.items()}


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != COMMIT_TIME_GATE_VERSION:
        raise ValueError("commit-gate scenario-set version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("commit-time gate must be deterministic and model-free")
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected = {"base_families": len(FAMILIES), "conditions": len(SCENARIO_CONDITIONS),
                "commit_modes": len(COMMIT_MODES),
                "scenario_runs": len(FAMILIES) * len(SCENARIO_CONDITIONS) * len(COMMIT_MODES),
                "measured_generation_calls": 0}
    for field, value in expected.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": COMMIT_TIME_GATE_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic",
        "model": None,
        "location": "local_machine",
        "commit_modes": list(COMMIT_MODES),
        "conditions": {name: {"expected_executed": executed, "expected_decision": decision.value,
                              "stale_evidence": stale}
                       for name, (executed, decision, stale) in SCENARIO_CONDITIONS.items()},
        "fixture_sha256": stable_hash(family_fixtures()),
        "config_sha256": stable_hash(config),
        "measured_generation_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "planning_estimates": estimates,
        "commit_gate": _gate(config),
        "outputs_if_run": [str(path.relative_to(ROOT))
                           for path in output_paths(str(config["output_prefix"])).values()],
    }


def commit_gate_audit(records: list[dict[str, object]], summaries: list[dict[str, object]],
                      *, gate: dict[str, object]) -> dict[str, object]:
    expected_runs = len(FAMILIES) * len(SCENARIO_CONDITIONS) * len(COMMIT_MODES)
    keys = {(r["mode"], r["condition"], r["family_id"]) for r in records}
    if len(records) != expected_runs or len(keys) != expected_runs:
        raise ValueError("commit-gate record coverage mismatch")
    by_mode = {str(row["mode"]): row for row in summaries}
    proposed = by_mode[str(gate["proposed_mode"])]
    rules = {
        "proposed_mode_has_no_unsafe_execution":
            proposed["unsafe_executions"] <= gate["maximum_unsafe_executions"],
        "proposed_mode_has_no_duplicate_mutation":
            proposed["duplicate_mutations"] <= gate["maximum_duplicate_mutations"],
        "proposed_mode_does_not_block_legitimate_actions":
            proposed["false_blocking_rate"] <= gate["maximum_false_blocking_rate"],
        "proposed_mode_detects_all_stale_authorization":
            proposed["stale_authorization_detection_rate"] >= gate["minimum_stale_authorization_detection_rate"],
        "proposed_mode_fails_closed_without_registry":
            proposed["fail_closed_violations"] <= gate["maximum_fail_closed_violations"],
        "proposed_mode_keeps_validated_and_applied_evidence_equal":
            (proposed["action_state_consistency"] or 0.0) >= gate["minimum_action_state_consistency"],
        "proposed_mode_routes_match_expectations":
            proposed["route_accuracy"] >= gate["minimum_route_accuracy"],
        "stale_authorization_counterfactual_is_present":
            by_mode["prepared_only"]["unsafe_executions"] == gate["required_prepared_only_unsafe_executions"],
        "unlocked_recheck_window_is_observable":
            by_mode["recheck_unlocked"]["unsafe_executions"] == gate["required_unlocked_window_unsafe_executions"],
    }
    passed = all(rules.values())
    return {
        "status": "PASS_COMMIT_TIME_GATE" if passed else "FAIL_COMMIT_TIME_GATE",
        "analysis_scope": "development-only deterministic prepare/commit simulation of stale authorization",
        "pre_specified_gate": rules,
        "thresholds": gate,
        "mode_observations": summaries,
        "limitations": [
            "This is a deterministic simulator test, not an LLM experiment.",
            "Atomicity holds for one in-process registry and state store; distributed commit, clock skew, "
            "partitions and crash recovery are not modeled.",
            "Interleaving is injected at one named point between the evidence check and the mutation.",
            "Scenarios reuse three synthetic durable-store families and assume authenticated proof cards.",
            "Expected outcomes and thresholds were set from the design; they are not learned or tuned values.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal commit-gate run requires a clean worktree")
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records, summaries = evaluate_commit_gate()
    audit = commit_gate_audit(records, summaries, gate=_gate(config))
    with paths["raw"].open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    paths["audit"].write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finished = datetime.now(timezone.utc)
    manifest = {
        **plan, **provenance,
        "status": "COMPLETED",
        "started_at_utc": started.isoformat(),
        "started_at_hong_kong": started.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "finished_at_utc": finished.isoformat(),
        "finished_at_hong_kong": finished.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "duration_seconds": time.perf_counter() - timer,
        "python_version": platform.python_version(),
        "config_snapshot": config,
        "measured_generation_calls_completed": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "gate_status": audit["status"],
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the commit-time evidence freshness gate")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if not args.run:
        print(json.dumps(build_plan(config), ensure_ascii=False, indent=2))
        return
    if not args.acknowledge_experiment_plan:
        raise SystemExit("--run requires --acknowledge-experiment-plan")
    run(config)


if __name__ == "__main__":
    main()
