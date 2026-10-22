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

Every comparison concerns Execute / Confirm / Handoff, evidence selection,
harmful or unnecessary intervention. Main frozen harmful-Execute scores are an
authored unsafe flag AND the released route. The later replay/toolkit applies a
declared simulated transition to illustrate the state diff; it is not an
independent live-domain outcome measurement. Summary fluency is never the final score.

## Three-claim spine

Do not narrate every experiment chronologically. The failed and intermediate runs remain in the repository for reproducibility, but the main deck only needs three claims:

| Claim | Best evidence | What the audience learns |
| --- | --- | --- |
| Evidence availability can change a tool decision | Controlled critical/noise deletions plus the fixed-budget strategy comparison | Distinguish induced upstream evidence loss from a compactor's actual retention failure |
| A correct route is not enough | Failed grounded-routing development gates; separately, held-out proof-source selection | Test source existence, claim support and complete action proof separately |
| Audit has a sharp boundary | 22/22 stable typed audited routes; 8/8 non-hold omissions fail closed; 3/3 hidden holds remain harmful | Revalidate visible proof at the tool boundary, and protect upstream event delivery separately |

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

- **12-minute core:** 1.5 minutes hook and failure; 1.5 minutes research question and Crash Test; 2 minutes matched design; 2.5 minutes results; 2 minutes deterministic replay; 2 minutes playbook; 0.5 minute close.
- **Optional 5-minute depth:** baseline definitions, route-versus-grounding failure, exact-token fairness, and one negative audit experiment.
- **Backup only:** full experiment chronology, implementation details, all metrics, and additional domains.

The replay is presenter-controlled and deterministic. It does not require audience interaction or a live model call.

The interface follows the same progressive-disclosure rule as the talk. Its
default Story Mode opens on the hotel active-hold failure and shows only the
request, the missing fact, the resulting route, the external state diff, and
the durable-source lesson. **Evidence Suite** keeps the full seven-strategy by
three-sibling matrix for aggregate comparison, while **Trace Inspector** keeps
exact memory, proof cards, obligations, tokens, and citation details for Q&A.
The dense table is therefore evidence behind the story, not the first screen
the audience must decode.

## Core figures

- `figures/matched-case-held-y6.png` is the opening boundary example. Word-matched noise deletion changes nothing; deleting a hold **before compaction** flips Handoff to harmful Execute. The pictured state diff is a simulated replay. Do not call this proof that the compactor deleted the hold.
- `figures/benchmark-design.png` shows 20 bases / 60 matched contexts, six compressed strategies under 384 raw tokens plus unbudgeted full history, and family-level splits. Core critical/noise events are word-count matched, not token- or byte-matched.
- `figures/heldout-method-comparison.png` separates stable-route accuracy, visible-card recall and proof-source selection. Several strong baselines tie on stable audited routing. Typed proof alone is 100% on both displayed evidence metrics; that is not semantic-entailment verification.
- `figures/heldout-causal-boundary.png` shows visible-proof validation, non-hold gaps that fail closed, and holds removed before compaction that cannot be reconstructed downstream. Not every non-hold gap is single-answer repairable.
- `figures/budget-sensitivity.png` shows the development-only 384 / 256 / 192-token stress test. Strong summaries and typed proof keep 18/18 stable routes at 192 tokens; U-Fold-lite degrades, generic pinning loses most visible proof, and typed proof's only loss is one non-decisive recovery card in two records.
- `figures/durable-store-rescue.png` closes the hidden-hold story with a development-only architecture test: memory-only proof validates 12/18 routes with three harmful Executes; point-in-time registry lookup reaches 18/18 while leaving 12 expired, revoked, and wrong-scope controls unchanged.
- `figures/experiment-scale.png` is optional evidence for the work behind the result. It reports selected stages with measured calls and wall time, plus archive totals derived from the current index. Exact changing totals live in the generated figure/metrics, not a second handwritten counter here. These counts exclude separate tokenizer probes and are not independent sample sizes.
- `figures/presentation-metrics.json` contains every derived value, source artifact path, SHA-256 hash, and claim boundary used by all seven figures.

For a short presentation, do not try to show all seven figures:

- **Core:** matched hotel case → benchmark design → held-out method comparison → causal boundary and durable-store rescue side by side.
- **Optional depth:** budget sensitivity, if at least one extra minute is available.
- **Backup only:** experiment scale. Use it to answer “how much did you run?”, not as evidence that the idea is correct.

This yields one example, one causal design, one aggregate comparison, and one architecture lesson. The Playbook then becomes the conclusion rather than an eighth results chart.

## Experiment stopping rule

Do not add experiments merely to increase the call count. The frozen evidence
answers the core questions under declared typed-card and external-lookup
assumptions. The frozen development-only natural-language extraction diagnostic
has completed with uniform Handoff and substantial contract failures. Report
that boundary without automatically tuning or rerunning. A real single-workflow
compactor adapter is a separate optional engineering acceptance test, not a
prerequisite for the bounded course result.

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

