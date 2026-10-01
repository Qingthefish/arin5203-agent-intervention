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

## Experiment Policy

Run unit tests, deterministic checks, and small local pilots first. Before any formal experiment, record the model, task count, estimated time, expected tokens or API cost, execution location, and output files. Do not launch paid external API experiments without team approval.

## Course Constraints

The project is for ARIN 5203 only. Public implementations must be cited, other course groups' code must not be used, and one team member submits each deliverable with all team members named.
