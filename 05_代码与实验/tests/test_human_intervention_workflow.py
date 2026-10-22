import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.durable_proof_store import DurableProofRecord, DurableProofStore
from platform_agent_eval.human_intervention_workflow import (
    ActionBinding,
    InterventionWorkflow,
    ProtocolChecks,
    RequestState,
    ResponderDirectory,
    ResponseDecision,
    SimulatedActionLedger,
    TimelineEvidenceProvider,
    TrustedChannel,
    response_for,
)
from platform_agent_eval.proof_cards import ActionRequest, ProofCard, ProofCardKind, ProofPolicy


# Development family: the vendor-payment example from the contribution brief.
T0 = "2026-11-20T09:00:00+08:00"
DAY = ("2026-11-20T00:00:00+08:00", "2026-11-20T23:59:59+08:00")
ACTION = ActionRequest(
    actor_id="payments-agent-3", operation="SCHEDULE_VENDOR_PAYMENT",
    target_id="invoice-kowloon-5820",
    scope=(("amount_hkd", "58200"), ("payee", "harbour-supplies")),
    effective_at=T0,
)
POLICY = ProofPolicy(
    authority_issuers=("treasury-registry", "confirmation-ledger"),
    clearance_issuers=("risk-control",),
    hold_issuers=("risk-control",),
    delegation_issuers=("orchestration-registry",),
    recovery_issuers=("ledger-service",),
    repair_channel_issuers=("identity-service",),
    confirmable_authority_actors=("treasury-officer-ivy",),
)
DIRECTORY = ResponderDirectory((
    TrustedChannel("chan-ivy", "treasury-officer-ivy"),
    TrustedChannel("chan-bob", "clerk-bob"),
))


def card(card_id, kind, issuer, subject, *, action=ACTION, window=DAY, transferable=False):
    return ProofCard(card_id, kind, (f"ev-{card_id}",), issuer, subject, action.operation,
                     action.target_id, action.scope, window[0], window[1],
                     transferable=transferable)


CLEARANCE = card("c-clr", ProofCardKind.CLEARANCE, "risk-control", ACTION.target_id)
RECOVERY = card("c-rec", ProofCardKind.RECOVERY, "ledger-service", ACTION.target_id)
REPAIR = card("c-rep", ProofCardKind.REPAIR_CHANNEL, "identity-service", "treasury-officer-ivy")
HOLD = card("c-hold", ProofCardKind.ACTIVE_HOLD, "risk-control", ACTION.target_id)
AUTHORITY = card("c-auth", ProofCardKind.AUTHORITY, "treasury-registry", ACTION.actor_id)


def record(record_id, item, committed="2026-11-20T08:00:00+08:00", revoked=None):
    return DurableProofRecord(record_id, item, committed, revoked)


BASE = (record("r-clr", CLEARANCE), record("r-rec", RECOVERY), record("r-rep", REPAIR))


def at(minutes):
    from datetime import datetime
    return (datetime.fromisoformat(T0) + timedelta(minutes=minutes)).isoformat()


def make(records=BASE, policy_versions=((T0, POLICY),), outages=(), checks=ProtocolChecks(),
         pre_commit_check=None, extra_transitions=()):
    provider = TimelineEvidenceProvider(policy_versions, (), DurableProofStore("treasury", "s1", records),
                                        outages)
    transitions = {ActionBinding.of(ACTION).sha256: {"invoice_status": "scheduled",
                                                     "amount_hkd": 58200}}
    transitions.update(dict(extra_transitions))
    ledger = SimulatedActionLedger({"invoice_status": "open"}, transitions,
                                   deduplicate=checks.deduplicate)
    workflow = InterventionWorkflow(provider, DIRECTORY, ledger, start_time=T0,
                                    confirmation_issuer="confirmation-ledger", checks=checks,
                                    pre_commit_check=pre_commit_check)
    return workflow, ledger


def start(workflow, action=ACTION, **kwargs):
    outcome = workflow.request_confirmation(action, **kwargs)
    return outcome, outcome.request


