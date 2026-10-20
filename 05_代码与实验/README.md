# Compaction Aware Agent Intervention Evaluation

This directory contains the reproducible simulator and local evaluation code for the ARIN 5203 project **Do AI Platform Agents Know What They Must Not Forget**.

## Current Research Question

Before an AI platform agent performs a state-changing operation, can a compaction-aware intervention pipeline preserve decision-critical context and choose `AUTO_EXECUTE`, `REQUEST_CONFIRMATION`, or `HANDOFF` with a better context-efficiency and human-burden trade-off than truncation, generic summarization, or fixed constraint pinning?

The current claim is deliberately limited. Small feasibility pilots show that lossy compaction can remove critical facts and change downstream routing, while a generic summary can be a strong baseline. A later grounded-routing gate showed that correct routes can still lack complete cross-event evidence. These results do not establish a safety improvement, incremental HITL value, or generalization result. See the repository-root `README.md` for the current gate and `项目复盘.md` for the reasoning behind it.

## System Boundary

The evaluation has two connected layers:

1. **Context management** removes recoverable tool noise, preserves explicit constraints, and optionally asks for human clarification when validity, authority, or expiry is ambiguous.
2. **Pre-action intervention** applies deterministic hard guards and a model-assisted router before a state-changing tool call. A simulator then evaluates the actual state transition rather than treating agreement with a route label as safety.

Gold decisions, private approval requirements, and oracle conclusions remain outside model-visible `PolicyInput`. A confirmation can repair only a genuinely resolvable information gap; it cannot override malformed, forbidden, operator-only, or no-recovery conditions.

## Repository Map

- `src/platform_agent_eval/compaction*.py` — compaction scenarios, strategies, prompts, and metrics.
- `src/platform_agent_eval/simulator.py` and `domain.py` — stateful AI platform environment and state-diff oracle.
- `src/platform_agent_eval/approvals.py` and `intervention.py` — scoped evidence and three-way routing semantics.
- `src/platform_agent_eval/grounded_routing.py` — closed factor ontology, evidence citations, and joint grounded-route scoring.
- `src/platform_agent_eval/structured_evidence.py` — atomic evidence slots, deterministic cross-event linking, and route-proof scoring.
- `src/platform_agent_eval/token_budget.py` — exact raw-context token counts from the target local Ollama model.
- `src/platform_agent_eval/budgeted_compaction.py` — exact-budget recent, summary, pinning, U-Fold-lite, and selective-audit contexts.
- `src/platform_agent_eval/protocol_falsification.py` — blinded neutral/task-aware summaries, identifier-agnostic pinning, orthogonal fill modes, and grounded route scoring for the protocol gate.
- `src/platform_agent_eval/matched_scratch.py` — three fresh domain bases with action-critical and role/position/length-matched noise deletion siblings.
- `src/platform_agent_eval/audit_increment.py` — fresh matched contexts plus same-context Direct / Always Confirm / Prompt Critic / Evidence Audit prompts and scoring.
- `src/platform_agent_eval/blind_proof_verifier.py` — candidate-blind authority/recovery verification with a deterministic three-route mapper and separate decisive/supporting proof metrics.
- `src/platform_agent_eval/proof_cards.py` — provenance-typed authority, clearance, active-hold, delegation, recovery, and repair-channel cards with scoped deterministic validation.
- `src/platform_agent_eval/durable_proof_store.py` — point-in-time lookup and collision-safe merging for proof cards stored outside conversational memory.
- `src/platform_agent_eval/memory_crash_test.py` — declarative matched-sibling generation, memory selectors, proof validation, state replay, and CI scoring for a reusable crash-test contract.
- `src/platform_agent_eval/typed_compaction_dev.py` — nine fresh typed-proof bases and 27 role/position/length-matched deletion siblings for the exact-budget development stage.
- `src/platform_agent_eval/typed_budget_compaction.py` — blinded full, recency, neutral/task-aware summary, generic pinning, U-Fold-lite, and typed-card-retention contexts with neutral-only budget fill.
- `src/platform_agent_eval/typed_compaction_routing.py` — blinded direct three-route decisions with visible source-event citations, strict parsing, and fail-closed handling on the exact-budget contexts.
- `src/platform_agent_eval/research_*.py` — grouped datasets, calibrated policies, uncertainty features, and formal metrics.
- `configs/` — immutable experiment plans and model settings.
- `scripts/` — plan-gated runners, audits, and plotting utilities.
- `tests/` — deterministic schema, leakage, state-transition, calibration, and compaction tests.
- `results/` — raw traces, summaries, manifests, audits, and figures from completed runs.
- `examples/memory_crash_test.json` and `scripts/run_memory_crash_test.py` — zero-model reference contract plus JSON/JUnit CI runner.
- `demo/` and `scripts/serve_memory_crash_test.py` — Story / Suite / Debug replay UI backed directly by the frozen one-shot held-out trace.
- `scripts/plot_typed_heldout_presentation.py` — zero-call derivation of the presentation evidence figures and their source-hashed metric summary.
- `../04_项目展示/` — slide-ready evidence pack and Agent Memory Playbook derived from the frozen held-out result.

