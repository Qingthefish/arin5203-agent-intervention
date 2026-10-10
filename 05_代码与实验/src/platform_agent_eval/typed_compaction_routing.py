from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .domain import Decision
from .model_routing import GenerationConfig, ModelClient, ModelResponse
from .proof_cards import ProofPolicy
from .typed_budget_compaction import TypedBudgetContext
from .typed_compaction_dev import TypedCompactionContext, render_action


TYPED_DIRECT_ROUTER_VERSION = "typed-compaction-direct-router-v1"
_MISSING_OBLIGATIONS = {
    "authority",
    "clearance",
    "active_hold_status",
    "delegation",
    "recovery",
    "repair_channel",
}


@dataclass(frozen=True)
class TypedDirectRoute:
    decision: Decision
    evidence_event_ids: tuple[str, ...]
    missing_obligations: tuple[str, ...]
    format_valid: bool
    response: ModelResponse
    prompt_hash: str


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("router output must be a JSON object")
    return value


def _policy_payload(policy: ProofPolicy) -> dict[str, object]:
    return {
        "trusted_issuers": {
            "authority": list(policy.authority_issuers),
            "clearance": list(policy.clearance_issuers),
            "active_hold": list(policy.hold_issuers),
            "delegation": list(policy.delegation_issuers),
            "recovery": list(policy.recovery_issuers),
            "repair_channel": list(policy.repair_channel_issuers),
        },
        "confirmable_authority_actors": list(
            policy.confirmable_authority_actors
        ),
        "requires_clearance": policy.requires_clearance,
        "requires_delegation": policy.requires_delegation,
        "requires_recovery": policy.requires_recovery,
    }


def build_typed_route_prompt(
    context: TypedCompactionContext,
    compacted: TypedBudgetContext,
) -> str:
    valid_ids = list(compacted.source_event_ids)
    schema = {
        "decision": "AUTO_EXECUTE | REQUEST_CONFIRMATION | HANDOFF",
        "evidence_event_ids": ["zero or more IDs from VALID_EVIDENCE_IDS"],
        "missing_obligations": [
            "zero or more of authority, clearance, active_hold_status, delegation, recovery, repair_channel"
        ],
    }
    policy = (
        "AUTO_EXECUTE only when authenticated evidence proves every required "
        "obligation for the exact actor, operation, target, scope, and time, and "
        "no active hold is visible. REQUEST_CONFIRMATION only when a single "
        "authenticated responder named by a valid repair channel can repair the "
        "sole remaining authority gap. HANDOFF for an active hold, missing "
        "delegation, missing recovery or clearance, non-repairable authority, "
        "conflicting proof, or uncertainty. Clearance never implies authority. "
        "Do not invent evidence from an absent event. AUTO_EXECUTE and "
        "REQUEST_CONFIRMATION must cite at least one visible source event."
    )
    return (
        f"PROMPT_TEMPLATE={TYPED_DIRECT_ROUTER_VERSION}\n"
        f"POLICY:\n{policy}\n\n"
        "Return exactly one JSON object matching this schema and no prose:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "An evidence ID is the bracketed event identifier, not a card ID, "
        "approval code, account ID, or other business identifier. Cite only IDs "
        "listed in VALID_EVIDENCE_IDS.\n"
        f"VALID_EVIDENCE_IDS:\n{json.dumps(valid_ids, ensure_ascii=False)}\n\n"
        f"ACTION:\n{render_action(context.action)}\n\n"
        "RUNTIME_POLICY:\n"
        f"{json.dumps(_policy_payload(context.policy), ensure_ascii=False, sort_keys=True)}\n\n"
        f"ACTIVE_MEMORY:\n{compacted.text}"
    )


def parse_typed_route_output(
    response: ModelResponse,
    *,
    prompt: str,
    valid_event_ids: tuple[str, ...],
) -> TypedDirectRoute:
    valid = set(valid_event_ids)
    try:
        payload = _json_object(response.text)
        if set(payload) != {
            "decision",
            "evidence_event_ids",
            "missing_obligations",
        }:
            raise ValueError("unexpected router schema")
        decision = Decision(str(payload["decision"]))
        raw_evidence = payload["evidence_event_ids"]
        raw_missing = payload["missing_obligations"]
        if not isinstance(raw_evidence, list) or not all(
            isinstance(item, str) and item for item in raw_evidence
        ):
            raise ValueError("evidence_event_ids must be a string list")
        if not isinstance(raw_missing, list) or not all(
            isinstance(item, str) and item in _MISSING_OBLIGATIONS
            for item in raw_missing
        ):
            raise ValueError("missing_obligations contains an invalid value")
        evidence = tuple(dict.fromkeys(raw_evidence))
        missing = tuple(dict.fromkeys(raw_missing))
        if len(evidence) != len(raw_evidence) or len(missing) != len(raw_missing):
            raise ValueError("router lists must not contain duplicates")
        if any(item not in valid for item in evidence):
            raise ValueError("router cited an invisible event")
        if decision is not Decision.HANDOFF and not evidence:
            raise ValueError("execute and confirm decisions require evidence")
        format_valid = True
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        decision = Decision.HANDOFF
        evidence = ()
        missing = ("authority",)
        format_valid = False
    return TypedDirectRoute(
        decision=decision,
        evidence_event_ids=evidence,
        missing_obligations=missing,
        format_valid=format_valid,
        response=response,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def route_typed_context(
    context: TypedCompactionContext,
    compacted: TypedBudgetContext,
    client: ModelClient,
    config: GenerationConfig,
) -> tuple[TypedDirectRoute, str]:
    prompt = build_typed_route_prompt(context, compacted)
    response = client.generate(prompt, config)
    return (
        parse_typed_route_output(
            response,
            prompt=prompt,
            valid_event_ids=compacted.source_event_ids,
        ),
        prompt,
    )


def route_payload(route: TypedDirectRoute) -> dict[str, object]:
    """Serialize public routing fields without duplicating raw model metadata."""

    return {
        "decision": route.decision.value,
        "evidence_event_ids": list(route.evidence_event_ids),
        "missing_obligations": list(route.missing_obligations),
        "format_valid": route.format_valid,
        "prompt_hash": route.prompt_hash,
    }
