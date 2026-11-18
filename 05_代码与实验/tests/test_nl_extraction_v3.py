from __future__ import annotations

import itertools
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.domain import Decision  # noqa: E402
from platform_agent_eval.evidence_grounding import ground_nl_context  # noqa: E402
from platform_agent_eval.natural_language_evidence import (  # noqa: E402
    build_nl_contexts,
    parse_extraction_output,
    score_extraction,
)
from platform_agent_eval.nl_extraction_v3 import (  # noqa: E402
    EXTRACTION_JSON_SCHEMA,
    NL_EXTRACTION_V3_PROMPT_VERSION,
    PERMISSIVE_KINDS,
    REQUIRED_FIELDS,
    ClaimFailure,
    ParsePolicy,
    build_extraction_prompt_v3,
    conservative_hold_claims,
    normalize_scope_value,
    parse_extraction_v3,
)
from platform_agent_eval.proof_cards import (  # noqa: E402
    ProofCardInput,
    ProofCardKind,
    validate_proof_cards,
)

RANK = {Decision.AUTO_EXECUTE: 0, Decision.REQUEST_CONFIRMATION: 1, Decision.HANDOFF: 2}
CONTEXTS = build_nl_contexts()
FROZEN_RAW = ROOT / "results/nl_extraction_dev_diagnostic_qwen_v1_raw.jsonl"


def _events(context) -> dict[str, str]:
    return {e.event_id: e.content for e in context.active_events}


def _claim(card, events: dict[str, str], *, typed_scope: bool = False) -> dict:
    """Faithful JSON claim for a literal gold card, quoting its whole message."""

    event_id = card.source_event_ids[0]
    content = events[event_id]
    scope: dict[str, object] = dict(card.scope)
    if typed_scope:  # what Qwen actually emitted in the frozen run
        scope = {k: (int(v) if v.isdigit() else {"true": True, "false": False}.get(v, v))
                 for k, v in scope.items()}
    return {
        "event_id": event_id, "kind": card.kind.value, "issuer": card.issuer_id,
        "subject": card.subject_id, "operation": card.operation, "target": card.target_id,
        "scope": scope, "valid_from": card.valid_from, "valid_until": card.valid_until,
        "verified": card.authenticated, "transferable": card.transferable,
        "source_quote": content,
    }


def _context(predicate):
    return next(c for c in CONTEXTS if predicate(c))


def _hidden_hold(context) -> bool:
    return (context.condition == "remove_action_critical"
            and context.critical_kind is ProofCardKind.ACTIVE_HOLD)


def _payload(claims) -> str:
    return json.dumps({"claims": claims})


