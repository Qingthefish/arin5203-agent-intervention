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
- A 5-task pilot and an expanded 20-task, 60-case pilot have run locally with Ollama and Qwen3.5-9B at no API cost.
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
python3 scripts/run_model_pilot.py --config configs/scoped_pilot.json
```

The second command is plan-only and makes no model request. A real local run requires both `--run` and `--acknowledge-experiment-plan`. Existing experiments use local Ollama and Qwen3.5-9B; they do not require a paid API key.

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
