# Compaction Aware Agent Intervention Evaluation

This directory contains the reproducible simulator and local evaluation code for the ARIN 5203 project **Do AI Platform Agents Know What They Must Not Forget**.

## Current Research Question

Before an AI platform agent performs a state-changing operation, can a compaction-aware intervention pipeline preserve decision-critical context and choose `AUTO_EXECUTE`, `REQUEST_CONFIRMATION`, or `HANDOFF` with a better context-efficiency and human-burden trade-off than truncation, generic summarization, or fixed constraint pinning?

The current claim is deliberately limited. A five-scenario feasibility pilot shows that lossy compaction can remove critical facts and change downstream routing. It does not yet establish a safety improvement or generalization result.

## System Boundary

The evaluation has two connected layers:

1. **Context management** removes recoverable tool noise, preserves explicit constraints, and optionally asks for human clarification when validity, authority, or expiry is ambiguous.
2. **Pre-action intervention** applies deterministic hard guards and a model-assisted router before a state-changing tool call. A simulator then evaluates the actual state transition rather than treating agreement with a route label as safety.

Gold decisions, private approval requirements, and oracle conclusions remain outside model-visible `PolicyInput`. A confirmation can repair only a genuinely resolvable information gap; it cannot override malformed, forbidden, operator-only, or no-recovery conditions.

## Repository Map

- `src/platform_agent_eval/compaction*.py` — compaction scenarios, strategies, prompts, and metrics.
- `src/platform_agent_eval/simulator.py` and `domain.py` — stateful AI platform environment and state-diff oracle.
- `src/platform_agent_eval/approvals.py` and `intervention.py` — scoped evidence and three-way routing semantics.
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
python3 scripts/run_research_experiment.py --config configs/research_plan.json
```

The model runners are plan-only by default. They print the model, cases, expected calls, estimated resources, and output paths without contacting a model server. A real run requires both `--run` and `--acknowledge-experiment-plan`. Existing formal output prefixes cannot be overwritten.

Completed model experiments use local Ollama with `qwen3.5:9b`. No model weights, API keys, or company data are stored in the repository.

## Evidence That Can Be Cited

### Compaction feasibility pilot

- Five authored scenarios and five strategies.
- 35 measured local generations plus one warm-up.
- 248.98 seconds; 24,395 prompt tokens; 2,062 completion tokens; external API cost `$0`.
- Tail truncation retained 25% of exact critical markers and achieved 60% route accuracy.
- Generic summarization reduced context by 84.8% but changed one `HANDOFF` case to `REQUEST_CONFIRMATION`.
- Broad rule pinning preserved every marker but reduced context by only 0.24%.
- Selective HITL preserved every marker, reduced context by 47.0%, and asked one simulated expiry question.
- No strategy produced a harmful execution in this five-case pilot. These results justify further evaluation, not a safety-superiority claim.

Primary artifacts use the prefix `compaction_pilot_qwen_v1`.

### Proposal-alignment pilot

- Six synthetic scenarios: two platform approval/rollback cases, two financial-style entity/amount/validity cases, and two main/sub-agent authority-boundary cases.
- 42 measured local generations plus one warm-up; 317.25 seconds.
- 30,682 prompt tokens; 2,704 completion tokens; zero format errors; external API cost `$0`.
- Full context, generic summarization, and selective context management each achieved 100% route accuracy.
- Tail truncation and the current keyword-pinning baseline each achieved 66.7% route accuracy; neither caused a harmful execution.
- Generic summarization reduced context by 84.4%. Selective context management reduced it by 46.0% while preserving all exact critical markers.
- The keyword rule reduced context by only 1.8% because boilerplate noise contained words such as `authority`, `ownership`, and `recovery`; it is not yet a strong pinning baseline.
- Selective context management requested review twice, but neither request matched an answerable event, so this run does not demonstrate incremental HITL value.

Primary artifacts use the prefix `proposal_alignment_qwen_v1`. A scenario-set-specific deterministic audit replaced an inapplicable five-case recommendation after the run; the raw traces and summary were not changed.

### Earlier intervention development runs

The earlier pipeline, model, expanded, scoped, and calibrated artifacts are retained as development history. They established the simulator, exposed a consent-like shortcut, motivated scoped raw approval evidence, and tested train/dev/test plumbing. They are not independent final-test results and should not be combined with the compaction pilot as if they came from one frozen protocol.

The 40-family / 120-case `research_v3` dataset remains useful as a source of state-changing operations and approval counterfactuals. It must be adapted and re-split before it becomes the formal compaction benchmark.

## Next Development Gate

The next run is a 20-task development pilot, not the final experiment. Before it runs, the dataset must add:

- approval scope, expiry, negation, ownership, entity, amount, and change evidence;
- main-agent to sub-agent handoff cases;
- recoverable versus non-recoverable tool outputs;
- structured fact-oracle scoring in addition to exact-string markers;
- both precise and deliberately broad pinning baselines;
- matched pairs where one short human answer changes the safe action, plus non-answerable handoff controls;
- retained-context budgets so reliability can be compared at similar compression levels.

If the expanded pilot still shows routing degradation but no harmful mutations, the report will frame the contribution as compaction fidelity, safe autonomy, and intervention efficiency rather than claiming a demonstrated safety improvement.

## Experimental Discipline

- Fix seeds and save configuration, prompt hashes, model identity, token use, and raw output.
- Keep counterfactual sibling cases in the same split.
- Select prompts, thresholds, and policies using development data only.
- Report failures and format fallbacks rather than silently dropping them.
- Do not run paid external APIs without explicit team approval.
- Cite every borrowed implementation and preserve its license notice where required.
