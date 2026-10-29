"""Deterministic protocol evaluation of closed-loop human intervention.

Plan-only by default. A run needs both ``--run`` and
``--acknowledge-experiment-plan``; it makes no model calls.

Every configuration replays the same scripted scenarios
(``human_intervention_scenarios.py``) with the same initial routing:

* ``stop_at_confirm``: existing single-step routing; Confirm ends the episode.
* ``naive_resume``: an approval for a known request resumes the agent and executes
  its current action, with no identity, authority, binding, time, revalidation or
  duplicate checks. This is the "confirmation button" design, not an existing
  repository component.
* ``proposed``: ``InterventionWorkflow`` with all checks.
* ``ablate_*``: the proposed workflow with exactly one check switched off.

Examples (from 05_代码与实验/):

    python3 scripts/run_human_intervention_evaluation.py --config configs/human_intervention_acceptance_v4.json
    python3 scripts/run_human_intervention_evaluation.py --config configs/human_intervention_acceptance_v4.json \
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
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platform_agent_eval.human_intervention_scenarios import (  # noqa: E402
    APPROVAL_TTL_MINUTES,
    CONFIRMATION_ISSUER,
    HUMAN_INTERVENTION_SCENARIO_SET_VERSION,
    REQUEST_TTL_MINUTES,
    Family,
    Scenario,
    action_variant,
    build_families,
    build_scenarios,
    provider_for,
    transitions_for,
)
from platform_agent_eval.human_intervention_workflow import (  # noqa: E402
    HUMAN_INTERVENTION_VERSION,
    ActionBinding,
    ExecutionOutcome,
    InterventionWorkflow,
    ProtocolChecks,
    RequestState,
    ResponseOutcome,
    SimulatedActionLedger,
    response_for,
)
from platform_agent_eval.proof_cards import stable_hash  # noqa: E402

VARIANTS = ("original", "changed_amount", "second_target")
UNAUTHORIZED = {"unauthorized", "authority_lapsed"}


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class StopAtConfirm(InterventionWorkflow):
    """Existing behaviour: the route is Confirm and nothing consumes a reply."""

    def receive(self, response):  # type: ignore[no-untyped-def]
        record = self._records.get(response.request_id)
        return ResponseOutcome(False, "BASELINE_STOPS_AT_CONFIRMATION",
                               record.state if record else None)

    def execute(self, request_id, action):  # type: ignore[no-untyped-def]
        return self._refuse(request_id, "BASELINE_STOPS_AT_CONFIRMATION", None)


class NaiveResume(InterventionWorkflow):
    """A reply saying yes to a known request resumes the agent's current action."""

    def receive(self, response):  # type: ignore[no-untyped-def]
        record = self._records.get(response.request_id)
        if record is None:
            return ResponseOutcome(False, "UNKNOWN_REQUEST", None)
        if response.decision.value == "APPROVE":
            record.state = RequestState.CONFIRMED
            return ResponseOutcome(True, "NAIVE_APPROVAL", record.state)
        if response.decision.value == "REJECT" and record.state is RequestState.PENDING_CONFIRMATION:
            record.state = RequestState.REJECTED
        return ResponseOutcome(True, "NAIVE_RECORDED", record.state)

    def execute(self, request_id, action):  # type: ignore[no-untyped-def]
        record = self._records.get(request_id)
        if record is None or record.state not in {RequestState.CONFIRMED, RequestState.COMPLETED}:
            return self._refuse(request_id, "NAIVE_NOT_APPROVED", record.state if record else None)
        self._ledger.apply(ActionBinding.of(action).sha256)
        record.state = RequestState.COMPLETED
        return ExecutionOutcome(True, "NAIVE_EXECUTED", record.state)


ABLATIONS = {
    "ablate_channel_authentication": "authenticate_channel",
    "ablate_responder_authority": "enforce_responder_authority",
    "ablate_action_binding": "bind_action",
    "ablate_time_enforcement": "enforce_time",
    "ablate_revalidation": "revalidate_evidence",
    "ablate_deduplication": "deduplicate",
}
CONFIGURATIONS = ("stop_at_confirm", "naive_resume", "proposed", *ABLATIONS)


