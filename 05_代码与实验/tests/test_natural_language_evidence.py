import json
import importlib.util
import io
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from platform_agent_eval.domain import Decision
from platform_agent_eval.natural_language_evidence import (
    LEAK_MARKERS,
    EXTRACTION_METRIC_DEFINITIONS,
    ExtractionParse,
    build_extraction_prompt,
    build_nl_contexts,
    build_nl_families,
    applicable_keys,
    claims_to_cards,
    parse_extraction_output,
    render_card_text,
    score_extraction,
)
from platform_agent_eval.proof_cards import ProofCardKind
from platform_agent_eval.model_routing import GenerationConfig, ModelResponse


_spec = importlib.util.spec_from_file_location(
    "nl_evidence_runner", Path(__file__).resolve().parents[1] / "scripts/run_nl_evidence_extraction.py"
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _perfect_output(context) -> str:
    messages = {e.event_id: e.content for e in context.active_events}
    claims = [
        {
            "event_id": card.source_event_ids[0],
            "kind": card.kind.value,
            "issuer": card.issuer_id,
            "subject": card.subject_id,
            "operation": card.operation,
            "target": card.target_id,
            "scope": dict(card.scope),
            "valid_from": card.valid_from,
            "valid_until": card.valid_until,
            "verified": card.authenticated,
            "transferable": card.transferable,
            "source_quote": messages[card.source_event_ids[0]],
        }
        for card in (*context.visible_cards, *context.nonapplicable_cards)
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
        for context in self.contexts:
            prompt = build_extraction_prompt(context)
            self.assertNotIn(context.expected_decision.value, prompt.split("HISTORY:")[1])
            self.assertNotIn(context.condition, prompt)

    def test_critical_and_noise_bytes_and_roles_match(self):
        for family in self.families:
            events = {e.event_id: e for e in family.history}
            self.assertEqual(
                len(events[family.critical_event_id].content.encode("utf-8")),
                len(events[family.matched_noise_event_id].content.encode("utf-8")),
                family.family_id,
            )
            self.assertEqual(events[family.critical_event_id].role, events[family.matched_noise_event_id].role)

    def test_distractor_is_never_gold_evidence(self):
        for family in self.families:
            sources = {card.source_event_ids[0] for card in family.cards}
            if family.variant == "distractor":
                self.assertIsNotNone(family.distractor_event_id)
                self.assertNotIn(family.distractor_event_id, sources)
            else:
                self.assertIsNone(family.distractor_event_id)

    def test_every_literal_source_names_its_operation(self):
        for context in self.contexts:
            events = {event.event_id: event.content for event in context.active_events}
            for card in (*context.visible_cards, *context.nonapplicable_cards):
                self.assertIn(
                    card.operation.lower().replace("_", " "),
                    events[card.source_event_ids[0]],
                    (context.case_id, card.source_event_ids[0]),
                )

    def test_clean_and_distractor_change_only_equal_byte_message_content(self):
        paired = {(c.family_id, c.condition, c.variant): c for c in self.contexts}
        for context in self.contexts:
            if context.variant != "distractor":
                continue
            clean = paired[(context.family_id, context.condition, "clean")]
            self.assertEqual(len(clean.active_events), len(context.active_events))
            for ordinary, distracted in zip(clean.active_events, context.active_events, strict=True):
                self.assertEqual(ordinary.event_id, distracted.event_id)
                self.assertEqual(ordinary.role, distracted.role)
                if distracted.event_id == context.distractor_event_id:
                    self.assertNotEqual(ordinary.content, distracted.content)
                    self.assertEqual(
                        len(ordinary.content.encode("utf-8")),
                        len(distracted.content.encode("utf-8")),
                    )
                else:
                    self.assertEqual(ordinary.content, distracted.content)

    def test_invalid_literal_cards_are_complete_and_separate_from_valid_evidence(self):
        for context in self.contexts:
            if context.variant != "distractor":
                self.assertEqual((), context.nonapplicable_cards)
                continue
            self.assertEqual(1, len(context.nonapplicable_cards))
            self.assertEqual(set(), applicable_keys(context.nonapplicable_cards, context.action, context.policy))
            invalid = context.nonapplicable_cards[0]
            self.assertNotIn(invalid, context.visible_cards)
            self.assertEqual((context.distractor_event_id,), invalid.source_event_ids)
            text = next(e.content for e in context.active_events if e.event_id == context.distractor_event_id)
            self.assertIn(invalid.valid_from, text)
            self.assertIn(invalid.valid_until, text)
            self.assertIn(invalid.target_id, text)
            self.assertIn(invalid.issuer_id, text)
            self.assertTrue(invalid.scope)

    def test_perfect_extraction_matches_gold_except_hidden_holds(self):
        for context in self.contexts:
            parse = parse_extraction_output(
                _perfect_output(context), {e.event_id: e.content for e in context.active_events}
            )
            score = score_extraction(context, parse)
            hidden_hold = (
                context.condition == "remove_action_critical"
                and context.critical_kind is ProofCardKind.ACTIVE_HOLD
            )
            self.assertEqual(score["route_correct"], not hidden_hold, context.case_id)
            self.assertEqual(score["card_recall"], 1.0)
            self.assertEqual(score["card_precision"], 1.0)
            self.assertEqual(score["all_source_exact_recall"], 1.0)
            self.assertEqual(score["all_source_exact_precision"], 1.0)
            self.assertEqual(score["matched_field_correct"], score["matched_field_total"])
            self.assertTrue(score["route_matches_visible_oracle"])
            self.assertTrue(score["candidate_route_matches_visible_oracle"])
            self.assertEqual(score["candidate_decision"], score["decision"])
            self.assertEqual(score["invented_field_claims"], 0)
            self.assertEqual(score["unsupported_source_claims"], 0)
            self.assertEqual(score["omitted_literal_gold_claims"], 0)
            self.assertFalse(score["distractor_false_positive"])

    def test_distractor_claim_is_detected_as_false_positive(self):
        context = next(
            c for c in self.contexts
            if c.variant == "distractor" and c.condition == "full_evidence"
        )
        claims = json.loads(_perfect_output(context))["claims"]
        promoted = {
            **claims[0], "event_id": context.distractor_event_id,
            "kind": "ACTIVE_HOLD", "issuer": context.policy.hold_issuers[0],
            "subject": context.action.target_id,
            "operation": context.action.operation,
            "target": context.action.target_id,
            "scope": dict(context.action.scope), "verified": True,
            "source_quote": next(e.content for e in context.active_events if e.event_id == context.distractor_event_id),
        }
        claims = [promoted if claim["event_id"] == context.distractor_event_id else claim for claim in claims]
        parse = parse_extraction_output(
            json.dumps({"claims": claims}), {e.event_id: e.content for e in context.active_events}
        )
        score = score_extraction(context, parse)
        self.assertTrue(score["distractor_false_positive"])
        self.assertEqual(score["decision"], Decision.HANDOFF.value)
        self.assertEqual(score["invented_field_claims"], 1)

    def test_invalid_output_fails_closed(self):
        context = self.contexts[0]
        parse = parse_extraction_output("not json", {e.event_id: e.content for e in context.active_events})
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
            {e.event_id: e.content for e in context.active_events},
        )
        self.assertIsInstance(parse, ExtractionParse)
        self.assertEqual(parse.claims, ())
        self.assertEqual(parse.dropped_claims, 2)
        self.assertFalse(parse.format_valid)

    def test_malformed_hold_cannot_disappear_into_a_valid_execute(self):
        context = next(c for c in self.contexts if c.condition == "full_evidence"
                       and c.critical_kind is ProofCardKind.ACTIVE_HOLD)
        payload = json.loads(_perfect_output(context))
        for claim in payload["claims"]:
            if claim["kind"] == "ACTIVE_HOLD":
                claim["kind"] = "ACTIVE-HOLD"
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        self.assertFalse(parsed.format_valid)
        self.assertEqual(parsed.dropped_claims, 1)
        self.assertEqual(score_extraction(context, parsed)["decision"], Decision.HANDOFF.value)

    def test_literal_wrong_actor_scope_and_expiry_are_not_repaired_by_adapter(self):
        context = self.contexts[0]
        for field, value in (
            ("subject", "another-agent"),
            ("scope", {"namespace": "another-namespace"}),
            ("valid_until", "2026-10-05T23:59:00+08:00"),
        ):
            payload = json.loads(_perfect_output(context))
            authority = next(c for c in payload["claims"] if c["kind"] == "AUTHORITY")
            authority[field] = value
            if field == "valid_until":
                authority["valid_from"] = "2026-10-05T00:00:00+08:00"
            parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
            self.assertTrue(parsed.format_valid)
            card = next(c for c in claims_to_cards(parsed.claims) if c.kind is ProofCardKind.AUTHORITY)
            self.assertEqual(getattr(card, {"subject": "subject_id", "scope": "scope", "valid_until": "valid_until"}[field]),
                             tuple(sorted(value.items())) if field == "scope" else value)
            self.assertNotEqual(score_extraction(context, parsed)["decision"], Decision.AUTO_EXECUTE.value)

    def test_nonexistent_quote_or_nonboolean_flag_invalidates_whole_output(self):
        context = self.contexts[0]
        for field, value in (("source_quote", "made-up approval"), ("verified", "true")):
            payload = json.loads(_perfect_output(context))
            payload["claims"][0][field] = value
            parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
            self.assertFalse(parsed.format_valid)
            self.assertEqual(score_extraction(context, parsed)["decision"], Decision.HANDOFF.value)

    def test_duplicate_event_with_another_kind_fails_closed(self):
        context = self.contexts[0]
        payload = json.loads(_perfect_output(context))
        payload["claims"].append({**payload["claims"][0], "kind": "ACTIVE_HOLD"})
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        self.assertFalse(parsed.format_valid)

    def test_correct_source_and_kind_do_not_hide_invented_validity(self):
        context = self.contexts[0]
        payload = json.loads(_perfect_output(context))
        payload["claims"][0]["valid_until"] = "2027-12-31T23:59:00+08:00"
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        score = score_extraction(context, parsed)
        self.assertLess(score["card_precision"], 1.0)
        self.assertLess(score["card_recall"], 1.0)

    def test_invalid_card_omission_is_not_confused_with_correct_rejection(self):
        context = next(c for c in self.contexts if c.variant == "distractor"
                       and c.condition == "full_evidence")
        payload = json.loads(_perfect_output(context))
        payload["claims"] = [c for c in payload["claims"] if c["event_id"] != context.distractor_event_id]
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        score = score_extraction(context, parsed)
        self.assertTrue(score["route_matches_visible_oracle"])
        self.assertEqual(score["card_precision"], 1.0)
        self.assertEqual(score["card_recall"], 1.0)
        self.assertEqual(score["all_source_exact_precision"], 1.0)
        self.assertLess(score["all_source_exact_recall"], 1.0)
        self.assertEqual(score["omitted_literal_gold_claims"], 1)

    def test_field_counts_distinguish_wrong_normalization_and_unsupported_source(self):
        context = self.contexts[0]
        payload = json.loads(_perfect_output(context))
        payload["claims"][0]["subject"] = "another-agent"
        noise = next(e for e in context.active_events if e.event_id == context.matched_noise_event_id)
        payload["claims"].append({**payload["claims"][0], "event_id": noise.event_id, "source_quote": noise.content})
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        score = score_extraction(context, parsed)
        self.assertTrue(parsed.format_valid)
        self.assertEqual(score["matched_field_total"], 10 * len(context.visible_cards))
        self.assertEqual(score["matched_field_correct"], score["matched_field_total"] - 1)
        self.assertEqual(score["invented_field_claims"], 1)
        self.assertEqual(score["unsupported_source_claims"], 1)
        self.assertEqual(score["omitted_literal_gold_claims"], 0)
        self.assertAlmostEqual(
            score["all_source_exact_precision"],
            (len(context.visible_cards) - 1) / (len(context.visible_cards) + 1),
        )

    def test_malformed_extra_claim_is_in_precision_denominator_and_blocks_release(self):
        context = next(c for c in self.contexts if c.variant == "clean"
                       and c.condition == "full_evidence"
                       and c.expected_decision is Decision.AUTO_EXECUTE)
        payload = json.loads(_perfect_output(context))
        payload["claims"].append({"kind": "ACTIVE-HOLD"})
        parsed = parse_extraction_output(json.dumps(payload), {e.event_id: e.content for e in context.active_events})
        score = score_extraction(context, parsed)
        self.assertEqual(score["candidate_decision"], Decision.AUTO_EXECUTE.value)
        self.assertEqual(score["decision"], Decision.HANDOFF.value)
        self.assertTrue(score["format_fail_closed"])
        self.assertTrue(score["candidate_route_matches_visible_oracle"])
        self.assertFalse(score["route_matches_visible_oracle"])
        self.assertAlmostEqual(
            score["all_source_exact_precision"],
            len(context.visible_cards) / (len(context.visible_cards) + 1),
        )
        self.assertIn("dropped malformed claims", EXTRACTION_METRIC_DEFINITIONS["all_source_exact_precision/recall"])

    def test_rendering_preserves_card_subject_and_time_instead_of_action(self):
        context = self.contexts[0]
        card = next(c for c in context.visible_cards if c.kind is ProofCardKind.AUTHORITY)
        changed = replace(card, subject_id="other-agent", valid_until="2026-10-06T18:00:00+08:00")
        text = render_card_text(changed, context.action, context.policy)
        self.assertIn("other-agent", text)
        self.assertIn(changed.valid_until, text)
        self.assertNotIn(context.action.actor_id, text)


class NaturalLanguageRunnerTest(unittest.TestCase):
    def setUp(self):
        self.contexts = build_nl_contexts(variants=("clean",), splits=("dev",))[:3]
        self.config = GenerationConfig(model="fake-local", max_tokens=2400)

    def test_plan_freezes_prompts_config_and_dataset_without_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = runner.output_paths("nl_test_v1", Path(directory))
            plan = runner.build_plan(self.contexts, self.config, "http://127.0.0.1:11434", paths)
            self.assertEqual(plan["model_calls"], 3)
            self.assertEqual(plan["status"], "PLAN_ONLY_NO_MODEL_CALLS")
            self.assertEqual(len(plan["prompt_hashes"]), 3)
            self.assertEqual(plan["configuration"]["seed"], 5203)
            self.assertEqual(len(plan["dataset_sha256"]), 64)
            self.assertFalse(any(path.exists() for path in paths.values()))

    def test_model_free_client_fixture_produces_auditable_bundle_and_refuses_reuse(self):
        contexts = self.contexts
        class Client:
            def generate(self, prompt, config):
                context = next(c for c in contexts if build_extraction_prompt(c) == prompt)
                return ModelResponse(_perfect_output(context), 100, 200, 1.0, "fake-local", "fixture")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = runner.output_paths("nl_test_v1", Path(directory))
            plan = runner.build_plan(contexts, self.config, "http://127.0.0.1:11434", paths)
            audit = runner.run_experiment(contexts, self.config, plan, paths, Client())
            self.assertEqual(audit["status"], "PASS")
            manifest = json.loads(paths["manifest"].read_text())
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["completed_model_calls"], 3)
            self.assertEqual(manifest["prompt_tokens"], 300)
            self.assertEqual(manifest["completion_tokens"], 600)
            self.assertEqual(set(manifest["artifact_sha256"]), {"raw", "summary", "audit"})
            with self.assertRaises(FileExistsError):
                runner.run_experiment(contexts, self.config, plan, paths, Client())

    def test_launch_failure_preserves_manifest_raw_summary_and_failed_audit(self):
        class Client:
            def generate(self, prompt, config):
                raise RuntimeError("fixture offline")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = runner.output_paths("nl_test_v1", Path(directory))
            plan = runner.build_plan(self.contexts, self.config, "http://127.0.0.1:11434", paths)
            with self.assertRaisesRegex(RuntimeError, "fixture offline"):
                runner.run_experiment(self.contexts, self.config, plan, paths, Client())
            manifest = json.loads(paths["manifest"].read_text())
            self.assertEqual(manifest["status"], "FAILED")
            self.assertEqual(manifest["completed_model_calls"], 0)
            self.assertEqual(manifest["attempted_model_calls"], 1)
            self.assertEqual(json.loads(paths["audit"].read_text())["status"], "FAIL")
            self.assertTrue(all(p.exists() for p in paths.values()))

    def test_partial_invalid_extraction_is_recorded_without_retry(self):
        class Client:
            def generate(self, prompt, config):
                return ModelResponse('{"claims":[{"kind":"ACTIVE-HOLD"}]}', 10, 20, 1.0, "fake-local")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = runner.output_paths("nl_test_v1", Path(directory))
            plan = runner.build_plan(self.contexts, self.config, "http://127.0.0.1:11434", paths)
            audit = runner.run_experiment(self.contexts, self.config, plan, paths, Client())
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["summary"]["all"]["format_errors"], 3)
            self.assertEqual(audit["format_valid_records"], 0)
            records = [json.loads(line) for line in paths["raw"].read_text().splitlines()]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(record["score"]["decision"] == Decision.HANDOFF.value for record in records))

    def test_plan_rejects_remote_endpoint_and_unsafe_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = runner.output_paths("nl_test_v1", Path(directory))
            with self.assertRaises(ValueError):
                runner.build_plan(self.contexts, self.config, "https://example.com", paths)
            with self.assertRaises(ValueError):
                runner.output_paths("../overwrite", Path(directory))

    def test_audit_detects_prompt_tampering(self):
        contexts = self.contexts
        class Client:
            def generate(self, prompt, config):
                context = next(c for c in contexts if build_extraction_prompt(c) == prompt)
                return ModelResponse(_perfect_output(context), 100, 200, 1.0, "fake-local")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = runner.output_paths("nl_test_v1", Path(directory))
            plan = runner.build_plan(contexts, self.config, "http://127.0.0.1:11434", paths)
            runner.run_experiment(contexts, self.config, plan, paths, Client())
            records = [json.loads(line) for line in paths["raw"].read_text().splitlines()]
            records[0]["prompt"] += "tampered"
            self.assertEqual(runner.audit_records(records, contexts, plan)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
