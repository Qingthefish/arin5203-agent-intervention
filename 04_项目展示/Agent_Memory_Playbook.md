# Agent Memory Playbook

## The takeaway

**Conversation may be compressed, but the proof required for a state-changing action must be preserved or revalidated.**

The practical problem is not “make the summary more complete.” It is to keep conversational memory and action proof on different reliability paths. A fluent summary may be useful for dialogue continuity while still being an unsafe basis for changing a booking, sending money, granting access, or deploying a system.

## Who owns this problem?

A model or Agent framework may determine the context window, tokenizer, truncation behavior, or when an automatic summary is triggered. The application team still owns the part that depends on business meaning: which tool calls mutate state, what authority each call requires, where current holds and permissions live, who may repair a missing fact, and what must happen when proof cannot be read.

Choosing a larger model or a different API may delay compaction or improve summarization, but it cannot define these product-specific proof obligations. Treat provider-managed memory as a useful cache; keep permission, policy, and hold state in an application-controlled source of truth.

## Six design rules

### 1. Define proof obligations before writing the compactor

For each state-changing tool, write down what must be true before execution. Our reusable set is:

- **authority** — who may authorize this action;
- **scope** — which action, target, amount, tenant, or parameter is covered;
- **validity** — whether the evidence is current and authenticated;
- **blocking conditions** — holds, prohibitions, conflicts, and unresolved policy checks;
- **recovery** — whether reversal or a safe fallback exists;
- **repair channel** — who can supply a missing fact or take control.

This list is action-specific. Do not ask a generic summarizer to guess what will matter later.

### 2. Create typed proof records when evidence originates

When an authenticated approval, delegation, hold, or recovery plan appears, store it as a small record with provenance. At minimum retain:

`type · issuer · subject · action · target/scope · valid-until · source event · authentication · transferability`

The source event remains the audit anchor. The typed record is a compact control representation, not a replacement for the original log.

### 3. Compact conversation and proof separately

Use semantic summaries for goals, preferences, and narrative continuity. Use deterministic inclusion and validation rules for action proof. Filling a token budget with recent raw messages or plausible prose must not silently recreate authority.

In our held-out run, strong summaries matched audited route accuracy, but their route citations were less consistently grounded in visible sources. A correct route is not enough when its stated approval never existed in active memory.

### 4. Revalidate at the tool boundary

Immediately before the tool call, check the proof records against the proposed action:

- Does the issuer have the right role?
- Do action, target, scope, and parameters match?
- Is the proof still valid now?
- Is any active hold visible?
- Is recovery adequate for this operation?
- Does each decisive claim cite a source still present in active memory?

Treat this as a control-plane check, not another free-form “please review” prompt.

### 5. Route the gap, not just the risk score

- **Execute** when all mandatory proof obligations are satisfied and no blocking condition is active.
- **Confirm** when one authenticated answer from the current user can repair the exact missing fact.
- **Handoff** when authority belongs to another role, policy remains blocked, recovery is inadequate, or a user answer cannot legitimately repair the gap.

Always Confirm is not a safe default: it creates unnecessary intervention and can invite an ordinary requester to “approve” something only an operator may authorize.

### 6. Crash-test memory with matched siblings

For every important workflow, test three versions of the same history:

1. complete evidence;
2. remove exactly one action-critical fact;
3. remove equal-size noise from the same role and nearby position.

Then measure both the decision and its evidence chain:

- route accuracy and harmful state changes;
- unnecessary Confirm/Handoff;
- decisive-evidence retention;
- citation grounding and contradictions;
- changes caused by deleting noise;
- helpful versus harmful audit corrections.

If critical deletion and noise deletion behave the same, the Agent may be following surface cues instead of evidence.

## What the held-out experiment supports

On 11 untouched bases / 33 matched contexts under a 384 raw-token budget, the typed-proof method plus deterministic audit routed all 22 full and matched-noise contexts correctly. It retained every visible card and critical event, made 10 helpful corrections, made zero harmful corrections, and produced no harmful execution or unnecessary intervention on those stable contexts.

The result does **not** show that only typed memory can route correctly. Three strong summary baselines also reached 22/22 after the same provenance-aware audit. The observed distinction was evidence-chain inspectability: typed proof reached 100% visible-source citation precision, while the comparison summaries were lower.

## What this architecture cannot solve

No downstream compactor or reviewer can preserve a prohibition that disappears before it receives the history. The held-out set deliberately contains three hidden-active-hold siblings; all three produced harmful Executes because every visible proof suggested the action was allowed.

That boundary requires a separate upstream control:

- durable policy or hold stores queried at action time;
- event-delivery monitoring and checkpoint integrity;
- versioned authorization services;
- fail-closed handling when required sources are unavailable.

Memory design is one control layer, not the whole safety system.

## One-slide version

> **Separate chat memory from action proof.**  
> Capture typed, source-linked evidence when it appears; preserve it independently of conversational summaries; revalidate it immediately before a state-changing tool call; route repairable gaps to Confirm and non-repairable gaps to Handoff; test the design by deleting one critical fact versus equal-size noise; and monitor upstream evidence loss because no compactor can recover an event it never received.

## Five questions to ask during Agent iteration

1. What exact proof does this tool call require?
2. Where is each proof item created, authenticated, and versioned?
3. Can compaction remove it or replace it with unsupported prose?
4. Can the Agent distinguish a question the user can answer from authority only an operator holds?
5. What happens if a blocking event never reaches active context at all?

## Minimal build order

1. List every tool that can book, pay, send, deploy, grant, delete, or otherwise change external state.
2. Define that tool's proof contract before tuning its memory prompt.
3. Store authenticated approvals, delegations, holds, and recovery plans as source-linked records when they originate.
4. Let conversational memory summarize freely, but re-read durable authority and hold state immediately before mutation.
5. Validate the proposed action against both sources and route to Execute, Confirm, or Handoff.
6. Add matched memory crash tests to regression evaluation before shipping the next Agent iteration.
