from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.model_routing import GenerationConfig, ModelResponse, OllamaClient
from platform_agent_eval.protocol_falsification import normalize_bracketed_event_ids
from platform_agent_eval.token_budget import CachedTokenCounter, OllamaRawTokenCounter
from platform_agent_eval.typed_budget_compaction import (
    BUDGETED_METHODS,
    METHODS,
    TYPED_BUDGET_COMPACTION_VERSION,
    TypedCompactionDraft,
    build_budget_context,
    deterministic_drafts,
)
from platform_agent_eval.typed_compaction_dev import (
    TYPED_COMPACTION_DEV_VERSION,
    TypedCompactionContext,
    build_typed_compaction_contexts,
    build_typed_compaction_families,
    stable_hash,
)
from platform_agent_eval.typed_compaction_routing import (
    TYPED_DIRECT_ROUTER_VERSION,
    route_typed_context,
)
from run_typed_exact_budget_gate import (
    ProbeCounter,
    _response_usage,
    append_jsonl,
    assert_paths_available,
    git_provenance,
    make_record,
    output_paths,
    summarize,
)


SWEEP_VERSION = "typed-budget-sensitivity-v1"
GENERATIVE_METHODS = ("neutral_summary", "task_aware_summary", "ufold_lite")


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_paths(config: dict[str, object]) -> dict[str, Path]:
    return output_paths(str(config["source_run_prefix"]))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("source trace rows must be JSON objects")
                records.append(value)
    return records


def load_source_records(
    config: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    paths = _source_paths(config)
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing frozen source artifacts: {missing}")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    audit = json.loads(paths["audit"].read_text(encoding="utf-8"))
    records = _read_jsonl(paths["raw"])
    if manifest.get("status") != "COMPLETED":
        raise ValueError("frozen source run is not complete")
    if audit.get("status") != "PASS_TYPED_EXACT_BUDGET_DEVELOPMENT_GATE":
        raise ValueError("frozen source run did not pass the development gate")
    if int(manifest.get("budget_tokens", -1)) != int(config["source_budget_tokens"]):
        raise ValueError("source budget does not match the sweep configuration")
    return records, manifest, audit


def _protocol_gate(config: dict[str, object]) -> dict[str, float | int]:
    raw = config.get("protocol_gate")
    if not isinstance(raw, dict):
        raise ValueError("protocol_gate must be an object")
    float_fields = {
        "minimum_budget_utilization",
        "minimum_budgeted_utilization_rate",
    }
    expected = {
        "maximum_source_replay_mismatches",
        "maximum_budget_violations",
        "maximum_blinded_label_leaks",
        "maximum_source_integrity_errors",
        "maximum_protected_fill_violations",
        "maximum_compactor_format_errors",
        "maximum_direct_router_format_errors",
        "maximum_token_count_probe_calls",
        *float_fields,
    }
    if set(raw) != expected:
        raise ValueError(f"protocol_gate fields must be exactly {sorted(expected)}")
    return {
        key: float(value) if key in float_fields else int(value)
        for key, value in raw.items()
    }


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != TYPED_COMPACTION_DEV_VERSION:
        raise ValueError("budget sweep is restricted to the frozen development set")
    if config.get("compaction_version") != TYPED_BUDGET_COMPACTION_VERSION:
        raise ValueError("typed-budget compaction version mismatch")
    if config.get("router_version") != TYPED_DIRECT_ROUTER_VERSION:
        raise ValueError("typed direct-router version mismatch")
    if config.get("provider") != "ollama":
        raise ValueError("budget sweep requires local Ollama")
    budgets = tuple(int(item) for item in config["sweep_budget_tokens"])
    if not budgets or len(set(budgets)) != len(budgets) or any(item <= 0 for item in budgets):
        raise ValueError("sweep budgets must be unique positive integers")
    if any(item >= int(config["source_budget_tokens"]) for item in budgets):
        raise ValueError("sweep budgets must be tighter than the frozen source budget")
    families = build_typed_compaction_families()
    contexts = build_typed_compaction_contexts()
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected_counts = {
        "base_families": len(families),
        "matched_contexts": len(contexts),
        "budgeted_methods": len(BUDGETED_METHODS),
        "sweep_budgets": len(budgets),
        "frozen_source_records": len(contexts) * len(METHODS),
        "reused_generative_compactor_outputs": len(contexts) * len(GENERATIVE_METHODS),
        "compactor_generation_calls": 0,
        "routing_generation_calls": len(contexts) * len(BUDGETED_METHODS) * len(budgets),
        "measured_generation_calls": len(contexts) * len(BUDGETED_METHODS) * len(budgets),
        "warmup_calls": 1,
    }
    for field, value in expected_counts.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    source_records, source_manifest, _ = load_source_records(config)
    expected_source = {
        (context.case_id, method)
        for context in contexts
        for method in METHODS
    }
    actual_source = [(str(row["case_id"]), str(row["method"])) for row in source_records]
    if set(actual_source) != expected_source or len(actual_source) != len(expected_source):
        raise ValueError("frozen source trace coverage mismatch")
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "sweep_version": SWEEP_VERSION,
        "scenario_set": config["scenario_set"],
        "compaction_version": TYPED_BUDGET_COMPACTION_VERSION,
        "router_version": TYPED_DIRECT_ROUTER_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "ollama",
        "model": config["model"],
        "location": "local_machine",
        "base_families": len(families),
        "matched_contexts": len(contexts),
        "methods": list(BUDGETED_METHODS),
        "source_budget_tokens": int(config["source_budget_tokens"]),
        "sweep_budget_tokens": list(budgets),
        "dataset_sha256": stable_hash(families),
        "config_sha256": stable_hash(config),
        "source_run_prefix": config["source_run_prefix"],
        "source_git_commit": source_manifest.get("git_commit"),
        "source_artifact_sha256": {
            key: _sha256(path) for key, path in _source_paths(config).items()
        },
        "measured_generation_calls": expected_counts["measured_generation_calls"],
        "warmup_calls": expected_counts["warmup_calls"],
        "estimated_input_tokens": estimates["estimated_input_tokens"],
        "estimated_output_tokens": estimates["estimated_output_tokens"],
        "estimated_wall_time_minutes": estimates["estimated_wall_time_minutes"],
        "external_api_cost_usd": float(estimates["external_api_cost_usd"]),
        "planning_estimates": estimates,
        "protocol_gate": _protocol_gate(config),
        "outputs_if_run": [
            str(path.relative_to(ROOT))
            for path in output_paths(str(config["output_prefix"])).values()
        ],
    }


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("compactor output must be a JSON object")
    return value


