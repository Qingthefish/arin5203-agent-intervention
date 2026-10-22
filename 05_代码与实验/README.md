# Agent Memory Crash Test

**Crash-test the evidence an AI agent retains before state-changing actions.**

Agent Memory Crash Test is an installable, zero-model research toolkit for turning a memory-dependent tool call into a deterministic regression gate. A declarative contract generates three matched conditions—complete evidence, one action-critical deletion, and one exactly byte-matched noise deletion—then checks whether the agent-side policy should `AUTO_EXECUTE`, `REQUEST_CONFIRMATION`, or `HANDOFF`. Reports include retained provenance, harmful state mutations, noise sensitivity, JSON, and standard JUnit XML.

This is a research preview, not a production safety certification. It helps teams test memory and compaction changes before deployment; it does not replace authorization services, identity controls, transaction validation, sandboxing, or human review.

## Ten-Minute Quickstart

Python 3.12 or newer is required. The deterministic path has no runtime dependencies and does not need an API key.

```bash
python3 -m pip install -e .
agent-memory-crash-test --init my-memory-gate.json
agent-memory-crash-test --spec my-memory-gate.json --validate-only
```

The repository includes a copy-ready GitHub Actions gate. A maintainer with
workflow permission can enable it with:

```bash
mkdir -p .github/workflows
cp ci/github-actions.yml .github/workflows/memory-crash-test.yml
```

Run the bundled red-to-green example:

```bash
# Expected red: conversational memory lost an active hold.
agent-memory-crash-test \
  --spec examples/memory_crash_test.json \
  --output-dir reports/memory \
  --proof-source memory \
  --strategy typed-proof-memory \
  --allow-fail

# Expected green: the same validator re-reads the declared durable registry.
agent-memory-crash-test \
  --spec examples/memory_crash_test.json \
  --output-dir reports/registry \
  --proof-source registry \
  --strategy typed-proof-memory
```

The first command deliberately reports `5/6` with one harmful execution. The second reports `6/6` with zero harmful executions. The action, policy, memory strategy, and validator stay unchanged; only the source of authoritative proof changes.

## What This Tests

```text
conversation or agent trace
          │
          ├── complete evidence
          ├── remove one action-critical event
          └── remove equal-size irrelevant noise
                         │
                 memory strategy
                         │
              provenance proof gate
                         │
          Execute / Confirm / Handoff
                         │
             deterministic state diff
```

The toolkit is deliberately narrower than a general memory framework. It does not decide what a user prefers, build a vector database, or claim that a model's explanation is faithful. It asks whether the evidence required for one proposed mutation survived, whether the route is grounded in retained sources, and what state would change if the operation executed.

The contract schema is published at `schemas/agent-memory-crash-test-v1.schema.json`. The public Python API is available from `agent_memory_crash_test`; the underlying research modules remain under `platform_agent_eval` for reproducibility.

## Where It Fits

This project does not replace an Agent framework, memory database, benchmark,
or runtime authorization service. It connects those layers through one narrow
developer question: **if one action-relevant fact disappears while an
equally sized irrelevant fact disappears in the control, does the proposed
tool call still take the right route for grounded reasons?**

Related work already studies long-term memory, memory-to-action failures,
context compaction, abstention, delegation, and human intervention. The useful
unit here is their integration into a declarative, provider-independent
regression gate with matched deletions, provenance checks, three-way routing,
and observable state diffs. See [`docs/related-work.md`](docs/related-work.md)
for the positioning and claim boundary.

## Research Origin

This package contains the reproducible simulator and local evaluation code for the ARIN 5203 project **Do AI Platform Agents Know What They Must Not Forget? — Compaction-Aware Intervention Before State-Changing Operations**. The course research archive, immutable traces, presentation evidence, and full decision history live in the companion repository: <https://github.com/Qingthefish/arin5203-agent-intervention>.

## Current Research Question

Before an AI platform agent performs a state-changing operation, can a compaction-aware intervention pipeline preserve decision-critical context and choose `AUTO_EXECUTE`, `REQUEST_CONFIRMATION`, or `HANDOFF` with a better context-efficiency and human-burden trade-off than truncation, generic summarization, or fixed constraint pinning?

