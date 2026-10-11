#!/usr/bin/env python3
"""Render presentation figures from the immutable one-shot held-out trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # Metric derivation and its tests remain stdlib-only.
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_RAW = ROOT / "results" / "typed_exact_budget_heldout_qwen_v1_raw.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "04_项目展示" / "figures"

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


def write_summary(metrics: dict[str, Any], raw_path: Path, output: Path) -> None:
    payload = {
        "source": str(raw_path.relative_to(PROJECT_ROOT)),
        "source_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "analysis": metrics,
        "claim_boundary": (
            "Derived presentation metrics only. They do not alter the immutable formal "
            "run and do not support production-safety or unique-superiority claims."
        ),
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    require_pillow()
    records = load_records(args.raw)
    metrics = compute_metrics(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    render_method_comparison(metrics, args.output_dir / "heldout-method-comparison.png")
    render_causal_boundary(metrics, args.output_dir / "heldout-causal-boundary.png")
    write_summary(metrics, args.raw, args.output_dir / "presentation-metrics.json")
    print(f"Wrote presentation evidence to {args.output_dir}")


if __name__ == "__main__":
    main()
