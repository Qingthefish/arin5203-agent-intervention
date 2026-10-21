# Authoring a Memory Crash-Test Contract

A crash test starts from a proposed state-changing action, not from a generic
question-answering prompt. The author states which proof obligations apply,
where each proof came from, and what external state would change if execution
were allowed.

## 1. Define one action

`action` binds the actor, operation, target, exact scope, and effective time.
Proof is checked against all five fields. A card for another actor, target,
scope, operation, or validity window is ignored rather than treated as partial
authority.

## 2. Define trusted issuers and obligations

`policy` lists trusted issuers separately for:

- `AUTHORITY`: who authorized this actor to perform this action;
- `CLEARANCE`: whether ordinary policy checks passed;
- `ACTIVE_HOLD`: a currently applicable blocker;
- `DELEGATION`: whether authority can pass to the acting subagent;
- `RECOVERY`: whether the change has an accepted recovery path;
- `REPAIR_CHANNEL`: an authenticated person who can repair a missing authority
  fact with one answer.

These types are intentionally not interchangeable. Clearance is not authority,
and a generic user confirmation cannot override an operator-only hold.

## 3. Link cards to source events

Every proof card names one or more `source_event_ids`. A card is available from
conversational memory only when all of its source events survive the selected
memory strategy. This lets the report distinguish a grounded decision from a
route that merely happened to match the expected label.

Cards should be created when authenticated evidence originates. The reference
runner does not claim that an LLM can reliably reconstruct typed proof from
arbitrary prose after the fact.

## 4. Choose matched deletion events

Each base case identifies:

- one `critical_event_id` whose removal should change the safe route; and
- one `matched_noise_event_id` with the same role and exactly the same UTF-8
  byte length whose removal should not change the route.

The runner rejects contracts where those two events do not satisfy the match.
This turns "the agent forgot something" into a controlled causal comparison.

## 5. Declare the oracle and state transition

`expected_decisions` defines the expected route for all three conditions.
`unsafe_if_executed` identifies conditions in which execution would be harmful.
`state.before` and `state.after` define the externally visible mutation. The
runner applies `state.after` only for `AUTO_EXECUTE`, making a harmful route
visible as a state diff rather than only a label mismatch.

## 6. Add memory strategies

Version 1 supports four deterministic selectors:

- `all_visible`: every event not deleted by the condition;
- `proof_sources`: visible events linked to declared proof cards;
- `recent_events`: the last `event_count` visible events;
- `snapshot`: exact retained-event IDs imported from an external compactor.

`snapshot` is the main integration boundary for a real Agent stack. Capture the
IDs retained by the production compactor and place them under the three matched
conditions; the crash-test runner remains independent of the model provider.

## 7. Treat registries as authoritative reads, not extra prose

An optional `durable_store` contains versioned card records that live outside
conversational memory. Registry mode filters records by operation, target,
commit time, revocation, and integrity, then sends returned cards through the
same proof validator. Retrieval never bypasses issuer, subject, scope, validity,
authentication, or transferability checks.

The local reference store is intentionally simple. Production systems must add
their own consistency, availability, identity, revocation, and time-of-check /
time-of-use controls.
