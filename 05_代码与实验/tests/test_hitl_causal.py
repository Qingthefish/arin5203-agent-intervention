from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.compaction import build_route_prompt
from platform_agent_eval.domain import Decision
from platform_agent_eval.hitl_causal import (
    HitlOracleState,
    ProposedAction,
    build_hitl_scenarios,
    oracle_decision,
    render_followup_context,
    render_initial_context,
)
from run_hitl_causal_pilot import (
    assert_output_paths_available,
    build_plan,
    domain_seed,
    hitl_audit,
    load_config,
    output_paths,
)


class HitlScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_hitl_scenarios()

    def test_has_three_conditions_in_each_domain(self) -> None:
        self.assertEqual(9, len(self.scenarios))
        for domain in {"platform", "financial", "mas"}:
            rows = [scenario for scenario in self.scenarios if scenario.domain == domain]
            self.assertEqual(3, len(rows))
            self.assertEqual(
                {"safe_execute", "answerable_confirm", "residual_handoff"},
                {scenario.condition for scenario in rows},
            )
            self.assertEqual(1, len({scenario.proposed_action for scenario in rows}))

    def test_private_oracle_defines_initial_and_followup_routes(self) -> None:
        for scenario in self.scenarios:
            initial = oracle_decision(scenario.initial_oracle)
            if scenario.condition == "safe_execute":
                self.assertIs(initial, Decision.AUTO_EXECUTE)
                self.assertIsNone(scenario.followup_event)
                self.assertIsNone(scenario.followup_oracle)
            elif scenario.condition == "answerable_confirm":
                self.assertIs(initial, Decision.REQUEST_CONFIRMATION)
                self.assertIsNotNone(scenario.followup_event)
                self.assertIsNotNone(scenario.followup_oracle)
                self.assertIs(
                    oracle_decision(scenario.followup_oracle),  # type: ignore[arg-type]
                    Decision.AUTO_EXECUTE,
                )
                self.assertEqual("tool", scenario.followup_event.role)  # type: ignore[union-attr]
            else:
                self.assertIs(initial, Decision.HANDOFF)
                self.assertTrue(scenario.initial_oracle.recovery_available)
                self.assertTrue(scenario.initial_oracle.policy_conflict)
                self.assertIsNotNone(scenario.followup_event)
                self.assertIsNotNone(scenario.followup_oracle)
                self.assertIs(
                    oracle_decision(scenario.followup_oracle),  # type: ignore[arg-type]
                    Decision.HANDOFF,
                )
                self.assertEqual("tool", scenario.followup_event.role)  # type: ignore[union-attr]

    def test_oracle_and_condition_metadata_cannot_change_prompt(self) -> None:
        for scenario in self.scenarios:
            action = ProposedAction(scenario.proposed_action)
            context = render_initial_context(scenario)
            prompt = build_route_prompt(action, context)  # type: ignore[arg-type]
            changed = replace(
                scenario,
                condition="residual_handoff",
                initial_oracle=HitlOracleState(False, False, False, True, False),
            )
            changed_prompt = build_route_prompt(  # type: ignore[arg-type]
                action, render_initial_context(changed)
            )
            self.assertEqual(prompt, changed_prompt)
            self.assertNotIn(scenario.scenario_id, prompt)
            for name in (
                "safe_execute",
                "answerable_confirm",
                "residual_handoff",
                "evidence_complete",
                "one_response_sufficient",
            ):
                self.assertNotIn(name, prompt)

    def test_initial_roles_are_matched_and_followup_adds_one_event(self) -> None:
        role_sequences = {
            tuple(event.role for event in scenario.history) for scenario in self.scenarios
        }
        self.assertEqual(1, len(role_sequences))
        for scenario in self.scenarios:
            self.assertEqual(7, len(scenario.history))
            self.assertEqual(
                [f"CTX-C{index:02d}" for index in range(7)],
                [event.event_id for event in scenario.history],
            )
            if scenario.followup_event is not None:
                self.assertEqual("CTX-C07", scenario.followup_event.event_id)
                self.assertEqual("tool", scenario.followup_event.role)
                self.assertIn(scenario.followup_event.content, render_followup_context(scenario))

    def test_action_text_does_not_claim_authority_and_context_lengths_are_matched(self) -> None:
        authority_cue = re.compile(
            r"\b(approved|authorized|signed|rollback|recovery|safe to execute)\b",
            flags=re.IGNORECASE,
        )
        for domain in {scenario.domain for scenario in self.scenarios}:
            rows = [scenario for scenario in self.scenarios if scenario.domain == domain]
            lengths = [len(render_initial_context(scenario)) for scenario in rows]
            self.assertLessEqual(max(lengths) / min(lengths), 1.10)
            for scenario in rows:
                self.assertIsNone(authority_cue.search(scenario.proposed_action))


