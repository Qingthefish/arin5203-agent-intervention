from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.budgeted_compaction import (
    budgeted_generic_summary,
    budgeted_precise_pinning,
    budgeted_recent_window,
    budgeted_selective_audit,
    budgeted_ufold_lite,
)
from platform_agent_eval.compaction_scenarios import build_proposal_alignment_scenarios
from platform_agent_eval.model_routing import GenerationConfig, ModelResponse
from platform_agent_eval.token_budget import TokenCount
from run_fixed_budget_dev_pilot import (
    STRATEGIES,
    assert_paths_available,
    build_plan,
    load_config,
    output_paths,
    pipeline_audit,
    summarize,
)


class WordCounter:
    def count(self, text: str) -> TokenCount:
        return TokenCount(
            token_count=len(text.split()),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            latency_ms=0.0,
            model_id="fake-model",
        )


class FakeClient:
    def __init__(self, *, invalid: str | None = None) -> None:
        self.invalid = invalid

    def generate(self, prompt: str, _config: GenerationConfig) -> ModelResponse:
        if "-generic" in prompt:
            payload = (
                {"wrong": "schema"}
                if self.invalid == "generic"
                else {"summary": "Current goal with scoped authority and recovery."}
            )
        elif "-ufold-lite" in prompt:
            payload = (
                {
                    "intent_summary": "Current state change.",
                    "tool_log": [{"event_id": "INVISIBLE", "fact": "bad"}],
                }
                if self.invalid == "ufold"
                else {
                    "intent_summary": "Current state change.",
                    "tool_log": [
                        {"event_id": "PLAT1-U02", "fact": "Scoped approval exists."}
                    ],
                }
            )
        elif "-selective-audit" in prompt:
            payload = {
                "summary": "Pending state change.",
                "preserve_event_ids": ["PLAT1-U02"],
                "review_event_ids": [],
            }
        else:
            raise AssertionError("unexpected fake prompt")
        return ModelResponse(
            text=json.dumps(payload),
            prompt_tokens=10,
            completion_tokens=10,
            latency_ms=1.0,
            model_id="fake-model",
        )


class BudgetedCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = build_proposal_alignment_scenarios()[0]
        self.counter = WordCounter()
        self.generation = GenerationConfig(model="fake-model")

    def test_recent_and_precise_contexts_respect_budget_floor_and_cap(self) -> None:
        for function in (budgeted_recent_window, budgeted_precise_pinning):
            result = function(
                self.scenario,
                counter=self.counter,
                budget_tokens=120,
                minimum_utilization=0.9,
            )
            self.assertLessEqual(result.exact_raw_tokens, 120)
            self.assertGreaterEqual(result.exact_raw_tokens, 108)

    def test_precise_pinning_keeps_operator_boundary_record(self) -> None:
        scenario = next(
            item
            for item in build_proposal_alignment_scenarios()
            if item.scenario_id == "align-mas-boundary-handoff"
        )
        result = budgeted_precise_pinning(
            scenario,
            counter=self.counter,
            budget_tokens=120,
            minimum_utilization=0.9,
        )
        self.assertIn("MAS2-T02", result.retained_event_ids)
        self.assertIn("operator-only", result.text)

    def test_valid_generative_compactors_are_budget_matched(self) -> None:
        functions = (
            budgeted_generic_summary,
            budgeted_ufold_lite,
            budgeted_selective_audit,
        )
        for function in functions:
            result = function(
                self.scenario,
                client=FakeClient(),
                config=self.generation,
                counter=self.counter,
                budget_tokens=120,
                minimum_utilization=0.9,
            )
            self.assertTrue(result.format_valid)
            self.assertLessEqual(result.exact_raw_tokens, 120)
            self.assertGreaterEqual(result.exact_raw_tokens, 108)

    def test_invalid_ufold_citation_is_visible_and_falls_back(self) -> None:
        result = budgeted_ufold_lite(
            self.scenario,
            client=FakeClient(invalid="ufold"),
            config=self.generation,
            counter=self.counter,
            budget_tokens=120,
            minimum_utilization=0.9,
        )
        self.assertFalse(result.format_valid)
        self.assertIn("invalid", result.text)

    def test_selective_audit_requests_do_not_inject_human_answers(self) -> None:
        result = budgeted_selective_audit(
            self.scenario,
            client=FakeClient(),
            config=self.generation,
            counter=self.counter,
            budget_tokens=120,
            minimum_utilization=0.9,
        )
        self.assertNotIn("HUMAN-REVIEW", result.text)


class FixedBudgetRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "fixed_budget_dev_pilot.json")

    def test_plan_is_local_and_has_exact_call_counts(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_OR_TOKENIZER_CALLS", plan["status"])
        self.assertEqual(54, plan["measured_generation_calls"])
        self.assertEqual(18, plan["compactor_generation_calls"])
        self.assertEqual(36, plan["routing_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("trial", results_dir=Path(directory))
            assert_paths_available(paths)
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def perfect_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for scenario in build_proposal_alignment_scenarios():
            for strategy in STRATEGIES:
                budgeted = strategy != "full_context_ceiling"
                records.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "strategy": strategy,
                        "correct_route": True,
                        "harmful_execution": False,
                        "autonomous_execution": scenario.expected_decision.value
                        == "AUTO_EXECUTE",
                        "unnecessary_intervention": False,
                        "critical_markers_retained": len(scenario.critical_markers),
                        "critical_markers_total": len(scenario.critical_markers),
                        "exact_raw_tokens": 250 if budgeted else 720,
                        "budget_utilization": 250 / 256 if budgeted else None,
                        "context_reduction": 1 - (250 if budgeted else 720) / 720,
                        "review_event_ids": [],
                        "compactor_format_valid": True,
                        "router_format_valid": True,
                        "model_calls": 1,
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "latency_ms": 1.0,
                    }
                )
        return records

    def test_perfect_budget_records_pass_pipeline_gate(self) -> None:
        records = self.perfect_records()
        summaries = summarize(records)
        audit = pipeline_audit(
            records,
            summaries,
            budget_tokens=256,
            minimum_utilization=0.9,
            gate=build_plan(self.config)["pipeline_gate"],
        )
        self.assertEqual("PASS_FIXED_BUDGET_PIPELINE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))

    def test_budget_violation_fails_pipeline_gate(self) -> None:
        records = self.perfect_records()
        records[1]["exact_raw_tokens"] = 257
        records[1]["budget_utilization"] = 257 / 256
        summaries = summarize(records)
        audit = pipeline_audit(
            records,
            summaries,
            budget_tokens=256,
            minimum_utilization=0.9,
            gate=build_plan(self.config)["pipeline_gate"],
        )
        self.assertEqual("REVISE_FIXED_BUDGET_PIPELINE", audit["status"])
        self.assertFalse(
            audit["pre_specified_gate"]["budget_violations_within_limit"]
        )


if __name__ == "__main__":
    unittest.main()
