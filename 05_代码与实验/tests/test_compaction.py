from __future__ import annotations

import unittest

from platform_agent_eval.compaction import (
    critical_retention,
    effective_oracle,
    full_context,
    rule_pinning,
    tail_truncation,
)
from platform_agent_eval.compaction_scenarios import build_compaction_pilot_scenarios
from platform_agent_eval.domain import Decision


class CompactionScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_compaction_pilot_scenarios()

    def test_pilot_has_five_cases_and_all_three_routes(self) -> None:
        self.assertEqual(len(self.scenarios), 5)
        self.assertEqual(
            {scenario.expected_decision for scenario in self.scenarios},
            {
                Decision.AUTO_EXECUTE,
                Decision.REQUEST_CONFIRMATION,
                Decision.HANDOFF,
            },
        )

    def test_full_context_retains_every_critical_marker(self) -> None:
        for scenario in self.scenarios:
            retained, total = critical_retention(scenario, full_context(scenario).text)
            self.assertEqual(retained, total)

    def test_tail_truncation_removes_at_least_one_old_critical_fact(self) -> None:
        lost = 0
        for scenario in self.scenarios:
            retained, total = critical_retention(
                scenario,
                tail_truncation(scenario, keep_last_events=4).text,
            )
            lost += total - retained
        self.assertGreater(lost, 0)

    def test_rule_pinning_is_deterministic_and_preserves_explicit_rules(self) -> None:
        for scenario in self.scenarios:
            first = rule_pinning(scenario, keep_last_events=4)
            second = rule_pinning(scenario, keep_last_events=4)
            self.assertEqual(first, second)
            retained, total = critical_retention(scenario, first.text)
            self.assertEqual(retained, total)

    def test_human_answer_changes_only_the_ambiguous_oracle(self) -> None:
        rollout = next(
            scenario
            for scenario in self.scenarios
            if scenario.scenario_id == "compact-rollout-ambiguous"
        )
        no_review = rule_pinning(rollout)
        self.assertEqual(
            effective_oracle(rollout, no_review),
            (Decision.REQUEST_CONFIRMATION, True),
        )
        reviewed = type(no_review)(
            strategy="selective_hitl",
            text=no_review.text,
            human_answers=(rollout.review_answers[0][1],),
        )
        self.assertEqual(
            effective_oracle(rollout, reviewed),
            (Decision.AUTO_EXECUTE, False),
        )


if __name__ == "__main__":
    unittest.main()