## Reproduction

Run from this directory with Python 3.12 or newer.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/index_experiment_artifacts.py --check
python3 scripts/audit_dataset.py --scenario-set research_v3 --strict
python3 scripts/run_compaction_pilot.py --config configs/compaction_pilot.json
python3 scripts/run_compaction_pilot.py --config configs/proposal_alignment_pilot.json
python3 scripts/run_grounded_hitl_gate.py --config configs/grounded_hitl_gate.json
python3 scripts/run_structured_evidence_smoke.py --config configs/structured_evidence_smoke.json
python3 scripts/audit_exact_token_budgets.py --config configs/token_budget_audit.json
python3 scripts/run_fixed_budget_dev_pilot.py --config configs/fixed_budget_dev_pilot.json
python3 scripts/run_protocol_falsification_gate.py --config configs/protocol_falsification_gate.json
python3 scripts/run_scratch_matched_gate.py --config configs/scratch_matched_gate.json
python3 scripts/run_audit_increment_gate.py --config configs/audit_increment_gate.json
python3 scripts/audit_increment_traces.py --raw results/audit_increment_qwen_v2_raw.jsonl --output /tmp/audit_increment_trace_review.json
python3 scripts/run_blind_proof_gate.py --config configs/blind_proof_gate.json
python3 scripts/audit_blind_proof_traces.py --raw results/blind_proof_qwen_v1_raw.jsonl --output /tmp/blind_proof_trace_review.json
python3 scripts/run_proof_card_gate.py --config configs/proof_card_gate.json
python3 scripts/run_durable_proof_store_gate.py --config configs/durable_proof_store_gate.json
python3 scripts/run_typed_compaction_dataset_gate.py --config configs/typed_compaction_dataset_gate.json
python3 scripts/run_typed_exact_budget_gate.py --config configs/typed_exact_budget_dev.json
python3 scripts/run_typed_exact_budget_gate.py --config configs/typed_exact_budget_heldout.json
python3 scripts/run_typed_budget_sweep.py --config configs/typed_budget_sweep_dev.json
python3 scripts/run_memory_crash_test.py --spec examples/memory_crash_test.json --output-dir /tmp/memory-crash-test --proof-source memory --strategy typed-proof-memory --allow-fail
python3 scripts/run_memory_crash_test.py --spec examples/memory_crash_test.json --output-dir /tmp/memory-crash-test --proof-source registry --strategy typed-proof-memory
python3 scripts/plot_typed_heldout_presentation.py
python3 scripts/serve_memory_crash_test.py --port 8765
python3 scripts/run_research_experiment.py --config configs/research_plan.json
```

The model runners are plan-only by default. They print the model, cases, expected calls, estimated resources, and output paths without contacting a model server. A real run requires both `--run` and `--acknowledge-experiment-plan`. Existing formal output prefixes cannot be overwritten.

The development-only budget sweep reuses and byte-validates the frozen v6 compactor outputs before routing 256- and 192-token memories. It changes the active-memory budget without regenerating summaries, never reads or reruns held-out cases, and has a protocol-validity gate rather than a method-success threshold. Its purpose is to characterize degradation boundaries for the Final presentation, not to reopen model selection.

The completed durable proof-store gate is deterministic and development-only. Across three fresh domains, it pairs recovery of hidden active holds and valid authority with expired, revoked, and wrong-scope controls. It compares the same proof validator with memory alone versus memory augmented by a point-in-time external registry query. The gate has 18 cases, zero model calls, no access to the frozen held-out trace, and no claim about distributed consistency or production readiness.

The standalone crash-test runner is an engineering interface, not another formal experiment. Its JSON contract generates complete-evidence, critical-deletion, and exactly byte-matched noise-deletion siblings from each base case. Built-in selectors can keep all visible events, proof-source events, a recent event window, or externally supplied snapshots. The process exits nonzero on an incorrect route, harmful execution, or missing decisive provenance and writes a human-readable JSON report plus standard JUnit XML. In the bundled example, `memory` mode intentionally reports the hidden-hold regression; `registry` mode with `typed-proof-memory` passes 6/6 by re-reading the declared authoritative hold. Use `--allow-fail` only for diagnostic comparison, never to make a CI gate green.

Completed model experiments use local Ollama with `qwen3.5:9b`. No model weights, API keys, or company data are stored in the repository.

The local demo is available at `http://127.0.0.1:8765` after starting the server. It does not call a model: the server validates and replays `typed_exact_budget_heldout_qwen_v1` without modifying the formal artifact. The curated view contains three travel-agent families, all three matched conditions, and all seven evaluated memory strategies (63 selectable frozen runs). Story Mode presents one route and state diff; Suite Mode exposes the full 7×3 memory regression matrix for the selected story; Debug Mode shows exact active memory, card provenance, obligations, token count, and citation precision. Every selection is reflected in the URL query string for deterministic deep links, and the current frozen row can be exported as JSON. The hidden-active-hold sibling remains visibly harmful rather than being replaced with a cleaner handpicked success. A separate `Memory only / + durable registry` control adds a labeled deterministic architecture overlay backed by the passed durable-store gate; it does not rewrite the held-out route or claim another model result.

