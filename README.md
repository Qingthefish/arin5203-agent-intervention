# ARIN 5203 Course Project

## Project

**Do AI Platform Agents Know What They Must Not Forget?**<br>
**Compaction-Aware Intervention Before State-Changing Operations**

This project studies how context compaction changes a tool-using agent's decision before consequential operations. The system removes recoverable tool noise, pins clearly safety-critical constraints, and requests a short human decision only when the validity or authority of a candidate memory is ambiguous. The compacted context then feeds a pre-action gate that chooses autonomous execution, user confirmation, or human handoff. Evaluation connects context reduction and critical-fact retention to harmful state changes, safe autonomous completion, intervention burden, latency, and token cost.

## Team

- **Qingcheng Yu** — agent product design, intervention policy, and evaluation.
- **Siu Kwun Yeung** — enterprise multi-agent workflows, verification, human review, and control requirements.
- **Qingyin Guo** — agent application prototyping, search and parsing workflows, tool and API integration, and orchestration.

All team members will review the scenario policy, implementation, experiments, and report. The role descriptions identify primary ownership rather than isolated workstreams.

## Current Status — 2026-10-04

- The proposal body is 351 whitespace-delimited English words, remains one paragraph, and now fixes the formal scope at 20 base scenarios / 60 matched cases with a U-Fold-inspired baseline.
- The deterministic simulator, intervention policies, baselines, metrics, and unit tests are implemented.
- A 5-family pipeline pilot (15 cases, 39 measured generations) and a balanced 20-family development pilot (60 cases, 153 measured generations) have run locally with Ollama and Qwen3.5-9B at no API cost.
- Two small compaction feasibility pilots compared full context, tail truncation, generic summarization, rule pinning, and selective human review across platform, financial-style evidence, and main/sub-agent authority patterns. They ran locally with zero API cost and show that the pipeline is feasible and compaction can change routing. They do **not** establish safety superiority or incremental value from a human answer.
- The core literature now covers constraint loss, when/what to compact, downstream behavioral validation, fixed-budget reliability, and selective human curation. The original τ-bench, ToolSandbox, Semantic Entropy Probes, and SABER papers remain supporting evaluation and intervention background.
- All completed runs have manifests and machine-readable artifacts. The 20-family intervention run is a method-development result, not the final held-out compaction evaluation; its families are reserved for the eventual training pool.
- The `medium_pilot_qwen_k3_v1` artifacts preserve the original edge-biased threshold tie-break. The subsequent code revision selects maximum-margin thresholds on development predictions; no v1 artifact is silently overwritten.
- The 18-context anti-shortcut causal audit met its pre-specified development gate at the minimum boundary: all six full-evidence contexts were correct, matched-noise removal changed 0/6 decisions, and critical-evidence removal triggered intervention in 4/6. Both missed cases were main--sub-agent authority scenarios. This does not yet validate Confirm versus Handoff; the next gate explicitly separates answerable omissions from residual risk before any scale-up.
- The subsequent 9-scenario / 15-call paired HITL pilot routed all initial and follow-up contexts correctly. An independent post-hoc audit nevertheless found ungrounded free-form reasons, so route correctness is not treated as faithful evidence use.
- A closed eight-factor schema with mandatory `CTX-Cxx` citations was then tested on the same development gate. The first run is preserved as a failed runner artifact because a tuple/list audit mismatch occurred after all raw calls. In completed v2--v4 iterations, routing stayed at 15/15 with zero harmful false executes, but joint grounded route accuracy rose only from 46.7% to 66.7%. The frozen v4 prompt reached 93.9% grounding precision and zero direct contradictions, yet only 86.1% decisive-factor recall and 10/15 joint success; it therefore failed the pre-specified scale-up gate.
- Prompt, ontology, and gold definitions are now frozen for the original authored set. Structured evidence slots plus deterministic cross-event linking were evaluated on new cases before any budget-matched compaction scale-up. The old compaction pilots are not budget-fair comparisons and will not be presented as final method rankings.
- The first structured-evidence smoke used nine entirely new matched contexts and compared the frozen v4 router with atomic slot extraction plus deterministic linking. The frozen router achieved 9/9 correct routes and complete route proofs. The structured method achieved 6/9 routes and 3/9 complete proofs, with 83.3% atomic precision, 75.0% decisive-slot recall, one format error, and zero harmful false executes. It failed every positive scale-up criterion except the two safety-burden limits. This v1 schema is frozen as a negative result: the next design must remove ambiguous slot-value conventions and reduce all-or-nothing extraction burden on fresh development cases rather than rescoring this set to pass.
- An exact Qwen tokenizer re-audit counted all 55 active contexts from the two earlier compaction pilots. Among the four compacted strategies, the largest-to-smallest mean context ratio was 6.23x in the five-case pilot and 5.90x in the six-case pilot, far beyond the pre-specified 1.10 fairness limit. The character-count proxy had 9.1% mean absolute ratio error and 18.3% maximum error. These pilots remain feasibility evidence only; they must not be used to rank compaction methods.
- The replacement exact-budget pipeline then passed its pre-specified engineering gate on six reused development scenarios: all 30 budgeted contexts stayed within 256 raw Qwen tokens and used at least 90% of the budget, while strategy means ranged only from 246.0 to 250.5 tokens (1.018x). Full history, generic summary, precise pinning, and selective audit routed 6/6 correctly; recent window and U-Fold-lite routed 4/6. These method scores are directional rather than held-out evidence. Four compactor-format fallbacks and 493 tokenizer probes also show that schema interoperability and cached token counting must be fixed before scale-up.
- A stricter post-hoc read of the immutable fixed-budget raw traces found additional protocol confounds: the so-called generic prompt explicitly named authority and recovery fields, pinning used dataset-specific identifier patterns, every summary condition was mixed with recent raw events, and the router could see method labels. Most importantly, one selective-audit fallback omitted the real approval event but still routed `AUTO_EXECUTE` by claiming that valid approval existed. Correct routes are therefore no longer accepted without grounded evidence support. Before any fresh scenario scale-up, the next gate separates neutral versus task-aware summaries and no-fill versus neutral-fill versus raw-tail-fill, blinds method labels, freezes identifier-agnostic pinning, requires cited evidence, and caches exact token counts.
- `02_里程碑/milestone.tex` is now aligned with the compaction-aware topic and compiles successfully. It is a truthful working milestone draft, not the final November submission; later frozen results and template confirmation remain pending.

