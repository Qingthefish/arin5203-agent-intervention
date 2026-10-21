import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.natural_language_evidence import (
    LEAK_MARKERS,
    ExtractionParse,
    build_extraction_prompt,
    build_nl_contexts,
    build_nl_families,
    parse_extraction_output,
    score_extraction,
)
from platform_agent_eval.proof_cards import ProofCardKind


def _perfect_output(context) -> str:
    claims = [
        {
            "event_id": card.source_event_ids[0],
            "kind": card.kind.value,
            "issuer": card.issuer_id,
            "applies_to_proposed_action": True,
            "valid_now": True,
            "verified": True,
            "transferable": card.transferable,
        }
        for card in context.visible_cards
    ]
    return json.dumps({"claims": claims})


class NaturalLanguageEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contexts = build_nl_contexts()
        cls.families = build_nl_families()

    def test_size_and_balance(self):
        self.assertEqual(len(self.contexts), 120)
        counts = Counter((c.split, c.variant) for c in self.contexts)
        self.assertEqual(counts[("dev", "clean")], 27)
        self.assertEqual(counts[("test", "distractor")], 33)

    def test_no_typed_format_leaks_or_card_ids(self):
        for context in self.contexts:
            text = context.active_context
            for marker in LEAK_MARKERS:
                self.assertNotIn(marker, text, context.case_id)
            for card in context.visible_cards:
                self.assertNotIn(card.card_id, text, context.case_id)

    def test_gold_labels_never_in_prompt(self):
        for context in self.contexts[:12]:
            prompt = build_extraction_prompt(context)
            self.assertNotIn(context.expected_decision.value, prompt.split("HISTORY:")[1])
            self.assertNotIn(context.condition, prompt)

    def test_critical_and_noise_word_counts_match(self):
        for family in self.families:
            events = {e.event_id: e for e in family.history}
            self.assertEqual(
                len(events[family.critical_event_id].content.split()),
                len(events[family.matched_noise_event_id].content.split()),
                family.family_id,
            )

    def test_distractor_is_never_gold_evidence(self):
        for family in self.families:
            sources = {card.source_event_ids[0] for card in family.cards}
            if family.variant == "distractor":
                self.assertIsNotNone(family.distractor_event_id)
                self.assertNotIn(family.distractor_event_id, sources)
            else:
                self.assertIsNone(family.distractor_event_id)

    def test_perfect_extraction_matches_gold_except_hidden_holds(self):
        for context in self.contexts:
            parse = parse_extraction_output(
                _perfect_output(context), {e.event_id for e in context.active_events}
            )
            score = score_extraction(context, parse)
            hidden_hold = (
                context.condition == "remove_action_critical"
                and context.critical_kind is ProofCardKind.ACTIVE_HOLD
            )
            self.assertEqual(score["route_correct"], not hidden_hold, context.case_id)
            self.assertEqual(score["card_recall"], 1.0)
            self.assertEqual(score["card_precision"], 1.0)

    def test_distractor_claim_is_detected_as_false_positive(self):
        context = next(
            c for c in self.contexts
            if c.variant == "distractor" and c.condition == "full_evidence"
        )
        claims = json.loads(_perfect_output(context))["claims"]
        claims.append({
            "event_id": context.distractor_event_id, "kind": "ACTIVE_HOLD",
            "issuer": context.policy.hold_issuers[0], "applies_to_proposed_action": True,
            "valid_now": True, "verified": True, "transferable": False,
        })
        parse = parse_extraction_output(
            json.dumps({"claims": claims}), {e.event_id for e in context.active_events}
        )
        score = score_extraction(context, parse)
        self.assertTrue(score["distractor_false_positive"])
        self.assertEqual(score["decision"], Decision.HANDOFF.value)

    def test_invalid_output_fails_closed(self):
        context = self.contexts[0]
        parse = parse_extraction_output("not json", {e.event_id for e in context.active_events})
        self.assertFalse(parse.format_valid)
        score = score_extraction(context, parse)
        self.assertNotEqual(score["decision"], Decision.AUTO_EXECUTE.value)

    def test_invisible_and_unknown_claims_are_dropped(self):
        context = self.contexts[0]
        parse = parse_extraction_output(
            json.dumps({"claims": [
                {"event_id": "ZZ-99", "kind": "AUTHORITY"},
                {"event_id": context.active_events[1].event_id, "kind": "APPROVAL"},
            ]}),
            {e.event_id for e in context.active_events},
        )
        self.assertIsInstance(parse, ExtractionParse)
        self.assertEqual(parse.claims, ())
        self.assertEqual(parse.dropped_claims, 2)


if __name__ == "__main__":
    unittest.main()