1. Open the default `held-y6` Story Mode: the active hold disappeared before compaction, so the typed system still Executes and the hotel state diff is marked harmful.
2. Turn on the durable registry overlay and show that the same validator now Handoffs after re-reading the authoritative hold.
3. Switch to Evidence Suite to show that the story is one cell in a 7-strategy × 3-sibling regression matrix, not a handpicked animation.
4. If time permits, use `held-t8` in Trace Inspector: Direct wants to Execute, evidence audit changes the route to Handoff, and the exact source-linked delegation gap is visible.
5. End on the playbook rule: **a compactor can preserve evidence it receives; it cannot recover evidence that never entered its active context.**

The demo is a replay of frozen traces, not a staged live-model generation. That makes the classroom presentation deterministic while keeping every screen traceable to the formal artifact. The adjacent command-line Crash Test Kit turns the same design into a CI interface: a JSON proof contract produces matched siblings and JSON/JUnit reports, so the product takeaway is “write memory regression tests before shipping a mutating Agent,” not “watch our website.”

## Claims safe to say

- In the frozen held-out run, typed proof retention plus deterministic audit achieved 22/22 correct stable routes, 100% visible-card and critical-event retention, zero harmful executions, zero unnecessary interventions, and zero matched-noise route changes.
- The audit corrected 10 typed direct-router errors and spoiled none.
- Neutral summary, task-aware summary, and U-Fold-lite also achieved 22/22 audited stable routes; this is not a unique route-accuracy win.
- Typed proof's evidence-selection metric was 100%, versus 75.7% neutral, 69.1% task-aware and 98.2% U-Fold-lite. These are macro-averaged **proof-source citation precision** values, not semantic entailment. Every method had zero parsed citations outside active source IDs in a post-hoc recount.
- Across all 33 contexts U-Fold-lite achieved 31/33 versus typed proof's 30/33. Its conservative evidence loss blocked one hidden-hold Execute. Do not hide this result behind the stable subset or imply a universal typed-method win.
- All three hidden-active-hold deletion cases remained harmful Executes. This is the disclosed system boundary.

Do not claim production safety, universal model generalization, or that compaction physically deletes the source log. The experiment concerns what evidence remains in the Agent's active decision context.

## Final report assembly map

Target about **7.5 pages including references** until the reference-page rule is
confirmed. Methods and Experiments carry 60% of the rubric. The report owns the
full protocol and results; hand-made slides keep the main story above, and the
two-page Milestone remains a development checkpoint.

A seven-page [working draft](../03_最终报告/Project_Final_Report_Yu_Yeung_Guo_DRAFT.pdf)
now exists, with [editable LaTeX](../03_最终报告/final_report.tex). It is not a
submission-ready artifact; live template alignment and team review remain open.

| Report content | Pages | Source owner / material to assemble |
| --- | ---: | --- |
| Title, Abstract, Introduction | 0.75 | [Root README](../README.md)'s question and boundaries; one travel-action example. Abstract ≤300 words. |
| Related Work | 0.5 | `docs/related-work.md`: direct overlap with Compaction Cliff and PAIR; inspired baselines are not reproductions. |
| Data and Protocol | 0.75 | `src/platform_agent_eval/typed_compaction_{dev,heldout}.py` and `configs/typed_exact_budget_heldout.json`: family split, word-matched siblings, blinded methods and active-token budget. |
| Methods | 1.5 | `src/platform_agent_eval/proof_cards.py`, `docs/contract.md`, `docs/integration.md`: proof obligations, source-ID lookup, repairability and tool boundary; show external records outside the active budget. |
| Experiments and Failure Analysis | 2.25 | `typed_exact_budget_heldout_qwen_v1` main comparison; `typed_budget_sweep_dev_qwen_v1` development sensitivity; `durable_proof_store_deterministic_v1` architecture test; one negative trace. |
| Limitations, Developer Implications, Conclusion | 0.75 | [Playbook](Agent_Memory_Playbook.md) and the [retrospective](../项目复盘.md)'s 2026-10-23 review: three design decisions, evidence assumptions and failure boundary. |
| References | 1.0 | Verified primary sources and any borrowed implementation, cited in the body. |

Research paths/prefixes above are relative to `05_代码与实验/`; links resolve separately.
For each run, `results/<prefix>_raw.jsonl` owns traces, `_summary.csv` scores,
`_audit.json` protocol checks, and `_manifest.json` configuration and provenance.
`figures/presentation-metrics.json` owns derived figure values; `results/index.json`
is discovery metadata. The experiment-scale figure is optional backup only.

Captions must distinguish **observed** frozen traces, **demonstrated** simulated
replay/registry behavior, and **recommended** architecture. Show both stable and
all-condition results: strong methods tie at 22/22 stable routes, while U-Fold-lite
has 31/33 overall versus typed proof's 30/33. Proof-source selection is not semantic
entailment; the source-existence recount is post-hoc. Main harmful-Execute scores
combine an authored unsafe flag with the route; replay state diffs are simulated.

The completed NL diagnostic occupies a short Experiments subsection linked to
`nl_extraction_dev_diagnostic_qwen_v1`. Explain strict JSON-mode contract failure,
raw versus post-parser omissions, signed/verified ambiguity, and why all-Handoff
does not demonstrate useful safety. It is development-only extraction on derived
families, not a compactor comparison or new held-out result. Verify live
submission/template rules and sharing preference before final sign-off;
supplementary material is submitted separately.

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
