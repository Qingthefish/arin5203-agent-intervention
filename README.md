# ARIN 5203 Course Project

**Do AI Platform Agents Know What They Must Not Forget?**<br>
**Compaction-Aware Intervention Before State-Changing Operations**

Building an Agent from 0 to 1 is increasingly accessible. Keeping it reliable over long histories requires knowing which evidence must survive before its next tool changes external state. This project compares memory strategies under a fixed raw-token budget, checks action-specific proof, and evaluates Execute / Confirm / Handoff through a deterministic simulator.

## Team

- **Qingcheng Yu** — agent product design, intervention policy, evaluation and presentation.
- **Siu Kwun Yeung** — enterprise multi-agent workflows, verification, review and control requirements.
- **Qingyin Guo** — agent application prototypes, tools/APIs and orchestration.

These are primary responsibilities; scenario review, implementation and final conclusions are shared. Team experience motivates synthetic cases, not claims about company production systems.

Teammate `HelloWorld2333666` contributed the commit-time, human-intervention and
field-grounding extensions. Their commits and original result bundles are kept;
integration fixes and acceptance checks are recorded separately.

Teammate `qingyg086` contributed report figures and bootstrap intervals, paired
trace analysis, a post-hoc router ablation and Milestone revisions. PRs #2–#6
are merged; the original frozen methods, data and scores are unchanged.

## Current Snapshot — 2026-11-19

