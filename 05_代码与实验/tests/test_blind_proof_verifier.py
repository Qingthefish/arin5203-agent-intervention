from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.blind_proof_verifier import (
    CONDITIONS,
    METHODS,
    ProofClaim,
    ProofDecision,
    build_proof_contexts,
    build_proof_families,
    build_proof_prompt,
    map_proof_to_route,
    parse_proof_output,
    score_proof,
)
from platform_agent_eval.domain import Decision
from platform_agent_eval.model_routing import ModelResponse
from run_blind_proof_gate import (
    assert_paths_available,
    build_plan,
    load_config,
    output_paths,
    proof_audit,
    summarize,
)


CONFIG = ROOT / "configs" / "blind_proof_gate.json"


def response(payload: object) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(payload),
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        model_id="fake-model",
    )


class BlindProofDatasetTests(unittest.TestCase):
    def test_has_three_fresh_domains_and_nine_grouped_contexts(self) -> None:
        families = build_proof_families()
        contexts = build_proof_contexts()
        self.assertEqual({"platform", "financial", "mas"}, {x.domain for x in families})
        self.assertEqual(9, len(contexts))
        for family in families:
            siblings = [x for x in contexts if x.family_id == family.family_id]
            self.assertEqual(set(CONDITIONS), {x.condition for x in siblings})
            self.assertEqual(1, len({x.proposed_action for x in siblings}))

    def test_critical_and_noise_events_are_matched(self) -> None:
        for family in build_proof_families():
            by_id = {event.event_id: event for event in family.history}
            critical = by_id[family.critical_event_id]
            noise = by_id[family.matched_noise_event_id]
            self.assertEqual(critical.role, noise.role)
            positions = {event.event_id: i for i, event in enumerate(family.history)}
            self.assertEqual(1, abs(positions[critical.event_id] - positions[noise.event_id]))
            lengths = (len(critical.content.split()), len(noise.content.split()))
            self.assertLessEqual(max(lengths) / min(lengths), 1.2)
            self.assertRegex(critical.event_id, r"^[A-Z]\d-\d{2}$")
            self.assertRegex(noise.event_id, r"^[A-Z]\d-\d{2}$")

    def test_blind_prompt_contains_no_candidate_or_private_route(self) -> None:
        for context in build_proof_contexts():
            prompt = build_proof_prompt(context)
            self.assertIn(context.active_context, prompt)
            self.assertIn(context.proposed_action, prompt)
            self.assertNotIn("CANDIDATE_ROUTE", prompt)
            self.assertNotIn(context.case_id, prompt)
            self.assertNotIn(context.condition, prompt)
            self.assertNotIn("expected_decision", prompt)

    def test_deterministic_mapper_has_three_routes_and_fails_closed(self) -> None:
        self.assertEqual(
            Decision.AUTO_EXECUTE,
            map_proof_to_route("VERIFIED", "VERIFIED"),
        )
        self.assertEqual(
            Decision.REQUEST_CONFIRMATION,
            map_proof_to_route("REPAIRABLE_GAP", "VERIFIED"),
        )
        self.assertEqual(
            Decision.HANDOFF,
            map_proof_to_route("OPERATOR_ONLY_GAP", "VERIFIED"),
        )
        self.assertEqual(Decision.HANDOFF, map_proof_to_route("UNKNOWN", "UNKNOWN"))


class BlindProofScoringTests(unittest.TestCase):
    def test_valid_platform_proof_maps_to_execute(self) -> None:
        context = next(
            item
            for item in build_proof_contexts()
            if item.case_id == "proof-b8::full_evidence"
        )
        proof = parse_proof_output(
            response(
                {
                    "authority": {
                        "status": "VERIFIED",
                        "evidence_ids": ["B8-05"],
                    },
                    "recovery": {
                        "status": "VERIFIED",
                        "evidence_ids": ["B8-09"],
                    },
                }
            ),
            active_context=context.active_context,
        )
        score = score_proof(context, proof)
        self.assertEqual(Decision.AUTO_EXECUTE, proof.mapped_decision)
        self.assertTrue(score.joint_decisive_proof_route_correct)
        self.assertTrue(score.full_proof_correct)

    def test_handoff_decisive_proof_is_separate_from_supporting_recovery(self) -> None:
        context = next(
            item
            for item in build_proof_contexts()
            if item.case_id == "proof-n5::full_evidence"
        )
        proof = ProofDecision(
            authority=ProofClaim("BLOCKED", ("N5-05",)),
            recovery=ProofClaim("UNKNOWN", ("N5-08",)),
            mapped_decision=Decision.HANDOFF,
            format_valid=True,
            response=response({"unused": True}),
            raw_output="{}",
        )
        score = score_proof(context, proof)
        self.assertTrue(score.joint_decisive_proof_route_correct)
        self.assertFalse(score.supporting_recovery_correct)
        self.assertFalse(score.full_proof_correct)

    def test_invalid_output_fails_closed(self) -> None:
        context = build_proof_contexts()[0]
        proof = parse_proof_output(
            response({"authority": {"status": "VERIFIED"}}),
            active_context=context.active_context,
        )
        self.assertFalse(proof.format_valid)
        self.assertEqual(Decision.HANDOFF, proof.mapped_decision)


class BlindProofRunnerTests(unittest.TestCase):
    def test_plan_is_local_and_has_eighteen_calls(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["matched_contexts"])
        self.assertEqual(18, plan["measured_generation_calls"])
        self.assertEqual(list(METHODS), plan["methods"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("proof", results_dir=Path(directory))
            paths["manifest"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_perfect_verifier_with_two_direct_errors_passes_gate(self) -> None:
        wrong_cases = {
            "proof-b8::remove_action_critical",
            "proof-q2::remove_action_critical",
        }
        records = []
        for context in build_proof_contexts():
            for method in METHODS:
                decision = context.expected_decision
                if method == "direct_router" and context.case_id in wrong_cases:
                    decision = Decision.AUTO_EXECUTE
                correct = decision is context.expected_decision
                records.append(
                    {
                        "case_id": context.case_id,
                        "method": method,
                        "decision": decision.value,
                        "correct_route": correct,
                        "harmful_execution": bool(
                            context.unsafe_if_executed
                            and decision is Decision.AUTO_EXECUTE
                        ),
                        "unnecessary_intervention": False,
                        "format_valid": True,
                        "joint_decisive_proof_route_correct": (
                            correct if method == "direct_router" else True
                        ),
                        "full_proof_correct": (
                            correct if method == "direct_router" else True
                        ),
                        "decisive_proof_recall": float(
                            correct if method == "direct_router" else True
                        ),
                        "supporting_recovery_correct": (
                            True if method == "blind_proof_verifier" else None
                        ),
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    }
                )
        summaries = summarize(records)
        audit = proof_audit(
            records,
            summaries,
            gate=load_config(CONFIG)["blind_proof_gate"],
        )
        self.assertEqual("PASS_BLIND_PROOF_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))


if __name__ == "__main__":
    unittest.main()
