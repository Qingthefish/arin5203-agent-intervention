# Related Work and Claim Boundary

Agent Memory Crash Test integrates established memory, intervention, and
stateful-evaluation ideas into a course-scale regression contract. It makes no
priority claim, introduces no new memory algorithm, and does not establish a
state-of-the-art ranking.

Primary sources and protocol descriptions below were checked on **2026-10-23**.
Reading a paper or inspecting a repository does not independently reproduce its
results. “Borrowed” identifies a design influence, not reused implementation.

## Closest mechanisms and evaluation protocols

| Primary work | Actual mechanism or protocol | Borrowed here and non-reproduction boundary |
| --- | --- | --- |
| [Mem2ActBench: A Benchmark for Evaluating Long-Term Memory Utilization in Task-Oriented Autonomous Agents](https://arxiv.org/html/2601.19935v1) | Tests memory-grounded tool parameters; its main comparison supplies the correct tool to isolate parameter grounding. | Evaluate memory through downstream actions. Our task checks authorization evidence and intervention routes, rather than reproducing its dataset or memory-framework comparison. |
| [Governance Decay: How Context Compaction Silently Erases Safety Constraints in Long-Horizon LLM Agents](https://arxiv.org/html/2606.22528v2) | ConstraintRot compares absent, visible, compacted, and pinned policies; deterministically grades terminal tool calls and proposes Constraint Pinning. | Motives for constraint retention and controlled omission. Our generic pinning is not its defense implementation; our simulator and repairability-aware routes use a different protocol. The source studies compaction, not length alone. |
| [The Compaction Cliff in Long-Running AI Agent Memory](https://arxiv.org/html/2608.22752v1) | Knowledge Triage already combines typed retention, a deterministic post-compaction verifier, restoration or Unsafe escalation, and downstream behavioral evaluation. | This is a direct method neighbor. Typed retention plus verification and fail-closed behavior are established mechanisms. Our implementation uses action-specific proof types, retained-source lookup, and Execute/Confirm/Handoff; it does not reproduce TypeCompact or its classifier. |
| [Adapting Context Compression for Long-Horizon Agents with Counterfactual Continuations](https://arxiv.org/html/2609.36526v1) (PAIR) | Restores the same environment checkpoint, repeatedly continues from pre/post-compression context with later compression disabled, and uses localized evidence to adapt compression prompts. | Inspires holding the action/state fixed while perturbing evidence. Our deletion siblings and next-action checks do not implement PAIR's continuation estimator or prompt adaptation. |
| [AgentAbstain: Do LLM Agents Know When Not to Act?](https://arxiv.org/html/2607.10059v1) | Pairs should-act/should-abstain tasks through a controlled instruction, tool, or environment change; operational scoring combines a commit check with a response judge. Clarification and refusal both count as abstention. | Test restraint together with autonomous action, including whether a mutation happened before the agent abstained. Our Confirm and Handoff distinguish repairable proof gaps from operator-required intervention; this is not its binary abstention protocol. |
| [HiL-Bench (Human-in-Loop Benchmark): Do Agents Know When to Ask for Help?](https://arxiv.org/html/2604.09408v4) | SWE/SQL blockers emerge through exploration; a simulated ask_human tool returns registered resolutions, and Ask-F1 balances targeted help-seeking against over-asking. | Motivates explicit repair channels and unnecessary-intervention measurement. We do not reproduce Ask-F1, train help-seeking, or measure a real human workflow. |
| [DelegationBench: Measuring When AI Agents Should Ask Before Acting](https://arxiv.org/html/2610.05532v1) | Separates acting, asking permission, requesting information, and refusing; examines matched pairs, elicitation sensitivity, and judgment-to-tool-action gaps. | Permission is distinct from a missing fact, and label agreement alone is insufficient. Its four labels do not map directly to our three routes; we do not reproduce its human-reference or Tool-Loop studies. The official repository is now [DelegationCheck](https://github.com/PieLord757/delegation-check). |

## Compression baselines and stateful evaluation

| Primary work | Relation to this project |
| --- | --- |
| [U-Fold: Dynamic Intent-Aware Context Folding for User-Centric Agents](https://aclanthology.org/2026.findings-acl.897/) | Maintains full history and dynamically extracts an evolving intent summary, to-do list, and relevant tool log. U-Fold-lite borrows the separation of intent and tool evidence; a single budgeted checkpoint is not its multi-turn algorithm or a paper reproduction. |
| [ACON: Optimizing Context Compression for Long-horizon LLM Agents](https://proceedings.mlr.press/v306/kang26b.html), [official implementation](https://github.com/microsoft/acon) | Optimizes natural-language compression guidelines from trajectory failures and distills compressors. It motivates downstream utility evaluation; our summary prompts do not implement its optimization or distillation. |
| [StateComp: Learning When to Compress History in Long Horizon Agents](https://arxiv.org/html/2609.27298v1) | Learns state-conditioned KEEP/READY routing and applies span/token gates before summarization. It motivates task-dependent replaceability; we do not train its router. Its task-performance notion of safe compression does not establish authorization safety. |
| [τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains](https://arxiv.org/abs/2406.12045), [ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities](https://arxiv.org/abs/2408.04682) | Provide evaluation precedents: final database-state comparison and reliability across trials (τ-bench), and state dependencies plus intermediate/final trajectory milestones (ToolSandbox). Our deterministic mutation replay borrows these principles; it does not run either benchmark or match their full interactive environments. |

## Integration contributed by this toolkit

The reusable contract connects these mechanisms:

1. bind proof obligations to one proposed state-changing action;
2. compare complete evidence, one critical deletion, and a matched noise deletion;
3. check retained-source provenance alongside route correctness;
4. distinguish autonomous execution, confirmation through a declared authenticated
   repair channel, and operator handoff; and
5. replay the declared state mutation and emit regression-test results.

[Promptfoo already supports JSON/JUnit exports](https://www.promptfoo.dev/docs/configuration/outputs/)
and [DeepEval supports thresholded evaluation tests in CI](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd).
JSON, JUnit, and CI integration are engineering choices, not research novelty.
This project packages a narrow action-evidence test contract; it does not claim
that the combination is the first available implementation.

## Protocol and evidence boundaries

- **Matching is protocol-specific.** The frozen course compaction experiments use
  same-role, adjacent critical/noise events with equal word counts. The reusable
  JSON contract requires the same role and exactly equal UTF-8 byte lengths.
  Neither condition establishes equal token length. Do not relabel the frozen
  experiment as byte-matched because the later contract is stricter.
- **The budget is active memory.** The main audit can rehydrate canonical proof
  cards through retained source IDs. External records, storage, and lookup costs
  are outside that raw-token budget. This is source retention plus lookup and
  validation, not fully self-contained compressed proof. Typed capsules also
  encode deterministic action-scope/valid-now bits computed from those records;
  they are not merely a different prompt for unconstrained prose compression.
- **Provenance checks have limited semantics.** A valid retained event ID measures
  source availability; it does not prove that the source entails every claim in
  a model's explanation. The natural-language extension's quote-containment check
  likewise does not establish entailment or cryptographic authenticity.
- **Evidence creation is assumed in the main study.** Authenticated source-linked
  cards and domain obligations are provided. The study does not establish reliable
  extraction from arbitrary prose or real signature verification. Selecting
  author-declared proof sources in a deterministic fixture is not evidence that a
  real compactor discovered them.
- **Omission and compaction are distinct interventions.** Critical deletion before
  compaction probes missing observational evidence. A downstream audit cannot
  recover an active hold that never reached its input. Registry rescue assumes an
  authoritative external record; it does not solve consistency, issuer compromise,
  availability, revocation races, or time-of-check/time-of-use failures.
- **Routes and state diffs are simulated.** Confirm/Handoff specify intervention
  semantics; authenticated follow-up and human burden require separate evaluation.
  The main frozen harmful-Execute score is an authored unsafe flag AND Execute.
  Later replay/toolkit state diffs follow a declared transition, not independently
  executed payments, bookings, or deployments.
- **Results are local to the evaluated design.** Strong summaries can tie after
  the same audit. A small, correlated synthetic benchmark and a passing CI suite
  do not establish universal typed-memory superiority or production safety.

Production teams should keep current permissions, holds, and revocations in
authoritative services and revalidate them beside the side-effecting tool. The
toolkit is a pre-deployment regression instrument for that architecture.
