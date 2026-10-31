#!/usr/bin/env python3
"""Print-friendly figures for the final report (zero model calls).

Reads only the frozen bootstrap summary derived from the one-shot held-out
trace and writes a vector PDF for the two-column CVPR template.

    python3 scripts/bootstrap_heldout_ci.py --write   # once
    python3 scripts/plot_report_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "results" / "heldout_bootstrap_ci_v1.json"
OUT_DIR = ROOT.parent / "03_最终报告" / "figures"

# Validated categorical slots 1-2 (light surface): blue = direct, orange = audit.
DIRECT, AUDIT = "#2a78d6", "#eb6834"
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
LABELS = {
    "full_context_ceiling": "Full history*",
    "recent_window": "Recent window",
    "neutral_summary": "Neutral summary",
    "task_aware_summary": "Task-aware summary",
    "generic_pinning": "Generic pinning",
    "ufold_lite": "U-Fold-lite",
    "typed_card_retention": "Typed proof",
}


def _panel(ax, data, direct_key, audit_key, total, title):
    methods = list(LABELS)
    height = 0.36
    for row, method in enumerate(methods):
        y = len(methods) - 1 - row
        for offset, key, color in ((height / 2 + 0.02, direct_key, DIRECT),
                                   (-height / 2 - 0.02, audit_key, AUDIT)):
            stat = data[method][key]
            value, (low, high) = stat["observed"], stat["ci95"]
            ax.barh(y + offset, value, height=height, color=color, linewidth=0)
            if high > low:
                ax.errorbar(value, y + offset, xerr=[[value - low], [high - value]],
                            fmt="none", ecolor=INK, elinewidth=0.7, capsize=1.6)
            ax.text(max(high, value) + total * 0.02, y + offset, f"{value}",
                    va="center", ha="left", fontsize=6.5, color=INK)
    ax.set_yticks(range(len(methods)))
    ax.set_yticklabels([LABELS[m] for m in reversed(methods)], fontsize=7, color=INK)
    ax.set_xlim(0, total * 1.12)
    ax.set_title(title, fontsize=7.5, color=INK, loc="center", pad=3)
    ax.tick_params(axis="x", labelsize=6.5, colors=MUTED, length=2)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.spines["bottom"].set_linewidth(0.6)


def main() -> None:
    data = json.loads(CI.read_text(encoding="utf-8"))["methods"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Serif"
    fig, axes = plt.subplots(2, 1, figsize=(3.3, 4.2), facecolor=SURFACE)
    _panel(axes[0], data, "stable_correct_direct", "stable_correct_audit", 22,
           "(a) Correct stable routes (of 22)")
    _panel(axes[1], data, "harmful_direct", "harmful_audit", 33,
           "(b) Harmful Executes, all contexts (of 33)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=DIRECT), plt.Rectangle((0, 0), 1, 1, color=AUDIT)]
    fig.legend(handles, ["Direct model route", "Deterministic proof audit"],
               loc="upper center", ncol=2, fontsize=6.8, frameon=False,
               bbox_to_anchor=(0.55, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.965), h_pad=1.0)
    out = OUT_DIR / "heldout_direct_vs_audit.pdf"
    fig.savefig(out, facecolor=SURFACE)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
