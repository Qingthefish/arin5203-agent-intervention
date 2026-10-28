from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.commit_time_gate import (
    CHANGE_AT,
    COMMIT_AT,
    COMMIT_MODES,
    FAMILIES,
    PREPARE_AT,
    SCENARIO_CONDITIONS,
    CommitTimeGate,
    VersionedProofRegistry,
    declared_transition,
    evaluate_commit_gate,
    family_fixtures,
    run_scenario,
)
from platform_agent_eval.domain import Decision
from platform_agent_eval.durable_proof_store import (
    DurableProofRecord,
    DurableProofStore,
    augment_with_durable_cards,
    build_durable_proof_cases,
    lookup_durable_cards,
)
from platform_agent_eval.proof_cards import ProofCardInput, stable_hash, validate_proof_cards
from run_commit_time_gate import (
    _gate,
    assert_paths_available,
    build_plan,
    commit_gate_audit,
    load_config,
    output_paths,
)

CONFIG = ROOT / "configs" / "commit_time_gate.json"


def record(record_id: str, card, committed_at: str = "2026-10-19T17:00:00+08:00") -> DurableProofRecord:
    return DurableProofRecord(record_id=record_id, card=card, committed_at=committed_at)


class FinancialPaymentFixture(unittest.TestCase):
    """The df7 vendor-payment family from the durable-store gate, reused unchanged."""

    def setUp(self) -> None:
        self.fx = family_fixtures()["df7"]
        self.registry = VersionedProofRegistry("registry", (record("auth", self.fx.authority),))
        self.gate = CommitTimeGate("gate", self.registry, {self.fx.action.target_id: {"payment": "unscheduled"}})
        self.transition = declared_transition(self.fx.action)

    def prepare(self, memory=None, gate=None):
        gate = gate or self.gate
        cards = self.fx.confirm_memory if memory is None else memory
        return gate.prepare(self.fx.action, self.fx.policy, cards, self.transition, at=PREPARE_AT)

    def commit(self, prepared, *, mode="atomic_revalidate", action=None, transition=None, interleave=None, gate=None):
        return (gate or self.gate).commit(
            prepared, action=action or self.fx.action, transition=transition or self.transition,
            at=COMMIT_AT, mode=mode, interleave=interleave)

    def hold(self, record_id: str = "hold") -> DurableProofRecord:
        return record(record_id, self.fx.active_hold, committed_at=CHANGE_AT)


