from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.typed_budget_compaction import BUDGETED_METHODS
from platform_agent_eval.typed_compaction_dev import build_typed_compaction_contexts
from run_typed_budget_sweep import (
    _source_record_map,
    budget_sweep_audit,
    build_plan,
    load_config,
    load_source_records,
    replay_draft,
)


class TypedBudgetSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "typed_budget_sweep_dev.json")

    def test_plan_reuses_compactors_and_freezes_new_route_count(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual([256, 192], plan["sweep_budget_tokens"])
        self.assertEqual(324, plan["measured_generation_calls"])
        self.assertEqual(0, plan["planning_estimates"]["compactor_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_frozen_generative_outputs_reparse_with_visible_sources(self) -> None:
        records, _, _ = load_source_records(self.config)
        by_key = _source_record_map(records)
        context = build_typed_compaction_contexts()[0]
        for method in ("neutral_summary", "task_aware_summary", "ufold_lite"):
            draft = replay_draft(context, method, by_key[(context.case_id, method)])
            self.assertTrue(draft.format_valid)
            self.assertTrue(draft.summary)
            self.assertTrue(draft.source_event_ids)

    def test_protocol_gate_does_not_require_method_success(self) -> None:
        contexts = build_typed_compaction_contexts()
        records: list[dict[str, object]] = []
        for budget in (256, 192):
            for context in contexts:
                for method in BUDGETED_METHODS:
                    records.append(
                        {
                            "sweep_budget_tokens": budget,
                            "case_id": context.case_id,
                            "method": method,
                            "budget_utilization": 0.95,
                            "budget_violation": False,
                            "blinded_label_leaks": [],
                            "source_integrity_valid": True,
                            "protected_fill_violation": False,
                            "compactor_format_valid": True,
                            "direct": {"format_valid": True},
                        }
                    )
        audit = budget_sweep_audit(
            records,
            contexts=contexts,
            budgets=(256, 192),
            source_replay_mismatches=[],
            cache_requests=100,
            cache_hits=50,
            cache_misses=50,
            gate=self.config["protocol_gate"],
        )
        self.assertEqual("PASS_TYPED_BUDGET_SWEEP_PROTOCOL_GATE", audit["status"])
        self.assertNotIn("typed_method_passed", audit)


if __name__ == "__main__":
    unittest.main()
