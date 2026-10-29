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
unit here is their integration into a declarative, provider-agnostic fixture
format for regression tests with matched deletions, provenance checks, three-way routing,
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
real signature verification or a deployed human workflow. Confirm/Handoff in
the main frozen evaluation are route semantics. The optional human-intervention
module separately tests a scripted follow-up lifecycle under a channel-directory
trust fixture; it does not establish real authentication.

Gold decisions and oracle conclusions stay outside model-visible inputs. State
diffs in the replay/toolkit come from a declared simulated transition, not a live
booking, payment or production service. The main frozen comparison instead
scores harmful Execute as the authored `unsafe_if_executed` flag AND the
released Execute route; do not describe those raw records as independent
domain-state execution traces.

The frozen field `proof_citation_precision` measures the macro-averaged fraction
of direct-router citations selecting visible proof-card sources, not semantic
entailment or complete decisive proof. A labeled post-hoc recount in the
presentation metrics separates source-ID existence from proof-source selection.
Main research siblings are word-count matched; the later toolkit and NL-v1
contracts use exact UTF-8 bytes. Neither matching rule means equal tokenizer
length. Only the six compressed strategies share the active-memory token cap;
full history is an unbudgeted reference.

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
- `src/platform_agent_eval/commit_time_gate.py` — prepare/commit gate that re-reads a versioned registry at the commit instant and applies the simulated transition inside one serializable commit section.
- `src/platform_agent_eval/human_intervention_workflow.py` and `human_intervention_scenarios.py` — closed-loop handling of `REQUEST_CONFIRMATION`: bound requests, channel-authenticated responses, revalidation with the unchanged validator, idempotent simulated execution, and the protocol scenario matrix.
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
test-family rewrites are not new independent held-out data. The v2 snapshot
repairs missing literal operations, makes invalid distractors fully specified,
and pairs clean/distractor replacement events by role, position and UTF-8 bytes.
Invalid records must be extracted faithfully, then rejected for the declared
scope/target/authentication mismatch. The first frozen development diagnostic is
complete; it does not establish upstream extraction readiness. This extension
has no compactor comparison.

Print a development plan without contacting a model:

```bash
python3 scripts/run_nl_evidence_extraction.py --split dev --variant clean --limit 6
```

The frozen first diagnostic selects four development families (`v7`, `c4`,
`d8`, `r5`), both variants and all three siblings: 24 calls covering three
domains, three original routes and all three distractor styles. This is not a
full domain-by-route grid. Its immutable plan is
`configs/nl_extraction_dev_diagnostic_v1.json`. Reprint/verify it with:

```bash
python3 scripts/run_nl_evidence_extraction.py --split dev --variant all \
  --family-id nl-typed-v7 --family-id nl-typed-c4 \
  --family-id nl-typed-d8 --family-id nl-typed-r5 \
  --max-tokens 3072 --context-window 8192 --timeout-seconds 240 \
  --output-prefix nl_extraction_dev_diagnostic_qwen_v1 \
  --plan-file configs/nl_extraction_dev_diagnostic_v1.json
```

Multi-variant runs require explicit family selection rather than prefix
`--limit`, which would silently select clean records first. A plan file is
created exclusively in plan-only mode and must match on a real run. It freezes
source code, selected prompts, complete scoring references, config and output
prefix. `num_ctx=8192` is passed explicitly for this diagnostic; older runners
retain their existing behavior when no context override is set.

Model formatting and field errors are measured outcomes, not recording-gate
failures or permission to tune and retry. Report literal-source exact P/R,
conditional matched-field accuracy, omissions, invalid-distractor acceptance,
candidate versus released decisions, and paired changes. Perfect visible
extraction still disagrees with world-gold on the two selected hidden-hold
deletions; visible-oracle agreement must be reported separately. Run once,
report either outcome, and stop rather than expanding automatically.