| Workstream | Status | Evidence or entry point |
| --- | --- | --- |
| Proposal | Submitted; 92/100. No attributable instructor explanation for the deduction was found. | [Proposal files](01_提案/) |
| Core evaluation | Development protocol frozen; one-shot held-out evaluation complete. | [Held-out audit](05_代码与实验/results/typed_exact_budget_heldout_qwen_v1_audit.json) |
| Additional evidence | Budget sweep and durable-store test complete; teammate post-hoc paired/bootstrap analyses and router ablation are archived separately. The ablation uses a different model build and is not another untouched test. | [Experiment index](05_代码与实验/results/index.json), [Ablation summary](05_代码与实验/results/router_ablation_heldout_qwen3_5_9b_v1_summary.json) |
| Milestone | Submitted 6 Nov at 17:50; Canvas now shows 92/100. The visible comments contain team-member information. No instructor explanation was visible; PDF annotation access could not be completed. | [Canvas item](https://canvas.ust.hk/courses/71916/assignments/461590), [Submitted PDF](02_里程碑/Project_Milestone_Yu_Yeung_Guo.pdf), [LaTeX source](02_里程碑/milestone.tex) |
| AI paper/model sharing | Completed, per the team's 19 Nov update. The ACE title/link in row 19 and anonymous view/download were verified on 16 Nov. This was the separate 10-minute, 5% paper-sharing task. | [Schedule, row 19](https://docs.google.com/spreadsheets/d/1dGBKnn5RbBlhXROIEPmw-c7BQL4mejrDl5gUnpB1UDo/edit#gid=0&range=A19:F19) |
| Presentation | Low-density three-step replay; case/strategy matrix and trace details remain expandable. Seven evidence figures are available; team hand-builds PPT. | [Presentation guide](04_项目展示/README.md), [Playbook](04_项目展示/Agent_Memory_Playbook.md) |
| Reusable toolkit | Public research preview; contract-validation hardening is in patch v0.1.1. | [Standalone repository](https://github.com/Qingthefish/agent-memory-crash-test) |
| Commit-time gate | Integrated; original v1 deterministic evidence is preserved, with current applied-receipt and retry fixes checked separately. In-process simulation only. | [Original audit](05_代码与实验/results/commit_time_gate_deterministic_v1_audit.json), [Runbook](05_代码与实验/README.md#commit-time-evidence-freshness-gate) |
| Confirmation lifecycle | Integrated with strict reply-decision validation, channel-bound responder fixtures, action binding, expiry, revalidation and execute-once simulation. | [Technical notes](05_代码与实验/docs/human-intervention.md) |
| Field grounding | Integrated optional English cue-based checker; failures and intervention costs remain visible. No general semantic-verification or authentication claim. | [Technical notes and archived failures](05_代码与实验/docs/evidence-grounding.md) |
| Composed action loop | Synthetic hotel workflow with grounding, confirmation and commit-time mutation; known applied receipts reconcile errors, unknown outcomes stop automatic resume. | [Runnable example](05_代码与实验/examples/guarded_hotel_workflow.py), [Outcome handling](05_代码与实验/docs/integration.md#reconcile-an-error-after-the-side-effect) |
| Natural-language extension | Frozen development diagnostic complete: all routes Handoff. A zero-call post-hoc re-parse (11 Nov) attributes every rejected claim to scope typing and exposes ignored holds; interface v3 is implemented and unit-tested but **experimental and unvalidated**. Its validation run on five unseen dev families was attempted on local `qwen3.8:27b` and failed before any generation: this Ollama build's MLX backend lacks structured-output support (HTTP 501, 0/30 calls). The failed bundle is preserved, and no validation result exists yet. No end-to-end readiness claim. | [Diagnostic audit](05_代码与实验/results/nl_extraction_dev_diagnostic_qwen_v1_audit.json), [Re-parse audit](05_代码与实验/results/nl_extraction_dev_reparse_v3_posthoc_v1_audit.json), [v3 runbook](05_代码与实验/README.md#interface-v3-and-the-failure-layer-re-parse) |
| Component comparison | Post-hoc, zero-call reading of the frozen run. Typed direct routing exceeds the task-aware summary; their audited routes coincide. The primary audit bundles lookup and checking. Hidden holds account for their remaining harm. | [Factorial audit](05_代码与实验/results/factorial_ablation_heldout_posthoc_v1_audit.json), [Runbook](05_代码与实验/README.md#memory-x-verification-factorial) |
| Final report | Eight-page team-review draft including references, rebuilt and visually checked in the course-linked CVPR template. Includes teammate component and extraction analyses. Team review and report-sharing declaration remain. Due 5 Dec, 23:59 Hong Kong time. | [Review PDF](03_最终报告/Project_Final_Report_Yu_Yeung_Guo_DRAFT.pdf), [LaTeX source](03_最终报告/final_report.tex) |
| Supplement | Separate review ZIP contains source, frozen evidence, failure records, tests, replay and template sources, with file hashes and reproduction instructions. Both ZIP and code are below 10 MB. | [Supplement ZIP](03_最终报告/Project_Final_Supplement_Yu_Yeung_Guo.zip), [Packaging instructions](05_代码与实验/README.md#package-the-final-supplement) |

Exact calls, timings, tokens and scores live in manifests, summaries and audits. Historical pilots, failed gates and design changes are recorded in [项目复盘.md](项目复盘.md); the homepage is a current map, not a second experiment diary.

## What the Evidence Supports

1. Removing one action-critical fact can change the next tool decision; removing matched noise provides the causal control.
2. Earlier grounded-routing gates show that a correct route can still claim unsupported approval. In the frozen comparison, proof-source citation precision measures selection of proof sources, not semantic entailment; every method's parsed citations stayed inside its active source-ID set.
3. Typed retention and deterministic checking provide an inspectable proof chain. Strong summaries tie on audited stable routes; an inspired baseline does better across all conditions. The result does not establish typed-memory or state-of-the-art superiority. A post-hoc factorial of the same run shows why. Typed direct routing exceeds the task-aware summary in this run (20 vs 11 of 33 correct). Their lookup-plus-audit routes both reach 30/33. In a separate model build, giving the model the same re-read records did not reproduce the gain.
4. An audit cannot recover a hold removed before it receives the history. The durable-store test demonstrates one response under a declared authenticated-record assumption.

The benchmark contains 20 synthetic base families and 60 matched contexts: nine development bases and eleven held-out bases, with siblings kept together. Critical/noise events are word-count matched, not exact-token matched. The six compressed strategies share a 384 raw-Qwen-token budget; full history is an unbudgeted reference. These are correlated variants of a small, risk-enriched, single-model benchmark.

## Assumptions That Must Stay Visible

| Layer | What is established | What remains outside the claim |
| --- | --- | --- |
| Evidence creation | Main evaluation starts from source-linked typed records. Optional extraction and lexical field-grounding modules expose upstream failures. | Reliable arbitrary free-text extraction, general semantic entailment and real signature verification. |
| Memory and audit | Retained source IDs permit the deterministic audit to rehydrate canonical records. The fixed budget applies to active memory. | Total external storage, lookup overhead and a fully self-contained compressed-memory system. |
| Action outcome | Main frozen scores use an authored unsafe-if-executed flag plus the released route. The later replay/toolkit applies a declared simulated transition to show the state diff. | Independent live-domain outcome validation, real bookings, transfers or production deployments. |
| Human intervention | Route semantics distinguish a repairable answer from a required handoff; a scripted workflow now tests bound replies, expiry and simulated execution. | A deployed human workflow, real identity verification, a user study or measured production intervention burden. |
| Generalization | Frozen methods were evaluated once on separately authored synthetic families. | Broad model/domain generalization or production safety certification. |

The engineering takeaway is to treat conversational memory as a cache and validate authoritative action proof at the tool boundary. A passing test does not replace an authorization service.

The [related-work review](05_代码与实验/docs/related-work.md) distinguishes borrowed mechanisms from this project's integration. The [integration guide](05_代码与实验/docs/integration.md) maps current provider hooks to the application-owned proof boundary; it also explains why opaque compaction is not covered by a retained-ID snapshot alone.

## Next Work and Stopping Rule

The core experimental comparison and the separate ACE sharing are complete.
The next deliverables are the Final report and separate supplementary file,
followed by the course-project presentation. The team's 19 Nov integration
review checks the new PR #7 analyses and experimental interface, preserves the
original evidence, and rebuilds the report within the page limit. The
component comparison supports the joint lookup-plus-checking effect in this
run. Its post-hoc status and the different-build router ablation remain visible.

The remaining work is team review of the eight-page manuscript, a report-sharing
declaration, hand-built project slides, and the actual Canvas upload when the
Final item opens. The presentation uses one familiar travel case, the matched
comparison, the hidden-hold boundary, and an actionable developer procedure.
Further model experiments require an unanswered question that could change a
design decision. The experimental v3 extraction validation remains optional.

The optional **development-only natural-language extraction diagnostic** has
completed once on four existing families, both variants and all siblings.
The frozen JSON-mode interface is brittle: parser rejection and field mismatch
lead to uniform Handoff, not useful safety discrimination. Authentication wording
also limits interpreting every canonical mismatch as a model error. This does
not change the main held-out result or establish that schema-constrained
extraction cannot work. No automatic tuning run or expansion follows.

The integration preserves the contributor's v1 artifacts and failures. Human
workflow v1.3 and the NL-v2 grounding compatibility path have separate acceptance
plans and unit checks; no new formal result bundle was generated. The frozen
main comparison is unchanged. One synthetic hotel example now composes the
modules: preserve grounding vetoes, ask only when authority is repairable,
and delegate the sole simulated mutation to the commit gate. Authentication
and extraction are fixtures; this is not a real authenticated booking service.
The latest fault checks also separate an exception from the execution outcome:
only a trusted applied receipt establishes reconciled success, while an unknown
outcome closes the request and is never reported as definitely unexecuted.

The latest submitted Milestone and the repository's three-page PDF now match
byte for byte. The earlier two-page submission has been superseded by the
user's 17:50 resubmission; all members should use this same repository PDF.
Post-hoc ablation raw records, memory hashes, original direct-prompt hashes and
reported counts were checked; the new model build remains explicitly distinct
from the frozen run. Its legacy manifest lacks standard completion/usage
metadata and an audit bundle, so the index must not promote it to a frozen
gate result or silently include it in old manifest-based call totals. Before
any further ablation launch, bring its runner into the existing plan-only,
dual-explicit-flag and artifact conventions. No new run is needed for today's
submission. The useful engineering handoff is runnable code, trace export and
explicit adapter contracts. A live compactor adapter remains optional.

| Engineering extension | Current state | Acceptance question |
| --- | --- | --- |
| Commit-time freshness | Integrated and deterministically checked; not yet a live-tool or distributed guarantee. | Do holds/revocations, changed arguments and retries remain correct at the simulated mutation boundary? |
| [Human intervention](05_代码与实验/docs/human-intervention.md) | Integrated; unit acceptance includes the scripted matrix and malformed-reply regression. | Can only the named responder repair a bound gap, without replay, stale permission or duplicate execution? |
| [Field grounding](05_代码与实验/docs/evidence-grounding.md) | Integrated; current NL-v2 fixture compatibility checked, v1 failure evidence preserved. | Does source text support each field within the declared profile, without confusing textual support with authentication? |
| [Composed hotel loop](05_代码与实验/examples/guarded_hotel_workflow.py) | Source and clean-install example checks complete under the existing simulator assumptions. | Does a grounding veto survive the adapter, and can a hold introduced after confirmation still prevent the actual mutation? |

Further experiments need a concrete unanswered question that could change a design decision or claim. Extra model calls, models or charts alone are not a reason to run them.

### Final submission checklist, verified 19 Nov 2026

The [live project instructions](https://cqf.io/ARIN5203/project.html) require
these deliverables. The [Canvas assignment list](https://canvas.ust.hk/courses/71916/assignments)
currently contains Proposal and Milestone, with no Final Report upload item.

| Deliverable | Instructor requirement | Current action |
| --- | --- | --- |
| Final report | PDF, 6–8 pages, provided template, abstract at most 300 words, all three names; one member submits. Due 5 Dec 2026 at 23:59 Hong Kong time. | Review the eight-page draft, including references within that limit, and settle the report-sharing declaration before exporting the submission copy. |
| Supplement | Separate PDF or ZIP; relevant source, demos and visualizations. Code over 10 MB and model checkpoints are excluded by the course instructions. | Use the hashed ZIP and its code README. Rebuild after changing included files. |
| Course-project sharing | Syllabus lists Week 13. | Exact date, team duration, slide-upload destination and demo rules have not been published in the sources checked. The ACE task's 10-minute rule belongs to that earlier task. |

The report rubric is Introduction 10%, Related Work 10%, Data 10%, Methods 30%,
Experiments 30%, Conclusion 5%, and Writing/Formatting 5%. The source does not
explicitly exempt references from the page limit; the review draft includes
them within eight pages. It asks authors to state whether the report may be
shared with classmates. Source reuse must be cited in the report body.

Before upload, all members should review the same report and supplement from
`03_最终报告/`. One submitting member is sufficient under the official rule.
The local DRAFT filename marks team-review status. A successful Canvas receipt
and uploaded-file comparison complete submission verification once the item
opens. The completed Milestone remains the three-page PDF submitted at 17:50
on 6 Nov and graded 92/100.

## Start Here

From `05_代码与实验/` with Python 3.12 or newer:

```bash
python3 -m pip install -e .
agent-memory-crash-test --init my-memory-gate.json
agent-memory-crash-test --spec examples/memory_crash_test.json --validate-only
python3 -m unittest discover -s tests -v
python3 scripts/index_experiment_artifacts.py --check
python3 scripts/serve_memory_crash_test.py --port 8765
```

Open `http://127.0.0.1:8765` for the model-free frozen-trace replay. The [technical runbook](05_代码与实验/README.md) owns commands, artifact rules and reproduction details. Model runners remain plan-only without both explicit run flags; existing experiments use local Ollama `qwen3.5:9b` at zero external API fee.

## Repository and Collaboration

- [AGENTS.md](AGENTS.md) — permanent scope and working rules.
- [项目复盘.md](项目复盘.md) — rationale, failures and presentation decisions.
- [05_代码与实验/README.md](05_代码与实验/README.md) — technical interfaces and reproduction.
- [results/index.json](05_代码与实验/results/index.json) — generated artifact discovery; manifests/audits own exact results.
- `01_提案/`, `02_里程碑/`, `03_最终报告/`, `04_项目展示/` — course deliverables, working report and presentation evidence.
- `CVPR2026_模板源码/` — locally retained vendor template; the course link currently opens a CVPR 2026 template (checked 27 Oct). Its README is not project documentation.

The [course repository](https://github.com/Qingthefish/arin5203-agent-intervention) contains the research archive and latest development. The [standalone toolkit](https://github.com/Qingthefish/agent-memory-crash-test) publishes reviewed, versioned package snapshots; it does not automatically inherit every experimental extension.

Pull current `main`, create a focused branch, preserve immutable outputs, and use a PR for teammate contributions. Keep credentials, private company material, model weights and unrelated coursework out of commits. One team member submits each course deliverable with all three names. Recheck the live course instructions at submission time.
