from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.typed_budget_compaction import METHODS
from platform_agent_eval.typed_compaction_heldout import (
    build_typed_compaction_heldout_contexts,
    build_typed_compaction_heldout_families,
)
from run_typed_exact_budget_gate import (
    _gate,
    build_plan,
    exact_budget_audit,
    load_config,
    summarize,
)


DEV_CONFIG = ROOT / "configs" / "typed_exact_budget_dev.json"
HELDOUT_CONFIG = ROOT / "configs" / "typed_exact_budget_heldout.json"
HELDOUT_DATASET_MANIFEST = ROOT / "results" / "typed_compaction_heldout_v1_manifest.json"


class TypedExactBudgetHeldoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dev_config = load_config(DEV_CONFIG)
        self.heldout_config = load_config(HELDOUT_CONFIG)

    def test_plan_uses_frozen_heldout_set_and_call_counts(self) -> None:
        plan = build_plan(self.heldout_config)
        frozen_manifest = json.loads(HELDOUT_DATASET_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual("heldout", plan["evaluation_phase"])
        self.assertEqual(11, plan["base_families"])
        self.assertEqual(33, plan["matched_contexts"])
        self.assertEqual(99, plan["planning_estimates"]["compactor_generation_calls"])
        self.assertEqual(231, plan["planning_estimates"]["routing_generation_calls"])
        self.assertEqual(330, plan["measured_generation_calls"])
        self.assertEqual(384, plan["budget_tokens"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])
        self.assertEqual(frozen_manifest["dataset_sha256"], plan["dataset_sha256"])

    def test_method_prompt_budget_seed_and_thresholds_equal_v6(self) -> None:
        frozen_fields = (
            "compaction_version",
            "router_version",
            "provider",
            "model",
            "temperature",
            "seed",
            "budget_tokens",
            "minimum_utilization",
            "compactor_max_tokens",
            "router_max_tokens",
        )
        for field in frozen_fields:
            self.assertEqual(
                self.dev_config[field],
                self.heldout_config[field],
                field,
            )
        self.assertEqual(
            self.dev_config["development_gate"],
            self.heldout_config["heldout_gate"],
        )

    def test_perfect_heldout_records_pass_heldout_gate(self) -> None:
        contexts = build_typed_compaction_heldout_contexts()
        families = build_typed_compaction_heldout_families()
        records: list[dict[str, object]] = []
        for context in contexts:
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
                            True if context.critical_event_id in active_ids else None
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
            cache_requests=120,
            cache_hits=80,
            cache_misses=40,
            gate=_gate(self.heldout_config),
            contexts=contexts,
            families=families,
            evaluation_phase="heldout",
        )
        self.assertEqual("PASS_TYPED_EXACT_BUDGET_HELDOUT_GATE", audit["status"])
        self.assertTrue(audit["instrumentation_passed"])
        self.assertTrue(audit["typed_method_passed"])
        self.assertEqual(
            "FINALIZE_RESULTS_AND_BUILD_DETERMINISTIC_REPLAY",
            audit["recommendation"],
        )


if __name__ == "__main__":
    unittest.main()
