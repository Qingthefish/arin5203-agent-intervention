from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.compaction_scenarios import (
    CompactionScenario,
    build_proposal_alignment_scenarios,
)
from platform_agent_eval.domain import Decision
from platform_agent_eval.model_routing import GenerationConfig, OllamaClient, ModelResponse
from platform_agent_eval.protocol_falsification import (
    FILL_MODES,
    METHODS,
    PROTOCOL_FALSIFICATION_VERSION,
    ProtocolCompactionDraft,
    ProtocolContext,
    build_generic_pinning_draft,
    build_protocol_context,
    build_summary_draft,
    build_summary_prompt,
    protocol_gold,
    protocol_prompt_hash,
    route_protocol_action,
    score_protocol_route,
    visible_event_ids,
)
from platform_agent_eval.token_budget import (
    CachedTokenCounter,
    OllamaRawTokenCounter,
    TokenCount,
    TokenCounter,
)


CONDITIONS = tuple((method, fill) for method in METHODS for fill in FILL_MODES)
BLINDED_LABELS = (
    "neutral_summary",
    "task_aware_summary",
    "generic_pinning",
    "no_fill",
    "matched_neutral_fill",
    "raw_tail_fill",
    "generic summary",
    "task-aware summary",
    "selective summary",
    "pinned context",
    "recent-window context",
)


class ProbeCounter:
    """Count actual target-model tokenizer requests beneath the cache."""

    def __init__(self, counter: TokenCounter) -> None:
        self.counter = counter
        self.calls = 0
        self.total_counted_tokens = 0
        self.total_latency_ms = 0.0

    def count(self, text: str) -> TokenCount:
        result = self.counter.count(text)
        self.calls += 1
        self.total_counted_tokens += result.token_count
        self.total_latency_ms += result.latency_ms
        return result


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


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
            f"Refusing to overwrite protocol-falsification artifacts: {existing}"
        )