class RequestCreationTest(unittest.TestCase):
    def test_request_is_specific_bound_and_addressed_to_the_repair_responder(self):
        workflow, _ = make()
        outcome, request = start(workflow)
        self.assertIs(outcome.decision, Decision.REQUEST_CONFIRMATION)
        self.assertEqual(request.responder_id, "treasury-officer-ivy")
        self.assertEqual(request.delivery_channel_id, "chan-ivy")
        self.assertEqual(request.missing_obligation, "authority")
        self.assertEqual(request.repair_card_ids, ("c-rep",))
        self.assertEqual(request.action_sha256, ActionBinding.of(ACTION).sha256)
        self.assertEqual(request.expires_at, at(30))
        self.assertIn("SCHEDULE_VENDOR_PAYMENT", request.message)
        self.assertIn("amount_hkd=58200", request.message)

    def test_request_to_a_person_without_authority_is_refused(self):
        workflow, _ = make()
        outcome, request = start(workflow, responder_id="clerk-bob")
        self.assertIsNone(request)
        self.assertEqual(outcome.reason, "ADDRESSEE_NOT_AUTHORIZED_FOR_GAP")

    def test_handoff_is_never_converted_into_confirmation(self):
        workflow, _ = make(records=(record("r-rec", RECOVERY), record("r-rep", REPAIR)))
        outcome, request = start(workflow)
        self.assertIs(outcome.decision, Decision.HANDOFF)
        self.assertIsNone(request)

    def test_execute_route_needs_no_request(self):
        workflow, _ = make(records=BASE + (record("r-auth", AUTHORITY),))
        outcome, request = start(workflow)
        self.assertIs(outcome.decision, Decision.AUTO_EXECUTE)
        self.assertIsNone(request)

    def test_policy_must_trust_the_confirmation_issuer(self):
        untrusting = replace(POLICY, authority_issuers=("treasury-registry",))
        workflow, _ = make(policy_versions=((T0, untrusting),))
        outcome, request = start(workflow)
        self.assertIsNone(request)
        self.assertEqual(outcome.reason, "CONFIRMATION_ISSUER_NOT_TRUSTED_BY_POLICY")


