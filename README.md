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

## Current Snapshot — 2026-10-29

| Workstream | Status | Evidence or entry point |
| --- | --- | --- |
| Proposal | Submitted; 92/100. No attributable instructor explanation for the deduction was found. | [Proposal files](01_提案/) |
| Core evaluation | Development protocol frozen; one-shot held-out evaluation complete. | [Held-out audit](05_代码与实验/results/typed_exact_budget_heldout_qwen_v1_audit.json) |
| Additional evidence | Development budget sweep and deterministic durable-store test complete. | [Experiment index](05_代码与实验/results/index.json) |
| Milestone | Two-page report checked against live requirements and visually reviewed; ready for team review, with no content change needed this round. Due 6 Nov, 23:59; no submission item was visible in the student's Canvas list on 29 Oct. | [PDF](02_里程碑/Project_Milestone_Yu_Yeung_Guo.pdf), [LaTeX source](02_里程碑/milestone.tex) |
| Presentation | Low-density three-step replay; case/strategy matrix and trace details remain expandable. Seven evidence figures are available; team hand-builds PPT. | [Presentation guide](04_项目展示/README.md), [Playbook](04_项目展示/Agent_Memory_Playbook.md) |
| Reusable toolkit | Public research preview; contract-validation hardening is in patch v0.1.1. | [Standalone repository](https://github.com/Qingthefish/agent-memory-crash-test) |
| Commit-time gate | Group-contributed prepare/commit gate hardened and checked; versioned deterministic development acceptance passes under in-process simulation assumptions. | [Audit](05_代码与实验/results/commit_time_gate_deterministic_v1_audit.json), [Runbook](05_代码与实验/README.md#commit-time-evidence-freshness-gate) |
| Confirmation lifecycle | Integrated with strict reply-decision validation, channel-bound responder fixtures, action binding, expiry, revalidation and execute-once simulation. | [Technical notes](05_代码与实验/docs/human-intervention.md) |
| Field grounding | Integrated optional English cue-based checker; failures and intervention costs remain visible. No general semantic-verification or authentication claim. | [Technical notes and archived failures](05_代码与实验/docs/evidence-grounding.md) |
| Composed action loop | A synthetic hotel workflow now joins grounding, bound confirmation and commit-time mutation; tested from source and a clean local wheel install. | [Runnable example](05_代码与实验/examples/guarded_hotel_workflow.py), [Adapter contracts](05_代码与实验/docs/integration.md#composed-hotel-workflow) |
| Natural-language extension | Frozen development diagnostic complete: all routes Handoff; strict contract failures dominate. No end-to-end readiness claim. | [Diagnostic audit](05_代码与实验/results/nl_extraction_dev_diagnostic_qwen_v1_audit.json), [Frozen plan](05_代码与实验/configs/nl_extraction_dev_diagnostic_v1.json) |
| Final report | Existing seven-page working draft is parked while Milestone takes priority; not submission-ready. | [Draft PDF](03_最终报告/Project_Final_Report_Yu_Yeung_Guo_DRAFT.pdf), [LaTeX source](03_最终报告/final_report.tex) |

Exact calls, timings, tokens and scores live in manifests, summaries and audits. Historical pilots, failed gates and design changes are recorded in [项目复盘.md](项目复盘.md); the homepage is a current map, not a second experiment diary.

## What the Evidence Supports

1. Removing one action-critical fact can change the next tool decision; removing matched noise provides the causal control.
2. Earlier grounded-routing gates show that a correct route can still claim unsupported approval. In the frozen comparison, proof-source citation precision measures selection of proof sources, not semantic entailment; every method's parsed citations stayed inside its active source-ID set.
3. Typed retention and deterministic checking provide an inspectable proof chain. Strong summaries tie on audited stable routes; an inspired baseline does better across all conditions. The result does not establish typed-memory or state-of-the-art superiority.
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

The core experimental question is answered at course-project scale. The current
priority is team review and Milestone submission readiness. The three existing
runtime extensions are integrated and checked as bounded research modules.
The existing Final draft is parked at the
team's request. The 2026-10-23 review corrects interpretation, not frozen scores
or method selection; its source-existence recount is explicitly post-hoc.

The optional **development-only natural-language extraction diagnostic** has
completed once on four existing families, both variants and all siblings.
The frozen JSON-mode interface is brittle: parser rejection and field mismatch
lead to uniform Handoff, not useful safety discrimination. Authentication wording
also limits interpreting every canonical mismatch as a model error. This does
not change the main held-out result or establish that schema-constrained
extraction cannot work. No automatic tuning run or expansion follows.

The integration preserves the contributor's v1 artifacts and failures. Human
workflow v1.2 and the NL-v2 grounding compatibility path have separate acceptance
plans and unit checks; no new formal result bundle was generated. The frozen
main comparison is unchanged. One synthetic hotel example now composes the
modules: preserve grounding vetoes, ask only when authority is repairable,
and delegate the sole simulated mutation to the commit gate. Authentication
and extraction are fixtures; this is not a real authenticated booking service.

Next: team-review the short Milestone and the composed hotel example, then submit
through the correct Canvas item when it becomes available. Final and hand-made
slides can resume later. The useful engineering handoff is now runnable code,
trace export and explicit adapter contracts, not another broad model sweep.
An actual single-workflow compactor adapter remains optional engineering work,
not a prerequisite for presenting the bounded research result.

| Engineering extension | Current state | Acceptance question |
| --- | --- | --- |
| Commit-time freshness | Integrated and deterministically checked; not yet a live-tool or distributed guarantee. | Do holds/revocations, changed arguments and retries remain correct at the simulated mutation boundary? |
| [Human intervention](05_代码与实验/docs/human-intervention.md) | Integrated; unit acceptance includes the scripted matrix and malformed-reply regression. | Can only the named responder repair a bound gap, without replay, stale permission or duplicate execution? |
| [Field grounding](05_代码与实验/docs/evidence-grounding.md) | Integrated; current NL-v2 fixture compatibility checked, v1 failure evidence preserved. | Does source text support each field within the declared profile, without confusing textual support with authentication? |
| [Composed hotel loop](05_代码与实验/examples/guarded_hotel_workflow.py) | Source and clean-install example checks complete under the existing simulator assumptions. | Does a grounding veto survive the adapter, and can a hold introduced after confirmation still prevent the actual mutation? |

Further experiments need a concrete unanswered question that could change a design decision or claim. Extra model calls, models or charts alone are not a reason to run them.

### Milestone submission checklist

- The [live project page](https://cqf.io/ARIN5203/project.html), checked on
  29 Oct, still requires 2–3 pages in the provided template, all three names,
  and one submitting member. Its template link currently opens CVPR 2026,
  despite the old `cvpr2022` URL slug.
- The student's [Canvas assignment list](https://canvas.ust.hk/courses/71916/assignments)
  had no Milestone item on 29 Oct; the earlier Gmail/Outlook and announcement
  checks had found no new submission notice. Recheck the live item before
  submission for allowed files, deadline/time zone and any attachment rules.
- Prepare the report PDF; do not upload it to Proposal or an Assignment item.
  No extra GitHub/ZIP/demo requirement is stated in the Milestone section.
  If the correct item remains unavailable near the deadline, contact the TA
  for a submission route; no message or submission has been sent automatically.
- The syllabus lists project sharing in Week 13, without a per-team duration
  or demo rule. Any internal timing plan remains provisional.

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
