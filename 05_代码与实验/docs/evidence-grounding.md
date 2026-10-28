# Field-Level Evidence Grounding

Module: `src/platform_agent_eval/evidence_grounding.py` (`evidence-grounding-v1`).

Integration note (29 Oct): the lexical verifier is unchanged. The archived v1
result below used NL-v1 templates; main now generates repaired NL-v2 templates
with literal operations. The current compatibility plan is
`configs/evidence_grounding_acceptance_v2.json`, which pins both the NL version
and the complete derived-context hash. Unit acceptance is separate from the
archived result, and no formal v2 result was generated. Canonical claim fixtures
used in these tests are not extraction-model outputs.

This layer sits between natural-language claim extraction and the frozen
proof-card validator. It asks one narrow question. Does the cited message
actually support each field of the extracted claim?

```text
message history
  -> existing extractor output (JSON claims with event_id and source_quote)
  -> existing parser (schema, types, quote containment; malformed output fails closed)
  -> evidence grounding (this module; field statuses, restrictive-cue scan)
  -> existing validate_proof_cards (unchanged)
  -> Execute / Confirm / Handoff
```

## 1. Gap this addresses

The existing parser checks that a quote occurs in the cited event. It does not
check that the claim's kind, issuer, subject, operation, target, scope, window,
authentication flag or transferability are stated by that event. The offline
scorer compares fields with gold cards, but gold cards do not exist at run time.

A concrete counterexample from the existing `nl-evidence-v1` contexts shows the
gap. Cite a signed freeze message, but label it `AUTHORITY` with the trusted
authority issuer and the acting agent as subject. The quote exists, the claim is
well formed, and the baseline routes to `AUTO_EXECUTE` on an unsafe action. The
authority issuer named in that claim does not appear in the message at all.

A second gap is omission. If the extractor drops a hold claim, the parse is
still valid and nothing downstream sees the hold.

## 2. Threat model

In scope are extractor errors that produce a well-formed claim with a real
quote but an unsupported value. Examples are a denial or freeze read as
approval, an expired or revoked approval read as current, action fields copied
onto a message that states other values, a relayed message marked as
authenticated, a condition or hedge left out of the quote, and an omitted
restrictive message.

Out of scope are forged messages, compromised registries, adversarial text
written to defeat the cue lists, coreference across messages, and any
authentication of senders. The module never makes a claim more trusted. It
can only remove permissive claims or force Handoff.

## 3. Three different checks

| Check | Question | Where |
| --- | --- | --- |
| Literal citation validation | Does the quote occur in the cited event? | existing `parse_extraction_output` |
| Semantic grounding (narrow) | Does the cited event state each claimed field, without a contrary cue? | this module |
| Authentication | Did the stated issuer really send it, and is the signature valid? | not implemented; needs an authenticated source |

A `SUPPORTED` authentication field means only that the text reports successful
authentication, for example "signature verified". It does not verify anything.

## 4. Status vocabulary

Every field gets exactly one status.

- `SUPPORTED`. The cited event states the value inside the supported profile, and
  no in-profile cue contradicts it.
- `CONTRADICTED`. The event states a different value or the opposite polarity.
- `INSUFFICIENT_EVIDENCE`. The value is not stated in a recognisable form, the
  statement is hedged or conditional, or the text is outside the profile.

A claim is `CONTRADICTED` if any field is. Otherwise it is
`INSUFFICIENT_EVIDENCE` if any field is. Otherwise it is `SUPPORTED`. Ambiguity
is never treated as support.

## 5. Field rules

The full cited event is checked, not only the quote. This catches a condition or
denial outside a selectively short quote. Each field result records whether its
evidence lies inside the quote.

| Field | SUPPORTED when | CONTRADICTED when |
| --- | --- | --- |
| kind (permissive) | a cue for that kind is present and not negated | a hold, prohibition, denial or revocation cue is attributed to the action, or the kind cue is negated |
| kind (`ACTIVE_HOLD`) | a hold or prohibition cue is attributed to the target | the event reports the hold lifted or absent |
| issuer, subject | the identifier occurs as a whole token | never (absence is insufficient) |
| subject of clearance, hold, recovery | it equals the target (existing card convention) | |
| operation | UPPER_SNAKE name, or its words in order with inflection and at most two words between | never |
| target | whole-token match | the event says it does not cover the target |
| scope string | whole-token match (`prod-north` does not match `prod-north-old`) | the key is followed by another value |
| scope number | the number occurs (thousands separators allowed) | a currency-tagged amount or keyed value differs |
| scope boolean | key word stated with matching polarity | opposite polarity stated |
| validity | both claimed ISO timestamps occur in the event | the event states another window, or reports expiry while the claimed window covers the action time |
| authentication (`verified: true`) | a positive report such as "signed" or "signature verified" | "unverified", "signature check failed", "claims to be from" and similar |
| transferable (`true`) | "transferable" stated | "not transferable" or "non-transferable" |
| qualification (permissive only) | no hedge, condition, request or counterfactual cue | never (these are insufficient) |