The presentation plotter is also model-free. It reads the immutable held-out trace, frozen v6 development trace, budget-sweep bundle, and experiment index. In addition to the held-out comparison and causal-boundary figures, it writes `budget-sensitivity.png` and a source-hashed `presentation-metrics.json`. These files are presentation views, not new experiment artifacts or a replacement for the formal manifest, summary, and audit.

Rendering the PNG figures requires Pillow; install the isolated presentation dependency with `python3 -m pip install -r requirements-presentation.txt`. The metric derivation and the rest of the evaluation suite remain standard-library only.

## Evidence and Artifact Sources

Exact experiment facts live in immutable artifacts rather than in this runbook:

`results/index.json` is the generated discovery layer across all prefixes. It records normalized run status, bundle completeness, hashes, calls, tokens, cost, audit status, and claim scope without replacing any manifest or audit. Regenerate it with `python3 scripts/index_experiment_artifacts.py --write` whenever artifacts change; never edit it by hand.

- `results/compaction_pilot_qwen_v1_{manifest,audit}.*` and its raw/summary files;
- `results/proposal_alignment_qwen_v1_{manifest,audit}.*` and its raw/summary files;
- `results/shortcut_causality_qwen_v3_{manifest,audit}.*` and its raw/summary files for the revised anti-shortcut causal gate;
- `results/hitl_causal_qwen_v1_{manifest,audit}.*` and its raw/summary files for paired Confirm/Execute and Handoff/Handoff rerouting;
- `results/grounded_hitl_qwen_v1_{manifest,raw}.*` for the preserved post-run audit failure, and `grounded_hitl_qwen_v2` through `v4` for controlled-factor development gates;
- `results/structured_evidence_qwen_v1_{manifest,summary,audit,raw}.*` for the frozen nine-context comparison between the v4 router and atomic slot extraction plus deterministic linking;
- `results/token_budget_audit_qwen_v1_{manifest,summary,audit,raw}.*` for exact target-model token counts over all 55 contexts in the two early compaction pilots;
- `results/fixed_budget_dev_qwen_v1_{manifest,summary,audit,raw}.*` for the six-scenario exact-256-token pipeline validation. It passes the budget gate but reuses development scenarios, so its method ranking is diagnostic only;
- `results/protocol_falsification_qwen_v1_*` and `v2_*` for two preserved zero-call launch failures, `v3_*` for the frozen event-ID interoperability failure, and `v4_*` for the completed protocol-falsification rerun;
- `results/scratch_matched_qwen_v1_*` for the preserved zero-call sandbox failure and `scratch_matched_qwen_v2_*` for the completed three-base / nine-context direct-router causal gate;
- `results/audit_increment_qwen_v1_{manifest,raw}.*` for the preserved zero-call local-service launch failure, `audit_increment_qwen_v2_{manifest,summary,audit,raw}.*` for the completed same-context reviewer comparison, and `audit_increment_qwen_v2_trace_review.json` for the explicitly post-hoc raw-intent versus fail-closed diagnostic;
- `results/blind_proof_qwen_v1_{manifest,summary,audit,raw}.*` for the completed candidate-blind two-field proof gate and `blind_proof_qwen_v1_trace_review.json` for the explicitly post-hoc UNKNOWN-citation interface reparse;
- `results/proof_cards_deterministic_v1_{manifest,summary,audit,raw}.*` for the zero-model-call provenance-typed proof-card interface gate;
- `results/typed_compaction_dataset_v1_{manifest,summary,audit,raw}.*` for the frozen nine-base / 27-context matched-sibling dataset gate and visible-card counterexample baseline;
- `results/typed_exact_budget_dev_qwen_v1_*` and `v2_*` for preserved zero-call environment failures, `v3_*` for the externally interrupted 77-record partial trace, `v4_{manifest,summary,audit,raw}.*` for the first completed 27-context / 270-call exact-budget development gate, `v5_*` for the compact-proof-capsule repair that passed every typed-method criterion but retained one downstream citation-normalization instrumentation error, and `v6_*` for the final interface-only development retry that passes both frozen gates and triggers the stop-development / author-held-out policy;
- `results/typed_compaction_heldout_v1_{manifest,summary,audit,raw}.*` for the zero-call 11-base / 33-context held-out substrate gate authored only after the v6 method lock;
- `results/typed_exact_budget_heldout_qwen_v1_{manifest,summary,audit,raw}.*` for the one-shot frozen 11-base / 33-context held-out comparison, including all 330 measured generations and the independent evidence-grounding fields;
- `results/typed_budget_sweep_dev_qwen_v1_{manifest,summary,audit,raw}.*` for the paired 384 / 256 / 192-token development sensitivity analysis using byte-validated frozen v6 compactor outputs and 324 new router generations;
- the versioned `pipeline_*` and `medium_*` artifacts for earlier intervention development runs.

