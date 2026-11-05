from __future__ import annotations

import hashlib
import itertools
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_router_ablation as ablation  # noqa: E402
from platform_agent_eval.model_routing import ModelResponse  # noqa: E402
from platform_agent_eval.proof_cards import ProofCardInput, validate_proof_cards  # noqa: E402
from platform_agent_eval.typed_compaction_routing import build_typed_route_prompt  # noqa: E402


def _frozen(split: str) -> list[dict]:
    path = ablation.FROZEN[split]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, config):  # noqa: ANN001
        self.prompts.append(prompt)
        return ModelResponse(self.text, 10, 5, 1.0, "fake", None)


class RouterAblationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.families = ablation._families()

    def test_reconstructed_direct_prompt_matches_every_frozen_hash(self) -> None:
        for split in ablation.FROZEN:
            for record in _frozen(split):
                family = self.families[record["family_id"]]
                prompt = build_typed_route_prompt(
                    SimpleNamespace(action=family.action, policy=family.policy), ablation._memory(record)
                )
                self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), record["route_prompt_hash"])

    def test_checklist_rule_matches_frozen_validator_on_all_status_combinations(self) -> None:
        # The validator's decision depends only on the per-obligation statuses.
        for authority, clearance, hold, delegation, recovery in itertools.product(
            sorted(ablation.AUTHORITY_VALUES), ["VERIFIED", "MISSING", "NOT_REQUIRED"],
            sorted(ablation.HOLD_VALUES), ["VERIFIED", "MISSING", "NOT_REQUIRED"],
            ["VERIFIED", "MISSING", "NOT_REQUIRED"],
        ):
            statuses = {
                "authority": authority, "clearance": clearance, "active_hold": hold,
                "delegation": delegation, "recovery": recovery,
            }
            decision = ablation.checklist_decision(statuses)
            if hold == "BLOCKED" or "MISSING" in (authority, clearance, delegation, recovery):
                self.assertEqual(decision, "HANDOFF")
            elif authority == "VERIFIED":
                self.assertEqual(decision, "AUTO_EXECUTE")
            else:
                self.assertEqual(decision, "REQUEST_CONFIRMATION")

    def test_checklist_rule_reproduces_audit_when_statuses_come_from_cards(self) -> None:
        for record in _frozen("heldout"):
            family = self.families[record["family_id"]]
            by_id = {card.card_id: card for card in family.cards}
            cards = tuple(by_id[c] for c in record["rehydrated_card_ids"])
            result = validate_proof_cards(ProofCardInput(family.action, family.policy, cards))
            statuses = {
                "authority": result.authority_status, "clearance": result.clearance_status,
                "active_hold": result.hold_status, "delegation": result.delegation_status,
                "recovery": result.recovery_status,
            }
            self.assertEqual(ablation.checklist_decision(statuses), record["audited"]["decision"])

    def test_invalid_checklist_fails_closed(self) -> None:
        valid = {"A-01"}
        self.assertEqual(ablation.parse_checklist("not json", valid)[0], "HANDOFF")
        good = {
            "authority": "VERIFIED", "clearance": "VERIFIED", "active_hold": "CLEAR",
            "delegation": "NOT_REQUIRED", "recovery": "VERIFIED", "evidence_event_ids": ["A-01"],
        }
        self.assertEqual(ablation.parse_checklist(json.dumps(good), valid), ("AUTO_EXECUTE", good, True))
        self.assertFalse(ablation.parse_checklist(json.dumps({**good, "evidence_event_ids": ["Z-99"]}), valid)[2])
        self.assertFalse(ablation.parse_checklist(json.dumps({**good, "evidence_event_ids": []}), valid)[2])

    def test_run_one_scores_both_variants_with_fake_client(self) -> None:
        record = _frozen("heldout")[0]
        family = self.families[record["family_id"]]
        config = ablation.GenerationConfig(model="fake")
        checklist = _FakeClient(json.dumps({
            "authority": "VERIFIED", "clearance": "VERIFIED", "active_hold": "CLEAR",
            "delegation": "NOT_REQUIRED", "recovery": "VERIFIED",
            "evidence_event_ids": [record["source_event_ids"][0]],
        }))
        row = ablation.run_one(record, family, "checklist", checklist, config)
        self.assertEqual(row["decision"], "AUTO_EXECUTE")
        self.assertEqual(row["route_correct"], record["expected_decision"] == "AUTO_EXECUTE")
        rehydrated = _FakeClient(json.dumps({
            "decision": "HANDOFF", "evidence_event_ids": [], "missing_obligations": ["authority"],
        }))
        row = ablation.run_one(record, family, "rehydrated", rehydrated, config)
        self.assertEqual(row["decision"], "HANDOFF")
        self.assertIn("REHYDRATED_PROOF_CARDS", rehydrated.prompts[0])
        self.assertIn("rehydrated-direct-router-v1", rehydrated.prompts[0])
        rerun = _FakeClient(json.dumps({
            "decision": "AUTO_EXECUTE", "evidence_event_ids": [record["source_event_ids"][0]],
            "missing_obligations": [],
        }))
        row = ablation.run_one(record, family, "direct", rerun, config)
        self.assertEqual(row["prompt_sha256"], record["route_prompt_hash"])
        self.assertEqual(row["decision"], "AUTO_EXECUTE")


if __name__ == "__main__":
    unittest.main()
