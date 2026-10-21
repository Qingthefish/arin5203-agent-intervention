"""Export the natural-language evidence set for review (zero model calls).

Writes a JSONL file with every context and a Markdown preview that shows the
full-evidence history of each family side by side with its gold evidence.

    python3 scripts/export_nl_evidence_set.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.natural_language_evidence import (  # noqa: E402
    LEAK_MARKERS,
    NL_EVIDENCE_VERSION,
    build_nl_contexts,
    context_record,
    oracle_decision,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "results"))
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    prefix = NL_EVIDENCE_VERSION.replace("-", "_")
    jsonl = out / f"{prefix}_dataset.jsonl"
    preview = out / f"{prefix}_dataset_preview.md"
    if jsonl.exists() or preview.exists():
        raise SystemExit("refusing to overwrite an existing dataset export")
    contexts = build_nl_contexts()
    records = [context_record(context) for context in contexts]
    jsonl.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    leaks = [c.case_id for c in contexts if any(m in c.active_context for m in LEAK_MARKERS)]
    mismatches = [c.case_id for c in contexts if oracle_decision(c) is not c.expected_decision]
    counts = Counter((c.split, c.variant, c.expected_decision.value) for c in contexts)

    lines = [
        f"# Natural-language evidence set ({NL_EVIDENCE_VERSION})",
        "",
        f"- Contexts: {len(contexts)} (20 families x 2 variants x 3 conditions)",
        f"- Typed-format leaks: {len(leaks)}",
        "- Matching: UTF-8 bytes, role and position; no token-budget equivalence claimed",
        "- Scope: templated rewrites of existing families, not new independent test data",
        "- Contexts where perfect extraction still disagrees with gold "
        f"(expected hidden-hold deletions): {len(mismatches)}",
        "",
        "| split | variant | expected route | contexts |",
        "|---|---|---|---|",
        *[f"| {s} | {v} | {d} | {n} |" for (s, v, d), n in sorted(counts.items())],
        "",
    ]
    for context in contexts:
        if context.condition != "full_evidence" or context.variant != "distractor":
            continue
        gold = {card.source_event_ids[0]: card.kind.value for card in context.visible_cards}
        lines += [
            f"## {context.family_id} ({context.split}, {context.domain}) — {context.title}",
            "",
            f"Expected route (full evidence): **{context.expected_decision.value}**; "
            f"critical evidence: `{context.critical_event_id}` ({context.critical_kind.value}); "
            f"matched noise: `{context.matched_noise_event_id}`; "
            f"distractor: `{context.distractor_event_id}`",
            "",
            f"Proposed action: `{context.proposed_action}`",
            "",
        ]
        for event in context.active_events:
            tag = ""
            if event.event_id in gold:
                tag = f" **[gold: {gold[event.event_id]}]**"
            elif event.event_id == context.distractor_event_id:
                tag = " **[distractor: not evidence]**"
            elif event.event_id == context.matched_noise_event_id:
                tag = " *[matched noise]*"
            if event.content.startswith("Operational observation"):
                continue
            lines.append(f"- `{event.event_id}` {event.role}{tag}: {event.content}")
        lines.append("")
    preview.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {jsonl} and {preview}")
    print(f"contexts={len(contexts)} leaks={len(leaks)} expected_mismatches={len(mismatches)}")


if __name__ == "__main__":
    main()
