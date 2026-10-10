from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.typed_budget_compaction import METHODS
from platform_agent_eval.typed_compaction_dev import build_typed_compaction_contexts
from run_typed_exact_budget_gate import (
    _gate,
    assert_paths_available,
    build_plan,
    exact_budget_audit,
    load_config,
    output_paths,
    summarize,
)


class TypedExactBudgetRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "typed_exact_budget_dev.json")

    def test_plan_is_local_zero_cost_and_freezes_call_counts(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual("local_machine", plan["location"])
        self.assertEqual(27, plan["matched_contexts"])
        self.assertEqual(270, plan["measured_generation_calls"])
        self.assertEqual(384, plan["budget_tokens"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("frozen", results_dir=Path(directory))
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_perfect_instrumentation_and_typed_method_pass_gate(self) -> None:
        records: list[dict[str, object]] = []
        for context in build_typed_compaction_contexts():
            active_ids = {event.event_id for event in context.active_events}
            for method in METHODS:
                budgeted = method != "full_context_ceiling"
                metrics = {
                    "route_correct": True,
                    "harmful_execution": False,
                    "unjustified_execution": False,
                    "unnecessary_intervention": False,
                    "safe_autonomous_completion": (
                        context.expected_decision is Decision.AUTO_EXECUTE
                    ),
                }
                records.append(
                    {
                        "case_id": context.case_id,
                        "family_id": context.family_id,
                        "condition": context.condition,
                        "method": method,
                        "expected_decision": context.expected_decision.value,
                        "exact_raw_tokens": 365 if budgeted else 700,
                        "budget_tokens": 384 if budgeted else None,
                        "budget_utilization": 365 / 384 if budgeted else None,
                        "budget_violation": False,
                        "blinded_label_leaks": [],
                        "source_integrity_valid": True,
                        "protected_fill_violation": False,
                        "compactor_format_valid": True,
                        "visible_card_recall": 1.0,
                        "critical_event_visible_before_compaction": (
                            context.critical_event_id in active_ids
                        ),
                        "critical_event_retained": (
                            True
                            if context.critical_event_id in active_ids
                            else None
                        ),
                        "direct": {
                            "decision": context.expected_decision.value,
                            "format_valid": True,
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            **metrics,
                        },
                        "audited": {
                            "decision": context.expected_decision.value,
                            **metrics,
                        },
                        "audit_helpful": False,
                        "audit_harmful": False,
                    }
                )
        summaries = summarize(records)
        audit = exact_budget_audit(
            records,
            summaries,
            budget_tokens=384,
            cache_requests=100,
            cache_hits=75,
            cache_misses=25,
            gate=_gate(self.config),
        )
        self.assertEqual(
            "PASS_TYPED_EXACT_BUDGET_DEVELOPMENT_GATE", audit["status"]
        )
        self.assertTrue(audit["instrumentation_passed"])
        self.assertTrue(audit["typed_method_passed"])


if __name__ == "__main__":
    unittest.main()
