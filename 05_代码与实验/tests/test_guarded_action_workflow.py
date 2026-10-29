import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from guarded_hotel_workflow import (  # noqa: E402
    ACTION, POLICY, REPLY_AT, START, build_workflow, publish_hold, run_scenario,
)
from platform_agent_eval.domain import Decision  # noqa: E402
from platform_agent_eval.guarded_action_workflow import (  # noqa: E402
    CommitBoundExecutor, GroundedEvidenceProvider, GroundingInput,
)
from platform_agent_eval.human_intervention_workflow import (  # noqa: E402
    EvidenceUnavailable, InterventionWorkflow, ProtocolChecks, RequestState,
    SimulatedActionLedger, response_for,
)
from platform_agent_eval.natural_language_evidence import parse_extraction_output  # noqa: E402


def approve(fixture, response_id="reply-1", action=ACTION):
    start = fixture.workflow.request_confirmation(action)
    request = start.request
    assert request is not None
    fixture.workflow.advance_to(REPLY_AT)
    outcome = fixture.workflow.receive(response_for(request, response_id, "channel-lee"))
    assert outcome.accepted
    return request


class GuardedHotelIntegrationTest(unittest.TestCase):
    def test_commit_cleanup_error_reconciles_the_applied_mutation_without_replaying(self):
        fixture = build_workflow()
        request = approve(fixture)
        original_commit = fixture.gate.commit
        existing = fixture.registry.snapshot(ACTION.operation, ACTION.target_id)[0].records[0]

        def deferred_writes():
            fixture.registry.publish(existing)  # duplicate fails during section cleanup
            publish_hold(fixture.registry)       # a later valid write must still survive

        def commit_with_cleanup_error(*args, **kwargs):
            return original_commit(*args, **kwargs, interleave=deferred_writes)

        with patch.object(fixture.gate, "commit", side_effect=commit_with_cleanup_error):
            outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertTrue(outcome.executed)
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.COMPLETED)
        self.assertEqual(len(fixture.gate.executions()), 1)
        self.assertEqual(fixture.gate.state(ACTION.target_id)["charged_hkd"], 1800)
        self.assertIsNotNone(outcome.receipt)
        self.assertTrue(any(e.event == "EXECUTOR" and e.outcome == "WARNING"
                            for e in fixture.workflow.audit))
        # The receipt must use the successful commit's proof, not the later hold.
        self.assertIs(fixture.executor.last_result.decision, Decision.AUTO_EXECUTE)
        self.assertNotIn("new-hold", outcome.receipt.decisive_card_ids)
        self.assertIn("hold-record", {r.record_id for r in fixture.registry.snapshot(
            ACTION.operation, ACTION.target_id)[0].records})
        self.assertFalse(fixture.workflow.execute(request.request_id, ACTION).executed)
        self.assertEqual(len(fixture.gate.executions()), 1)

    def test_unreconciled_error_closes_request_as_unknown_and_disables_resume(self):
        def fail_before_commit(registry):
            raise RuntimeError("fixture transport failed before a result was returned")

        fixture = build_workflow(before_commit=fail_before_commit)
        request = approve(fixture)
        with self.assertRaises(RuntimeError) as failure:
            fixture.workflow.execute(request.request_id, ACTION)
        self.assertEqual(type(failure.exception).__name__, "MutationOutcomeUnknown")
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.ESCALATED)
        self.assertIn("UNKNOWN", fixture.workflow.record_summary(request.request_id)["reason"])
        self.assertIsNone(fixture.workflow.record_summary(request.request_id)["executed"])
        self.assertFalse(fixture.workflow.execute(request.request_id, ACTION).executed)
        self.assertEqual(fixture.gate.executions(), ())

    def test_missing_receipt_after_a_logged_mutation_is_unknown_and_cannot_replay(self):
        fixture = build_workflow()
        request = approve(fixture)
        original_apply = fixture.gate._apply

        def apply_then_fail(*args, **kwargs):
            original_apply(*args, **kwargs)
            raise RuntimeError("fixture acknowledgement failed before receipt storage")

        with patch.object(fixture.gate, "_apply", side_effect=apply_then_fail):
            with self.assertRaises(RuntimeError) as failure:
                fixture.workflow.execute(request.request_id, ACTION)
        self.assertEqual(type(failure.exception).__name__, "MutationOutcomeUnknown")
        self.assertIsNone(fixture.workflow.record_summary(request.request_id)["executed"])
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.ESCALATED)
        self.assertEqual(len(fixture.gate.executions()), 1)

        self.assertIsNone(fixture.executor.last_result)
        self.assertFalse(fixture.workflow.execute(request.request_id, ACTION).executed)
        self.assertEqual(len(fixture.gate.executions()), 1)

    def test_receipt_lookup_failure_never_turns_an_applied_operation_into_false(self):
        fixture = build_workflow()
        request = approve(fixture)
        original_commit = fixture.gate.commit

        def commit_then_error(*args, **kwargs):
            original_commit(*args, **kwargs)
            raise RuntimeError("fixture result transport failed")

        with patch.object(fixture.gate, "commit", side_effect=commit_then_error), \
             patch.object(fixture.gate, "committed_result", side_effect=RuntimeError("lookup unavailable")):
            with self.assertRaises(RuntimeError) as failure:
                fixture.workflow.execute(request.request_id, ACTION)
        self.assertEqual(type(failure.exception).__name__, "MutationOutcomeUnknown")
        self.assertIsNone(fixture.workflow.record_summary(request.request_id)["executed"])
        self.assertIn("receipt lookup", fixture.executor.last_error)
        self.assertEqual(len(fixture.gate.executions()), 1)
        self.assertIsNone(fixture.executor.last_result)
        self.assertFalse(fixture.workflow.execute(request.request_id, ACTION).executed)
        self.assertEqual(len(fixture.gate.executions()), 1)

    def test_existing_registry_approval_executes_without_an_unnecessary_question(self):
        row = run_scenario("already_authorized")
        self.assertEqual(row["initial_decision"], "AUTO_EXECUTE")
        self.assertIsNone(row["confirmation_request"])
        self.assertIsNone(row["response"])
        self.assertEqual(row["mutation_count"], 1)
        self.assertEqual(row["state_after"]["hotel"], "riverside")

    def test_initial_handoff_creates_no_confirmation_or_mutation(self):
        row = run_scenario("initial_handoff")
        self.assertEqual(row["initial_decision"], "HANDOFF")
        self.assertIn("UNACCOUNTED_RESTRICTIVE_EVIDENCE", row["initial_reason"])
        self.assertIsNone(row["confirmation_request"])
        self.assertEqual(row["executions"], [])
        self.assertEqual(row["state_before"], row["state_after"])
        self.assertEqual(row["mutation_count"], 0)

    def test_grounding_confirmation_and_actual_commit_form_one_proof_chain(self):
        fixture = build_workflow()
        request = approve(fixture)
        grounded = fixture.provider.last_result
        self.assertIs(grounded.baseline_decision, Decision.AUTO_EXECUTE)
        self.assertIs(grounded.decision, Decision.REQUEST_CONFIRMATION)
        self.assertIn("x-memory-note-authority", grounded.excluded_card_ids)
        outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertTrue(outcome.executed)
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.COMPLETED)
        self.assertEqual(len(fixture.gate.executions()), 1)
        self.assertEqual(fixture.gate.state(ACTION.target_id),
                         {"hotel": "riverside", "charged_hkd": 1800, "mutation_count": 1})
        self.assertIn("hic-" + request.request_id + "-reply-1", outcome.receipt.decisive_card_ids)
        self.assertNotIn("x-memory-note-authority", outcome.receipt.decisive_card_ids)
        self.assertEqual(outcome.receipt.decisive_card_ids,
                         fixture.executor.last_result.commit_check.result.decisive_card_ids)
        self.assertIn(("hotel", "'harbour-view'", "'riverside'"), outcome.receipt.state_diff)

    def test_hold_between_prepare_and_commit_vetoes_an_already_approved_action(self):
        fixture = build_workflow(before_commit=publish_hold)
        request = approve(fixture)
        before = fixture.gate.state(ACTION.target_id)
        outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertFalse(outcome.executed)
        # The earlier workflow validation passed: the commit re-read is load-bearing.
        self.assertIs(outcome.validation.decision, Decision.AUTO_EXECUTE)
        result = fixture.executor.last_result
        self.assertIs(result.prepared_decision, Decision.AUTO_EXECUTE)
        self.assertIs(result.decision, Decision.HANDOFF)
        self.assertGreater(result.commit_check.relevant_version, result.prepared_relevant_version)
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.ESCALATED)
        self.assertEqual(fixture.gate.state(ACTION.target_id), before)
        self.assertEqual(fixture.gate.executions(), ())
        self.assertIsNone(outcome.receipt)

    def test_untyped_omitted_hold_cannot_be_lost_when_passing_cards_to_workflow(self):
        fixture = build_workflow()
        fixture.events["unextracted-message"] = "booking-river-24 is on hold. Do not proceed."
        start = fixture.workflow.request_confirmation(ACTION)
        result = fixture.provider.last_result
        self.assertTrue(result.unaccounted_signals)
        # Cards alone would permit asking Lee. The grounding veto must survive composition.
        self.assertIs(result.validation.decision, Decision.REQUEST_CONFIRMATION)
        self.assertIs(start.decision, Decision.HANDOFF)
        self.assertIsNone(start.request)
        self.assertEqual(fixture.gate.executions(), ())

    def test_new_visible_restriction_after_reply_stops_before_dispatch(self):
        fixture = build_workflow()
        request = approve(fixture)
        fixture.events["new-message"] = "booking-river-24 is on hold. Do not proceed."
        outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertFalse(outcome.executed)
        self.assertIs(fixture.workflow.state_of(request.request_id), RequestState.ESCALATED)
        self.assertIsNone(fixture.executor.last_result)
        self.assertEqual(fixture.gate.executions(), ())

    def test_retries_and_a_new_confirmation_do_not_reset_the_operation_binding(self):
        fixture = build_workflow()
        first = approve(fixture)
        self.assertTrue(fixture.workflow.execute(first.request_id, ACTION).executed)
        self.assertFalse(fixture.workflow.execute(first.request_id, ACTION).executed)
        later_action = replace(ACTION, effective_at="2026-11-02T10:06:00+08:00")
        second = fixture.workflow.request_confirmation(later_action).request
        fixture.workflow.advance_to(later_action.effective_at)
        self.assertTrue(fixture.workflow.receive(response_for(
            second, "reply-2", "channel-lee")).accepted)
        self.assertFalse(fixture.workflow.execute(second.request_id, later_action).executed)
        self.assertEqual(len(fixture.gate.executions()), 1)
        self.assertEqual(fixture.gate.state(ACTION.target_id)["mutation_count"], 1)

    def test_changed_arguments_wrong_person_and_expiry_never_reach_mutation(self):
        for name in ("changed_arguments", "wrong_person", "expired_approval"):
            with self.subTest(scenario=name):
                row = run_scenario(name)
                self.assertEqual(row["state_before"], row["state_after"])
                self.assertEqual(row["mutation_count"], 0)
                self.assertIsNone(row["commit"])

    def test_registry_outage_at_commit_fails_closed(self):
        fixture = build_workflow(before_commit=lambda registry: registry.set_available(False))
        request = approve(fixture)
        outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertFalse(outcome.executed)
        self.assertIs(fixture.executor.last_result.decision, Decision.HANDOFF)
        self.assertEqual(fixture.gate.executions(), ())

    def test_recovery_revoked_between_checks_cannot_be_replaced_by_human_approval(self):
        fixture = build_workflow(before_commit=lambda registry: registry.revoke(
            "record-recovery", REPLY_AT))
        request = approve(fixture)
        outcome = fixture.workflow.execute(request.request_id, ACTION)
        self.assertFalse(outcome.executed)
        self.assertEqual(fixture.gate.executions(), ())
        self.assertIn("MEMORY_CARD_REVOKED_IN_REGISTRY:recovery",
                      fixture.executor.last_result.reason_codes)


