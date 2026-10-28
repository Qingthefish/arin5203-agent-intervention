# Closed-Loop Human Intervention

Module: `src/platform_agent_eval/human_intervention_workflow.py` (`human-intervention-v1.1`).

Integration acceptance adds strict response-decision validation before any
approval can be recorded. A raw string, Boolean or missing decision is rejected
rather than falling through to approval and failing during audit logging.
The two added input/path regression tests are separate from the archived v1
scenario matrix. The current development acceptance plan is
`configs/human_intervention_acceptance_v2.json`; the original v1 config and
results remain unchanged, and do not measure the updated implementation.

This module asks what happens after the validator returns `REQUEST_CONFIRMATION`.
Can the agent obtain, check and apply a human reply without opening a new
authorization or execution hole?

## 1. Existing system

`validate_proof_cards` already decides when a gap is repairable. Authority is
missing, an applicable `REPAIR_CHANNEL` card names a responder, and that
responder is listed in `ProofPolicy.confirmable_authority_actors`. Every other
missing obligation, or any applicable hold, routes to `HANDOFF`.

Before this module, nothing at run time consumed that decision. `intervention.resolve_after_confirmation`
is an evaluator-side counterfactual. It reads the private oracle requirements and
builds a perfectly valid approval, so it never checks a real reply. `hitl_causal.py`
studies prompts with oracle follow-up states. `durable_proof_store.py` supplies
point-in-time evidence lookup, which this module reuses.

## 2. Gap

A naive loop treats "yes" as permission to resume. That accepts replies from the
wrong person, for another amount, after the deadline, after a rejection, or
replayed from another request. It also executes on stale evidence and can execute
twice. Section 7 measures this on the same scenarios.

## 3. Method

```text
validator -> REQUEST_CONFIRMATION
  -> ConfirmationRequest (one action binding, one authorized responder, deadline, challenge)
  -> HumanResponse (structured; identity taken from the delivery channel only)
  -> response checks (identity, addressee, current repair authority, binding, state, time)
  -> accepted approval becomes one AUTHORITY ProofCard with request/response provenance
  -> validate_proof_cards again on evidence read at execution time
  -> execute once (COMPLETED) / stop (REJECTED, EXPIRED, CANCELLED) / Handoff (ESCALATED)
```

**States.** `PENDING_CONFIRMATION` and `CONFIRMED` are open. `COMPLETED`,
`REJECTED`, `EXPIRED`, `CANCELLED` and `ESCALATED` are terminal. `ESCALATED`
is the existing Handoff route. No route is added.

**Request creation.** A request is created only when the validator returns
`REQUEST_CONFIRMATION`. Execute needs none, and Handoff is never converted. The
addressee must be the subject of an applicable repair card, and must have a
trusted channel. The request records the action binding hash (actor, operation,
target, scope), the missing obligation, the repair card IDs, the deadline and a
challenge value. Its message names exactly what is being approved.

**Approval as evidence.** An accepted approval becomes an `AUTHORITY` card issued
by a declared confirmation issuer. The policy must list that issuer in
`authority_issuers`, otherwise no request is created. The card covers only the
bound action, starts at the reply time and lasts for the approval TTL. It carries
`(request_id, response_id)` as provenance. It repairs authority only. Clearance,
recovery, delegation and holds are revalidated as before.

**Response checks, in order.**

| Check | Failure reason |
| --- | --- |
| request exists | `UNKNOWN_REQUEST` |
| response ID not seen before | `DUPLICATE_RESPONSE` (no effect) |
| channel bound to a principal | `UNAUTHENTICATED_CHANNEL` |
| body identity claim, if any, equals that principal | `CLAIMED_IDENTITY_DIFFERS_FROM_CHANNEL` |
| challenge matches this request | `CHALLENGE_MISMATCH_POSSIBLE_REPLAY` |
| operation, target, scope and action hash match | `*_MISMATCH` |
| request still open | `REQUEST_NOT_OPEN_<state>` |
| principal is the addressee | `RESPONDER_NOT_ADDRESSED` |
| repair authority still applies now | `RESPONDER_AUTHORITY_LAPSED` (escalates) |