class ResponseValidationTest(unittest.TestCase):
    def setUp(self):
        self.workflow, self.ledger = make()
        _, self.request = start(self.workflow)

    def respond(self, response_id="resp-1", channel="chan-ivy",
                decision=ResponseDecision.APPROVE, **overrides):
        return self.workflow.receive(response_for(self.request, response_id, channel, decision,
                                                  **overrides))

    def test_valid_timely_confirmation_executes_once_after_revalidation(self):
        self.workflow.advance_to(at(5))
        self.assertTrue(self.respond().accepted)
        outcome = self.workflow.execute(self.request.request_id, ACTION)
        self.assertTrue(outcome.executed)
        self.assertIs(outcome.validation.decision, Decision.AUTO_EXECUTE)
        self.assertIn(f"hic-{self.request.request_id}-resp-1", outcome.receipt.decisive_card_ids)
        self.assertIn("c-clr", outcome.receipt.decisive_card_ids)
        self.assertEqual(self.ledger.state["invoice_status"], "scheduled")

    def test_wrong_person_is_rejected(self):
        outcome = self.respond(channel="chan-bob")
        self.assertEqual(outcome.reason, "RESPONDER_NOT_ADDRESSED")
        self.assertIs(self.workflow.state_of(self.request.request_id), RequestState.PENDING_CONFIRMATION)

    def test_claimed_identity_is_not_authentication(self):
        outcome = self.respond(channel="chan-unknown", claimed_responder_id="treasury-officer-ivy",
                               claimed_verified=True)
        self.assertEqual(outcome.reason, "UNAUTHENTICATED_CHANNEL")
        outcome = self.respond("resp-2", channel="chan-bob",
                               claimed_responder_id="treasury-officer-ivy", claimed_verified=True)
        self.assertEqual(outcome.reason, "CLAIMED_IDENTITY_DIFFERS_FROM_CHANNEL")

    def test_different_amount_or_target_is_rejected(self):
        scope = (("amount_hkd", "5820"), ("payee", "harbour-supplies"))
        self.assertEqual(self.respond(scope=scope).reason, "SCOPE_MISMATCH")
        self.assertEqual(self.respond("resp-2", target_id="invoice-kowloon-5821").reason,
                         "TARGET_MISMATCH")
        self.assertEqual(self.respond("resp-3", action_sha256="0" * 64).reason,
                         "ACTION_HASH_MISMATCH")

    def test_request_expiry_cannot_be_bypassed_by_backdating(self):
        self.workflow.advance_to(at(31))
        self.assertIs(self.workflow.state_of(self.request.request_id), RequestState.EXPIRED)
        outcome = self.respond(claimed_sent_at=at(10))
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.reason, "REQUEST_NOT_OPEN_EXPIRED")
        self.assertFalse(self.workflow.execute(self.request.request_id, ACTION).executed)

    def test_clock_cannot_move_backwards(self):
        self.workflow.advance_to(at(10))
        with self.assertRaises(ValueError):
            self.workflow.advance_to(at(5))

    def test_approval_that_goes_stale_before_execution_is_not_used(self):
        self.respond()
        self.workflow.advance_to(at(16))
        self.assertIs(self.workflow.state_of(self.request.request_id), RequestState.EXPIRED)
        self.assertFalse(self.workflow.execute(self.request.request_id, ACTION).executed)
        self.assertEqual(self.ledger.applied, [])

    def test_explicit_rejection_stops_and_a_later_approval_cannot_reopen(self):
        self.assertTrue(self.respond(decision=ResponseDecision.REJECT).accepted)
        self.assertEqual(self.respond("resp-2").reason, "REQUEST_NOT_OPEN_REJECTED")
        self.assertFalse(self.workflow.execute(self.request.request_id, ACTION).executed)

    def test_rejection_after_approval_escalates(self):
        self.respond()
        outcome = self.respond("resp-2", decision=ResponseDecision.REJECT)
        self.assertEqual(outcome.reason, "CONFLICTING_RESPONSES")
        self.assertIs(self.workflow.state_of(self.request.request_id), RequestState.ESCALATED)
        self.assertFalse(self.workflow.execute(self.request.request_id, ACTION).executed)

    def test_duplicate_response_and_repeated_execution_mutate_once(self):
        self.assertTrue(self.respond().accepted)
        self.assertTrue(self.workflow.execute(self.request.request_id, ACTION).executed)
        self.assertEqual(self.respond().reason, "DUPLICATE_RESPONSE")
        second = self.workflow.execute(self.request.request_id, ACTION)
        self.assertFalse(second.executed)
        self.assertEqual(second.reason, "ALREADY_EXECUTED")
        self.assertEqual(self.ledger.mutations(self.request.action_sha256), 1)

    def test_second_approval_message_is_not_a_second_authorization(self):
        self.respond()
        self.assertEqual(self.respond("resp-2").reason, "ALREADY_CONFIRMED")

    def test_cancelled_request_rejects_later_response(self):
        self.workflow.cancel(self.request.request_id)
        self.assertEqual(self.respond().reason, "REQUEST_NOT_OPEN_CANCELLED")

    def test_clarification_is_not_approval(self):
        self.assertEqual(self.respond(decision=ResponseDecision.CLARIFY).reason,
                         "CLARIFICATION_REQUESTED")
        self.assertFalse(self.workflow.execute(self.request.request_id, ACTION).executed)
        self.assertTrue(self.respond("resp-2").accepted)
        self.assertTrue(self.workflow.execute(self.request.request_id, ACTION).executed)

    def test_changed_parameters_after_approval_need_reauthorization(self):
        self.respond()
        changed = replace(ACTION, scope=(("amount_hkd", "85200"), ("payee", "harbour-supplies")))
        outcome = self.workflow.execute(self.request.request_id, changed)
        self.assertEqual(outcome.reason, "ACTION_CHANGED_REAUTHORIZATION_REQUIRED")
        self.assertEqual(self.ledger.applied, [])
        self.assertIs(self.workflow.state_of(self.request.request_id), RequestState.CONFIRMED)

    def test_old_approval_replayed_for_a_new_request_is_rejected(self):
        second_action = replace(ACTION, target_id="invoice-kowloon-5821")
        second_cards = tuple(
            record(f"r2-{item.card_id}", card(
                f"{item.card_id}-2", item.kind, item.issuer_id,
                second_action.target_id if item.kind is not ProofCardKind.REPAIR_CHANNEL
                else item.subject_id, action=second_action))
            for item in (CLEARANCE, RECOVERY, REPAIR)
        )
        workflow, ledger = make(
            records=BASE + second_cards,
            extra_transitions=((ActionBinding.of(second_action).sha256, {"second": "paid"}),),
        )
        _, first = start(workflow)
        old = response_for(first, "resp-1", "chan-ivy")
        workflow.receive(old)
        self.assertTrue(workflow.execute(first.request_id, ACTION).executed)
        _, second = start(workflow, second_action)
        replay = replace(old, request_id=second.request_id, response_id="resp-replay")
        self.assertEqual(workflow.receive(replay).reason, "CHALLENGE_MISMATCH_POSSIBLE_REPLAY")
        self.assertEqual(workflow.receive(replace(old, response_id="resp-again")).reason,
                         "REQUEST_NOT_OPEN_COMPLETED")
        self.assertFalse(workflow.execute(second.request_id, second_action).executed)
        self.assertEqual(len(ledger.applied), 1)