class RequiredScenarioTests(FinancialPaymentFixture):
    def test_nested_transition_input_cannot_change_prepared_mutation(self) -> None:
        self.transition = {"payload": {"amount": "100", "items": ["original"]}}
        original = deepcopy(self.transition)
        prepared = self.prepare()
        self.transition["payload"]["amount"] = "999"
        result = self.commit(prepared, transition=original)
        self.assertTrue(result.executed)
        self.assertEqual(original["payload"], result.execution.state_after["payload"])

    def test_nested_prepared_token_tampering_is_rejected(self) -> None:
        self.transition = {"payload": {"amount": "100"}}
        original = deepcopy(self.transition)
        prepared = self.prepare()
        dict(prepared.transition)["payload"]["amount"] = "999"
        result = self.commit(prepared, transition=original)
        self.assertFalse(result.executed)
        self.assertIs(result.decision, Decision.HANDOFF)
        self.assertEqual(0, self.gate.state(self.fx.action.target_id)["mutation_count"])

    def test_nested_token_mutation_during_commit_cannot_change_snapshot(self) -> None:
        self.transition = {"payload": {"amount": "100"}}
        original = deepcopy(self.transition)
        prepared = self.prepare()
        result = self.commit(prepared, transition=original, interleave=lambda:
                             dict(prepared.transition)["payload"].update(amount="999"))
        self.assertTrue(result.executed)
        self.assertEqual("100", self.gate.state(self.fx.action.target_id)["payload"]["amount"])

    def test_nested_state_and_execution_views_do_not_mutate_ledger(self) -> None:
        self.transition = {"payload": {"amount": "100"}}
        result = self.commit(self.prepare())
        result.execution.state_after["payload"]["amount"] = "999"
        view = self.gate.state(self.fx.action.target_id)
        view["payload"]["amount"] = "888"
        history = self.gate.executions()
        history[0].state_after["payload"]["amount"] = "777"
        self.assertEqual("100", self.gate.state(self.fx.action.target_id)["payload"]["amount"])
        self.assertEqual("100", self.gate.executions()[0].state_after["payload"]["amount"])

    def test_nested_initial_state_is_detached_from_caller(self) -> None:
        initial = {self.fx.action.target_id: {"payload": {"amount": "100"}}}
        gate = CommitTimeGate("isolated", self.registry, initial)
        initial[self.fx.action.target_id]["payload"]["amount"] = "999"
        self.assertEqual("100", gate.state(self.fx.action.target_id)["payload"]["amount"])

    def test_unchanged_valid_authorization_executes_once(self) -> None:
        prepared = self.prepare()
        self.assertIs(prepared.decision, Decision.AUTO_EXECUTE)
        result = self.commit(prepared)
        self.assertTrue(result.executed)
        self.assertIs(result.decision, Decision.AUTO_EXECUTE)
        self.assertIn(self.fx.authority.card_id, result.commit_check.result.decisive_card_ids)
        state = self.gate.state(self.fx.action.target_id)
        self.assertEqual(1, state["mutation_count"])
        self.assertEqual("unscheduled", state["payment"])  # untouched fields survive
        self.assertEqual(self.fx.action.operation, state["applied_operation"])

    def test_active_hold_published_after_prepare_blocks(self) -> None:
        prepared = self.prepare()
        self.registry.publish(self.hold())
        result = self.commit(prepared)
        self.assertFalse(result.executed)
        self.assertIs(result.decision, Decision.HANDOFF)
        self.assertEqual(("COMMIT_REVALIDATION_FAILED",), result.reason_codes)
        self.assertEqual((self.fx.active_hold.card_id,), result.commit_check.result.decisive_card_ids)
        self.assertEqual(0, self.gate.state(self.fx.action.target_id)["mutation_count"])

    def test_authority_revoked_before_commit_blocks_with_repair_route(self) -> None:
        prepared = self.prepare()
        self.registry.revoke("auth", CHANGE_AT)
        result = self.commit(prepared)
        self.assertFalse(result.executed)
        # The memory still holds an authenticated repair channel, so Confirm is the route.
        self.assertIs(result.decision, Decision.REQUEST_CONFIRMATION)
        self.assertEqual("REPAIRABLE_GAP", result.commit_check.result.authority_status)

    def test_changed_action_or_transition_rejects_the_stale_approval(self) -> None:
        name, value = self.fx.action.scope[0]
        changed = replace(self.fx.action, scope=((name, value + "0"),) + self.fx.action.scope[1:])
        prepared = self.prepare()
        result = self.commit(prepared, action=changed)
        self.assertEqual((False, Decision.HANDOFF, ("ACTION_CHANGED_SINCE_PREPARE",)),
                         (result.executed, result.decision, result.reason_codes))
        # The token is single-use: resubmitting the original parameters does not revive it.
        self.assertEqual(("PREPARED_ALREADY_USED",), self.commit(prepared).reason_codes)
        second = self.prepare()
        altered = {**self.transition, "amount_hkd": "999999"}
        self.assertEqual(("TRANSITION_CHANGED_SINCE_PREPARE",), self.commit(second, transition=altered).reason_codes)
        # A fresh prepare for the original action is still allowed to execute.
        self.assertTrue(self.commit(self.prepare()).executed)

    def test_unavailable_registry_fails_closed_at_commit_and_prepare(self) -> None:
        prepared = self.prepare()
        self.registry.set_available(False)
        result = self.commit(prepared)
        self.assertEqual((False, Decision.HANDOFF, ("REGISTRY_UNAVAILABLE",)),
                         (result.executed, result.decision, result.reason_codes))
        unavailable = self.prepare()
        self.assertIs(unavailable.decision, Decision.HANDOFF)
        self.assertEqual(("REGISTRY_UNAVAILABLE",), unavailable.check.reason_codes)
        self.assertEqual(("PREPARED_DECISION_NOT_EXECUTABLE",), self.commit(unavailable).reason_codes)
        self.assertEqual(0, self.gate.state(self.fx.action.target_id)["mutation_count"])

    def test_relevant_version_change_is_revalidated_or_blocked(self) -> None:
        benign = record("expired-hold", self.fx.expired_hold)
        prepared = self.prepare()
        self.registry.publish(benign)
        result = self.commit(prepared)
        self.assertTrue(result.executed)
        self.assertNotEqual(prepared.check.relevant_version, result.commit_check.relevant_version)
        unchanged_gate = CommitTimeGate("strict-unchanged", self.registry)
        strict = self.commit(self.prepare(gate=unchanged_gate), gate=unchanged_gate, mode="pin_relevant_version")
        self.assertTrue(strict.executed)  # nothing changed since this later prepare
        strict_gate = CommitTimeGate("strict-changed", self.registry)  # fresh state: no prior execution
        strict_prepared = self.prepare(gate=strict_gate)
        self.registry.publish(record("expired-hold-2", replace(self.fx.expired_hold, card_id="expired-2")))
        blocked = self.commit(strict_prepared, gate=strict_gate, mode="pin_relevant_version")
        self.assertEqual(("RELEVANT_EVIDENCE_VERSION_CHANGED",), blocked.reason_codes)
        self.assertFalse(blocked.executed)

    def test_unrelated_evidence_change_causes_no_intervention(self) -> None:
        other = family_fixtures()["dt4"]
        for mode, executes in (("atomic_revalidate", True), ("pin_relevant_version", True),
                               ("pin_registry_version", False)):
            with self.subTest(mode=mode):
                registry = VersionedProofRegistry("r", (record("auth", self.fx.authority),))
                gate = CommitTimeGate("g", registry)
                prepared = self.prepare(gate=gate)
                registry.publish(record("other-hold", other.active_hold, committed_at=CHANGE_AT))
                self.assertEqual(prepared.check.relevant_version,
                                 registry.relevant_version(self.fx.action.operation, self.fx.action.target_id))
                self.assertNotEqual(prepared.check.registry_version, registry.version)
                self.assertEqual(executes, self.commit(prepared, gate=gate, mode=mode).executed)

    def test_duplicate_commits_produce_exactly_one_mutation(self) -> None:
        first = self.prepare()
        second = self.prepare()
        self.assertTrue(self.commit(first).executed)
        self.assertEqual(("PREPARED_ALREADY_USED",), self.commit(first).reason_codes)
        self.assertEqual(("ACTION_ALREADY_EXECUTED_OR_IN_FLIGHT",), self.commit(second).reason_codes)
        self.assertEqual(1, self.gate.state(self.fx.action.target_id)["mutation_count"])
        self.assertEqual(1, len(self.gate.executions()))

    def test_a_blocked_commit_does_not_poison_a_later_legitimate_retry(self) -> None:
        blocked = self.prepare()
        self.registry.publish(self.hold())
        self.assertFalse(self.commit(blocked).executed)
        self.registry.revoke("hold", "2026-10-19T20:04:00+08:00")  # the hold is lifted
        retry = self.commit(self.prepare())
        self.assertTrue(retry.executed)
        self.assertEqual(1, self.gate.state(self.fx.action.target_id)["mutation_count"])