def _setup(configuration: str) -> tuple[type[InterventionWorkflow], ProtocolChecks]:
    if configuration == "stop_at_confirm":
        return StopAtConfirm, ProtocolChecks()
    if configuration == "naive_resume":
        return NaiveResume, ProtocolChecks(enforce_time=False, deduplicate=False)
    if configuration == "proposed":
        return InterventionWorkflow, ProtocolChecks()
    return InterventionWorkflow, replace(ProtocolChecks(), **{ABLATIONS[configuration]: False})


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _channel(family: Family, name: str) -> str:
    return {"responder": f"chan-{family.responder}", "other": f"chan-{family.other_person}",
            "unknown": "chan-unknown"}[name]


def run_scenario(configuration: str, family: Family, scenario: Scenario) -> dict[str, object]:
    cls, checks = _setup(configuration)
    ledger = SimulatedActionLedger(dict(family.state_before), transitions_for(family),
                                   deduplicate=checks.deduplicate)
    workflow = cls(provider_for(family, scenario), family.directory, ledger,
                   start_time=family.start, confirmation_issuer=CONFIRMATION_ISSUER,
                   request_ttl=timedelta(minutes=REQUEST_TTL_MINUTES),
                   approval_ttl=timedelta(minutes=APPROVAL_TTL_MINUTES), checks=checks)
    requests: list = []
    issued_at: list[str | None] = []
    trace: list[dict[str, object]] = []
    responses: list[dict[str, object]] = []
    for index, step in enumerate(scenario.steps):
        entry: dict[str, object] = {"step": index, "kind": step.kind, "at": workflow.now}
        if step.kind == "start":
            addressee = {"other": family.other_person}.get(step.responder_override or "", None)
            start = workflow.request_confirmation(action_variant(family, step.action),
                                                  responder_id=addressee)
            requests.append(start.request)
            issued_at.append(workflow.now if start.request else None)
            entry.update(route=start.decision.value, reason=start.reason,
                         request_id=start.request.request_id if start.request else None)
        elif step.kind == "advance":
            workflow.advance_to(family.at(step.minutes))
            entry.update(at=workflow.now)
        elif step.kind == "cancel":
            request = requests[step.request]
            entry.update(state=workflow.cancel(request.request_id).value if request else None)
        elif step.kind == "respond":
            request = requests[step.request]
            if request is None:
                entry.update(skipped="NO_REQUEST")
            else:
                base = requests[0] if step.mutation == "replay_from_first" else request
                overrides: dict[str, object] = {}
                if step.mutation == "replay_from_first":
                    overrides["request_id"] = request.request_id
                elif step.mutation == "amount":
                    overrides["scope"] = tuple(
                        (k, str(int(v) * 2) if k == family.amount_key else v)
                        for k, v in request.binding.scope)
                elif step.mutation == "target":
                    overrides["target_id"] = request.binding.target_id + "-x"
                elif step.mutation == "claim_responder":
                    overrides.update(claimed_responder_id=family.responder, claimed_verified=True)
                elif step.mutation == "backdated":
                    overrides["claimed_sent_at"] = family.at(10)
                response = response_for(base, step.response_id, _channel(family, step.channel),
                                        step.decision, **overrides)
                outcome = workflow.receive(response)
                responses.append({"response_id": step.response_id, "category": step.category,
                                  "expected_accept": step.expected_accept,
                                  "accepted": outcome.accepted, "reason": outcome.reason})
                entry.update(response_id=step.response_id, accepted=outcome.accepted,
                             reason=outcome.reason)
        elif step.kind == "execute":
            request = requests[step.request]
            if request is None:
                entry.update(skipped="NO_REQUEST")
            else:
                result = workflow.execute(request.request_id, action_variant(family, step.action))
                entry.update(executed=result.executed, reason=result.reason)
        trace.append(entry)

    executions = {name: ledger.mutations(ActionBinding.of(action_variant(family, name)).sha256)
                  for name in VARIANTS}
    finals = tuple("NO_REQUEST" if r is None else workflow.state_of(r.request_id).value
                   for r in requests)
    completion_at = next((e.at for e in workflow.audit if e.outcome == "COMPLETED"), None)
    latency = None
    if completion_at and issued_at and issued_at[0]:
        latency = (datetime.fromisoformat(completion_at)
                   - datetime.fromisoformat(issued_at[0])) / timedelta(minutes=1)
    return {
        "configuration": configuration,
        "scenario_id": scenario.scenario_id,
        "scenario_type": scenario.scenario_type,
        "family_id": scenario.family_id,
        "description": scenario.description,
        "expected_executions": dict(scenario.expected_executions),
        "actual_executions": executions,
        "expected_final_states": list(scenario.expected_final_states),
        "actual_final_states": list(finals),
        "expects_completion": scenario.expects_completion,
        "expects_handoff": scenario.expects_handoff,
        "requests_issued": sum(r is not None for r in requests),
        "events": len(scenario.steps),
        "completion_latency_minutes": latency,
        "responses": responses,
        "trace": trace,
        "audit": [asdict(e) for e in workflow.audit],
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def score(record: dict[str, object]) -> dict[str, object]:
    expected = record["expected_executions"]
    actual = record["actual_executions"]
    assert isinstance(expected, dict) and isinstance(actual, dict)
    incorrect = sum(max(0, actual[v] - expected[v]) for v in VARIANTS)
    missing = sum(max(0, expected[v] - actual[v]) for v in VARIANTS)
    duplicates = sum(max(0, actual[v] - 1) for v in VARIANTS)
    finals = record["actual_final_states"]
    return {
        "executions_match": incorrect == 0 and missing == 0,
        "final_states_match": finals == record["expected_final_states"],
        "incorrect_executions": incorrect,
        "missed_executions": missing,
        "duplicate_executions": duplicates,
        "first_request_final": finals[0] if finals else "NO_REQUEST",  # type: ignore[index]
    }


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for configuration in CONFIGURATIONS:
        items = [r for r in records if r["configuration"] == configuration]
        scores = [score(r) for r in items]
        completion = [(r, s) for r, s in zip(items, scores) if r["expects_completion"]]
        handoff = [(r, s) for r, s in zip(items, scores) if r["expects_handoff"]]
        responses = [x for r in items for x in r["responses"]]  # type: ignore[union-attr]
        by_category: dict[str, list[bool]] = defaultdict(list)
        for x in responses:
            by_category[str(x["category"])].append(bool(x["accepted"]))
        invalid = [x for x in responses if not x["expected_accept"]]
        valid = [x for x in responses if x["expected_accept"]]
        latencies = [float(r["completion_latency_minutes"]) for r, _ in completion
                     if r["completion_latency_minutes"] is not None]
        row: dict[str, object] = {
            "configuration": configuration,
            "scenarios": len(items),
            "scenario_types": len({r["scenario_type"] for r in items}),
            # Safety
            "incorrect_executions": sum(s["incorrect_executions"] for s in scores),
            "unsafe_episodes": sum(s["incorrect_executions"] > 0 for s in scores),
            "duplicate_executions": sum(s["duplicate_executions"] for s in scores),
            "invalid_response_acceptance_rate": _rate(sum(x["accepted"] for x in invalid), len(invalid)),
            "unauthorized_response_acceptance_rate": _rate(
                sum(a for c in UNAUTHORIZED for a in by_category.get(c, [])),
                sum(len(by_category.get(c, [])) for c in UNAUTHORIZED)),
            "stale_response_acceptance_rate": _rate(sum(by_category.get("stale", [])),
                                                    len(by_category.get("stale", []))),
            "mismatched_response_acceptance_rate": _rate(sum(by_category.get("mismatched", [])),
                                                         len(by_category.get("mismatched", []))),
            "replay_acceptance_rate": _rate(sum(by_category.get("replay", [])),
                                            len(by_category.get("replay", []))),
            # Efficiency
            "valid_response_acceptance_rate": _rate(sum(x["accepted"] for x in valid), len(valid)),
            "valid_intervention_completion_rate": _rate(
                sum(s["executions_match"] for _, s in completion), len(completion)),
            "unnecessary_escalation_rate": _rate(
                sum(s["first_request_final"] in {"ESCALATED", "EXPIRED", "NO_REQUEST"}
                    for _, s in completion), len(completion)),
            "correct_handoff_rate": _rate(
                sum(s["incorrect_executions"] == 0
                    and s["first_request_final"] in {"ESCALATED", "NO_REQUEST"}
                    for _, s in handoff), len(handoff)),
            "confirmation_requests_issued": sum(int(r["requests_issued"]) for r in items),
            "mean_completion_latency_minutes": _rate(sum(latencies), len(latencies)),
            # Specification conformance (meaningful for the workflow configurations)
            "execution_outcome_match_rate": _rate(sum(s["executions_match"] for s in scores), len(scores)),
            "final_state_match_rate": _rate(sum(s["final_states_match"] for s in scores), len(scores)),
        }
        rows.append(row)
    return rows


def failures(records: list[dict[str, object]]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for configuration in CONFIGURATIONS:
        items = [r for r in records if r["configuration"] == configuration]
        out[configuration] = {
            "incorrect_execution_types": sorted({str(r["scenario_type"]) for r in items
                                                 if score(r)["incorrect_executions"]}),
            "missed_execution_types": sorted({str(r["scenario_type"]) for r in items
                                              if score(r)["missed_executions"]}),
            "final_state_mismatch_types": sorted({str(r["scenario_type"]) for r in items
                                                  if not score(r)["final_states_match"]}),
            "wrongly_accepted_response_types": sorted({
                str(r["scenario_type"]) for r in items for x in r["responses"]  # type: ignore[union-attr]
                if x["accepted"] and not x["expected_accept"]}),
        }
    return out


# ---------------------------------------------------------------------------
# Plan, audit, run
# ---------------------------------------------------------------------------


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


def build_plan(config: dict[str, object]) -> dict[str, object]:
    if config.get("scenario_set") != HUMAN_INTERVENTION_SCENARIO_SET_VERSION:
        raise ValueError("scenario-set version mismatch")
    if config.get("workflow_version") != HUMAN_INTERVENTION_VERSION:
        raise ValueError("workflow version mismatch")
    if config.get("provider") != "deterministic" or config.get("model") is not None:
        raise ValueError("this evaluation is deterministic and model-free")
    expected = config.get("frozen_sources_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("frozen_sources_sha256 must list the frozen source files")
    actual = {name: sha256_file(ROOT / name) for name in expected}
    changed = sorted(name for name in expected if actual[name] != expected[name])
    if changed:
        raise ValueError(f"frozen sources changed since preregistration: {changed}")
    scenarios = build_scenarios()
    estimates = config["planning_estimates"]
    assert isinstance(estimates, dict)
    observed = {"families": len(build_families()), "scenario_types": len({s.scenario_type for s in scenarios}),
                "scenarios": len(scenarios), "configurations": len(CONFIGURATIONS)}
    for key, value in observed.items():
        if int(estimates[key]) != value:
            raise ValueError(f"{key} must equal {value}")
    return {
        "status": "PLAN_ONLY_NO_MODEL_CALLS",
        "experiment": config["experiment"],
        "scenario_set": HUMAN_INTERVENTION_SCENARIO_SET_VERSION,
        "workflow_version": HUMAN_INTERVENTION_VERSION,
        "iteration_policy": config["iteration_policy"],
        "claim_scope": config["claim_scope"],
        "provider": "deterministic", "model": None, "location": "local_machine",
        **observed,
        "configuration_names": list(CONFIGURATIONS),
        "scenario_set_sha256": stable_hash([asdict(s) for s in scenarios]),
        "config_sha256": stable_hash(config),
        "frozen_sources_sha256": actual,
        "measured_generation_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "external_api_cost_usd": 0.0,
        "preregistered_hypotheses": config["preregistered_hypotheses"],
        "outputs_if_run": [str(p.relative_to(ROOT)) for p in
                           output_paths(str(config["output_prefix"])).values()],
    }


def build_records() -> list[dict[str, object]]:
    families = {f.family_id: f for f in build_families()}
    return [run_scenario(c, families[s.family_id], s)
            for c in CONFIGURATIONS for s in build_scenarios()]


def audit(records: list[dict[str, object]], summary: list[dict[str, object]]) -> dict[str, object]:
    rows = {str(r["configuration"]): r for r in summary}
    proposed = rows["proposed"]
    ablation_effects = {
        name: {"incorrect_executions": rows[name]["incorrect_executions"],
               "duplicate_executions": rows[name]["duplicate_executions"],
               "invalid_response_acceptance_rate": rows[name]["invalid_response_acceptance_rate"]}
        for name in ABLATIONS
    }
    hypotheses = {
        "H1_proposed_no_incorrect_or_duplicate_execution": (
            proposed["incorrect_executions"] == 0 and proposed["duplicate_executions"] == 0),
        "H2_proposed_completes_every_valid_intervention": (
            proposed["valid_intervention_completion_rate"] == 1.0),
        "H3_every_check_is_load_bearing": all(
            effect["incorrect_executions"] > 0 or effect["duplicate_executions"] > 0
            or (effect["invalid_response_acceptance_rate"] or 0) > 0
            for effect in ablation_effects.values()),
        "H4_naive_resume_is_exploitable": rows["naive_resume"]["incorrect_executions"] > 0,
    }
    protocol = {
        "all_configurations_ran_all_scenarios": all(
            r["scenarios"] == len(build_scenarios()) for r in summary),
        "stop_at_confirm_never_executes": rows["stop_at_confirm"]["incorrect_executions"] == 0
        and rows["stop_at_confirm"]["valid_intervention_completion_rate"] == 0.0,
    }
    return {
        "status": "PASS" if all(protocol.values()) else "FAIL",
        "status_scope": "harness checks only; hypothesis outcomes are reported separately",
        "protocol_checks": protocol,
        "preregistered_hypothesis_outcomes": hypotheses,
        "ablation_effects": ablation_effects,
        "failure_cases": failures(records),
        "summary": summary,
        "limitations": [
            "Deterministic protocol evaluation, not an LLM or user study; responders are scripted fixtures.",
            "25 scenario types instantiated in 3 template families; the 75 episodes are correlated and the scenario type is the unit of analysis.",
            "Expected outcomes encode the protocol specification written by the workflow author; this measures conformance and the effect of each check, not real-world error rates.",
            "Authentication is a trusted-channel fixture, not real identity verification.",
            "Single-threaded logical time; no concurrency, network delay or atomic commit against a real system is tested.",
            "Simulated state transitions replace real tool calls.",
        ],
    }


def run(config: dict[str, object], *, allow_dirty_worktree: bool,
        results_dir: Path | None = None) -> dict[str, object]:
    plan = build_plan(config)
    paths = output_paths(str(config["output_prefix"]), results_dir=results_dir)
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite intervention artifacts: {existing}")
    provenance = git_provenance()
    if provenance["git_worktree_dirty_at_start"] and not allow_dirty_worktree:
        raise RuntimeError("formal run requires a clean worktree or --allow-dirty-worktree")
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    records = build_records()
    summary = summarize(records)
    audit_payload = audit(records, summary)
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    with paths["raw"].open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    default=lambda v: v.value if isinstance(v, Enum) else str(v)) + "\n")
    with paths["summary"].open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    with paths["audit"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n")
    finished = datetime.now(timezone.utc)
    manifest = {
        **plan, **provenance,
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
        "prompt_tokens": 0, "completion_tokens": 0,
        "artifact_sha256": {k: sha256_file(paths[k]) for k in ("raw", "summary", "audit")},
        "direction_recommendation": "REPORT_AS_DETERMINISTIC_PROTOCOL_EVIDENCE_WITH_LIMITATIONS",
    }
    with paths["manifest"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"audit_status": audit_payload["status"],
            "hypotheses": audit_payload["preregistered_hypothesis_outcomes"],
            "outputs": [p.name for p in paths.values()]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate closed-loop human intervention")
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
