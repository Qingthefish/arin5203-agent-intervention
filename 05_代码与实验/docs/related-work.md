# Related Work and Claim Boundary

Agent Memory Crash Test deliberately combines established ideas rather than
claiming a new memory algorithm.

## Closest research directions

- [Mem2ActBench](https://arxiv.org/abs/2601.19935) evaluates whether agent
  memory supports later actions rather than only retrieval.
- [Governance Decay](https://arxiv.org/abs/2606.22528) studies how safety and
  governance constraints weaken across long agent trajectories.
- [The Compaction Cliff](https://arxiv.org/abs/2608.22752) examines typed
  retention, constraint verification, and unsafe fallback after compaction.
- [PAIR](https://arxiv.org/abs/2609.36526) motivates matched comparison of
  continuations from the same state under full and compacted context.
- [AgentAbstain](https://arxiv.org/abs/2607.10059) studies when an agent should
  act or abstain.
- [HiL-Bench](https://arxiv.org/abs/2604.09408) studies when incomplete
  specifications should trigger human assistance.
- [DelegationBench](https://arxiv.org/abs/2610.05532) studies when agents
  should act, ask permission, request missing information, or refuse, using
  matched scenario pairs.

## What this toolkit adds

The contribution is the cross-layer test contract:

1. bind proof obligations to one proposed state-changing action;
2. compare complete evidence, one critical deletion, and one equal-byte noise
   deletion;
3. require retained-source provenance rather than accepting a correct label
   supported by invented evidence;
4. distinguish autonomous execution, authenticated confirmation, and operator
   handoff; and
5. replay the external state mutation and emit machine-readable CI results.

A non-exhaustive literature and repository search found adjacent components,
but not a directly reusable project packaging this entire protocol as a
declarative JSON/JUnit gate. That is a positioning statement, not a priority
claim.

## What this toolkit does not establish

- It does not prove that one compaction method is universally best.
- It does not infer trustworthy proof cards from arbitrary free text.
- It does not make conversation memory an authorization source of truth.
- It does not model distributed consistency, compromised issuers, or runtime
  races in the reference registry.
- A passing suite is not evidence that an application is safe in production.

Production teams should keep current permissions, holds, and revocations in
authoritative services and revalidate them beside the side-effecting tool. The
toolkit is a pre-deployment regression instrument for that architecture.
