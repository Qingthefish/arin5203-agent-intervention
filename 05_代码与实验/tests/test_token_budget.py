from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from platform_agent_eval.token_budget import (
    OllamaRawTokenCounter,
    TokenCount,
)
from audit_exact_token_budgets import (
    assert_paths_available,
    build_plan,
    count_records,
    load_config,
    output_paths,
    token_budget_audit,
)


class FakeCounter:
    def count(self, text: str) -> TokenCount:
        return TokenCount(
            token_count=len(text.split()),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            latency_ms=1.0,
            model_id="fake-model",
        )


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.buffer = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.buffer.read()


class TokenCounterTests(unittest.TestCase):
    def test_ollama_counter_uses_raw_prompt_and_one_probe_token(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(request, timeout):
            captured["payload"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return FakeResponse(
                {"model": "qwen3.5:9b", "prompt_eval_count": 7, "response": "x"}
            )

        counter = OllamaRawTokenCounter(model="qwen3.5:9b", timeout_seconds=12.0)
        with patch("urllib.request.urlopen", fake_open):
            result = counter.count("seven token test")
        self.assertEqual(7, result.token_count)
        payload = captured["payload"]
        self.assertTrue(payload["raw"])
        self.assertFalse(payload["stream"])
        self.assertEqual(1, payload["options"]["num_predict"])
        self.assertEqual("seven token test", payload["prompt"])
        self.assertEqual(12.0, captured["timeout"])

    def test_counter_rejects_empty_text(self) -> None:
        with self.assertRaises(ValueError):
            OllamaRawTokenCounter(model="qwen3.5:9b").count("")


class TokenAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "token_budget_audit.json")

    def test_plan_covers_all_old_records_without_calls(self) -> None:
        plan = build_plan(self.config)
        self.assertEqual("PLAN_ONLY_NO_TOKEN_COUNT_CALLS", plan["status"])
        self.assertEqual(55, plan["source_records"])
        self.assertEqual(55, plan["raw_token_count_calls"])
        self.assertEqual(55, plan["generated_probe_tokens"])
        self.assertEqual(0.0, plan["external_api_cost_usd"])

    def test_artifacts_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = output_paths("trial", results_dir=Path(directory))
            assert_paths_available(paths)
            paths["manifest"].touch()
            with self.assertRaises(FileExistsError):
                assert_paths_available(paths)

    def test_count_records_preserves_source_identity(self) -> None:
        source = [
            {
                "source_artifact": "results/source.jsonl",
                "source_row": 1,
                "scenario_id": "s1",
                "strategy": "generic_summary",
                "active_context": "one two three four",
                "active_context_estimated_tokens": 8,
                "model_digest": "digest",
            }
        ]
        counted = count_records(source, FakeCounter())
        self.assertEqual(4, counted[0]["exact_raw_tokens"])
        self.assertEqual(2.0, counted[0]["heuristic_to_exact_ratio"])
        self.assertEqual("s1", counted[0]["scenario_id"])

    def test_audit_detects_strategy_budget_mismatch(self) -> None:
        records: list[dict[str, object]] = []
        means = {
            "tail_truncation": 100,
            "generic_summary": 110,
            "rule_pinning": 300,
            "selective_hitl": 160,
            "full_context": 500,
        }
        for strategy, tokens in means.items():
            records.append(
                {
                    "source_artifact": "results/source.jsonl",
                    "scenario_id": "s1",
                    "strategy": strategy,
                    "exact_raw_tokens": tokens,
                    "heuristic_estimated_tokens": tokens,
                    "heuristic_to_exact_ratio": 1.0,
                }
            )
        audit = token_budget_audit(
            records,
            expected_records=5,
            maximum_ratio=1.1,
        )
        self.assertEqual("BUDGET_MISMATCH_CONFIRMED", audit["status"])
        self.assertEqual(
            "DO_NOT_USE_OLD_PILOTS_TO_RANK_COMPACTION_METHODS",
            audit["recommendation"],
        )
        self.assertFalse(audit["source_checks"][0]["budget_matched_within_threshold"])


if __name__ == "__main__":
    unittest.main()
