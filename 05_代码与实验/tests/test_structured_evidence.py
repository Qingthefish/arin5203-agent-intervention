from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.compaction import estimate_tokens
from platform_agent_eval.domain import Decision
from platform_agent_eval.grounded_routing import GroundedFactorClaim
from platform_agent_eval.model_routing import ModelResponse
from platform_agent_eval.structured_evidence import (
    SLOT_KINDS,
    STRUCTURED_EXTRACTION_PROMPT_VERSION,
    STRUCTURED_SCENARIO_SET_VERSION,
    EvidenceSlot,
    SlotExtraction,
    build_slot_extraction_prompt,
    build_structured_scenarios,
    link_structured_evidence,
    parse_slot_output,
    render_structured_context,
    score_factor_proof,
    score_slots,
    score_transition_attribution,
)
from run_structured_evidence_smoke import (
    assert_paths_available,
    build_plan,
    load_config,
    output_paths,
    structured_audit,
)


def response(payload: object) -> ModelResponse:
    return ModelResponse(
        text=payload if isinstance(payload, str) else json.dumps(payload),
        prompt_tokens=10,
        completion_tokens=10,
        latency_ms=1.0,
        model_id="fake-model",
    )


def perfect_factor_claims(scenario) -> tuple[GroundedFactorClaim, ...]:
    claims = [
        GroundedFactorClaim(
            spec.factor,
            tuple(sorted(spec.required_evidence_ids)),
        )
        for spec in scenario.route_factor_specs
    ]
    if scenario.diagnostic_slots:
        claims.append(
            GroundedFactorClaim("RESPONDER_NOT_AUTHORIZED", ("CTX-C07",))
        )
    return tuple(claims)


class StructuredScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_structured_scenarios()

    def test_new_set_has_three_domains_and_three_routes(self) -> None:
        self.assertEqual("structured-evidence-smoke-v1", STRUCTURED_SCENARIO_SET_VERSION)
        self.assertEqual(9, len(self.scenarios))
        self.assertEqual(
            {"platform", "financial", "mas"},
            {scenario.domain for scenario in self.scenarios},
        )
        for domain in {"platform", "financial", "mas"}:
            items = [scenario for scenario in self.scenarios if scenario.domain == domain]
            self.assertEqual(
                {
                    Decision.AUTO_EXECUTE,
                    Decision.REQUEST_CONFIRMATION,
                    Decision.HANDOFF,
                },
                {scenario.expected_decision for scenario in items},
            )

    def test_context_shape_and_length_are_matched_within_domain(self) -> None:
        for domain in {"platform", "financial", "mas"}:
            items = [scenario for scenario in self.scenarios if scenario.domain == domain]
            roles = [tuple(event.role for event in scenario.history) for scenario in items]
            self.assertEqual(1, len(set(roles)))
            self.assertTrue(all(len(scenario.history) == 9 for scenario in items))
            lengths = [
                estimate_tokens(render_structured_context(scenario))
                for scenario in items
            ]
            self.assertLessEqual(max(lengths) / min(lengths), 1.15)

    def test_opaque_entities_and_actions_are_new(self) -> None:
        rendered = "\n".join(render_structured_context(item) for item in self.scenarios)
        for old_id in (
            "project-atlas",
            "HK-ENTITY-204",
            "OWN-17",
            "FC-18",
            "PO-41",
        ):
            self.assertNotIn(old_id, rendered)
        for new_id in ("SVC-LYRA-81", "FIN-731", "WF-ORBIT-72"):
            self.assertIn(new_id, rendered)

    def test_route_and_transition_gold_are_separate(self) -> None:
        handoffs = [item for item in self.scenarios if item.condition == "handoff"]
        self.assertEqual(3, len(handoffs))
        for scenario in handoffs:
            self.assertEqual(2, len(scenario.decisive_slots))
            self.assertEqual("RESPONDER_ID", scenario.diagnostic_slots[0].kind)
            self.assertEqual(
                {"POLICY_HOLD_ACTIVE", "OPERATOR_ADJUDICATION_REQUIRED"},
                {spec.factor for spec in scenario.route_factor_specs},
            )

    def test_prompt_contains_schema_but_not_private_route(self) -> None:
        scenario = next(item for item in self.scenarios if item.condition == "confirm")
        prompt = build_slot_extraction_prompt(
            scenario.action,
            render_structured_context(scenario),
        )
        self.assertIn(
            f"PROMPT_TEMPLATE={STRUCTURED_EXTRACTION_PROMPT_VERSION}", prompt
        )
        self.assertIn("Extract atomic evidence only", prompt)
        self.assertIn("AUTHORIZED_ACTOR", prompt)
        self.assertNotIn(scenario.scenario_id, prompt)
        self.assertNotIn(scenario.condition, prompt)
        self.assertNotIn(scenario.expected_decision.value, prompt)


class StructuredParserAndLinkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_structured_scenarios()

    def extraction(self, scenario, slots=None) -> SlotExtraction:
        chosen = scenario.true_slots if slots is None else slots
        return SlotExtraction(tuple(chosen), True, response({"slots": []}), "{}")

    def test_exact_slot_schema_parses(self) -> None:
        scenario = self.scenarios[0]
        payload = {"slots": [asdict(slot) for slot in scenario.true_slots]}
        parsed = parse_slot_output(
            response(payload), active_context=render_structured_context(scenario)
        )
        self.assertTrue(parsed.format_valid)
        self.assertEqual(scenario.true_slots, parsed.slots)
        self.assertTrue(set(slot.kind for slot in parsed.slots).issubset(SLOT_KINDS))

    def test_parser_fails_closed_on_extra_key_or_invisible_event(self) -> None:
        scenario = self.scenarios[0]
        bad_payloads = [
            {"slots": [], "decision": "AUTO_EXECUTE"},
            {
                "slots": [
                    {
                        "kind": "AUTHORIZED_ACTOR",
                        "value": "OWN-N47",
                        "evidence_id": "CTX-C99",
                    }
                ]
            },
            {
                "slots": [
                    {
                        "kind": "UNKNOWN",
                        "value": "OWN-N47",
                        "evidence_id": "CTX-C04",
                    }
                ]
            },
        ]
        for payload in bad_payloads:
            parsed = parse_slot_output(
                response(payload), active_context=render_structured_context(scenario)
            )
            self.assertFalse(parsed.format_valid)
            linked = link_structured_evidence(scenario.action, parsed)
            self.assertIs(Decision.HANDOFF, linked.decision)

    def test_perfect_slots_link_all_three_routes(self) -> None:
        for scenario in self.scenarios:
            extraction = self.extraction(scenario)
            linked = link_structured_evidence(scenario.action, extraction)
            self.assertIs(scenario.expected_decision, linked.decision)
            proof = score_factor_proof(scenario, linked.factor_claims)
            self.assertTrue(proof.exact_complete)
            score = score_slots(scenario, extraction)
            self.assertEqual(1.0, score.atomic_precision)
            self.assertEqual(1.0, score.decisive_atomic_recall)

    def test_missing_signature_cannot_auto_execute(self) -> None:
        scenario = next(item for item in self.scenarios if item.condition == "execute")
        slots = tuple(
            slot for slot in scenario.true_slots if slot.kind != "GRANT_SIGNER"
        )
        linked = link_structured_evidence(scenario.action, self.extraction(scenario, slots))
        self.assertIs(Decision.HANDOFF, linked.decision)

    def test_wrong_actor_join_cannot_auto_execute(self) -> None:
        scenario = next(item for item in self.scenarios if item.condition == "execute")
        slots = tuple(
            EvidenceSlot(slot.kind, "ACTOR-WRONG", slot.evidence_id)
            if slot.kind == "GRANT_SIGNER"
            else slot
            for slot in scenario.true_slots
        )
        linked = link_structured_evidence(scenario.action, self.extraction(scenario, slots))
        self.assertIs(Decision.HANDOFF, linked.decision)

    def test_transition_claim_does_not_pollute_route_proof(self) -> None:
        scenario = next(item for item in self.scenarios if item.condition == "handoff")
        claims = perfect_factor_claims(scenario)
        proof = score_factor_proof(scenario, claims)
        self.assertTrue(proof.exact_complete)
        self.assertEqual(2, proof.predicted_count)
        self.assertTrue(score_transition_attribution(scenario, claims))

    def test_spurious_transition_claim_breaks_non_handoff_proof(self) -> None:
        scenario = next(item for item in self.scenarios if item.condition == "execute")
        claims = (
            *perfect_factor_claims(scenario),
            GroundedFactorClaim("RESPONDER_NOT_AUTHORIZED", ("CTX-C07",)),
        )
        proof = score_factor_proof(scenario, claims)
        self.assertFalse(proof.exact_complete)
        self.assertEqual(1, proof.unsupported_count)


class StructuredRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "structured_evidence_smoke.json")

    def test_plan_is_local_zero_cost_and_pre_registered(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(18, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])
        self.assertEqual(64, len(plan["public_scenario_sha256"]))
        self.assertEqual(64, len(plan["gold_evidence_graph_sha256"]))

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("trial", results_dir=Path(directory))
            assert_paths_available(paths)
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def _perfect_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for scenario in build_structured_scenarios():
            factor_claims = perfect_factor_claims(scenario)
            baseline_payload = {
                "decision": scenario.expected_decision.value,
                "risk_score": 0.1,
                "decisive_findings": [asdict(claim) for claim in factor_claims],
            }
            records.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "domain": scenario.domain,
                    "condition": scenario.condition,
                    "method": "frozen_v4",
                    "expected_decision": scenario.expected_decision.value,
                    "raw_output": json.dumps(baseline_payload),
                    "active_context": render_structured_context(scenario),
                    "model_id": "fake-model",
                }
            )
            records.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "domain": scenario.domain,
                    "condition": scenario.condition,
                    "method": "structured_linker",
                    "expected_decision": scenario.expected_decision.value,
                    "raw_output": json.dumps(
                        {"slots": [asdict(slot) for slot in scenario.true_slots]}
                    ),
                    "active_context": render_structured_context(scenario),
                    "model_id": "fake-model",
                }
            )
        return records

    def test_perfect_records_pass_pre_specified_gate(self) -> None:
        audit = structured_audit(
            self._perfect_records(),
            build_plan(self.config)["structured_gate"],
        )
        self.assertEqual("PASS_TO_FIXED_BUDGET_PILOT", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))

    def test_audit_rejects_missing_record(self) -> None:
        records = self._perfect_records()
        with self.assertRaises(ValueError):
            structured_audit(
                records[:-1],
                build_plan(self.config)["structured_gate"],
            )


if __name__ == "__main__":
    unittest.main()
