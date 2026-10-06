# ARIN 5203 Project Instructions

## Scope and Objective

- Work only inside this repository. Do not modify Assignment 1 or other course directories.
- The locked topic is **Do AI Platform Agents Know What They Must Not Forget? — Compaction-Aware Intervention Before State-Changing Operations**.
- The experimental question is whether compaction-aware context management can preserve decision-critical evidence and improve the trade-off among context reduction, autonomous execution, confirmation, and human handoff.
- This is a course project, not a production-safety certification. Keep claims proportional to the evidence.

## Read Before Editing

1. Always read `README.md`; it is the only current-status page and contains the next experimental gate.
2. Read `项目复盘.md` only for research design, writing, or presentation work; it records decisions and failed approaches rather than daily status.
3. Read `05_代码与实验/README.md` before changing code or running experiments; it is the technical runbook.
4. Treat `01_提案/Project_Proposal_Yu_Yeung_Guo.docx` as the current proposal and `Project_Proposal_Qingcheng_Yu_原始草稿.docx` as archive-only.

If these files conflict, preserve reproducible evidence and ask the team before changing the locked research question.

## Sources of Truth

- `README.md`: current title, evidence boundary, next gate, and teammate onboarding.
- `项目复盘.md`: research rationale, dated decisions, failed approaches, and presentation narrative.
- `05_代码与实验/README.md`: commands, interfaces, artifact rules, and reproduction workflow.
- `05_代码与实验/results/*_{manifest,summary,audit}.*`: exact run counts, timings, token usage, and metrics. Do not copy these numbers into multiple Markdown files.
- `05_代码与实验/results/index.json`: machine-generated discovery index only. Regenerate it after adding or changing experiment artifacts; manifests and audits remain the evidence sources.
- The proposal DOCX and milestone TeX are the content sources for those deliverables. The CVPR template README is upstream vendor documentation and must not be edited.

## Markdown Maintenance Triggers

- A normal code, test, dataset, or experiment-artifact change does **not** require editing every Markdown file.
- For every new model experiment, always save versioned raw/summary/audit/manifest artifacts. Update `README.md` only when the current status or next gate changes. Update `项目复盘.md` only when the evidence changes a research decision, claim, failure analysis, or presentation story.
- When the topic, scope, contribution, or evidence boundary changes, update both `README.md` and `项目复盘.md`.
- When a command, interface, directory layout, dependency, or reproduction procedure changes, update only `05_代码与实验/README.md` unless it also changes project status.
- Put stable collaboration and safety guardrails only in `AGENTS.md`; do not duplicate dynamic results here.
- Never edit the CVPR template's vendor README. Do not create another planning/progress Markdown file unless none of the four sources above can own the information.
- Record failed experiments only when they teach a reusable lesson or alter the next decision. Preserve their immutable manifests, label them non-citable when appropriate, and summarize the lesson in `项目复盘.md`; do not maintain a command-by-command diary.

## Engineering Rules

- Use Python 3.12 or newer.
- Run `python3 -m unittest discover -s tests -v` from `05_代码与实验/` after code changes.
- Keep gold labels, oracle facts, and private approval requirements outside model-visible inputs.
- Keep counterfactual siblings in the same train/dev/test split.
- Fix seeds and save configuration, prompt hashes, raw outputs, model identity, latency, token usage, and manifests.
- Never overwrite an existing experiment prefix. Add a new versioned prefix.
- After adding experiment artifacts, run `python3 scripts/index_experiment_artifacts.py --write` and then `--check` from `05_代码与实验/`. Do not hand-edit `results/index.json`.
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

- Pull `main`, create a focused branch, and make small commits. Use a pull request when a teammate is reviewing or contributing; owner-only maintenance may merge after tests and artifact checks.
- Avoid concurrent edits to DOCX, PDFs, and generated binary figures.
- Before merging, report changed files, tests run, new experiment artifacts, and any claim that must be updated.
