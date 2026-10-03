# ARIN 5203 Project Instructions

## Scope and Objective

- Work only inside this repository. Do not modify Assignment 1 or other course directories.
- The locked topic is **Do AI Platform Agents Know What They Must Not Forget? — Compaction-Aware Intervention Before State-Changing Operations**.
- The experimental question is whether compaction-aware context management can preserve decision-critical evidence and improve the trade-off among context reduction, autonomous execution, confirmation, and human handoff.
- This is a course project, not a production-safety certification. Keep claims proportional to the evidence.

## Read Before Editing

1. Read `README.md` for the current status and collaboration workflow.
2. Read `项目复盘.md` for decisions, failed approaches, literature scope, and the presentation narrative.
3. Read `05_代码与实验/README.md` before changing code or running experiments.
4. Treat `01_提案/Project_Proposal_Yu_Yeung_Guo.docx` as the current proposal and `Project_Proposal_Qingcheng_Yu_原始草稿.docx` as archive-only.

If these files conflict, preserve reproducible evidence and ask the team before changing the locked research question.

## Current Evidence Boundary

- The five-scenario compaction pilot is completed local feasibility evidence, not a final benchmark.
- The six-scenario proposal-alignment pilot is also completed. It validates one shared framework across platform, financial-evidence, and multi-agent handoff patterns, but it does not demonstrate safety superiority or incremental value from human answers.
- Earlier intervention experiments are development history; do not combine them with the compaction pilot as if they were one frozen evaluation.
- No final held-out compaction result exists yet.
- The next gate is a 20-task development set and a separately frozen test set. Repair the keyword-pinning baseline and isolate answerable HITL cases before running it.

## Engineering Rules

- Use Python 3.12 or newer.
- Run `python3 -m unittest discover -s tests -v` from `05_代码与实验/` after code changes.
- Keep gold labels, oracle facts, and private approval requirements outside model-visible inputs.
- Keep counterfactual siblings in the same train/dev/test split.
- Fix seeds and save configuration, prompt hashes, raw outputs, model identity, latency, token usage, and manifests.
- Never overwrite an existing experiment prefix. Add a new versioned prefix.
- Prefer the standard library. `Pillow` is optional and used only for plotting.

## Experiment Safety and Cost

- Model runners must remain plan-only unless both explicit run flags are supplied.
- Before a formal run, state the model, task count, model-call count, estimated time, token range, execution location, cost, and output files.
- Existing local model runs use Ollama with `qwen3.5:9b` and no external API fee.
- Do not use a paid API, upload company data, or add secrets without explicit team approval.
- Do not commit model weights, API keys, private company material, or unrelated course work.

## Research and Writing Rules

- Use primary papers, official repositories, and official product documentation where possible.
- Cite borrowed methods and implementations; preserve their license notices.
- Do not describe a baseline as a paper reproduction unless the implemented protocol actually matches it.
- Distinguish planned work, development evidence, and frozen-test findings.
- Do not fabricate HSBC, startup, or Xiaohongshu production facts. Team experience may motivate synthetic scenario templates only.
- Keep the folder lean. Update `项目复盘.md` instead of creating new planning Markdown files.

## Collaboration

- Pull `main`, create a focused branch, make small commits, and open a pull request for review.
- Avoid concurrent edits to DOCX, PDFs, and generated binary figures.
- Before merging, report changed files, tests run, new experiment artifacts, and any claim that must be updated.

## Good First Tasks

- Review synthetic scenarios for realism, ambiguity, and shortcut leakage.
- Add structured fact-oracle checks without exposing gold information to prompts.
- Review retained-context budget matching and compaction baselines.
- Reproduce figures and audit manifests without changing frozen artifacts.
- Translate technical results into a three-branch demo: compact/pin/ask feeding execute/confirm/handoff.
