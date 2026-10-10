from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.model_routing import ModelResponse
from platform_agent_eval.typed_budget_compaction import full_context
from platform_agent_eval.typed_compaction_dev import build_typed_compaction_contexts
from platform_agent_eval.typed_compaction_routing import (
    build_typed_route_prompt,
    parse_typed_route_output,
)
from platform_agent_eval.token_budget import TokenCount


class WordCounter:
    def count(self, text: str) -> TokenCount:
        return TokenCount(
            token_count=len(text.split()),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            latency_ms=0.0,
            model_id="word-counter",
        )


def response(payload: object) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(payload),
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        model_id="fake-model",
    )


class TypedCompactionRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = next(
            item
            for item in build_typed_compaction_contexts()
            if item.case_id == "typed-v7::full_evidence"
        )
        self.compacted = full_context(self.context, WordCounter())
        self.prompt = build_typed_route_prompt(self.context, self.compacted)

    def test_prompt_is_blinded_and_contains_runtime_obligations(self) -> None:
        self.assertNotIn(self.context.case_id, self.prompt)
        self.assertNotIn(self.context.condition, self.prompt)
        self.assertNotIn("full_context_ceiling", self.prompt)
        self.assertIn("Clearance never implies authority", self.prompt)
        self.assertIn("VALID_EVIDENCE_IDS", self.prompt)
        self.assertIn(self.context.action.target_id, self.prompt)

    def test_visible_citations_parse(self) -> None:
        event_id = self.context.visible_cards[0].source_event_ids[0]
        routed = parse_typed_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "evidence_event_ids": [event_id],
                    "missing_obligations": [],
                }
            ),
            prompt=self.prompt,
            valid_event_ids=self.compacted.source_event_ids,
        )
        self.assertTrue(routed.format_valid)
        self.assertEqual(Decision.AUTO_EXECUTE, routed.decision)
        self.assertEqual((event_id,), routed.evidence_event_ids)

    def test_invisible_citation_fails_closed(self) -> None:
        routed = parse_typed_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "evidence_event_ids": ["NOT-VISIBLE"],
                    "missing_obligations": [],
                }
            ),
            prompt=self.prompt,
            valid_event_ids=self.compacted.source_event_ids,
        )
        self.assertFalse(routed.format_valid)
        self.assertEqual(Decision.HANDOFF, routed.decision)

    def test_execute_without_evidence_fails_closed(self) -> None:
        routed = parse_typed_route_output(
            response(
                {
                    "decision": "AUTO_EXECUTE",
                    "evidence_event_ids": [],
                    "missing_obligations": [],
                }
            ),
            prompt=self.prompt,
            valid_event_ids=self.compacted.source_event_ids,
        )
        self.assertFalse(routed.format_valid)
        self.assertEqual(Decision.HANDOFF, routed.decision)

    def test_handoff_may_report_missing_proof_without_citation(self) -> None:
        routed = parse_typed_route_output(
            response(
                {
                    "decision": "HANDOFF",
                    "evidence_event_ids": [],
                    "missing_obligations": ["delegation"],
                }
            ),
            prompt=self.prompt,
            valid_event_ids=self.compacted.source_event_ids,
        )
        self.assertTrue(routed.format_valid)
        self.assertEqual(("delegation",), routed.missing_obligations)


if __name__ == "__main__":
    unittest.main()
