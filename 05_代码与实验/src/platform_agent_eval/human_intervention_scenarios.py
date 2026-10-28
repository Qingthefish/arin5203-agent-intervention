"""Scenario matrix for the closed-loop human-intervention protocol evaluation.

Three families (release deploy, repository access, shipment release with a
required delegation) instantiate the same 25 scenario types. The families are
template instantiations of one protocol script, so the unit of analysis is the
scenario type; the three instances are correlated, not independent samples.

Expected outcomes encode the protocol specification written before the run:
which responses should be accepted, how many times each action binding should
execute, and the final request state. They are scoring labels only; the
workflow never reads them. Responders are scripted fixtures, not people.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from .durable_proof_store import DurableProofRecord, DurableProofStore
from .human_intervention_workflow import (
    ActionBinding,
    ResponderDirectory,
    ResponseDecision,
    TimelineEvidenceProvider,
    TrustedChannel,
)
from .proof_cards import ActionRequest, ProofCard, ProofCardKind, ProofPolicy


HUMAN_INTERVENTION_SCENARIO_SET_VERSION = "human-intervention-scenarios-v1"
CONFIRMATION_ISSUER = "confirmation-ledger"
REQUEST_TTL_MINUTES = 30
APPROVAL_TTL_MINUTES = 15


@dataclass(frozen=True)
class Family:
    family_id: str
    domain: str
    start: str
    action: ActionRequest
    policy: ProofPolicy
    responder: str
    other_person: str
    amount_key: str
    base_cards: tuple[ProofCard, ...]
    state_before: dict[str, object] = field(hash=False)
    state_after: dict[str, object] = field(hash=False)

    def at(self, minutes: float) -> str:
        return (datetime.fromisoformat(self.start) + timedelta(minutes=minutes)).isoformat()

    @property
    def directory(self) -> ResponderDirectory:
        return ResponderDirectory((
            TrustedChannel(f"chan-{self.responder}", self.responder),
            TrustedChannel(f"chan-{self.other_person}", self.other_person),
        ))


@dataclass(frozen=True)
class Step:
    """One scripted event. ``kind`` is advance, start, respond, execute or cancel."""

    kind: str
    minutes: float = 0.0
    request: int = 0
    action: str = "original"
    responder_override: str | None = None
    response_id: str = ""
    channel: str = "responder"
    decision: ResponseDecision = ResponseDecision.APPROVE
    mutation: str = "none"
    category: str = ""
    expected_accept: bool = False


@dataclass(frozen=True)
class Scenario:
    scenario_type: str
    family_id: str
    description: str
    steps: tuple[Step, ...]
    extra_records: tuple[DurableProofRecord, ...]
    removed_base_kinds: tuple[ProofCardKind, ...]
    policy_versions: tuple[tuple[float, str], ...]
    outages: tuple[tuple[float, float], ...]
    expected_executions: tuple[tuple[str, int], ...]
    expected_final_states: tuple[str, ...]
    expects_completion: bool
    expects_handoff: bool

    @property
    def scenario_id(self) -> str:
        return f"{self.family_id}:{self.scenario_type}"


def _card(card_id: str, kind: ProofCardKind, issuer: str, subject: str,
          action: ActionRequest, *, transferable: bool = False) -> ProofCard:
    day = action.effective_at[:10]
    offset = action.effective_at[-6:]
    return ProofCard(card_id, kind, (f"ev-{card_id}",), issuer, subject, action.operation,
                     action.target_id, action.scope, f"{day}T00:00:00{offset}",
                     f"{day}T23:59:59{offset}", transferable=transferable)


def _policy(prefix: str, responder: str, *, delegation: bool = False) -> ProofPolicy:
    return ProofPolicy(
        authority_issuers=(f"{prefix}-owner-registry", CONFIRMATION_ISSUER),
        clearance_issuers=(f"{prefix}-risk",),
        hold_issuers=(f"{prefix}-risk",),
        delegation_issuers=(f"{prefix}-orchestrator",),
        recovery_issuers=(f"{prefix}-recovery",),
        repair_channel_issuers=("identity-service",),
        confirmable_authority_actors=(responder,),
        requires_delegation=delegation,
    )


def _family(family_id: str, domain: str, start: str, action: ActionRequest, prefix: str,
            responder: str, other: str, amount_key: str, delegation: bool,
            before: dict[str, object], after: dict[str, object]) -> Family:
    action = replace(action, effective_at=start)
    cards = [
        _card(f"{family_id}-clr", ProofCardKind.CLEARANCE, f"{prefix}-risk", action.target_id, action),
        _card(f"{family_id}-rec", ProofCardKind.RECOVERY, f"{prefix}-recovery", action.target_id, action),
        _card(f"{family_id}-rep", ProofCardKind.REPAIR_CHANNEL, "identity-service", responder, action),
    ]
    if delegation:
        cards.append(_card(f"{family_id}-del", ProofCardKind.DELEGATION, f"{prefix}-orchestrator",
                           action.actor_id, action, transferable=True))
    return Family(family_id, domain, start, action, _policy(prefix, responder, delegation=delegation),
                  responder, other, amount_key, tuple(cards), before, after)


def build_families() -> list[Family]:
    return [
        _family("HI1", "platform_release", "2026-11-24T10:00:00+08:00",
                ActionRequest("release-agent-h1", "DEPLOY_RELEASE", "service-lumen-9",
                              (("namespace", "prod-east"), ("replicas", "8")),
                              "2026-11-24T10:00:00+08:00"),
                "platform", "owner-mira", "intern-kai", "replicas", False,
                {"service-lumen-9.version": "v41"}, {"service-lumen-9.version": "v42"}),
        _family("HI2", "access_management", "2026-11-25T14:00:00+08:00",
                ActionRequest("access-agent-h2", "GRANT_ACCESS", "repo-heron-12",
                              (("duration_days", "30"), ("role", "maintainer")),
                              "2026-11-25T14:00:00+08:00"),
                "access", "lead-omar", "contractor-dan", "duration_days", False,
                {"repo-heron-12.maintainers": 3}, {"repo-heron-12.maintainers": 4}),
        _family("HI3", "logistics", "2026-11-26T09:30:00+08:00",
                ActionRequest("dispatch-agent-h3", "RELEASE_SHIPMENT", "shipment-kestrel-5521",
                              (("carrier", "northwind"), ("value_usd", "48500")),
                              "2026-11-26T09:30:00+08:00"),
                "trade", "buyer-kim", "warehouse-lee", "value_usd", True,
                {"shipment-kestrel-5521.status": "held"},
                {"shipment-kestrel-5521.status": "released"}),
    ]


# ---------------------------------------------------------------------------
# Variants of the action used by some scenarios
# ---------------------------------------------------------------------------


def action_variant(family: Family, name: str) -> ActionRequest:
    action = family.action
    if name == "original":
        return action
    if name == "changed_amount":
        scope = tuple((k, str(int(v) * 2) if k == family.amount_key else v) for k, v in action.scope)
        return replace(action, scope=scope)
    if name == "second_target":
        return replace(action, target_id=action.target_id + "-b")
    raise ValueError(f"unknown action variant {name}")


def provider_for(family: Family, scenario: Scenario) -> TimelineEvidenceProvider:
    committed = family.at(-60)
    records = [
        DurableProofRecord(f"rec-{card.card_id}", card, committed)
        for card in family.base_cards if card.kind not in scenario.removed_base_kinds
    ]
    second = action_variant(family, "second_target")
    for card in family.base_cards:
        subject = card.subject_id if card.kind in {ProofCardKind.REPAIR_CHANNEL,
                                                   ProofCardKind.DELEGATION} else second.target_id
        moved = replace(card, card_id=card.card_id + "-b", target_id=second.target_id,
                        subject_id=subject, source_event_ids=(f"ev-{card.card_id}-b",))
        records.append(DurableProofRecord(f"rec-{moved.card_id}", moved, committed))
    records.extend(scenario.extra_records)
    policies = {"base": family.policy,
                "requires_delegation": replace(family.policy, requires_delegation=True,
                                               delegation_issuers=("unused-orchestrator",)),
                "harmless": replace(family.policy, recovery_issuers=family.policy.recovery_issuers
                                    + ("backup-recovery",))}
    versions = tuple((family.at(minutes), policies[name]) for minutes, name in scenario.policy_versions)
    outages = tuple((family.at(a), family.at(b)) for a, b in scenario.outages)
    store = DurableProofStore(f"{family.family_id}-registry", "snapshot-1", tuple(records))
    return TimelineEvidenceProvider(versions, (), store, outages)


def transitions_for(family: Family) -> dict[str, dict[str, object]]:
    return {
        ActionBinding.of(action_variant(family, name)).sha256: dict(family.state_after)
        for name in ("original", "changed_amount", "second_target")
    }


# ---------------------------------------------------------------------------
# Scenario types
# ---------------------------------------------------------------------------


def _respond(response_id: str, category: str, expected: bool, **kwargs: object) -> Step:
    return Step("respond", response_id=response_id, category=category, expected_accept=expected,
                **kwargs)  # type: ignore[arg-type]


def _scenarios_for(f: Family) -> list[Scenario]:
    def sc(kind: str, description: str, steps: list[Step], *, executions: dict[str, int],
           states: tuple[str, ...], completion: bool, handoff: bool,
           extra: tuple[DurableProofRecord, ...] = (), removed: tuple[ProofCardKind, ...] = (),
           policies: tuple[tuple[float, str], ...] = ((0.0, "base"),),
           outages: tuple[tuple[float, float], ...] = (),
           first: Step = Step("start")) -> Scenario:
        exec_map = {"original": 0, "changed_amount": 0, "second_target": 0, **executions}
        return Scenario(kind, f.family_id, description, (first,) + tuple(steps), extra,
                        removed, policies, outages, tuple(sorted(exec_map.items())), states,
                        completion, handoff)

    hold = next(c for c in f.base_cards if c.kind is ProofCardKind.CLEARANCE)
    hold = replace(hold, card_id=f"{f.family_id}-hold", kind=ProofCardKind.ACTIVE_HOLD,
                   source_event_ids=(f"ev-{f.family_id}-hold",))
    repair = next(c for c in f.base_cards if c.kind is ProofCardKind.REPAIR_CHANNEL)
    clearance = next(c for c in f.base_cards if c.kind is ProofCardKind.CLEARANCE)
    ok = _respond("r1", "valid", True)
    adv = lambda m: Step("advance", minutes=m)  # noqa: E731
    run = Step("execute")

    return [
        sc("valid_timely", "Correct responder approves in time.", [adv(5), ok, run],
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
        sc("wrong_person", "An authenticated but unaddressed person approves.",
           [adv(5), _respond("r1", "unauthorized", False, channel="other"), run, adv(31)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("unverified_identity_claim", "Unknown channel claims to be the responder.",
           [adv(5), _respond("r1", "unauthorized", False, channel="unknown",
                             mutation="claim_responder"), run, adv(31)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("identity_claim_on_other_channel", "Another person's channel claims the responder name.",
           [adv(5), _respond("r1", "unauthorized", False, channel="other",
                             mutation="claim_responder"), run, adv(31)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("addressee_without_authority", "Agent tries to ask a person who cannot repair the gap.",
           [], executions={}, states=("NO_REQUEST",), completion=False, handoff=True,
           first=Step("start", responder_override="other")),
        sc("different_amount", "Responder approves a different amount.",
           [adv(5), _respond("r1", "mismatched", False, mutation="amount"), run, adv(31)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("different_target", "Responder approves a different target.",
           [adv(5), _respond("r1", "mismatched", False, mutation="target"), run, adv(31)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("approval_stale_before_execution", "Valid approval, execution after it lapses.",
           [adv(5), ok, adv(21), run],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("request_expired_before_response", "Reply after the deadline with a backdated claim.",
           [adv(31), _respond("r1", "stale", False, mutation="backdated"), run],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("explicit_rejection", "Responder rejects, then a later approval arrives.",
           [adv(5), _respond("r1", "valid", True, decision=ResponseDecision.REJECT),
            _respond("r2", "after_terminal", False), run],
           executions={}, states=("REJECTED",), completion=False, handoff=False),
        sc("hold_appears_while_waiting", "A hold is committed before the reply.",
           [adv(5), ok, run], extra=(DurableProofRecord("rec-hold", hold, f.at(3)),),
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("responder_authority_revoked", "The repair channel is revoked while waiting.",
           [adv(5), _respond("r1", "authority_lapsed", False), run],
           extra=(DurableProofRecord("rec-rep-revoked", replace(repair, card_id=repair.card_id + "-x"),
                                     f.at(-60), f.at(2)),),
           removed=(ProofCardKind.REPAIR_CHANNEL,),
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("relevant_policy_change", "Policy starts requiring a delegation nobody holds.",
           [adv(5), ok, run], policies=((0.0, "base"), (4.0, "requires_delegation")),
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("harmless_policy_change", "Policy adds an unrelated recovery issuer.",
           [adv(5), ok, run], policies=((0.0, "base"), (4.0, "harmless")),
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
        sc("duplicate_identical_response", "The same reply is delivered twice; agent retries.",
           [adv(5), ok, run, _respond("r1", "duplicate", False), run],
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
        sc("conflicting_responses", "Approval, then rejection before execution.",
           [adv(5), ok, _respond("r2", "conflict", True, decision=ResponseDecision.REJECT), run],
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("parameters_changed_after_approval", "Agent executes a doubled amount.",
           [adv(5), ok, Step("execute", action="changed_amount"), adv(21)],
           executions={}, states=("EXPIRED",), completion=False, handoff=False),
        sc("replay_old_approval", "First approval is replayed against a second request.",
           [adv(5), ok, run, Step("start", action="second_target"),
            _respond("r1", "replay", False, request=1, mutation="replay_from_first"),
            Step("execute", request=1, action="second_target"), adv(40)],
           executions={"original": 1}, states=("COMPLETED", "EXPIRED"),
           completion=True, handoff=False),
        sc("cancelled_before_approval", "Requester cancels, then an approval arrives.",
           [adv(2), Step("cancel"), adv(5), _respond("r1", "after_terminal", False), run],
           executions={}, states=("CANCELLED",), completion=False, handoff=False),
        sc("evidence_source_unavailable", "Registry is down at execution time.",
           [adv(5), ok, adv(6), run], outages=((6.0, 20.0),),
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("remaining_obligation_lapses", "Clearance is revoked after the approval.",
           [adv(5), ok, adv(7), run],
           extra=(DurableProofRecord("rec-clr-revoked", replace(clearance, card_id=clearance.card_id + "-x"),
                                     f.at(-60), f.at(6)),),
           removed=(ProofCardKind.CLEARANCE,),
           executions={}, states=("ESCALATED",), completion=False, handoff=True),
        sc("initial_handoff_not_converted", "Clearance is missing from the start.",
           [], removed=(ProofCardKind.CLEARANCE,),
           executions={}, states=("NO_REQUEST",), completion=False, handoff=True),
        sc("repeated_execution_request", "Agent calls execute three times.",
           [adv(5), ok, run, run, run],
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
        sc("clarify_then_approve", "Responder asks a question, then approves.",
           [adv(3), _respond("r1", "clarify", True, decision=ResponseDecision.CLARIFY), run,
            adv(5), _respond("r2", "valid", True), run],
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
        sc("junk_then_valid", "A wrong person replies first, then the responder approves.",
           [adv(3), _respond("r1", "unauthorized", False, channel="other"), adv(5),
            _respond("r2", "valid", True), run],
           executions={"original": 1}, states=("COMPLETED",), completion=True, handoff=False),
    ]


def build_scenarios() -> list[Scenario]:
    return [scenario for family in build_families() for scenario in _scenarios_for(family)]