class RevalidationTest(unittest.TestCase):
    def run_case(self, records=BASE, policy_versions=((T0, POLICY),), outages=(),
                 respond_at=5, execute_at=6, pre_commit_check=None):
        workflow, ledger = make(records, policy_versions, outages,
                                pre_commit_check=pre_commit_check)
        _, request = start(workflow)
        workflow.advance_to(at(respond_at))
        response = workflow.receive(response_for(request, "resp-1", "chan-ivy"))
        workflow.advance_to(at(execute_at))
        execution = workflow.execute(request.request_id, ACTION)
        return workflow, ledger, request, response, execution

    def test_hold_appearing_while_waiting_blocks(self):
        hold = record("r-hold", HOLD, committed=at(3))
        *_, execution = self.run_case(BASE + (hold,))
        self.assertFalse(execution.executed)
        self.assertIn("HOLD_BLOCKED", execution.reason)

    def test_responder_authority_revoked_while_waiting_escalates(self):
        records = (BASE[0], BASE[1], record("r-rep", REPAIR, revoked=at(2)))
        workflow, _, request, response, execution = self.run_case(records)
        self.assertEqual(response.reason, "RESPONDER_AUTHORITY_LAPSED")
        self.assertIs(workflow.state_of(request.request_id), RequestState.ESCALATED)
        self.assertFalse(execution.executed)

    def test_confirmation_does_not_satisfy_other_obligations(self):
        records = (record("r-clr", CLEARANCE, revoked=at(5)), BASE[1], BASE[2])
        *_, execution = self.run_case(records, respond_at=4, execute_at=6)
        self.assertFalse(execution.executed)
        self.assertIn("CLEARANCE_MISSING", execution.reason)

    def test_relevant_policy_change_is_revalidated(self):
        stricter = replace(POLICY, requires_delegation=True)
        *_, execution = self.run_case(policy_versions=((T0, POLICY), (at(5), stricter)))
        self.assertFalse(execution.executed)
        self.assertIn("DELEGATION_MISSING", execution.reason)
        untrusting = replace(POLICY, authority_issuers=("treasury-registry",))
        *_, execution = self.run_case(policy_versions=((T0, POLICY), (at(5), untrusting)))
        self.assertEqual(execution.reason, "CONFIRMATION_DID_NOT_RESOLVE_GAP")

    def test_harmless_policy_change_does_not_cause_handoff(self):
        wider = replace(POLICY, recovery_issuers=("ledger-service", "backup-ledger"))
        *_, execution = self.run_case(policy_versions=((T0, POLICY), (at(5), wider)))
        self.assertTrue(execution.executed)

    def test_unavailable_evidence_fails_closed(self):
        workflow, ledger, request, _, execution = self.run_case(outages=((at(6), at(10)),))
        self.assertFalse(execution.executed)
        self.assertEqual(execution.reason, "EVIDENCE_SOURCE_UNAVAILABLE")
        self.assertIs(workflow.state_of(request.request_id), RequestState.ESCALATED)

    def test_optional_pre_commit_check_can_block(self):
        *_, execution = self.run_case(pre_commit_check=lambda action, result: "STALE_SNAPSHOT")
        self.assertEqual(execution.reason, "PRE_COMMIT_CHECK_STALE_SNAPSHOT")
        self.assertFalse(execution.executed)

    def test_audit_records_every_step_in_order(self):
        workflow, *_ = self.run_case()
        events = [(e.event, e.outcome) for e in workflow.audit]
        self.assertEqual(events, [("START", "PENDING_CONFIRMATION"), ("RESPONSE", "ACCEPTED"),
                                  ("STATE", "COMPLETED")])
        self.assertEqual([e.seq for e in workflow.audit], [1, 2, 3])


