from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.proof_cards import (
    ProofCardInput,
    ProofCardKind,
    build_proof_card_cases,
    expired,
    score_proof_card_case,
    validate_proof_cards,
)
from run_proof_card_gate import (
    assert_paths_available,
    build_plan,
    build_records,
    load_config,
    output_paths,
    proof_card_audit,
    summarize,
)


CONFIG = ROOT / "configs" / "proof_card_gate.json"


class ProofCardDatasetTests(unittest.TestCase):
    def test_has_nine_balanced_cases_across_three_domains(self) -> None:
        cases = build_proof_card_cases()
        self.assertEqual(9, len(cases))
        self.assertEqual({"platform", "financial", "mas_travel"}, {x.domain for x in cases})
        counts = {
            decision: sum(case.expected_decision is decision for case in cases)
            for decision in (
                Decision.AUTO_EXECUTE,
                Decision.REQUEST_CONFIRMATION,
                Decision.HANDOFF,
            )
        }
        self.assertEqual(3, counts[Decision.AUTO_EXECUTE])
        self.assertEqual(3, counts[Decision.REQUEST_CONFIRMATION])
        self.assertEqual(3, counts[Decision.HANDOFF])

    def test_runtime_input_cannot_expose_gold_or_case_identity(self) -> None:
        visible_fields = {field.name for field in fields(ProofCardInput)}
        self.assertTrue(visible_fields.isdisjoint({
            "case_id", "domain", "expected_decision", "unsafe_if_executed"
        }))


class ProofCardValidationTests(unittest.TestCase):
    def test_all_frozen_cases_match_route_reason_and_provenance(self) -> None:
        for case in build_proof_card_cases():
            with self.subTest(case=case.case_id):
                result = validate_proof_cards(case.runtime_input)
                score = score_proof_card_case(case, result)
                self.assertTrue(score.route_correct)
                self.assertFalse(score.harmful_execution)
                self.assertTrue(score.reasons_complete)
                self.assertTrue(score.decisive_provenance_complete)
                self.assertFalse(score.clearance_used_as_authority)
                self.assertTrue(score.ignored_cards_are_non_decisive)

    def test_clearance_without_authority_hands_off(self) -> None:
        case = next(x for x in build_proof_card_cases() if x.case_id == "cards-platform-clearance-only")
        result = validate_proof_cards(case.runtime_input)
        self.assertEqual(Decision.HANDOFF, result.decision)
        self.assertEqual("MISSING", result.authority_status)
        self.assertEqual("VERIFIED", result.clearance_status)
        self.assertEqual((), result.authority_card_ids)

    def test_active_hold_dominates_complete_authority(self) -> None:
        case = next(x for x in build_proof_card_cases() if x.case_id == "cards-financial-hold")
        result = validate_proof_cards(case.runtime_input)
        self.assertEqual(Decision.HANDOFF, result.decision)
        self.assertEqual("BLOCKED", result.hold_status)
        self.assertEqual(("M6-35",), result.decisive_card_ids)

    def test_missing_delegation_cannot_be_repaired_by_requester(self) -> None:
        case = next(x for x in build_proof_card_cases() if x.case_id == "cards-mas-handoff")
        result = validate_proof_cards(case.runtime_input)
        self.assertEqual(Decision.HANDOFF, result.decision)
        self.assertIn("delegation", result.missing_obligations)

    def test_expired_authority_is_ignored_and_repair_channel_can_confirm(self) -> None:
        execute = next(x for x in build_proof_card_cases() if x.case_id == "cards-platform-execute")
        confirm = next(x for x in build_proof_card_cases() if x.case_id == "cards-platform-confirm")
        authority = next(card for card in execute.runtime_input.cards if card.kind is ProofCardKind.AUTHORITY)
        cards = (expired(authority),) + confirm.runtime_input.cards
        result = validate_proof_cards(replace(confirm.runtime_input, cards=cards))
        self.assertEqual(Decision.REQUEST_CONFIRMATION, result.decision)
        self.assertIn(authority.card_id, result.ignored_card_ids)

    def test_wrong_target_scope_issuer_and_authentication_are_ignored(self) -> None:
        case = next(x for x in build_proof_card_cases() if x.case_id == "cards-platform-execute")
        authority = next(card for card in case.runtime_input.cards if card.kind is ProofCardKind.AUTHORITY)
        invalid_cards = (
            replace(authority, card_id="bad-target", target_id="another-service"),
            replace(authority, card_id="bad-scope", scope=(("namespace", "staging"),)),
            replace(authority, card_id="bad-issuer", issuer_id="chat-user"),
            replace(authority, card_id="bad-auth", authenticated=False),
        )
        base_cards = tuple(card for card in case.runtime_input.cards if card.kind is not ProofCardKind.AUTHORITY)
        result = validate_proof_cards(replace(case.runtime_input, cards=invalid_cards + base_cards))
        self.assertEqual(Decision.HANDOFF, result.decision)
        self.assertEqual({card.card_id for card in invalid_cards}, set(result.ignored_card_ids) - {"T4-52"})


class ProofCardRunnerTests(unittest.TestCase):
    def test_plan_is_local_model_free_and_zero_cost(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["cases"])
        self.assertEqual(0, plan["measured_generation_calls"])
        self.assertIsNone(plan["model"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("proof", results_dir=Path(directory))
            paths["manifest"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_frozen_records_pass_pre_specified_gate(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        summaries = summarize(records)
        audit = proof_card_audit(records, summaries, gate=config["proof_card_gate"])
        self.assertEqual("PASS_PROOF_CARD_INTERFACE_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))

    def test_audit_fails_if_clearance_is_promoted_or_reason_is_missing(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        records[0]["clearance_promoted_to_authority"] = 1
        records[0]["score"]["reasons_complete"] = False
        audit = proof_card_audit(records, summarize(records), gate=config["proof_card_gate"])
        self.assertEqual("FAIL_PROOF_CARD_INTERFACE_GATE", audit["status"])
        self.assertFalse(audit["pre_specified_gate"]["clearance_is_never_promoted_to_authority"])
        self.assertFalse(audit["pre_specified_gate"]["required_reasons_are_complete"])


if __name__ == "__main__":
    unittest.main()
