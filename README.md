# ARIN 5203 Course Project

## Project

**Do AI Platform Agents Know When to Ask for Help**  
Context Aware Intervention Before State Changing Operations

This project studies a pre-action intervention gate for tool-using agents. Before a proposed state-changing operation, the gate chooses among autonomous execution, user confirmation, and human handoff. The evaluation focuses on harmful state changes, safe autonomous completion, coverage, calibration, intervention burden, latency, and token cost.

## Team

- **Qingcheng Yu** — agent product design, intervention policy, and evaluation.
- **Siu Kwun Yeung** — enterprise multi-agent workflows, verification, human review, and control requirements.
- **Qingyin Guo** — agent application prototyping, search and parsing workflows, tool and API integration, and orchestration.

All team members will review the scenario policy, implementation, experiments, and report. The role descriptions identify primary ownership rather than isolated workstreams.

## Current Status

- The 331-word proposal is ready for team review and remains one paragraph as required by the course page.
- The deterministic simulator, intervention policies, baselines, metrics, and unit tests are implemented.
- A 5-family pipeline pilot (15 cases, 39 measured generations) and a balanced 20-family development pilot (60 cases, 153 measured generations) have run locally with Ollama and Qwen3.5-9B at no API cost.
- Both runs have complete manifests and machine-readable artifact audits. The 20-family run is a method-development result, not the final held-out evaluation; its families are reserved for the eventual training pool.
- The `medium_pilot_qwen_k3_v1` artifacts preserve the original edge-biased threshold tie-break. The subsequent code revision selects maximum-margin thresholds on development predictions; no v1 artifact is silently overwritten.
- The remaining 20 untouched families are reserved for the frozen formal development and test splits.
- `02_里程碑/milestone.tex` is a working milestone draft with preliminary results. It is not yet the final milestone submission.

## Repository Structure

- `01_提案/` — proposal, references, and the original draft.
- `02_里程碑/` — milestone LaTeX source.
- `05_代码与实验/` — simulator, scenario sets, model routing, tests, configurations, and results.
- `CVPR2026_模板源码/` — instructor-provided report template.
- Course requirement snapshots and official template archives remain unchanged at the repository root.

Chinese directory names are retained because they match the course-material organization. Code, configuration keys, paper filenames, and technical documentation use English where that improves interoperability.

## Local Reproduction

From `05_代码与实验/`:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_research_experiment.py --config configs/research_medium_pilot.json
python3 scripts/audit_research_artifacts.py --prefix medium_pilot_qwen_k3_v1
```

The research runner is plan-only unless both `--run` and `--acknowledge-experiment-plan` are present. Existing experiments use local Ollama and Qwen3.5-9B; they do not require a paid API key. Existing output prefixes are immutable so an accidental rerun cannot overwrite the evidence.

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