The current claim is deliberately limited. Frozen development and held-out experiments show that lossy compaction can remove critical facts and change downstream routing, while strong summaries can remain competitive on route accuracy. Typed proof memory is most clearly differentiated by inspectable evidence provenance rather than a universal route-accuracy win. No post-compaction method can reconstruct an authoritative event that never reached active context; the reference durable registry demonstrates one system-level response to that boundary without claiming production readiness.

## System Boundary

The main evaluation starts with synthetic histories whose authenticated evidence
has already been encoded as source-linked proof cards. Memory strategies retain
events, citations or compact proof capsules under the same active-memory budget.
A direct model router reads that memory; a deterministic audit can rehydrate
canonical records through retained source IDs and check their action-specific
obligations. The external record store and lookup cost are outside the raw-token
memory budget.

This evaluates retention and validation under a declared card-creation
assumption. It does not establish reliable card extraction from arbitrary prose,
real signature verification or a deployed human workflow. Confirm/Handoff are
route semantics here; an authenticated follow-up must be evaluated separately.

Gold decisions and oracle conclusions stay outside model-visible inputs. State
diffs come from the deterministic simulator or declared contract transition,
not a live booking, payment or production service.

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
- `src/platform_agent_eval/evidence_grounding.py` and `evidence_grounding_cases.py` — field-level grounding of extracted natural-language claims in their cited messages, a restrictive-cue scan, a fail-closed gate around the unchanged validator, and the frozen evaluation cases.
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
- The companion course archive's `04_项目展示/` directory contains the slide-ready evidence pack and Agent Memory Playbook derived from the frozen held-out result.

## Natural-Language Evidence Extension

The course contribution in PR #1 adds an optional extraction diagnostic:
ordinary messages → literal evidence fields with source quotes → the existing
proof validator. The v1 interface preserves the extracted subject, operation,
target, scope and validity window; it never fills these from the proposed
action. Any malformed claim invalidates the output and routes to Handoff.
Citation presence is checked against the actual event text. Quote containment
does not independently establish semantic entailment or cryptographic trust.

`results/nl_evidence_v0_dataset*` preserves the contributor's original export.
`results/nl_evidence_v1_dataset*` is the revised snapshot, with same-role,
same-position, equal-UTF-8-byte critical/noise events. This is not a claim of
equal token budgets. The 120 contexts reuse the existing 20 base families;
test-family rewrites are not new independent held-out data. No extraction
model run has been completed. This extension has no compactor comparison.

Print a development plan without contacting a model:

```bash
python3 scripts/run_nl_evidence_extraction.py --split dev --variant clean --limit 6
```

The runner requires both `--run` and `--acknowledge-experiment-plan` to contact
loopback Ollama. `--limit` preserves whole sibling triples. Each versioned run
reserves its prefix and writes raw JSONL, summary CSV, audit JSON and a manifest,
including prompt/config/dataset hashes, generation settings, Git revision,
model identity, latency and tokens. Offline launches and interruptions remain
discoverable. Audit PASS is an instrumentation result, not an extraction
quality claim. After any actual run, regenerate and check `results/index.json`.
Dataset export also refuses to overwrite existing versioned files.

### Field-level grounding

`evidence_grounding.py` checks each extracted field against the full cited
message before the unchanged validator runs. Fields are `SUPPORTED`,
`CONTRADICTED` or `INSUFFICIENT_EVIDENCE`. Only fully supported permissive
claims reach the validator. Hold claims are never removed. A hold, prohibition,
denial or revocation cue that no supported hold claim accounts for routes to
Handoff, and the result is never more permissive than the baseline route. The
checks are closed English cue lists over a declared profile, not general
entailment, and they verify no signatures. See
[`docs/evidence-grounding.md`](docs/evidence-grounding.md) for the rules,
threat model, results and limitations.

```python
from platform_agent_eval.evidence_grounding import ground_nl_context
result = ground_nl_context(context, parse)  # decision, baseline_decision, failure_layer, claim_groundings
```

```bash
python3 -m unittest tests.test_evidence_grounding -v
python3 scripts/run_evidence_grounding_evaluation.py --config configs/evidence_grounding_eval.json
```

The evaluation runner is deterministic and plan-only without `--run` and
`--acknowledge-experiment-plan`. It refuses to run if the verifier or case
module differs from the hashes frozen in the config.

## Reproduction

