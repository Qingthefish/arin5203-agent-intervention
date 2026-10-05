from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.audit_increment import (
    CONDITIONS,
    METHODS,
    build_audit_contexts,
    build_audit_families,
    build_review_prompt,
)
from platform_agent_eval.domain import Decision
from platform_agent_eval.model_routing import ModelResponse
from platform_agent_eval.protocol_falsification import parse_protocol_route_output
from run_audit_increment_gate import (
    assert_paths_available,
    build_plan,
    increment_audit,
    load_config,
    output_paths,
    pairwise_increment,
    summarize,
)
from audit_increment_traces import trace_review


CONFIG = ROOT / "configs" / "audit_increment_gate.json"


def response(payload: object) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(payload),
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        model_id="fake-model",
    )


def candidate_for(context):
    first_factor, spec = next(iter(context.gold.decisive_factors.items()))
    evidence = sorted(next(iter(spec.required_evidence_sets)))
    return parse_protocol_route_output(
        response(
            {
                "decision": context.expected_decision.value,
                "risk_score": 0.2,
                "decisive_findings": [
                    {"factor": first_factor, "evidence_ids": evidence}
                ],
            }
        ),
        active_context=context.active_context,
    )


class AuditIncrementDatasetTests(unittest.TestCase):
    def test_has_three_domains_and_nine_grouped_contexts(self) -> None:
        families = build_audit_families()
        contexts = build_audit_contexts()
        self.assertEqual({"platform", "financial", "mas"}, {x.domain for x in families})
        self.assertEqual(9, len(contexts))
        for family in families:
            siblings = [x for x in contexts if x.family_id == family.family_id]
            self.assertEqual(set(CONDITIONS), {x.condition for x in siblings})
            self.assertEqual(1, len({x.proposed_action for x in siblings}))

    def test_critical_and_noise_deletions_are_matched(self) -> None:
        for family in build_audit_families():
            by_id = {event.event_id: event for event in family.history}
            critical = by_id[family.critical_event_id]
            noise = by_id[family.matched_noise_event_id]
            self.assertEqual(critical.role, noise.role)
            positions = {event.event_id: i for i, event in enumerate(family.history)}
            self.assertEqual(
                1,
                abs(positions[critical.event_id] - positions[noise.event_id]),
            )
            lengths = (len(critical.content.split()), len(noise.content.split()))
            self.assertLessEqual(max(lengths) / min(lengths), 1.2)
            self.assertRegex(critical.event_id, r"^[A-Z]\d-\d{2}$")
            self.assertRegex(noise.event_id, r"^[A-Z]\d-\d{2}$")

    def test_deletion_routes_cover_confirm_handoff_and_harmful_execute_risk(self) -> None:
        critical = {
            context.family_id: context
            for context in build_audit_contexts()
            if context.condition == "remove_action_critical"
        }
        self.assertEqual(
            Decision.REQUEST_CONFIRMATION,
            critical["audit-j3"].expected_decision,
        )
        self.assertEqual(Decision.HANDOFF, critical["audit-r6"].expected_decision)
        self.assertEqual(Decision.HANDOFF, critical["audit-v9"].expected_decision)
        self.assertTrue(all(context.unsafe_if_executed for context in critical.values()))

    def test_reviews_share_context_and_hide_private_labels(self) -> None:
        for context in build_audit_contexts():
            candidate = candidate_for(context)
            for method in ("prompt_critic", "evidence_audit"):
                prompt = build_review_prompt(context, candidate, method)
                self.assertIn(context.active_context, prompt)
                self.assertIn(context.proposed_action, prompt)
                self.assertNotIn(context.case_id, prompt)
                self.assertNotIn(context.condition, prompt)
                self.assertNotIn("expected_decision", prompt)


