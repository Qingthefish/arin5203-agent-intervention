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

## Current Status — 2026-10-03

- The proposal body is 351 whitespace-delimited English words, remains one paragraph, and now fixes the formal scope at 20 base scenarios / 60 matched cases with a U-Fold-inspired baseline.
- The deterministic simulator, intervention policies, baselines, metrics, and unit tests are implemented.
- A 5-family pipeline pilot (15 cases, 39 measured generations) and a balanced 20-family development pilot (60 cases, 153 measured generations) have run locally with Ollama and Qwen3.5-9B at no API cost.
- Two small compaction feasibility pilots compared full context, tail truncation, generic summarization, rule pinning, and selective human review across platform, financial-style evidence, and main/sub-agent authority patterns. They ran locally with zero API cost and show that the pipeline is feasible and compaction can change routing. They do **not** establish safety superiority or incremental value from a human answer.
- The core literature now covers constraint loss, when/what to compact, downstream behavioral validation, fixed-budget reliability, and selective human curation. The original τ-bench, ToolSandbox, Semantic Entropy Probes, and SABER papers remain supporting evaluation and intervention background.
- All completed runs have manifests and machine-readable artifacts. The 20-family intervention run is a method-development result, not the final held-out compaction evaluation; its families are reserved for the eventual training pool.
- The `medium_pilot_qwen_k3_v1` artifacts preserve the original edge-biased threshold tie-break. The subsequent code revision selects maximum-margin thresholds on development predictions; no v1 artifact is silently overwritten.
- The 18-context anti-shortcut causal audit met its pre-specified development gate at the minimum boundary: all six full-evidence contexts were correct, matched-noise removal changed 0/6 decisions, and critical-evidence removal triggered intervention in 4/6. Both missed cases were main--sub-agent authority scenarios. This does not yet validate Confirm versus Handoff; the next gate explicitly separates answerable omissions from residual risk before any scale-up.
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
