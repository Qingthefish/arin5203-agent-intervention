from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.model_routing import GenerationConfig, ModelResponse
from platform_agent_eval.token_budget import TokenCount
from platform_agent_eval.typed_budget_compaction import (
    BUDGETED_METHODS,
    build_budget_context,
    deterministic_drafts,
    full_context,
    rehydrate_cards,
    summary_draft,
    ufold_draft,
)
from platform_agent_eval.typed_compaction_dev import build_typed_compaction_contexts


class WordCounter:
    def count(self, text: str) -> TokenCount:
        return TokenCount(
            token_count=len(text.split()),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            latency_ms=0.0,
            model_id="word-counter",
        )


class FakeClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def generate(self, _prompt: str, _config: GenerationConfig) -> ModelResponse:
        return ModelResponse(
            text=json.dumps(self.payload),
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1.0,
            model_id="fake-model",
        )


class TypedBudgetCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = next(
            item for item in build_typed_compaction_contexts()
            if item.case_id == "typed-v7::full_evidence"
        )
        self.counter = WordCounter()

    def test_deterministic_methods_share_budget_and_blind_labels(self) -> None:
        drafts = deterministic_drafts(self.context)
        self.assertEqual(
            {"recent_window", "generic_pinning", "typed_card_retention"},
            set(drafts),
        )
        for draft in drafts.values():
            compacted = build_budget_context(
                self.context,
                draft,
                counter=self.counter,
                budget_tokens=300,
                minimum_utilization=0.8,
            )
            self.assertLessEqual(compacted.exact_raw_tokens, 300)
            self.assertNotIn(draft.method, compacted.text)
            self.assertTrue(set(compacted.neutral_fill_event_ids).isdisjoint(
                {source for card in self.context.visible_cards for source in card.source_event_ids}
            ))

    def test_typed_retention_rehydrates_every_visible_card_at_sufficient_budget(self) -> None:
        draft = deterministic_drafts(self.context)["typed_card_retention"]
        compacted = build_budget_context(
            self.context, draft, counter=self.counter,
            budget_tokens=360, minimum_utilization=0.8,
        )
        self.assertEqual(
            {card.card_id for card in self.context.visible_cards},
            {card.card_id for card in rehydrate_cards(self.context, compacted)},
        )
        self.assertIn("PROOF_FIELDS=source|id|type", compacted.text)
        self.assertNotIn("TOOL: Proof card", compacted.text)
        for card in self.context.visible_cards:
            self.assertIn(card.card_id, compacted.text)

    def test_summary_accepts_comma_separated_visible_citations(self) -> None:
        first, second = (
            card.source_event_ids[0] for card in self.context.visible_cards[:2]
        )
        draft = summary_draft(
            self.context,
            "neutral_summary",
            FakeClient({"summary": f"Two proofs remain relevant [{first}, {second}]."}),
            GenerationConfig(model="fake"),
        )
        self.assertTrue(draft.format_valid)
        self.assertEqual((first, second), draft.source_event_ids)
        compacted = build_budget_context(
            self.context,
            draft,
            counter=self.counter,
            budget_tokens=180,
            minimum_utilization=0.7,
        )
        self.assertTrue({first, second}.issubset(compacted.source_event_ids))
        self.assertEqual(
            {self.context.visible_cards[0].card_id, self.context.visible_cards[1].card_id},
            {
                card.card_id
                for card in rehydrate_cards(self.context, compacted)
                if card.card_id
                in {
                    self.context.visible_cards[0].card_id,
                    self.context.visible_cards[1].card_id,
                }
            },
        )

    def test_every_typed_capsule_keeps_all_visible_provenance(self) -> None:
        for context in build_typed_compaction_contexts():
            draft = deterministic_drafts(context)["typed_card_retention"]
            expected_sources = {
                source
                for card in context.visible_cards
                for source in card.source_event_ids
            }
            self.assertEqual(expected_sources, set(draft.source_event_ids))
            for source in expected_sources:
                self.assertIn(f"[{source}]", draft.summary)

    def test_utilization_floor_rounds_up_to_whole_token(self) -> None:
        draft = deterministic_drafts(self.context)["recent_window"]
        compacted = build_budget_context(
            self.context,
            draft,
            counter=self.counter,
            budget_tokens=101,
            minimum_utilization=0.9,
        )
        self.assertGreaterEqual(compacted.exact_raw_tokens, 91)

    def test_full_context_is_an_unbudgeted_ceiling(self) -> None:
        compacted = full_context(self.context, self.counter)
        self.assertIsNone(compacted.budget_tokens)
        self.assertEqual(len(self.context.visible_cards), len(rehydrate_cards(self.context, compacted)))

    def test_summary_citations_can_rehydrate_canonical_cards(self) -> None:
        source = self.context.visible_cards[0].source_event_ids[0]
        draft = summary_draft(
            self.context,
            "neutral_summary",
            FakeClient({"summary": f"A current proof remains relevant [{source}]."}),
            GenerationConfig(model="fake"),
        )
        compacted = build_budget_context(
            self.context, draft, counter=self.counter,
            budget_tokens=180, minimum_utilization=0.7,
        )
        self.assertIn(self.context.visible_cards[0].card_id, {
            card.card_id for card in rehydrate_cards(self.context, compacted)
        })

    def test_truncated_summary_cannot_rehydrate_a_removed_citation(self) -> None:
        source = self.context.visible_cards[0].source_event_ids[0]
        draft = summary_draft(
            self.context,
            "neutral_summary",
            FakeClient(
                {
                    "summary": (
                        "Routine context " * 80
                        + f"final authority evidence [{source}]."
                    )
                }
            ),
            GenerationConfig(model="fake"),
        )
        compacted = build_budget_context(
            self.context,
            draft,
            counter=self.counter,
            budget_tokens=40,
            minimum_utilization=0.7,
        )
        self.assertTrue(compacted.base_was_truncated)
        self.assertNotIn(source, compacted.text)
        self.assertNotIn(
            self.context.visible_cards[0].card_id,
            {card.card_id for card in rehydrate_cards(self.context, compacted)},
        )

    def test_generic_pinning_recognizes_plain_typed_proof_words(self) -> None:
        draft = deterministic_drafts(self.context)["generic_pinning"]
        self.assertTrue(set(draft.priority_event_ids).intersection(
            {source for card in self.context.visible_cards for source in card.source_event_ids}
        ))

    def test_ufold_rejects_invisible_source_event(self) -> None:
        draft = ufold_draft(
            self.context,
            FakeClient({
                "intent_summary": "Deploy the service",
                "proof_log": [{"event_id": "NOT-VISIBLE", "fact": "approved"}],
            }),
            GenerationConfig(model="fake"),
        )
        self.assertFalse(draft.format_valid)
        self.assertEqual((), draft.source_event_ids)

    def test_every_budgeted_method_is_accounted_for(self) -> None:
        self.assertEqual(6, len(BUDGETED_METHODS))


if __name__ == "__main__":
    unittest.main()
