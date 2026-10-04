from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.matched_scratch import (
    CONDITIONS,
    all_gold_evidence_visible,
    build_scratch_contexts,
    build_scratch_families,
    score_scratch_route,
)
from platform_agent_eval.model_routing import ModelResponse
from platform_agent_eval.protocol_falsification import (
    build_protocol_route_prompt,
    parse_protocol_route_output,
)
from run_scratch_matched_gate import (
    assert_paths_available,
    build_plan,
    load_config,
    output_paths,
    scratch_audit,
    summarize,
)


CONFIG = ROOT / "configs" / "scratch_matched_gate.json"


def response(payload: object) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(payload),
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        model_id="fake-model",
    )


class ScratchDatasetTests(unittest.TestCase):
    def test_has_three_domains_and_nine_grouped_contexts(self) -> None:
        families = build_scratch_families()
        contexts = build_scratch_contexts()
        self.assertEqual({"platform", "financial", "mas"}, {x.domain for x in families})
        self.assertEqual(9, len(contexts))
        for family in families:
            siblings = [x for x in contexts if x.family_id == family.family_id]
            self.assertEqual(set(CONDITIONS), {x.condition for x in siblings})
            self.assertEqual(1, len({x.proposed_action for x in siblings}))

    def test_critical_and_noise_events_are_role_position_length_matched(self) -> None:
        for family in build_scratch_families():
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

    def test_deletions_remove_exactly_one_intended_event(self) -> None:
        contexts = build_scratch_contexts()
        for context in contexts:
            if context.condition == "full_evidence":
                self.assertEqual((), context.removed_event_ids)
            else:
                self.assertEqual(1, len(context.removed_event_ids))
            visible = {event.event_id for event in context.active_events}
            if context.condition == "remove_action_critical":
                self.assertNotIn(context.critical_event_id, visible)
                self.assertIn(context.matched_noise_event_id, visible)
            elif context.condition == "remove_matched_noise":
                self.assertIn(context.critical_event_id, visible)
                self.assertNotIn(context.matched_noise_event_id, visible)

    def test_expected_routes_cover_both_deletion_directions(self) -> None:
        by_key = {(x.family_id, x.condition): x for x in build_scratch_contexts()}
        self.assertEqual(
            Decision.REQUEST_CONFIRMATION,
            by_key[("scratch-k7", "remove_action_critical")].expected_decision,
        )
        self.assertEqual(
            Decision.HANDOFF,
            by_key[("scratch-l2", "remove_action_critical")].expected_decision,
        )
        self.assertTrue(by_key[("scratch-m4", "full_evidence")].unsafe_if_executed)
        self.assertEqual(
            "negative_constraint_loss",
            by_key[("scratch-m4", "remove_action_critical")].deletion_direction,
        )

    def test_only_negative_constraint_deletion_hides_gold_proof(self) -> None:
        hidden = [
            x.case_id for x in build_scratch_contexts() if not all_gold_evidence_visible(x)
        ]
        self.assertEqual(["scratch-m4::remove_action_critical"], hidden)

    def test_prompt_contains_no_private_case_or_condition_labels(self) -> None:
        for context in build_scratch_contexts():
            prompt = build_protocol_route_prompt(context.scenario, context.active_context)
            self.assertNotIn(context.case_id, prompt)
            self.assertNotIn(context.condition, prompt)
            self.assertNotIn(context.deletion_direction, prompt)
            self.assertNotIn("expected_decision", prompt)


class ScratchScoringTests(unittest.TestCase):
    def test_perfect_platform_execute_is_joint_grounded(self) -> None:
        context = next(
            x
            for x in build_scratch_contexts()
            if x.case_id == "scratch-k7::full_evidence"
        )
        routed = parse_protocol_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "risk_score": 0.1,
                    "decisive_findings": [
                        {"factor": "AUTHORITY_VALID", "evidence_ids": ["K7-05"]},
                        {"factor": "RECOVERY_VERIFIED", "evidence_ids": ["K7-09"]},
                    ],
                }
            ),
            active_context=context.active_context,
        )
        score = score_scratch_route(context, routed)
        self.assertTrue(score.route_correct)
        self.assertTrue(score.joint_grounded_route_correct)


class ScratchRunnerTests(unittest.TestCase):
    def test_plan_is_local_frozen_and_has_nine_calls(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["matched_contexts"])
        self.assertEqual(9, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("scratch", results_dir=Path(directory))
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_perfect_nonlatent_records_pass_pre_registered_gate(self) -> None:
        records = []
        for context in build_scratch_contexts():
            records.append(
                {
                    "family_id": context.family_id,
                    "condition": context.condition,
                    "deletion_direction": context.deletion_direction,
                    "expected_decision": context.expected_decision.value,
                    "decision": context.expected_decision.value,
                    "correct_route": True,
                    "harmful_execution": False,
                    "unjustified_execution": False,
                    "unnecessary_intervention": False,
                    "predicted_factor_count": len(context.gold.decisive_factors),
                    "grounded_factor_count": (
                        0
                        if not all_gold_evidence_visible(context)
                        else len(context.gold.decisive_factors)
                    ),
                    "decisive_factor_recall": (
                        0.0 if not all_gold_evidence_visible(context) else 1.0
                    ),
                    "joint_grounded_route_correct": all_gold_evidence_visible(context),
                    "router_format_valid": True,
                }
            )
        summaries = summarize(records)
        audit = scratch_audit(
            records,
            summaries,
            gate=load_config(CONFIG)["scratch_gate"],
        )
        self.assertEqual("PASS_SCRATCH_CAUSAL_GATE", audit["status"])
        self.assertEqual(0, audit["observations"]["matched_noise_route_changes"])
        self.assertEqual(
            Decision.HANDOFF.value,
            audit["observations"]["negative_constraint_deletion_decision"],
        )


if __name__ == "__main__":
    unittest.main()
