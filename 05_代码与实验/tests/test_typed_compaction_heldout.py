from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.proof_cards import ProofCardKind
from platform_agent_eval.typed_compaction_dev import (
    CONDITIONS,
    build_typed_compaction_families,
    visible_card_baseline,
)
from platform_agent_eval.typed_compaction_heldout import (
    build_typed_compaction_heldout_contexts,
    build_typed_compaction_heldout_families,
)
from run_typed_compaction_heldout_gate import (
    assert_paths_available,
    build_plan,
    build_records,
    dataset_audit,
    load_config,
    output_paths,
    summarize,
)


CONFIG = ROOT / "configs" / "typed_compaction_heldout_gate.json"


class TypedCompactionHeldoutDatasetTests(unittest.TestCase):
    def test_has_eleven_bases_and_thirty_three_grouped_contexts(self) -> None:
        families = build_typed_compaction_heldout_families()
        contexts = build_typed_compaction_heldout_contexts()
        self.assertEqual(11, len(families))
        self.assertEqual(33, len(contexts))
        self.assertEqual(
            Counter({"platform": 4, "financial": 4, "mas_travel": 3}),
            Counter(family.domain for family in families),
        )
        for family in families:
            siblings = [x for x in contexts if x.family_id == family.family_id]
            self.assertEqual(set(CONDITIONS), {x.condition for x in siblings})
            self.assertEqual(1, len({x.action for x in siblings}))
            self.assertEqual(1, len({x.policy for x in siblings}))

    def test_each_domain_covers_every_route_and_total_distribution_is_frozen(self) -> None:
        full = [
            context for context in build_typed_compaction_heldout_contexts()
            if context.condition == "full_evidence"
        ]
        expected_by_domain = {
            "platform": Counter({Decision.AUTO_EXECUTE: 2, Decision.REQUEST_CONFIRMATION: 1, Decision.HANDOFF: 1}),
            "financial": Counter({Decision.AUTO_EXECUTE: 2, Decision.REQUEST_CONFIRMATION: 1, Decision.HANDOFF: 1}),
            "mas_travel": Counter({Decision.AUTO_EXECUTE: 1, Decision.REQUEST_CONFIRMATION: 1, Decision.HANDOFF: 1}),
        }
        for domain, expected in expected_by_domain.items():
            self.assertEqual(
                expected,
                Counter(x.expected_decision for x in full if x.domain == domain),
            )
        self.assertEqual(
            Counter({Decision.AUTO_EXECUTE: 5, Decision.REQUEST_CONFIRMATION: 3, Decision.HANDOFF: 3}),
            Counter(x.expected_decision for x in full),
        )

    def test_all_six_proof_kinds_appear_as_critical_evidence(self) -> None:
        self.assertEqual(
            set(ProofCardKind),
            {family.critical_kind for family in build_typed_compaction_heldout_families()},
        )

    def test_identifiers_actions_and_targets_do_not_overlap_development_set(self) -> None:
        dev = build_typed_compaction_families()
        heldout = build_typed_compaction_heldout_families()
        self.assertTrue({x.family_id for x in dev}.isdisjoint(x.family_id for x in heldout))
        self.assertTrue({x.action.actor_id for x in dev}.isdisjoint(x.action.actor_id for x in heldout))
        self.assertTrue({x.action.target_id for x in dev}.isdisjoint(x.action.target_id for x in heldout))
        self.assertTrue({x.action.operation for x in dev}.isdisjoint(x.action.operation for x in heldout))
        self.assertTrue(
            {card.card_id for family in dev for card in family.cards}.isdisjoint(
                card.card_id for family in heldout for card in family.cards
            )
        )
        self.assertTrue(
            {event.event_id for family in dev for event in family.history}.isdisjoint(
                event.event_id for family in heldout for event in family.history
            )
        )

    def test_critical_and_noise_events_are_role_position_length_matched(self) -> None:
        for family in build_typed_compaction_heldout_families():
            by_id = {event.event_id: event for event in family.history}
            critical = by_id[family.critical_event_id]
            noise = by_id[family.matched_noise_event_id]
            positions = {event.event_id: index for index, event in enumerate(family.history)}
            self.assertEqual(critical.role, noise.role)
            self.assertEqual(1, abs(positions[critical.event_id] - positions[noise.event_id]))
            lengths = (len(critical.content.split()), len(noise.content.split()))
            self.assertLessEqual(max(lengths) / min(lengths), 1.05)
            self.assertRegex(critical.event_id, r"^[A-Z]\d-\d{2}$")
            self.assertRegex(noise.event_id, r"^[A-Z]\d-\d{2}$")

    def test_deletions_remove_one_event_and_only_critical_deletion_removes_a_card(self) -> None:
        for context in build_typed_compaction_heldout_contexts():
            visible_events = {event.event_id for event in context.active_events}
            visible_sources = {
                source
                for card in context.visible_cards
                for source in card.source_event_ids
            }
            gold_ids = {card.card_id for card in context.gold_cards}
            visible_ids = {card.card_id for card in context.visible_cards}
            self.assertTrue(visible_sources.issubset(visible_events))
            if context.condition == "full_evidence":
                self.assertEqual((), context.removed_event_ids)
                self.assertEqual(gold_ids, visible_ids)
            elif context.condition == "remove_action_critical":
                self.assertEqual((context.critical_event_id,), context.removed_event_ids)
                self.assertNotIn(context.critical_event_id, visible_sources)
                self.assertEqual(1, len(gold_ids - visible_ids))
            else:
                self.assertEqual((context.matched_noise_event_id,), context.removed_event_ids)
                self.assertNotIn(context.matched_noise_event_id, visible_events)
                self.assertEqual(gold_ids, visible_ids)

    def test_runtime_context_contains_no_private_labels(self) -> None:
        for context in build_typed_compaction_heldout_contexts():
            rendered = context.active_context
            self.assertNotIn(context.case_id, rendered)
            self.assertNotIn(context.family_id, rendered)
            self.assertNotIn(context.condition, rendered)
            self.assertNotIn("expected_decision", rendered)
            self.assertNotIn("unsafe_if_executed", rendered)


