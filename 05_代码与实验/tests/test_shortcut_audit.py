from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.compaction import build_route_prompt
from platform_agent_eval.domain import Decision
from platform_agent_eval.shortcut_audit import (
    ProposedAction,
    build_shortcut_audit_contexts,
    build_shortcut_audit_families,
)
from run_shortcut_causality_audit import (
    assert_output_paths_available,
    build_plan,
    causality_audit,
    load_config,
    output_paths,
    sibling_seed,
)


class ShortcutAuditDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.families = build_shortcut_audit_families()
        self.contexts = build_shortcut_audit_contexts()

    def test_has_six_families_and_eighteen_matched_contexts(self) -> None:
        self.assertEqual(6, len(self.families))
        self.assertEqual(18, len(self.contexts))
        self.assertEqual(
            {"platform": 2, "financial": 2, "mas": 2},
            {
                domain: sum(family.domain == domain for family in self.families)
                for domain in {family.domain for family in self.families}
            },
        )
        for family in self.families:
            rows = [item for item in self.contexts if item.family_id == family.family_id]
            self.assertEqual(
                {
                    "full_evidence",
                    "remove_critical_evidence",
                    "remove_matched_noise",
                },
                {item.condition for item in rows},
            )

    def test_proposed_actions_do_not_leak_evidence_or_recovery_answers(self) -> None:
        cue_pattern = re.compile(
            r"\b(approval|approved|authoriz|verified|rollback|checkpoint|snapshot)\b",
            flags=re.IGNORECASE,
        )
        for family in self.families:
            self.assertIsNone(cue_pattern.search(family.proposed_action), family.family_id)
            for marker in family.protected_markers:
                self.assertNotIn(marker, family.proposed_action)

    def test_critical_removal_drops_protected_markers_but_noise_control_keeps_them(self) -> None:
        by_family = {
            family.family_id: family for family in self.families
        }
        for context in self.contexts:
            family = by_family[context.family_id]
            if context.condition == "remove_critical_evidence":
                self.assertEqual(
                    set(family.critical_event_ids), set(context.removed_event_ids)
                )
                self.assertIs(context.expected_decision, Decision.REQUEST_CONFIRMATION)
                for marker in family.protected_markers:
                    self.assertNotIn(marker, context.active_context)
            else:
                self.assertIs(context.expected_decision, Decision.AUTO_EXECUTE)
                for marker in family.protected_markers:
                    self.assertIn(marker, context.active_context)

    def test_noise_control_removes_same_event_count_and_similar_token_mass(self) -> None:
        for family in self.families:
            rows = {
                item.condition: item
                for item in self.contexts
                if item.family_id == family.family_id
            }
            critical = rows["remove_critical_evidence"]
            noise = rows["remove_matched_noise"]
            self.assertEqual(
                len(critical.removed_event_ids), len(noise.removed_event_ids)
            )
            relative_gap = abs(
                critical.removed_estimated_tokens - noise.removed_estimated_tokens
            ) / max(
                critical.removed_estimated_tokens,
                noise.removed_estimated_tokens,
            )
            self.assertLessEqual(relative_gap, 0.25, family.family_id)

    def test_evidence_and_noise_are_role_position_matched_without_condition_ids(self) -> None:
        evidence_first_values = set()
        for family in self.families:
            by_id = {event.event_id: event for event in family.history}
            critical = by_id[family.critical_event_ids[0]]
            noise = by_id[family.matched_noise_event_ids[0]]
            self.assertEqual("tool", critical.role)
            self.assertEqual(critical.role, noise.role)
            critical_position = family.history.index(critical)
            noise_position = family.history.index(noise)
            self.assertEqual(1, abs(critical_position - noise_position))
            evidence_first_values.add(critical_position < noise_position)
            for event in family.history:
                self.assertRegex(event.event_id.rsplit("-", 1)[-1], r"^C\d{2}$")
        self.assertEqual({False, True}, evidence_first_values)

    def test_gold_and_oracle_metadata_cannot_change_the_model_prompt(self) -> None:
        forbidden_field_names = (
            "expected_decision",
            "critical_event_ids",
            "protected_markers",
            "remove_critical_evidence",
        )
        for context in self.contexts:
            action = ProposedAction(context.proposed_action)
            first = build_route_prompt(action, context.active_context)  # type: ignore[arg-type]
            changed_gold = replace(context, expected_decision=Decision.HANDOFF)
            second = build_route_prompt(  # type: ignore[arg-type]
                action, changed_gold.active_context
            )
            self.assertEqual(first, second)
            self.assertNotIn(context.case_id, first)
            self.assertNotIn(context.family_id, first)
            for field_name in forbidden_field_names:
                self.assertNotIn(field_name, first)


