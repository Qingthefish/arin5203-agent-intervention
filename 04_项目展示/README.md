# Presentation Evidence Pack

This directory turns the frozen held-out experiment into a presentation that is useful to Agent developers. It does not add a new model run or reinterpret the test set.

## One-sentence story

Building an Agent from 0 to 1 is increasingly easy; keeping it reliable from 1 to 100 is harder because context compaction can silently change the evidence available before a tool changes external state.

## Audience contract

The presentation should be understandable to a classmate who has built an Agent in Coze, Dify, Claude Code, or Codex but has never operated an AI platform. It promises to answer three practical questions:

1. What can go wrong after an Agent shortens a long working history?
2. How can a developer test whether one missing memory actually caused the wrong action?
3. What should be stored, checked, or escalated before a tool changes the outside world?

Introduce the mechanism through one familiar travel-agent story before using research vocabulary. In that story, the Agent still remembers the request to change a booking but loses either the delegation that authorizes payment or an active hold that forbids the change. The visible consequence is not a worse chat answer; it is a booking state that changes when it should not.

The audience should leave with an implementation procedure, not the tautology that “memory can fail”: inventory proof requirements for each mutating tool, keep authoritative proof on a separate reliability path from chat summaries, validate that proof at the tool boundary, route repairable and non-repairable gaps differently, and crash-test the design by deleting one fact at a time.

Use these plain-language mappings on first mention:

| Research term | Audience-facing meaning |
| --- | --- |
| Context compaction | The Agent shortens old chat and tool history so it can keep working |
| State-changing operation | A tool actually books, pays, sends, deploys, or changes a record |
| Evidence audit | A last check that permission, scope, time limit, blockers, and recovery proof are present |
| Matched sibling | The same story with either one critical fact or equal-length noise removed |
| Provenance | The Agent can point to the exact source event behind a claimed fact |

## What the experiments actually compare

The project is a controlled comparison along five independent axes. Keeping these axes separate is the main reason the result is useful to developers rather than only a warning about forgetting.

| Axis held or changed | Comparison | Developer question answered |
| --- | --- | --- |
| Memory strategy | recent window, neutral summary, task-aware summary, generic pinning, U-Fold-lite, typed proof; full history is an unbudgeted ceiling | Which representations retain action proof under the same raw-token budget? |
| Evidence perturbation | complete history, one critical fact removed, equal-size nearby noise removed | Did the missing fact cause the route change, or is the Agent merely reacting to shorter text? |
| Decision layer | direct router versus the same memory plus deterministic proof audit | Does the audit repair mistakes without spoiling already-correct autonomy? |
| Token pressure | 384, 256, and 192 raw tokens on the frozen development set | Which methods fail first as memory becomes tighter, and what proof disappears? |
| Source architecture | memory only versus point-in-time durable proof lookup | Can downstream memory solve the failure, or must the system re-read authoritative state? |

Every comparison ends at the same outcomes: Execute / Confirm / Handoff, cited decisive evidence, harmful or unnecessary intervention, and the actual external state diff. Summary fluency is never the final score.

## Three-claim spine

Do not narrate every experiment chronologically. The failed and intermediate runs remain in the repository for reproducibility, but the main deck only needs three claims:

| Claim | Best evidence | What the audience learns |
| --- | --- | --- |
| Compaction can silently change a tool decision | Full / critical-deletion / equal-noise matched siblings | Test memory by changing one fact at a time, not by reading plausible summaries |
| A correct route is not enough | Earlier grounded-routing cases where the button was right but the cited approval was absent; held-out citation precision | Score whether the decisive evidence really exists and can be traced |
| Audit has a sharp boundary | 22/22 stable typed audited routes; 8/8 repairable omissions fail closed; 3/3 hidden holds remain harmful | Revalidate visible proof at the tool boundary, and protect upstream event delivery separately |

This framing preserves all of the research work without forcing the audience to remember the protocol-falsification gate, multiple router versions, or each failed schema. Those belong in the report and backup slides as the evidence trail behind the final design.

## Recommended nine-slide arc

| Slide | Purpose | Evidence or visual |
| --- | --- | --- |
| 1. Hook | Move from “how to build an Agent” to “how to keep one reliable” | 0→1 versus 1→100 framing |
| 2. One familiar failure | Show that forgetting is an action problem, not only a conversation problem | `figures/matched-case-held-y6.png` |
| 3. Research question | Define the exact decision | Under the same raw-token budget, should the Agent Execute, Confirm, or Handoff? |
| 4. Crash Test | Make the experiment legible | Agent Memory Crash Test: history → compacted memory → route → state diff |
| 5. Matched design | Explain causality without statistics jargon | `figures/benchmark-design.png` |
| 6. Main result | Separate route quality from evidence quality | `figures/heldout-method-comparison.png` |
| 7. Honest boundary | Show what the audit fixes and cannot fix | `figures/heldout-causal-boundary.png` plus the hidden-hold replay |
| 8. Developer takeaway | Convert the result into a reusable design checklist | `Agent_Memory_Playbook.md` |
| 9. Close | State the contribution without overclaiming | Memory is a control-plane input; preserve or revalidate action proof |

