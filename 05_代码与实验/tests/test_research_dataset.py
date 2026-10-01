from __future__ import annotations

import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.approvals import missing_requirements
from platform_agent_eval.baselines import build_baseline_predictions
from platform_agent_eval.dataset_audit import audit_scenario_set
from platform_agent_eval.domain import Decision
from platform_agent_eval.intervention import counterfactual_targets, resolve_after_confirmation
from platform_agent_eval.domain import RouterResult
from platform_agent_eval.research_scenarios import build_research_scenarios
from platform_agent_eval.research_pipeline import (
    ABLATION_EXCLUSIONS,
    ablate_prepared_cases,
    fit_three_way_policy,
    hard_guard_predictions,
    predict_prepared,
    prepare_cases,
)
from platform_agent_eval.research_metrics import (
    grouped_bootstrap_intervals,
    summarize_predictions,
)
from platform_agent_eval.scenarios import stratified_grouped_split, validate_scenario_set


class ResearchDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_research_scenarios()

    def test_candidate_has_declared_size_balance_and_valid_labels(self) -> None:
        validate_scenario_set(self.scenarios)
        self.assertEqual(120, len(self.scenarios))
        self.assertEqual(40, len({case.gold.base_task_id for case in self.scenarios}))
        self.assertEqual(
            {operation: 24 for operation in {
                "CHANGE_GPU_QUOTA",
                "PREEMPT_WORKLOAD",
                "TRANSFER_RESOURCE",
                "ROLLOUT_MODEL",
                "RECLAIM_CAPACITY",
            }},
            dict(Counter(case.policy_input.operation.value for case in self.scenarios)),
        )
        self.assertEqual(
            {
                "AUTO_EXECUTE": 40,
                "REQUEST_CONFIRMATION": 40,
                "HANDOFF": 22,
                "BLOCK": 18,
            },
            dict(Counter(case.gold.expected_decision.value for case in self.scenarios)),
        )

    def test_operation_stratified_split_is_grouped_and_balanced(self) -> None:
        splits = stratified_grouped_split(self.scenarios, seed=5203)
        family_splits = defaultdict(set)
        operation_split_counts = defaultdict(Counter)
        for case in self.scenarios:
            split = splits[case.gold.scenario_id]
            family_splits[case.gold.base_task_id].add(split)
            operation_split_counts[case.policy_input.operation.value][split] += 1
        self.assertTrue(all(len(items) == 1 for items in family_splits.values()))
        self.assertTrue(
            all(
                counts == {"train": 12, "dev": 6, "test": 6}
                for counts in operation_split_counts.values()
            )
        )

    def test_cross_tenant_requirements_cover_every_affected_owner(self) -> None:
        for case in self.scenarios:
            if not case.policy_input.cross_tenant:
                continue
            expected = {case.policy_input.resource_owner}
            expected.update(
                tenant
                for tenant in case.policy_input.affected_tenants
                if tenant != "platform"
            )
            actual = {
                requirement.resource_owner_scope
                for requirement in case.oracle.approval_requirements
            }
            self.assertTrue(expected.issubset(actual), case.gold.scenario_id)

    def test_execute_evidence_is_complete_and_confirm_evidence_is_not(self) -> None:
        for case in self.scenarios:
            evidence = case.policy_input.approval_evidence or ()
            missing = missing_requirements(evidence, case.oracle.approval_requirements)
            if case.gold.expected_decision is Decision.AUTO_EXECUTE:
                self.assertEqual((), missing, case.gold.scenario_id)
            elif case.gold.expected_decision is Decision.REQUEST_CONFIRMATION:
                self.assertTrue(missing, case.gold.scenario_id)

    def test_confirmation_resolves_and_handoff_retains_residual_hazard(self) -> None:
        for case in self.scenarios:
            resolution = resolve_after_confirmation(case)
            if case.gold.expected_decision is Decision.REQUEST_CONFIRMATION:
                self.assertTrue(resolution.resolved, case.gold.scenario_id)
            elif case.gold.expected_decision is Decision.HANDOFF:
                self.assertFalse(resolution.resolved, case.gold.scenario_id)
                self.assertTrue(resolution.outcome.prohibited_attempt)

    def test_counterfactual_targets_match_rules_without_reading_gold(self) -> None:
        for case in self.scenarios:
            targets = counterfactual_targets(case)
            expected = case.gold.expected_decision
            self.assertEqual(expected is Decision.BLOCK, targets.hard_block)
            self.assertEqual(
                expected in {
                    Decision.REQUEST_CONFIRMATION,
                    Decision.HANDOFF,
                    Decision.BLOCK,
                },
                targets.unsafe_if_executed,
            )
            self.assertEqual(
                expected is Decision.REQUEST_CONFIRMATION,
                targets.resolvable_by_confirmation,
            )

    def test_train_dev_calibration_pipeline_never_requires_test_for_fitting(self) -> None:
        splits = stratified_grouped_split(self.scenarios, seed=5203)
        samples = {}
        for case in self.scenarios:
            if case.gold.expected_decision is Decision.BLOCK:
                continue
            unsafe = case.gold.expected_decision is not Decision.AUTO_EXECUTE
            resolvable = case.gold.expected_decision is Decision.REQUEST_CONFIRMATION
            decision = (
                Decision.AUTO_EXECUTE
                if not unsafe
                else Decision.REQUEST_CONFIRMATION
                if resolvable
                else Decision.HANDOFF
            )
            base_risk = 0.85 if unsafe else 0.15
            samples[case.gold.scenario_id] = [
                RouterResult(
                    decision=decision,
                    decision_source="fake",
                    risk_score=base_risk + offset,
                    reason_codes=("synthetic_test_signal",),
                )
                for offset in (-0.05, 0.0, 0.05)
            ]
        prepared = prepare_cases(self.scenarios, samples, splits)
        no_test = [item for item in prepared if item.split != "test"]
        policy = fit_three_way_policy(no_test)
        test_predictions = predict_prepared(
            policy,
            [item for item in prepared if item.split == "test"],
        )
        guarded = hard_guard_predictions(self.scenarios, splits)
        self.assertEqual(25, len(test_predictions))
        self.assertEqual(18, len(guarded))
        self.assertTrue(all(item.split == "test" for item in test_predictions))
        baselines, thresholds = build_baseline_predictions(
            self.scenarios,
            samples,
            splits,
        )
        self.assertEqual(
            {
                "ungated_autonomy",
                "guarded_always_execute",
                "verify_every_mutation",
                "static_tool_tiers",
                "single_prompt_critic",
                "majority_vote_critic",
                "verbalized_confidence",
            },
            set(baselines),
        )
        self.assertTrue(all(len(rows) == 120 for rows in baselines.values()))
        self.assertIn("verbalized_confidence_execute_below", thresholds)
        for excluded in ABLATION_EXCLUSIONS.values():
            ablated = ablate_prepared_cases(no_test, excluded_features=excluded)
            self.assertTrue(
                set(excluded).isdisjoint(ablated[0].features)
            )
            fit_three_way_policy(ablated)
        critic_only = ablate_prepared_cases(
            no_test,
            keep_prefixes=("critic_",),
        )
        self.assertTrue(
            all(name.startswith("critic_") for name in critic_only[0].features)
        )
        fit_three_way_policy(critic_only)
        all_predictions = [*test_predictions, *guarded]
        summary = summarize_predictions(
            self.scenarios,
            all_predictions,
            split="test",
        )
        self.assertEqual(30, summary["cases"])
        self.assertIn("authorized_task_completion_rate", summary)
        self.assertIn("aurc", summary)
        intervals = grouped_bootstrap_intervals(
            self.scenarios,
            all_predictions,
            split="test",
            samples=20,
            seed=1,
        )
        self.assertIn("unsafe_execution_rate", intervals)
        self.assertLessEqual(
            intervals["unsafe_execution_rate"]["ci95_low"],
            intervals["unsafe_execution_rate"]["estimate"],
        )
        self.assertGreaterEqual(
            intervals["unsafe_execution_rate"]["ci95_high"],
            intervals["unsafe_execution_rate"]["estimate"],
        )

        one_family = next(
            case.gold.base_task_id
            for case in self.scenarios
            if case.gold.scenario_id in {item.scenario_id for item in all_predictions}
            and next(
                item.split
                for item in all_predictions
                if item.scenario_id == case.gold.scenario_id
            )
            == "test"
        )
        one_family_cases = [
            case for case in self.scenarios if case.gold.base_task_id == one_family
        ]
        one_family_ids = {case.gold.scenario_id for case in one_family_cases}
        one_family_predictions = [
            item for item in all_predictions if item.scenario_id in one_family_ids
        ]
        with self.assertRaisesRegex(ValueError, "at least two independent task families"):
            grouped_bootstrap_intervals(
                one_family_cases,
                one_family_predictions,
                split="test",
                samples=20,
                seed=1,
            )

    def test_full_dataset_passes_semantic_approval_and_prompt_audit(self) -> None:
        audit = audit_scenario_set(self.scenarios)
        self.assertEqual((), audit.errors)
        self.assertEqual((), audit.constant_features)
        self.assertEqual(120, audit.cases)
        self.assertEqual(40, audit.families)


if __name__ == "__main__":
    unittest.main()
