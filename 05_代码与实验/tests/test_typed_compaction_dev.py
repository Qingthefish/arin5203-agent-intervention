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
    all_gold_cards_visible,
    build_typed_compaction_contexts,
    build_typed_compaction_families,
    visible_card_baseline,
)
from run_typed_compaction_dataset_gate import (
    assert_paths_available,
    build_plan,
    build_records,
    dataset_audit,
    load_config,
    output_paths,
    summarize,
)


CONFIG = ROOT / "configs" / "typed_compaction_dataset_gate.json"


class TypedCompactionDatasetTests(unittest.TestCase):
    def test_has_nine_bases_and_twenty_seven_grouped_contexts(self) -> None:
        families = build_typed_compaction_families()
        contexts = build_typed_compaction_contexts()
        self.assertEqual(9, len(families))
        self.assertEqual(27, len(contexts))
        self.assertEqual({"platform", "financial", "mas_travel"}, {x.domain for x in families})
        for family in families:
            siblings = [x for x in contexts if x.family_id == family.family_id]
            self.assertEqual(set(CONDITIONS), {x.condition for x in siblings})
            self.assertEqual(1, len({x.action for x in siblings}))
            self.assertEqual(1, len({x.policy for x in siblings}))

    def test_full_routes_are_balanced_within_every_domain(self) -> None:
        full = [x for x in build_typed_compaction_contexts() if x.condition == "full_evidence"]
        for domain in ("platform", "financial", "mas_travel"):
            routes = Counter(x.expected_decision for x in full if x.domain == domain)
            self.assertEqual(1, routes[Decision.AUTO_EXECUTE])
            self.assertEqual(1, routes[Decision.REQUEST_CONFIRMATION])
            self.assertEqual(1, routes[Decision.HANDOFF])

    def test_critical_and_noise_events_are_role_position_length_matched(self) -> None:
        for family in build_typed_compaction_families():
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

    def test_deletions_remove_exactly_one_event_and_its_card_only(self) -> None:
        for context in build_typed_compaction_contexts():
            visible_events = {event.event_id for event in context.active_events}
            visible_sources = {
                source
                for card in context.visible_cards
                for source in card.source_event_ids
            }
            self.assertTrue(visible_sources.issubset(visible_events))
            if context.condition == "full_evidence":
                self.assertEqual((), context.removed_event_ids)
                self.assertTrue(all_gold_cards_visible(context))
            elif context.condition == "remove_action_critical":
                self.assertEqual((context.critical_event_id,), context.removed_event_ids)
                self.assertNotIn(context.critical_event_id, visible_sources)
                self.assertFalse(all_gold_cards_visible(context))
            else:
                self.assertEqual((context.matched_noise_event_id,), context.removed_event_ids)
                self.assertNotIn(context.matched_noise_event_id, visible_events)
                self.assertTrue(all_gold_cards_visible(context))

    def test_critical_deletions_cover_four_distinct_proof_types(self) -> None:
        kinds = Counter(family.critical_kind for family in build_typed_compaction_families())
        self.assertEqual(2, kinds[ProofCardKind.AUTHORITY])
        self.assertEqual(3, kinds[ProofCardKind.ACTIVE_HOLD])
        self.assertEqual(3, kinds[ProofCardKind.REPAIR_CHANNEL])
        self.assertEqual(1, kinds[ProofCardKind.DELEGATION])

    def test_private_labels_do_not_appear_in_runtime_context(self) -> None:
        for context in build_typed_compaction_contexts():
            rendered = context.active_context
            self.assertNotIn(context.case_id, rendered)
            self.assertNotIn(context.condition, rendered)
            self.assertNotIn("expected_decision", rendered)
            self.assertNotIn("unsafe_if_executed", rendered)


class TypedCompactionBaselineTests(unittest.TestCase):
    def test_visible_card_validator_is_perfect_on_full_and_noise_controls(self) -> None:
        for context in build_typed_compaction_contexts():
            if context.condition == "remove_action_critical":
                continue
            with self.subTest(case=context.case_id):
                self.assertEqual(
                    context.expected_decision,
                    visible_card_baseline(context).decision,
                )

    def test_lost_hold_causes_exactly_three_harmful_executes(self) -> None:
        failures = []
        for context in build_typed_compaction_contexts():
            result = visible_card_baseline(context)
            if (
                context.condition == "remove_action_critical"
                and context.critical_kind is ProofCardKind.ACTIVE_HOLD
                and result.decision is Decision.AUTO_EXECUTE
                and context.unsafe_if_executed
            ):
                failures.append(context.case_id)
        self.assertEqual(3, len(failures))

    def test_other_critical_losses_fail_closed_to_confirm_or_handoff(self) -> None:
        for context in build_typed_compaction_contexts():
            if context.condition != "remove_action_critical":
                continue
            if context.critical_kind is ProofCardKind.ACTIVE_HOLD:
                continue
            with self.subTest(case=context.case_id):
                result = visible_card_baseline(context)
                self.assertIn(
                    result.decision,
                    {Decision.REQUEST_CONFIRMATION, Decision.HANDOFF},
                )
                self.assertEqual(context.expected_decision, result.decision)


class TypedCompactionRunnerTests(unittest.TestCase):
    def test_plan_is_local_model_free_and_zero_cost(self) -> None:
        plan = build_plan(load_config(CONFIG))
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual(9, plan["base_families"])
        self.assertEqual(27, plan["matched_contexts"])
        self.assertEqual(0, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifact_prefix_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("typed", results_dir=Path(directory))
            paths["audit"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_frozen_records_pass_dataset_gate(self) -> None:
        config = load_config(CONFIG)
        records = build_records()
        audit = dataset_audit(
            records,
            summarize(records),
            gate=config["dataset_gate"],
        )
        self.assertEqual("PASS_TYPED_COMPACTION_DATASET_GATE", audit["status"])
        self.assertTrue(all(audit["pre_specified_gate"].values()))


if __name__ == "__main__":
    unittest.main()