Completed evidence is under `nl_extraction_dev_diagnostic_qwen_v1`: recording
checks pass, but every released route is Handoff. Strict string-scope contract
failures dominate; source/quote presence is not complete field fidelity. Do not
interpret the saved `omitted_literal_gold_claims` as raw model omissions: that
metric counts sources absent after parsing, including rejected claims. JSON
mode here is not schema-constrained generation. Signed-only authentication
language is also ambiguous under the prompt rule. These are limitations of this
frozen diagnostic, not reasons to alter its outputs or automatically rerun it.

The runner requires both `--run` and `--acknowledge-experiment-plan` to contact
loopback Ollama. `--limit` preserves whole sibling triples. Each versioned run
reserves its prefix and writes raw JSONL, summary CSV, audit JSON and a manifest,
including prompt/config/dataset hashes, generation settings, Git revision,
model identity, latency and tokens. Offline launches and interruptions remain
discoverable. Audit PASS is an instrumentation result, not an extraction
quality claim. After any actual run, regenerate and check `results/index.json`.
Dataset export also refuses to overwrite existing versioned files.

## Commit-Time Evidence Freshness Gate

The durable store answers what the registry said at one instant. The commit-time
gate checks that the answer still holds when the simulated mutation is applied.
`prepare` reuses the existing lookup, merge and proof validator and binds the
result to the exact action, declared transition, policy and evidence versions.
`commit` rejects changed parameters, forged or reused tokens and repeated
actions, then re-reads the registry at the commit instant and applies the
transition only if the validator still returns `AUTO_EXECUTE`. A registry
revocation also removes a memory copy of the same card. An unreadable registry
fails closed to Handoff.

The consistency model is explicit and simulator-only. Registry writes submitted
while a commit section is open are deferred and applied in order afterwards, so
the evidence read, validation and state mutation observe one registry version.
Distributed commit, clock skew, partitions and crash recovery are not modeled.

Integration acceptance also checks nested JSON aliasing: transition inputs,
issued tokens, commit snapshots and returned state/history are detached from
caller-owned containers. Deferred registry writes are drained even if one is
invalid; failures are then reported as an `ExceptionGroup`, so a malformed
write cannot silently discard a later valid hold. These are in-process
integrity checks, not authentication or distributed-transaction guarantees.
Idempotency covers the exact action and transition binding, including the
original action timestamp; callers still need a real tool's operation key.
The policy is fixed per prepared action, not fetched from a live policy service.

The development evaluation reuses the three durable-store families with 13
conditions and compares the gate with four baselines: trusting the prepare-time
decision, an unlocked re-check, and two version-pinning variants. Print the
model-free plan:

```bash
python3 scripts/run_commit_time_gate.py --config configs/commit_time_gate.json
```

A formal run needs `--run --acknowledge-experiment-plan` and a clean, committed
worktree, and writes the versioned `commit_time_gate_deterministic_v1` prefix.
The one-shot `commit_time_gate_deterministic_v1` bundle is now complete; do not
rerun that prefix. Its audit passes the declared in-process development gate.
This tests authored schedules and expected outcomes, not a new held-out LLM
comparison or a real concurrent payment service. The added nested-value,
deferred-error and output-path regressions remain unit checks separate from
the formal scenario matrix. Raw, summary, audit and manifest own exact results;
the runner writes LF CSV for byte-preserving Git storage.

Read route and mutation metrics separately: the unlocked recheck matches every
authored condition route yet still has unsafe interleaved executions. The
condition route labels do not themselves certify the evidence state at apply;
the commit-snapshot outcome check and version-consistency metric expose that gap.
## Closed-Loop Human Intervention

The validator's `REQUEST_CONFIRMATION` route now has a run-time lifecycle.
`human_intervention_workflow.py` binds each request to one action and one
authorized responder from the existing repair-channel card. It accepts only
structured replies whose identity comes from a trusted channel fixture. An
accepted approval becomes one `AUTHORITY` card, and the unchanged validator
re-runs on evidence read at execution time before a single simulated mutation.
Handoff is never converted into Confirm. See
[`docs/human-intervention.md`](docs/human-intervention.md) for states, checks,
trust boundaries, results and limitations.

```bash
python3 -m unittest tests.test_human_intervention_workflow -v
python3 scripts/run_human_intervention_evaluation.py --config configs/human_intervention_acceptance_v3.json
```