## Repository Structure

- `01_提案/` — proposal, original draft, and the deliberately limited primary-paper set.
- `02_里程碑/` — milestone LaTeX source.
- `05_代码与实验/` — simulator, scenario sets, model routing, tests, configurations, and results.
- `项目复盘.md` — the single living project retrospective and presentation evidence map.
- `CVPR2026_模板源码/` — instructor-provided report template.
- Course requirement snapshots and official template archives remain unchanged at the repository root.

Chinese directory names are retained because they match the course-material organization. Code, configuration keys, paper filenames, and technical documentation use English where that improves interoperability.

## Local Reproduction

From `05_代码与实验/`:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_compaction_pilot.py --config configs/proposal_alignment_pilot.json
python3 scripts/run_grounded_hitl_gate.py --config configs/grounded_hitl_gate.json
python3 scripts/run_research_experiment.py --config configs/research_medium_pilot.json
python3 scripts/audit_research_artifacts.py --prefix medium_pilot_qwen_k3_v1
```

The research runner is plan-only unless both `--run` and `--acknowledge-experiment-plan` are present. Existing experiments use local Ollama and Qwen3.5-9B; they do not require a paid API key. Existing output prefixes are immutable so an accidental rerun cannot overwrite the evidence.

### First 10 Minutes for a New Teammate

1. Clone the repository and open its root folder in Codex. The root `AGENTS.md` is the machine-readable project brief that Codex loads automatically.
2. Ask Codex: `Summarize the locked research question, completed evidence, claim limits, and the safest task I can take next.`
3. Read `项目复盘.md` only if the task concerns research decisions, writing, or presentation; read `05_代码与实验/README.md` only if the task concerns code or experiments.
4. For code work, enter `05_代码与实验/` and run the unit tests. The tests and deterministic audits use only Python 3.12+ standard-library code.
5. Create a branch before editing. Do not rerun or overwrite completed experiment prefixes.

Codex access alone is enough for reading, coding, tests, dataset review, and writing. Reproducing model-backed results additionally requires local [Ollama](https://ollama.com/) and the exact `qwen3.5:9b` model. `Pillow` is optional and needed only to regenerate PNG figures. No OpenAI, Qwen, or other paid API key is required for the existing workflow.

## Collaboration Workflow

1. Pull the latest `main` before starting work: `git pull --ff-only origin main`.
2. Create a short branch for each change, such as `git switch -c feat/scenario-review`.
3. Keep commits focused and do not commit API keys, model weights, or unrelated course work.
4. Push the branch and open a pull request so another member can review it before merging.

Avoid editing the same DOCX or binary result file concurrently because Git cannot merge those files line by line. LaTeX, Python, JSON, and Markdown files are easier to review and merge through pull requests.

## Experiment Policy

Run unit tests, deterministic checks, and small local pilots first. Before any formal experiment, record the model, task count, estimated time, expected tokens or API cost, execution location, and output files. Do not launch paid external API experiments without team approval.

## Course Constraints

The project is for ARIN 5203 only. Public implementations must be cited, other course groups' code must not be used, and one team member submits each deliverable with all team members named.