class AuditIncrementRunnerTests(unittest.TestCase):
    def test_plan_is_local_frozen_and_has_twenty_seven_calls(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["matched_contexts"])
        self.assertEqual(27, plan["measured_generation_calls"])
        self.assertEqual(list(METHODS), plan["methods"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("audit", results_dir=Path(directory))
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_pairwise_metrics_and_pre_specified_gate_have_known_values(self) -> None:
        records = []
        deliberately_wrong = {
            "audit-j3::remove_action_critical",
            "audit-v9::remove_action_critical",
        }
        for context in build_audit_contexts():
            for method in METHODS:
                if method in {"direct_router", "prompt_critic"} and context.case_id in deliberately_wrong:
                    decision = Decision.AUTO_EXECUTE
                elif method == "always_confirm":
                    decision = Decision.REQUEST_CONFIRMATION
                else:
                    decision = context.expected_decision
                correct = decision is context.expected_decision
                direct_decision = (
                    Decision.AUTO_EXECUTE
                    if context.case_id in deliberately_wrong
                    else context.expected_decision
                )
                records.append(
                    {
                        "case_id": context.case_id,
                        "family_id": context.family_id,
                        "condition": context.condition,
                        "method": method,
                        "decision": decision.value,
                        "correct_route": correct,
                        "harmful_execution": bool(
                            context.unsafe_if_executed
                            and decision is Decision.AUTO_EXECUTE
                        ),
                        "unjustified_execution": bool(
                            context.expected_decision is not Decision.AUTO_EXECUTE
                            and decision is Decision.AUTO_EXECUTE
                        ),
                        "unnecessary_intervention": bool(
                            context.expected_decision is Decision.AUTO_EXECUTE
                            and decision is not Decision.AUTO_EXECUTE
                        ),
                        "predicted_factor_count": 1,
                        "grounded_factor_count": int(correct),
                        "decisive_factor_recall": float(correct),
                        "joint_grounded_route_correct": correct,
                        "format_valid": True,
                        "changed_candidate_route": decision is not direct_decision,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    }
                )
        increment = pairwise_increment(records, "evidence_audit")
        self.assertEqual(2, increment["corrected_direct_errors"])
        self.assertEqual(0, increment["spoiled_direct_correct"])
        self.assertEqual(2, increment["net_corrections"])

        summaries = summarize(records)
        audit = increment_audit(
            records,
            summaries,
            gate=load_config(CONFIG)["audit_increment_gate"],
        )
        self.assertEqual("PASS_AUDIT_INCREMENT_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))

    def test_post_hoc_trace_review_separates_raw_intent_from_fail_closed_route(self) -> None:
        records = []
        unsafe_case = "audit-j3::remove_action_critical"
        for context in build_audit_contexts():
            for method in METHODS:
                raw_route = context.expected_decision.value
                parsed_route = raw_route
                format_valid = True
                if context.case_id == unsafe_case and method in {
                    "direct_router",
                    "evidence_audit",
                }:
                    raw_route = Decision.AUTO_EXECUTE.value
                    parsed_route = Decision.HANDOFF.value
                    format_valid = False
                elif context.case_id == unsafe_case and method == "prompt_critic":
                    raw_route = Decision.REQUEST_CONFIRMATION.value
                    parsed_route = raw_route
                records.append(
                    {
                        "case_id": context.case_id,
                        "method": method,
                        "unsafe_if_executed": context.unsafe_if_executed,
                        "format_valid": format_valid,
                        "decision": parsed_route,
                        "harmful_execution": bool(
                            context.unsafe_if_executed
                            and parsed_route == Decision.AUTO_EXECUTE.value
                        ),
                        "raw_output": json.dumps({"decision": raw_route}),
                    }
                )
        review = trace_review(records)
        self.assertEqual(
            1,
            review["per_method"]["direct_router"]["raw_unsafe_auto_intents"],
        )
        self.assertEqual(
            1,
            review["per_method"]["direct_router"][
                "fail_closed_blocks_of_raw_unsafe_auto"
            ],
        )
        self.assertEqual(
            [unsafe_case],
            review["candidate_anchor_review"]["evidence_audit"][
                "retained_unsafe_auto_intent"
            ],
        )


if __name__ == "__main__":
    unittest.main()