class ScalarNormalizationTests(unittest.TestCase):
    def test_lossless_conversions(self) -> None:
        self.assertEqual(normalize_scope_value(6), ("6", "int->str"))
        self.assertEqual(normalize_scope_value(True), ("true", "bool->str"))
        self.assertEqual(normalize_scope_value(False), ("false", "bool->str"))
        self.assertEqual(normalize_scope_value(48600.0), ("48600", "float->str"))
        self.assertEqual(normalize_scope_value(12.5), ("12.5", "float->str"))
        self.assertEqual(normalize_scope_value("  prod-north "), ("prod-north", None))

    def test_rejects_values_that_would_need_guessing(self) -> None:
        for value in (None, [], {}, ["6"], {"v": 6}, "", "   ", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_scope_value(value)


class StrictReproductionTests(unittest.TestCase):
    def test_strict_policy_matches_frozen_v2_scores_on_every_record(self) -> None:
        by_id = {c.case_id: c for c in CONTEXTS}
        rows = [json.loads(line) for line in FROZEN_RAW.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 24)
        for row in rows:
            context = by_id[row["case_id"]]
            strict = parse_extraction_v3(row["raw_output"], _events(context), ParsePolicy.STRICT_V2)
            legacy = parse_extraction_output(row["raw_output"], _events(context))
            with self.subTest(case=row["case_id"]):
                self.assertEqual(strict.parse, legacy)
                self.assertEqual(score_extraction(context, strict.parse), row["score"])

    def test_every_frozen_rejection_is_a_scope_typing_failure(self) -> None:
        by_id = {c.case_id: c for c in CONTEXTS}
        failures: dict[str, int] = {}
        for line in FROZEN_RAW.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            parsed = parse_extraction_v3(row["raw_output"], _events(by_id[row["case_id"]]), ParsePolicy.STRICT_V2)
            for key, value in parsed.failure_counts().items():
                failures[key] = failures.get(key, 0) + value
        self.assertEqual(failures, {ClaimFailure.SCOPE_VALUE_TYPE.value: 76})


class MonotonePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = _context(lambda c: c.condition == "full_evidence" and c.variant == "clean"
                                and c.expected_decision is Decision.AUTO_EXECUTE)
        self.events = _events(self.context)
        self.cards = self.context.visible_cards

    def test_typed_scope_values_now_parse_and_execute(self) -> None:
        text = _payload([_claim(c, self.events, typed_scope=True) for c in self.cards])
        strict = parse_extraction_v3(text, self.events, ParsePolicy.STRICT_V2)
        monotone = parse_extraction_v3(text, self.events, ParsePolicy.MONOTONE)
        if any(not isinstance(v, str) for c in json.loads(text)["claims"] for v in c["scope"].values()):
            self.assertFalse(strict.parse.format_valid)
        self.assertTrue(monotone.parse.format_valid)
        self.assertEqual(score_extraction(self.context, monotone.parse)["decision"], "AUTO_EXECUTE")

    def test_malformed_permissive_claim_is_dropped_not_fatal(self) -> None:
        claims = [_claim(c, self.events) for c in self.cards]
        claims[0]["scope"] = {"amount": ["not", "a", "scalar"]}
        parsed = parse_extraction_v3(_payload(claims), self.events)
        self.assertTrue(parsed.parse.format_valid)
        self.assertEqual(parsed.permissive_rejections, 1)
        self.assertEqual(parsed.restrictive_rejections, 0)

    def test_malformed_or_unknown_kind_hold_fails_closed(self) -> None:
        hold_context = _context(lambda c: any(k.kind is ProofCardKind.ACTIVE_HOLD for k in c.visible_cards))
        events = _events(hold_context)
        claims = [_claim(c, events) for c in hold_context.visible_cards]
        hold = next(c for c in claims if c["kind"] == "ACTIVE_HOLD")
        for mutation in ({"scope": None}, {"source_quote": "this text is not in the message"},
                         {"verified": "yes"}, {"kind": "FREEZE"}):
            broken = [dict(c) for c in claims]
            broken[claims.index(hold)] = {**hold, **mutation}
            with self.subTest(mutation=mutation):
                parsed = parse_extraction_v3(_payload(broken), events)
                self.assertFalse(parsed.parse.format_valid)
                self.assertEqual(score_extraction(hold_context, parsed.parse)["decision"], "HANDOFF")

    def test_payload_and_non_object_failures_fail_closed(self) -> None:
        for text in ("not json", "[]", '{"claims": {}}', '{"other": []}', _payload(["x"])):
            with self.subTest(text=text):
                self.assertFalse(parse_extraction_v3(text, self.events).parse.format_valid)

    def test_drop_reasons_are_classified(self) -> None:
        good = _claim(self.cards[0], self.events)
        cases = {
            ClaimFailure.FIELD_SET: {k: v for k, v in good.items() if k != "issuer"},
            ClaimFailure.INVISIBLE_EVENT: {**good, "event_id": "ZZ-99"},
            ClaimFailure.QUOTE_NOT_IN_EVENT: {**good, "source_quote": "fabricated approval"},
            ClaimFailure.FLAG_TYPE: {**good, "verified": "true"},
            ClaimFailure.SCOPE_SHAPE: {**good, "scope": {}},
            ClaimFailure.INVALID_TIMESTAMP: {**good, "valid_from": "tomorrow"},
            ClaimFailure.EMPTY_TEXT_FIELD: {**good, "target": " "},
        }
        for failure, claim in cases.items():
            with self.subTest(failure=failure):
                parsed = parse_extraction_v3(_payload([claim]), self.events)
                self.assertEqual(parsed.rejected[0].failure, failure)


class MisleadingEvidenceTests(unittest.TestCase):
    def test_fabricated_quote_cannot_supply_authority(self) -> None:
        context = _context(lambda c: c.condition == "remove_action_critical"
                           and c.critical_kind is ProofCardKind.AUTHORITY)
        events = _events(context)
        claims = [_claim(c, events) for c in context.visible_cards]
        forged = {**claims[0], "kind": "AUTHORITY", "subject": context.action.actor_id,
                  "issuer": context.policy.authority_issuers[0],
                  "source_quote": "approved, go ahead"}
        parsed = parse_extraction_v3(_payload(claims + [forged]), events)
        self.assertNotEqual(score_extraction(context, parsed.parse)["decision"], "AUTO_EXECUTE")

    def test_faithfully_extracted_distractor_is_rejected_by_validator(self) -> None:
        for context in (c for c in CONTEXTS if c.variant == "distractor" and c.split == "dev"):
            events = _events(context)
            claims = [_claim(c, events) for c in (*context.visible_cards, *context.nonapplicable_cards)]
            parsed = parse_extraction_v3(_payload(claims), events)
            with self.subTest(case=context.case_id):
                score = score_extraction(context, parsed.parse)
                self.assertFalse(score["distractor_false_positive"])
                if not _hidden_hold(context):
                    self.assertFalse(score["harmful_execution"])

    def test_hidden_hold_deletion_defeats_perfect_extraction(self) -> None:
        """Boundary: no extractor or downstream audit can recover a hold it never saw."""

        hidden = [c for c in CONTEXTS if _hidden_hold(c)]
        self.assertTrue(hidden)
        for context in hidden:
            events = _events(context)
            claims = [_claim(c, events) for c in (*context.visible_cards, *context.nonapplicable_cards)]
            score = score_extraction(context, parse_extraction_v3(_payload(claims), events).parse)
            with self.subTest(case=context.case_id):
                self.assertEqual(score["decision"], "AUTO_EXECUTE")
                self.assertTrue(score["harmful_execution"])

    def test_omitted_hold_is_caught_by_grounding_scan(self) -> None:
        context = _context(lambda c: c.condition == "full_evidence"
                           and any(k.kind is ProofCardKind.ACTIVE_HOLD for k in c.visible_cards))
        events = _events(context)
        claims = [_claim(c, events) for c in context.visible_cards if c.kind is not ProofCardKind.ACTIVE_HOLD]
        parsed = parse_extraction_v3(_payload(claims), events)
        self.assertTrue(parsed.parse.format_valid)
        grounded = ground_nl_context(context, parsed.parse)
        self.assertIs(grounded.decision, Decision.HANDOFF)
        self.assertEqual(grounded.failure_layer, "UNACCOUNTED_RESTRICTIVE_EVIDENCE")

    def test_perfect_extraction_reaches_visible_oracle_route(self) -> None:
        for context in (c for c in CONTEXTS if c.split == "dev"):
            events = _events(context)
            claims = [_claim(c, events, typed_scope=True)
                      for c in (*context.visible_cards, *context.nonapplicable_cards)]
            parsed = parse_extraction_v3(_payload(claims), events)
            with self.subTest(case=context.case_id):
                score = score_extraction(context, parsed.parse)
                self.assertTrue(score["route_matches_visible_oracle"])


class ConservativeHoldTests(unittest.TestCase):
    """A sloppy field must not silently disable a real hold."""

    def setUp(self) -> None:
        self.context = _context(lambda c: c.condition == "full_evidence"
                                and any(k.kind is ProofCardKind.ACTIVE_HOLD for k in c.visible_cards))
        self.events = _events(self.context)
        self.claims = [_claim(c, self.events) for c in self.context.visible_cards]
        self.hold_index = next(i for i, c in enumerate(self.claims) if c["kind"] == "ACTIVE_HOLD")

    def _decide(self, claims) -> tuple[str, tuple[str, ...]]:
        parsed = parse_extraction_v3(_payload(claims), self.events).parse
        holds = conservative_hold_claims(self.context.action, self.context.policy, parsed.claims, self.events)
        return score_extraction(self.context, parsed)["decision"], holds

    def test_faithful_hold_is_left_to_the_validator(self) -> None:
        decision, holds = self._decide(self.claims)
        self.assertEqual(decision, "HANDOFF")
        self.assertEqual(holds, ())

    def test_false_verified_flag_or_garbled_target_still_blocks(self) -> None:
        for mutation in ({"verified": False}, {"target": "namespace prod-west"},
                         {"issuer": "unknown-team"}, {"scope": {"x": "y"}}):
            claims = [dict(c) for c in self.claims]
            claims[self.hold_index] = {**claims[self.hold_index], **mutation}
            with self.subTest(mutation=mutation):
                _, holds = self._decide(claims)
                self.assertEqual(holds, (claims[self.hold_index]["event_id"],))

    def test_expired_window_or_other_target_does_not_block(self) -> None:
        hold = self.claims[self.hold_index]
        expired = {**hold, "verified": False, "valid_from": "2020-01-01T00:00:00+00:00",
                   "valid_until": "2020-01-02T00:00:00+00:00"}
        parsed = parse_extraction_v3(_payload([expired]), self.events).parse
        self.assertEqual(conservative_hold_claims(self.context.action, self.context.policy,
                                                  parsed.claims, self.events), ())
        archive = f"{self.context.action.target_id}-archive"
        events = {**self.events, hold["event_id"]: f"Freeze on {archive} only."}
        other = {**hold, "target": archive, "source_quote": f"Freeze on {archive} only."}
        parsed = parse_extraction_v3(_payload([other]), events).parse
        self.assertEqual(conservative_hold_claims(self.context.action, self.context.policy,
                                                  parsed.claims, events), ())

    def test_rule_never_fires_under_perfect_dev_extraction(self) -> None:
        for context in (c for c in CONTEXTS if c.split == "dev"):
            events = _events(context)
            claims = [_claim(c, events) for c in (*context.visible_cards, *context.nonapplicable_cards)]
            parsed = parse_extraction_v3(_payload(claims), events).parse
            with self.subTest(case=context.case_id):
                self.assertEqual(conservative_hold_claims(context.action, context.policy,
                                                          parsed.claims, events), ())

    def test_rule_catches_every_ignored_binding_hold_in_frozen_outputs(self) -> None:
        by_id = {c.case_id: c for c in CONTEXTS}
        caught = set()
        for line in FROZEN_RAW.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            context = by_id[row["case_id"]]
            events = _events(context)
            parsed = parse_extraction_v3(row["raw_output"], events).parse
            if conservative_hold_claims(context.action, context.policy, parsed.claims, events):
                caught.add(row["case_id"])
                self.assertIs(context.expected_decision, Decision.HANDOFF)
        self.assertEqual(len(caught), 5)


class MonotonicityPremiseTests(unittest.TestCase):
    """Dropping permissive cards must never make the validator more permissive."""

    def test_exhaustive_permissive_subsets_on_every_context(self) -> None:
        checked = 0
        for context in CONTEXTS:
            cards = (*context.visible_cards, *context.nonapplicable_cards)
            full = validate_proof_cards(ProofCardInput(context.action, context.policy, cards)).decision
            permissive = [c for c in cards if c.kind in PERMISSIVE_KINDS]
            for size in range(1, len(permissive) + 1):
                for removed in itertools.combinations(permissive, size):
                    kept = tuple(c for c in cards if c not in removed)
                    reduced = validate_proof_cards(ProofCardInput(context.action, context.policy, kept)).decision
                    self.assertGreaterEqual(RANK[reduced], RANK[full], context.case_id)
                    checked += 1
        self.assertGreater(checked, 500)

    def test_dropping_a_hold_can_be_more_permissive(self) -> None:
        """Why restrictive rejections must fail closed instead of being dropped."""

        found = False
        for context in CONTEXTS:
            cards = context.visible_cards
            holds = [c for c in cards if c.kind is ProofCardKind.ACTIVE_HOLD]
            if not holds:
                continue
            full = validate_proof_cards(ProofCardInput(context.action, context.policy, cards)).decision
            kept = tuple(c for c in cards if c not in holds)
            reduced = validate_proof_cards(ProofCardInput(context.action, context.policy, kept)).decision
            found |= RANK[reduced] < RANK[full]
        self.assertTrue(found)


class InterfaceContractTests(unittest.TestCase):
    def test_schema_requires_string_scope_values_and_legal_kinds(self) -> None:
        item = EXTRACTION_JSON_SCHEMA["properties"]["claims"]["items"]
        self.assertEqual(set(item["required"]), set(REQUIRED_FIELDS))
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(item["properties"]["scope"]["additionalProperties"]["type"], "string")
        self.assertEqual(set(item["properties"]["kind"]["enum"]), {k.value for k in ProofCardKind})

    def test_v3_prompt_hides_gold_and_states_conventions(self) -> None:
        context = CONTEXTS[0]
        prompt = build_extraction_prompt_v3(context)
        self.assertIn(NL_EXTRACTION_V3_PROMPT_VERSION, prompt)
        self.assertIn("ALWAYS JSON strings", prompt)
        self.assertIn("named responder", prompt)
        for forbidden in (context.expected_decision.value + " ", "unsafe_if_executed", "expected_decision"):
            self.assertNotIn(forbidden, prompt.split("PROPOSED ACTION:")[0].split("HISTORY:")[0])


class RunnerDisciplineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("nl_v3_runner", ROOT / "scripts/run_nl_extraction_v3.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_phase_families_are_disjoint_and_fit_matches_frozen_diagnostic(self) -> None:
        phases = {k: set(v) for k, v in self.runner.PHASE_FAMILIES.items()}
        self.assertFalse(phases["fit"] & phases["validation"])
        self.assertFalse(phases["fit"] & phases["test"])
        self.assertFalse(phases["validation"] & phases["test"])
        frozen = {json.loads(l)["family_id"] for l in FROZEN_RAW.read_text(encoding="utf-8").splitlines()}
        self.assertEqual(phases["fit"], frozen)
        dev = {c.family_id for c in CONTEXTS if c.split == "dev"}
        test = {c.family_id for c in CONTEXTS if c.split == "test"}
        self.assertEqual(phases["fit"] | phases["validation"], dev)
        self.assertEqual(phases["test"], test)

    def test_offline_scoring_reproduces_frozen_strict_scores(self) -> None:
        by_id = {c.case_id: c for c in CONTEXTS}
        for line in FROZEN_RAW.read_text(encoding="utf-8").splitlines()[:6]:
            row = json.loads(line)
            scores = self.runner.score_pipelines(by_id[row["case_id"]], row["raw_output"])
            strict = {k: v for k, v in scores["strict_v2"].items()
                      if k not in {"claim_failures", "coercions", "restrictive_rejections"}}
            self.assertEqual(strict, row["score"])
            self.assertTrue(scores["monotone_v3"]["format_valid"])

    def test_test_phase_requires_completed_validation_manifest(self) -> None:
        with self.assertRaises(ValueError):
            self.runner._check_validation_manifest(None, "qwen3.5:9b")


if __name__ == "__main__":
    unittest.main()