`verified: false` and `transferable: false` are recorded as `NOT_ASSERTED` and
pass, because they cannot create permission. Forwarded or relayed messages
without an explicit failure are insufficient for authentication.

Negation uses a clause-local window of up to four preceding tokens that stops at
"and", "or", "but" or a comma. A restrictive cue is attributed to the action when
its sentence names the target, or names no identifier-like token at all. A
sentence that names only another identifier-like token (containing a digit, or
two hyphens, or a known issuer or actor) is attributed elsewhere.

## 6. Gate semantics and failure layers

`ground_extraction(action, policy, parse, events, pre_verified_cards=())`:

1. Malformed extraction output routes to Handoff (`EXTRACTION_FORMAT`), as before.
2. Permissive claims reach the validator only when every field is `SUPPORTED`.
   Removing a permissive card can only make the validator's route more cautious.
3. `ACTIVE_HOLD` claims are always passed through, whatever their status.
   Grounding never weakens blocking evidence.
4. Every non-structured event linked to the action is scanned for hold,
   prohibition, denial and revocation cues. An event is linked when it names the
   target, or when a claim cites it with the action target. A signal is
   accounted for only when a `SUPPORTED` `ACTIVE_HOLD` claim cites the same event.
   Any unaccounted signal routes to Handoff.
5. The final route is the more cautious of the grounded route and the baseline
   route on the same parse. The gate cannot be more permissive than the baseline.

No fourth route is added. `failure_layer` records why the route was taken.

| Layer | Meaning |
| --- | --- |
| `EXTRACTION_FORMAT` | malformed extractor output |
| `UNACCOUNTED_RESTRICTIVE_EVIDENCE` | a linked restrictive cue was not represented by a supported hold claim |
| `GROUNDING_CONTRADICTION` | an excluded, otherwise applicable claim was contradicted by its source |
| `GROUNDING_ABSTENTION` | excluded unsupported claims changed the route |
| `AUTHORIZATION_HOLD` | the unchanged validator found an applicable hold |
| `EVIDENCE_UNAVAILABLE` | an obligation is missing although grounding changed nothing |
| `REPAIRABLE_AUTHORITY_GAP` | Confirm through the existing repair channel |
| `NONE` | Execute with all obligations met |

`pre_verified_cards` lets typed records from an authenticated structured source
(for example the durable proof store) bypass grounding. Their source events are
not rescanned.

## 7. Usage

```python
from platform_agent_eval.evidence_grounding import ground_extraction, ground_nl_context
from platform_agent_eval.natural_language_evidence import parse_extraction_output

parse = parse_extraction_output(model_json, visible_events)
result = ground_extraction(action, policy, parse, non_system_events)
result.decision            # Execute / Confirm / Handoff
result.baseline_decision   # existing pipeline on the same parse
result.claim_groundings    # per-claim, per-field statuses and reasons
result.unaccounted_signals # restrictive cues with event IDs
```

`ground_nl_context(context, parse)` adapts the existing `NLContext` and drops the
system prompt. Neither function reads gold routes, gold cards, scenario IDs or
expected labels.

## 8. Evaluation protocol

`scripts/run_evidence_grounding_evaluation.py` compares the baseline (quote
presence plus the unchanged validator) with the same pipeline plus grounding,
on identical inputs. It is deterministic and makes no model calls.

- **Development.** Unit tests in `tests/test_evidence_grounding.py` use a deploy
  family and the existing NL templates. The verifier was tuned only on these.
- **Freeze.** The verifier hash was recorded before the evaluation cases were
  written. The case-module hash and four hypotheses were recorded before the
  first run. The runner refuses to run if either hash changes.
- **Part A.** 58 author-written cases in three new families (dataset deletion,
  repository access, shipment release with delegation). 48 are main cases and 10
  are falsification cases designed to break the lexical rules. Each case has one
  focus claim with a gold status, gold unsupported fields and a gold route.
  Routes are scored twice. `end_to_end` grounds the background evidence too.
  `focus_isolated` passes background evidence as pre-verified structured cards.
