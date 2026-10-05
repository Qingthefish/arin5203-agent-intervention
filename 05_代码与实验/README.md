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
- `src/platform_agent_eval/research_*.py` — grouped datasets, calibrated policies, uncertainty features, and formal metrics.
- `configs/` — immutable experiment plans and model settings.
- `scripts/` — plan-gated runners, audits, and plotting utilities.
- `tests/` — deterministic schema, leakage, state-transition, calibration, and compaction tests.
- `results/` — raw traces, summaries, manifests, audits, and figures from completed runs.

## Reproduction

Run from this directory with Python 3.12 or newer.

```bash
python3 -m unittest discover -s tests -v
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
python3 scripts/run_research_experiment.py --config configs/research_plan.json
```

The model runners are plan-only by default. They print the model, cases, expected calls, estimated resources, and output paths without contacting a model server. A real run requires both `--run` and `--acknowledge-experiment-plan`. Existing formal output prefixes cannot be overwritten.

Completed model experiments use local Ollama with `qwen3.5:9b`. No model weights, API keys, or company data are stored in the repository.

## Evidence and Artifact Sources

Exact experiment facts live in immutable artifacts rather than in this runbook:

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
- the versioned `pipeline_*` and `medium_*` artifacts for earlier intervention development runs.

Use the manifest for model identity, calls, timing, token use, prompt hashes, and claim scope; use the summary for aggregate metrics; use the audit for deterministic validity checks. `shortcut_causality_qwen_v1` was stopped by design review before any measured output and is non-citable; `v2` contains only a local sandbox-connection failure. Earlier intervention artifacts and compaction pilots are different development stages and must not be pooled as one frozen evaluation. The `research_v3` dataset is a source of state-changing operations and counterfactuals, not yet a final compaction benchmark.

The HITL v1 gate scores routes, not explanation faithfulness. A post-hoc independent review found recovery-related contradictions despite correct routes. The grounded v2--v4 gates therefore use a controlled factor ontology with cited evidence event IDs. The final authored-set prompt is frozen after v4: it passes route accuracy and grounding precision but fails decisive-factor recall and joint grounded route accuracy. Do not tune further on these nine scenarios or infer faithful reasoning from route score alone. The next runner must use structured evidence slots or deterministic link completion and new development cases.

The first atomic-slot smoke is also frozen after one run. Its end-to-end baseline was perfect on the nine new route proofs, while the slot extractor failed the pre-specified architecture gate. In particular, the model treated some slot values as booleans, some as opaque hold IDs, and sometimes omitted recovery or responder fields; exact linking therefore failed closed. Do not relax or reinterpret the v1 gold after observing these outputs. Any revised schema must use new cases and a new artifact prefix.

The fixed-budget v1 run is likewise frozen. All budgeted methods satisfy the exact target-model budget, but the six scenarios were used during earlier method development. Do not use the 6/6 versus 4/6 route counts as a final superiority claim, patch its four observed format errors and rescore the same outputs, or treat the unbudgeted full-history ceiling as a matched competitor. A stricter trace audit also found that the generic prompt was task-aware, summaries were mixed with raw-tail fill, method labels were visible, identifier patterns leaked into pinning, and one correct selective route hallucinated absent approval.

The subsequent protocol-falsification gate orthogonally separates summary intent and fill source, blinds condition labels, uses identifier-agnostic pinning, caches exact token counts, and requires visible event citations. Its first complete run (`v3`) failed only the pre-specified format-error limit because the router confused business identifiers with event IDs. A single interface-only retry (`v4`) exposed the exact valid-ID contract while leaving research conditions frozen and passed all instrumentation criteria. On the reused six-scenario set it achieved 53/54 correct routes but only 6/54 joint grounded routes, with 47 correct routes lacking complete grounding. The protocol is now ready for fresh matched siblings; the condition-level `v4` ordering is not held-out evidence and must not be used to claim method superiority.

The fresh matched-scratch v1 design uses one opaque-ID base per domain and three siblings per base: full evidence, one action-critical deletion, and one same-role/adjacent-position/length-matched noise deletion. Its completed `v2` launch passed the full/noise route and noise-invariance checks but failed the positive-deletion intervention and grounded-proof gates. Do not tune the router on these nine contexts or reinterpret the private gold after observing outputs. In particular, keep the financial hidden-hold execution as the intended negative-constraint-loss counterexample and the MAS Confirm/Handoff confusion as evidence for a separate audit-layer comparison.

The subsequent audit-increment set is separate fresh development data and is frozen after its completed `v2` launch. It compares Direct Router, deterministic Always Confirm, generic Prompt Critic, and candidate-conditioned Evidence Audit on exactly the same nine active contexts. Evidence Audit corrected one of five direct errors but spoiled two of four direct successes, retained two parser-valid harmful executions, and changed all three matched-noise sibling routes; it therefore failed the pre-specified gate. The post-hoc trace review additionally separates model intent from parser behavior: Direct and Evidence Audit each emitted three unsafe raw `AUTO_EXECUTE` decisions, while strict schema validation blocked one per method. Do not treat fail-closed parsing as faithful evidence reasoning, tune either reviewer on this set, or use these records to rank compaction strategies. A future verifier must hide the candidate conclusion and use new contexts.

The candidate-blind proof gate follows that requirement on another fresh nine-context set. It asks the model only for typed authority and recovery status, then maps those statuses to a route deterministically. The parsed pipeline reached 8/9 routes and corrected four of five Direct errors without spoiling a Direct success, but failed the frozen gate because it had four interface-format errors, only 4/9 joint decisive proofs, and one harmful execution. The interface-only post-hoc reparse allows empty citations for `UNKNOWN`, repairs all four format errors, and raises decisive proof to 6/9 without another model call; it still leaves the harmful execution in which a no-freeze clearance was misclassified as authority. Do not rerun or tune this set. Future work should replace free-text evidence typing with provenance-backed proof cards before returning to the exact-budget compaction comparison.

## Experimental Discipline

- Fix seeds and save configuration, prompt hashes, model identity, token use, and raw output.
- Keep counterfactual sibling cases in the same split.
- Select prompts, thresholds, and policies using development data only.
- Report failures and format fallbacks rather than silently dropping them.
- Do not run paid external APIs without explicit team approval.
- Cite every borrowed implementation and preserve its license notice where required.