def replay_draft(
    context: TypedCompactionContext,
    method: str,
    source_record: dict[str, object],
) -> TypedCompactionDraft:
    if method not in BUDGETED_METHODS:
        raise ValueError(f"unsupported replay method: {method}")
    if method not in GENERATIVE_METHODS:
        return deterministic_drafts(context)[method]
    raw = source_record.get("compactor_raw_output")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"missing frozen compactor output for {context.case_id}/{method}")
    payload = _json_object(raw)
    visible = {event.event_id for event in context.active_events}
    if method in {"neutral_summary", "task_aware_summary"}:
        if set(payload) != {"summary"}:
            raise ValueError("unexpected frozen summary schema")
        summary = str(payload["summary"]).strip()
        source_ids = normalize_bracketed_event_ids(summary)
        if not summary or not source_ids or any(item not in visible for item in source_ids):
            raise ValueError("frozen summary has invalid visible provenance")
    else:
        if set(payload) != {"intent_summary", "proof_log"}:
            raise ValueError("unexpected frozen U-Fold-lite schema")
        intent = str(payload["intent_summary"]).strip()
        proof_log = payload["proof_log"]
        if not intent or not isinstance(proof_log, list):
            raise ValueError("invalid frozen U-Fold-lite output")
        sources: list[str] = []
        facts: list[str] = []
        for item in proof_log:
            if not isinstance(item, dict) or set(item) != {"event_id", "fact"}:
                raise ValueError("invalid frozen U-Fold-lite proof item")
            event_id = str(item["event_id"])
            fact = str(item["fact"]).strip()
            if event_id not in visible or not fact:
                raise ValueError("frozen U-Fold-lite proof lacks visible provenance")
            sources.append(event_id)
            facts.append(f"[{event_id}] {fact}")
        source_ids = tuple(dict.fromkeys(sources))
        summary = "INTENT: " + intent
        if facts:
            summary += "\nPROOF LOG:\n" + "\n".join(facts)
    return TypedCompactionDraft(
        method=method,
        summary=summary,
        priority_event_ids=(),
        source_event_ids=tuple(dict.fromkeys(source_ids)),
        format_valid=True,
        raw_output=raw,
    )