A rejection closes the request as `REJECTED`, and a later approval cannot reopen
it. A rejection or question after an approval closes it as `ESCALATED`. A second
approval is a no-op. A clarification leaves the request pending.

**Execution.** `execute(request_id, action)` refuses unless the request is
`CONFIRMED` and the action has the same binding. Changed parameters need a new
request. It then reads evidence at the current clock, re-runs the unchanged
validator with the approval card added, calls an optional `pre_commit_check`,
and applies the declared transition once. A completed request returns
`ALREADY_EXECUTED`, and the ledger refuses a second mutation of the same binding.

**Time.** The workflow owns a logical clock that only moves forward. Pending
requests expire at their deadline, and confirmed approvals expire at their TTL.
Reply timestamps are recorded but never read, so backdating has no effect.

## 4. Threat model

Considered: wrong responder, self-declared identity or `verified` flags in the
reply body, a known channel claiming another name, approval of a different
amount or target, late or backdated replies, replay of an old approval, duplicate
delivery, approve-then-reject conflicts, cancellation, responder authority
revoked while waiting, holds, revoked clearance or stricter policy appearing
before execution, an unavailable evidence source, and repeated execute calls.

Not considered: a compromised trusted channel or directory, a malicious but
genuinely authorized responder, collusion, social engineering of the responder,
and denial of service.

## 5. Trust and consistency boundaries

- **Identity.** `ResponderDirectory` is a fixture that maps channel IDs to
  principals. It stands in for an authenticated session. It is not real identity
  verification, and the approval card's `authenticated=True` holds only inside
  this simulation.
- **Authority.** Authority comes from existing proof cards and policy. The module
  does not model organizational policy beyond `ProofPolicy`.
- **Time and ordering.** Events are processed one at a time on a logical clock.
  Real asynchronous delivery, network delay and concurrent replies are not
  modelled.
- **Execution.** `SimulatedActionLedger` applies a declared state change. Real
  tools need their own idempotency key and commit-time check. No Commit-Time
  Freshness Gate was wired into this workflow. The repository now includes a
  separate commit-time gate; `pre_commit_check` remains a check-only hook,
  not an atomic execution adapter. Nothing here is atomic against an external system.
- **Evidence grounding.** This module consumes typed cards and does not call
  the optional field-grounding layer. No combined end-to-end guarantee follows
  from testing the modules separately.

## 6. Usage

```python
from platform_agent_eval.human_intervention_workflow import (
    InterventionWorkflow, ResponderDirectory, SimulatedActionLedger,
    TimelineEvidenceProvider, TrustedChannel, response_for,
)

workflow = InterventionWorkflow(provider, directory, ledger,
                                start_time=t0, confirmation_issuer="confirmation-ledger")
start = workflow.request_confirmation(action)          # None request unless Confirm
workflow.advance_to(t1)
workflow.receive(response_for(start.request, "resp-1", "chan-owner"))
outcome = workflow.execute(start.request.request_id, action)
workflow.audit                                          # ordered AuditEntry records
```

`TimelineEvidenceProvider` combines a policy timeline, static cards, an optional
`DurableProofStore` and declared outages. Any callable that takes an
`ActionRequest` and returns an `EvidenceSnapshot`, or raises `EvidenceUnavailable`,
can replace it.

## 7. Evaluation

`scripts/run_human_intervention_evaluation.py` replays 25 scenario types in three
new families (release deploy, repository access, shipment release with required
delegation). That gives 75 episodes. The families share one script, so the
scenario type is the unit of analysis. The development unit tests use a separate
vendor-payment family. The workflow and the scenario matrix were hashed in
`configs/human_intervention_eval.json` with four hypotheses before the single run.

Configurations, all with the same initial routing and request creation:

- `stop_at_confirm` is the existing behaviour. Confirm ends the episode.
- `naive_resume` resumes the agent's current action after any approval for a known
  request, with no other checks. It is a strawman design, not repository code.
- `proposed` is the full workflow.
- `ablate_*` switches off exactly one check.

Artifacts: `results/human_intervention_deterministic_v1_{raw.jsonl,summary.csv,audit.json,manifest.json}`.
The audit holds every metric and failing scenario type.

### Results (v1)

Safety, over 75 episodes:

| Configuration | Incorrect executions | Unsafe episodes | Duplicate executions | Invalid replies accepted |
| --- | --- | --- | --- | --- |
| stop_at_confirm | 0 | 0 | 0 | 0% |
| naive_resume | 60 | 57 | 9 | 100% |
| proposed | 0 | 0 | 0 | 0% |
| no channel authentication | 6 | 6 | 0 | 17% |
| no responder authority | 6 | 6 | 0 | 25% |
| no action binding | 6 | 6 | 0 | 17% |
| no time enforcement | 3 | 3 | 0 | 8% |
| no revalidation | 12 | 12 | 0 | 0% |
| no deduplication | 9 | 6 | 9 | 0% |

Efficiency. Seven scenario types (21 episodes) should end in exactly one
execution. The proposed workflow completed all of them with one request each.
`stop_at_confirm` completed none, so every legitimate repair would still need a
person to finish the job. `naive_resume` completed only 12 of 21 exactly, because
duplicates and the replayed approval caused extra executions. The proposed
workflow escalated every scenario where the specification requires Handoff.

Each removed check reopens a specific failure. Channel authentication guards
against forged identity claims. Responder authority guards against wrong
responders and revoked repair channels. Binding guards against wrong amounts and
targets. Time guards against late replies. Revalidation guards against holds,
revoked clearance, stricter policy and outages that appear while waiting.
Deduplication guards against duplicate and repeated execution. Revalidation had
the largest effect. Time enforcement partly overlaps with revalidation, because
the approval card's validity window also stops a stale approval at execution.

**How to read this.** The same author wrote the specification, the workflow and
the scenarios. Full conformance of `proposed` is therefore expected and shows only
that the implementation matches its specification. The informative results are
the ablations and the naive baseline on identical scripts. Safety parity with
`stop_at_confirm` is trivial, because that baseline never executes. The
comparison that matters there is completion.

## 8. Limitations

- Simulated channel-bound identity, not real authentication.
- A deterministic single-threaded workflow, not an asynchronous distributed system.
- `ProofPolicy` authorization checks, not real organizational policy enforcement.
- Simulated state transitions, not production tool execution.
- Scripted responders, not observed human behaviour. No user study was run.
- Only authority gaps are repairable, because that is what the existing validator
  allows. Multi-obligation repair is out of scope.
- One addressee per request. Multi-approver quorums are not modelled.

## 9. Positioning

Human-in-the-loop approval, workflow state machines, role-based authorization,
idempotency keys and replay protection are established techniques. Nothing here
is a new invention. The contribution is narrower. It integrates them with this
project's proof cards and validator at the agent's execution boundary, and it
evaluates which checks matter on matched scenarios. It extends the project's
Confirm route from a routing label to a verifiable repair. It complements work on
abstention, asking for help and delegated authority by testing what happens after
the agent correctly decides to ask.

## 10. Reproduction

From `05_代码与实验/`:

```bash
python3 -m unittest tests.test_human_intervention_workflow -v
python3 scripts/run_human_intervention_evaluation.py --config configs/human_intervention_acceptance_v2.json
```

The second command prints the current acceptance plan only. The original v1
config and prefix remain archived; its code is preserved in contributor commit
`c0e0cad`. A new formal run needs a new `output_prefix`, `--run
--acknowledge-experiment-plan`, and `--allow-dirty-worktree` only when
uncommitted changes must be recorded.