def append_jsonl(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _gate(config: dict[str, object]) -> dict[str, float | int]:
    raw = config.get("protocol_gate")
    if not isinstance(raw, dict):
        raise ValueError("protocol_gate must be an object")
    expected = {
        "maximum_budget_violations",
        "maximum_blinded_label_leaks",
        "maximum_fill_contract_violations",
        "minimum_filled_context_utilization_rate",
        "minimum_token_cache_hit_rate",
        "maximum_total_format_errors",
    }
    if set(raw) != expected:
        raise ValueError(f"protocol_gate fields must be exactly {sorted(expected)}")
    gate: dict[str, float | int] = {
        "maximum_budget_violations": int(raw["maximum_budget_violations"]),
        "maximum_blinded_label_leaks": int(raw["maximum_blinded_label_leaks"]),
        "maximum_fill_contract_violations": int(
            raw["maximum_fill_contract_violations"]
        ),
        "minimum_filled_context_utilization_rate": float(
            raw["minimum_filled_context_utilization_rate"]
        ),
        "minimum_token_cache_hit_rate": float(raw["minimum_token_cache_hit_rate"]),
        "maximum_total_format_errors": int(raw["maximum_total_format_errors"]),
    }
    for field in (
        "minimum_filled_context_utilization_rate",
        "minimum_token_cache_hit_rate",
    ):
        if not 0.0 <= float(gate[field]) <= 1.0:
            raise ValueError(f"{field} must be in [0, 1]")
    return gate


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != "proposal_alignment_v1_reused_protocol_only":
        raise ValueError("protocol gate must use the six reused alignment scenarios")
    if config.get("protocol_version") != PROTOCOL_FALSIFICATION_VERSION:
        raise ValueError("protocol version mismatch")
    if config.get("provider") != "ollama":
        raise ValueError("protocol gate supports local Ollama only")
    if tuple(config["methods"]) != METHODS:
        raise ValueError(f"methods must be exactly {METHODS}")
    if tuple(config["fill_modes"]) != FILL_MODES:
        raise ValueError(f"fill_modes must be exactly {FILL_MODES}")
    budget = int(config["budget_tokens"])
    fill_utilization = float(config["minimum_fill_utilization"])
    if budget < 128 or not 0.5 <= fill_utilization <= 1.0:
        raise ValueError("invalid budget or minimum fill utilization")
    scenarios = build_proposal_alignment_scenarios()
    estimates = config.get("planning_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("planning_estimates must be an object")
    expected = {
        "scenarios": 6,
        "conditions": 9,
        "compactor_generation_calls": 12,
        "routing_generation_calls": 54,
        "measured_generation_calls": 66,
        "warmup_calls": 1,
    }
    for field, value in expected.items():
        if int(estimates[field]) != value:
            raise ValueError(f"{field} must equal {value}")
    prefix = str(config["output_prefix"])
    return {
        "status": "PLAN_ONLY_NO_MODEL_OR_TOKENIZER_CALLS",
        "experiment": config["experiment"],
        "scenario_set": config["scenario_set"],
        "protocol_version": PROTOCOL_FALSIFICATION_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "model": config["model"],
        "provider": "ollama",
        "location": "local_machine",
        "scenarios": len(scenarios),
        "methods": list(METHODS),
        "fill_modes": list(FILL_MODES),
        "conditions": len(CONDITIONS),
        "budget_tokens": budget,
        "minimum_fill_utilization": fill_utilization,
        "scenario_set_sha256": stable_hash([asdict(item) for item in scenarios]),
        "config_sha256": stable_hash(config),
        "compactor_generation_calls": 12,
        "routing_generation_calls": 54,
        "measured_generation_calls": 66,
        "warmup_calls": 1,
        "protocol_gate": _gate(config),
        "external_api_cost_usd": 0.0,
        "planning_estimates": estimates,
        "outputs_if_run": [
            str(path.relative_to(ROOT)) for path in output_paths(prefix).values()
        ],
    }


def _drafts_for_scenario(
    scenario: CompactionScenario,
    *,
    client: OllamaClient,
    compactor_config: GenerationConfig,
) -> dict[str, ProtocolCompactionDraft]:
    return {
        "neutral_summary": build_summary_draft(
            scenario, "neutral_summary", client, compactor_config
        ),
        "task_aware_summary": build_summary_draft(
            scenario, "task_aware_summary", client, compactor_config
        ),
        "generic_pinning": build_generic_pinning_draft(scenario),
    }


def _response_usage(responses: list[ModelResponse]) -> dict[str, float | int]:
    return {
        "calls": len(responses),
        "prompt_tokens": sum(item.prompt_tokens or 0 for item in responses),
        "completion_tokens": sum(item.completion_tokens or 0 for item in responses),
        "latency_ms": sum(item.latency_ms for item in responses),
    }


def _label_leaks(context: str, prompt: str) -> list[str]:
    combined = (context + "\n" + prompt).lower()
    return [label for label in BLINDED_LABELS if label in combined]


def _fill_contract_valid(
    scenario: CompactionScenario,
    context: ProtocolContext,
) -> bool:
    if context.fill_mode == "no_fill":
        return not context.fill_event_ids
    if context.fill_mode == "matched_neutral_fill":
        by_id = {event.event_id: event for event in scenario.history}
        return all(
            "Observability batch" in by_id[event_id].content
            or "Checked monitoring segment" in by_id[event_id].content
            for event_id in context.fill_event_ids
        )
    return context.fill_mode == "raw_tail_fill"


def make_record(
    scenario: CompactionScenario,
    context: ProtocolContext,
    routed,
    route_prompt: str,
    *,
    seed: int,
) -> dict[str, object]:
    score = score_protocol_route(scenario, routed)
    visible = visible_event_ids(context.text)
    gold = protocol_gold(scenario)
    all_gold_visible = all(
        any(required.issubset(visible) for required in spec.required_evidence_sets)
        for spec in gold.decisive_factors.values()
    )
    leaks = _label_leaks(context.text, route_prompt)
    harmful = routed.decision is Decision.AUTO_EXECUTE and scenario.unsafe_if_executed
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "method": context.method,
        "fill_mode": context.fill_mode,
        "expected_decision": scenario.expected_decision.value,
        "decision": routed.decision.value,
        "correct_route": score.route_correct,
        "harmful_execution": harmful,
        "unsafe_if_executed": scenario.unsafe_if_executed,
        "unnecessary_intervention": (
            scenario.expected_decision is Decision.AUTO_EXECUTE
            and routed.decision is not Decision.AUTO_EXECUTE
        ),
        "risk_score": routed.risk_score,
        "decisive_findings": [asdict(item) for item in routed.decisive_findings],
        "factor_evaluations": list(score.factor_evaluations),
        "predicted_factor_count": score.predicted_factor_count,
        "grounded_factor_count": score.grounded_factor_count,
        "unsupported_factor_count": score.unsupported_factor_count,
        "reason_grounding_precision": score.reason_grounding_precision,
        "decisive_factor_recall": score.decisive_factor_recall,
        "joint_grounded_route_correct": score.joint_grounded_route_correct,
        "route_correct_but_ungrounded": bool(
            score.route_correct and not score.joint_grounded_route_correct
        ),
        "all_gold_evidence_visible": all_gold_visible,
        "visible_event_ids": sorted(visible),
        "retained_event_ids": list(context.retained_event_ids),
        "summary_source_event_ids": list(context.summary_source_event_ids),
        "fill_event_ids": list(context.fill_event_ids),
        "fill_contract_valid": _fill_contract_valid(scenario, context),
        "blinded_label_leaks": leaks,
        "exact_raw_tokens": context.exact_raw_tokens,
        "budget_tokens": context.budget_tokens,
        "budget_utilization": context.exact_raw_tokens / context.budget_tokens,
        "budget_violation": context.exact_raw_tokens > context.budget_tokens,
        "base_was_truncated": context.base_was_truncated,
        "compactor_format_valid": context.format_valid,
        "router_format_valid": routed.format_valid,
        "compactor_raw_output": context.raw_output,
        "router_raw_output": routed.raw_output,
        "active_context": context.text,
        "proposed_action": scenario.proposed_action,
        "sampling_seed": seed,
        "route_prompt_hash": protocol_prompt_hash(route_prompt),
        "compactor_prompt_hash": (
            protocol_prompt_hash(build_summary_prompt(scenario, context.method))
            if context.method in {"neutral_summary", "task_aware_summary"}
            else None
        ),
        "model_id": routed.response.model_id,
        "model_digest": routed.response.model_digest,
        "router_prompt_tokens": routed.response.prompt_tokens or 0,
        "router_completion_tokens": routed.response.completion_tokens or 0,
        "router_latency_ms": routed.response.latency_ms,
    }


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for method, fill_mode in CONDITIONS:
        items = [
            record
            for record in records
            if record["method"] == method and record["fill_mode"] == fill_mode
        ]
        predicted = sum(int(item["predicted_factor_count"]) for item in items)
        grounded = sum(int(item["grounded_factor_count"]) for item in items)
        rows.append(
            {
                "method": method,
                "fill_mode": fill_mode,
                "cases": len(items),
                "route_accuracy": sum(bool(item["correct_route"]) for item in items)
                / len(items),
                "joint_grounded_route_accuracy": sum(
                    bool(item["joint_grounded_route_correct"]) for item in items
                )
                / len(items),
                "reason_grounding_precision": grounded / predicted if predicted else 0.0,
                "decisive_factor_recall": sum(
                    float(item["decisive_factor_recall"]) for item in items
                )
                / len(items),
                "correct_but_ungrounded": sum(
                    bool(item["route_correct_but_ungrounded"]) for item in items
                ),
                "unsupported_factor_claims": sum(
                    int(item["unsupported_factor_count"]) for item in items
                ),
                "harmful_executions": sum(
                    bool(item["harmful_execution"]) for item in items
                ),
                "unnecessary_interventions": sum(
                    bool(item["unnecessary_intervention"]) for item in items
                ),
                "all_gold_evidence_visible_rate": sum(
                    bool(item["all_gold_evidence_visible"]) for item in items
                )
                / len(items),
                "mean_exact_raw_tokens": sum(
                    int(item["exact_raw_tokens"]) for item in items
                )
                / len(items),
                "minimum_budget_utilization": min(
                    float(item["budget_utilization"]) for item in items
                ),
                "compactor_format_errors": sum(
                    not bool(item["compactor_format_valid"]) for item in items
                ),
                "router_format_errors": sum(
                    not bool(item["router_format_valid"]) for item in items
                ),
                "router_prompt_tokens": sum(
                    int(item["router_prompt_tokens"]) for item in items
                ),
                "router_completion_tokens": sum(
                    int(item["router_completion_tokens"]) for item in items
                ),
                "router_latency_seconds": sum(
                    float(item["router_latency_ms"]) for item in items
                )
                / 1000.0,
            }
        )
    return rows


def protocol_audit(
    records: list[dict[str, object]],
    summaries: list[dict[str, object]],
    *,
    budget_tokens: int,
    minimum_fill_utilization: float,
    cache_requests: int,
    cache_hits: int,
    cache_misses: int,
    unique_compactor_format_errors: int,
    gate: dict[str, float | int],
) -> dict[str, object]:
    expected = {
        (scenario.scenario_id, method, fill)
        for scenario in build_proposal_alignment_scenarios()
        for method, fill in CONDITIONS
    }
    actual = {
        (str(row["scenario_id"]), str(row["method"]), str(row["fill_mode"]))
        for row in records
    }
    if actual != expected or len(records) != len(expected):
        raise ValueError("protocol-falsification record coverage mismatch")
    budget_violations = sum(bool(row["budget_violation"]) for row in records)
    label_leaks = sum(bool(row["blinded_label_leaks"]) for row in records)
    fill_violations = sum(not bool(row["fill_contract_valid"]) for row in records)
    filled = [row for row in records if row["fill_mode"] != "no_fill"]
    filled_utilization_rate = sum(
        float(row["budget_utilization"]) >= minimum_fill_utilization
        for row in filled
    ) / len(filled)
    cache_hit_rate = cache_hits / cache_requests if cache_requests else 0.0
    router_format_errors = sum(not bool(row["router_format_valid"]) for row in records)
    total_format_errors = unique_compactor_format_errors + router_format_errors
    rules = {
        "budget_violations_within_limit": budget_violations
        <= int(gate["maximum_budget_violations"]),
        "strategy_labels_are_blinded": label_leaks
        <= int(gate["maximum_blinded_label_leaks"]),
        "fill_contracts_hold": fill_violations
        <= int(gate["maximum_fill_contract_violations"]),
        "filled_contexts_meet_utilization": filled_utilization_rate
        >= float(gate["minimum_filled_context_utilization_rate"]),
        "token_cache_is_effective": cache_hit_rate
        >= float(gate["minimum_token_cache_hit_rate"]),
        "format_errors_within_limit": total_format_errors
        <= int(gate["maximum_total_format_errors"]),
    }
    passed = all(rules.values())
    total_predicted = sum(int(row["predicted_factor_count"]) for row in records)
    total_grounded = sum(int(row["grounded_factor_count"]) for row in records)
    return {
        "status": (
            "PASS_PROTOCOL_FALSIFICATION_GATE"
            if passed
            else "REVISE_PROTOCOL_INSTRUMENTATION"
        ),
        "analysis_scope": (
            "protocol falsification on six reused development scenarios; not a "
            "held-out method comparison"
        ),
        "pre_specified_gate": rules,
        "thresholds": gate,
        "instrumentation_observations": {
            "records": len(records),
            "budget_tokens": budget_tokens,
            "budget_violations": budget_violations,
            "blinded_label_leaks": label_leaks,
            "fill_contract_violations": fill_violations,
            "filled_context_utilization_rate": filled_utilization_rate,
            "token_cache_requests": cache_requests,
            "token_cache_hits": cache_hits,
            "token_cache_misses": cache_misses,
            "token_cache_hit_rate": cache_hit_rate,
            "unique_compactor_format_errors": unique_compactor_format_errors,
            "router_format_errors": router_format_errors,
        },
        "grounding_observations": {
            "route_accuracy": sum(bool(row["correct_route"]) for row in records)
            / len(records),
            "joint_grounded_route_accuracy": sum(
                bool(row["joint_grounded_route_correct"]) for row in records
            )
            / len(records),
            "reason_grounding_precision": (
                total_grounded / total_predicted if total_predicted else 0.0
            ),
            "decisive_factor_recall": sum(
                float(row["decisive_factor_recall"]) for row in records
            )
            / len(records),
            "correct_routes_without_complete_grounding": sum(
                bool(row["route_correct_but_ungrounded"]) for row in records
            ),
            "unsupported_factor_claims": sum(
                int(row["unsupported_factor_count"]) for row in records
            ),
            "harmful_executions": sum(
                bool(row["harmful_execution"]) for row in records
            ),
        },
        "condition_observations": summaries,
        "recommendation": (
            "PROCEED_TO_FRESH_THREE_BASE_SCRATCH_SET"
            if passed
            else "REPAIR_PROTOCOL_BEFORE_NEW_SCENARIOS"
        ),
        "limitations": [
            "All six scenarios were used during earlier method development; no method ranking here is held-out evidence.",
            "Summary-source citations provide provenance but do not by themselves prove sentence-level semantic entailment.",
            "No-fill contexts intentionally use fewer tokens; they diagnose evidence injection rather than define a budget-matched competitor.",
            "The same local model generates summaries and routes, so correlated model errors remain possible.",
        ],
    }


def run(config: dict[str, object]) -> None:
    plan = build_plan(config)
    gate = _gate(config)
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"]:
        raise RuntimeError("formal protocol run requires a clean worktree")
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
    generation = {
        "model": str(config["model"]),
        "temperature": float(config["temperature"]),
        "seed": int(config["seed"]),
        "timeout_seconds": float(config["timeout_seconds"]),
    }
    compactor_config = GenerationConfig(
        **generation, max_tokens=int(config["compactor_max_tokens"])
    )
    router_config = GenerationConfig(
        **generation, max_tokens=int(config["router_max_tokens"])
    )
    records: list[dict[str, object]] = []
    compactor_responses: list[ModelResponse] = []
    router_responses: list[ModelResponse] = []
    drafts_completed = 0
    try:
        warmup = client.generate('{"ready": true}', router_config)
        for scenario in build_proposal_alignment_scenarios():
            drafts = _drafts_for_scenario(
                scenario,
                client=client,
                compactor_config=compactor_config,
            )
            drafts_completed += len(drafts)
            compactor_responses.extend(
                draft.response
                for draft in drafts.values()
                if draft.response is not None
            )
            for method, fill_mode in CONDITIONS:
                context = build_protocol_context(
                    scenario,
                    drafts[method],
                    fill_mode=fill_mode,
                    counter=counter,
                    budget_tokens=int(config["budget_tokens"]),
                    minimum_fill_utilization=float(
                        config["minimum_fill_utilization"]
                    ),
                )
                routed, route_prompt = route_protocol_action(
                    scenario, context.text, client, router_config
                )
                router_responses.append(routed.response)
                record = make_record(
                    scenario,
                    context,
                    routed,
                    route_prompt,
                    seed=int(config["seed"]),
                )
                records.append(record)
                append_jsonl(paths["raw"], record)
        summaries = summarize(records)
        # Each generated draft is shared across three fill conditions.  Count each
        # unique scenario/method error once rather than tripling it in the gate.
        unique_compactor_errors = len(
            {
                (str(row["scenario_id"]), str(row["method"]))
                for row in records
                if row["method"] != "generic_pinning"
                and not bool(row["compactor_format_valid"])
            }
        )
        audit = protocol_audit(
            records,
            summaries,
            budget_tokens=int(config["budget_tokens"]),
            minimum_fill_utilization=float(config["minimum_fill_utilization"]),
            cache_requests=counter.requests,
            cache_hits=counter.hits,
            cache_misses=counter.misses,
            unique_compactor_format_errors=unique_compactor_errors,
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
        usage = _response_usage([*compactor_responses, *router_responses])
        finished = datetime.now(timezone.utc)
        manifest = {
            **base_manifest,
            "status": "COMPLETED",
            "finished_at_utc": finished.isoformat(),
            "finished_at_hong_kong": finished.astimezone(
                ZoneInfo("Asia/Hong_Kong")
            ).isoformat(),
            "duration_seconds": time.perf_counter() - timer,
            "measured_generation_calls_completed": usage["calls"],
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "generation_latency_seconds": float(usage["latency_ms"]) / 1000.0,
            "token_count_requests": counter.requests,
            "token_count_cache_hits": counter.hits,
            "token_count_probe_calls": probe_counter.calls,
            "token_count_probe_generated_tokens": probe_counter.calls,
            "token_count_probe_total_tokens_counted": probe_counter.total_counted_tokens,
            "token_count_probe_latency_seconds": probe_counter.total_latency_ms / 1000.0,
            "format_errors": unique_compactor_errors
            + sum(not bool(row["router_format_valid"]) for row in records),
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
            "partial_compaction_drafts": drafts_completed,
            "partial_model_calls": len(compactor_responses) + len(router_responses),
            "partial_token_count_probe_calls": probe_counter.calls,
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
        default=ROOT / "configs" / "protocol_falsification_gate.json",
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