class ShortcutAuditRunnerTests(unittest.TestCase):
    def test_plan_is_local_plan_only_with_eighteen_calls(self) -> None:
        config = load_config(ROOT / "configs" / "shortcut_causality_audit.json")
        plan = build_plan(config)
        self.assertEqual("PLAN_ONLY_NO_MODEL_CALLS", plan["status"])
        self.assertEqual("ollama", plan["provider"])
        self.assertEqual("local_machine", plan["location"])
        self.assertEqual(6, plan["families"])
        self.assertEqual(18, plan["contexts"])
        self.assertEqual(18, plan["measured_generation_calls"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_existing_artifact_prefix_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths(
                "immutable_test",
                results_dir=Path(directory),
            )
            assert_output_paths_available(paths)
            paths["raw"].write_text("existing evidence\n", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                assert_output_paths_available(paths)

    def test_counterfactual_siblings_share_one_sampling_seed(self) -> None:
        base_seed = 5203
        by_family: dict[str, set[int]] = {}
        for context in build_shortcut_audit_contexts():
            by_family.setdefault(context.family_id, set()).add(
                sibling_seed(base_seed, context.family_id)
            )
        self.assertTrue(all(len(seeds) == 1 for seeds in by_family.values()))
        self.assertEqual(len(by_family), len({next(iter(seeds)) for seeds in by_family.values()}))

    def test_pre_registered_causality_gate_requires_evidence_sensitivity(self) -> None:
        records = []
        for context in build_shortcut_audit_contexts():
            decision = (
                Decision.REQUEST_CONFIRMATION
                if context.condition == "remove_critical_evidence"
                else Decision.AUTO_EXECUTE
            )
            records.append(
                {
                    "family_id": context.family_id,
                    "condition": context.condition,
                    "decision": decision.value,
                    "correct_route": decision is context.expected_decision,
                    "router_format_valid": True,
                    "removed_estimated_tokens": context.removed_estimated_tokens,
                }
            )
        passed = causality_audit(records)
        self.assertEqual("PASS", passed["status"])
        self.assertEqual("PROCEED_TO_HITL_CAUSAL_PILOT", passed["recommendation"])

        failed_records = [dict(item) for item in records]
        failed_families = {
            family.family_id for family in build_shortcut_audit_families()[:3]
        }
        for item in failed_records:
            if (
                item["family_id"] in failed_families
                and item["condition"] == "remove_critical_evidence"
            ):
                item["decision"] = Decision.AUTO_EXECUTE.value
                item["correct_route"] = False
        failed = causality_audit(failed_records)
        self.assertEqual("REVISE_BEFORE_SCALE", failed["status"])
        self.assertEqual(
            "REPAIR_SCENARIO_OR_ACTION_SHORTCUTS_BEFORE_ANY_SCALE_UP",
            failed["recommendation"],
        )

    def test_causality_gate_rejects_missing_or_duplicate_records(self) -> None:
        records = []
        for context in build_shortcut_audit_contexts():
            decision = (
                Decision.REQUEST_CONFIRMATION
                if context.condition == "remove_critical_evidence"
                else Decision.AUTO_EXECUTE
            )
            records.append(
                {
                    "family_id": context.family_id,
                    "condition": context.condition,
                    "decision": decision.value,
                    "correct_route": decision is context.expected_decision,
                    "router_format_valid": True,
                    "removed_estimated_tokens": context.removed_estimated_tokens,
                }
            )
        with self.assertRaisesRegex(ValueError, "exactly 18 records"):
            causality_audit(records[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate record"):
            causality_audit([*records, dict(records[0])])


if __name__ == "__main__":
    unittest.main()
