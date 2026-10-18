from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.durable_proof_store import (
    CONDITIONS,
    DurableLookupResult,
    augment_with_durable_cards,
    build_durable_proof_cases,
    evaluate_durable_case,
    lookup_durable_cards,
)
from run_durable_proof_store_gate import (
    assert_paths_available,
    build_plan,
    build_records,
    durable_store_audit,
    load_config,
    output_paths,
    summarize,
)


CONFIG = ROOT / "configs" / "durable_proof_store_gate.json"


class DurableProofDatasetTests(unittest.TestCase):
    def test_has_three_fresh_families_and_six_conditions_each(self) -> None:
        cases = build_durable_proof_cases()
        self.assertEqual(18, len(cases))
        self.assertEqual({"platform", "financial", "mas_travel"}, {x.domain for x in cases})
        self.assertEqual(3, len({x.family_id for x in cases}))
        for family_id in {x.family_id for x in cases}:
            self.assertEqual(set(CONDITIONS), {x.condition for x in cases if x.family_id == family_id})

    def test_memory_only_preconditions_and_durable_gold_are_frozen(self) -> None:
        for case in build_durable_proof_cases():
            with self.subTest(case=case.case_id):
                evaluation = evaluate_durable_case(case)
                self.assertTrue(evaluation.memory_matches_frozen_precondition)
                self.assertTrue(evaluation.durable_route_correct)
                self.assertEqual(
                    case.expected_returned_card_ids,
                    evaluation.receipt.returned_card_ids,
                )
                self.assertEqual(
                    case.expected_decisive_retrieved_card_ids,
                    evaluation.retrieved_decisive_card_ids,
                )


class DurableProofLookupTests(unittest.TestCase):
    def test_hidden_active_holds_remove_three_unsafe_memory_executions(self) -> None:
        items = [
            evaluate_durable_case(case)
            for case in build_durable_proof_cases()
            if case.condition == "recover_active_hold"
        ]
        self.assertEqual(3, sum(x.memory_harmful_execution for x in items))
        self.assertEqual(0, sum(x.durable_harmful_execution for x in items))
        self.assertTrue(all(x.durable_result.decision is Decision.HANDOFF for x in items))

    def test_valid_authority_restores_three_safe_executions(self) -> None:
        items = [
            evaluate_durable_case(case)
            for case in build_durable_proof_cases()
            if case.condition == "recover_valid_authority"
        ]
        self.assertTrue(all(x.memory_result.decision is Decision.REQUEST_CONFIRMATION for x in items))
        self.assertTrue(all(x.durable_result.decision is Decision.AUTO_EXECUTE for x in items))

    def test_expired_revoked_and_wrong_scope_controls_do_not_change_routes(self) -> None:
        controls = {
            "ignore_expired_hold",
            "ignore_revoked_hold",
            "reject_wrong_scope_authority",
            "reject_revoked_authority",
        }
        for case in build_durable_proof_cases():
            if case.condition not in controls:
                continue
            with self.subTest(case=case.case_id):
                evaluation = evaluate_durable_case(case)
                self.assertEqual(evaluation.memory_result.decision, evaluation.durable_result.decision)
                self.assertFalse(evaluation.retrieval_harmful)

    def test_revoked_record_is_rejected_by_point_in_time_lookup(self) -> None:
        case = next(
            x for x in build_durable_proof_cases()
            if x.condition == "reject_revoked_authority"
        )
        lookup = lookup_durable_cards(case.store, case.memory_input.action)
        self.assertEqual((), lookup.cards)
        self.assertEqual("REVOKED", lookup.receipt.rejected_records[0][1])

    def test_conflicting_card_id_cannot_shadow_memory(self) -> None:
        case = build_durable_proof_cases()[0]
        existing = case.memory_input.cards[0]
        conflicting = replace(existing, issuer_id="untrusted-shadow")
        lookup = DurableLookupResult(
            cards=(conflicting,),
            receipt=lookup_durable_cards(case.store, case.memory_input.action).receipt,
        )
        with self.assertRaises(ValueError):
            augment_with_durable_cards(case.memory_input, lookup)


class DurableProofRunnerTests(unittest.TestCase):
    def test_plan_is_local_model_free_and_zero_cost(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(3, plan["base_families"])
        self.assertEqual(18, plan["cases"])
        self.assertEqual(0, plan["measured_generation_calls"])
        self.assertIsNone(plan["model"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("durable", results_dir=Path(directory))
            paths["audit"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_frozen_records_pass_pre_specified_gate(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        audit = durable_store_audit(records, summarize(records), gate=config["durable_store_gate"])
        self.assertEqual("PASS_DURABLE_PROOF_STORE_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))

    def test_audit_fails_when_a_control_is_spoiled(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        control = next(x for x in records if x["condition"] == "ignore_expired_hold")
        control["evaluation"]["durable_result"]["decision"] = Decision.HANDOFF.value
        audit = durable_store_audit(records, summarize(records), gate=config["durable_store_gate"])
        self.assertEqual("FAIL_DURABLE_PROOF_STORE_GATE", audit["status"])
        self.assertFalse(audit["pre_specified_gate"]["negative_controls_do_not_change_route"])


if __name__ == "__main__":
    unittest.main()