Use Python 3.12 or newer from this directory. The public deterministic CLI is
shown in the quickstart; these checks read the existing research evidence:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/index_experiment_artifacts.py --check
python3 scripts/audit_dataset.py --scenario-set research_v3 --strict
```

Preview the frozen comparison and optional extension without making model calls:

```bash
python3 scripts/run_typed_exact_budget_gate.py --config configs/typed_exact_budget_heldout.json
python3 scripts/run_typed_budget_sweep.py --config configs/typed_budget_sweep_dev.json
python3 scripts/run_durable_proof_store_gate.py --config configs/durable_proof_store_gate.json
```

These runners are plan-only by default. A real run requires both `--run` and
`--acknowledge-experiment-plan`, and existing output prefixes cannot be reused.
The held-out comparison has already been run once and must not be retuned or
rerun for a better score. Earlier `scripts/run_*` entry points are retained for
provenance; use their `--help` and the matching frozen manifest/config to inspect
a historical protocol rather than treating every script as the next task.

For the model-free demo:

```bash
python3 scripts/serve_memory_crash_test.py --port 8765
```

Open `http://127.0.0.1:8765`. Story Mode presents one familiar case and simulated
state diff; Evidence Suite expands to the seven-strategy/three-condition matrix;
Trace Inspector exposes exact memory and provenance. The three curated travel
families replay immutable held-out records. A labeled durable-registry overlay
shows a deterministic architecture alternative while preserving the original
hidden-hold failure. Neither path contacts a model or a real booking service.

To render the seven figures, install the optional dependency and choose an
output directory (the default targets the companion course archive):

```bash
python3 -m pip install -r requirements-presentation.txt
python3 scripts/plot_typed_heldout_presentation.py --output-dir reports/figures
```

The plotter reads frozen traces and the experiment index, then writes PNGs and
source-hashed `presentation-metrics.json`. Those are derived presentation views,
not new experiment results. The research and CLI paths otherwise use the
standard library; no model weights, API keys or company data are stored here.

## Evidence and Artifact Sources

`results/index.json` is generated discovery metadata. Use each run's manifest
for configuration, hashes, identity, calls, timing and usage; its summary for
metrics; and its audit for protocol checks. Regenerate and check the index
after adding artifacts. Do not edit it manually.

| Evidence | Frozen prefix | Interpretation |
| --- | --- | --- |
| Method development | `typed_exact_budget_dev_qwen_v6` | Passed development protocol and method gates; earlier failed versions remain preserved. |
| One-shot held-out comparison | `typed_exact_budget_heldout_qwen_v1` | Main course-project comparison; strong summaries tie on audited stable routes. |
| Tighter memory budgets | `typed_budget_sweep_dev_qwen_v1` | Development-only sensitivity analysis, reusing frozen compactor outputs. |
| External proof lookup | `durable_proof_store_deterministic_v1` | Deterministic architecture gate assuming authenticated cards; no LLM extraction or distributed-systems claim. |
| Claim grounding before validation | `evidence_grounding_deterministic_v1` | Deterministic baseline-vs-grounding comparison on 58 author-written cases and derived corruptions of the NL templates; no extraction-model or general-NLI claim. |
| Correct route with weak grounding | `grounded_hitl_qwen_v4` | Development counterexample motivating joint evidence/route scoring. |
| Unhelpful reviewer and clearance confusion | `audit_increment_qwen_v2`, `blind_proof_qwen_v1` | Failed development approaches; post-hoc trace reviews are explicitly labeled. |
| Earlier feasibility/protocol repairs | All other prefixes in the index | Historical diagnostics; do not pool them as independent final evaluation or method rankings. |

The course archive's `项目复盘.md` owns the failure analysis and research
decisions. Versioned raw, summary, audit and manifest files remain immutable,
including failed, interrupted and zero-call launches. Natural-language dataset
exports are fixtures, not evidence of completed model experiments.

## Experimental Discipline

- Fix seeds and save configuration, prompt hashes, model identity, token use, and raw output.
- Keep counterfactual sibling cases in the same split.
- Select prompts, thresholds, and policies using development data only.
- Report failures and format fallbacks rather than silently dropping them.
- Do not run paid external APIs without explicit team approval.
- Cite every borrowed implementation and preserve its license notice where required.
