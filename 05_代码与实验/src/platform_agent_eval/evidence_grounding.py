"""Field-level grounding checks for extracted natural-language evidence.

The natural-language extension (``natural_language_evidence``) checks that an
extracted claim is well formed and that its ``source_quote`` occurs in the cited
message. Quote containment shows that a citation exists. It does not show that
the cited message supports the claimed kind, issuer, subject, operation,
target, scope, validity window, authentication report or transferability.

This module adds a deterministic, gold-free check between extraction and the
frozen proof-card validator. Each field of each claim receives one status:

* ``SUPPORTED``: the cited message states the value inside the declared
  supported profile, and no in-profile cue contradicts it.
* ``CONTRADICTED``: the cited message states a different value or the opposite
  polarity (for example a denial cited as an approval).
* ``INSUFFICIENT_EVIDENCE``: the message does not state the value in a form the
  checker can recognise, is hedged or conditional, or lies outside the profile.

Supported profile (``evidence-grounding-v1``), English only:

* identifiers (issuer, subject, target and string scope values) appear
  verbatim as tokens; hyphens are part of a token, so ``prod-north`` does not
  match inside ``prod-north-old``;
* the operation appears as its UPPER_SNAKE name or as its words in order, with
  simple inflections and at most two intervening words;
* numeric scope values appear as numbers (thousands separators allowed);
  currency-suffixed keys such as ``amount_hkd`` are compared with amounts
  tagged by that currency;
* validity windows appear as explicit ISO-8601 timestamps with an offset;
* polarity, hedging, conditions and authentication reports are recognised only
  through the closed cue lists below, with a short clause-local negation window.

Everything outside that profile abstains as ``INSUFFICIENT_EVIDENCE``. These are
narrow lexical checks, not general natural-language inference. An
authentication field marked ``SUPPORTED`` means only that the text *reports*
successful authentication; this module never establishes cryptographic trust,
identity or authority, and it can only remove or block permissions.

Gate semantics (``ground_extraction``):

1. malformed extraction output routes to Handoff, as before;
2. permissive claims (all kinds except ``ACTIVE_HOLD``) reach the validator only
   when every field is ``SUPPORTED``;
3. ``ACTIVE_HOLD`` claims are never removed or weakened by grounding;
4. a restrictive cue (hold, prohibition, denial or revocation) in a message
   linked to the action, which no supported ``ACTIVE_HOLD`` claim accounts
   for, routes to Handoff;
5. the result is never more permissive than the existing pipeline's route on
   the same parse.

Gold routes, scenario IDs and expected labels are never read here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .domain import Decision
from .natural_language_evidence import (
    ExtractedClaim,
    ExtractionParse,
    NLContext,
    claims_to_cards,
)
from .proof_cards import (
    ActionRequest,
    ProofCard,
    ProofCardInput,
    ProofCardKind,
    ProofCardResult,
    ProofPolicy,
    _card_applies,
    validate_proof_cards,
)


EVIDENCE_GROUNDING_VERSION = "evidence-grounding-v1"


class GroundingStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


RESTRICTIVE_KINDS: frozenset[ProofCardKind] = frozenset({ProofCardKind.ACTIVE_HOLD})

# Route order from most to least permissive; used to keep the gate monotone.
_ROUTE_RANK: dict[Decision, int] = {
    Decision.AUTO_EXECUTE: 0,
    Decision.REQUEST_CONFIRMATION: 1,
    Decision.HANDOFF: 2,
    Decision.BLOCK: 3,
}


@dataclass(frozen=True)
class FieldGrounding:
    field: str
    status: GroundingStatus
    reason: str
    evidence: str | None = None
    in_quote: bool | None = None


@dataclass(frozen=True)
class ClaimGrounding:
    event_id: str
    kind: ProofCardKind
    card_id: str
    status: GroundingStatus
    fields: tuple[FieldGrounding, ...]
    restrictive: bool

    @property
    def failed_fields(self) -> tuple[FieldGrounding, ...]:
        return tuple(f for f in self.fields if f.status is not GroundingStatus.SUPPORTED)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(f"{f.field}:{f.reason}" for f in self.failed_fields)


@dataclass(frozen=True)
class RestrictiveSignal:
    event_id: str
    category: str
    cue: str
    sentence: str
    linked_by: str
    accounted_for: bool


@dataclass(frozen=True)
class GroundingGateResult:
    decision: Decision
    baseline_decision: Decision
    failure_layer: str
    reason_codes: tuple[str, ...]
    claim_groundings: tuple[ClaimGrounding, ...]
    admitted_card_ids: tuple[str, ...]
    excluded_card_ids: tuple[str, ...]
    restrictive_signals: tuple[RestrictiveSignal, ...]
    validation: ProofCardResult | None
    baseline_validation: ProofCardResult | None

    @property
    def unaccounted_signals(self) -> tuple[RestrictiveSignal, ...]:
        return tuple(s for s in self.restrictive_signals if not s.accounted_for)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_CONTRACTIONS: tuple[tuple[str, str], ...] = (
    (r"\bcan't\b", "can not"),
    (r"\bcannot\b", "can not"),
    (r"\bwon't\b", "will not"),
    (r"\bshan't\b", "shall not"),
    (r"\b(\w+)n't\b", r"\1 not"),
)

_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:\d{2})"
)


def normalize_text(text: str) -> str:
    """Lowercase, unify quotes and dashes, and expand negative contractions."""

    value = text.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = re.sub(r"\s*[—–]\s*", "; ", value)
    value = re.sub(r"\s+--\s+", "; ", value)
    value = value.lower()
    for pattern, replacement in _CONTRACTIONS:
        value = re.sub(pattern, replacement, value)
    return re.sub(r"\s+", " ", value).strip()


def _sentences(normalized: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+", normalized)
    return [part.strip(" \"'") for part in parts if part.strip(" \"'")]


def _clauses(normalized: str) -> list[str]:
    clauses: list[str] = []
    for sentence in _sentences(normalized):
        for part in re.split(r":\s+|\s*,?\s+(?:but|however|although|whereas)\s+", sentence):
            if part.strip():
                clauses.append(part.strip())
    return clauses


def _token_pattern(value: str) -> re.Pattern[str]:
    """Match an identifier as a whole token; hyphens belong to the token."""

    return re.compile(r"(?<![a-z0-9_-])" + re.escape(value.lower()) + r"(?![a-z0-9_-])")


def _mentions(normalized: str, value: str) -> bool:
    return bool(_token_pattern(value).search(normalized))


def _stem_pattern(token: str) -> str:
    stem = token[:-1] if token.endswith("e") and len(token) > 3 else token
    return re.escape(stem) + r"(?:e|es|s|ed|d|ing)?"


def operation_pattern(operation: str) -> str:
    words = [w for w in operation.lower().split("_") if w]
    if not words:
        return r"(?!x)x"
    ordered = r"(?:\W+\w+){0,2}?\W+".join(r"\b" + _stem_pattern(w) + r"\b" for w in words)
    return rf"(?:\b{re.escape(operation.lower())}\b|{ordered})"


# ---------------------------------------------------------------------------
# Closed cue lists. Each entry is (name, regex) over normalised text.
# ---------------------------------------------------------------------------

_NEGATORS = frozenset({"not", "no", "never", "nothing", "nobody", "none", "without", "neither", "nor"})
_NEGATION_STOPS = frozenset({"and", "or", "but", ",", "then", "so", "yet"})

_ACTION_VERBS = (
    r"(?:proceed|go ahead|continue|execute|run|perform|pay|deploy|release|book|"
    r"purchase|buy|transfer|send|delete|remove|grant|approve|schedule|increase|"
    r"move forward|process|submit|wire)"
)

_AUTHORITY_STRONG: tuple[tuple[str, str], ...] = (
    ("approved", r"\bapproved\b"),
    ("authorized", r"\bauthori[sz]ed\b"),
    ("go_ahead", r"\bgo ahead\b"),
    ("cleared_to", r"\bcleared(?: by [\w-]+)? to\b"),
    ("sign_off_allows", r"\bsign-?off (?:allows|permits|grants|covers)\b"),
    ("signed_off", r"\bsigned off\b"),
    ("permission_granted", r"\b(?:permission|consent|approval|authori[sz]ation) (?:is |was |has been )?(?:granted|given|confirmed)\b"),
    ("grants_permission", r"\bgrant(?:s|ed)? (?:permission|approval|authori[sz]ation)\b"),
)

_CLEARANCE: tuple[tuple[str, str], ...] = (
    ("clearance", r"\bclearance\b"),
    ("policy_check_passed", r"\b(?:policy|compliance) (?:check|review|screen)s? (?:has |have )?(?:passed|cleared|succeeded)\b"),
    ("passed_policy_check", r"\bpassed (?:the |a )?(?:policy|compliance) (?:check|review|screen)\b"),
    ("check_passed", r"\bcheck passed\b"),
    ("nothing_blocks", r"\bnothing in (?:the )?policy blocks\b"),
    ("no_policy_objection", r"\bno (?:policy|compliance) (?:objection|issue|blocker|concern)s?\b"),
    ("compliant", r"\b(?:policy-compliant|compliant with (?:the )?policy)\b"),
)

_DELEGATION: tuple[tuple[str, str], ...] = (
    ("delegation", r"\bdelegat(?:e|ed|es|ion)\b"),
    ("handed_task", r"\bhanded (?:this|the) (?:task|work|job)\b"),
    ("on_behalf", r"\bon (?:the )?[\w-]+(?:'s)? behalf\b|\bon behalf of\b"),
    ("act_for", r"\bact(?:s|ing)? for\b"),
    ("transferred_authority", r"\btransferred (?:the )?authority\b"),
)

_RECOVERY: tuple[tuple[str, str], ...] = (
    ("roll_back", r"\broll(?:ed|s)? (?:it |this |them |that )?back\b"),
    ("rollback", r"\brollback\b"),
    ("restore", r"\brestor(?:e|ed|able)\b"),
    ("undo", r"\bundo(?:ne)?\b"),
    ("revert", r"\brevert(?:ed|ible)?\b"),
    ("reversible", r"\breversible\b"),
)

_REPAIR: tuple[tuple[str, str], ...] = (
    ("can_supply_sign_off", r"\bcan (?:supply|provide|give) (?:the |a )?(?:missing )?(?:sign-?off|approval|confirmation)\b"),
    ("allowed_to_confirm", r"\b(?:allowed|authori[sz]ed|permitted|able) to (?:confirm|approve)\b"),
    ("right_person", r"\bright (?:person|contact) to (?:approve|confirm)\b"),
    ("can_confirm", r"\bcan (?:approve|confirm) (?:it|this|the)\b"),
)

_HOLD: tuple[tuple[str, str], ...] = (
    ("hold_off", r"\bhold off\b"),
    ("hold", r"\b(?:a|an|the|this|policy|compliance|legal|change|active) hold\b"),
    ("on_hold", r"\bon hold\b"),
    ("freeze", r"\bfreeze\b"),
    ("frozen", r"\bfrozen\b"),
    ("block", r"\bblock(?:ed|s)?\b"),
    ("embargo", r"\bembargo(?:ed)?\b"),
    ("suspended", r"\bsuspended\b"),
)

_PROHIBITION: tuple[tuple[str, str], ...] = (
    ("must_not", rf"\b(?:do|does|did|must|should|shall|may|can|will) not (?:\w+ ){{0,2}}{_ACTION_VERBS}\b"),
    ("no_one_should", rf"\bno one (?:should|may|can|is to) (?:\w+ ){{0,2}}{_ACTION_VERBS}\b"),
    ("stop", r"(?:^|[;:\"]\s*)(?:please )?stop\b"),
    ("not_allowed", r"\b(?:is|are) not (?:allowed|permitted) to\b"),
)

_DENIAL: tuple[tuple[str, str], ...] = (
    ("denied", r"\b(?:denied|declined|rejected|refused|disapproved|vetoed)\b"),
    ("not_approved", r"\bnot (?:been )?(?:approved|authori[sz]ed|cleared|permitted|allowed|granted|signed off|given)\b"),
    ("never_approved", r"\bnever (?:been )?approved\b"),
    ("did_not_approve", r"\b(?:did|does|do|will|would) not (?:approve|authori[sz]e|sign off)\b"),
    ("no_approval", r"\bno (?:approval|authori[sz]ation|permission|consent|sign-?off) (?:was |has been |is )?(?:given|granted|recorded|on file|exists?)\b"),
    ("without_approval", r"\bwithout (?:any )?(?:approval|authori[sz]ation|sign-?off)\b"),
    ("check_failed", r"\b(?:policy|compliance) (?:check|review|screen)s? (?:has |have )?failed\b"),
)

_REVOCATION: tuple[tuple[str, str], ...] = (
    ("revoked", r"\b(?:revoked|withdrawn|rescinded|retracted|voided)\b"),
    ("cancelled", r"\b(?:approval|authori[sz]ation|permission|sign-?off|consent) (?:has been |was |is )?cancell?ed\b"),
    ("no_longer_permitted", r"\bno longer (?:approved|authori[sz]ed|permitted|allowed|stands|in effect)\b"),
)

_EXPIRY: tuple[tuple[str, str], ...] = (
    ("expired", r"\bexpired\b"),
    ("lapsed", r"\blapsed\b"),
    ("no_longer_valid", r"\bno longer valid\b"),
    ("out_of_date", r"\bout of date\b"),
)

_LIFT: tuple[tuple[str, str], ...] = (
    ("hold_lifted", r"\b(?:hold|freeze|block|embargo|suspension)s?\b[^.;]{0,80}?\b(?:has |have )?(?:been |was |were |is )?(?:lifted|removed|ended|withdrawn|expired|revoked)\b"),
    ("unfrozen", r"\b(?:unfrozen|unblocked)\b"),
    ("no_longer_held", r"\bno longer (?:frozen|blocked|on hold)\b"),
    ("no_hold", r"\bno (?:\w+ )?(?:hold|freeze|block)s?\b"),
)

_HEDGE: tuple[tuple[str, str], ...] = (
    ("probably", r"\b(?:probably|maybe|perhaps|possibly|likely)\b"),
    ("i_think", r"\bi (?:think|guess|believe|assume|suppose)\b"),
    ("should_be_fine", r"\b(?:should|seems? to|looks? to) be (?:fine|ok|okay|good)\b"),
    ("looks_fine", r"\b(?:seems?|looks?) (?:fine|ok|okay|good)\b"),
    ("not_sure", r"\b(?:not sure|unclear|tentative(?:ly)?|in principle)\b"),
)

_QUALIFIER: tuple[tuple[str, str], ...] = (
    ("only_after", r"\bonly (?:after|if|once|when|until)\b"),
    ("subject_to", r"\bsubject to\b"),
    ("provided_that", r"\bprovided (?:that\b)?"),
    ("on_condition", r"\bon (?:the )?condition\b|\bconditional(?:ly)? (?:on|upon)\b"),
    ("unless", r"\bunless\b"),
    ("pending", r"\bpending\b|\bawaiting\b"),
    ("as_long_as", r"\bas long as\b"),
    ("not_before", r"\bnot before\b"),
)

_REQUEST_OR_HYPOTHETICAL: tuple[tuple[str, str], ...] = (
    ("request", r"\b(?:requested|requesting|asked for|asking for|seeking|seeks|needs?|needed|waiting for|awaiting|request) (?:an? |the |your |their )?(?:approval|sign-?off|authori[sz]ation|clearance|permission|consent)\b"),
    ("counterfactual", r"\bif (?:\w+ ){0,4}(?:had|were|would)\b"),
    ("future_approval", r"\b(?:would|will|plans? to|planned to|intends? to) (?:be )?(?:approve|approved|authori[sz]e|sign off)\b"),
)

_AUTH_NEGATIVE: tuple[tuple[str, str], ...] = (
    ("unverified", r"\b(?:unverified|unsigned|unauthenticated)\b"),
    ("not_verified", r"\bnot (?:been |yet )?(?:verified|signed|authenticated)\b"),
    ("check_failed", r"\b(?:signature|identity|authentication|verification|dkim) (?:check )?(?:failed|missing|invalid|mismatch)\b"),
    ("failed_check", r"\bfailed (?:the )?(?:signature|identity|authentication) (?:check|verification)\b"),
    ("could_not_verify", r"\bcould not (?:be )?(?:verified|authenticated|verify|authenticate)\b"),
    ("claims_to_be", r"\bclaims? to be from\b|\bpurport(?:s|ing|edly)?\b|\bspoof(?:ed)?\b"),
)

_AUTH_WEAKENING: tuple[tuple[str, str], ...] = (
    ("forwarded", r"\bforwarded\b|\brelayed\b|\bscreenshot\b|\bpasted\b|\bcopied from\b"),
)

_AUTH_POSITIVE: tuple[tuple[str, str], ...] = (
    ("signature_verified", r"\bsignature (?:was |is |has been )?(?:verified|valid|checked)\b"),
    ("signed", r"\bsigned\b(?! off)"),
    ("verified", r"\bverified\b"),
    ("authenticated", r"\bauthenticated\b"),
)

_TARGET_EXCLUSION = (
    r"\b(?:does|do|did) not (?:cover|apply to|include|concern|affect|relate to) {t}",
    r"\bnot (?:for|about|on) {t}",
    r"\b(?:other than|except(?: for)?|excluding|unrelated to) {t}",
)


@dataclass(frozen=True)
class _Cue:
    name: str
    text: str
    clause: str
    negated: bool


def _preceding_negated(clause: str, start: int) -> bool:
    tokens = re.findall(r"[a-z']+|,", clause[:start])
    for token in reversed(tokens[-4:]):
        if token in _NEGATION_STOPS:
            return False
        if token in _NEGATORS:
            return True
    return False


def _find(clauses: list[str], table: tuple[tuple[str, str], ...]) -> list[_Cue]:
    found: list[_Cue] = []
    for clause in clauses:
        for name, pattern in table:
            for match in re.finditer(pattern, clause):
                found.append(
                    _Cue(name, match.group(0), clause, _preceding_negated(clause, match.start()))
                )
    return found


def _positive(cues: list[_Cue]) -> list[_Cue]:
    return [cue for cue in cues if not cue.negated]


# ---------------------------------------------------------------------------
# Identifier attribution for restrictive cues
# ---------------------------------------------------------------------------

_IDENTIFIER = re.compile(r"(?<![a-z0-9_-])[a-z0-9]+(?:-[a-z0-9]+)+(?![a-z0-9_-])")


def _identifiers(normalized_sentence: str, known: frozenset[str]) -> set[str]:
    stripped = _TIMESTAMP.sub(" ", normalized_sentence)
    found: set[str] = set()
    for token in _IDENTIFIER.findall(stripped):
        if token in known or any(ch.isdigit() for ch in token) or token.count("-") >= 2:
            found.add(token)
    return found


def _target_excluded(normalized: str, target: str) -> bool:
    escaped = r"(?<![a-z0-9_-])" + re.escape(target.lower()) + r"(?![a-z0-9_-])"
    return any(re.search(p.format(t=escaped), normalized) for p in _TARGET_EXCLUSION)


def _known_entities(action: ActionRequest, policy: ProofPolicy) -> frozenset[str]:
    names = {action.actor_id, action.target_id}
    for group in (
        policy.authority_issuers, policy.clearance_issuers, policy.hold_issuers,
        policy.delegation_issuers, policy.recovery_issuers,
        policy.repair_channel_issuers, policy.confirmable_authority_actors,
    ):
        names.update(group)
    return frozenset(name.lower() for name in names)


def _restrictive_cues(
    normalized: str,
    action: ActionRequest,
    policy: ProofPolicy,
) -> list[tuple[str, _Cue]]:
    """Return (category, cue) for restrictive cues attributable to the action target.

    A sentence that names the target counts. A sentence that names only other
    identifier-like tokens is attributed to those items and is skipped. A
    sentence that names no identifier counts, because the message as a whole is
    already linked to the action by the caller.
    """

    exclusion = _target_excluded(normalized, action.target_id)
    target = action.target_id.lower()
    known = _known_entities(action, policy)
    issuers = known - {target}
    op = operation_pattern(action.operation)
    prohibition = _PROHIBITION + (
        ("must_not_operation", rf"\b(?:do|does|did|must|should|shall|may|can|will) not (?:\w+ ){{0,2}}{op}"),
    )
    found: list[tuple[str, _Cue]] = []
    for sentence in _sentences(normalized):
        ids = _identifiers(sentence, known)
        names_target = target in ids or _mentions(sentence, target)
        others = ids - {target} - issuers
        if not names_target and others:
            continue
        if exclusion and not names_target and not ids:
            # The message explicitly says the target is not covered; an
            # unattributed restrictive sentence belongs to the other item.
            continue
        clauses = _clauses(sentence)
        lifts = _find(clauses, _LIFT)
        for category, table in (
            ("HOLD", _HOLD), ("PROHIBITION", prohibition),
            ("DENIAL", _DENIAL), ("REVOCATION", _REVOCATION),
        ):
            for cue in _find(clauses, table):
                if cue.negated:
                    continue
                if category in {"HOLD", "REVOCATION"} and any(
                    lift.clause == cue.clause for lift in lifts
                ):
                    continue
                found.append((category, cue))
    return found


# ---------------------------------------------------------------------------
# Field checks
# ---------------------------------------------------------------------------


def _field(name: str, status: GroundingStatus, reason: str,
           evidence: str | None = None, quote: str | None = None) -> FieldGrounding:
    in_quote = None if evidence is None or quote is None else evidence in quote
    return FieldGrounding(name, status, reason, evidence, in_quote)


def _identifier_field(name: str, value: str, normalized: str, quote: str) -> FieldGrounding:
    match = _token_pattern(value).search(normalized)
    if match:
        return _field(name, GroundingStatus.SUPPORTED, "LITERAL_MATCH", match.group(0), quote)
    return _field(name, GroundingStatus.INSUFFICIENT_EVIDENCE, "VALUE_NOT_STATED")


def _target_field(claim: ExtractedClaim, normalized: str, quote: str) -> FieldGrounding:
    if _target_excluded(normalized, claim.target):
        return _field("target", GroundingStatus.CONTRADICTED, "SOURCE_EXCLUDES_TARGET")
    return _identifier_field("target", claim.target, normalized, quote)


def _subject_field(claim: ExtractedClaim, normalized: str, quote: str) -> FieldGrounding:
    if claim.kind in {
        ProofCardKind.CLEARANCE, ProofCardKind.ACTIVE_HOLD, ProofCardKind.RECOVERY
    } and claim.subject == claim.target:
        # Existing card convention: object-level evidence uses the target as subject.
        return _field("subject", GroundingStatus.SUPPORTED, "TARGET_AS_SUBJECT_CONVENTION")
    return _identifier_field("subject", claim.subject, normalized, quote)


def _operation_field(claim: ExtractedClaim, normalized: str, quote: str) -> FieldGrounding:
    match = re.search(operation_pattern(claim.operation), normalized)
    if match:
        return _field("operation", GroundingStatus.SUPPORTED, "OPERATION_WORDS_PRESENT",
                      match.group(0), quote)
    return _field("operation", GroundingStatus.INSUFFICIENT_EVIDENCE, "OPERATION_NOT_STATED")


def _numbers(text: str) -> set[str]:
    values: set[str] = set()
    for raw in re.findall(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])", _TIMESTAMP.sub(" ", text)):
        cleaned = raw.rstrip(".,").replace(",", "")
        if cleaned:
            values.add(_canonical_number(cleaned))
    return values


def _canonical_number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    return str(int(number)) if number.is_integer() else repr(number)


def _currency_amounts(normalized: str, currency: str) -> set[str]:
    stripped = _TIMESTAMP.sub(" ", normalized)
    number = r"(?<![\w.-])(\d(?:[\d,]*\d)?(?:\.\d+)?)(?![\w-])"
    amounts: set[str] = set()
    for pattern in (rf"\b{currency}\s?\$?\s?{number}", rf"{number}\s?{currency}\b"):
        for raw in re.findall(pattern, stripped):
            amounts.add(_canonical_number(raw.replace(",", "")))
    return amounts


def _scope_field(key: str, value: str, normalized: str, quote: str) -> FieldGrounding:
    name = f"scope.{key}"
    lowered = value.lower()
    key_words = [w for w in key.lower().split("_") if w]
    currency = key_words[-1] if key_words and re.fullmatch(r"[a-z]{3}", key_words[-1]) and key_words[-1] in {
        "hkd", "usd", "eur", "gbp", "cny", "rmb", "jpy", "sgd"
    } else None

    if lowered in {"true", "false"}:
        phrase = " ".join(key_words)
        positive = re.search(rf"(?<!non-)\b{re.escape(phrase)}\b", normalized)
        negative = re.search(rf"\bnon-{re.escape(phrase)}\b|\bnot {re.escape(phrase)}\b", normalized)
        stated_true = bool(positive) and not (
            positive and _preceding_negated(normalized, positive.start())
        )
        if negative and not stated_true:
            stated = "false"
        elif stated_true and not negative:
            stated = "true"
        else:
            return _field(name, GroundingStatus.INSUFFICIENT_EVIDENCE, "BOOLEAN_NOT_STATED")
        if stated == lowered:
            evidence = (negative or positive).group(0)  # type: ignore[union-attr]
            return _field(name, GroundingStatus.SUPPORTED, "BOOLEAN_STATED", evidence, quote)
        return _field(name, GroundingStatus.CONTRADICTED, "BOOLEAN_OPPOSITE")

    if re.fullmatch(r"\d+(?:\.\d+)?", lowered):
        target_number = _canonical_number(lowered)
        if currency:
            amounts = _currency_amounts(normalized, currency)
            if target_number in amounts:
                return _field(name, GroundingStatus.SUPPORTED, "CURRENCY_AMOUNT_MATCH",
                              target_number, None)
            if amounts:
                return _field(name, GroundingStatus.CONTRADICTED, "CURRENCY_AMOUNT_MISMATCH")
        keyed = re.findall(
            rf"\b{re.escape(' '.join(key_words))}\s+(?:of\s+)?(\d[\d,]*(?:\.\d+)?)", normalized
        )
        keyed_values = {_canonical_number(v.rstrip('.,').replace(',', '')) for v in keyed}
        if keyed_values and target_number not in keyed_values:
            return _field(name, GroundingStatus.CONTRADICTED, "KEYED_VALUE_MISMATCH")
        if target_number in _numbers(normalized):
            return _field(name, GroundingStatus.SUPPORTED, "NUMBER_PRESENT", target_number, None)
        return _field(name, GroundingStatus.INSUFFICIENT_EVIDENCE, "VALUE_NOT_STATED")

    if _mentions(normalized, lowered):
        match = _token_pattern(lowered).search(normalized)
        return _field(name, GroundingStatus.SUPPORTED, "LITERAL_MATCH",
                      match.group(0) if match else lowered, quote)
    phrase = " ".join(key_words)
    keyed = re.findall(rf"\b{re.escape(phrase)}\s+([a-z0-9][\w.-]*[a-z0-9]|[a-z0-9])", normalized)
    if keyed:
        return _field(name, GroundingStatus.CONTRADICTED, "KEYED_VALUE_MISMATCH")
    return _field(name, GroundingStatus.INSUFFICIENT_EVIDENCE, "VALUE_NOT_STATED")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("z", "Z"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _validity_field(
    claim: ExtractedClaim,
    raw_text: str,
    clauses: list[str],
    action: ActionRequest,
) -> FieldGrounding:
    stated = {ts for ts in (_parse_timestamp(m) for m in _TIMESTAMP.findall(raw_text)) if ts}
    start = _parse_timestamp(claim.valid_from)
    end = _parse_timestamp(claim.valid_until)
    effective = _parse_timestamp(action.effective_at)
    expiry = _positive(_find(clauses, _EXPIRY))
    if (
        claim.kind not in RESTRICTIVE_KINDS
        and expiry
        and start is not None and end is not None and effective is not None
        and start <= effective <= end
    ):
        return _field("validity", GroundingStatus.CONTRADICTED, "SOURCE_REPORTS_EXPIRY",
                      expiry[0].text)
    if start is None or end is None:
        return _field("validity", GroundingStatus.INSUFFICIENT_EVIDENCE, "UNPARSEABLE_WINDOW")
    if start in stated and end in stated:
        return _field("validity", GroundingStatus.SUPPORTED, "TIMESTAMPS_STATED")
    if len(stated) >= 2:
        return _field("validity", GroundingStatus.CONTRADICTED, "WINDOW_DIFFERS_FROM_SOURCE")
    return _field("validity", GroundingStatus.INSUFFICIENT_EVIDENCE, "WINDOW_NOT_STATED")


def _authentication_field(claim: ExtractedClaim, clauses: list[str]) -> FieldGrounding:
    if not claim.verified:
        return _field("authentication", GroundingStatus.SUPPORTED, "NOT_ASSERTED")
    negative = _find(clauses, _AUTH_NEGATIVE)
    if negative:
        return _field("authentication", GroundingStatus.CONTRADICTED,
                      f"SOURCE_REPORTS_{negative[0].name.upper()}", negative[0].text)
    if _find(clauses, _AUTH_WEAKENING):
        return _field("authentication", GroundingStatus.INSUFFICIENT_EVIDENCE,
                      "RELAYED_MESSAGE_NOT_INDEPENDENTLY_AUTHENTICATED")
    positive = _positive(_find(clauses, _AUTH_POSITIVE))
    if positive:
        return _field("authentication", GroundingStatus.SUPPORTED,
                      "TEXT_REPORTS_AUTHENTICATION", positive[0].text)
    return _field("authentication", GroundingStatus.INSUFFICIENT_EVIDENCE,
                  "AUTHENTICATION_NOT_REPORTED")


def _transferable_field(claim: ExtractedClaim, normalized: str, clauses: list[str]) -> FieldGrounding:
    if not claim.transferable:
        return _field("transferable", GroundingStatus.SUPPORTED, "NOT_ASSERTED")
    if re.search(r"\bnon-transferable\b|\b(?:may|can|must) not be (?:re-?)?delegated\b", normalized):
        return _field("transferable", GroundingStatus.CONTRADICTED, "SOURCE_SAYS_NOT_TRANSFERABLE")
    cues = _find(clauses, (("transferable", r"(?<!non-)\btransferable\b"),))
    if any(cue.negated for cue in cues):
        return _field("transferable", GroundingStatus.CONTRADICTED, "SOURCE_SAYS_NOT_TRANSFERABLE")
    if cues:
        return _field("transferable", GroundingStatus.SUPPORTED, "TRANSFERABLE_STATED", cues[0].text)
    return _field("transferable", GroundingStatus.INSUFFICIENT_EVIDENCE, "TRANSFERABILITY_NOT_STATED")


_KIND_TABLES: dict[ProofCardKind, tuple[tuple[str, str], ...]] = {
    ProofCardKind.AUTHORITY: _AUTHORITY_STRONG,
    ProofCardKind.CLEARANCE: _CLEARANCE,
    ProofCardKind.DELEGATION: _DELEGATION,
    ProofCardKind.RECOVERY: _RECOVERY,
    ProofCardKind.REPAIR_CHANNEL: _REPAIR,
}


def _kind_field(
    claim: ExtractedClaim,
    normalized: str,
    clauses: list[str],
    action: ActionRequest,
    policy: ProofPolicy,
) -> FieldGrounding:
    if claim.kind is ProofCardKind.ACTIVE_HOLD:
        restrictive = [
            cue for category, cue in _restrictive_cues(normalized, action, policy)
            if category in {"HOLD", "PROHIBITION"}
        ]
        if restrictive:
            return _field("kind", GroundingStatus.SUPPORTED, f"RESTRICTIVE_CUE_{restrictive[0].name.upper()}",
                          restrictive[0].text)
        lifted = _find(clauses, _LIFT) + [c for c in _find(clauses, _HOLD) if c.negated]
        if lifted:
            return _field("kind", GroundingStatus.CONTRADICTED, "SOURCE_REPORTS_NO_ACTIVE_HOLD",
                          lifted[0].text)
        return _field("kind", GroundingStatus.INSUFFICIENT_EVIDENCE, "NO_RESTRICTIVE_CUE")

    conflict = _restrictive_cues(normalized, action, policy)
    if conflict:
        category, cue = conflict[0]
        return _field("kind", GroundingStatus.CONTRADICTED, f"POLARITY_CONFLICT_{category}", cue.text)

    op = operation_pattern(claim.operation)
    table = _KIND_TABLES[claim.kind]
    if claim.kind is ProofCardKind.AUTHORITY:
        table = table + (
            ("may_operation", rf"\bmay (?:now )?(?:\w+ )?{op}"),
            ("allowed_to_operation", rf"\b(?:is|are) (?:allowed|permitted) to (?:\w+ )?{op}"),
        )
    cues = _find(clauses, table)
    negated = [cue for cue in cues if cue.negated]
    if negated:
        return _field("kind", GroundingStatus.CONTRADICTED, f"NEGATED_{negated[0].name.upper()}",
                      negated[0].text)
    positive = _positive(cues)
    if not positive:
        return _field("kind", GroundingStatus.INSUFFICIENT_EVIDENCE, "KIND_CUE_ABSENT")
    if claim.kind is ProofCardKind.AUTHORITY and all(
        cue.name in {"may_operation", "allowed_to_operation"} for cue in positive
    ):
        other = [
            cue for kind, other_table in _KIND_TABLES.items() if kind is not ProofCardKind.AUTHORITY
            for cue in _positive(_find(clauses, other_table))
        ]
        if other:
            return _field("kind", GroundingStatus.INSUFFICIENT_EVIDENCE,
                          "WEAK_AUTHORITY_CUE_WITH_OTHER_KIND", other[0].text)
    return _field("kind", GroundingStatus.SUPPORTED, f"KIND_CUE_{positive[0].name.upper()}",
                  positive[0].text)


def _qualification_field(claim: ExtractedClaim, clauses: list[str], quote: str) -> FieldGrounding:
    tables: list[tuple[str, tuple[tuple[str, str], ...]]] = [
        ("HEDGED", _HEDGE), ("CONDITIONAL", _QUALIFIER),
    ]
    if claim.kind in {ProofCardKind.AUTHORITY, ProofCardKind.CLEARANCE, ProofCardKind.DELEGATION}:
        tables.append(("REQUESTED_OR_HYPOTHETICAL", _REQUEST_OR_HYPOTHETICAL))
    for label, table in tables:
        cues = _positive(_find(clauses, table))
        if cues:
            outside = cues[0].text not in quote
            reason = f"{label}_{cues[0].name.upper()}" + ("_OUTSIDE_QUOTE" if outside else "")
            return _field("qualification", GroundingStatus.INSUFFICIENT_EVIDENCE, reason,
                          cues[0].text, quote)
    return _field("qualification", GroundingStatus.SUPPORTED, "UNQUALIFIED")


def verify_claim(
    claim: ExtractedClaim,
    event_text: str | None,
    action: ActionRequest,
    policy: ProofPolicy,
) -> ClaimGrounding:
    """Ground one extracted claim in the full text of its cited message.

    The full message is used, not only the quote, so a qualification or denial
    outside a selectively short quote is still seen. ``action`` supplies only
    the effective time for the expiry check and the target and operation for
    attributing restrictive cues. Claim values are never replaced by action
    values.
    """

    card_id = f"x-{claim.event_id}-{claim.kind.value.lower()}"
    restrictive = claim.kind in RESTRICTIVE_KINDS
    if event_text is None:
        fields = (_field("citation", GroundingStatus.INSUFFICIENT_EVIDENCE, "EVENT_NOT_VISIBLE"),)
        return ClaimGrounding(claim.event_id, claim.kind, card_id,
                              GroundingStatus.INSUFFICIENT_EVIDENCE, fields, restrictive)
    normalized = normalize_text(event_text)
    quote = normalize_text(claim.source_quote)
    clauses = _clauses(normalized)
    fields: list[FieldGrounding] = []
    if not quote or quote not in normalized:
        fields.append(_field("citation", GroundingStatus.INSUFFICIENT_EVIDENCE, "QUOTE_NOT_IN_EVENT"))
    else:
        fields.append(_field("citation", GroundingStatus.SUPPORTED, "QUOTE_IN_EVENT"))
    fields.append(_kind_field(claim, normalized, clauses, action, policy))
    fields.append(_identifier_field("issuer", claim.issuer, normalized, quote))
    fields.append(_subject_field(claim, normalized, quote))
    fields.append(_operation_field(claim, normalized, quote))
    fields.append(_target_field(claim, normalized, quote))
    for key, value in claim.scope:
        fields.append(_scope_field(key, value, normalized, quote))
    fields.append(_validity_field(claim, event_text, clauses, action))
    fields.append(_authentication_field(claim, clauses))
    fields.append(_transferable_field(claim, normalized, clauses))
    if not restrictive:
        fields.append(_qualification_field(claim, clauses, quote))

    statuses = {f.status for f in fields}
    if GroundingStatus.CONTRADICTED in statuses:
        status = GroundingStatus.CONTRADICTED
    elif GroundingStatus.INSUFFICIENT_EVIDENCE in statuses:
        status = GroundingStatus.INSUFFICIENT_EVIDENCE
    else:
        status = GroundingStatus.SUPPORTED
    return ClaimGrounding(claim.event_id, claim.kind, card_id, status, tuple(fields), restrictive)


# ---------------------------------------------------------------------------
# Context-level restrictive evidence scan
# ---------------------------------------------------------------------------


def scan_restrictive_signals(
    events: Mapping[str, str],
    action: ActionRequest,
    policy: ProofPolicy,
    claims: tuple[ExtractedClaim, ...],
    groundings: tuple[ClaimGrounding, ...],
) -> tuple[RestrictiveSignal, ...]:
    """Find hold, prohibition, denial or revocation cues linked to the action.

    A message is linked when it names the action target (and does not exclude
    it), or when any extracted claim cites it with the action target. The
    second link uses the extractor's own citation, so a message such as "Do
    not proceed with the transaction" is linked once a claim cites it.

    A signal is accounted for only when a ``SUPPORTED`` ``ACTIVE_HOLD`` claim
    cites the same message. The validator then decides whether that hold
    applies (scope, window, issuer, authentication).
    """

    target = action.target_id
    cited_for_target = {c.event_id for c in claims if c.target == target}
    accounted = {
        g.event_id for g in groundings
        if g.kind is ProofCardKind.ACTIVE_HOLD and g.status is GroundingStatus.SUPPORTED
    }
    signals: list[RestrictiveSignal] = []
    for event_id, text in events.items():
        normalized = normalize_text(text)
        names_target = _mentions(normalized, target) and not _target_excluded(normalized, target)
        if names_target:
            linked_by = "TARGET_MENTION"
        elif event_id in cited_for_target:
            linked_by = "CLAIM_CITATION"
        else:
            continue
        seen: set[tuple[str, str]] = set()
        for category, cue in _restrictive_cues(normalized, action, policy):
            key = (category, cue.text)
            if key in seen:
                continue
            seen.add(key)
            signals.append(
                RestrictiveSignal(event_id, category, cue.text, cue.clause, linked_by,
                                  event_id in accounted)
            )
    return tuple(signals)


# ---------------------------------------------------------------------------
# Gate around the existing validator
# ---------------------------------------------------------------------------


def _more_conservative(first: Decision, second: Decision) -> Decision:
    return first if _ROUTE_RANK[first] >= _ROUTE_RANK[second] else second


def ground_extraction(
    action: ActionRequest,
    policy: ProofPolicy,
    parse: ExtractionParse,
    events: Mapping[str, str],
    pre_verified_cards: tuple[ProofCard, ...] = (),
) -> GroundingGateResult:
    """Ground extracted claims, then route with the unchanged proof validator.

    ``events`` maps visible event IDs to message text. Callers should omit the
    system prompt; the NL adapter below does this. ``pre_verified_cards`` are
    typed records from an authenticated structured source (for example the
    durable proof store). They bypass grounding, reach both routes unchanged,
    and their source messages are not rescanned for restrictive cues.
    """

    if not parse.format_valid:
        return GroundingGateResult(
            decision=Decision.HANDOFF, baseline_decision=Decision.HANDOFF,
            failure_layer="EXTRACTION_FORMAT",
            reason_codes=(parse.error or "EXTRACTION_FORMAT_INVALID",),
            claim_groundings=(), admitted_card_ids=(), excluded_card_ids=(),
            restrictive_signals=(), validation=None, baseline_validation=None,
        )

    cards = claims_to_cards(parse.claims)
    baseline_validation = validate_proof_cards(
        ProofCardInput(action, policy, pre_verified_cards + cards)
    )
    groundings = tuple(
        verify_claim(claim, events.get(claim.event_id), action, policy) for claim in parse.claims
    )
    admitted: list[ProofCard] = list(pre_verified_cards)
    excluded: list[ProofCard] = []
    reasons: list[str] = []
    for card, grounding in zip(cards, groundings):
        if grounding.restrictive or grounding.status is GroundingStatus.SUPPORTED:
            admitted.append(card)
            if grounding.restrictive and grounding.status is not GroundingStatus.SUPPORTED:
                reasons.append(f"{card.card_id}:RESTRICTIVE_CLAIM_KEPT_DESPITE_{grounding.status.value}")
        else:
            excluded.append(card)
            reasons.extend(f"{card.card_id}:{code}" for code in grounding.reason_codes)

    structured_sources = {e for card in pre_verified_cards for e in card.source_event_ids}
    scanned = {k: v for k, v in events.items() if k not in structured_sources}
    signals = scan_restrictive_signals(scanned, action, policy, parse.claims, groundings)
    unaccounted = [s for s in signals if not s.accounted_for]
    validation = validate_proof_cards(ProofCardInput(action, policy, tuple(admitted)))

    if unaccounted:
        grounded_decision = Decision.HANDOFF
        reasons.extend(f"{s.event_id}:UNACCOUNTED_{s.category}" for s in unaccounted)
    else:
        grounded_decision = validation.decision
    decision = _more_conservative(grounded_decision, baseline_validation.decision)

    excluded_applicable = [c for c in excluded if _card_applies(c, action, policy)]
    contradicted_applicable = [
        c for c, g in zip(cards, groundings)
        if c in excluded_applicable and g.status is GroundingStatus.CONTRADICTED
    ]
    if unaccounted:
        layer = "UNACCOUNTED_RESTRICTIVE_EVIDENCE"
    elif decision is not baseline_validation.decision and contradicted_applicable:
        layer = "GROUNDING_CONTRADICTION"
    elif decision is not baseline_validation.decision:
        layer = "GROUNDING_ABSTENTION"
    elif validation.hold_status == "BLOCKED":
        layer = "AUTHORIZATION_HOLD"
    elif validation.missing_obligations:
        layer = "EVIDENCE_UNAVAILABLE"
    elif decision is Decision.REQUEST_CONFIRMATION:
        layer = "REPAIRABLE_AUTHORITY_GAP"
    else:
        layer = "NONE"

    return GroundingGateResult(
        decision=decision,
        baseline_decision=baseline_validation.decision,
        failure_layer=layer,
        reason_codes=tuple(reasons) + validation.reason_codes,
        claim_groundings=groundings,
        admitted_card_ids=tuple(c.card_id for c in admitted),
        excluded_card_ids=tuple(c.card_id for c in excluded),
        restrictive_signals=signals,
        validation=validation,
        baseline_validation=baseline_validation,
    )


def nl_context_events(context: NLContext) -> dict[str, str]:
    """Visible non-system messages of a natural-language context."""

    return {e.event_id: e.content for e in context.active_events if e.role != "system"}


def ground_nl_context(context: NLContext, parse: ExtractionParse) -> GroundingGateResult:
    """Adapter for the existing natural-language contexts; reads no gold field."""

    return ground_extraction(context.action, context.policy, parse, nl_context_events(context))