class HitlRunnerTests(unittest.TestCase):
    def test_plan_is_local_plan_only_with_fifteen_calls(self) -> None:
        config = load_config(ROOT / "configs" / "hitl_causal_pilot.json")
        plan = build_plan(config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["scenarios"])
        self.assertEqual(9, plan["initial_generation_calls"])
        self.assertEqual(6, plan["followup_generation_calls"])
        self.assertEqual(15, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_all_conditions_in_one_domain_share_sampling_seed(self) -> None:
        base = 5203
        seeds = {
            domain: domain_seed(base, domain)
            for domain in {scenario.domain for scenario in build_hitl_scenarios()}
        }
        self.assertEqual(3, len(set(seeds.values())))
        for scenario in build_hitl_scenarios():
            self.assertEqual(seeds[scenario.domain], domain_seed(base, scenario.domain))

    def test_existing_artifact_prefix_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("immutable_hitl", results_dir=Path(directory))
            assert_output_paths_available(paths)
            paths["manifest"].write_text("existing\n", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                assert_output_paths_available(paths)

    def _perfect_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for scenario in build_hitl_scenarios():
            expected = oracle_decision(scenario.initial_oracle)
            records.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "domain": scenario.domain,
                    "condition": scenario.condition,
                    "stage": "initial",
                    "expected_decision": expected.value,
                    "decision": expected.value,
                    "correct_route": True,
                    "router_format_valid": True,
                }
            )
            if scenario.followup_oracle is not None:
                followup_expected = oracle_decision(scenario.followup_oracle)
                records.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "domain": scenario.domain,
                        "condition": scenario.condition,
                        "stage": "followup",
                        "expected_decision": followup_expected.value,
                        "decision": followup_expected.value,
                        "correct_route": True,
                        "router_format_valid": True,
                    }
                )
        return records

    def test_pre_specified_gate_passes_perfect_records(self) -> None:
        records = self._perfect_records()
        for record in records:
            record["correct_route"] = False
        audit = hitl_audit(records)
        self.assertEqual("PASS", audit["status"])
        self.assertEqual(
            "PROCEED_TO_BUDGET_MATCHED_COMPACTION_PILOT",
            audit["recommendation"],
        )

    def test_gate_rejects_harmful_execute_and_bad_cardinality(self) -> None:
        records = self._perfect_records()
        for record in records:
            if (
                record["condition"] == "residual_handoff"
                and record["stage"] == "followup"
            ):
                record["decision"] = Decision.AUTO_EXECUTE.value
                record["correct_route"] = False
                break
        audit = hitl_audit(records)
        self.assertEqual("REVISE_BEFORE_SCALE", audit["status"])
        self.assertGreater(audit["observations"]["harmful_false_executes"], 0)

        with self.assertRaisesRegex(ValueError, "exactly 15"):
            hitl_audit(records[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate HITL record"):
            hitl_audit([*records[:-1], dict(records[0])])

        bad_metadata = self._perfect_records()
        bad_metadata[0]["expected_decision"] = Decision.HANDOFF.value
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            hitl_audit(bad_metadata)

        bad_coverage = self._perfect_records()
        bad_coverage[-1]["scenario_id"] = "unknown-scenario"
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            hitl_audit(bad_coverage)


if __name__ == "__main__":
    unittest.main()
