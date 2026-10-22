# Integration Guide

Agent Memory Crash Test is designed first as an offline regression gate. It can
sit beside an existing Agent framework without replacing its memory store,
compactor, tool runtime, or approval mechanism.

## Recommended development loop

1. Select one consequential tool call such as sending, purchasing, deleting,
   publishing, changing permissions, or updating a production record.
2. Capture a sanitized trace with stable event IDs.
3. Define the action's proof obligations and trusted issuers.
4. Apply the current memory strategy separately to each perturbed input. For
   inspectable, source-linked memory, export retained events as `snapshot`
   selectors. For opaque memory, capture the downstream tool behavior instead;
   the current snapshot CLI alone is insufficient. Keep oracle fields out of
   either process.
5. Run full, critical-deletion, and matched-noise siblings in CI.
6. Fail the build on an incorrect route, harmful mutation or missing decisive
   provenance. Give full/noise siblings identical expected routes; alternatively
   assert zero reported noise changes separately. Version 0.1.1 reports noise
   changes but does not enforce that invariant independently of supplied gold.
7. Re-run the same suite when changing the model, system prompt, context budget,
   summarizer, retriever, memory provider, or approval policy.

## Framework adapter boundary

For the current **retained-ID adapter path**, a capture record can contain:

```json
{
  "events": [{"event_id": "...", "role": "...", "content": "..."}],
  "retained_event_ids": ["..."],
  "proposed_action": {
    "actor_id": "...",
    "operation": "...",
    "target_id": "...",
    "scope": {},
    "effective_at": "..."
  }
}
```

This is an adapter-side capture shape, **not** a payload accepted directly by the
CLI. Map the IDs into the contract's `strategies[].snapshots` fields for
`full_evidence`, `remove_action_critical`, and `remove_matched_noise`.
Version 0.1.1 shares each strategy's condition map across the suite; it has no
per-case snapshot map. Use a separate single-case contract for traces with
different event IDs. A generalized multi-case adapter is future work.

Do not infer retention merely because an ID appears in a fluent summary: verify
its source mapping and which canonical records the adapter makes available.
Keep raw credentials,
personal data, and proprietary production content out of the fixture; synthetic
or carefully sanitized traces are preferable for a public suite.

The `proof_sources` selector is an idealized reference over declared fixture
cards. It cannot establish whether an actual framework correctly extracted or
retained evidence. The deterministic audit can rehydrate canonical cards from
retained source IDs; account separately for that external record store, trust
verification and lookup cost when designing a real system.

State diffs in this kit replay the contract author's declared transition. The
kit does not send bookings, payments or production tool calls. Its unsafe labels
are also author-supplied and require review for the intended business policy.

## Provider mechanisms versus application obligations

Official sources checked on **2026-10-23**. These are documented integration
mechanisms, not systems evaluated by our local Qwen benchmark.

| Layer / source | Documented control | What the application still must define |
| --- | --- | --- |
| [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction) | Configurable server threshold or a standalone compact endpoint; the compacted item is encrypted and opaque. | Preserve the returned window according to that endpoint's contract. A retained-ID inspection cannot establish what the opaque item remembers. |
| [Anthropic compaction](https://platform.claude.com/docs/en/build-with-claude/compaction), [threshold controls](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold) | On-demand or threshold-triggered summaries; the threshold API exposes custom instructions and a pause after compaction. | Decide which proof to retain or fetch, then inspect/validate at an appropriate application hook; a summary is not an authorization check. |
| [Anthropic context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing) | Clear older tool results with configurable retention and tool exclusions; the client can retain the original history. | Distinguish active-context removal from deletion of the source log; tool exclusions alone are not action-specific proof validation. |
| [LangChain summarization](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization) | Developer-configured triggers, retention and summary prompt. | Record counter/tokenizer, trigger, prompt and version; do not assume all frameworks count tokens identically. |
| [OpenAI tool guardrails and approvals](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals), [LangChain HITL](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) | Checks and review around proposed tool calls. | Bind authority to exact action arguments and define who can repair a gap. Vendor review choices are not our three route semantics. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Checkpoint/resume execution; an interrupted node restarts on resume. | A persisted approval need not be current or authentic. Make preceding side effects idempotent or move them after review; a checkpoint is not an undo operation. |

**Architectural inference:** test readable and opaque memory differently. With
readable/source-linked memory, inspect retained proof and replay the decision.
With opaque memory, run each perturbed input through the real compaction and
continuation path, then evaluate proposed arguments, permission checks and
outcomes against a separately maintained oracle. Do not translate an opaque
blob into invented source IDs or claim that the current CLI has implemented
this end-to-end behavior adapter. No provider API calls were made in this review.

Before comparing real systems, freeze the model/API version, compaction trigger,
counter/tokenizer, full compactor input, resulting window, external retrieval
receipts, continuation prompt, proposed tool arguments and sandbox outcome.
Equal active-memory budgets do not equal total storage, information access,
latency or monetary cost.

## Runtime use

The deterministic proof validator can inform a runtime gate, but version 0.1 is
not a drop-in authorization service. A production integration should enforce the
final decision next to the side-effecting tool, independently verify identity
and policy, bind approvals to the exact action arguments, and record both the
decision and actual execution outcome.

Conversation memory should be treated as a performance cache. Current authority,
holds, revocations, and other source-of-truth state should be re-read from an
independent service at the action boundary when the application requires it.

## CI outputs

The CLI writes:

- a JSON report containing every condition, retained event, proof card, route,
  registry receipt, and state diff; and
- JUnit XML that common CI systems can display as ordinary test failures.

The exit code is nonzero unless every selected record has the expected route,
zero harmful execution, and complete decisive provenance. `--allow-fail` is for
diagnostic baselines only and should not be used on the release gate.

## Useful next integration, not a new framework

The next engineering acceptance test is one sanitized workflow using an actual
compactor: independently capture all three siblings, export three validated
snapshots in a single-case contract, and reproduce the expected red/green gate
from a clean install. Then check that changing a tool argument invalidates an
old approval. This would establish one real adapter, not universal production
readiness. Opaque continuation adapters and resume/idempotency fault injection
remain explicitly unimplemented extensions.