- **Part B.** Faithful and corrupted extractions of the 120 existing
  `nl-evidence-v1` contexts. These templates were visible during development, so
  Part B is a development stress test.

Artifacts: `results/evidence_grounding_deterministic_v1_{raw.jsonl,summary.csv,audit.json,manifest.json}`.
The audit holds every metric, the confusion matrices and the failing case IDs.

## 9. Results (v1, single run)

Main focus claims (48). The baseline accepts every gold-unsupported focus claim
by construction, because each one parses and quotes a real event. Grounding
accepted 1 of 33 (`E2-10`, a condition phrased "as soon as"). No gold-contradicted
claim was accepted. 13 of 22 were labelled `CONTRADICTED` and 9 abstained as
`INSUFFICIENT_EVIDENCE`. These were mostly cases where a different target,
subject, issuer or count was stated without a keyed pattern. 3 of 15 gold-supported claims were rejected,
all of them paraphrase cases. Field-level flagging had micro precision 0.82 and
recall 0.93 against the author's field labels.

| Main cases (48) | Unsafe auto-executions | Unnecessary interventions | Route accuracy |
| --- | --- | --- | --- |
| Baseline, either setting | 35 | 0 | 0.27 |
| Grounded, focus_isolated | 3 | 3 | 0.85 |
| Grounded, end_to_end | 1 | 9 | 0.46 |

The end-to-end row looks safe for the wrong reason in two families. In E2 the
background recovery message says the grant "can be revoked", which triggers the
revocation cue. In E3 the background clearance says "export screening passed",
which no clearance cue covers. Both force Handoff and hide misses. The isolated
setting is the cleaner estimate of focus-claim behaviour.

The three isolated unsafe executions are real misses. They are an omitted
"litigation hold" (the hold pattern lacks that modifier), an omitted retraction
phrased "please disregard my earlier authorization", and the "as soon as"
condition.

Falsification cases (10). Grounding accepted 2 of 4 gold-unsupported claims
(an issuer named only to deny it issued the approval, and a sarcastic "go
ahead"). It rejected 3 of 6 gold-supported claims (an unrelated earlier
rejection in the same message, a count in words, a date in words). A
restriction phrased without cue words ("needs to stay in the warehouse") was
missed.

Part B on the existing templates. With faithful extraction, grounding lowers
route accuracy from 0.90 to 0.70. One clearance template and one repair-channel
template never name the operation. Grounding treats the gold card's operation as
unsupported, which is the declared rule, so 28 contexts become more cautious.
Under the hold-as-authority and drop-hold corruptions, unjustified executions
fall from 36 to 10. The remaining 10 are hidden-hold contexts where the hold
message was deleted from the history. No grounding check can recover those.

All four preregistered hypotheses passed. H3 (false rejection at most 0.25)
passed at 0.20. These are protocol outcomes on synthetic cases, not a quality
certification.

Labelling notes found after the run, left unchanged in the frozen artifacts.
`E3-12` lists only `target` as unsupported, but the hold message also does not
state the operation or the scope values that the extractor copied, so three of
the 11 main field false positives are labelling omissions. Gold field labels for
`E1-05` (kind of an expired approval), `E2-15` (operation stated as "maintainer
grants") and `E3-14` ("approved carriers") are debatable.

## 10. Known limitations

- English, closed cue lists, short negation window. This is not natural-language
  inference. Paraphrases outside the profile abstain, which costs interventions.
- Coreference is not resolved. An unrelated "rejected" or "revoked" in a message
  that names the target is attributed to the action.
- Restrictions phrased without cue words are missed. Omission detection is only as
  good as the restrictive cue lists.
- Issuer and subject checks are presence checks. An issuer mentioned in a negated
  or reported role is still counted as present.
- Natural-language dates and numbers in words are not parsed.
- Contradictions without a keyed pattern (another target, subject or count)
  abstain instead of being labelled contradicted. Both outcomes exclude the claim.
- Evaluation cases share an author with the verifier and are synthetic and
  correlated. No extraction model was run. Real error rates are unknown.

## 11. Reproduction

From `05_代码与实验/`:

```bash
python3 -m unittest tests.test_evidence_grounding -v
python3 scripts/run_evidence_grounding_evaluation.py --config configs/evidence_grounding_acceptance_v2.json
```

The second command prints the current compatibility plan only. The v1 prefix
already exists and will not be overwritten. Its original config is retained as
archive metadata; the old NL inputs and runner are preserved in contributor
commit `6e9f968`, not silently substituted with current NL-v2. A future formal
run requires the new versioned prefix and both explicit run flags. No model or
new formal result is needed for the current unit acceptance.
