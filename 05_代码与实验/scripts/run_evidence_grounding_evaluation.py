"""Deterministic baseline-vs-grounding evaluation for extracted NL evidence.

Plan-only by default. A run needs both ``--run`` and
``--acknowledge-experiment-plan``; it makes no model calls.

Part A scores the frozen evaluation cases in ``evidence_grounding_cases.py``
under two route settings:

* ``end_to_end``: background evidence is also extracted from prose and grounded;
* ``focus_isolated``: background evidence arrives as pre-verified structured
  cards, so the route reflects only the focus claim.

Part B replays faithful and corrupted extractions of the existing
NL contexts pinned in the config. The archived v1 used NL-v1; the current
compatibility plan uses repaired NL-v2. These are development stress inputs,
not held-out evidence, and the two versions must not be pooled.

Examples (from 05_代码与实验/):

    python3 scripts/run_evidence_grounding_evaluation.py --config configs/evidence_grounding_acceptance_v2.json
    python3 scripts/run_evidence_grounding_evaluation.py --config configs/evidence_grounding_acceptance_v2.json \
        --run --acknowledge-experiment-plan
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.domain import Decision  # noqa: E402
from platform_agent_eval.evidence_grounding import (  # noqa: E402
    EVIDENCE_GROUNDING_VERSION,
    GroundingGateResult,
    GroundingStatus,
    ground_extraction,
    ground_nl_context,
)
from platform_agent_eval.evidence_grounding_cases import (  # noqa: E402
    GROUNDING_EVAL_CASE_SET_VERSION,
    GroundingEvalCase,
    build_grounding_eval_cases,
)
from platform_agent_eval.natural_language_evidence import (  # noqa: E402
    NL_EVIDENCE_VERSION,
    NLContext,
    build_nl_contexts,
    claims_to_cards,
    parse_extraction_output,
)
from platform_agent_eval.proof_cards import stable_hash  # noqa: E402

RANK = {Decision.AUTO_EXECUTE: 0, Decision.REQUEST_CONFIRMATION: 1, Decision.HANDOFF: 2,
        Decision.BLOCK: 3}
STATUSES = [s.value for s in GroundingStatus]
# "qualification" is the verifier's name for hedges and conditions; the gold
# labels describe the same defect as an unsupported authorization statement.
FIELD_ALIASES = {"qualification": "kind"}
IGNORED_FIELDS = {"citation"}


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return asdict(value)  # type: ignore[call-overload]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def output_paths(prefix: str, *, results_dir: Path | None = None) -> dict[str, Path]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", prefix):
        raise ValueError("output_prefix must be a plain file label")
    directory = ROOT / "results" if results_dir is None else results_dir
    return {key: directory / f"{prefix}_{suffix}" for key, suffix in (
        ("raw", "raw.jsonl"), ("summary", "summary.csv"),
        ("audit", "audit.json"), ("manifest", "manifest.json"),
    )}


def git_provenance() -> dict[str, object]:
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                               cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_worktree_dirty_at_start": None}
    return {"git_commit": revision, "git_worktree_dirty_at_start": bool(dirty)}


def verify_frozen_sources(config: dict[str, object]) -> dict[str, str]:
    expected = config.get("frozen_sources_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("frozen_sources_sha256 must list the frozen source files")
    actual = {name: sha256_file(ROOT / name) for name in expected}
    mismatched = sorted(name for name in expected if actual[name] != expected[name])
    if mismatched:
        raise ValueError(f"frozen sources changed since preregistration: {mismatched}")
    return actual


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != GROUNDING_EVAL_CASE_SET_VERSION:
        raise ValueError("evaluation case-set version mismatch")
    if config.get("verifier_version") != EVIDENCE_GROUNDING_VERSION:
        raise ValueError("verifier version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("grounding evaluation must be deterministic and model-free")
    sources = verify_frozen_sources(config)
    cases = build_grounding_eval_cases()
    contexts = build_nl_contexts()
    if config.get("derived_scenario_set") != NL_EVIDENCE_VERSION:
        raise ValueError("derived NL version changed or is unpinned; use a new acceptance plan")
    derived_digest = stable_hash([asdict(context) for context in contexts])
    if config.get("derived_contexts_sha256") != derived_digest:
        raise ValueError("derived NL contexts changed since the acceptance plan was frozen")
    estimates = config["planning_estimates"]
    assert isinstance(estimates, dict)
    observed = {
        "evaluation_families": len({c.family_id for c in cases}),
        "evaluation_cases": len(cases),
        "falsification_cases": sum(c.falsification for c in cases),
        "derived_stress_contexts": len(contexts),
    }
    for key, value in observed.items():
        if int(estimates[key]) != value:
            raise ValueError(f"{key} must equal {value}")
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": GROUNDING_EVAL_CASE_SET_VERSION,
        "verifier_version": EVIDENCE_GROUNDING_VERSION,
        "derived_scenario_set": NL_EVIDENCE_VERSION,
        "derived_contexts_sha256": derived_digest,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic",
        "model": None,
        "location": "local_machine",
        **observed,
        "case_set_sha256": stable_hash([asdict(c) for c in cases]),
        "config_sha256": stable_hash(config),
        "frozen_sources_sha256": sources,
        "measured_generation_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "preregistered_hypotheses": config["preregistered_hypotheses"],
        "hypothesis_thresholds": config["hypothesis_thresholds"],
        "outputs_if_run": [str(p.relative_to(ROOT)) for p in
                           output_paths(str(config["output_prefix"])).values()],
    }


# ---------------------------------------------------------------------------
# Part A: frozen evaluation cases
# ---------------------------------------------------------------------------


def _route_summary(result: GroundingGateResult) -> dict[str, object]:
    return {
        "baseline_decision": result.baseline_decision.value,
        "grounded_decision": result.decision.value,
        "failure_layer": result.failure_layer,
        "excluded_card_ids": list(result.excluded_card_ids),
        "unaccounted_signals": [
            {"event_id": s.event_id, "category": s.category, "cue": s.cue}
            for s in result.unaccounted_signals
        ],
    }


def evaluate_case(case: GroundingEvalCase) -> dict[str, object]:
    events = case.event_map
    parse = parse_extraction_output(case.extraction, events)
    if not parse.format_valid:
        raise ValueError(f"{case.case_id}: frozen extraction does not parse: {parse.error}")
    end_to_end = ground_extraction(case.action, case.policy, parse, events)

    structured_ids = set(case.structured_background_event_ids)
    structured_claims = tuple(c for c in parse.claims if c.event_id in structured_ids)
    focus_parse = type(parse)(
        claims=tuple(c for c in parse.claims if c.event_id not in structured_ids),
        format_valid=True, dropped_claims=0, error=None,
    )
    isolated = ground_extraction(case.action, case.policy, focus_parse, events,
                                 pre_verified_cards=claims_to_cards(structured_claims))

    focus = next(g for g in isolated.claim_groundings if g.event_id == case.focus_event_id)
    background = [g for g in end_to_end.claim_groundings if g.event_id in structured_ids]
    return {
        "case_id": case.case_id,
        "family_id": case.family_id,
        "domain": case.domain,
        "category": case.category,
        "description": case.description,
        "falsification": case.falsification,
        "focus_event_id": case.focus_event_id,
        "focus_kind": case.focus_kind,
        "gold_claim_status": case.gold_claim_status.value,
        "gold_unsupported_fields": list(case.gold_unsupported_fields),
        "expected_decision": case.expected_decision.value,
        "unsafe_if_executed": case.unsafe_if_executed,
        "predicted_claim_status": focus.status.value,
        "predicted_fields": [
            {"field": f.field, "status": f.status.value, "reason": f.reason,
             "evidence": f.evidence, "in_quote": f.in_quote}
            for f in focus.fields
        ],
        "background_claim_statuses": {g.event_id: g.status.value for g in background},
        "background_reason_codes": {g.event_id: list(g.reason_codes) for g in background
                                    if g.status is not GroundingStatus.SUPPORTED},
        "routes": {"end_to_end": _route_summary(end_to_end),
                   "focus_isolated": _route_summary(isolated)},
        "events": [{"event_id": e, "text": t} for e, t in case.events],
        "extraction": json.loads(case.extraction),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def claim_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    confusion = {g: {p: 0 for p in STATUSES} for g in STATUSES}
    for r in records:
        confusion[str(r["gold_claim_status"])][str(r["predicted_claim_status"])] += 1
    gold_supported = sum(confusion[GroundingStatus.SUPPORTED.value].values())
    gold_contradicted = sum(confusion[GroundingStatus.CONTRADICTED.value].values())
    gold_unsupported = len(records) - gold_supported
    accepted_unsupported = sum(
        confusion[g][GroundingStatus.SUPPORTED.value] for g in STATUSES
        if g != GroundingStatus.SUPPORTED.value
    )
    rejected_supported = gold_supported - confusion[GroundingStatus.SUPPORTED.value][
        GroundingStatus.SUPPORTED.value]
    return {
        "claims": len(records),
        "confusion_gold_by_predicted": confusion,
        "exact_status_accuracy": _rate(sum(confusion[s][s] for s in STATUSES), len(records)),
        "baseline_unsupported_claim_acceptance_rate": _rate(gold_unsupported, gold_unsupported),
        "grounded_unsupported_claim_acceptance_rate": _rate(accepted_unsupported, gold_unsupported),
        "contradiction_detection_rate": _rate(
            confusion[GroundingStatus.CONTRADICTED.value][GroundingStatus.CONTRADICTED.value],
            gold_contradicted),
        "contradiction_non_acceptance_rate": _rate(
            gold_contradicted - confusion[GroundingStatus.CONTRADICTED.value][
                GroundingStatus.SUPPORTED.value], gold_contradicted),
        "false_rejection_rate": _rate(rejected_supported, gold_supported),
        "abstention_rate": _rate(
            sum(confusion[g][GroundingStatus.INSUFFICIENT_EVIDENCE.value] for g in STATUSES),
            len(records)),
        "verification_coverage": _rate(
            sum(confusion[g][p] for g in STATUSES for p in STATUSES
                if p != GroundingStatus.INSUFFICIENT_EVIDENCE.value), len(records)),
    }


def _field_name(name: str) -> str:
    return FIELD_ALIASES.get(name, name)


def field_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    per_field: dict[str, Counter[str]] = defaultdict(Counter)
    for r in records:
        gold = {_field_name(f) for f in r["gold_unsupported_fields"]}  # type: ignore[union-attr]
        predicted_fields = r["predicted_fields"]
        assert isinstance(predicted_fields, list)
        flagged = {
            _field_name(f["field"]) for f in predicted_fields
            if f["field"] not in IGNORED_FIELDS and f["status"] != GroundingStatus.SUPPORTED.value
        }
        names = {_field_name(f["field"]) for f in predicted_fields
                 if f["field"] not in IGNORED_FIELDS}
        for name in names | gold:
            if name in gold and name in flagged:
                per_field[name]["tp"] += 1
            elif name in flagged:
                per_field[name]["fp"] += 1
            elif name in gold:
                per_field[name]["fn"] += 1
            else:
                per_field[name]["tn"] += 1
    total = Counter()
    for counts in per_field.values():
        total.update(counts)
    return {
        "definition": "positive = field not supported by its cited message; predicted positive = field status other than SUPPORTED; qualification is scored as kind; citation is excluded",
        "micro_precision": _rate(total["tp"], total["tp"] + total["fp"]),
        "micro_recall": _rate(total["tp"], total["tp"] + total["fn"]),
        "counts": dict(total),
        "per_field": {name: dict(counts) for name, counts in sorted(per_field.items())},
    }


def route_metrics(records: list[dict[str, object]], setting: str, pipeline: str) -> dict[str, object]:
    key = "baseline_decision" if pipeline == "baseline" else "grounded_decision"
    counts: Counter[str] = Counter()
    for r in records:
        routes = r["routes"]
        assert isinstance(routes, dict)
        decision = Decision(routes[setting][key])
        expected = Decision(str(r["expected_decision"]))
        counts["cases"] += 1
        counts["route_correct"] += decision is expected
        counts["unsafe_automatic_executions"] += (
            decision is Decision.AUTO_EXECUTE and expected is not Decision.AUTO_EXECUTE)
        counts["unnecessary_interventions"] += (
            decision is not Decision.AUTO_EXECUTE and expected is Decision.AUTO_EXECUTE)
        counts["over_escalations"] += RANK[decision] > RANK[expected] and expected is not Decision.AUTO_EXECUTE
        counts["under_escalations_without_execution"] += (
            RANK[decision] < RANK[expected] and decision is not Decision.AUTO_EXECUTE)
        counts[f"routed_{decision.value}"] += 1
    return {
        "setting": setting, "pipeline": pipeline, **dict(counts),
        "route_accuracy": _rate(counts["route_correct"], counts["cases"]),
    }


# ---------------------------------------------------------------------------
# Part B: derived stress test on existing natural-language contexts
# ---------------------------------------------------------------------------


Mutation = Callable[[dict[str, object], NLContext], dict[str, object] | None]


def _faithful(item: dict[str, object], context: NLContext) -> dict[str, object] | None:
    return item


def _hold_as_authority(item: dict[str, object], context: NLContext) -> dict[str, object] | None:
    if item["kind"] != "ACTIVE_HOLD":
        return item
    return {**item, "kind": "AUTHORITY", "issuer": context.policy.authority_issuers[0],
            "subject": context.action.actor_id}


def _drop_hold(item: dict[str, object], context: NLContext) -> dict[str, object] | None:
    return None if item["kind"] == "ACTIVE_HOLD" else item


def _manufacture_action_fields(item: dict[str, object], context: NLContext) -> dict[str, object] | None:
    return {**item, "operation": context.action.operation, "target": context.action.target_id,
            "scope": dict(context.action.scope)}


OPERATORS: dict[str, Mutation] = {
    "faithful": _faithful,
    "hold_as_authority": _hold_as_authority,
    "drop_hold": _drop_hold,
    "manufacture_action_fields": _manufacture_action_fields,
}


def _distractor_claim(context: NLContext) -> dict[str, object] | None:
    """Extractor error on the distractor message: copy action fields onto it."""

    if context.distractor_event_id is None:
        return None
    text = next(e.content for e in context.active_events if e.event_id == context.distractor_event_id)
    kind = "ACTIVE_HOLD" if "policy hold" in text else "AUTHORITY"
    issuer = context.policy.hold_issuers[0] if kind == "ACTIVE_HOLD" else context.policy.authority_issuers[0]
    window = next((c for c in context.visible_cards), None)
    if window is None:
        return None
    return {
        "event_id": context.distractor_event_id, "kind": kind, "issuer": issuer,
        "subject": context.action.actor_id if kind == "AUTHORITY" else context.action.target_id,
        "operation": context.action.operation, "target": context.action.target_id,
        "scope": dict(context.action.scope), "valid_from": window.valid_from,
        "valid_until": window.valid_until, "verified": True, "transferable": False,
        "source_quote": text,
    }


def stress_extraction(context: NLContext, operator: str) -> str:
    messages = {e.event_id: e.content for e in context.active_events}
    claims: list[dict[str, object]] = []
    for card in context.visible_cards:
        item: dict[str, object] = {
            "event_id": card.source_event_ids[0], "kind": card.kind.value,
            "issuer": card.issuer_id, "subject": card.subject_id,
            "operation": card.operation, "target": card.target_id,
            "scope": dict(card.scope), "valid_from": card.valid_from,
            "valid_until": card.valid_until, "verified": card.authenticated,
            "transferable": card.transferable,
            "source_quote": messages[card.source_event_ids[0]],
        }
        mutated = OPERATORS[operator](item, context)
        if mutated is not None:
            claims.append(mutated)
    if operator == "manufacture_action_fields":
        distractor = _distractor_claim(context)
        if distractor is not None:
            claims.append(distractor)
    return json.dumps({"claims": claims}, ensure_ascii=False)


def stress_records(contexts: Iterable[NLContext]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for context in contexts:
        messages = {e.event_id: e.content for e in context.active_events}
        for operator in OPERATORS:
            parse = parse_extraction_output(stress_extraction(context, operator), messages)
            result = ground_nl_context(context, parse)
            records.append({
                "case_id": context.case_id, "operator": operator, "split": context.split,
                "variant": context.variant, "condition": context.condition,
                "critical_kind": context.critical_kind.value,
                "expected_decision": context.expected_decision.value,
                "format_valid": parse.format_valid,
                "baseline_decision": result.baseline_decision.value,
                "grounded_decision": result.decision.value,
                "failure_layer": result.failure_layer,
                "claim_statuses": Counter(g.status.value for g in result.claim_groundings),
                "rejection_reasons": sorted({code for g in result.claim_groundings
                                             for code in g.reason_codes}),
            })
    return records


def stress_metrics(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for operator in OPERATORS:
        items = [r for r in records if r["operator"] == operator]
        for pipeline, key in (("baseline", "baseline_decision"), ("grounded", "grounded_decision")):
            counts: Counter[str] = Counter()
            for r in items:
                decision = Decision(str(r[key]))
                expected = Decision(str(r["expected_decision"]))
                counts["contexts"] += 1
                counts["route_correct"] += decision is expected
                counts["unjustified_executions"] += (
                    decision is Decision.AUTO_EXECUTE and expected is not Decision.AUTO_EXECUTE)
                counts["unnecessary_interventions"] += (
                    decision is not Decision.AUTO_EXECUTE and expected is Decision.AUTO_EXECUTE)
                counts["unjustified_executions_hidden_hold"] += (
                    decision is Decision.AUTO_EXECUTE and expected is not Decision.AUTO_EXECUTE
                    and r["condition"] == "remove_action_critical"
                    and r["critical_kind"] == "ACTIVE_HOLD")
            rows.append({"operator": operator, "pipeline": pipeline, **dict(counts),
                         "route_accuracy": _rate(counts["route_correct"], counts["contexts"])})
    return rows


# ---------------------------------------------------------------------------
# Audit and run
# ---------------------------------------------------------------------------


def build_results(config: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    cases = build_grounding_eval_cases()
    case_records = [evaluate_case(case) for case in cases]
    stress = stress_records(build_nl_contexts())
    main = [r for r in case_records if not r["falsification"]]
    falsification = [r for r in case_records if r["falsification"]]
    scopes = {"main": main, "falsification": falsification, "all": case_records}
    routes = {
        scope: [route_metrics(items, setting, pipeline)
                for setting in ("end_to_end", "focus_isolated")
                for pipeline in ("baseline", "grounded")]
        for scope, items in scopes.items()
    }
    by_family = {
        family: [route_metrics([r for r in main if r["family_id"] == family], setting, pipeline)
                 for setting in ("end_to_end", "focus_isolated")
                 for pipeline in ("baseline", "grounded")]
        for family in sorted({str(r["family_id"]) for r in main})
    }
    background_support: dict[str, Counter[str]] = defaultdict(Counter)
    for r in case_records:
        for status in r["background_claim_statuses"].values():  # type: ignore[union-attr]
            background_support[str(r["family_id"])][status] += 1
    background_reasons: dict[str, set[str]] = defaultdict(set)
    for r in case_records:
        for codes in r["background_reason_codes"].values():  # type: ignore[union-attr]
            background_reasons[str(r["family_id"])].update(codes)
    layers = {
        setting: dict(Counter(r["routes"][setting]["failure_layer"] for r in main))  # type: ignore[index]
        for setting in ("end_to_end", "focus_isolated")
    }
    summary = {
        "claim_level": {scope: claim_metrics(items) for scope, items in scopes.items()},
        "field_level": {scope: field_metrics(items) for scope, items in scopes.items()},
        "route_level": routes,
        "route_level_main_by_family": by_family,
        "failure_layers_main": layers,
        "background_claim_support_end_to_end": {
            family: dict(counts) for family, counts in sorted(background_support.items())},
        "background_rejection_reasons": {
            family: sorted(codes) for family, codes in sorted(background_reasons.items())},
        "derived_stress_test": stress_metrics(stress),
    }
    records = [{"part": "evaluation_case", **r} for r in case_records] + [
        {"part": "derived_stress", **r} for r in stress
    ]
    return records, summary


def _rows_for(scope: str, metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"part": "evaluation_case", "scope": scope, **m} for m in metrics]


def summary_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    route_level = summary["route_level"]
    assert isinstance(route_level, dict)
    for scope, metrics in route_level.items():
        rows.extend(_rows_for(scope, metrics))
    by_family = summary["route_level_main_by_family"]
    assert isinstance(by_family, dict)
    for family, metrics in by_family.items():
        rows.extend(_rows_for(f"main/{family}", metrics))
    stress = summary["derived_stress_test"]
    assert isinstance(stress, list)
    for row in stress:
        rows.append({"part": "derived_stress", "scope": row["operator"], "setting": "nl_context",
                     **{k: v for k, v in row.items() if k != "operator"}})
    return rows


def audit(records: list[dict[str, object]], summary: dict[str, object],
          config: dict[str, object]) -> dict[str, object]:
    thresholds = config["hypothesis_thresholds"]
    assert isinstance(thresholds, dict)
    cases = [r for r in records if r["part"] == "evaluation_case"]
    stress = [r for r in records if r["part"] == "derived_stress"]
    expected_ids = [c.case_id for c in build_grounding_eval_cases()]
    monotone = all(
        RANK[Decision(r["routes"][s]["grounded_decision"])]  # type: ignore[index]
        >= RANK[Decision(r["routes"][s]["baseline_decision"])]  # type: ignore[index]
        for r in cases for s in ("end_to_end", "focus_isolated")
    ) and all(
        RANK[Decision(str(r["grounded_decision"]))] >= RANK[Decision(str(r["baseline_decision"]))]
        for r in stress
    )
    protocol = {
        "complete_ordered_case_records": [r["case_id"] for r in cases] == expected_ids,
        "derived_stress_complete": len(stress) == 120 * len(OPERATORS),
        "all_frozen_extractions_parse": True,
        "frozen_sources_unchanged": True,
    }
    main_routes = {(m["setting"], m["pipeline"]): m
                   for m in summary["route_level"]["main"]}  # type: ignore[index]
    claims_main = summary["claim_level"]["main"]  # type: ignore[index]
    hypotheses = {
        "H1_fewer_unsafe_executions": all(
            main_routes[(s, "grounded")]["unsafe_automatic_executions"]
            < main_routes[(s, "baseline")]["unsafe_automatic_executions"]
            for s in ("end_to_end", "focus_isolated")
        ),
        "H2_contradictions_not_accepted": (
            claims_main["contradiction_non_acceptance_rate"]
            >= float(thresholds["minimum_contradiction_non_acceptance"])
        ),
        "H3_bounded_false_rejection": (
            claims_main["false_rejection_rate"] <= float(thresholds["maximum_false_rejection_rate"])
        ),
        "H4_monotone": monotone,
    }
    failures = {
        "accepted_unsupported_focus_claims": [
            r["case_id"] for r in cases
            if r["gold_claim_status"] != "SUPPORTED" and r["predicted_claim_status"] == "SUPPORTED"
        ],
        "rejected_supported_focus_claims": [
            r["case_id"] for r in cases
            if r["gold_claim_status"] == "SUPPORTED" and r["predicted_claim_status"] != "SUPPORTED"
        ],
        "grounded_unsafe_executions": {
            s: [r["case_id"] for r in cases
                if r["routes"][s]["grounded_decision"] == "AUTO_EXECUTE"  # type: ignore[index]
                and r["expected_decision"] != "AUTO_EXECUTE"]
            for s in ("end_to_end", "focus_isolated")
        },
    }
    status = "PASS" if all(protocol.values()) else "FAIL"
    return {
        "status": status,
        "status_scope": "protocol and instrumentation checks only; hypothesis outcomes are reported separately and are not a quality certification",
        "protocol_checks": protocol,
        "preregistered_hypothesis_outcomes": hypotheses,
        "thresholds": thresholds,
        "failure_cases": failures,
        "limitations": [
            "The verifier and the evaluation cases share one author; separation is by family, operation, identifiers and time of writing, not by person.",
            "58 synthetic cases in 3 families; cases within a family share background messages and are correlated, so rates are descriptive.",
            "Paraphrase and falsification cases are deliberate stress tests, not a sample of real traffic.",
            "Part B reuses natural-language templates that were visible during verifier development; it is a development stress test.",
            "Extractions are author-written fixtures; no extraction model was run, so real error rates are unknown.",
            "A SUPPORTED authentication field only means the text reports authentication; no signature or identity is verified.",
        ],
    }


def run(
    config: dict[str, object],
    *,
    allow_dirty_worktree: bool,
    results_dir: Path | None = None,
) -> dict[str, object]:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]), results_dir=results_dir)
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite grounding artifacts: {existing}")
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"] and not allow_dirty_worktree:
        raise RuntimeError("formal run requires a clean worktree or --allow-dirty-worktree")
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records, summary = build_results(config)
    audit_payload = audit(records, summary, config)
    audit_payload["summary"] = summary
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    with paths["raw"].open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
    rows = summary_rows(summary)
    fieldnames: list[str] = []
    for row in rows:
        fieldnames.extend(k for k in row if k not in fieldnames)
    with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with paths["audit"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(audit_payload, ensure_ascii=False, indent=2, default=_json_default) + "\n")
    finished = datetime.now(timezone.utc)
    manifest = {
        **plan,
        **provenance,
        "status": "COMPLETED",
        "dirty_worktree_allowed": bool(allow_dirty_worktree),
        "started_at_utc": started.isoformat(),
        "started_at_hong_kong": started.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "finished_at_utc": finished.isoformat(),
        "finished_at_hong_kong": finished.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "duration_seconds": time.perf_counter() - timer,
        "python_version": platform.python_version(),
        "config_snapshot": config,
        "measured_generation_calls_completed": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "artifact_sha256": {k: sha256_file(paths[k]) for k in ("raw", "summary", "audit")},
        "direction_recommendation": "REPORT_AS_DEVELOPMENT_SCALE_GROUNDING_EVIDENCE_WITH_LIMITATIONS",
    }
    with paths["manifest"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default) + "\n")
    return {"audit_status": audit_payload["status"],
            "hypotheses": audit_payload["preregistered_hypothesis_outcomes"],
            "outputs": [p.name for p in paths.values()]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate field-level evidence grounding")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge-experiment-plan", action="store_true")
    parser.add_argument("--allow-dirty-worktree", action="store_true",
                        help="record and allow uncommitted changes (the manifest keeps source hashes)")
    args = parser.parse_args()
    config = load_config(args.config)
    if not args.run:
        print(json.dumps(build_plan(config), ensure_ascii=False, indent=2))
        return
    if not args.acknowledge_experiment_plan:
        raise SystemExit("--run requires --acknowledge-experiment-plan")
    print(json.dumps(run(config, allow_dirty_worktree=args.allow_dirty_worktree), indent=2))


if __name__ == "__main__":
    main()
