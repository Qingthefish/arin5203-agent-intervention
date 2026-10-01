# AI Platform Agent Intervention Evaluation

This directory contains the reproducible local simulator for the ARIN 5203 course project. The current deterministic smoke test validates schemas, policy-input/gold-label separation, state transitions, safety checks, baselines, split handling, and metrics without calling any model API.

Run from this directory with Python 3.12 or newer:

```bash
python3 scripts/run_mock_pilot.py
python3 -m unittest discover -s tests -v
python3 scripts/run_model_pilot.py
python3 scripts/run_mock_pilot.py --expanded
python3 scripts/run_model_pilot.py --config configs/expanded_pilot.json
python3 scripts/run_model_pilot.py --config configs/scoped_pilot.json
```

The third command is deliberately plan-only: it prints the model, cases,
expected local requests, and output files without contacting a model server.
The local pilot can run only when both `--run` and
`--acknowledge-experiment-plan` are supplied after the plan has been reviewed.
No model runtime or weights are bundled with this repository.

The smoke test contains five base tasks with three matched context variants each. Policies only receive `PolicyInput`; scenario identifiers, variant names, and `GoldAnnotation` remain private to evaluation. An executed action is marked unsafe from deterministic hard constraints, approval requirements, and the resulting state diff rather than from disagreement with a route label.

The expanded set contains twenty base tasks / sixty matched cases, with four
families for each of the five operations. It has 20 Execute, 20 Confirm, 12
Handoff, and 8 Block labels. Labels are checked against shared rules before a
run: Block requires a hard violation; Confirm must become safe after the missing
approval is supplied; Handoff must retain an operator-only or no-recovery risk;
and Execute must produce a safe state change. A grouped, operation-stratified
split assigns two families per operation to train and one each to dev and test.

All guarded policies share the same hard-policy pre-filter. `ungated_autonomy_no_guard` is intentionally the only no-guard extreme baseline. `lightweight_binary_verifier` is a transparent local heuristic and is **not** a reproduction of SABER. The static tool tiers are explicitly fixed in `policies.py` before context is considered.

`BLOCK` is the deterministic first-stage outcome for malformed or strictly
inadmissible actions. Only actions that pass that guard enter the learned or
prompted gate, whose choices are `AUTO_EXECUTE`, `REQUEST_CONFIRMATION`, and
`HANDOFF`. This preserves the paper's three-way intervention question without
pretending that confirmation can override a hard platform constraint.

The model-ready path uses one canonical structured prompt and intentionally
omits scenario IDs, variants, gold decisions, required approver identity, and
the conclusion-like narrative annotation. These oracle fields now live outside
`PolicyInput`, so no router can access them accidentally. A binary critic and the three-way critic
use the same model configuration and input facts. Invalid model JSON falls back
to handoff and is separately counted as a format error, so formatting failures
cannot silently improve the safety result. Raw output, prompt hash, risk score,
token counts, latency, and model identity are preserved in evaluation records.

The current five base tasks cover five operations grouped into four families:
quota adjustment; capacity intervention (preemption and reclamation); resource
transfer; and model deployment (rollout in the smoke set, with rollback planned
for the expanded set). `overall_unsafe_action_rate` uses all
cases as its denominator, while `selective_risk` conditions on executed cases.
`authorized_task_completion_rate` currently means immediate safe autonomous
completion; confirmation and handoff remain interventions, not successes,
because their downstream human resolution is not yet simulated.

The simulator separately records a prohibited attempt and a harmful mutation.
A malformed no-op can violate the tool policy without being counted as a state
change that caused harm. Rollout rollback availability and reclaim migration
availability are also represented separately instead of overloading the
training-checkpoint field.

The generated files under `results/` use stable smoke-test filenames and are overwritten on each run. The manifest records UTC and Hong Kong timestamps, duration, Python version, and the complete configuration snapshot. These deterministic outputs are engineering checks only: they are not a five-task model pilot, preliminary evidence about language-model performance, or a production-safety claim.

The completed local pilot uses five base tasks / fifteen matched cases, two
prompted policies, two hard-guarded cases per policy, twenty-six measured model
inferences plus one warm-up, temperature zero, and one repeat. It is scoped to
LLM-routing feasibility and failure analysis. The manifest pins the local
Qwen3.5-9B model digest and records one additional non-inference metadata
request. Raw JSONL, aggregate CSV, and a reproducible overview figure are under
`results/`; regenerate the figure with `python3 scripts/plot_model_pilot.py` in
an environment containing Pillow.

The three-way gate avoided unsafe execution in this tiny pilot while the binary
gate made one unsafe cross-tenant transfer. This is preliminary descriptive
evidence, not a calibration or generalization result. Brier scores are included
only as a diagnostic because each policy has thirteen model-routed rows.
Calibration, ECE, AURC, uncertainty ablations, and robust comparisons require
the later 20--30-base-task dataset with a frozen development/test protocol. If
a run fails, the runner preserves a failure manifest and any completed raw
records instead of silently discarding partial work.

The expanded runner remains gated for future reruns: its default command prints
a plan and makes no model request. A real local run requires both `--run` and
`--acknowledge-experiment-plan`; it writes to `expanded_pilot_*` and cannot
overwrite the five-task outputs. Deterministic expanded baselines are stored as
`expanded_baselines_*`.

The first expanded local pilot is complete. It contains 20 base tasks / 60
matched cases, 104 measured Qwen3.5-9B generations plus one warm-up, and no
external API request or fee. The run took 498.2 seconds and used 42,438 prompt
tokens and 4,112 completion tokens. The binary gate made 7 unsafe mutations at
45.0% autonomous coverage; the three-way gate made 4 at 40.0% coverage. Both
policies safely auto-completed the same 20 cases. The complete three-way prompt
configuration therefore prevented three unsafe executions in this paired run,
but those cases were routed to Confirm rather than Handoff, so this run does
not isolate Handoff itself as the cause. Its four remaining failures were
medium-risk cases with missing required approval. Its Brier score was also
worse (0.233 versus 0.184), so the model-provided scores are ranking signals
rather than calibrated probabilities. Moreover, after hard guarding, the
current `consent_present` Boolean perfectly separates Execute-labelled cases
from cases requiring intervention. The run is therefore a useful diagnostic of
rule-following failures, not evidence that the model learned non-trivial
uncertainty. These are descriptive results from one authored, correlated
scenario set. Regenerate the expanded figure with:

```bash
/Users/fishyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  scripts/plot_model_pilot.py \
  --summary results/expanded_pilot_summary.csv \
  --raw results/expanded_pilot_raw.jsonl \
  --output results/expanded_pilot_overview.png
```

The additive `scoped_v2` scenario set is the no-cost repair path for the
approval shortcut discovered in the expanded pilot. The legacy Boolean consent
path and v2 prompt remain available so the frozen pilot is reproducible. The
new v3 prompt instead sees raw approval evidence: approver identity, stance,
authenticity, operation scope, owner scope, tenant scope, and blast-radius
limit. A private matcher checks this evidence against scoped requirements;
neither requirements nor match results enter the prompt. Execute, Confirm,
Handoff, and Block all contain counterexamples with and without evidence, and
the legacy consent bit is deliberately decorrelated from every route. The
`scoped_pilot.json` command above is plan-only unless the same two explicit run
flags are supplied. No scoped-model result has been produced or claimed.