class AdapterBoundaryTest(unittest.TestCase):
    def test_grounding_format_failure_does_not_turn_into_repairable_missing_authority(self):
        provider = GroundedEvidenceProvider(lambda action: GroundingInput(
            POLICY, parse_extraction_output("broken JSON", {}), {}))
        with self.assertRaises(EvidenceUnavailable):
            provider(ACTION)
        self.assertEqual(provider.last_result.failure_layer, "EXTRACTION_FORMAT")

    def test_grounding_handoff_without_a_hold_card_is_preserved(self):
        # Complete-path veto coverage lives in the integration tests above.
        fixture = build_workflow()
        fixture.events["hold"] = "booking-river-24 is frozen."
        with self.assertRaises(EvidenceUnavailable):
            fixture.provider(ACTION)
        self.assertIs(fixture.provider.last_result.decision, Decision.HANDOFF)

    def test_executor_rejects_a_different_declared_action(self):
        fixture = build_workflow()
        result = fixture.executor(replace(ACTION, actor_id="different-agent"), POLICY, (), START)
        self.assertFalse(result.executed)
        self.assertEqual(fixture.gate.executions(), ())

    def test_transition_configuration_is_detached_from_caller_mutation(self):
        fixture = build_workflow()
        transition = {"hotel": "riverside", "details": {"charged_hkd": 1800}}
        executor = CommitBoundExecutor(fixture.gate, ACTION, transition)
        transition["details"]["charged_hkd"] = 999999
        # Use the fixture's public provider and directory values, with no legacy ledger.
        from platform_agent_eval.human_intervention_workflow import ResponderDirectory, TrustedChannel
        fixture.workflow = InterventionWorkflow(
            fixture.provider, ResponderDirectory((TrustedChannel("channel-lee", "traveller-lee"),)),
            start_time=START, confirmation_issuer="confirmation-ledger", executor=executor)
        request = approve(fixture)
        self.assertTrue(fixture.workflow.execute(request.request_id, ACTION).executed)
        self.assertEqual(fixture.gate.state(ACTION.target_id)["details"], {"charged_hkd": 1800})

    def test_custom_dispatch_cannot_silently_bypass_checks_or_also_apply_legacy_ledger(self):
        from platform_agent_eval.human_intervention_workflow import ResponderDirectory
        fixture = build_workflow()
        common = dict(start_time=START, confirmation_issuer="confirmation-ledger")
        with self.assertRaises(ValueError):
            InterventionWorkflow(fixture.provider, ResponderDirectory(()), **common)
        with self.assertRaises(ValueError):
            InterventionWorkflow(fixture.provider, ResponderDirectory(()),
                                 SimulatedActionLedger({}, {}), executor=fixture.executor, **common)
        with self.assertRaises(ValueError):
            InterventionWorkflow(fixture.provider, ResponderDirectory(()), executor=fixture.executor,
                                 checks=ProtocolChecks(revalidate_evidence=False), **common)

    def test_example_emits_machine_readable_traces_without_external_services(self):
        command = [sys.executable, str(ROOT / "examples/guarded_hotel_workflow.py"), "--json"]
        rows = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        self.assertEqual(len(rows), 10)
        rows_by_name = {row["scenario"]: row for row in rows}
        self.assertEqual(rows_by_name["valid"]["mutation_count"], 1)
        self.assertEqual(rows_by_name["hold_before_commit"]["mutation_count"], 0)
        self.assertEqual(rows_by_name["duplicate_execution"]["mutation_count"], 1)
        self.assertTrue(rows_by_name["post_commit_error"]["executions"][0]["executed"])
        self.assertTrue(rows_by_name["post_commit_error"]["commit_error"])
        unknown = rows_by_name["opaque_ack_lost"]
        self.assertIsNone(unknown["executions"][0]["executed"])
        self.assertIsNone(unknown["workflow_summary"]["executed"])
        self.assertEqual(unknown["mutation_count"], 1)
        self.assertEqual(unknown["request_state"], "ESCALATED")


if __name__ == "__main__":
    unittest.main()