def _source_record_map(
    records: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (str(record["case_id"]), str(record["method"])): record
        for record in records
    }


def validate_source_replay(
    contexts: list[TypedCompactionContext],
    source_records: list[dict[str, object]],
    *,
    counter: CachedTokenCounter,
    source_budget_tokens: int,
    minimum_utilization: float,
) -> tuple[dict[tuple[str, str], TypedCompactionDraft], list[dict[str, object]]]:
    by_key = _source_record_map(source_records)
    drafts: dict[tuple[str, str], TypedCompactionDraft] = {}
    mismatches: list[dict[str, object]] = []
    for context in contexts:
        for method in BUDGETED_METHODS:
            source = by_key[(context.case_id, method)]
            try:
                draft = replay_draft(context, method, source)
                replayed = build_budget_context(
                    context,
                    draft,
                    counter=counter,
                    budget_tokens=source_budget_tokens,
                    minimum_utilization=minimum_utilization,
                )
                checks = {
                    "active_memory_sha256": hashlib.sha256(
                        replayed.text.encode("utf-8")
                    ).hexdigest()
                    == source["active_memory_sha256"],
                    "exact_raw_tokens": replayed.exact_raw_tokens
                    == int(source["exact_raw_tokens"]),
                    "source_event_ids": list(replayed.source_event_ids)
                    == list(source["source_event_ids"]),
                    "neutral_fill_event_ids": list(replayed.neutral_fill_event_ids)
                    == list(source["neutral_fill_event_ids"]),
                    "format_valid": replayed.format_valid
                    == bool(source["compactor_format_valid"]),
                }
                drafts[(context.case_id, method)] = draft
                if not all(checks.values()):
                    mismatches.append(
                        {"case_id": context.case_id, "method": method, "checks": checks}
                    )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                mismatches.append(
                    {
                        "case_id": context.case_id,
                        "method": method,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    return drafts, mismatches


def budget_sweep_audit(
    records: list[dict[str, object]],
    *,
    contexts: list[TypedCompactionContext],
    budgets: tuple[int, ...],
    source_replay_mismatches: list[dict[str, object]],
    cache_requests: int,
    cache_hits: int,
    cache_misses: int,
    gate: dict[str, float | int],
) -> dict[str, object]:
    expected = {
        (budget, context.case_id, method)
        for budget in budgets
        for context in contexts
        for method in BUDGETED_METHODS
    }
    actual = [
        (int(record["sweep_budget_tokens"]), str(record["case_id"]), str(record["method"]))
        for record in records
    ]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("budget-sweep record coverage mismatch")
    utilization_rate = sum(
        float(record["budget_utilization"]) >= float(gate["minimum_budget_utilization"])
        for record in records
    ) / len(records)
    observations = {
        "records": len(records),
        "source_replay_mismatches": len(source_replay_mismatches),
        "budget_violations": sum(bool(item["budget_violation"]) for item in records),
        "budgeted_utilization_rate": utilization_rate,
        "blinded_label_leaks": sum(bool(item["blinded_label_leaks"]) for item in records),
        "source_integrity_errors": sum(not bool(item["source_integrity_valid"]) for item in records),
        "protected_fill_violations": sum(bool(item["protected_fill_violation"]) for item in records),
        "compactor_format_errors": sum(not bool(item["compactor_format_valid"]) for item in records),
        "direct_router_format_errors": sum(
            not bool(item["direct"]["format_valid"]) for item in records  # type: ignore[index]
        ),
        "token_cache_requests": cache_requests,
        "token_cache_hits": cache_hits,
        "token_cache_misses": cache_misses,
        "token_cache_hit_rate": cache_hits / cache_requests if cache_requests else 0.0,
    }
    rules = {
        "frozen_source_replays_exactly": observations["source_replay_mismatches"]
        <= int(gate["maximum_source_replay_mismatches"]),
        "budget_violations_within_limit": observations["budget_violations"]
        <= int(gate["maximum_budget_violations"]),
        "budgeted_contexts_meet_utilization": utilization_rate
        >= float(gate["minimum_budgeted_utilization_rate"]),
        "strategy_labels_are_blinded": observations["blinded_label_leaks"]
        <= int(gate["maximum_blinded_label_leaks"]),
        "all_sources_have_visible_provenance": observations["source_integrity_errors"]
        <= int(gate["maximum_source_integrity_errors"]),
        "neutral_fill_never_reinjects_protected_cards": observations["protected_fill_violations"]
        <= int(gate["maximum_protected_fill_violations"]),
        "compactor_replays_are_parse_valid": observations["compactor_format_errors"]
        <= int(gate["maximum_compactor_format_errors"]),
        "direct_router_format_errors_within_limit": observations["direct_router_format_errors"]
        <= int(gate["maximum_direct_router_format_errors"]),
        "token_count_probes_within_limit": cache_misses
        <= int(gate["maximum_token_count_probe_calls"]),
    }
    passed = all(rules.values())
    return {
        "status": (
            "PASS_TYPED_BUDGET_SWEEP_PROTOCOL_GATE"
            if passed
            else "REPAIR_TYPED_BUDGET_SWEEP_PROTOCOL"
        ),
        "analysis_scope": (
            "paired development-set sensitivity characterization using byte-validated "
            "frozen v6 compactor outputs and newly routed 256- and 192-token memories"
        ),
        "pre_specified_gate": rules,
        "thresholds": gate,
        "protocol_passed": passed,
        "instrumentation_observations": observations,
        "source_replay_mismatches": source_replay_mismatches,
        "recommendation": (
            "RENDER_BUDGET_SENSITIVITY_AND_START_DURABLE_MEMORY_EXTENSION"
            if passed
            else "REPAIR_SWEEP_INSTRUMENTATION_BEFORE_INTERPRETING_METHODS"
        ),
        "limitations": [
            "The sweep uses the nine frozen development bases and does not modify or rerun the held-out set.",
            "The 384-token point comes from the frozen v6 source trace; lower budgets reuse its compactor outputs so only active-memory packing and routing change.",
            "The sweep characterizes failure boundaries and is not a second method-selection gate.",
            "Typed cards are assumed to exist when authenticated evidence originates; free-text card extraction remains outside this experiment.",
            "No downstream audit can recover a decisive event removed before compaction receives the history.",
        ],
    }


def _summary_rows(
    source_records: list[dict[str, object]],
    records: list[dict[str, object]],
    budgets: tuple[int, ...],
    *,
    source_budget_tokens: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in summarize(source_records):
        rows.append(
            {
                "budget_tokens": source_budget_tokens,
                "measurement_origin": "frozen_v6_source",
                **row,
            }
        )
    source_full = [item for item in source_records if item["method"] == "full_context_ceiling"]
    for budget in budgets:
        selected = [item for item in records if int(item["sweep_budget_tokens"]) == budget]
        for row in summarize([*source_full, *selected]):
            rows.append(
                {
                    "budget_tokens": budget,
                    "measurement_origin": (
                        "frozen_v6_ceiling" if row["method"] == "full_context_ceiling"
                        else "replayed_compactor_new_route"
                    ),
                    **row,
                }
            )
    return rows


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal budget sweep requires a clean worktree")
    paths = output_paths(str(config["output_prefix"]))
    assert_paths_available(paths)
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    source_records, _, _ = load_source_records(config)
    contexts = build_typed_compaction_contexts()
    budgets = tuple(int(item) for item in config["sweep_budget_tokens"])
    gate = _protocol_gate(config)
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    base_manifest = {
        **plan,
        **provenance,
        "status": "RUNNING",
        "started_at_utc": started.isoformat(),
        "started_at_hong_kong": started.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "python_version": platform.python_version(),
        "config_snapshot": config,
    }
    paths["manifest"].write_text(
        json.dumps(base_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["raw"].touch(exist_ok=False)
    client = OllamaClient(str(config["base_url"]))
    probe_counter = ProbeCounter(
        OllamaRawTokenCounter(
            model=str(config["model"]),
            base_url=str(config["base_url"]),
            timeout_seconds=float(config["timeout_seconds"]),
            seed=int(config["seed"]),
        )
    )
    counter = CachedTokenCounter(probe_counter)
    router_config = GenerationConfig(
        model=str(config["model"]),
        temperature=float(config["temperature"]),
        seed=int(config["seed"]),
        timeout_seconds=float(config["timeout_seconds"]),
        max_tokens=int(config["router_max_tokens"]),
    )
    records: list[dict[str, object]] = []
    router_responses: list[ModelResponse] = []
    replay_mismatches: list[dict[str, object]] = []
    try:
        drafts, replay_mismatches = validate_source_replay(
            contexts,
            source_records,
            counter=counter,
            source_budget_tokens=int(config["source_budget_tokens"]),
            minimum_utilization=float(config["minimum_utilization"]),
        )
        if replay_mismatches:
            raise RuntimeError(
                f"frozen v6 source replay produced {len(replay_mismatches)} mismatches"
            )
        source_by_key = _source_record_map(source_records)
        warmup = client.generate('{"ready": true}', router_config)
        for budget in budgets:
            for context in contexts:
                for method in BUDGETED_METHODS:
                    source = source_by_key[(context.case_id, method)]
                    compacted = build_budget_context(
                        context,
                        drafts[(context.case_id, method)],
                        counter=counter,
                        budget_tokens=budget,
                        minimum_utilization=float(config["minimum_utilization"]),
                    )
                    direct, route_prompt = route_typed_context(
                        context,
                        compacted,
                        client,
                        router_config,
                    )
                    router_responses.append(direct.response)
                    record = make_record(
                        context,
                        compacted,
                        direct,
                        route_prompt,
                        compactor_prompt_hash=(
                            str(source["compactor_prompt_hash"])
                            if source.get("compactor_prompt_hash")
                            else None
                        ),
                        seed=int(config["seed"]),
                    )
                    record.update(
                        {
                            "sweep_budget_tokens": budget,
                            "measurement_origin": "replayed_frozen_compactor_output_new_route",
                            "source_run_prefix": config["source_run_prefix"],
                            "source_active_memory_sha256": source["active_memory_sha256"],
                        }
                    )
                    records.append(record)
                    append_jsonl(paths["raw"], record)
        summaries = _summary_rows(
            source_records,
            records,
            budgets,
            source_budget_tokens=int(config["source_budget_tokens"]),
        )
        audit = budget_sweep_audit(
            records,
            contexts=contexts,
            budgets=budgets,
            source_replay_mismatches=replay_mismatches,
            cache_requests=counter.requests,
            cache_hits=counter.hits,
            cache_misses=counter.misses,
            gate=gate,
        )
        with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
        paths["audit"].write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        usage = _response_usage(router_responses)
        finished = datetime.now(timezone.utc)
        manifest = {
            **base_manifest,
            "status": "COMPLETED",
            "finished_at_utc": finished.isoformat(),
            "finished_at_hong_kong": finished.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
            "duration_seconds": time.perf_counter() - timer,
            "measured_generation_calls_completed": usage["calls"],
            "compactor_generation_calls_completed": 0,
            "routing_generation_calls_completed": len(router_responses),
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "generation_latency_seconds": float(usage["latency_ms"]) / 1000.0,
            "token_count_requests": counter.requests,
            "token_count_cache_hits": counter.hits,
            "token_count_probe_calls": probe_counter.calls,
            "token_count_probe_generated_tokens": probe_counter.calls,
            "token_count_probe_total_tokens_counted": probe_counter.total_counted_tokens,
            "token_count_probe_latency_seconds": probe_counter.total_latency_ms / 1000.0,
            "source_replay_mismatches": len(replay_mismatches),
            "format_errors": sum(
                int(not bool(record["direct"]["format_valid"]))  # type: ignore[index]
                for record in records
            ),
            "model_id": warmup.model_id,
            "model_digest": warmup.model_digest,
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
            "partial_records": len(records),
            "partial_model_calls": len(router_responses),
            "partial_token_count_probe_calls": probe_counter.calls,
            "source_replay_mismatches": replay_mismatches,
        }
        paths["manifest"].write_text(
            json.dumps(failed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a paired development-only typed-memory budget sweep"
    )
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
