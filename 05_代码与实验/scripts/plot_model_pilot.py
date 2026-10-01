#!/usr/bin/env python3
"""Render the small local-model pilot as a publication-ready PNG."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "results" / "model_pilot_summary.csv"
DEFAULT_RAW = ROOT / "results" / "model_pilot_raw.jsonl"
DEFAULT_OUTPUT = ROOT / "results" / "model_pilot_overview.png"

POLICY_LABELS = {
    "prompt_binary_critic_r01": "Binary verify gate",
    "prompt_three_way_critic_r01": "Three-way gate",
}
DECISION_LABELS = {
    "AUTO_EXECUTE": "Execute",
    "REQUEST_CONFIRMATION": "Confirm",
    "HANDOFF": "Handoff",
    "BLOCK": "Hard block",
}
COLORS = {
    "AUTO_EXECUTE": "#3B82F6",
    "REQUEST_CONFIRMATION": "#F59E0B",
    "HANDOFF": "#8B5CF6",
    "BLOCK": "#64748B",
}


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold
        else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Helvetica.ttc"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, *,
         size: int = 28, fill: str = "#0F172A", bold: bool = False,
         anchor: str | None = None) -> None:
    draw.text(xy, value, font=load_font(size, bold), fill=fill, anchor=anchor)


def load_inputs(summary_path: Path, raw_path: Path):
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        summaries = {
            row["policy"]: row
            for row in rows
            if not row.get("split") or row["split"] == "all"
        }
    records = []
    with raw_path.open(encoding="utf-8") as handle:
        for line in handle:
            records.append(json.loads(line))
    return summaries, records


def render(summary_path: Path, raw_path: Path, output_path: Path) -> None:
    summaries, records = load_inputs(summary_path, raw_path)
    policies = [name for name in POLICY_LABELS if name in summaries]
    if len(policies) != 2:
        raise ValueError(f"Expected the two pilot policies, found {policies}")

    decision_counts: dict[str, Counter[str]] = defaultdict(Counter)
    unsafe_executes = Counter()
    for row in records:
        decision_counts[row["policy"]][row["decision"]] += 1
        if row["unsafe_mutation"]:
            unsafe_executes[row["policy"]] += 1

    scenario_counts = {policy: sum(decision_counts[policy].values()) for policy in policies}
    if len(set(scenario_counts.values())) != 1:
        raise ValueError(f"Policies cover different scenario counts: {scenario_counts}")
    scenario_count = next(iter(scenario_counts.values()))
    base_task_count = len({row["base_task_id"] for row in records})
    guarded_count = sum(
        row["decision_source"] == "hard_guard"
        for row in records
        if row["policy"] == policies[0]
    )
    safe_completion_count = {
        policy: sum(
            row["safe_autonomous_completion"]
            for row in records
            if row["policy"] == policy
        )
        for policy in policies
    }

    image = Image.new("RGB", (1800, 1000), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    text(
        draw,
        (80, 58),
        f"Local {base_task_count}-task pilot: intervention outcomes",
        size=46,
        bold=True,
    )
    text(
        draw,
        (80, 116),
        f"Qwen3.5-9B on {scenario_count} matched cases; one deterministic repeat; descriptive evidence only",
        size=25,
        fill="#475569",
    )

    # Panel A: decision distributions.
    left = (70, 180, 1015, 850)
    draw.rounded_rectangle(left, radius=24, fill="white", outline="#E2E8F0", width=3)
    text(draw, (115, 225), "A. Routing outcomes", size=32, bold=True)
    text(
        draw,
        (115, 270),
        f"Counts out of {scenario_count} cases",
        size=22,
        fill="#64748B",
    )

    x0, x1 = 180, 950
    bar_width = x1 - x0
    y_positions = [400, 595]
    order = ["AUTO_EXECUTE", "REQUEST_CONFIRMATION", "HANDOFF", "BLOCK"]
    for policy, y in zip(policies, y_positions):
        text(draw, (115, y - 58), POLICY_LABELS[policy], size=27, bold=True)
        cursor = x0
        for decision in order:
            count = decision_counts[policy][decision]
            if not count:
                continue
            width = round(bar_width * count / scenario_count)
            draw.rectangle((cursor, y, cursor + width, y + 74), fill=COLORS[decision])
            if width > 58:
                text(draw, (cursor + width // 2, y + 37), str(count), size=25,
                     fill="white", bold=True, anchor="mm")
            cursor += width
        unsafe = unsafe_executes[policy]
        unsafe_label = f"unsafe executions: {unsafe}"
        text(draw, (x1, y + 91), unsafe_label, size=22,
             fill="#B91C1C" if unsafe else "#15803D", anchor="ra")

    legend_x, legend_y = 120, 760
    for decision in order:
        draw.rounded_rectangle(
            (legend_x, legend_y, legend_x + 26, legend_y + 26),
            radius=5,
            fill=COLORS[decision],
        )
        text(draw, (legend_x + 38, legend_y + 13), DECISION_LABELS[decision],
             size=20, anchor="lm")
        legend_x += 190

    # Panel B: safety-autonomy trade-off.
    right = (1050, 180, 1730, 850)
    draw.rounded_rectangle(right, radius=24, fill="white", outline="#E2E8F0", width=3)
    text(draw, (1095, 225), "B. Safety-autonomy trade-off", size=32, bold=True)
    safe_values = set(safe_completion_count.values())
    if len(safe_values) == 1:
        safe_text = f"Both policies safely auto-completed {next(iter(safe_values))}/{scenario_count} cases"
    else:
        safe_text = "Safe autonomous completions are shown in the labels below"
    text(draw, (1095, 270), safe_text, size=22, fill="#64748B")

    plot_left, plot_top, plot_right, plot_bottom = 1150, 380, 1660, 700
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill="#94A3B8", width=3)
    draw.line((plot_left, plot_bottom, plot_left, plot_top), fill="#94A3B8", width=3)
    for pct in [0, 20, 40, 60, 80, 100]:
        x = plot_left + (plot_right - plot_left) * pct / 100
        draw.line((x, plot_bottom, x, plot_bottom + 10), fill="#94A3B8", width=2)
        text(draw, (round(x), plot_bottom + 22), str(pct), size=18,
             fill="#64748B", anchor="ma")
    max_unsafe = max(
        float(summaries[policy]["overall_unsafe_action_rate"]) * 100
        for policy in policies
    )
    y_axis_max = max(10, int((max_unsafe + 4.999) // 5) * 5)
    y_ticks = [round(y_axis_max * i / 5) for i in range(6)]
    for pct in y_ticks:
        y = plot_bottom - (plot_bottom - plot_top) * pct / y_axis_max
        draw.line((plot_left - 10, y, plot_left, y), fill="#94A3B8", width=2)
        text(draw, (plot_left - 18, round(y)), str(pct), size=18,
             fill="#64748B", anchor="rm")
    text(draw, ((plot_left + plot_right) // 2, 778), "Autonomous coverage (%)",
         size=22, anchor="ma")
    text(draw, (1095, 330), "Unsafe action rate (%)", size=22)

    point_colors = ["#2563EB", "#7C3AED"]
    for policy, color in zip(policies, point_colors):
        row = summaries[policy]
        coverage = float(row["autonomous_coverage"]) * 100
        unsafe_rate = float(row["overall_unsafe_action_rate"]) * 100
        x = plot_left + (plot_right - plot_left) * coverage / 100
        y = plot_bottom - (plot_bottom - plot_top) * unsafe_rate / y_axis_max
        radius = 31
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=color, outline="white", width=5)
        if unsafe_rate > 0:
            label_x, label_y, anchor = x + radius + 12, y - 12, "lm"
        else:
            label_x, label_y, anchor = x + radius + 12, y - 52, "lm"
        text(draw, (round(label_x), round(label_y)), POLICY_LABELS[policy], size=20,
             bold=True, fill=color, anchor=anchor)
        text(draw, (round(label_x), round(label_y + 28)),
             f"coverage {coverage:.1f}%; unsafe {unsafe_rate:.1f}%", size=18,
             fill="#475569", anchor=anchor)

    prevented = unsafe_executes[policies[0]] - unsafe_executes[policies[1]]
    text(draw, (1405, 752), f"Three-way prevented {prevented} unsafe auto-executions",
         size=19, fill="#15803D", bold=True, anchor="ma")

    text(
        draw,
        (80, 925),
        f"Hard guards blocked {guarded_count} cases per policy. One correlated run is insufficient for significance or calibration claims.",
        size=21,
        fill="#475569",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, dpi=(200, 200), optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.summary, args.raw, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
