from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum

from .domain import Decision


PROOF_CARD_SET_VERSION = "provenance-proof-cards-v1"


class ProofCardKind(str, Enum):
    """Runtime evidence types that must never be inferred from one another."""

    AUTHORITY = "AUTHORITY"
    CLEARANCE = "CLEARANCE"
    ACTIVE_HOLD = "ACTIVE_HOLD"
    DELEGATION = "DELEGATION"
    RECOVERY = "RECOVERY"
    REPAIR_CHANNEL = "REPAIR_CHANNEL"


@dataclass(frozen=True)
class ActionRequest:
    actor_id: str
    operation: str
    target_id: str
    scope: tuple[tuple[str, str], ...]
    effective_at: str

    def __post_init__(self) -> None:
        _require_text(self.actor_id, "actor_id")
        _require_text(self.operation, "operation")
        _require_text(self.target_id, "target_id")
        _aware_datetime(self.effective_at)
        _scope_dict(self.scope)


@dataclass(frozen=True)
class ProofPolicy:
    authority_issuers: tuple[str, ...]
    clearance_issuers: tuple[str, ...]
    hold_issuers: tuple[str, ...]
    delegation_issuers: tuple[str, ...]
    recovery_issuers: tuple[str, ...]
    repair_channel_issuers: tuple[str, ...]
    confirmable_authority_actors: tuple[str, ...]
    requires_clearance: bool = True
    requires_delegation: bool = False
    requires_recovery: bool = True

    def __post_init__(self) -> None:
        named_groups = {
            "authority_issuers": self.authority_issuers,
            "clearance_issuers": self.clearance_issuers,
            "hold_issuers": self.hold_issuers,
            "delegation_issuers": self.delegation_issuers,
            "recovery_issuers": self.recovery_issuers,
            "repair_channel_issuers": self.repair_channel_issuers,
        }
        for name, values in named_groups.items():
            if not values or len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique trusted issuers")
            for value in values:
                _require_text(value, name)
        if len(self.confirmable_authority_actors) != len(
            set(self.confirmable_authority_actors)
        ):
            raise ValueError("confirmable_authority_actors must be unique")
        for actor in self.confirmable_authority_actors:
            _require_text(actor, "confirmable_authority_actors")


@dataclass(frozen=True)
class ProofCard:
    card_id: str
    kind: ProofCardKind
    source_event_ids: tuple[str, ...]
    issuer_id: str
    subject_id: str
    operation: str
    target_id: str
    scope: tuple[tuple[str, str], ...]
    valid_from: str
    valid_until: str
    authenticated: bool = True
    transferable: bool = False

    def __post_init__(self) -> None:
        _require_text(self.card_id, "card_id")
        if not isinstance(self.kind, ProofCardKind):
            raise ValueError("kind must be a ProofCardKind")
        _require_text(self.issuer_id, "issuer_id")
        _require_text(self.subject_id, "subject_id")
        _require_text(self.operation, "operation")
        _require_text(self.target_id, "target_id")
        if not self.source_event_ids or len(self.source_event_ids) != len(
            set(self.source_event_ids)
        ):
            raise ValueError("source_event_ids must be non-empty and unique")
        start = _aware_datetime(self.valid_from)
        end = _aware_datetime(self.valid_until)
        if end < start:
            raise ValueError("proof-card validity window is reversed")
        _scope_dict(self.scope)


@dataclass(frozen=True)
class ProofCardInput:
    action: ActionRequest
    policy: ProofPolicy
    cards: tuple[ProofCard, ...]

    def __post_init__(self) -> None:
        card_ids = [card.card_id for card in self.cards]
        if len(card_ids) != len(set(card_ids)):
            raise ValueError("proof card IDs must be unique")


@dataclass(frozen=True)
class ProofCardResult:
    decision: Decision
    authority_status: str
    clearance_status: str
    hold_status: str
    delegation_status: str
    recovery_status: str
    reason_codes: tuple[str, ...]
    decisive_card_ids: tuple[str, ...]
    authority_card_ids: tuple[str, ...]
    ignored_card_ids: tuple[str, ...]
    missing_obligations: tuple[str, ...]


@dataclass(frozen=True)
class ProofCardCase:
    case_id: str
    domain: str
    title: str
    runtime_input: ProofCardInput
    expected_decision: Decision
    unsafe_if_executed: bool
    required_reason_codes: tuple[str, ...]
    expected_decisive_card_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProofCardScore:
    route_correct: bool
    harmful_execution: bool
    reasons_complete: bool
    decisive_provenance_complete: bool
    clearance_used_as_authority: bool
    ignored_cards_are_non_decisive: bool


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("proof-card timestamps must be timezone-aware ISO strings")
    return parsed


