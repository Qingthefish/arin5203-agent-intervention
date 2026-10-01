from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .approvals import missing_requirements
from .domain import Decision, EvaluationCase


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    message: str
    scenario_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetAudit:
    cases: int
    families: int
    route_counts: dict[str, int]
    operation_counts: dict[str, int]
    feature_route_counts: dict[str, dict[str, dict[str, int]]]
    constant_features: tuple[str, ...]
    findings: tuple[AuditFinding, ...]

    @property
    def errors(self) -> tuple[AuditFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "error")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["errors"] = len(self.errors)
        return payload


def _observable_features(case: EvaluationCase) -> dict[str, bool]:
    policy = case.policy_input
    evidence = policy.approval_evidence
    approval_missing = False
    if evidence is not None:
        approval_missing = bool(
            missing_requirements(evidence, case.oracle.approval_requirements)
        )
    return {
        "production": policy.production,
        "reversible": policy.reversible,
        "checkpoint_available": policy.checkpoint_available,
        "rollback_available": policy.rollback_available,
        "migration_target_available": policy.migration_target_available,
        "quota_borrowing": policy.quota_borrowing,
        "active_incident": policy.active_incident,
        "cross_tenant": policy.cross_tenant,
        "approval_evidence_present": bool(evidence),
        "approval_missing_or_invalid": approval_missing,
    }


def _semantic_findings(cases: list[EvaluationCase]) -> list[AuditFinding]:
    checks: tuple[tuple[str, str, Any], ...] = (
        ("active_incident", "text_active_incident_mismatch", lambda p: p.active_incident),
        ("no checkpoint", "text_checkpoint_mismatch", lambda p: not p.checkpoint_available),
        ("no migration target", "text_migration_mismatch", lambda p: not p.migration_target_available),
        ("production", "text_production_mismatch", lambda p: p.production),
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        text = case.policy_input.request.lower()
        for phrase, code, predicate in checks:
            if phrase in text and not predicate(case.policy_input):
                grouped[code].append(case.gold.scenario_id)
    return [
        AuditFinding(
            severity="error",
            code=code,
            message="Natural-language request contradicts a structured policy fact.",
            scenario_ids=tuple(ids),
        )
        for code, ids in sorted(grouped.items())
    ]


def _approval_and_leakage_findings(
    cases: list[EvaluationCase],
) -> list[AuditFinding]:
    from .model_routing import SCOPED_PROMPT_TEMPLATE_VERSION, build_policy_prompt

    findings: list[AuditFinding] = []
    duplicate_requests: dict[str, list[EvaluationCase]] = defaultdict(list)
    approval_gaps: list[str] = []
    prompt_leaks: list[str] = []
    for case in cases:
        duplicate_requests[case.policy_input.request.strip().lower()].append(case)
        expected_owners = {case.policy_input.resource_owner}
        expected_owners.update(
            tenant
            for tenant in case.policy_input.affected_tenants
            if tenant != "platform"
        )
        if case.oracle.approval_requirements:
            actual_owners = {
                requirement.resource_owner_scope
                for requirement in case.oracle.approval_requirements
            }
            if not expected_owners.issubset(actual_owners):
                approval_gaps.append(case.gold.scenario_id)

        if case.policy_input.approval_evidence is not None:
            prompt = build_policy_prompt(
                case.policy_input,
                "three_way",
                template_version=SCOPED_PROMPT_TEMPLATE_VERSION,
            )
            private_tokens = (
                case.gold.scenario_id,
                case.gold.base_task_id,
                '"scenario_id"',
                '"base_task_id"',
                '"variant"',
                '"expected_decision"',
            )
            if any(token in prompt for token in private_tokens):
                prompt_leaks.append(case.gold.scenario_id)

    duplicates = [
        items
        for items in duplicate_requests.values()
        if len({item.gold.base_task_id for item in items}) > 1
    ]
    if duplicates:
        findings.append(
            AuditFinding(
                severity="warning",
                code="duplicate_visible_request",
                message="Multiple cases expose identical request text.",
                scenario_ids=tuple(
                    item.gold.scenario_id
                    for duplicate_group in duplicates
                    for item in duplicate_group
                ),
            )
        )
    if approval_gaps:
        findings.append(
            AuditFinding(
                severity="error",
                code="incomplete_multilateral_approval",
                message="Approval requirements omit at least one affected owner.",
                scenario_ids=tuple(approval_gaps),
            )
        )
    if prompt_leaks:
        findings.append(
            AuditFinding(
                severity="error",
                code="private_label_in_prompt",
                message="A model prompt contains private dataset metadata.",
                scenario_ids=tuple(prompt_leaks),
            )
        )
    return findings


def _shortcut_findings(cases: list[EvaluationCase]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    feature_names = tuple(_observable_features(cases[0]))
    for name in feature_names:
        values = {value for case in cases for value in [_observable_features(case)[name]]}
        if len(values) == 1:
            continue
        for value in (False, True):
            selected = [case for case in cases if _observable_features(case)[name] is value]
            if len(selected) < 3:
                continue
            routes = {case.gold.expected_decision for case in selected}
            if len(routes) == 1:
                route = next(iter(routes))
                findings.append(
                    AuditFinding(
                        severity="warning",
                        code="route_pure_feature_slice",
                        message=(
                            f"{name}={value} predicts {route.value} for all "
                            f"{len(selected)} cases; add counterexamples or justify the rule."
                        ),
                        scenario_ids=tuple(case.gold.scenario_id for case in selected),
                    )
                )
    return findings


def audit_scenario_set(scenarios: Iterable[EvaluationCase]) -> DatasetAudit:
    cases = list(scenarios)
    if not cases:
        raise ValueError("Cannot audit an empty scenario set")

    feature_rows = [_observable_features(case) for case in cases]
    constant_features = tuple(
        name
        for name in feature_rows[0]
        if len({row[name] for row in feature_rows}) == 1
    )
    findings = [
        *_semantic_findings(cases),
        *_approval_and_leakage_findings(cases),
        *_shortcut_findings(cases),
    ]
    for feature in constant_features:
        findings.append(
            AuditFinding(
                severity="warning",
                code="constant_observable_feature",
                message=f"{feature} is constant and cannot support an ablation.",
            )
        )

    return DatasetAudit(
        cases=len(cases),
        families=len({case.gold.base_task_id for case in cases}),
        route_counts=dict(
            sorted(Counter(case.gold.expected_decision.value for case in cases).items())
        ),
        operation_counts=dict(
            sorted(Counter(case.policy_input.operation.value for case in cases).items())
        ),
        feature_route_counts={
            feature: {
                str(value).lower(): dict(
                    sorted(
                        Counter(
                            case.gold.expected_decision.value
                            for case in cases
                            if _observable_features(case)[feature] is value
                        ).items()
                    )
                )
                for value in (False, True)
            }
            for feature in feature_rows[0]
        },
        constant_features=constant_features,
        findings=tuple(findings),
    )
