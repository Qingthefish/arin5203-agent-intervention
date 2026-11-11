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

## Current Snapshot — 2026-11-06

| Workstream | Status | Evidence or entry point |
| --- | --- | --- |
| Proposal | Submitted; 92/100. No attributable instructor explanation for the deduction was found. | [Proposal files](01_提案/) |
| Core evaluation | Development protocol frozen; one-shot held-out evaluation complete. | [Held-out audit](05_代码与实验/results/typed_exact_budget_heldout_qwen_v1_audit.json) |
| Additional evidence | Budget sweep and durable-store test complete; teammate post-hoc paired/bootstrap analyses and router ablation are archived separately. The ablation uses a different model build and is not another untouched test. | [Experiment index](05_代码与实验/results/index.json), [Ablation summary](05_代码与实验/results/router_ablation_heldout_qwen3_5_9b_v1_summary.json) |
| Milestone | Latest Canvas receipt verified: Qingcheng submitted the three-page revision on 6 Nov at 17:50, before the 23:59 deadline. The downloaded submitted attachment is byte-identical to the repository PDF and includes the teammate additions. | [Canvas item](https://canvas.ust.hk/courses/71916/assignments/461590), [Submitted PDF](02_里程碑/Project_Milestone_Yu_Yeung_Guo.pdf), [LaTeX source](02_里程碑/milestone.tex) |
| AI paper/model sharing | Separate from the course-project presentation: this team is scheduled for 16 Nov, 10 minutes, on one or two related papers/models; 5% of the course grade. Title and slides URL were blank in the schedule checked on 6 Nov. | [Schedule, row 19](https://docs.google.com/spreadsheets/d/1dGBKnn5RbBlhXROIEPmw-c7BQL4mejrDl5gUnpB1UDo/edit#gid=0&range=A19:F19); instructor email dated 30 Oct |
| Presentation | Low-density three-step replay; case/strategy matrix and trace details remain expandable. Seven evidence figures are available; team hand-builds PPT. | [Presentation guide](04_项目展示/README.md), [Playbook](04_项目展示/Agent_Memory_Playbook.md) |
| Reusable toolkit | Public research preview; contract-validation hardening is in patch v0.1.1. | [Standalone repository](https://github.com/Qingthefish/agent-memory-crash-test) |
| Commit-time gate | Integrated; original v1 deterministic evidence is preserved, with current applied-receipt and retry fixes checked separately. In-process simulation only. | [Original audit](05_代码与实验/results/commit_time_gate_deterministic_v1_audit.json), [Runbook](05_代码与实验/README.md#commit-time-evidence-freshness-gate) |
| Confirmation lifecycle | Integrated with strict reply-decision validation, channel-bound responder fixtures, action binding, expiry, revalidation and execute-once simulation. | [Technical notes](05_代码与实验/docs/human-intervention.md) |
| Field grounding | Integrated optional English cue-based checker; failures and intervention costs remain visible. No general semantic-verification or authentication claim. | [Technical notes and archived failures](05_代码与实验/docs/evidence-grounding.md) |
| Composed action loop | Synthetic hotel workflow with grounding, confirmation and commit-time mutation; known applied receipts reconcile errors, unknown outcomes stop automatic resume. | [Runnable example](05_代码与实验/examples/guarded_hotel_workflow.py), [Outcome handling](05_代码与实验/docs/integration.md#reconcile-an-error-after-the-side-effect) |
| Natural-language extension | Frozen development diagnostic complete: all routes Handoff. A zero-call post-hoc re-parse (11 Nov) attributes every rejected claim to scope typing and exposes ignored holds; interface v3 is implemented and tested. Its validation run on five unseen dev families was attempted on local `qwen3.8:27b` and failed before any generation: this Ollama build's MLX backend lacks structured-output support (HTTP 501, 0/30 calls). The failed bundle is preserved, and no validation result exists yet. No end-to-end readiness claim. | [Diagnostic audit](05_代码与实验/results/nl_extraction_dev_diagnostic_qwen_v1_audit.json), [Re-parse audit](05_代码与实验/results/nl_extraction_dev_reparse_v3_posthoc_v1_audit.json), [v3 runbook](05_代码与实验/README.md#interface-v3-and-the-failure-layer-re-parse) |
| Component factorial | Post-hoc, zero-call reading of the frozen held-out run (11 Nov): the deterministic check, not memory representation, carries the safety gain; residual harm is hidden holds. Not pre-registered. | [Factorial audit](05_代码与实验/results/factorial_ablation_heldout_posthoc_v1_audit.json), [Runbook](05_代码与实验/README.md#memory-x-verification-factorial) |
| Final report | Working draft now includes teammate figures and bootstrap analysis; further assembly and team review remain. Not submission-ready; due 5 Dec, 23:59. | [Draft PDF](03_最终报告/Project_Final_Report_Yu_Yeung_Guo_DRAFT.pdf), [LaTeX source](03_最终报告/final_report.tex) |

Exact calls, timings, tokens and scores live in manifests, summaries and audits. Historical pilots, failed gates and design changes are recorded in [项目复盘.md](项目复盘.md); the homepage is a current map, not a second experiment diary.

## What the Evidence Supports

1. Removing one action-critical fact can change the next tool decision; removing matched noise provides the causal control.
2. Earlier grounded-routing gates show that a correct route can still claim unsupported approval. In the frozen comparison, proof-source citation precision measures selection of proof sources, not semantic entailment; every method's parsed citations stayed inside its active source-ID set.
3. Typed retention and deterministic checking provide an inspectable proof chain. Strong summaries tie on audited stable routes; an inspired baseline does better across all conditions. The result does not establish typed-memory or state-of-the-art superiority. A post-hoc factorial of the same run shows why. Typed memory helps only when the model routes directly (20 vs 11 of 33 correct). Under the deterministic audit both reach 30/33. In a separate model build, giving the model the same re-read records did not reproduce the gain.
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

The core experimental question is answered at course-project scale. The
Milestone submission receipt is verified. The immediate course task is the
separate AI paper/model sharing on 16 Nov: select one or two related papers,
prepare the team's hand-made slides, and fill the title and accessible slides
URL in the schedule before presenting. The three runtime extensions are
integrated and checked as bounded research modules. Final-report assembly and
course-project slides resume separately. The 2026-10-23 review corrects
interpretation, not frozen scores or method selection; its source-existence
recount is explicitly post-hoc.

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

### Milestone submission checklist

- The [live project page](https://cqf.io/ARIN5203/project.html), checked on
  6 Nov, requires 2–3 pages in the provided template, all three names, and one
  submitting member. A report PDF is sufficient; no extra GitHub/ZIP/demo
  requirement appears in the Milestone section or Canvas item.
- Canvas assignment 461590 shows a successful 6 Nov 17:50 submission, the report
  attachment and all three team members. The downloaded attachment
  `Project_Milestone_Yu_Yeung_Guo-1.pdf` is byte-identical to the repository PDF:
  three pages, 47,660 bytes, SHA-256
  `f1e202c84a20ba082f2af5e9eac0d1f6d775708b5648838ff050ca2a7c5f9f3a`.
  Its page count, authors, required sections and visible layout were checked.
  The `-1` filename suffix does not indicate different content. Use the
  repository PDF as the shared team submission file.
- The deadline is 6 Nov at 23:59 Hong Kong time. The upload window ends on
  10 Nov at 23:59; that later closing time is not the ordinary deadline.
- The instructor's 30 Oct email schedules AI paper/model sharing on 9, 16 and
  23 Nov, with this team listed on 16 Nov. It asks for the presentation title
  and an online slides URL before presenting; a USB/downloadable backup is
  requested. Sharing presentation parts among members is suggested, not
  required. This is separate from the syllabus's Week 13 course-project
  sharing, whose per-team duration and demo requirements remain unconfirmed.

Final is ready when:

- the report states the proof-card, external-record and simulator assumptions explicitly;
- each headline result maps to an immutable artifact, including strong-baseline ties and failures;
- the replay and clean-install toolkit example reproduce the documented behavior;
- the presentation ends with a procedure classmates can use when designing or iterating an Agent.

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