The evaluation runner is deterministic and plan-only without `--run` and
`--acknowledge-experiment-plan`. It refuses to run if the workflow or scenario
module differs from the hashes frozen in the config. The original v1 config
and result bundle describe the contributor's pre-integration implementation;
v1.1 adds malformed-decision rejection; v1.2 permits a trusted mutation executor
in place of the legacy ledger. Its v3 plan checks default-ledger compatibility;
combined execution is covered by separate integration tests, not those original
scores. Earlier plans remain archived. No new formal run is implied.

## Field-Level Grounding

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
python3 scripts/run_evidence_grounding_evaluation.py --config configs/evidence_grounding_acceptance_v2.json
```

The evaluation runner is deterministic and plan-only without `--run` and
`--acknowledge-experiment-plan`. It refuses to run if the verifier or case
module differs from the hashes frozen in the config. The current acceptance
plan also pins the NL-v2 context version and content hash. The archived v1
result used NL-v1 inputs; changing those inputs must not silently reuse its
plan or be presented as reproducing its scores. No new formal v2 run was made.

## Reproduction

### Run one composed action workflow

```bash
python3 examples/guarded_hotel_workflow.py
python3 examples/guarded_hotel_workflow.py --scenario hold_before_commit --json
python3 -m unittest tests.test_guarded_action_workflow -v
```

This synthetic hotel example joins the optional field-grounding provider,
channel-bound confirmation and the commit-time gate. Existing registry approval
executes without asking; a grounding veto creates no confirmation; a repairable
authority gap asks the named traveller. An accepted reply still cannot override
a new hold, changed arguments, expired approval or duplicate operation. JSON
shows the evidence decisions, exact request binding, registry versions and
simulated state diff.

`GroundedEvidenceProvider` preserves vetoes that have no corresponding hold
card. `CommitBoundExecutor` owns the sole mutation; the workflow cannot also use
the legacy ledger. A fixed declared action keeps its commit binding across
retries even when execution-time evidence is refreshed. See
[`docs/integration.md`](docs/integration.md#composed-hotel-workflow) for the
adapter contracts and remaining trust boundaries. Extraction and authentication
are scripted fixtures; no model, paid API or real booking is used. These are
engineering acceptance checks, not additional frozen benchmark scores.

To check a separately installed course build, add `--installed-package`; the
example then does not insert the checkout's `src` directory. The standalone
published v0.1.1 package does not automatically include this unreleased extension.

### Reproduce existing research evidence

Use Python 3.12 or newer from this directory. The public deterministic CLI is
shown in the quickstart; these checks read the existing research evidence:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/index_experiment_artifacts.py --check
python3 scripts/audit_dataset.py --scenario-set research_v3 --strict
```

Five optional frontend regression tests use Node.js's built-in VM to run the
actual demo script without a browser library. They are skipped if Node.js is
absent; the Python-only CLI and replay server do not require Node.js. Browser
visual checks remain separate from these rendering/interaction checks.

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

Open `http://127.0.0.1:8765`. Story Mode presents one familiar case in three
steps: task, deliberately removed evidence, and released route/simulated diff.
Expand **Explore cases, strategies and evidence** for other cases, conditions,
strategies, JSON export, Evidence Suite's seven-strategy/three-condition matrix,
and Trace Inspector's exact memory and provenance. Query links preserve these
selections, and non-Story deep links open the advanced controls. The three curated travel
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
| Commit-time freshness | `commit_time_gate_deterministic_v1` | Model-free development acceptance over authored schedules; in-process atomicity only, no live-tool or distributed guarantee. |
| Natural-language extraction | `nl_extraction_dev_diagnostic_qwen_v1` | Development-only JSON-mode interface diagnostic; uniform Handoff and contract failures, not end-to-end readiness. |
| Confirmation lifecycle | `human_intervention_deterministic_v1` | Deterministic protocol evaluation with scripted responders; full workflow vs stop-at-confirm, naive resume and single-check ablations. No LLM, user-study or real-identity claim. |
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
