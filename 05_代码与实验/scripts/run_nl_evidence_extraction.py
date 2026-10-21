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
import json
import platform
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.model_routing import GenerationConfig, OllamaClient  # noqa: E402
from platform_agent_eval.natural_language_evidence import (  # noqa: E402
    NL_EVIDENCE_VERSION,
    NL_EXTRACTION_PROMPT_VERSION,
    build_extraction_prompt,
    build_nl_contexts,
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
    summary: dict[str, object] = {}
    for key, items in sorted(groups.items()):
        scores = [item["score"] for item in items]  # type: ignore[index]
        summary[key] = {
            "contexts": len(items),
            "route_accuracy": _mean([float(s["route_correct"]) for s in scores]),
            "harmful_executions": sum(bool(s["harmful_execution"]) for s in scores),
            "unjustified_executions": sum(bool(s["unjustified_execution"]) for s in scores),
            "unnecessary_interventions": sum(bool(s["unnecessary_intervention"]) for s in scores),
            "mean_card_precision": _mean([float(s["card_precision"]) for s in scores]),
            "mean_card_recall": _mean([float(s["card_recall"]) for s in scores]),
            "distractor_false_positives": sum(bool(s["distractor_false_positive"]) for s in scores),
            "format_errors": sum(not s["format_valid"] for s in scores),
            "oracle_route_accuracy": _mean(
                [float(item["oracle_decision"] == item["expected_decision"]) for item in items]
            ),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--variant", choices=["clean", "distractor", "all"], default="clean")
    parser.add_argument("--limit", type=int, default=0, help="first N contexts only (0 = all)")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--seed", type=int, default=5203)
    parser.add_argument("--output-prefix", default="nl_extract_dev_local_v1")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    args = parser.parse_args()

    splits = ("dev", "test") if args.split == "all" else (args.split,)
    variants = ("clean", "distractor") if args.variant == "all" else (args.variant,)
    contexts = build_nl_contexts(variants=variants, splits=splits)  # type: ignore[arg-type]
    if args.limit:
        contexts = contexts[: args.limit]

    paths = {
        name: RESULTS / f"{args.output_prefix}_{name}"
        for name in ("raw.jsonl", "summary.json", "manifest.json")
    }
    plan = {
        "dataset_version": NL_EVIDENCE_VERSION,
        "prompt_version": NL_EXTRACTION_PROMPT_VERSION,
        "model": args.model,
        "splits": list(splits),
        "variants": list(variants),
        "contexts": len(contexts),
        "model_calls": len(contexts),
        "estimated_minutes_local": round(len(contexts) * 12 / 60, 1),
        "external_api_cost_usd": 0.0,
        "outputs": [str(path.relative_to(ROOT)) for path in paths.values()],
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if "test" in splits:
        print("WARNING: 'test' contexts derive from the frozen held-out families. "
              "Tune prompts on dev only, and run test once.")
    if not args.run:
        print("Plan only. Add --run --acknowledge-experiment-plan to call the local model.")
        return
    if not args.acknowledge_experiment_plan:
        raise SystemExit("--run requires --acknowledge-experiment-plan")
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite existing outputs: {existing}")

    client = OllamaClient(args.base_url)
    config = GenerationConfig(
        model=args.model, temperature=0.0, seed=args.seed, max_tokens=args.max_tokens
    )
    started = time.time()
    records: list[dict[str, object]] = []
    RESULTS.mkdir(exist_ok=True)
    with paths["raw.jsonl"].open("w", encoding="utf-8") as handle:
        for index, context in enumerate(contexts, start=1):
            prompt = build_extraction_prompt(context)
            response = client.generate(prompt, config)
            visible = {event.event_id for event in context.active_events}
            parse = parse_extraction_output(response.text, visible)
            score = score_extraction(context, parse)
            record = {
                "case_id": context.case_id,
                "split": context.split,
                "variant": context.variant,
                "condition": context.condition,
                "expected_decision": context.expected_decision.value,
                "oracle_decision": oracle_decision(context).value,
                "score": score,
                "raw_output": response.text,
                "parse_error": parse.error,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "latency_ms": response.latency_ms,
                "model_id": response.model_id,
                "model_digest": response.model_digest,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            records.append(record)
            print(f"[{index}/{len(contexts)}] {context.case_id}: "
                  f"{score['decision']} (expected {context.expected_decision.value})")

    summary = summarize(records)
    paths["summary.json"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        **plan,
        "completed_contexts": len(records),
        "wall_seconds": round(time.time() - started, 1),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "claim_scope": "development diagnostic; not a held-out result unless run once on test",
    }
    paths["manifest.json"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(summary.get("all"), indent=2))


if __name__ == "__main__":
    main()