The live narration should spend more time on slides 2, 4, 7, and 8 than on listing every baseline. The audience only needs one complete journey before seeing aggregate results.

## Modular run of show

No official final-presentation duration has been verified in the local course requirements, so prepare a compact core that can expand without changing the story:

- **12-minute core:** 1.5 minutes hook and failure; 2 minutes research question and Crash Test; 2 minutes matched design; 2.5 minutes results; 2 minutes deterministic replay; 1.5 minutes playbook; 0.5 minute close.
- **Optional 5-minute depth:** baseline definitions, route-versus-grounding failure, exact-token fairness, and one negative audit experiment.
- **Backup only:** full experiment chronology, implementation details, all metrics, and additional domains.

The replay is presenter-controlled and deterministic. It does not require audience interaction or a live model call.

## Core figures

- `figures/matched-case-held-y6.png` is the recommended opening example. It uses one frozen hotel-booking family to show that removing equal-size noise changes nothing, while removing the active hold flips Handoff to a harmful Execute and changes the external state.
- `figures/benchmark-design.png` explains the full experiment in one frame: 20 bases become 60 matched contexts, seven memory strategies share a 384-token budget, siblings remain in one split, and the state oracle scores Execute / Confirm / Handoff consequences.
- `figures/heldout-method-comparison.png` shows the main empirical nuance: several strong methods tie after deterministic audit on stable routing, while evidence-chain quality still separates them. Typed proof is the only evaluated method at 100% for both visible-card retention and citation precision in the frozen run.
- `figures/heldout-causal-boundary.png` shows the causal boundary: visible evidence can be validated, repairable proof gaps fail closed, but a hidden hold removed before compaction cannot be recovered by any downstream audit.
- `figures/budget-sensitivity.png` shows the development-only 384 / 256 / 192-token stress test. Strong summaries and typed proof keep 18/18 stable routes at 192 tokens; U-Fold-lite degrades, generic pinning loses most visible proof, and typed proof's only loss is one non-decisive recovery card in two records.
- `figures/durable-store-rescue.png` closes the hidden-hold story with a development-only architecture test: memory-only proof validates 12/18 routes with three harmful Executes; point-in-time registry lookup reaches 18/18 while leaving 12 expired, revoked, and wrong-scope controls unchanged.
- `figures/experiment-scale.png` is optional evidence for the work behind the result. It reports selected stages with measured calls and wall time, plus the machine-indexed totals: 40 run manifests, 2,069 measured local calls, 2.00 million recorded model tokens, 24 frozen gate bundles, 10 retained failed/aborted runs, and `$0` external API cost.
- `figures/presentation-metrics.json` contains every derived value, source artifact path, SHA-256 hash, and claim boundary used by all seven figures.

For a short presentation, do not try to show all seven figures:

- **Core:** matched hotel case → benchmark design → held-out method comparison → causal boundary and durable-store rescue side by side.
- **Optional depth:** budget sensitivity, if at least one extra minute is available.
- **Backup only:** experiment scale. Use it to answer “how much did you run?”, not as evidence that the idea is correct.

This yields one example, one causal design, one aggregate comparison, and one architecture lesson. The Playbook then becomes the conclusion rather than an eighth results chart.

## Experiment stopping rule

Do not add experiments merely to increase the call count. The frozen evidence already answers the main causal, budget, audit-increment, and upstream-boundary questions. A new run is justified only if slide rehearsal exposes a decision-relevant question that no existing immutable artifact can answer. The most plausible optional extension is a second already-installed local model as a transfer check; downloading a new large model solely for another bar chart is out of scope.

Regenerate the figures from `05_代码与实验/` with:

```bash
python3 scripts/plot_typed_heldout_presentation.py
```

The plotting script reads the immutable v6 development trace, one-shot held-out trace, and machine-generated experiment index. It does not call a model or alter formal results.

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

## Experiment evidence map for speakers

Use this map to answer questions without putting the whole history in the main deck:

| Stage | What it contributed | Main-deck status |
| --- | --- | --- |
| Early simulator and feasibility pilots | Proved the local pipeline and three-way routing could run | One sentence only |
| Token re-audit and protocol falsification | Showed old method comparisons were unfair and route accuracy hid grounding failures | Mention as research correction |
| Matched causal scratch sets | Isolated critical-evidence loss from same-size noise loss | Main method slide |
| Prompt critic and candidate-visible audit | Negative result: a second free-text opinion could spoil correct decisions | Backup failure lesson |
| Candidate-blind verifier | Improved routes but confused clearance with authority | Backup bridge to typed proof |
| Provenance-typed proof cards | Made evidence kinds, scope, source, and validity programmatically checkable | Main architecture slide |
| Exact-budget v4--v6 | Repaired instrumentation, passed development gates, and froze the method | Report or backup |
| One-shot held-out run | Supports final outcome, inspectability, and boundary claims | Main results slides |
| Deterministic replay | Makes the route and external state consequence visible | Main demo |