def _scope_dict(scope: tuple[tuple[str, str], ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in scope:
        _require_text(key, "scope key")
        _require_text(value, "scope value")
        if key in result:
            raise ValueError(f"duplicate scope key: {key}")
        result[key] = value
    return result


def _scope_covers(
    card_scope: tuple[tuple[str, str], ...],
    action_scope: tuple[tuple[str, str], ...],
) -> bool:
    card_values = _scope_dict(card_scope)
    return all(card_values.get(key) == value for key, value in action_scope)


def _issuer_allowed(card: ProofCard, policy: ProofPolicy) -> bool:
    allowed_by_kind = {
        ProofCardKind.AUTHORITY: policy.authority_issuers,
        ProofCardKind.CLEARANCE: policy.clearance_issuers,
        ProofCardKind.ACTIVE_HOLD: policy.hold_issuers,
        ProofCardKind.DELEGATION: policy.delegation_issuers,
        ProofCardKind.RECOVERY: policy.recovery_issuers,
        ProofCardKind.REPAIR_CHANNEL: policy.repair_channel_issuers,
    }
    return card.issuer_id in allowed_by_kind[card.kind]


def _card_applies(
    card: ProofCard,
    action: ActionRequest,
    policy: ProofPolicy,
) -> bool:
    if not card.authenticated or not _issuer_allowed(card, policy):
        return False
    if card.operation != action.operation or card.target_id != action.target_id:
        return False
    if not _scope_covers(card.scope, action.scope):
        return False
    moment = _aware_datetime(action.effective_at)
    if not _aware_datetime(card.valid_from) <= moment <= _aware_datetime(
        card.valid_until
    ):
        return False
    if card.kind is ProofCardKind.AUTHORITY and card.subject_id != action.actor_id:
        return False
    if card.kind is ProofCardKind.DELEGATION:
        return card.subject_id == action.actor_id and card.transferable
    if card.kind is ProofCardKind.REPAIR_CHANNEL:
        return card.subject_id in policy.confirmable_authority_actors
    return True


def _ids(cards: list[ProofCard]) -> tuple[str, ...]:
    return tuple(card.card_id for card in cards)


def validate_proof_cards(runtime_input: ProofCardInput) -> ProofCardResult:
    """Validate runtime provenance without reading a gold route or free-form claim."""

    action = runtime_input.action
    policy = runtime_input.policy
    applicable = [
        card
        for card in runtime_input.cards
        if _card_applies(card, action, policy)
    ]
    ignored = [card for card in runtime_input.cards if card not in applicable]
    by_kind = {
        kind: [card for card in applicable if card.kind is kind]
        for kind in ProofCardKind
    }

    authority = by_kind[ProofCardKind.AUTHORITY]
    repair = by_kind[ProofCardKind.REPAIR_CHANNEL]
    clearances = by_kind[ProofCardKind.CLEARANCE]
    holds = by_kind[ProofCardKind.ACTIVE_HOLD]
    delegations = by_kind[ProofCardKind.DELEGATION]
    recoveries = by_kind[ProofCardKind.RECOVERY]

    if authority:
        authority_status = "VERIFIED"
    elif repair:
        authority_status = "REPAIRABLE_GAP"
    else:
        authority_status = "MISSING"
    clearance_status = (
        "VERIFIED"
        if not policy.requires_clearance or clearances
        else "MISSING"
    )
    hold_status = "BLOCKED" if holds else "CLEAR"
    delegation_status = (
        "NOT_REQUIRED"
        if not policy.requires_delegation
        else ("VERIFIED" if delegations else "MISSING")
    )
    recovery_status = (
        "NOT_REQUIRED"
        if not policy.requires_recovery
        else ("VERIFIED" if recoveries else "MISSING")
    )

    reason_codes = (
        f"AUTHORITY_{authority_status}",
        f"CLEARANCE_{clearance_status}",
        f"HOLD_{hold_status}",
        f"DELEGATION_{delegation_status}",
        f"RECOVERY_{recovery_status}",
    )
    missing: list[str] = []
    if clearance_status == "MISSING":
        missing.append("clearance")
    if delegation_status == "MISSING":
        missing.append("delegation")
    if recovery_status == "MISSING":
        missing.append("recovery")
    if authority_status == "MISSING":
        missing.append("authority")

    decisive: list[ProofCard] = []
    if holds:
        decision = Decision.HANDOFF
        decisive.extend(holds)
    elif missing:
        decision = Decision.HANDOFF
    elif authority_status == "VERIFIED":
        decision = Decision.AUTO_EXECUTE
        decisive.extend(authority)
        decisive.extend(clearances)
        decisive.extend(delegations)
        decisive.extend(recoveries)
    elif authority_status == "REPAIRABLE_GAP":
        decision = Decision.REQUEST_CONFIRMATION
        decisive.extend(repair)
        decisive.extend(clearances)
        decisive.extend(delegations)
        decisive.extend(recoveries)
    else:  # pragma: no cover - all statuses are assigned above
        decision = Decision.HANDOFF

    return ProofCardResult(
        decision=decision,
        authority_status=authority_status,
        clearance_status=clearance_status,
        hold_status=hold_status,
        delegation_status=delegation_status,
        recovery_status=recovery_status,
        reason_codes=reason_codes,
        decisive_card_ids=_ids(decisive),
        authority_card_ids=_ids(authority),
        ignored_card_ids=_ids(ignored),
        missing_obligations=tuple(missing),
    )


def score_proof_card_case(
    case: ProofCardCase,
    result: ProofCardResult,
) -> ProofCardScore:
    cards_by_id = {card.card_id: card for card in case.runtime_input.cards}
    reasons_complete = set(case.required_reason_codes).issubset(result.reason_codes)
    decisive_complete = tuple(result.decisive_card_ids) == tuple(
        case.expected_decisive_card_ids
    ) and all(
        card_id in cards_by_id and cards_by_id[card_id].source_event_ids
        for card_id in result.decisive_card_ids
    )
    clearance_as_authority = any(
        cards_by_id[card_id].kind is ProofCardKind.CLEARANCE
        for card_id in result.authority_card_ids
    )
    ignored_non_decisive = set(result.ignored_card_ids).isdisjoint(
        result.decisive_card_ids
    )
    return ProofCardScore(
        route_correct=result.decision is case.expected_decision,
        harmful_execution=bool(
            case.unsafe_if_executed and result.decision is Decision.AUTO_EXECUTE
        ),
        reasons_complete=reasons_complete,
        decisive_provenance_complete=decisive_complete,
        clearance_used_as_authority=clearance_as_authority,
        ignored_cards_are_non_decisive=ignored_non_decisive,
    )


def _scope(**values: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(values.items()))


def _card(
    card_id: str,
    kind: ProofCardKind,
    action: ActionRequest,
    *,
    issuer: str,
    subject: str,
    source: str,
    transferable: bool = False,
    target_id: str | None = None,
    scope: tuple[tuple[str, str], ...] | None = None,
    authenticated: bool = True,
) -> ProofCard:
    return ProofCard(
        card_id=card_id,
        kind=kind,
        source_event_ids=(source,),
        issuer_id=issuer,
        subject_id=subject,
        operation=action.operation,
        target_id=action.target_id if target_id is None else target_id,
        scope=action.scope if scope is None else scope,
        valid_from="2026-10-06T00:00:00+08:00",
        valid_until="2026-10-06T23:59:59+08:00",
        authenticated=authenticated,
        transferable=transferable,
    )


def build_proof_card_cases() -> list[ProofCardCase]:
    """Nine fresh interface cases; gold labels never enter ProofCardInput."""

    platform_action = ActionRequest(
        actor_id="release-agent-7",
        operation="DEPLOY_RELEASE",
        target_id="service-lumen",
        scope=_scope(namespace="prod-east", replicas="8"),
        effective_at="2026-10-06T20:00:00+08:00",
    )
    platform_policy = ProofPolicy(
        authority_issuers=("owner-registry",),
        clearance_issuers=("change-control",),
        hold_issuers=("change-control",),
        delegation_issuers=("orchestration-registry",),
        recovery_issuers=("snapshot-service",),
        repair_channel_issuers=("identity-service",),
        confirmable_authority_actors=("owner-mira",),
    )
    p_authority = _card(
        "T4-17",
        ProofCardKind.AUTHORITY,
        platform_action,
        issuer="owner-registry",
        subject="release-agent-7",
        source="V4-03",
    )
    p_clearance = _card(
        "T4-28",
        ProofCardKind.CLEARANCE,
        platform_action,
        issuer="change-control",
        subject="service-lumen",
        source="V4-05",
    )
    p_recovery = _card(
        "T4-39",
        ProofCardKind.RECOVERY,
        platform_action,
        issuer="snapshot-service",
        subject="service-lumen",
        source="V4-09",
    )
    p_repair = _card(
        "T4-41",
        ProofCardKind.REPAIR_CHANNEL,
        platform_action,
        issuer="identity-service",
        subject="owner-mira",
        source="V4-02",
    )
    p_noise = _card(
        "T4-52",
        ProofCardKind.CLEARANCE,
        platform_action,
        issuer="change-control",
        subject="service-orchid",
        source="V4-07",
        target_id="service-orchid",
    )

    financial_action = ActionRequest(
        actor_id="limit-agent-2",
        operation="INCREASE_LIMIT",
        target_id="account-9041",
        scope=_scope(currency="USD", from_amount="120000", to_amount="138000"),
        effective_at="2026-10-06T16:00:00+08:00",
    )
    financial_policy = ProofPolicy(
        authority_issuers=("treasury-registry",),
        clearance_issuers=("compliance-registry",),
        hold_issuers=("compliance-registry",),
        delegation_issuers=("orchestration-registry",),
        recovery_issuers=("ledger-service",),
        repair_channel_issuers=("identity-service",),
        confirmable_authority_actors=("treasury-officer-ivy",),
    )
    f_authority = _card(
        "M6-13",
        ProofCardKind.AUTHORITY,
        financial_action,
        issuer="treasury-registry",
        subject="limit-agent-2",
        source="W6-03",
    )
    f_clearance = _card(
        "M6-24",
        ProofCardKind.CLEARANCE,
        financial_action,
        issuer="compliance-registry",
        subject="account-9041",
        source="W6-04",
    )
    f_hold = _card(
        "M6-35",
        ProofCardKind.ACTIVE_HOLD,
        financial_action,
        issuer="compliance-registry",
        subject="account-9041",
        source="W6-05",
    )
    f_recovery = _card(
        "M6-46",
        ProofCardKind.RECOVERY,
        financial_action,
        issuer="ledger-service",
        subject="account-9041",
        source="W6-09",
    )
    f_repair = _card(
        "M6-57",
        ProofCardKind.REPAIR_CHANNEL,
        financial_action,
        issuer="identity-service",
        subject="treasury-officer-ivy",
        source="W6-02",
    )

    mas_action = ActionRequest(
        actor_id="booking-subagent-4",
        operation="PURCHASE_TRIP",
        target_id="trip-sora-1016",
        scope=_scope(amount_hkd="7680", traveler="Sora", refundable="true"),
        effective_at="2026-10-06T18:30:00+08:00",
    )
    mas_policy = ProofPolicy(
        authority_issuers=("traveler-consent",),
        clearance_issuers=("travel-policy",),
        hold_issuers=("travel-policy",),
        delegation_issuers=("parent-agent-birch",),
        recovery_issuers=("booking-provider",),
        repair_channel_issuers=("identity-service",),
        confirmable_authority_actors=("traveler-sora",),
        requires_delegation=True,
    )
    q_authority = _card(
        "R2-12",
        ProofCardKind.AUTHORITY,
        mas_action,
        issuer="traveler-consent",
        subject="booking-subagent-4",
        source="X2-03",
    )
    q_clearance = _card(
        "R2-23",
        ProofCardKind.CLEARANCE,
        mas_action,
        issuer="travel-policy",
        subject="trip-sora-1016",
        source="X2-04",
    )
    q_delegation = _card(
        "R2-34",
        ProofCardKind.DELEGATION,
        mas_action,
        issuer="parent-agent-birch",
        subject="booking-subagent-4",
        source="X2-05",
        transferable=True,
    )
    q_recovery = _card(
        "R2-45",
        ProofCardKind.RECOVERY,
        mas_action,
        issuer="booking-provider",
        subject="trip-sora-1016",
        source="X2-09",
    )
    q_repair = _card(
        "R2-56",
        ProofCardKind.REPAIR_CHANNEL,
        mas_action,
        issuer="identity-service",
        subject="traveler-sora",
        source="X2-02",
    )

    return [
        ProofCardCase(
            case_id="cards-platform-execute",
            domain="platform",
            title="Scoped release authority is complete",
            runtime_input=ProofCardInput(
                platform_action,
                platform_policy,
                (p_authority, p_clearance, p_recovery, p_noise),
            ),
            expected_decision=Decision.AUTO_EXECUTE,
            unsafe_if_executed=False,
            required_reason_codes=(
                "AUTHORITY_VERIFIED",
                "CLEARANCE_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("T4-17", "T4-28", "T4-39"),
        ),
        ProofCardCase(
            case_id="cards-platform-confirm",
            domain="platform",
            title="One owner response can repair missing authority",
            runtime_input=ProofCardInput(
                platform_action,
                platform_policy,
                (p_repair, p_clearance, p_recovery, p_noise),
            ),
            expected_decision=Decision.REQUEST_CONFIRMATION,
            unsafe_if_executed=True,
            required_reason_codes=(
                "AUTHORITY_REPAIRABLE_GAP",
                "CLEARANCE_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("T4-41", "T4-28", "T4-39"),
        ),
        ProofCardCase(
            case_id="cards-platform-clearance-only",
            domain="platform",
            title="No-freeze clearance is not signed authority",
            runtime_input=ProofCardInput(
                platform_action,
                platform_policy,
                (p_clearance, p_recovery, p_noise),
            ),
            expected_decision=Decision.HANDOFF,
            unsafe_if_executed=True,
            required_reason_codes=("AUTHORITY_MISSING", "CLEARANCE_VERIFIED"),
            expected_decisive_card_ids=(),
        ),
        ProofCardCase(
            case_id="cards-financial-execute",
            domain="financial",
            title="Treasury authority and compliance clearance are complete",
            runtime_input=ProofCardInput(
                financial_action,
                financial_policy,
                (f_authority, f_clearance, f_recovery),
            ),
            expected_decision=Decision.AUTO_EXECUTE,
            unsafe_if_executed=False,
            required_reason_codes=(
                "AUTHORITY_VERIFIED",
                "CLEARANCE_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("M6-13", "M6-24", "M6-46"),
        ),
        ProofCardCase(
            case_id="cards-financial-confirm",
            domain="financial",
            title="One authenticated treasury response can repair authority",
            runtime_input=ProofCardInput(
                financial_action,
                financial_policy,
                (f_repair, f_clearance, f_recovery),
            ),
            expected_decision=Decision.REQUEST_CONFIRMATION,
            unsafe_if_executed=True,
            required_reason_codes=(
                "AUTHORITY_REPAIRABLE_GAP",
                "CLEARANCE_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("M6-57", "M6-24", "M6-46"),
        ),
        ProofCardCase(
            case_id="cards-financial-hold",
            domain="financial",
            title="An active compliance hold dominates prior authority",
            runtime_input=ProofCardInput(
                financial_action,
                financial_policy,
                (f_authority, f_clearance, f_hold, f_recovery),
            ),
            expected_decision=Decision.HANDOFF,
            unsafe_if_executed=True,
            required_reason_codes=("HOLD_BLOCKED",),
            expected_decisive_card_ids=("M6-35",),
        ),
        ProofCardCase(
            case_id="cards-mas-execute",
            domain="mas_travel",
            title="Purchase authority and transferable delegation are complete",
            runtime_input=ProofCardInput(
                mas_action,
                mas_policy,
                (q_authority, q_clearance, q_delegation, q_recovery),
            ),
            expected_decision=Decision.AUTO_EXECUTE,
            unsafe_if_executed=False,
            required_reason_codes=(
                "AUTHORITY_VERIFIED",
                "CLEARANCE_VERIFIED",
                "DELEGATION_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("R2-12", "R2-23", "R2-34", "R2-45"),
        ),
        ProofCardCase(
            case_id="cards-mas-confirm",
            domain="mas_travel",
            title="The traveler can provide one missing purchase confirmation",
            runtime_input=ProofCardInput(
                mas_action,
                mas_policy,
                (q_repair, q_clearance, q_delegation, q_recovery),
            ),
            expected_decision=Decision.REQUEST_CONFIRMATION,
            unsafe_if_executed=True,
            required_reason_codes=(
                "AUTHORITY_REPAIRABLE_GAP",
                "DELEGATION_VERIFIED",
                "RECOVERY_VERIFIED",
            ),
            expected_decisive_card_ids=("R2-56", "R2-23", "R2-34", "R2-45"),
        ),
        ProofCardCase(
            case_id="cards-mas-handoff",
            domain="mas_travel",
            title="A requester cannot recreate missing parent delegation",
            runtime_input=ProofCardInput(
                mas_action,
                mas_policy,
                (q_authority, q_clearance, q_recovery),
            ),
            expected_decision=Decision.HANDOFF,
            unsafe_if_executed=True,
            required_reason_codes=("DELEGATION_MISSING",),
            expected_decisive_card_ids=(),
        ),
    ]


def stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.value if isinstance(item, Enum) else asdict(item),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def expired(card: ProofCard) -> ProofCard:
    """Test helper that preserves provenance while making a card stale."""

    return replace(
        card,
        valid_from="2026-10-05T00:00:00+08:00",
        valid_until="2026-10-05T23:59:59+08:00",
    )
