# Integration Guide

Agent Memory Crash Test is designed first as an offline regression gate. It can
sit beside an existing Agent framework without replacing its memory store,
compactor, tool runtime, or approval mechanism.

## Recommended development loop

1. Select one consequential tool call such as sending, purchasing, deleting,
   publishing, changing permissions, or updating a production record.
2. Capture a sanitized trace with stable event IDs.
3. Define the action's proof obligations and trusted issuers.
4. Apply the current memory strategy separately to each perturbed input and
   export its retained events as `snapshot` selectors. Keep oracle fields out
   of this process.
5. Run full, critical-deletion, and matched-noise siblings in CI.
6. Fail the build on an incorrect route, harmful mutation, missing decisive
   provenance, or noise-induced instability.
7. Re-run the same suite when changing the model, system prompt, context budget,
   summarizer, retriever, memory provider, or approval policy.

## Framework adapter boundary

An adapter only needs to produce:

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

Map the retained IDs into a contract's `snapshot` strategy. Keep raw credentials,
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
