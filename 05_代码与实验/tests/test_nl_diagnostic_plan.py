from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platform_agent_eval.model_routing import GenerationConfig, ModelResponse, OllamaClient
from platform_agent_eval.natural_language_evidence import build_extraction_prompt, build_nl_contexts

spec = importlib.util.spec_from_file_location("nl_diagnostic_runner", ROOT / "scripts/run_nl_evidence_extraction.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAMILIES = ("nl-typed-v7", "nl-typed-c4", "nl-typed-d8", "nl-typed-r5")


def perfect_output(context):
    text = {event.event_id: event.content for event in context.active_events}
    return json.dumps({"claims": [{
        "event_id": card.source_event_ids[0], "kind": card.kind.value,
        "issuer": card.issuer_id, "subject": card.subject_id,
        "operation": card.operation, "target": card.target_id,
        "scope": dict(card.scope), "valid_from": card.valid_from,
        "valid_until": card.valid_until, "verified": card.authenticated,
        "transferable": card.transferable,
        "source_quote": text[card.source_event_ids[0]],
    } for card in (*context.visible_cards, *context.nonapplicable_cards)]})


class NLDiagnosticPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contexts = runner.select_contexts(
            build_nl_contexts(splits=("dev",)), FAMILIES,
        )

    def test_selection_is_four_dev_families_and_complete_variant_triples(self):
        contexts = self.contexts
        self.assertEqual(24, len(contexts))
        self.assertEqual({"dev"}, {c.split for c in contexts})
        self.assertEqual(3, len({c.domain for c in contexts}))
        self.assertEqual(3, len({c.expected_decision for c in contexts if c.condition == "full_evidence"}))
        for family in FAMILIES:
            selected = [c for c in contexts if c.family_id == family]
            self.assertEqual(6, len(selected))
            self.assertEqual({"clean", "distractor"}, {c.variant for c in selected})
        self.assertEqual(94, sum(len(c.visible_cards) + len(c.nonapplicable_cards) for c in contexts))

    def test_multi_variant_limit_and_unknown_family_cannot_silently_miss_pairs(self):
        with self.assertRaisesRegex(ValueError, "multi-variant"):
            runner.select_contexts(self.contexts, limit=18)
        with self.assertRaisesRegex(ValueError, "unknown"):
            runner.select_contexts(self.contexts, ("not-a-family",))
        with self.assertRaises(ValueError):
            runner.select_contexts(self.contexts, limit=2)

    def test_frozen_plan_refuses_drift_and_cannot_be_created_during_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plan.json"
            with self.assertRaisesRegex(ValueError, "plan-only"):
                runner.freeze_or_verify_plan({"config": 1}, path, running=True)
            runner.freeze_or_verify_plan({"config": 1}, path, running=False)
            runner.freeze_or_verify_plan({"config": 1}, path, running=True)
            with self.assertRaisesRegex(ValueError, "differs"):
                runner.freeze_or_verify_plan({"config": 2}, path, running=True)
            self.assertEqual({"config": 1}, json.loads(path.read_text()))

    def test_perfect_fixture_separates_upstream_hidden_holds_and_extraction(self):
        contexts = self.contexts
        class Client:
            def generate(self, prompt, config):
                context = next(c for c in contexts if build_extraction_prompt(c) == prompt)
                return ModelResponse(perfect_output(context), 100, 200, 1.0, "fixture", "fixture-digest")
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            paths = runner.output_paths("nl_fixture_v2", Path(folder))
            config = GenerationConfig(model="fixture", max_tokens=3072)
            plan = runner.build_plan(contexts, config, "http://127.0.0.1:11434", paths)
            audit = runner.run_experiment(contexts, config, plan, paths, Client())
        self.assertEqual("PASS", audit["status"])
        summary = audit["summary"]["all"]
        self.assertEqual(1.0, summary["visible_oracle_agreement"])
        self.assertAlmostEqual(22 / 24, summary["route_accuracy"])
        self.assertEqual(1.0, summary["mean_all_source_exact_recall"])
        self.assertEqual(940, summary["matched_field_correct"])
        pairs = audit["paired_diagnostics"]
        self.assertEqual(12, len(pairs["clean_distractor_pairs"]))
        self.assertEqual(8, len(pairs["noise_pairs"]))
        self.assertEqual(0, pairs["noise_route_changes"])
        self.assertEqual(2, pairs["world_errors_matching_visible_oracle"])
        self.assertEqual(0, pairs["visible_oracle_disagreements"])

    def test_explicit_context_window_is_sent_without_changing_legacy_default(self):
        requests = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"message": {"content": "{}"}, "model": "fixture",
                                   "prompt_eval_count": 10, "eval_count": 2}).encode()
        def urlopen(request, **kwargs):
            requests.append(json.loads(request.data))
            return Response()
        for window in (None, 8192):
            client = OllamaClient(num_ctx=window)
            client._digest_cache["fixture"] = "fixture-digest"
            with patch("urllib.request.urlopen", side_effect=urlopen):
                client.generate("fixture", GenerationConfig(model="fixture"))
        self.assertNotIn("num_ctx", requests[0]["options"])
        self.assertEqual(8192, requests[1]["options"]["num_ctx"])
        for invalid in (0, -1, True):
            with self.assertRaises(ValueError):
                OllamaClient(num_ctx=invalid)


if __name__ == "__main__":
    unittest.main()