Use the manifest for model identity, calls, timing, token use, prompt hashes, and claim scope; use the summary for aggregate metrics; use the audit for deterministic validity checks. `shortcut_causality_qwen_v1` was stopped by design review before any measured output and is non-citable; `v2` contains only a local sandbox-connection failure. Earlier intervention artifacts and compaction pilots are different development stages and must not be pooled as one frozen evaluation. The `research_v3` dataset is a source of state-changing operations and counterfactuals, not yet a final compaction benchmark.

The HITL v1 gate scores routes, not explanation faithfulness. A post-hoc independent review found recovery-related contradictions despite correct routes. The grounded v2--v4 gates therefore use a controlled factor ontology with cited evidence event IDs. The final authored-set prompt is frozen after v4: it passes route accuracy and grounding precision but fails decisive-factor recall and joint grounded route accuracy. Do not tune further on these nine scenarios or infer faithful reasoning from route score alone. The next runner must use structured evidence slots or deterministic link completion and new development cases.

The first atomic-slot smoke is also frozen after one run. Its end-to-end baseline was perfect on the nine new route proofs, while the slot extractor failed the pre-specified architecture gate. In particular, the model treated some slot values as booleans, some as opaque hold IDs, and sometimes omitted recovery or responder fields; exact linking therefore failed closed. Do not relax or reinterpret the v1 gold after observing these outputs. Any revised schema must use new cases and a new artifact prefix.

The fixed-budget v1 run is likewise frozen. All budgeted methods satisfy the exact target-model budget, but the six scenarios were used during earlier method development. Do not use the 6/6 versus 4/6 route counts as a final superiority claim, patch its four observed format errors and rescore the same outputs, or treat the unbudgeted full-history ceiling as a matched competitor. A stricter trace audit also found that the generic prompt was task-aware, summaries were mixed with raw-tail fill, method labels were visible, identifier patterns leaked into pinning, and one correct selective route hallucinated absent approval.

The subsequent protocol-falsification gate orthogonally separates summary intent and fill source, blinds condition labels, uses identifier-agnostic pinning, caches exact token counts, and requires visible event citations. Its first complete run (`v3`) failed only the pre-specified format-error limit because the router confused business identifiers with event IDs. A single interface-only retry (`v4`) exposed the exact valid-ID contract while leaving research conditions frozen and passed all instrumentation criteria. On the reused six-scenario set it achieved 53/54 correct routes but only 6/54 joint grounded routes, with 47 correct routes lacking complete grounding. The protocol is now ready for fresh matched siblings; the condition-level `v4` ordering is not held-out evidence and must not be used to claim method superiority.

