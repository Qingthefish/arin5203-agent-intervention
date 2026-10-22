# ARIN 5203 Course Project

**Do AI Platform Agents Know What They Must Not Forget?**<br>
**Compaction-Aware Intervention Before State-Changing Operations**

Building an Agent from 0 to 1 is increasingly accessible. Keeping it reliable over long histories requires knowing which evidence must survive before its next tool changes external state. This project compares memory strategies under a fixed raw-token budget, checks action-specific proof, and evaluates Execute / Confirm / Handoff through a deterministic simulator.

## Team

- **Qingcheng Yu** — agent product design, intervention policy, evaluation and presentation.
- **Siu Kwun Yeung** — enterprise multi-agent workflows, verification, review and control requirements.
- **Qingyin Guo** — agent application prototypes, tools/APIs and orchestration.

These are primary responsibilities; scenario review, implementation and final conclusions are shared. Team experience motivates synthetic cases, not claims about company production systems.

## Current Snapshot — 2026-10-23

| Workstream | Status | Evidence or entry point |
| --- | --- | --- |
| Proposal | Submitted; 92/100. No attributable instructor explanation for the deduction was found. | [Proposal files](01_提案/) |
| Core evaluation | Development protocol frozen; one-shot held-out evaluation complete. | [Held-out audit](05_代码与实验/results/typed_exact_budget_heldout_qwen_v1_audit.json) |
| Additional evidence | Development budget sweep and deterministic durable-store test complete. | [Experiment index](05_代码与实验/results/index.json) |
| Milestone | Two-page progress snapshot prepared; submission entry must be checked before submitting. | [PDF](02_里程碑/Project_Milestone_Yu_Yeung_Guo.pdf), [LaTeX source](02_里程碑/milestone.tex) |
| Presentation | Replay and seven evidence figures available; claim/metric interpretation reviewed. Team hand-builds PPT. | [Presentation guide](04_项目展示/README.md), [Playbook](04_项目展示/Agent_Memory_Playbook.md) |
| Reusable toolkit | Public research preview; contract-validation hardening is in patch v0.1.1. | [Standalone repository](https://github.com/Qingthefish/agent-memory-crash-test) |
| Natural-language extension | PR #1 merged with interface repairs; dataset and plan-only runner available, no model result yet. | [Runbook](05_代码与实验/README.md#natural-language-evidence-extension), [PR #1](https://github.com/Qingthefish/arin5203-agent-intervention/pull/1) |
| Final report | Evidence exists; the full report still needs to be written and assembled. | [Research rationale and claim boundaries](项目复盘.md) |

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
| Evidence creation | Main evaluation starts from source-linked typed records. | Reliable free-text extraction and real signature verification. PR #1 targets the first gap. |
| Memory and audit | Retained source IDs permit the deterministic audit to rehydrate canonical records. The fixed budget applies to active memory. | Total external storage, lookup overhead and a fully self-contained compressed-memory system. |
| Action outcome | Main frozen scores use an authored unsafe-if-executed flag plus the released route. The later replay/toolkit applies a declared simulated transition to show the state diff. | Independent live-domain outcome validation, real bookings, transfers or production deployments. |
| Human intervention | Route semantics distinguish a repairable answer from a required handoff. | A deployed human workflow, user study or measured production intervention burden. |
| Generalization | Frozen methods were evaluated once on separately authored synthetic families. | Broad model/domain generalization or production safety certification. |

The engineering takeaway is to treat conversational memory as a cache and validate authoritative action proof at the tool boundary. A passing test does not replace an authorization service.

The [related-work review](05_代码与实验/docs/related-work.md) distinguishes borrowed mechanisms from this project's integration. The [integration guide](05_代码与实验/docs/integration.md) maps current provider hooks to the application-owned proof boundary; it also explains why opaque compaction is not covered by a retained-ID snapshot alone.

## Next Work and Stopping Rule

The core experimental question is answered at course-project scale. The remaining required work is to turn that evidence into a clear Final report and the team's hand-made slides. The 2026-10-23 review corrects interpretation, not frozen scores or method selection; its source-existence recount is explicitly post-hoc.

One optional experiment remains justified: a small **development-only natural-language extraction diagnostic**, covering all three domains and Execute / Confirm / Handoff with clean and distractor variants. Freeze its selection, prompt, scoring and output prefix before a model run. Measure extraction fidelity and downstream mistakes. A successful diagnostic would support a larger end-to-end follow-up; failure would define the boundary to report. Neither outcome changes the original frozen held-out result.

Further experiments need a concrete unanswered question that could change a design decision or claim. Extra model calls, models or charts alone are not a reason to run them.

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
- `01_提案/`, `02_里程碑/`, `04_项目展示/` — course deliverables and presentation evidence.
- `CVPR2026_模板源码/` — instructor-linked vendor template; its README is not project documentation.

The [course repository](https://github.com/Qingthefish/arin5203-agent-intervention) contains the research archive and latest development. The [standalone toolkit](https://github.com/Qingthefish/agent-memory-crash-test) publishes reviewed, versioned package snapshots; it does not automatically inherit every experimental extension.

Pull current `main`, create a focused branch, preserve immutable outputs, and use a PR for teammate contributions. Keep credentials, private company material, model weights and unrelated coursework out of commits. One team member submits each course deliverable with all three names. Recheck the live course instructions at submission time.
