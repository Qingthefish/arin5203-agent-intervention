#!/usr/bin/env python3
"""Render presentation figures from the immutable one-shot held-out trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # Metric derivation and its tests remain stdlib-only.
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"
DEFAULT_DEV_RAW = ROOT / "results" / "typed_exact_budget_dev_qwen_v6_raw.jsonl"
DEFAULT_INDEX = ROOT / "results" / "index.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "04_项目展示" / "figures"

TURNING_POINTS = (
    ("compaction_pilot_qwen_v1", "Feasibility pilot"),
    ("grounded_hitl_qwen_v4", "Grounding gate"),
    ("fixed_budget_dev_qwen_v1", "Fixed-budget pipeline"),
    ("audit_increment_qwen_v2", "Prompt audit test"),
    ("blind_proof_qwen_v1", "Blind verifier"),
    ("typed_exact_budget_dev_qwen_v6", "Development freeze"),
    ("typed_exact_budget_heldout_qwen_v1", "One-shot held-out"),
)

METHOD_ORDER = (
    "full_context_ceiling",
    "recent_window",
    "neutral_summary",
    "task_aware_summary",
    "generic_pinning",
    "ufold_lite",
    "typed_card_retention",
)
METHOD_LABELS = {
    "full_context_ceiling": "Full context*",
    "recent_window": "Recent window",
    "neutral_summary": "Neutral summary",
    "task_aware_summary": "Task-aware",
    "generic_pinning": "Generic pinning",
    "ufold_lite": "U-Fold-lite",
    "typed_card_retention": "Typed proof",
}

COLORS = {
    "background": "#0D0F10",
    "panel": "#171A1C",
    "panel_alt": "#1D2123",
    "text": "#F4F1E9",
    "muted": "#9FA39F",
    "line": "#343A3C",
    "lime": "#C9F769",
    "cyan": "#77E6E0",
    "amber": "#FFCA67",
    "red": "#FF7B72",
}


def require_pillow() -> None:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError(
            "Pillow is required only for rendering. Install "
            "requirements-presentation.txt and rerun this script."
        )


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold
        else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/SFNS.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def put_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    size: int = 26,
    fill: str | None = None,
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(
        xy,
        value,
        font=load_font(size, bold),
        fill=fill or COLORS["text"],
        anchor=anchor,
    )


def wrap_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    size: int,
    max_width: int,
    bold: bool = False,
) -> list[str]:
    """Wrap text by rendered pixel width so slide labels never cross panels."""
    font = load_font(size, bold)
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def put_wrapped_center(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    top_y: int,
    value: str,
    *,
    size: int,
    max_width: int,
    fill: str,
    line_gap: int = 6,
) -> None:
    lines = wrap_text(draw, value, size=size, max_width=max_width)
    line_height = size + line_gap
    for index, line in enumerate(lines):
        put_text(
            draw,
            (center_x, top_y + index * line_height),
            line,
            size=size,
            fill=fill,
            anchor="ma",
        )


def load_records(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(records) != 231:
        raise ValueError(f"expected 231 frozen held-out records, found {len(records)}")
    return records


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_index(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "experiment-artifact-index-v1":
        raise ValueError("unexpected experiment index schema")
    return payload


def compute_experiment_scale(index: dict[str, Any]) -> dict[str, Any]:
    by_prefix = {str(run["prefix"]): run for run in index["runs"]}
    points: list[dict[str, Any]] = []
    for prefix, label in TURNING_POINTS:
        run = by_prefix[prefix]
        started = datetime.fromisoformat(str(run["started_at"]))
        finished = datetime.fromisoformat(str(run["finished_at"]))
        points.append(
            {
                "prefix": prefix,
                "label": label,
                "calls": int(run["measured_generation_calls"]),
                "minutes": (finished - started).total_seconds() / 60.0,
                "prompt_tokens": int(run["prompt_tokens"]),
                "completion_tokens": int(run["completion_tokens"]),
                "audit_status": str(run["audit_status"]),
            }
        )

    calls = [run.get("measured_generation_calls") for run in index["runs"]]
    prompt_tokens = [run.get("prompt_tokens") for run in index["runs"]]
    completion_tokens = [run.get("completion_tokens") for run in index["runs"]]
    costs = [run.get("external_api_cost_usd") for run in index["runs"]]
    return {
        "turning_points": points,
        "recorded_runs": int(index["totals"]["runs"]),
        "runs_with_call_counts": sum(value is not None for value in calls),
        "measured_calls": sum(int(value or 0) for value in calls),
        "recorded_tokens": sum(int(value or 0) for value in prompt_tokens)
        + sum(int(value or 0) for value in completion_tokens),
        "external_api_cost_usd": sum(float(value or 0.0) for value in costs),
        "failed_or_aborted": int(index["totals"]["evidence_tiers"]["FAILED_OR_ABORTED"]),
        "frozen_gate_bundles": int(index["totals"]["evidence_tiers"]["FROZEN_GATE_BUNDLE"]),
    }


def compute_benchmark_design(
    dev_records: list[dict[str, Any]], heldout_records: list[dict[str, Any]]
) -> dict[str, Any]:
    dev_cases = {str(row["case_id"]) for row in dev_records}
    heldout_cases = {str(row["case_id"]) for row in heldout_records}
    dev_families = {str(row["family_id"]) for row in dev_records}
    heldout_families = {str(row["family_id"]) for row in heldout_records}
    methods = {str(row["method"]) for row in heldout_records}

    family_rows: dict[str, dict[str, Any]] = {}
    for row in [*dev_records, *heldout_records]:
        family_rows.setdefault(str(row["family_id"]), row)
    domain_bases: dict[str, int] = defaultdict(int)
    for row in family_rows.values():
        domain_bases[str(row["domain"])] += 1

    heldout_full: dict[str, dict[str, Any]] = {}
    for row in heldout_records:
        if row["condition"] == "full_evidence":
            heldout_full.setdefault(str(row["family_id"]), row)
    route_mix: dict[str, int] = defaultdict(int)
    for row in heldout_full.values():
        route_mix[str(row["expected_decision"])] += 1

    return {
        "development_bases": len(dev_families),
        "development_cases": len(dev_cases),
        "heldout_bases": len(heldout_families),
        "heldout_cases": len(heldout_cases),
        "total_bases": len(dev_families) + len(heldout_families),
        "total_cases": len(dev_cases) + len(heldout_cases),
        "methods": len(methods),
        "budget_tokens": 384,
        "domain_bases": dict(domain_bases),
        "heldout_route_mix": dict(route_mix),
    }


def compute_case_story(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = {
        str(row["condition"]): row
        for row in records
        if row["family_id"] == "held-y6" and row["method"] == "typed_card_retention"
    }
    if set(rows) != {"full_evidence", "remove_action_critical", "remove_matched_noise"}:
        raise ValueError("held-y6 typed sibling triplet is incomplete")
    return {
        "family_id": "held-y6",
        "request": "Purchase Juniper's non-refundable hotel stay for HKD 7,480.",
        "conditions": [
            {
                "condition": condition,
                "critical_visible": bool(row["critical_event_visible_before_compaction"]),
                "critical_retained": bool(row["critical_event_retained"]),
                "decision": str(row["audited"]["decision"]),
                "route_correct": bool(row["audited"]["route_correct"]),
                "harmful_execution": bool(row["audited"]["harmful_execution"]),
                "removed_event_ids": list(row["removed_event_ids"]),
            }
            for condition, row in (
                ("full_evidence", rows["full_evidence"]),
                ("remove_action_critical", rows["remove_action_critical"]),
                ("remove_matched_noise", rows["remove_matched_noise"]),
            )
        ],
    }


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["method"])].append(record)
    if set(grouped) != set(METHOD_ORDER):
        raise ValueError("held-out method set no longer matches the frozen comparison")

    method_metrics: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        rows = grouped[method]
        stable = [row for row in rows if row["condition"] != "remove_action_critical"]
        method_metrics.append(
            {
                "method": method,
                "label": METHOD_LABELS[method],
                "stable_cases": len(stable),
                "direct_stable_correct": sum(bool(row["direct"]["route_correct"]) for row in stable),
                "audited_stable_correct": sum(bool(row["audited"]["route_correct"]) for row in stable),
                "direct_stable_harm": sum(bool(row["direct"]["harmful_execution"]) for row in stable),
                "audited_stable_harm": sum(bool(row["audited"]["harmful_execution"]) for row in stable),
                "visible_card_recall": sum(float(row["visible_card_recall"]) for row in rows) / len(rows),
                "proof_citation_precision": sum(float(row["direct"]["proof_citation_precision"]) for row in rows) / len(rows),
            }
        )

    typed = grouped["typed_card_retention"]
    typed_stable = [row for row in typed if row["condition"] != "remove_action_critical"]
    typed_deletions = [row for row in typed if row["condition"] == "remove_action_critical"]
    non_hold = [row for row in typed_deletions if row["critical_kind"] != "ACTIVE_HOLD"]
    hidden_hold = [row for row in typed_deletions if row["critical_kind"] == "ACTIVE_HOLD"]
    boundary = {
        "stable_cases": len(typed_stable),
        "stable_direct_correct": sum(bool(row["direct"]["route_correct"]) for row in typed_stable),
        "stable_audited_correct": sum(bool(row["audited"]["route_correct"]) for row in typed_stable),
        "stable_direct_harm": sum(bool(row["direct"]["harmful_execution"]) for row in typed_stable),
        "stable_audited_harm": sum(bool(row["audited"]["harmful_execution"]) for row in typed_stable),
        "audit_helpful": sum(bool(row["audit_helpful"]) for row in typed),
        "audit_harmful": sum(bool(row["audit_harmful"]) for row in typed),
        "non_hold_deletions": len(non_hold),
        "non_hold_fail_closed": sum(bool(row["audited"]["route_correct"]) for row in non_hold),
        "hidden_hold_deletions": len(hidden_hold),
        "hidden_hold_harmful_executes": sum(bool(row["audited"]["harmful_execution"]) for row in hidden_hold),
    }
    return {"method_metrics": method_metrics, "typed_boundary": boundary}


def _canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1800, 1000), COLORS["background"])
    draw = ImageDraw.Draw(image)
    put_text(draw, (76, 54), title, size=45, bold=True)
    put_text(draw, (76, 111), subtitle, size=23, fill=COLORS["muted"])
    return image, draw


def render_method_comparison(metrics: dict[str, Any], output: Path) -> None:
    image, draw = _canvas(
        "Held-out result: routing ties, proof quality separates",
        "11 untouched bases / 33 matched contexts / 384 raw-token budget / local Qwen3.5-9B",
    )
    left = (70, 180, 890, 870)
    right = (920, 180, 1730, 870)
    for box in (left, right):
        draw.rounded_rectangle(box, radius=22, fill=COLORS["panel"])

    put_text(draw, (110, 220), "A. Stable route accuracy", size=30, bold=True)
    put_text(draw, (110, 262), "Full history + matched-noise siblings (n=22 per method)", size=19, fill=COLORS["muted"])
    put_text(draw, (960, 220), "B. Evidence-chain quality", size=30, bold=True)
    put_text(draw, (960, 262), "Mean across all 33 contexts", size=19, fill=COLORS["muted"])

    rows = metrics["method_metrics"]
    y0, row_gap = 340, 68
    bar_x, bar_w = 330, 500
    proof_x, proof_w = 1180, 480
    for index, row in enumerate(rows):
        y = y0 + index * row_gap
        label_fill = COLORS["text"] if row["method"] != "full_context_ceiling" else COLORS["muted"]
        put_text(draw, (110, y + 12), row["label"], size=19, fill=label_fill, anchor="lm")
        direct = row["direct_stable_correct"] / row["stable_cases"]
        audited = row["audited_stable_correct"] / row["stable_cases"]
        draw.rounded_rectangle((bar_x, y, bar_x + bar_w, y + 16), radius=8, fill=COLORS["line"])
        draw.rounded_rectangle((bar_x, y, bar_x + round(bar_w * direct), y + 16), radius=8, fill=COLORS["cyan"])
        draw.rounded_rectangle((bar_x, y + 24, bar_x + bar_w, y + 40), radius=8, fill=COLORS["line"])
        draw.rounded_rectangle((bar_x, y + 24, bar_x + round(bar_w * audited), y + 40), radius=8, fill=COLORS["lime"])
        put_text(draw, (bar_x + bar_w + 12, y + 8), f"{row['direct_stable_correct']}/22", size=16, fill=COLORS["cyan"], anchor="lm")
        put_text(draw, (bar_x + bar_w + 12, y + 32), f"{row['audited_stable_correct']}/22", size=16, fill=COLORS["lime"], anchor="lm")

        put_text(draw, (960, y + 12), row["label"], size=19, fill=label_fill, anchor="lm")
        recall = row["visible_card_recall"]
        precision = row["proof_citation_precision"]
        draw.rounded_rectangle((proof_x, y, proof_x + proof_w, y + 16), radius=8, fill=COLORS["line"])
        draw.rounded_rectangle((proof_x, y, proof_x + round(proof_w * recall), y + 16), radius=8, fill=COLORS["amber"])
        draw.rounded_rectangle((proof_x, y + 24, proof_x + proof_w, y + 40), radius=8, fill=COLORS["line"])
        draw.rounded_rectangle((proof_x, y + 24, proof_x + round(proof_w * precision), y + 40), radius=8, fill=COLORS["cyan"])
        put_text(draw, (proof_x + proof_w + 12, y + 8), f"{recall * 100:.0f}%", size=16, fill=COLORS["amber"], anchor="lm")
        put_text(draw, (proof_x + proof_w + 12, y + 32), f"{precision * 100:.1f}%", size=16, fill=COLORS["cyan"], anchor="lm")

    put_text(draw, (330, 818), "Direct route", size=17, fill=COLORS["cyan"])
    put_text(draw, (500, 818), "Audited route", size=17, fill=COLORS["lime"])
    put_text(draw, (1180, 818), "Visible-card recall", size=17, fill=COLORS["amber"])
    put_text(draw, (1410, 818), "Citation precision", size=17, fill=COLORS["cyan"])
    put_text(draw, (76, 925), "* Full context is an unbudgeted ceiling, not a budget-matched competitor. Strong summaries tie on audited routing; typed proof is the only method at 100% on both retention and citation grounding.", size=18, fill=COLORS["muted"])
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(200, 200), optimize=True)


def _flow_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    metric: str,
    detail: str,
    accent: str,
) -> None:
    draw.rounded_rectangle(box, radius=24, fill=COLORS["panel"], outline=accent, width=3)
    x0, y0, x1, _ = box
    put_text(draw, (x0 + 28, y0 + 30), title, size=24, bold=True)
    put_text(draw, ((x0 + x1) // 2, y0 + 122), metric, size=46, fill=accent, bold=True, anchor="mm")
    put_wrapped_center(
        draw,
        (x0 + x1) // 2,
        y0 + 166,
        detail,
        size=18,
        max_width=(x1 - x0) - 56,
        fill=COLORS["muted"],
    )


def render_causal_boundary(metrics: dict[str, Any], output: Path) -> None:
    boundary = metrics["typed_boundary"]
    image, draw = _canvas(
        "What evidence audit can fix - and what it cannot",
        "Typed proof memory on the frozen held-out set",
    )
    boxes = [
        (70, 250, 540, 535),
        (665, 250, 1135, 535),
        (1260, 250, 1730, 535),
    ]
    _flow_box(
        draw,
        boxes[0],
        "Evidence remains visible",
        f"{boundary['stable_audited_correct']}/{boundary['stable_cases']}",
        f"Direct {boundary['stable_direct_correct']}/{boundary['stable_cases']} → audit {boundary['stable_audited_correct']}/{boundary['stable_cases']}; harm {boundary['stable_direct_harm']} → {boundary['stable_audited_harm']}",
        COLORS["lime"],
    )
    _flow_box(
        draw,
        boxes[1],
        "Repairable proof is missing",
        f"{boundary['non_hold_fail_closed']}/{boundary['non_hold_deletions']}",
        "Authority / clearance / delegation / recovery gaps fail closed",
        COLORS["amber"],
    )
    _flow_box(
        draw,
        boxes[2],
        "A hidden hold never arrives",
        f"{boundary['hidden_hold_harmful_executes']}/{boundary['hidden_hold_deletions']}",
        "Harmful Execute: no compactor can retain unseen evidence",
        COLORS["red"],
    )
    for x in (590, 1185):
        draw.line((x - 22, 392, x + 22, 392), fill=COLORS["muted"], width=4)
        draw.polygon(((x + 22, 392), (x + 8, 382), (x + 8, 402)), fill=COLORS["muted"])

    draw.rounded_rectangle((170, 650, 1630, 825), radius=24, fill=COLORS["panel_alt"])
    put_text(draw, (210, 690), "Developer rule", size=22, fill=COLORS["cyan"], bold=True)
    put_text(draw, (210, 738), "Compaction may summarize conversation, but state-changing tools need a separate proof path.", size=30, bold=True)
    put_text(draw, (210, 786), "Preserve typed evidence at origin, validate it after compaction, and monitor upstream evidence loss independently.", size=22, fill=COLORS["muted"])
    put_text(draw, (76, 925), f"Across all 33 typed contexts, audit made {boundary['audit_helpful']} helpful corrections and 0 harmful changes. The three hidden-hold failures are retained as the system boundary, not removed as outliers.", size=18, fill=COLORS["muted"])
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(200, 200), optimize=True)


def render_experiment_scale(scale: dict[str, Any], output: Path) -> None:
    image, draw = _canvas(
        "What it took to reach one frozen held-out result",
        "Selected turning points from the machine-indexed local experiment history",
    )
    chart = (70, 180, 1270, 870)
    summary = (1310, 180, 1730, 870)
    draw.rounded_rectangle(chart, radius=22, fill=COLORS["panel"])
    draw.rounded_rectangle(summary, radius=22, fill=COLORS["panel_alt"])

    points = scale["turning_points"]
    max_minutes = max(float(row["minutes"]) for row in points)
    label_x, bar_x, bar_w = 105, 410, 660
    y0, gap = 245, 82
    put_text(draw, (105, 207), "Measured wall time by turning point", size=25, bold=True)
    for index, row in enumerate(points):
        y = y0 + index * gap
        put_text(draw, (label_x, y + 16), row["label"], size=19, anchor="lm")
        draw.rounded_rectangle((bar_x, y, bar_x + bar_w, y + 24), radius=12, fill=COLORS["line"])
        width = max(6, round(bar_w * float(row["minutes"]) / max_minutes))
        accent = COLORS["lime"] if str(row["audit_status"]).startswith("PASS") else COLORS["amber"]
        draw.rounded_rectangle((bar_x, y, bar_x + width, y + 24), radius=12, fill=accent)
        put_text(
            draw,
            (bar_x + bar_w + 18, y + 12),
            f"{row['calls']} calls  ·  {row['minutes']:.1f} min",
            size=17,
            fill=COLORS["text"],
            anchor="lm",
        )

    put_text(draw, (1350, 224), "Recorded evidence", size=25, bold=True)
    aggregates = [
        (f"{scale['recorded_runs']}", "run manifests"),
        (f"{scale['measured_calls']:,}", "measured local calls"),
        (f"{scale['recorded_tokens'] / 1_000_000:.2f}M", "recorded model tokens"),
        (f"{scale['frozen_gate_bundles']}", "frozen gate bundles"),
        (f"{scale['failed_or_aborted']}", "failed or aborted runs kept"),
        (f"${scale['external_api_cost_usd']:.0f}", "external API cost"),
    ]
    for index, (value, label) in enumerate(aggregates):
        y = 292 + index * 88
        put_text(draw, (1350, y), value, size=36, bold=True, fill=COLORS["cyan"])
        put_text(draw, (1350, y + 42), label, size=18, fill=COLORS["muted"])

    put_text(
        draw,
        (76, 928),
        "Selected stages show measured elapsed time, not estimates. Aggregate totals sum numeric fields in results/index.json; incomplete legacy metadata is not imputed.",
        size=18,
        fill=COLORS["muted"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(200, 200), optimize=True)


def render_benchmark_design(design: dict[str, Any], output: Path) -> None:
    image, draw = _canvas(
        "Benchmark design: 20 bases become 60 matched cases",
        "The same action is tested with complete evidence, one critical deletion, and equal-length noise deletion",
    )

    stages = [
        (120, "20", "base scenarios", COLORS["cyan"]),
        (470, "×3", "matched siblings", COLORS["amber"]),
        (820, "60", "decision contexts", COLORS["lime"]),
        (1170, "7", "memory strategies", COLORS["cyan"]),
        (1520, "3", "routes + state oracle", COLORS["lime"]),
    ]
    for index, (x, metric, label, accent) in enumerate(stages):
        draw.ellipse((x - 68, 225, x + 68, 361), fill=COLORS["panel_alt"], outline=accent, width=4)
        put_text(draw, (x, 280), metric, size=41, bold=True, fill=accent, anchor="mm")
        put_wrapped_center(draw, x, 380, label, size=20, max_width=230, fill=COLORS["text"])
        if index < len(stages) - 1:
            next_x = stages[index + 1][0]
            draw.line((x + 86, 293, next_x - 86, 293), fill=COLORS["muted"], width=4)
            draw.polygon(
                ((next_x - 86, 293), (next_x - 102, 282), (next_x - 102, 304)),
                fill=COLORS["muted"],
            )

    draw.rounded_rectangle((70, 510, 1110, 840), radius=24, fill=COLORS["panel"])
    put_text(draw, (110, 550), "Matched sibling test", size=28, bold=True)
    sibling_rows = [
        ("Complete evidence", "critical proof + matched noise", COLORS["lime"]),
        ("Critical deletion", "critical proof removed; noise remains", COLORS["red"]),
        ("Noise deletion", "equal-length noise removed; proof remains", COLORS["cyan"]),
    ]
    for index, (label, detail, accent) in enumerate(sibling_rows):
        y = 620 + index * 72
        draw.rounded_rectangle((112, y, 314, y + 42), radius=10, fill=accent)
        put_text(draw, (213, y + 21), label, size=17, bold=True, fill=COLORS["background"], anchor="mm")
        put_text(draw, (344, y + 21), detail, size=19, fill=COLORS["text"], anchor="lm")

    draw.rounded_rectangle((1150, 510, 1730, 840), radius=24, fill=COLORS["panel_alt"])
    put_text(draw, (1190, 550), "Frozen split", size=28, bold=True)
    split_lines = [
        (f"{design['development_bases']} bases / {design['development_cases']} cases", "development"),
        (f"{design['heldout_bases']} bases / {design['heldout_cases']} cases", "one-shot held-out"),
        ("7 / 7 / 6 bases", "platform / financial / travel"),
        (f"{design['budget_tokens']} raw tokens", "per compacted context"),
        ("5 / 3 / 3", "held-out route mix"),
    ]
    for index, (value, label) in enumerate(split_lines):
        y = 613 + index * 48
        put_text(draw, (1190, y), value, size=22, bold=True, fill=COLORS["cyan"])
        put_text(draw, (1505, y), label, size=17, fill=COLORS["muted"])

    put_text(
        draw,
        (76, 928),
        "Siblings never cross splits. Neutral IDs, matched event role/position/length, and blinded strategy labels reduce shortcut cues.",
        size=18,
        fill=COLORS["muted"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(200, 200), optimize=True)


def render_case_story(story: dict[str, Any], output: Path) -> None:
    image, draw = _canvas(
        "One deleted fact changes the hotel booking",
        story["request"],
    )
    columns = [
        (70, 210, 540, 800),
        (665, 210, 1135, 800),
        (1260, 210, 1730, 800),
    ]
    labels = {
        "full_evidence": ("Complete history", "Policy hold visible", COLORS["lime"]),
        "remove_action_critical": ("Critical proof removed", "Policy hold never arrives", COLORS["red"]),
        "remove_matched_noise": ("Equal-size noise removed", "Policy hold still visible", COLORS["cyan"]),
    }
    for box, row in zip(columns, story["conditions"]):
        x0, y0, x1, y1 = box
        title, evidence, accent = labels[row["condition"]]
        draw.rounded_rectangle(box, radius=24, fill=COLORS["panel"], outline=accent, width=3)
        put_text(draw, (x0 + 28, y0 + 34), title, size=24, bold=True)
        put_text(draw, (x0 + 28, y0 + 82), evidence, size=19, fill=accent)

        # A compact visual trace: request, authority, hold, recovery, noise.
        trace_y = y0 + 145
        trace = [
            ("request", COLORS["muted"]),
            ("authority", COLORS["amber"]),
            ("policy hold", COLORS["red"]),
            ("recovery", COLORS["cyan"]),
            ("noise", COLORS["line"]),
        ]
        for index, (name, color) in enumerate(trace):
            y = trace_y + index * 42
            missing = (
                row["condition"] == "remove_action_critical" and name == "policy hold"
            ) or (row["condition"] == "remove_matched_noise" and name == "noise")
            if missing:
                draw.rounded_rectangle((x0 + 30, y, x1 - 30, y + 24), radius=10, outline=accent, width=2)
                put_text(draw, ((x0 + x1) // 2, y + 12), f"{name} removed", size=15, fill=accent, anchor="mm")
            else:
                draw.rounded_rectangle((x0 + 30, y, x1 - 30, y + 24), radius=10, fill=color)
                put_text(draw, ((x0 + x1) // 2, y + 12), name, size=15, fill=COLORS["background"] if color != COLORS["line"] else COLORS["muted"], anchor="mm")

        route = "Execute" if row["decision"] == "AUTO_EXECUTE" else "Handoff"
        route_color = COLORS["red"] if row["harmful_execution"] else COLORS["lime"]
        put_text(draw, ((x0 + x1) // 2, y0 + 407), route, size=42, bold=True, fill=route_color, anchor="mm")
        state = "draft → purchased\nHKD 0 → 7,480" if row["harmful_execution"] else "booking remains draft\ncharge remains HKD 0"
        for index, line in enumerate(state.splitlines()):
            put_text(draw, ((x0 + x1) // 2, y0 + 472 + index * 30), line, size=20, fill=COLORS["text"], anchor="mm")
        if row["harmful_execution"]:
            put_text(draw, ((x0 + x1) // 2, y0 + 555), "HARMFUL STATE CHANGE", size=18, bold=True, fill=COLORS["red"], anchor="mm")
        else:
            put_text(draw, ((x0 + x1) // 2, y0 + 555), "STATE UNCHANGED", size=18, bold=True, fill=COLORS["lime"], anchor="mm")

    draw.rounded_rectangle((260, 850, 1540, 916), radius=20, fill=COLORS["panel_alt"])
    put_text(
        draw,
        (900, 883),
        "Removing equal-size noise changes nothing. Removing one active hold flips the action and the external state.",
        size=23,
        bold=True,
        anchor="mm",
    )
    put_text(draw, (76, 957), "Frozen case held-y6 · typed proof memory · 384-token budget", size=16, fill=COLORS["muted"])
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(200, 200), optimize=True)


def write_summary(
    metrics: dict[str, Any],
    experiment_scale: dict[str, Any],
    benchmark_design: dict[str, Any],
    case_story: dict[str, Any],
    raw_path: Path,
    dev_raw_path: Path,
    index_path: Path,
    output: Path,
) -> None:
    payload = {
        "sources": {
            "heldout_raw": {
                "path": str(raw_path.relative_to(PROJECT_ROOT)),
                "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            },
            "development_raw": {
                "path": str(dev_raw_path.relative_to(PROJECT_ROOT)),
                "sha256": hashlib.sha256(dev_raw_path.read_bytes()).hexdigest(),
            },
            "experiment_index": {
                "path": str(index_path.relative_to(PROJECT_ROOT)),
                "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            },
        },
        "analysis": metrics,
        "experiment_scale": experiment_scale,
        "benchmark_design": benchmark_design,
        "case_story": case_story,
        "claim_boundary": (
            "Derived presentation metrics only. They do not alter the immutable formal "
            "run and do not support production-safety or unique-superiority claims."
        ),
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--dev-raw", type=Path, default=DEFAULT_DEV_RAW)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    require_pillow()
    records = load_records(args.raw)
    dev_records = load_jsonl(args.dev_raw)
    index = load_index(args.index)
    metrics = compute_metrics(records)
    experiment_scale = compute_experiment_scale(index)
    benchmark_design = compute_benchmark_design(dev_records, records)
    case_story = compute_case_story(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    render_method_comparison(metrics, args.output_dir / "heldout-method-comparison.png")
    render_causal_boundary(metrics, args.output_dir / "heldout-causal-boundary.png")
    render_experiment_scale(experiment_scale, args.output_dir / "experiment-scale.png")
    render_benchmark_design(benchmark_design, args.output_dir / "benchmark-design.png")
    render_case_story(case_story, args.output_dir / "matched-case-held-y6.png")
    write_summary(
        metrics,
        experiment_scale,
        benchmark_design,
        case_story,
        args.raw,
        args.dev_raw,
        args.index,
        args.output_dir / "presentation-metrics.json",
    )
    print(f"Wrote presentation evidence to {args.output_dir}")


if __name__ == "__main__":
    main()