class TypedCompactionHeldoutBaselineTests(unittest.TestCase):
    def test_visible_card_validator_is_perfect_on_full_and_noise_controls(self) -> None:
        for context in build_typed_compaction_heldout_contexts():
            if context.condition == "remove_action_critical":
                continue
            with self.subTest(case=context.case_id):
                self.assertEqual(context.expected_decision, visible_card_baseline(context).decision)

    def test_nonhold_losses_fail_closed_and_hidden_holds_create_three_harmful_executes(self) -> None:
        hidden_hold_harm = 0
        nonhold_correct = 0
        for context in build_typed_compaction_heldout_contexts():
            if context.condition != "remove_action_critical":
                continue
            result = visible_card_baseline(context)
            if context.critical_kind is ProofCardKind.ACTIVE_HOLD:
                hidden_hold_harm += int(
                    result.decision is Decision.AUTO_EXECUTE
                    and context.unsafe_if_executed
                )
            else:
                self.assertIn(
                    result.decision,
                    {Decision.REQUEST_CONFIRMATION, Decision.HANDOFF},
                )
                nonhold_correct += int(result.decision is context.expected_decision)
        self.assertEqual(3, hidden_hold_harm)
        self.assertEqual(8, nonhold_correct)


class TypedCompactionHeldoutRunnerTests(unittest.TestCase):
    def test_plan_is_local_model_free_and_zero_cost(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(11, plan["base_families"])
        self.assertEqual(33, plan["matched_contexts"])
        self.assertEqual(0, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("typed-heldout", results_dir=Path(directory))
            paths["audit"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_frozen_records_pass_dataset_gate(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        audit = dataset_audit(records, summarize(records), gate=config["dataset_gate"])
        self.assertEqual("PASS_TYPED_COMPACTION_HELDOUT_DATASET_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))


if __name__ == "__main__":
    unittest.main()