class AtomicityTests(FinancialPaymentFixture):
    def test_write_in_check_to_mutation_window_is_linearized_after_atomic_commit(self) -> None:
        result = self.commit(self.prepare(), interleave=lambda: self.registry.publish(self.hold()))
        self.assertTrue(result.executed)
        hold_change = next(c for c in self.registry.history() if c.record_id == "hold")
        self.assertGreater(hold_change.version, result.execution.applied_relevant_version)
        self.assertEqual(result.execution.validated_relevant_version, result.execution.applied_relevant_version)
        self.assertNotIn("hold", {r.record_id for r in result.execution.evidence_at_apply.records})
        # The deferred hold now governs the next action.
        blocked = self.commit(self.prepare(gate=CommitTimeGate("next", self.registry)),
                              gate=CommitTimeGate("next", self.registry))
        self.assertFalse(blocked.executed)

    def test_unlocked_recheck_applies_a_mutation_after_a_visible_hold(self) -> None:
        result = self.commit(self.prepare(), mode="recheck_unlocked",
                             interleave=lambda: self.registry.publish(self.hold()))
        self.assertTrue(result.executed)  # the TOCTOU window this module closes
        self.assertIn("hold", {r.record_id for r in result.execution.evidence_at_apply.records})
        self.assertNotEqual(result.execution.validated_relevant_version, result.execution.applied_relevant_version)

    def test_writes_inside_an_open_section_are_deferred_in_submission_order(self) -> None:
        with self.registry.commit_section():
            self.assertFalse(self.registry.publish(self.hold("h1")))
            self.assertFalse(self.registry.revoke("auth", CHANGE_AT))
            self.assertEqual(1, self.registry.version)
        self.assertEqual([(2, "publish", "h1"), (3, "revoke", "auth")],
                         [(c.version, c.change, c.record_id) for c in self.registry.history()[1:]])
        self.assertTrue(self.registry.publish(self.hold("h2")))

    def test_invalid_deferred_write_does_not_discard_a_later_hold(self) -> None:
        with self.assertRaises(Exception) as failure:
            with self.registry.commit_section():
                self.registry.publish(self.hold("auth"))  # duplicate, fails when applied
                self.registry.publish(self.hold("valid-hold"))
        self.assertIn("valid-hold", {item.record_id for item in self.registry.oracle_snapshot().records})
        self.assertEqual("valid-hold", self.registry.history()[-1].record_id)
        self.assertIsInstance(failure.exception, ExceptionGroup)

    def test_concurrent_commits_and_revocation_remain_serializable(self) -> None:
        for round_number in range(25):
            registry = VersionedProofRegistry("r", (record("auth", self.fx.authority),))
            gate = CommitTimeGate("g", registry)
            tokens = [self.prepare(gate=gate) for _ in range(6)]
            barrier = threading.Barrier(len(tokens) + 1)
            results = []

            def committer(token):
                barrier.wait()
                results.append(self.commit(token, gate=gate))

            def revoker():
                barrier.wait()
                registry.revoke("auth", CHANGE_AT)

            threads = [threading.Thread(target=committer, args=(t,)) for t in tokens]
            threads.append(threading.Thread(target=revoker))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            executions = gate.executions()
            revocation = next(c.version for c in registry.history() if c.change == "revoke")
            with self.subTest(round=round_number):
                self.assertEqual(len(tokens), len(results))
                self.assertLessEqual(len(executions), 1)
                self.assertEqual(len(executions), gate.state(self.fx.action.target_id)["mutation_count"])
                for execution in executions:
                    self.assertLess(execution.applied_relevant_version, revocation)
                for result in results:
                    if not result.executed and result.commit_check is not None:
                        self.assertGreaterEqual(result.commit_check.relevant_version, revocation)