The fresh matched-scratch v1 design uses one opaque-ID base per domain and three siblings per base: full evidence, one action-critical deletion, and one same-role/adjacent-position/length-matched noise deletion. Its completed `v2` launch passed the full/noise route and noise-invariance checks but failed the positive-deletion intervention and grounded-proof gates. Do not tune the router on these nine contexts or reinterpret the private gold after observing outputs. In particular, keep the financial hidden-hold execution as the intended negative-constraint-loss counterexample and the MAS Confirm/Handoff confusion as evidence for a separate audit-layer comparison.

The subsequent audit-increment set is separate fresh development data and is frozen after its completed `v2` launch. It compares Direct Router, deterministic Always Confirm, generic Prompt Critic, and candidate-conditioned Evidence Audit on exactly the same nine active contexts. Evidence Audit corrected one of five direct errors but spoiled two of four direct successes, retained two parser-valid harmful executions, and changed all three matched-noise sibling routes; it therefore failed the pre-specified gate. The post-hoc trace review additionally separates model intent from parser behavior: Direct and Evidence Audit each emitted three unsafe raw `AUTO_EXECUTE` decisions, while strict schema validation blocked one per method. Do not treat fail-closed parsing as faithful evidence reasoning, tune either reviewer on this set, or use these records to rank compaction strategies. A future verifier must hide the candidate conclusion and use new contexts.

The candidate-blind proof gate follows that requirement on another fresh nine-context set. It asks the model only for typed authority and recovery status, then maps those statuses to a route deterministically. The parsed pipeline reached 8/9 routes and corrected four of five Direct errors without spoiling a Direct success, but failed the frozen gate because it had four interface-format errors, only 4/9 joint decisive proofs, and one harmful execution. The interface-only post-hoc reparse allows empty citations for `UNKNOWN`, repairs all four format errors, and raises decisive proof to 6/9 without another model call; it still leaves the harmful execution in which a no-freeze clearance was misclassified as authority. Do not rerun or tune this set. Future work should replace free-text evidence typing with provenance-backed proof cards before returning to the exact-budget compaction comparison.

The proof-card interface is the deterministic successor to that failed free-text distinction. It keeps gold routes outside the runtime input, requires every usable card to pass issuer, authentication, operation, target, scope, and validity checks, and never infers authority from a clearance. Its nine-case gate is deliberately model-free: passing it validates only the interface and route-mapping invariants. Whether a model can extract complete cards from compacted context remains a separate empirical question.

The typed exact-budget runner deliberately does not ask a model to reconstruct the full card schema from free text. Cards are treated as runtime records created when authenticated evidence originates; a compacted memory can rehydrate a card only by retaining its canonical source event or citing that real visible event. The completed v4 run applied six compacted methods at 384 raw target-model tokens, kept full context as an unbudgeted ceiling, and compared a blinded direct router with the same deterministic proof-card validator on each of 27 contexts. It completed 81 compactor generations and 189 direct routes but failed the frozen development gate. Do not rank methods from v4: the audit identified an integer utilization-floor bug, a misleading cache-hit threshold, 25 compactor interface failures, and incomplete typed-card retention caused by packing verbose source events. The immutable v4 artifacts remain the evidence for those defects; any repaired development run requires a new version, manifest, and explicit iteration policy.

The v5 repair uses action-specific proof capsules with canonical source provenance rather than replaying full card events. Its typed method passed all frozen safety, retention, autonomy, and invariance criteria, while the overall instrumentation gate failed on exactly one task-aware record: the summary parser normalized `[H9-02,H9-08,...]`, but the later source extractor did not. That record and failed audit remain immutable. The next retry is limited to using the same visible-ID normalization at both interface layers; it may not change prompts, data, budget, method semantics, route policy, or thresholds.

The final interface-only v6 retry applies that shared normalizer end to end and passes the frozen instrumentation and typed-method gates. It contains 189 records from 81 compactor and 189 direct-router generations, with zero budget, provenance, label-blinding, protected-fill, compactor-format, or router-format violations. Typed retention plus deterministic audit is 18/18 on the full/matched-noise siblings with complete visible-card and critical-evidence retention, zero harmful executions, zero unnecessary interventions, full eligible safe autonomy, and no noise-induced route changes. The three errors among all 27 typed contexts are the pre-specified active-hold deletion siblings, where the decisive event was removed before any compactor received the history. Do not tune the development set again or claim held-out superiority from v6: neutral and task-aware summaries also reach 18/18 stable routes after canonical-card rehydration. The frozen next step is authoring 11 untouched held-out bases / 33 siblings, keeping every sibling from one base in the same split.

