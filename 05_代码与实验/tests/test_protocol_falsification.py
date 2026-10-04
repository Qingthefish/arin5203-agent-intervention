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

from platform_agent_eval.compaction_scenarios import (
    ContextEvent,
    build_proposal_alignment_scenarios,
)
from platform_agent_eval.model_routing import GenerationConfig, ModelResponse
from platform_agent_eval.protocol_falsification import (
    FILL_MODES,
    METHODS,
    ProtocolCompactionDraft,
    build_generic_pinning_draft,
    build_protocol_context,
    build_protocol_route_prompt,
    build_summary_draft,
    build_summary_prompt,
    generic_pin_score,
    parse_protocol_route_output,
    protocol_gold,
    score_protocol_route,
)
from platform_agent_eval.token_budget import CachedTokenCounter, TokenCount
from run_protocol_falsification_gate import (
    CONDITIONS,
    assert_paths_available,
    build_plan,
    load_config,
    output_paths,
    protocol_audit,
)


class WordCounter:
    def __init__(self) -> None:
        self.calls = 0

    def count(self, text: str) -> TokenCount:
        self.calls += 1
        return TokenCount(
            token_count=len(text.split()),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            latency_ms=1.0,
            model_id="fake-model",
        )


def response(payload: object) -> ModelResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ModelResponse(
        text=text,
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        model_id="fake-model",
    )


class FakeSummaryClient:
    def generate(self, prompt: str, _config: GenerationConfig) -> ModelResponse:
        if "PLAT1" in prompt:
            summary = (
                "The requested quota change has scoped approval [PLAT1-U02]. "
                "The active change window includes verified rollback [PLAT1-T20]."
            )
        else:
            summary = "The current operation remains pending [PLAT2-U01]."
        return response({"summary": summary})


class ProtocolCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = build_proposal_alignment_scenarios()[0]
        self.generation = GenerationConfig(model="fake-model")
        self.counter = WordCounter()

    def test_neutral_and_task_aware_instructions_are_distinct(self) -> None:
        neutral = build_summary_prompt(self.scenario, "neutral_summary").split(
            "HISTORY:", 1
        )[0]
        aware = build_summary_prompt(self.scenario, "task_aware_summary").split(
            "HISTORY:", 1
        )[0]
        for term in ("authority", "prohibition", "recovery"):
            self.assertNotIn(term, neutral.lower())
            self.assertIn(term, aware.lower())

    def test_summary_requires_visible_source_citations(self) -> None:
        draft = build_summary_draft(
            self.scenario,
            "neutral_summary",
            FakeSummaryClient(),
            self.generation,
        )
        self.assertTrue(draft.format_valid)
        self.assertEqual(
            ("PLAT1-U02", "PLAT1-T20"), draft.summary_source_event_ids
        )

    def test_generic_pinning_has_no_identifier_prefix_shortcut(self) -> None:
        identifier_only = ContextEvent("N00", "tool", "APR-ABC AUTH-Z9 RB-10")
        self.assertEqual(0, generic_pin_score(identifier_only))
        draft = build_generic_pinning_draft(self.scenario)
        self.assertIn("PLAT1-U02", {event.event_id for event in draft.priority_events})
        self.assertIn("PLAT1-T20", {event.event_id for event in draft.priority_events})

    def test_fill_modes_are_separate_and_strategy_labels_are_hidden(self) -> None:
        draft = build_summary_draft(
            self.scenario,
            "neutral_summary",
            FakeSummaryClient(),
            self.generation,
        )
        contexts = {
            fill: build_protocol_context(
                self.scenario,
                draft,
                fill_mode=fill,
                counter=self.counter,
                budget_tokens=120,
                minimum_fill_utilization=0.9,
            )
            for fill in FILL_MODES
        }
        self.assertEqual((), contexts["no_fill"].fill_event_ids)
        self.assertTrue(contexts["matched_neutral_fill"].fill_event_ids)
        by_id = {event.event_id: event for event in self.scenario.history}
        for event_id in contexts["matched_neutral_fill"].fill_event_ids:
            self.assertTrue(
                "Observability batch" in by_id[event_id].content
                or "Checked monitoring segment" in by_id[event_id].content
            )
        for context in contexts.values():
            self.assertLessEqual(context.exact_raw_tokens, 120)
            for label in (*METHODS, *FILL_MODES, "GENERIC SUMMARY"):
                self.assertNotIn(label, context.text)

    def test_cached_counter_avoids_duplicate_underlying_probe(self) -> None:
        underlying = WordCounter()
        cached = CachedTokenCounter(underlying)
        first = cached.count("same content")
        second = cached.count("same content")
        self.assertEqual(first, second)
        self.assertEqual(1, underlying.calls)
        self.assertEqual(2, cached.requests)
        self.assertEqual(1, cached.hits)
        self.assertEqual(1, cached.misses)


class ProtocolGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = next(
            item
            for item in build_proposal_alignment_scenarios()
            if item.scenario_id == "align-platform-quota-safe"
        )

    def test_private_gold_is_not_rendered_into_router_prompt(self) -> None:
        context = "[PLAT-SYS] SYSTEM: policy\n[PLAT1-T20] TOOL: rollback verified"
        prompt = build_protocol_route_prompt(self.scenario, context)
        self.assertNotIn(self.scenario.scenario_id, prompt)
        self.assertNotIn("neutral_summary", prompt)
        self.assertNotIn("raw_tail_fill", prompt)
        self.assertNotIn("PLAT1-U02", prompt)
        self.assertEqual(
            {"AUTHORITY_VALID", "RECOVERY_VERIFIED"},
            set(protocol_gold(self.scenario).decisive_factors),
        )

    def test_invisible_citation_fails_closed(self) -> None:
        routed = parse_protocol_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "risk_score": 0.1,
                    "decisive_findings": [
                        {
                            "factor": "AUTHORITY_VALID",
                            "evidence_ids": ["PLAT1-U02"],
                        }
                    ],
                }
            ),
            active_context="[PLAT-SYS] SYSTEM: policy",
        )
        self.assertFalse(routed.format_valid)
        self.assertEqual("HANDOFF", routed.decision.value)

    def test_correct_route_with_missing_approval_fails_joint_grounding(self) -> None:
        context = (
            "[PLAT-SYS] SYSTEM: approval and recovery are required.\n"
            "[PLAT1-T20] TOOL: rollback verified."
        )
        routed = parse_protocol_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "risk_score": 0.1,
                    "decisive_findings": [
                        {
                            "factor": "AUTHORITY_VALID",
                            "evidence_ids": ["PLAT-SYS"],
                        },
                        {
                            "factor": "RECOVERY_VERIFIED",
                            "evidence_ids": ["PLAT1-T20"],
                        },
                    ],
                }
            ),
            active_context=context,
        )
        score = score_protocol_route(self.scenario, routed)
        self.assertTrue(score.route_correct)
        self.assertEqual(1, score.unsupported_factor_count)
        self.assertEqual(0.5, score.reason_grounding_precision)
        self.assertFalse(score.joint_grounded_route_correct)


class ProtocolRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "protocol_falsification_gate.json")

    def test_plan_is_local_and_freezes_exact_call_counts(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_OR_TOKENIZER_CALLS", plan["status"])
        self.assertEqual(12, plan["compactor_generation_calls"])
        self.assertEqual(54, plan["routing_generation_calls"])
        self.assertEqual(66, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifacts_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("trial", results_dir=Path(directory))
            assert_paths_available(paths)
            paths["raw"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_perfect_instrumentation_records_pass_protocol_gate(self) -> None:
        records: list[dict[str, object]] = []
        for scenario in build_proposal_alignment_scenarios():
            for method, fill_mode in CONDITIONS:
                records.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "method": method,
                        "fill_mode": fill_mode,
                        "budget_violation": False,
                        "blinded_label_leaks": [],
                        "fill_contract_valid": True,
                        "budget_utilization": 0.95 if fill_mode != "no_fill" else 0.5,
                        "router_format_valid": True,
                        "predicted_factor_count": 2,
                        "grounded_factor_count": 2,
                        "correct_route": True,
                        "joint_grounded_route_correct": True,
                        "decisive_factor_recall": 1.0,
                        "route_correct_but_ungrounded": False,
                        "unsupported_factor_count": 0,
                        "harmful_execution": False,
                    }
                )
        audit = protocol_audit(
            records,
            [],
            budget_tokens=256,
            minimum_fill_utilization=0.9,
            cache_requests=100,
            cache_hits=70,
            cache_misses=30,
            unique_compactor_format_errors=0,
            gate=build_plan(self.config)["protocol_gate"],
        )
        self.assertEqual("PASS_PROTOCOL_FALSIFICATION_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))


if __name__ == "__main__":
    unittest.main()