class EvidenceSemanticsTests(FinancialPaymentFixture):
    def test_existing_lookup_rechecked_with_prepared_instant_misses_a_later_hold(self) -> None:
        # Motivation, not a change: the durable store is point-in-time by design.
        store = DurableProofStore("s", "snap", (self.hold(),))
        lookup = lookup_durable_cards(store, self.fx.action)
        self.assertEqual((("hold", "NOT_YET_COMMITTED"),), lookup.receipt.rejected_records)
        prepared = self.prepare()
        self.registry.publish(self.hold())
        self.assertFalse(self.commit(prepared).executed)  # the gate evaluates at the commit instant

    def test_relevant_version_alone_is_not_enough_without_time_revalidation(self) -> None:
        self.registry.publish(self.hold("scheduled"))  # becomes effective at CHANGE_AT
        prepared = self.prepare()
        self.assertIs(prepared.decision, Decision.AUTO_EXECUTE)
        result = self.commit(prepared, mode="pin_relevant_version")
        self.assertEqual(prepared.check.relevant_version, result.commit_check.relevant_version)
        self.assertFalse(result.executed)
        self.assertIs(result.decision, Decision.HANDOFF)

    def test_registry_revocation_removes_a_memory_copy_of_the_same_card(self) -> None:
        prepared = self.prepare(memory=self.fx.execute_memory)
        self.assertIs(prepared.decision, Decision.AUTO_EXECUTE)
        self.registry.revoke("auth", CHANGE_AT)
        result = self.commit(prepared)
        self.assertFalse(result.executed)
        self.assertIn(f"MEMORY_CARD_REVOKED_IN_REGISTRY:{self.fx.authority.card_id}", result.reason_codes)
        # The existing merge is unchanged: on its own it still keeps the memory copy.
        moment = replace(self.fx.action, effective_at=COMMIT_AT)
        lookup = lookup_durable_cards(self.registry.oracle_snapshot(), moment)
        legacy = validate_proof_cards(augment_with_durable_cards(
            ProofCardInput(moment, self.fx.policy, self.fx.execute_memory), lookup))
        self.assertIs(legacy.decision, Decision.AUTO_EXECUTE)

    def test_conflicting_registry_payload_fails_closed(self) -> None:
        tampered = replace(self.fx.authority, valid_until="2026-10-19T23:00:00+08:00")
        registry = VersionedProofRegistry("r", (record("auth", tampered),))
        gate = CommitTimeGate("g", registry)
        prepared = self.prepare(memory=self.fx.execute_memory, gate=gate)
        self.assertIs(prepared.decision, Decision.HANDOFF)
        self.assertIn("EVIDENCE_CONFLICT", prepared.check.reason_codes)

    def test_prepared_confirm_route_is_returned_and_never_executed(self) -> None:
        gate = CommitTimeGate("g", VersionedProofRegistry("empty"))
        prepared = self.prepare(gate=gate)
        self.assertIs(prepared.decision, Decision.REQUEST_CONFIRMATION)
        result = self.commit(prepared, gate=gate)
        self.assertEqual((False, Decision.REQUEST_CONFIRMATION), (result.executed, result.decision))

    def test_forged_or_foreign_prepared_actions_are_rejected(self) -> None:
        prepared = self.prepare()
        forged = replace(prepared, checked_at="2026-10-19T20:01:00+08:00")
        self.assertEqual(("PREPARED_NOT_ISSUED_BY_GATE",), self.commit(forged).reason_codes)
        foreign = self.prepare(gate=CommitTimeGate("other", self.registry))
        self.assertEqual(("PREPARED_NOT_ISSUED_BY_GATE",), self.commit(foreign).reason_codes)
        self.assertTrue(self.commit(prepared).executed)  # forged attempts do not consume the real token

    def test_invalid_commit_inputs_raise(self) -> None:
        prepared = self.prepare()
        for kwargs in ({"at": "2026-10-19T19:59:00+08:00"}, {"at": "2026-10-19T20:05:00"},
                       {"at": COMMIT_AT, "mode": "optimistic"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.gate.commit(prepared, action=self.fx.action, transition=self.transition, **kwargs)
        with self.assertRaises(ValueError):
            self.gate.prepare(self.fx.action, self.fx.policy, (), {"mutation_count": 3})
        with self.assertRaises(ValueError):
            self.gate.prepare(self.fx.action, self.fx.policy, (), {})


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.summaries = evaluate_commit_gate()
        cls.by_mode = {row["mode"]: row for row in cls.summaries}

    def test_proposed_mode_meets_every_expected_outcome(self) -> None:
        rows = [r for r in self.records if r["mode"] == "atomic_revalidate"]
        self.assertEqual(len(FAMILIES) * len(SCENARIO_CONDITIONS), len(rows))
        for row in rows:
            with self.subTest(condition=row["condition"], family=row["family_id"]):
                self.assertTrue(row["route_correct"])
                self.assertEqual(0, row["unsafe_executions"])
                self.assertEqual(row["expected_executed"], row["executions"] == 1)
        self.assertEqual({"mode": "atomic_revalidate", "scenarios": 39, "unsafe_executions": 0,
                          "duplicate_mutations": 0, "correct_execution_rate": 1.0, "false_blocking_rate": 0.0,
                          "stale_authorization_detection_rate": 1.0, "fail_closed_violations": 0,
                          "action_state_consistency": 1.0, "route_accuracy": 1.0},
                         self.by_mode["atomic_revalidate"])

    def test_baselines_expose_the_failure_each_design_choice_addresses(self) -> None:
        prepared_only = self.by_mode["prepared_only"]
        self.assertEqual((18, 0.0, 3), (prepared_only["unsafe_executions"],
                                        prepared_only["stale_authorization_detection_rate"],
                                        prepared_only["fail_closed_violations"]))
        unlocked = [r for r in self.records if r["mode"] == "recheck_unlocked" and r["unsafe_executions"]]
        self.assertEqual({"interleaved_hold"}, {r["condition"] for r in unlocked})
        self.assertEqual((0.4, 0.2), (self.by_mode["pin_registry_version"]["false_blocking_rate"],
                                      self.by_mode["pin_relevant_version"]["false_blocking_rate"]))
        for mode in COMMIT_MODES:
            self.assertEqual(0, self.by_mode[mode]["duplicate_mutations"])

    def test_metric_denominators_follow_the_labels(self) -> None:
        labels = SCENARIO_CONDITIONS.values()
        self.assertEqual(5, sum(executed for executed, _, _ in labels))
        self.assertEqual(5, sum(stale for _, _, stale in labels))
        self.assertFalse(any(executed and stale for executed, _, stale in labels))

    def test_evaluation_is_deterministic(self) -> None:
        again, _ = evaluate_commit_gate()
        self.assertEqual(json.dumps(self.records, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_reused_durable_store_fixtures_are_unchanged(self) -> None:
        manifest = json.loads((ROOT / "results" / "durable_proof_store_deterministic_v1_manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(manifest["case_set_sha256"], stable_hash(build_durable_proof_cases()))

    def test_single_scenario_rejects_unknown_condition(self) -> None:
        with self.assertRaises(ValueError):
            run_scenario("nothing", "df7", "atomic_revalidate")


class RunnerTests(unittest.TestCase):
    def test_output_prefix_cannot_escape_the_results_directory(self) -> None:
        for prefix in ("../escape", "/absolute", "", "x/y", "..\\escape", "x\n"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                output_paths(prefix)

    def test_plan_is_model_free_and_lists_versioned_outputs(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual((0, 0.0), (plan["measured_generation_calls"], plan["external_api_cost_usd"]))
        self.assertEqual(4, len(plan["outputs_if_run"]))
        self.assertTrue(all("commit_time_gate_deterministic_v1" in path for path in plan["outputs_if_run"]))
        self.assertTrue(all(Path(path).parent == Path("results") for path in plan["outputs_if_run"]))

    def test_plan_rejects_wrong_estimates_or_gate_fields(self) -> None:
        config = load_config(CONFIG)
        wrong = json.loads(json.dumps(config))
        wrong["planning_estimates"]["scenario_runs"] = 10
        with self.assertRaises(ValueError):
            build_plan(wrong)
        wrong = json.loads(json.dumps(config))
        wrong["commit_gate"]["unexpected"] = 1
        with self.assertRaises(ValueError):
            build_plan(wrong)
        wrong = json.loads(json.dumps(config))
        wrong["provider"] = "ollama"
        with self.assertRaises(ValueError):
            build_plan(wrong)

    def test_audit_passes_and_fails_on_a_threshold_violation(self) -> None:
        records, summaries = evaluate_commit_gate()
        gate = _gate(load_config(CONFIG))
        self.assertEqual("PASS_COMMIT_TIME_GATE", commit_gate_audit(records, summaries, gate=gate)["status"])
        broken = [dict(row) for row in summaries]
        next(row for row in broken if row["mode"] == "atomic_revalidate")["unsafe_executions"] = 1
        audit = commit_gate_audit(records, broken, gate=gate)
        self.assertEqual("FAIL_COMMIT_TIME_GATE", audit["status"])
        self.assertFalse(audit["pre_specified_gate"]["proposed_mode_has_no_unsafe_execution"])
        with self.assertRaises(ValueError):
            commit_gate_audit(records[:-1], summaries, gate=gate)

    def test_existing_output_prefix_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("commit_time_gate_deterministic_v1", results_dir=Path(directory))
            assert_paths_available(paths)
            paths["audit"].write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)


if __name__ == "__main__":
    unittest.main()
