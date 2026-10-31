#!/usr/bin/env python3
"""Family-clustered bootstrap intervals for the frozen one-shot held-out run.

Zero model calls. Reads the immutable held-out raw trace, resamples the eleven
base families with replacement (siblings stay together), and reports 95%
percentile intervals for per-method counts and the audit-minus-direct change.

    python3 scripts/bootstrap_heldout_ci.py            # print only
    python3 scripts/bootstrap_heldout_ci.py --write    # also write results/heldout_bootstrap_ci_v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"
OUTPUT = ROOT / "results" / "heldout_bootstrap_ci_v1.json"
STABLE = {"full_evidence", "remove_matched_noise"}
METHODS = (
    "full_context_ceiling",
    "recent_window",
    "neutral_summary",
    "task_aware_summary",
    "generic_pinning",
    "ufold_lite",
    "typed_card_retention",
)
METRICS = {
    "stable_correct_direct": lambda r: r["condition"] in STABLE and r["direct"]["route_correct"],
    "stable_correct_audit": lambda r: r["condition"] in STABLE and r["audited"]["route_correct"],
    "harmful_direct": lambda r: bool(r["direct"]["harmful_execution"]),
    "harmful_audit": lambda r: bool(r["audited"]["harmful_execution"]),
}


def family_counts(records: list[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """counts[method][family][metric] for one family's three siblings."""

    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for record in records:
        for name, test in METRICS.items():
            counts[record["method"]][record["family_id"]][name] += int(bool(test(record)))
    return counts


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=5203)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    raw_bytes = RAW.read_bytes()
    records = [json.loads(line) for line in raw_bytes.decode("utf-8").splitlines() if line]
    counts = family_counts(records)
    families = sorted({record["family_id"] for record in records})
    rng = random.Random(args.seed)
    draws = [[rng.choice(families) for _ in families] for _ in range(args.resamples)]

    result: dict[str, object] = {
        "source_raw": str(RAW.relative_to(ROOT)),
        "source_raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "families": len(families),
        "resamples": args.resamples,
        "seed": args.seed,
        "interval": "95% percentile, family-clustered bootstrap (siblings resampled together)",
        "claim_scope": "descriptive uncertainty for 11 correlated synthetic families; not a significance test of method superiority",
        "methods": {},
    }
    for method in METHODS:
        per_family = counts[method]
        observed = {
            name: sum(per_family[f][name] for f in families) for name in METRICS
        }
        observed["stable_gain"] = observed["stable_correct_audit"] - observed["stable_correct_direct"]
        observed["harm_reduction"] = observed["harmful_direct"] - observed["harmful_audit"]
        samples: dict[str, list[float]] = {name: [] for name in observed}
        for draw in draws:
            totals = {name: sum(per_family[f][name] for f in draw) for name in METRICS}
            totals["stable_gain"] = totals["stable_correct_audit"] - totals["stable_correct_direct"]
            totals["harm_reduction"] = totals["harmful_direct"] - totals["harmful_audit"]
            for name, value in totals.items():
                samples[name].append(value)
        result["methods"][method] = {  # type: ignore[index]
            name: {
                "observed": observed[name],
                "ci95": [percentile(samples[name], 0.025), percentile(samples[name], 0.975)],
            }
            for name in observed
        }

    text = json.dumps(result, indent=2)
    print(text)
    if args.write:
        if OUTPUT.exists():
            raise SystemExit(f"refusing to overwrite {OUTPUT}")
        OUTPUT.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
