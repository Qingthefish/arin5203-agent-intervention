"""Model-free, synthetic hotel rebooking through the three existing modules.

The extraction, authenticated records and response channels are declared fixtures.
No model, browser, booking service or payment API is contacted. This example
demonstrates composition; it is not a new benchmark or held-out result.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if "--installed-package" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from platform_agent_eval.commit_time_gate import (  # noqa: E402
    CommitTimeGate, RegistryUnavailableError, VersionedProofRegistry,
)
from platform_agent_eval.durable_proof_store import (  # noqa: E402
    DurableProofRecord, lookup_durable_cards,
)
from platform_agent_eval.guarded_action_workflow import (  # noqa: E402
    CommitBoundExecutor, GroundedEvidenceProvider, GroundingInput,
)
from platform_agent_eval.human_intervention_workflow import (  # noqa: E402
    EvidenceUnavailable, InterventionWorkflow, MutationOutcomeUnknown, ResponderDirectory,
    TrustedChannel, response_for,
)
from platform_agent_eval.natural_language_evidence import parse_extraction_output  # noqa: E402
from platform_agent_eval.proof_cards import (  # noqa: E402
    ActionRequest, ProofCard, ProofCardKind, ProofPolicy,
)

START = "2026-11-02T10:00:00+08:00"
REPLY_AT = "2026-11-02T10:05:00+08:00"
DAY_END = "2026-11-02T23:59:59+08:00"
ACTION = ActionRequest(
    "travel-agent", "REBOOK_HOTEL", "booking-river-24",
    (("charge_hkd", "1800"), ("hotel", "riverside")), START,
)
POLICY = ProofPolicy(
    authority_issuers=("traveller-approval", "confirmation-ledger"),
    clearance_issuers=("policy-desk",), hold_issuers=("policy-desk",),
    delegation_issuers=("travel-planner",), recovery_issuers=("booking-service",),
    repair_channel_issuers=("identity-service",),
    confirmable_authority_actors=("traveller-lee",),
)
SCENARIOS = ("already_authorized", "initial_handoff", "valid", "hold_before_commit",
             "wrong_person", "changed_arguments",
             "expired_approval", "duplicate_execution", "post_commit_error", "opaque_ack_lost")


class _PostCommitErrorRegistry(VersionedProofRegistry):
    """Fault fixture: the mutation completed, but section acknowledgement fails."""

    @contextmanager
    def commit_section(self):
        with super().commit_section():
            yield
        raise RuntimeError("fixture acknowledgement failed after commit-section cleanup")


def proof(card_id: str, kind: ProofCardKind, issuer: str, subject: str) -> ProofCard:
    return ProofCard(
        card_id, kind, ("source-" + card_id,), issuer, subject, ACTION.operation,
        ACTION.target_id, ACTION.scope, START, DAY_END,
    )


def publish_hold(registry: VersionedProofRegistry) -> None:
    registry.publish(DurableProofRecord(
        "hold-record", proof("new-hold", ProofCardKind.ACTIVE_HOLD,
                             "policy-desk", ACTION.target_id), REPLY_AT,
    ))


@dataclass
class HotelWorkflow:
    workflow: InterventionWorkflow
    provider: GroundedEvidenceProvider
    executor: CommitBoundExecutor
    registry: VersionedProofRegistry
    gate: CommitTimeGate
    events: dict[str, str]


def build_workflow(*, before_commit=None, fault=None) -> HotelWorkflow:
    if fault not in (None, "post_commit_error", "opaque_ack_lost"):
        raise ValueError("unknown fault fixture")
    cards = (
        proof("clearance", ProofCardKind.CLEARANCE, "policy-desk", ACTION.target_id),
        proof("recovery", ProofCardKind.RECOVERY, "booking-service", ACTION.target_id),
        proof("repair", ProofCardKind.REPAIR_CHANNEL, "identity-service", "traveller-lee"),
    )
    registry_type = _PostCommitErrorRegistry if fault == "post_commit_error" else VersionedProofRegistry
    registry = registry_type(
        "travel-registry", tuple(DurableProofRecord("record-" + c.card_id, c, START)
                                 for c in cards),
    )
    text = (
        "policy-desk (verified): policy check passed for REBOOK_HOTEL on "
        "booking-river-24, charge HKD 1800, hotel riverside. "
        f"Valid from {START} through {DAY_END}."
    )
    events = {"memory-note": text}
    # Deliberately wrong fixture: clearance is mislabeled as authority, with a
    # copied issuer and subject absent from the cited message. Quote presence
    # alone accepts it; field grounding must exclude it before asking Lee.
    extraction_json = json.dumps({"claims": [{
        "event_id": "memory-note", "kind": "AUTHORITY", "issuer": "traveller-approval",
        "subject": ACTION.actor_id, "operation": ACTION.operation, "target": ACTION.target_id,
        "scope": dict(ACTION.scope), "valid_from": START, "valid_until": DAY_END,
        "verified": True, "transferable": False, "source_quote": text,
    }]})

    def source(action: ActionRequest) -> GroundingInput:
        try:
            store, version, _ = registry.snapshot(action.operation, action.target_id)
        except RegistryUnavailableError as error:
            raise EvidenceUnavailable(str(error)) from error
        lookup = lookup_durable_cards(store, action)
        return GroundingInput(
            POLICY, parse_extraction_output(extraction_json, events), dict(events),
            lookup.cards, f"travel-registry@v{version}",
        )

    provider = GroundedEvidenceProvider(source)
    gate = CommitTimeGate("hotel-mutation", registry, {
        ACTION.target_id: {"hotel": "harbour-view", "charged_hkd": 0},
    })
    executor = CommitBoundExecutor(
        gate, ACTION, {"hotel": "riverside", "charged_hkd": 1800},
        before_commit=(lambda: before_commit(registry)) if before_commit else None,
    )
    mutation_executor = executor
    if fault == "opaque_ack_lost":
        def mutation_executor(*args):
            executor(*args)
            raise RuntimeError("fixture opaque executor lost its acknowledgement")

    workflow = InterventionWorkflow(
        provider, ResponderDirectory((TrustedChannel("channel-lee", "traveller-lee"),
                                      TrustedChannel("channel-colleague", "colleague"))),
        start_time=START, confirmation_issuer="confirmation-ledger", executor=mutation_executor,
    )
    return HotelWorkflow(workflow, provider, executor, registry, gate, events)


def run_scenario(scenario: str) -> dict[str, object]:
    if scenario not in SCENARIOS:
        raise ValueError("unknown hotel scenario")
    fixture = build_workflow(
        before_commit=publish_hold if scenario == "hold_before_commit" else None,
        fault=scenario if scenario in {"post_commit_error", "opaque_ack_lost"} else None)
    if scenario == "already_authorized":
        fixture.registry.publish(DurableProofRecord(
            "existing-approval", proof("existing-authority", ProofCardKind.AUTHORITY,
                                       "traveller-approval", ACTION.actor_id), START))
    elif scenario == "initial_handoff":
        fixture.events["unextracted-hold"] = "booking-river-24 is on hold. Do not proceed."
    workflow, gate = fixture.workflow, fixture.gate
    before = gate.state(ACTION.target_id)
    start = workflow.request_confirmation(ACTION)
    initial_grounding = fixture.provider.last_result
    assert initial_grounding is not None
    request = start.request
    response = None
    executions = []

    def execute_once(action):
        try:
            return asdict(workflow.execute(request.request_id, action))
        except MutationOutcomeUnknown as error:
            return {"executed": None, "reason": "EXECUTION_OUTCOME_UNKNOWN",
                    "state": workflow.state_of(request.request_id).value,
                    "error": str(error), "receipt": None}

    if request is None:
        if start.decision.value == "AUTO_EXECUTE":
            current = fixture.provider(ACTION)
            executions.append(asdict(fixture.executor(ACTION, current.policy, current.cards, START)))
    else:
        workflow.advance_to(REPLY_AT)
        response = workflow.receive(response_for(
            request, "reply-1", "channel-colleague" if scenario == "wrong_person" else "channel-lee",
        ))
        if scenario == "expired_approval":
            workflow.advance_to("2026-11-02T10:21:00+08:00")
        action = replace(ACTION, scope=(("charge_hkd", "2300"), ("hotel", "riverside"))) \
            if scenario == "changed_arguments" else ACTION
        executions.append(execute_once(action))
        if scenario == "duplicate_execution":
            executions.append(execute_once(action))
    commit = fixture.executor.last_result
    return {
        "scenario": scenario, "mode": "synthetic model-free composition example",
        "action": asdict(ACTION), "initial_decision": start.decision.value,
        "grounding": {
            "baseline_decision": initial_grounding.baseline_decision.value,
            "released_decision": initial_grounding.decision.value,
            "excluded_card_ids": initial_grounding.excluded_card_ids,
            "failure_layer": initial_grounding.failure_layer,
            "restrictive_signals": [asdict(signal) for signal in initial_grounding.restrictive_signals],
        },
        "confirmation_request": asdict(request) if request else None,
        "response": asdict(response) if response else None,
        "executions": executions,
        "request_state": workflow.state_of(request.request_id).value if request else None,
        "workflow_summary": workflow.record_summary(request.request_id) if request else None,
        "commit_error": fixture.executor.last_error,
        "initial_reason": start.reason,
        "state_before": before, "state_after": gate.state(ACTION.target_id),
        "mutation_count": len(gate.executions()),
        "commit": None if commit is None else {
            "prepared_decision": commit.prepared_decision.value,
            "released_decision": commit.decision.value, "executed": commit.executed,
            "reasons": commit.reason_codes,
            "proof_check": asdict(commit.commit_check.result)
            if commit.commit_check and commit.commit_check.result else None,
            "prepared_version": commit.prepared_relevant_version,
            "commit_version": commit.commit_check.relevant_version if commit.commit_check else None,
        },
        "audit": [asdict(entry) for entry in workflow.audit],
        "assumptions": ["scripted extraction", "trusted channel and registry fixtures",
                        "logical clock", "single-process simulated mutation",
                        "no extraction-quality or production-safety measurement"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument("--json", action="store_true", help="print complete traces as JSON")
    parser.add_argument("--installed-package", action="store_true",
                        help="use the installed course package without adding the checkout's src path")
    args = parser.parse_args()
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    rows = [run_scenario(scenario) for scenario in scenarios]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("Synthetic hotel workflow | no model or external booking/payment calls")
        for row in rows:
            reason = row["executions"][-1]["reason"] if row["executions"] else row["initial_reason"]
            state = row["request_state"] or "NO_REQUEST"
            print(f"{row['scenario']:22} {row['initial_decision']:22} {state:20} "
                  f"mutations={row['mutation_count']}  {reason}")
        print("Use --json for source decisions, confirmation binding, commit versions and state diffs.")


if __name__ == "__main__":
    main()
