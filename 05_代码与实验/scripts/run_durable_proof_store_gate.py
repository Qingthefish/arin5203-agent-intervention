from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.durable_proof_store import (
    CONDITIONS,
    DURABLE_PROOF_STORE_VERSION,
    build_durable_proof_cases,
    evaluate_durable_case,
)
from platform_agent_eval.proof_cards import stable_hash


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return asdict(value)


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
        raise FileExistsError(f"Refusing to overwrite durable-store artifacts: {existing}")


def git_provenance() -> dict[str, object]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_worktree_dirty_at_start": None}
    return {"git_commit": revision, "git_worktree_dirty_at_start": bool(dirty)}


def _gate(config: dict[str, object]) -> dict[str, float | int]:
    raw = config.get("durable_store_gate")
    if not isinstance(raw, dict):
        raise ValueError("durable_store_gate must be an object")
    expected = {
        "maximum_incorrect_durable_routes",
        "maximum_durable_harmful_executions",
        "required_memory_harmful_executions",
        "required_helpful_route_changes",
        "maximum_harmful_route_changes",
        "required_recovered_active_holds",
        "required_recovered_valid_authorities",
        "maximum_control_route_changes",
        "maximum_wrong_scope_authority_grants",
        "maximum_expired_or_revoked_hold_blocks",
        "maximum_revoked_authority_grants",
        "minimum_lookup_receipt_accuracy",
        "minimum_retrieved_decisive_provenance_accuracy",
    }
    if set(raw) != expected:
        raise ValueError(f"durable-store gate fields must be exactly {sorted(expected)}")
    return {
        key: float(value) if key.startswith("minimum_") else int(value)
        for key, value in raw.items()
    }


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != DURABLE_PROOF_STORE_VERSION:
        raise ValueError("durable-store scenario-set version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("durable-store gate must be deterministic and model-free")
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected = {"base_families": 3, "cases": 18, "measured_generation_calls": 0}
    for field, value in expected.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    cases = build_durable_proof_cases()
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": DURABLE_PROOF_STORE_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic",
        "model": None,
        "location": "local_machine",
        "base_families": len({case.family_id for case in cases}),
        "cases": len(cases),
        "case_set_sha256": stable_hash(cases),
        "config_sha256": stable_hash(config),
        "measured_generation_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "planning_estimates": estimates,
        "durable_store_gate": _gate(config),
        "outputs_if_run": [
            str(path.relative_to(ROOT))
            for path in output_paths(str(config["output_prefix"])).values()
        ],
    }


def build_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for case in build_durable_proof_cases():
        result = evaluate_durable_case(case)
        records.append(
            {
                "case_id": case.case_id,
                "family_id": case.family_id,
                "domain": case.domain,
                "condition": case.condition,
                "title": case.title,
                "memory_input": asdict(case.memory_input),
                "durable_store": asdict(case.store),
                "expected_memory_decision": case.expected_memory_decision.value,
                "expected_decision": case.expected_decision.value,
                "unsafe_if_executed": case.unsafe_if_executed,
                "expected_returned_card_ids": list(case.expected_returned_card_ids),
                "expected_decisive_retrieved_card_ids": list(
                    case.expected_decisive_retrieved_card_ids
                ),
                "evaluation": asdict(result),
                "lookup_receipt_correct": (
                    result.receipt.returned_card_ids
                    == case.expected_returned_card_ids
                ),
                "retrieved_decisive_provenance_correct": (
                    result.retrieved_decisive_card_ids
                    == case.expected_decisive_retrieved_card_ids
                ),
            }
        )
    return records


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    groups = [(condition, [x for x in records if x["condition"] == condition]) for condition in CONDITIONS]
    groups.append(("ALL", records))
    for name, items in groups:
        rows.append(
            {
                "condition": name,
                "cases": len(items),
                "memory_route_accuracy": sum(
                    x["evaluation"]["memory_route_correct"] for x in items
                ) / len(items),
                "durable_route_accuracy": sum(
                    x["evaluation"]["durable_route_correct"] for x in items
                ) / len(items),
                "memory_harmful_executions": sum(
                    x["evaluation"]["memory_harmful_execution"] for x in items
                ),
                "durable_harmful_executions": sum(
                    x["evaluation"]["durable_harmful_execution"] for x in items
                ),
                "helpful_route_changes": sum(
                    x["evaluation"]["retrieval_helpful"] for x in items
                ),
                "harmful_route_changes": sum(
                    x["evaluation"]["retrieval_harmful"] for x in items
                ),
                "lookup_receipt_accuracy": sum(x["lookup_receipt_correct"] for x in items)
                / len(items),
                "retrieved_decisive_provenance_accuracy": sum(
                    x["retrieved_decisive_provenance_correct"] for x in items
                ) / len(items),
            }
        )
    return rows


