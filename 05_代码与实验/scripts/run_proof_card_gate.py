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
from platform_agent_eval.proof_cards import (
    PROOF_CARD_SET_VERSION,
    ProofCardKind,
    build_proof_card_cases,
    score_proof_card_case,
    stable_hash,
    validate_proof_cards,
)


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
        raise FileExistsError(f"Refusing to overwrite proof-card artifacts: {existing}")


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
    return {"git_commit": revision, "git_worktree_dirty_at_start": bool(dirty)}


def _gate(config: dict[str, object]) -> dict[str, float | int]:
    raw = config.get("proof_card_gate")
    if not isinstance(raw, dict):
        raise ValueError("proof_card_gate must be an object")
    expected = {
        "maximum_incorrect_routes",
        "maximum_harmful_executions",
        "minimum_reason_completeness",
        "minimum_decisive_provenance_accuracy",
        "maximum_clearance_promoted_to_authority",
        "maximum_ignored_cards_used_as_decisive",
        "required_execute_decisions",
        "required_confirm_decisions",
        "required_handoff_decisions",
    }
    if set(raw) != expected:
        raise ValueError(f"proof-card gate fields must be exactly {sorted(expected)}")
    return {
        "maximum_incorrect_routes": int(raw["maximum_incorrect_routes"]),
        "maximum_harmful_executions": int(raw["maximum_harmful_executions"]),
        "minimum_reason_completeness": float(raw["minimum_reason_completeness"]),
        "minimum_decisive_provenance_accuracy": float(
            raw["minimum_decisive_provenance_accuracy"]
        ),
        "maximum_clearance_promoted_to_authority": int(
            raw["maximum_clearance_promoted_to_authority"]
        ),
        "maximum_ignored_cards_used_as_decisive": int(
            raw["maximum_ignored_cards_used_as_decisive"]
        ),
        "required_execute_decisions": int(raw["required_execute_decisions"]),
        "required_confirm_decisions": int(raw["required_confirm_decisions"]),
        "required_handoff_decisions": int(raw["required_handoff_decisions"]),
    }


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != PROOF_CARD_SET_VERSION:
        raise ValueError("proof-card scenario-set version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("proof-card gate must be deterministic and model-free")
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected = {"cases": 9, "measured_generation_calls": 0}
    for field, value in expected.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    cases = build_proof_card_cases()
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": PROOF_CARD_SET_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic",
        "model": None,
        "location": "local_machine",
        "cases": len(cases),
        "case_set_sha256": stable_hash(cases),
        "config_sha256": stable_hash(config),
        "measured_generation_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "planning_estimates": estimates,
        "proof_card_gate": _gate(config),
        "outputs_if_run": [
            str(path.relative_to(ROOT))
            for path in output_paths(str(config["output_prefix"])).values()
        ],
    }


def build_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for case in build_proof_card_cases():
        result = validate_proof_cards(case.runtime_input)
        score = score_proof_card_case(case, result)
        cards_by_id = {card.card_id: card for card in case.runtime_input.cards}
        clearance_promoted = sum(
            cards_by_id[card_id].kind is ProofCardKind.CLEARANCE
            for card_id in result.authority_card_ids
        )
        ignored_decisive = len(
            set(result.ignored_card_ids).intersection(result.decisive_card_ids)
        )
        records.append(
            {
                "case_id": case.case_id,
                "domain": case.domain,
                "title": case.title,
                "runtime_input": asdict(case.runtime_input),
                "expected_decision": case.expected_decision.value,
                "unsafe_if_executed": case.unsafe_if_executed,
                "required_reason_codes": list(case.required_reason_codes),
                "expected_decisive_card_ids": list(
                    case.expected_decisive_card_ids
                ),
                "result": asdict(result),
                "score": asdict(score),
                "clearance_promoted_to_authority": clearance_promoted,
                "ignored_cards_used_as_decisive": ignored_decisive,
            }
        )
    return records


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for domain in ("platform", "financial", "mas_travel", "ALL"):
        items = records if domain == "ALL" else [x for x in records if x["domain"] == domain]
        rows.append(
            {
                "domain": domain,
                "cases": len(items),
                "route_accuracy": sum(x["score"]["route_correct"] for x in items)
                / len(items),
                "harmful_executions": sum(
                    x["score"]["harmful_execution"] for x in items
                ),
                "reason_completeness": sum(
                    x["score"]["reasons_complete"] for x in items
                )
                / len(items),
                "decisive_provenance_accuracy": sum(
                    x["score"]["decisive_provenance_complete"] for x in items
                )
                / len(items),
                "execute_decisions": sum(
                    x["result"]["decision"] == Decision.AUTO_EXECUTE for x in items
                ),
                "confirm_decisions": sum(
                    x["result"]["decision"] == Decision.REQUEST_CONFIRMATION
                    for x in items
                ),
                "handoff_decisions": sum(
                    x["result"]["decision"] == Decision.HANDOFF for x in items
                ),
            }
        )
    return rows


