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
- the versioned `pipeline_*` and `medium_*` artifacts for earlier intervention development runs.

Use the manifest for model identity, calls, timing, token use, prompt hashes, and claim scope; use the summary for aggregate metrics; use the audit for deterministic validity checks. `shortcut_causality_qwen_v1` was stopped by design review before any measured output and is non-citable; `v2` contains only a local sandbox-connection failure. Earlier intervention artifacts and compaction pilots are different development stages and must not be pooled as one frozen evaluation. The `research_v3` dataset is a source of state-changing operations and counterfactuals, not yet a final compaction benchmark.

The HITL v1 gate scores routes, not explanation faithfulness. A post-hoc independent review found recovery-related contradictions despite correct routes. The grounded v2--v4 gates therefore use a controlled factor ontology with cited evidence event IDs. The final authored-set prompt is frozen after v4: it passes route accuracy and grounding precision but fails decisive-factor recall and joint grounded route accuracy. Do not tune further on these nine scenarios or infer faithful reasoning from route score alone. The next runner must use structured evidence slots or deterministic link completion and new development cases.

## Experimental Discipline

- Fix seeds and save configuration, prompt hashes, model identity, token use, and raw output.
- Keep counterfactual sibling cases in the same split.
- Select prompts, thresholds, and policies using development data only.
- Report failures and format fallbacks rather than silently dropping them.
- Do not run paid external APIs without explicit team approval.
- Cite every borrowed implementation and preserve its license notice where required.
