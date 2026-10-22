"""Natural-language evidence extraction experiment (development tool).

Plan-only by default. A real local run needs BOTH ``--run`` and
``--acknowledge-experiment-plan`` and a local Ollama server.

For each selected natural-language context the model extracts evidence claims,
the claims become proof cards, and the frozen deterministic validator routes the
action. Gold labels are used only for scoring.

Examples (from 05_代码与实验/):

    python3 scripts/run_nl_evidence_extraction.py                       # print plan only
    python3 scripts/run_nl_evidence_extraction.py --split dev --variant clean --limit 6 \
        --output-prefix nl_extract_smoke_local_v1 --run --acknowledge-experiment-plan
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.model_routing import GenerationConfig, OllamaClient  # noqa: E402
from platform_agent_eval.natural_language_evidence import (  # noqa: E402
    NL_EVIDENCE_VERSION,
    NL_EXTRACTION_PROMPT_VERSION,
    EXTRACTION_METRIC_DEFINITIONS,
    build_extraction_prompt,
    build_nl_contexts,
    context_record,
    oracle_decision,
    parse_extraction_output,
    score_extraction,
)

RESULTS = ROOT / "results"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        groups["all"].append(record)
        groups[f"{record['split']}/{record['variant']}"].append(record)
        groups[f"{record['split']}/{record['variant']}/{record['condition']}"].append(record)
        groups[f"domain/{record.get('domain', 'unknown')}/{record['variant']}"].append(record)
    summary: dict[str, object] = {}
    for key, items in sorted(groups.items()):
        scores = [item["score"] for item in items]  # type: ignore[index]
        summary[key] = {
            "contexts": len(items),
            "route_accuracy": _mean([float(s["route_correct"]) for s in scores]),
            "visible_oracle_agreement": _mean([float(s["route_matches_visible_oracle"]) for s in scores]),
            "candidate_visible_oracle_agreement": _mean([float(s["candidate_route_matches_visible_oracle"]) for s in scores]),
            "candidate_harmful_executions": sum(bool(s["candidate_harmful_execution"]) for s in scores),
            "harmful_executions": sum(bool(s["harmful_execution"]) for s in scores),
            "unjustified_executions": sum(bool(s["unjustified_execution"]) for s in scores),
            "unnecessary_interventions": sum(bool(s["unnecessary_intervention"]) for s in scores),
            "mean_card_precision": _mean([float(s["card_precision"]) for s in scores]),
            "mean_card_recall": _mean([float(s["card_recall"]) for s in scores]),
            "distractor_false_positives": sum(bool(s["distractor_false_positive"]) for s in scores),
            "format_errors": sum(not s["format_valid"] for s in scores),
            "dropped_claims": sum(int(s["dropped_claims"]) for s in scores),
            "mean_all_source_exact_precision": _mean([float(s["all_source_exact_precision"]) for s in scores]),
            "mean_all_source_exact_recall": _mean([float(s["all_source_exact_recall"]) for s in scores]),
            "matched_field_correct": sum(int(s["matched_field_correct"]) for s in scores),
            "matched_field_total": sum(int(s["matched_field_total"]) for s in scores),
            "unsupported_source_claims": sum(int(s["unsupported_source_claims"]) for s in scores),
            "invented_field_claims": sum(int(s["invented_field_claims"]) for s in scores),
            "omitted_literal_gold_claims": sum(int(s["omitted_literal_gold_claims"]) for s in scores),
            "oracle_route_accuracy": _mean(
                [float(item["oracle_decision"] == item["expected_decision"]) for item in items]
            ),
        }
    return summary


def paired_diagnostics(records):
    """Declared comparisons; partial bundles report missing pairs, not success."""
    by_key = {(r["family_id"], r["variant"], r["condition"]): r for r in records}
    pairs = []
    for family in sorted({r["family_id"] for r in records}):
        for condition in sorted({r["condition"] for r in records}):
            clean = by_key.get((family, "clean", condition))
            distractor = by_key.get((family, "distractor", condition))
            if clean is None or distractor is None:
                continue
            pairs.append({
                "family_id": family, "condition": condition,
                "clean_decision": clean["score"]["decision"],
                "distractor_decision": distractor["score"]["decision"],
                "route_changed": clean["score"]["decision"] != distractor["score"]["decision"],
                "spoiled_world_correct_route": clean["score"]["route_correct"] and not distractor["score"]["route_correct"],
                "repaired_world_incorrect_route": not clean["score"]["route_correct"] and distractor["score"]["route_correct"],
                "spoiled_visible_oracle_match": clean["score"]["route_matches_visible_oracle"] and not distractor["score"]["route_matches_visible_oracle"],
            })
    noise_pairs = []
    for family, variant in sorted({(r["family_id"], r["variant"]) for r in records}):
        full = by_key.get((family, variant, "full_evidence"))
        noise = by_key.get((family, variant, "remove_matched_noise"))
        if full is not None and noise is not None:
            noise_pairs.append({
                "family_id": family, "variant": variant,
                "route_changed": full["score"]["decision"] != noise["score"]["decision"],
            })
    return {
        "claim_scope": "Descriptive paired contrasts on derived development families, not independent samples or a compactor comparison.",
        "clean_distractor_pairs": pairs,
        "noise_pairs": noise_pairs,
        "clean_distractor_route_changes": sum(p["route_changed"] for p in pairs),
        "clean_distractor_spoiled_world_routes": sum(p["spoiled_world_correct_route"] for p in pairs),
        "clean_distractor_repaired_world_routes": sum(p["repaired_world_incorrect_route"] for p in pairs),
        "noise_route_changes": sum(p["route_changed"] for p in noise_pairs),
        "upstream_hidden_hold_records": sum(bool(r.get("hidden_hold_deletion")) for r in records),
        "world_errors_matching_visible_oracle": sum(not r["score"]["route_correct"] and r["score"]["route_matches_visible_oracle"] for r in records),
        "visible_oracle_disagreements": sum(not r["score"]["route_matches_visible_oracle"] for r in records),
    }


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def output_paths(prefix: str, directory: Path = RESULTS) -> dict[str, Path]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", prefix):
        raise ValueError("output prefix must be a simple versioned name")
    return {key: directory / f"{prefix}_{suffix}" for key, suffix in (
        ("raw", "raw.jsonl"), ("summary", "summary.csv"),
        ("audit", "audit.json"), ("manifest", "manifest.json"),
    )}


def select_contexts(contexts, family_ids=(), limit: int = 0):
    """Select whole triples; never silently truncate a multi-variant pairing."""
    if limit < 0 or limit % 3:
        raise ValueError("limit must be zero or a positive multiple of three")
    wanted = set(family_ids)
    unknown = wanted - {c.family_id for c in contexts}
    if unknown:
        raise ValueError(f"unknown selected family IDs: {sorted(unknown)}")
    selected = [c for c in contexts if not wanted or c.family_id in wanted]
    if limit and len({c.variant for c in selected}) > 1:
        raise ValueError("multi-variant runs require explicit family IDs, not --limit")
    return selected[:limit] if limit else selected


def freeze_or_verify_plan(plan, path: Path, *, running: bool) -> None:
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != plan:
            raise ValueError("current plan differs from the frozen plan")
        return
    if running:
        raise ValueError("freeze the plan in a plan-only invocation before running")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def build_plan(contexts, config: GenerationConfig, base_url: str, paths, context_window: int = 8192) -> dict[str, object]:
    endpoint = urlsplit(base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("this zero-fee runner supports loopback Ollama only")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}:
        raise ValueError("use a plain loopback Ollama origin")
    if not contexts or config.max_tokens <= 0 or config.seed < 0 or context_window <= config.max_tokens:
        raise ValueError("need contexts, positive max-tokens and nonnegative seed")
    prompts = [build_extraction_prompt(c) for c in contexts]
    prompt_chars = sum(len(p) for p in prompts)
    configuration = {**asdict(config), "base_url": base_url, "context_window_tokens": context_window}
    dataset = [context_record(c) for c in contexts]
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": "natural-language-evidence-extraction",
        "scenario_set": NL_EVIDENCE_VERSION,
        "prompt_version": NL_EXTRACTION_PROMPT_VERSION,
        "provider": "ollama", "location": "local_machine", "model": config.model,
        "configuration": configuration,
        "config_sha256": sha256(json.dumps(configuration, sort_keys=True)),
        "dataset_sha256": sha256(json.dumps(dataset, sort_keys=True)),
        "scoring_reference_sha256": sha256(json.dumps([asdict(c) for c in contexts], sort_keys=True)),
        "implementation_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), ROOT / "src/platform_agent_eval/natural_language_evidence.py",
                         ROOT / "src/platform_agent_eval/proof_cards.py", ROOT / "src/platform_agent_eval/model_routing.py")
        },
        "prompt_hashes": {c.case_id: sha256(p) for c, p in zip(contexts, prompts)},
        "selected_family_ids": sorted({c.family_id for c in contexts}),
        "selected_case_ids": [c.case_id for c in contexts],
        "splits": sorted({c.split for c in contexts}),
        "variants": sorted({c.variant for c in contexts}),
        "contexts": len(contexts), "model_calls": len(contexts),
        "estimated_minutes_local_range": [round(len(contexts) / 3, 1), round(len(contexts) * 1.5, 1)],
        "estimated_input_tokens_range": [prompt_chars // 6, prompt_chars // 2],
        "maximum_output_tokens": len(contexts) * config.max_tokens,
        "token_estimate_note": "planning estimate only; not tokenizer-matched or a compaction comparison",
        "external_api_cost_usd": 0.0,
        "claim_scope": "derived-family extraction diagnostic; no independent held-out or compaction-ranking claim",
        "protocol_gate": {"missing_or_duplicate_records": 0, "prompt_hash_errors": 0,
                          "unknown_usage_records": 0},
        "quality_policy": "Report format errors, fidelity and downstream mistakes; no effectiveness PASS threshold, retries or automatic expansion.",
        "field_fidelity_definitions": EXTRACTION_METRIC_DEFINITIONS,
        "metric_scope": {
            "card_precision_recall": "Exact signatures among action-applicable claims only; these legacy metrics ignore correctly nonapplicable records.",
            "all_source_exact_precision_recall": "Literal-source signatures including declared invalid distractors; malformed claims count against precision.",
            "matched_fields": "Ten normalized signature fields on claimed declared sources; omitted cards are separately counted, so this conditional accuracy is not recall.",
            "visible_oracle": "A perfect visible-evidence extractor can still Execute after an upstream hold was removed; world-gold and visible-oracle agreement are distinct.",
            "matching": "Critical/noise and clean/distractor replacement events use equal UTF-8 bytes and the same role/position; no equal-token or compactor-ranking claim.",
        },
        "outputs": {key: str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
                    for key, path in paths.items()},
    }


def audit_records(records, contexts, plan) -> dict[str, object]:
    expected_ids = [c.case_id for c in contexts]
    hashes = plan["prompt_hashes"]
    actual_ids = [r["case_id"] for r in records]
    criteria = {
        "complete_ordered_records": actual_ids == expected_ids,
        "prompt_hashes_match": all(r["prompt_sha256"] == hashes.get(r["case_id"])
                                   and sha256(r["prompt"]) == r["prompt_sha256"] for r in records),
        "usage_recorded": all(isinstance(r[k], int) and r[k] >= 0
                              for r in records for k in ("prompt_tokens", "completion_tokens")),
        "model_identity_recorded": all(bool(r["model_id"]) for r in records),
    }
    return {"status": "PASS" if all(criteria.values()) else "FAIL", "criteria": criteria,
            "format_valid_records": sum(bool(r["score"]["format_valid"]) for r in records),
            "claim_scope": "recording instrumentation only; model format/fidelity errors are diagnostic outcomes, not reasons to tune and retry",
            "summary": summarize(records), "paired_diagnostics": paired_diagnostics(records)}


def _git_provenance() -> dict[str, object]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return {"git_commit": commit, "git_worktree_dirty_at_start": bool(dirty)}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_worktree_dirty_at_start": None}


def run_experiment(contexts, config, plan, paths, client) -> dict[str, object]:
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("refusing to overwrite existing experiment artifacts")
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    manifest = {**plan, **_git_provenance(), "status": "RUNNING",
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version()}
    # Reserve the prefix before contacting Ollama; interrupted launches remain discoverable.
    with paths["manifest"].open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    started = time.perf_counter()
    records = []
    attempts = 0
    failure = None
    interrupted = False
    try:
        with paths["raw"].open("x", encoding="utf-8") as handle:
            for context in contexts:
                prompt = build_extraction_prompt(context)
                attempts += 1
                response = client.generate(prompt, config)
                parsed = parse_extraction_output(response.text, {e.event_id: e.content for e in context.active_events})
                record = {
                    "case_id": context.case_id, "family_id": context.family_id,
                    "domain": context.domain,
                    "split": context.split, "variant": context.variant, "condition": context.condition,
                    "critical_kind": context.critical_kind.value,
                    "hidden_hold_deletion": context.condition == "remove_action_critical" and context.critical_kind.value == "ACTIVE_HOLD",
                    "expected_decision": context.expected_decision.value,
                    "oracle_decision": oracle_decision(context).value,
                    "score": score_extraction(context, parsed), "raw_output": response.text,
                    "extracted_claims": [asdict(claim) for claim in parsed.claims],
                    "prompt": prompt, "prompt_sha256": sha256(prompt), "parse_error": parsed.error,
                    "prompt_tokens": response.prompt_tokens, "completion_tokens": response.completion_tokens,
                    "latency_ms": response.latency_ms, "model_id": response.model_id,
                    "model_digest": response.model_digest,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                records.append(record)
                print(f"[{len(records)}/{len(contexts)}] {context.case_id}: {record['score']['decision']}")
    except (Exception, KeyboardInterrupt) as exc:
        failure = f"{type(exc).__name__}: {exc}"
        interrupted = isinstance(exc, KeyboardInterrupt)
    audit = audit_records(records, contexts, plan)
    audit["run_error"] = failure
    if failure:
        audit["status"] = "FAIL"
    with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
        groups = summarize(records)
        fields = ["group", *next(iter(groups.values())).keys()] if groups else ["group", "contexts"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group, values in groups.items():
            writer.writerow({"group": group, **values})
    with paths["audit"].open("x", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2)
    manifest.update({
        "status": "ABORTED" if interrupted else ("FAILED" if failure else "COMPLETED"),
        "completed_model_calls": len(records), "attempted_model_calls": attempts,
        "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in records),
        "completion_tokens": sum(r["completion_tokens"] or 0 for r in records),
        "unknown_usage_records": sum(r["prompt_tokens"] is None or r["completion_tokens"] is None for r in records),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.perf_counter() - started, 3), "error": failure,
        "audit_status": audit["status"],
        "artifact_sha256": {k: hashlib.sha256(paths[k].read_bytes()).hexdigest() for k in ("raw", "summary", "audit")},
        "recommendation": "REPORT_DIAGNOSTIC_WITHOUT_RETUNING" if audit["status"] == "PASS" else "INSPECT_RECORDING_FAILURE_NO_AUTOMATIC_RERUN",
    })
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if interrupted:
        raise KeyboardInterrupt
    if failure:
        raise RuntimeError(failure)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--variant", choices=["clean", "distractor", "all"], default="clean")
    parser.add_argument("--limit", type=int, default=0, help="first N contexts, in whole sibling triples (0 = all)")
    parser.add_argument("--family-id", action="append", default=[], help="select a family explicitly; repeat for multiple families")
    parser.add_argument("--plan-file", type=Path, help="create an immutable plan in plan-only mode; verify the identical plan before running")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--max-tokens", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=5203)
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--output-prefix", default="nl_extract_dev_local_v1")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    args = parser.parse_args()
    if args.limit < 0 or args.limit % 3:
        parser.error("--limit must be zero or a positive multiple of three")
    splits = ("dev", "test") if args.split == "all" else (args.split,)
    variants = ("clean", "distractor") if args.variant == "all" else (args.variant,)
    contexts = build_nl_contexts(variants=variants, splits=splits)
    try:
        contexts = select_contexts(contexts, args.family_id, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    paths = output_paths(args.output_prefix)
    config = GenerationConfig(model=args.model, temperature=0.0, seed=args.seed,
                              max_tokens=args.max_tokens, timeout_seconds=args.timeout_seconds)
    plan = build_plan(contexts, config, args.base_url, paths, args.context_window)
    if args.plan_file:
        try:
            freeze_or_verify_plan(plan, args.plan_file, running=args.run)
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if "test" in splits:
        print("Derived test-family rewrites are not new independent held-out data; original held-out results stay frozen.")
    if not args.run:
        print("Plan only. Add --run --acknowledge-experiment-plan to call the local model.")
        return
    if not args.acknowledge_experiment_plan:
        parser.error("--run requires --acknowledge-experiment-plan")
    audit = run_experiment(contexts, config, plan, paths,
                           OllamaClient(args.base_url, num_ctx=args.context_window))
    print(json.dumps(audit, indent=2))
    if audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