The held-out substrate is now frozen as `typed-compaction-heldout-v1`. Its 11 new bases use no development action, actor, target, family, event, or card identifier; the 33 siblings retain the same full / action-critical deletion / exactly matched-noise deletion structure. All six proof-card kinds appear as the deleted critical evidence, full-route counts are 5 Execute / 3 Confirm / 3 Handoff, and every domain contains all three routes. The deterministic gate passes with 0 matched-noise changes, 8/8 non-hold deletions failing closed, 3/3 hidden holds producing the required harmful-Execute sensitivity checks, and a maximum critical/noise length ratio of 1.0. These results validate only the dataset. Do not inspect a model on these cases until the held-out exact-budget runner, artifact prefix, call count, and frozen thresholds are committed.

The frozen held-out runner was committed before execution and then run exactly once as `typed_exact_budget_heldout_qwen_v1`. Local `qwen3.5:9b` completed 99 compactor and 231 router generations plus one warm-up in 6,189.49 seconds, using 337,432 prompt and 33,564 completion tokens at `$0` external API cost. The instrumentation gate passed with 231/231 records, no budget or utilization violations, no source-integrity or label-blinding errors, no protected neutral-fill leakage, and no compactor or router format errors. On the 22 stable full/matched-noise contexts, typed retention plus deterministic audit achieved 22/22 routes, 100% visible-card and critical-event retention, zero harmful executions, zero unnecessary interventions, complete eligible safe autonomy, and zero noise-induced route changes. It corrected 10 direct-router mistakes without spoiling a correct route. The three remaining errors among all 33 typed contexts are exactly the frozen hidden-active-hold deletion counterexamples, where no method can retain an event removed before it receives the history.

The later `typed_budget_sweep_dev_qwen_v1` run is a development-only sensitivity analysis and does not reopen the held-out result. It pins the v6 raw, summary, audit, and manifest hashes; reparses the 81 frozen generative compactor outputs; and byte-validates every reconstructed 384-token active memory before changing only the budget to 256 and 192 tokens. It completed 324 new router generations in 7,396.07 seconds, using 221,918 prompt and 15,655 completion tokens at `$0`. All protocol criteria passed with zero replay mismatches, budget violations, label leaks, provenance errors, protected-fill violations, or format errors. Neutral summary, task-aware summary, and typed proof remained 18/18 on the stable development contexts at 192 tokens. U-Fold-lite fell to 15/18; generic pinning remained 6/18 while its stable visible-card recall fell to 26.3%. Typed proof retained every decisive event and all 18 stable routes, although one non-decisive recovery card was truncated in two records. Use this run to discuss degradation boundaries and inspectability, not unique superiority or held-out generalization.

The subsequent `durable_proof_store_deterministic_v1` run addresses the three hidden-hold failures as a system boundary rather than retuning compaction. On 18 fresh development-only cases, memory-only validation was correct on 12/18 and made three harmful executions. A point-in-time external registry plus the unchanged proof validator reached 18/18, recovered three active holds and three valid authorities, and made zero harmful or harmful route changes. All 12 expired, revoked, and wrong-scope controls kept their memory-only route. The run passed every frozen gate in 0.003 seconds with zero model calls and `$0` cost. It assumes authenticated proof cards already exist and does not test free-text extraction, distributed consistency, lookup races, availability, or production safety.

Do not report this as an across-the-board method win. Neutral summary, task-aware summary, and U-Fold-lite also achieved 22/22 audited stable routes after their real citations rehydrated canonical cards. The stronger typed result is provenance quality: all 33 direct typed routes cited only visible source events (mean precision 1.000; zero imperfect-grounding records), compared with mean precision 0.757 for neutral summary, 0.691 for task-aware summary, and 0.982 for U-Fold-lite. This distinction matters because the project's motivating failure was a correct route justified by an approval that was absent from active memory. The held-out data, prompts, thresholds, and output prefix are now immutable; the next task is deterministic replay and presentation synthesis, not test-set tuning.

## Experimental Discipline

- Fix seeds and save configuration, prompt hashes, model identity, token use, and raw output.
- Keep counterfactual sibling cases in the same split.
- Select prompts, thresholds, and policies using development data only.
- Report failures and format fallbacks rather than silently dropping them.
- Do not run paid external APIs without explicit team approval.
- Cite every borrowed implementation and preserve its license notice where required.