class AblationSwitchTest(unittest.TestCase):
    def test_switches_reopen_the_failures_they_guard(self):
        workflow, _ = make(checks=ProtocolChecks(authenticate_channel=False))
        _, request = start(workflow)
        forged = response_for(request, "r", "chan-unknown", claimed_responder_id="treasury-officer-ivy")
        self.assertTrue(workflow.receive(forged).accepted)

        workflow, ledger = make(checks=ProtocolChecks(deduplicate=False))
        _, request = start(workflow)
        workflow.receive(response_for(request, "r", "chan-ivy"))
        workflow.execute(request.request_id, ACTION)
        workflow.execute(request.request_id, ACTION)
        self.assertEqual(ledger.mutations(request.action_sha256), 2)


_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "intervention_runner",
    Path(__file__).resolve().parents[1] / "scripts/run_human_intervention_evaluation.py",
)
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner)
CONFIG = Path(__file__).resolve().parents[1] / "configs/human_intervention_eval.json"


class EvaluationHarnessTest(unittest.TestCase):
    def test_plan_is_model_free_and_pins_frozen_sources(self):
        config = runner.load_config(CONFIG)
        plan = runner.build_plan(config)
        self.assertEqual(plan["measured_generation_calls"], 0)
        self.assertEqual(plan["scenarios"], 75)
        tampered = json.loads(json.dumps(config))
        name = next(iter(tampered["frozen_sources_sha256"]))
        tampered["frozen_sources_sha256"][name] = "0" * 64
        with self.assertRaises(ValueError):
            runner.build_plan(tampered)

    def test_run_writes_bundle_once_and_refuses_overwrite(self):
        config = runner.load_config(CONFIG)
        config["output_prefix"] = "intervention_test_v1"
        with tempfile.TemporaryDirectory() as directory:
            outcome = runner.run(config, allow_dirty_worktree=True, results_dir=Path(directory))
            self.assertEqual(outcome["audit_status"], "PASS")
            with self.assertRaises(FileExistsError):
                runner.run(config, allow_dirty_worktree=True, results_dir=Path(directory))

    def test_scenario_labels_never_reach_the_workflow(self):
        import inspect
        from platform_agent_eval import human_intervention_workflow as workflow_module
        source = inspect.getsource(workflow_module)
        for label in ("expected_executions", "expected_final_states", "expected_accept",
                      "expects_completion", "human_intervention_scenarios"):
            self.assertNotIn(label, source)


if __name__ == "__main__":
    unittest.main()
