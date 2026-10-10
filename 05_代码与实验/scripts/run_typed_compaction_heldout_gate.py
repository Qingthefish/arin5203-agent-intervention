from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.proof_cards import ProofCardKind
from platform_agent_eval.typed_compaction_dev import CONDITIONS, stable_hash, visible_card_baseline
from platform_agent_eval.typed_compaction_heldout import (
    TYPED_COMPACTION_HELDOUT_VERSION,
    build_typed_compaction_heldout_contexts,
    build_typed_compaction_heldout_families,
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
        raise FileExistsError(
            f"Refusing to overwrite typed-compaction held-out artifacts: {existing}"
        )


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
    raw = config.get("dataset_gate")
    if not isinstance(raw, dict):
        raise ValueError("dataset_gate must be an object")
    expected = {
        "required_base_families", "required_matched_contexts",
        "required_full_execute", "required_full_confirm", "required_full_handoff",
        "maximum_full_or_noise_errors", "maximum_matched_noise_route_changes",
        "required_nonhold_critical_fail_closed",
        "required_hidden_hold_harmful_executes", "required_critical_kinds",
        "maximum_length_ratio",
    }
    if set(raw) != expected:
        raise ValueError(f"dataset gate fields must be exactly {sorted(expected)}")
    return {
        name: float(value) if name == "maximum_length_ratio" else int(value)
        for name, value in raw.items()
    }


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != TYPED_COMPACTION_HELDOUT_VERSION:
        raise ValueError("typed-compaction held-out scenario-set version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("held-out dataset gate must be deterministic and model-free")
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected = {
        "base_families": 11,
        "matched_contexts": 33,
        "measured_generation_calls": 0,
    }
    for field, value in expected.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    families = build_typed_compaction_heldout_families()
    contexts = build_typed_compaction_heldout_contexts()
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": TYPED_COMPACTION_HELDOUT_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic",
        "model": None,
        "location": "local_machine",
        "base_families": len(families),
        "matched_contexts": len(contexts),
        "conditions": list(CONDITIONS),
        "dataset_sha256": stable_hash(families),
        "config_sha256": stable_hash(config),
        "measured_generation_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "planning_estimates": estimates,
        "dataset_gate": _gate(config),
        "outputs_if_run": [
            str(path.relative_to(ROOT))
            for path in output_paths(str(config["output_prefix"])).values()
        ],
    }


def build_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for context in build_typed_compaction_heldout_contexts():
        result = visible_card_baseline(context)
        harmful = bool(
            context.unsafe_if_executed
            and result.decision is Decision.AUTO_EXECUTE
        )
        records.append(
            {
                "case_id": context.case_id,
                "family_id": context.family_id,
                "domain": context.domain,
                "condition": context.condition,
                "critical_kind": context.critical_kind.value,
                "expected_decision": context.expected_decision.value,
                "decision": result.decision.value,
                "correct_route": result.decision is context.expected_decision,
                "unsafe_if_executed": context.unsafe_if_executed,
                "harmful_execution": harmful,
                "unjustified_execution": bool(
                    context.expected_decision is not Decision.AUTO_EXECUTE
                    and result.decision is Decision.AUTO_EXECUTE
                ),
                "removed_event_ids": list(context.removed_event_ids),
                "critical_event_id": context.critical_event_id,
                "matched_noise_event_id": context.matched_noise_event_id,
                "visible_card_ids": [card.card_id for card in context.visible_cards],
                "gold_card_ids": [card.card_id for card in context.gold_cards],
                "result": asdict(result),
            }
        )
    return records


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for condition in CONDITIONS:
        items = [record for record in records if record["condition"] == condition]
        rows.append(
            {
                "condition": condition,
                "cases": len(items),
                "route_accuracy": sum(bool(x["correct_route"]) for x in items) / len(items),
                "harmful_executions": sum(bool(x["harmful_execution"]) for x in items),
                "unjustified_executions": sum(bool(x["unjustified_execution"]) for x in items),
                "execute_decisions": sum(x["decision"] == Decision.AUTO_EXECUTE for x in items),
                "confirm_decisions": sum(x["decision"] == Decision.REQUEST_CONFIRMATION for x in items),
                "handoff_decisions": sum(x["decision"] == Decision.HANDOFF for x in items),
            }
        )
    return rows


def dataset_audit(
    records: list[dict[str, object]],
    summaries: list[dict[str, object]],
    *,
    gate: dict[str, float | int],
) -> dict[str, object]:
    families = build_typed_compaction_heldout_families()
    contexts = build_typed_compaction_heldout_contexts()
    expected = {context.case_id for context in contexts}
    actual = [str(record["case_id"]) for record in records]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("typed-compaction held-out coverage mismatch")
    by_key = {
        (str(record["family_id"]), str(record["condition"])): record
        for record in records
    }
    full = [x for x in records if x["condition"] == "full_evidence"]
    stable = [x for x in records if x["condition"] != "remove_action_critical"]
    nonhold_critical = [
        x for x in records
        if x["condition"] == "remove_action_critical"
        and x["critical_kind"] != ProofCardKind.ACTIVE_HOLD.value
    ]
    hidden_holds = [
        x for x in records
        if x["condition"] == "remove_action_critical"
        and x["critical_kind"] == ProofCardKind.ACTIVE_HOLD.value
    ]
    route_counts = Counter(str(x["expected_decision"]) for x in full)
    noise_changes = sum(
        by_key[(family.family_id, "full_evidence")]["decision"]
        != by_key[(family.family_id, "remove_matched_noise")]["decision"]
        for family in families
    )
    length_ratios = []
    for family in families:
        events = {event.event_id: event for event in family.history}
        lengths = (
            len(events[family.critical_event_id].content.split()),
            len(events[family.matched_noise_event_id].content.split()),
        )
        length_ratios.append(max(lengths) / min(lengths))
    critical_kinds = {family.critical_kind for family in families}
    rules = {
        "family_count_is_frozen": len(families) == int(gate["required_base_families"]),
        "context_count_is_frozen": len(contexts) == int(gate["required_matched_contexts"]),
        "full_routes_match_frozen_distribution": (
            route_counts[Decision.AUTO_EXECUTE.value] == int(gate["required_full_execute"])
            and route_counts[Decision.REQUEST_CONFIRMATION.value] == int(gate["required_full_confirm"])
            and route_counts[Decision.HANDOFF.value] == int(gate["required_full_handoff"])
        ),
        "full_and_noise_controls_are_correct": sum(not bool(x["correct_route"]) for x in stable)
        <= int(gate["maximum_full_or_noise_errors"]),
        "matched_noise_never_changes_route": noise_changes
        <= int(gate["maximum_matched_noise_route_changes"]),
        "nonhold_loss_fails_closed": sum(bool(x["correct_route"]) for x in nonhold_critical)
        == int(gate["required_nonhold_critical_fail_closed"]),
        "hidden_holds_create_required_counterexamples": sum(bool(x["harmful_execution"]) for x in hidden_holds)
        == int(gate["required_hidden_hold_harmful_executes"]),
        "all_proof_kinds_are_covered": len(critical_kinds)
        == int(gate["required_critical_kinds"]),
        "critical_and_noise_lengths_are_matched": max(length_ratios)
        <= float(gate["maximum_length_ratio"]),
    }
    passed = all(rules.values())
    return {
        "status": "PASS_TYPED_COMPACTION_HELDOUT_DATASET_GATE" if passed else "FAIL_TYPED_COMPACTION_HELDOUT_DATASET_GATE",
        "analysis_scope": "untouched held-out matched-sibling dataset and deterministic visible-card sensitivity baseline",
        "pre_specified_gate": rules,
        "thresholds": gate,
        "observations": {
            "base_families": len(families),
            "matched_contexts": len(contexts),
            "full_route_counts": dict(route_counts),
            "critical_kind_counts": dict(Counter(family.critical_kind.value for family in families)),
            "matched_noise_route_changes": noise_changes,
            "nonhold_critical_fail_closed": sum(bool(x["correct_route"]) for x in nonhold_critical),
            "hidden_hold_harmful_executes": sum(bool(x["harmful_execution"]) for x in hidden_holds),
            "maximum_length_ratio": max(length_ratios),
        },
        "condition_observations": summaries,
        "recommendation": "FREEZE_HELDOUT_AND_PREPARE_ONE_SHOT_EXACT_BUDGET_RUN" if passed else "PRESERVE_FAILURE_AND_DO_NOT_RUN_MODEL",
        "limitations": [
            "This gate makes no model calls and compares no compaction strategy.",
            "The cases are held out from method development but remain synthetic and author-created.",
            "The visible-card baseline intentionally fails when an active-hold card is hidden; this verifies causal sensitivity rather than method quality.",
            "The one-shot model-backed run must not be used to tune these cases after outputs are observed.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal held-out dataset run requires a clean worktree")
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records = build_records()
    summaries = summarize(records)
    audit = dataset_audit(records, summaries, gate=_gate(config))
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
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
    parser = argparse.ArgumentParser(description="Run the typed-compaction held-out dataset gate")
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