def durable_store_audit(
    records: list[dict[str, object]],
    summaries: list[dict[str, object]],
    *,
    gate: dict[str, float | int],
) -> dict[str, object]:
    expected_ids = {case.case_id for case in build_durable_proof_cases()}
    actual_ids = [str(record["case_id"]) for record in records]
    if set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
        raise ValueError("durable-store record coverage mismatch")
    overall = next(row for row in summaries if row["condition"] == "ALL")
    by_condition = {
        condition: [x for x in records if x["condition"] == condition]
        for condition in CONDITIONS
    }
    incorrect = sum(not x["evaluation"]["durable_route_correct"] for x in records)
    durable_harmful = int(overall["durable_harmful_executions"])
    memory_harmful = int(overall["memory_harmful_executions"])
    helpful = int(overall["helpful_route_changes"])
    harmful = int(overall["harmful_route_changes"])
    controls = (
        "ignore_expired_hold",
        "ignore_revoked_hold",
        "reject_wrong_scope_authority",
        "reject_revoked_authority",
    )
    control_changes = sum(
        x["evaluation"]["memory_result"]["decision"]
        != x["evaluation"]["durable_result"]["decision"]
        for condition in controls
        for x in by_condition[condition]
    )
    recovered_holds = sum(
        x["evaluation"]["durable_result"]["decision"] is Decision.HANDOFF
        and x["evaluation"]["retrieved_decisive_card_ids"]
        == tuple(x["expected_decisive_retrieved_card_ids"])
        for x in by_condition["recover_active_hold"]
    )
    recovered_authorities = sum(
        x["evaluation"]["durable_result"]["decision"] is Decision.AUTO_EXECUTE
        and x["evaluation"]["retrieved_decisive_card_ids"]
        == tuple(x["expected_decisive_retrieved_card_ids"])
        for x in by_condition["recover_valid_authority"]
    )
    wrong_scope_grants = sum(
        x["evaluation"]["durable_result"]["decision"] is Decision.AUTO_EXECUTE
        for x in by_condition["reject_wrong_scope_authority"]
    )
    expired_or_revoked_blocks = sum(
        x["evaluation"]["durable_result"]["decision"] is Decision.HANDOFF
        for condition in ("ignore_expired_hold", "ignore_revoked_hold")
        for x in by_condition[condition]
    )
    revoked_authority_grants = sum(
        x["evaluation"]["durable_result"]["decision"] is Decision.AUTO_EXECUTE
        for x in by_condition["reject_revoked_authority"]
    )
    preconditions_ok = all(
        x["evaluation"]["memory_matches_frozen_precondition"] for x in records
    )
    rules = {
        "memory_only_preconditions_match_frozen_design": preconditions_ok,
        "all_durable_routes_match_frozen_gold": incorrect
        <= int(gate["maximum_incorrect_durable_routes"]),
        "durable_lookup_removes_harmful_execution": durable_harmful
        <= int(gate["maximum_durable_harmful_executions"]),
        "hidden_hold_counterfactual_is_present": memory_harmful
        == int(gate["required_memory_harmful_executions"]),
        "required_helpful_route_changes_occur": helpful
        == int(gate["required_helpful_route_changes"]),
        "no_correct_memory_route_is_spoiled": harmful
        <= int(gate["maximum_harmful_route_changes"]),
        "active_holds_are_recovered_with_provenance": recovered_holds
        == int(gate["required_recovered_active_holds"]),
        "valid_authorities_are_recovered_with_provenance": recovered_authorities
        == int(gate["required_recovered_valid_authorities"]),
        "negative_controls_do_not_change_route": control_changes
        <= int(gate["maximum_control_route_changes"]),
        "wrong_scope_authority_is_never_granted": wrong_scope_grants
        <= int(gate["maximum_wrong_scope_authority_grants"]),
        "expired_or_revoked_holds_do_not_block": expired_or_revoked_blocks
        <= int(gate["maximum_expired_or_revoked_hold_blocks"]),
        "revoked_authority_is_never_granted": revoked_authority_grants
        <= int(gate["maximum_revoked_authority_grants"]),
        "lookup_receipts_match_frozen_expectations": float(
            overall["lookup_receipt_accuracy"]
        ) >= float(gate["minimum_lookup_receipt_accuracy"]),
        "retrieved_decisive_cards_keep_exact_provenance": float(
            overall["retrieved_decisive_provenance_accuracy"]
        ) >= float(gate["minimum_retrieved_decisive_provenance_accuracy"]),
    }
    passed = all(rules.values())
    return {
        "status": "PASS_DURABLE_PROOF_STORE_GATE" if passed else "FAIL_DURABLE_PROOF_STORE_GATE",
        "analysis_scope": "development-only deterministic point-in-time proof lookup before state-changing actions",
        "pre_specified_gate": rules,
        "thresholds": gate,
        "observations": {
            "records": len(records),
            "memory_route_accuracy": overall["memory_route_accuracy"],
            "durable_route_accuracy": overall["durable_route_accuracy"],
            "memory_harmful_executions": memory_harmful,
            "durable_harmful_executions": durable_harmful,
            "helpful_route_changes": helpful,
            "harmful_route_changes": harmful,
            "control_route_changes": control_changes,
            "recovered_active_holds": recovered_holds,
            "recovered_valid_authorities": recovered_authorities,
        },
        "condition_observations": summaries,
        "recommendation": (
            "ADD_DURABLE_LOOKUP_TO_DETERMINISTIC_DEMO_AND_FINAL_PLAYBOOK"
            if passed
            else "FREEZE_FAILURE_AND_REVISE_STORE_SEMANTICS_ON_NEW_DEVELOPMENT_CASES"
        ),
        "limitations": [
            "This is a deterministic architecture test, not an LLM experiment.",
            "The 18 synthetic cases are development-only and do not alter the frozen held-out compaction result.",
            "The gate assumes the source registries already emit authenticated proof cards; it does not test extraction from free text.",
            "The in-memory snapshot does not measure distributed consistency, lookup latency, race conditions, or registry availability.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal durable-store run requires a clean worktree")
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records = build_records()
    summaries = summarize(records)
    audit = durable_store_audit(records, summaries, gate=_gate(config))
    with paths["raw"].open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
    with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    paths["audit"].write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    finished = datetime.now(timezone.utc)
    manifest = {
        **plan,
        **provenance,
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
        "direction_recommendation": audit["recommendation"],
    }
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the durable proof-store gate")
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