def proof_card_audit(
    records: list[dict[str, object]],
    summaries: list[dict[str, object]],
    *,
    gate: dict[str, float | int],
) -> dict[str, object]:
    expected_ids = {case.case_id for case in build_proof_card_cases()}
    actual_ids = [str(record["case_id"]) for record in records]
    if set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
        raise ValueError("proof-card record coverage mismatch")
    overall = next(row for row in summaries if row["domain"] == "ALL")
    by_id = {str(record["case_id"]): record for record in records}
    incorrect = sum(not x["score"]["route_correct"] for x in records)
    harmful = sum(x["score"]["harmful_execution"] for x in records)
    clearance_promoted = sum(
        int(x["clearance_promoted_to_authority"]) for x in records
    )
    ignored_decisive = sum(int(x["ignored_cards_used_as_decisive"]) for x in records)
    rules = {
        "all_routes_match_frozen_gold": incorrect
        <= int(gate["maximum_incorrect_routes"]),
        "no_harmful_execution": harmful
        <= int(gate["maximum_harmful_executions"]),
        "required_reasons_are_complete": float(overall["reason_completeness"])
        >= float(gate["minimum_reason_completeness"]),
        "decisive_cards_have_exact_provenance": float(
            overall["decisive_provenance_accuracy"]
        )
        >= float(gate["minimum_decisive_provenance_accuracy"]),
        "clearance_is_never_promoted_to_authority": clearance_promoted
        <= int(gate["maximum_clearance_promoted_to_authority"]),
        "ignored_cards_are_never_decisive": ignored_decisive
        <= int(gate["maximum_ignored_cards_used_as_decisive"]),
        "clearance_only_case_hands_off": by_id[
            "cards-platform-clearance-only"
        ]["result"]["decision"]
        == Decision.HANDOFF,
        "active_hold_dominates_prior_authority": by_id[
            "cards-financial-hold"
        ]["result"]["decision"]
        == Decision.HANDOFF,
        "missing_delegation_cannot_be_confirmed_away": by_id[
            "cards-mas-handoff"
        ]["result"]["decision"]
        == Decision.HANDOFF,
        "decision_classes_are_balanced": (
            int(overall["execute_decisions"])
            == int(gate["required_execute_decisions"])
            and int(overall["confirm_decisions"])
            == int(gate["required_confirm_decisions"])
            and int(overall["handoff_decisions"])
            == int(gate["required_handoff_decisions"])
        ),
    }
    passed = all(rules.values())
    return {
        "status": "PASS_PROOF_CARD_INTERFACE_GATE"
        if passed
        else "FAIL_PROOF_CARD_INTERFACE_GATE",
        "analysis_scope": (
            "deterministic validation of provenance-typed proof obligations before "
            "state-changing actions"
        ),
        "pre_specified_gate": rules,
        "thresholds": gate,
        "observations": {
            "records": len(records),
            "incorrect_routes": incorrect,
            "harmful_executions": harmful,
            "clearance_promoted_to_authority": clearance_promoted,
            "ignored_cards_used_as_decisive": ignored_decisive,
        },
        "domain_observations": summaries,
        "recommendation": (
            "PROCEED_TO_FRESH_EXACT_BUDGET_DEVELOPMENT_SET"
            if passed
            else "FREEZE_FAILURE_AND_REVISE_TYPED_VALIDATION_RULES"
        ),
        "limitations": [
            "This is a deterministic engineering and schema gate, not a model experiment.",
            "The nine cases are synthetic development cases and are not held-out evidence.",
            "The gate tests proof-card validation after extraction; it does not show that an LLM can extract the cards reliably from compacted context.",
            "No compaction method is compared here.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal proof-card run requires a clean worktree")
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records = build_records()
    summaries = summarize(records)
    audit = proof_card_audit(records, summaries, gate=_gate(config))
    with paths["raw"].open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, default=_json_default) + "\n"
            )
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
        "started_at_hong_kong": started.astimezone(
            ZoneInfo("Asia/Hong_Kong")
        ).isoformat(),
        "finished_at_utc": finished.isoformat(),
        "finished_at_hong_kong": finished.astimezone(
            ZoneInfo("Asia/Hong_Kong")
        ).isoformat(),
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
    parser = argparse.ArgumentParser(description="Run the typed proof-card gate")
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
