# Presentation Evidence Pack

This directory turns the frozen held-out experiment into a presentation that is useful to Agent developers. It does not add a new model run or reinterpret the test set.

## One-sentence story

Building an Agent from 0 to 1 is increasingly easy; keeping it reliable from 1 to 100 is harder because context compaction can silently change the evidence available before a tool changes external state.

## Recommended nine-slide arc

| Slide | Purpose | Evidence or visual |
| --- | --- | --- |
| 1. Hook | Move from “how to build an Agent” to “how to keep one reliable” | 0→1 versus 1→100 framing |
| 2. One familiar failure | Show that forgetting is an action problem, not only a conversation problem | Travel Agent loses a payment/delegation/hold fact, then changes a booking |
| 3. Research question | Define the exact decision | Under the same raw-token budget, should the Agent Execute, Confirm, or Handoff? |
| 4. Crash Test | Make the experiment legible | Agent Memory Crash Test: history → compacted memory → route → state diff |
| 5. Matched design | Explain causality without statistics jargon | Full evidence / remove one critical fact / remove equal-size noise |
| 6. Main result | Separate route quality from evidence quality | `figures/heldout-method-comparison.png` |
| 7. Honest boundary | Show what the audit fixes and cannot fix | `figures/heldout-causal-boundary.png` plus the hidden-hold replay |
| 8. Developer takeaway | Convert the result into a reusable design checklist | `Agent_Memory_Playbook.md` |
| 9. Close | State the contribution without overclaiming | Memory is a control-plane input; preserve or revalidate action proof |

The live narration should spend more time on slides 2, 4, 7, and 8 than on listing every baseline. The audience only needs one complete journey before seeing aggregate results.

## Core figures

- `figures/heldout-method-comparison.png` shows the main empirical nuance: several strong methods tie after deterministic audit on stable routing, while evidence-chain quality still separates them. Typed proof is the only evaluated method at 100% for both visible-card retention and citation precision in the frozen run.
- `figures/heldout-causal-boundary.png` shows the causal boundary: visible evidence can be validated, repairable proof gaps fail closed, but a hidden hold removed before compaction cannot be recovered by any downstream audit.
- `figures/presentation-metrics.json` contains the exact derived values, the source trace path, its SHA-256 hash, and the claim boundary.

Regenerate the figures from `05_代码与实验/` with:

```bash
python3 scripts/plot_typed_heldout_presentation.py
```

The plotting script reads the immutable `typed_exact_budget_heldout_qwen_v1_raw.jsonl`; it does not call a model or alter formal results.

## Demo route

Run the deterministic replay from `05_代码与实验/`:

```bash
python3 scripts/serve_memory_crash_test.py --port 8765
```

Recommended sequence:

1. Use `held-t8` with action-critical deletion: Direct wants to Execute, evidence audit changes the route to Handoff, and the external state remains unchanged.
2. Use `held-y6` with action-critical deletion: the active hold disappeared before compaction, so the typed system still Executes and the state diff is marked harmful.
3. End on the playbook rule: **a compactor can preserve evidence it receives; it cannot recover evidence that never entered its active context.**

The demo is a replay of frozen traces, not a staged live-model generation. That makes the classroom presentation deterministic while keeping every screen traceable to the formal artifact.

## Claims safe to say

- In the frozen held-out run, typed proof retention plus deterministic audit achieved 22/22 correct stable routes, 100% visible-card and critical-event retention, zero harmful executions, zero unnecessary interventions, and zero matched-noise route changes.
- The audit corrected 10 typed direct-router errors and spoiled none.
- Neutral summary, task-aware summary, and U-Fold-lite also achieved 22/22 audited stable routes; this is not a unique route-accuracy win.
- Typed proof's clearest observed advantage was inspectability: 100% visible-source citation precision, compared with 75.7% for neutral summary, 69.1% for task-aware summary, and 98.2% for U-Fold-lite.
- All three hidden-active-hold deletion cases remained harmful Executes. This is the disclosed system boundary.

Do not claim production safety, universal model generalization, or that compaction physically deletes the source log. The experiment concerns what evidence remains in the Agent's active decision context.
