from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Any


REQUIRED_SUFFIXES = (
    "samples.jsonl",
    "aggregates.jsonl",
    "predictions.csv",
    "metrics.json",
    "policy.json",
    "manifest.json",
)


@dataclass(frozen=True)
class ArtifactAudit:
    status: str
    prefix: str
    errors: tuple[str, ...]
    limitations: tuple[str, ...]
    summary: dict[str, Any]
    sha256: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_research_artifacts(
    results_dir: Path,
    prefix: str,
    *,
    minimum_inference_families: int = 5,
) -> ArtifactAudit:
    paths = {
        suffix: results_dir / f"{prefix}_{suffix}" for suffix in REQUIRED_SUFFIXES
    }
    missing = [path.name for path in paths.values() if not path.exists()]
    if missing:
        return ArtifactAudit(
            status="FAIL",
            prefix=prefix,
            errors=(f"Missing artifacts: {', '.join(sorted(missing))}",),
            limitations=(),
            summary={},
            sha256={
                suffix: _sha256(path)
                for suffix, path in paths.items()
                if path.exists()
            },
        )

    manifest = json.loads(paths["manifest.json"].read_text(encoding="utf-8"))
    samples = _read_jsonl(paths["samples.jsonl"])
    aggregates = _read_jsonl(paths["aggregates.jsonl"])
    metrics = json.loads(paths["metrics.json"].read_text(encoding="utf-8"))
    with paths["predictions.csv"].open(encoding="utf-8", newline="") as handle:
        predictions = list(csv.DictReader(handle))

    errors: list[str] = []
    limitations: list[str] = []
    if manifest.get("status") != "COMPLETE":
        errors.append(f"Manifest status is {manifest.get('status')!r}, not COMPLETE")

    expected_calls = int(manifest.get("measured_generation_calls", -1))
    completed_calls = int(manifest.get("measured_generation_calls_completed", -1))
    if len(samples) != expected_calls or completed_calls != expected_calls:
        errors.append(
            "Sample count mismatch: "
            f"expected={expected_calls}, completed={completed_calls}, rows={len(samples)}"
        )

    sample_keys = [
        (str(row["scenario_id"]), int(row["sample_index"])) for row in samples
    ]
    if len(sample_keys) != len(set(sample_keys)):
        errors.append("Duplicate (scenario_id, sample_index) sample rows")

    repeats = int(manifest.get("samples_per_case", 0))
    samples_per_scenario = Counter(str(row["scenario_id"]) for row in samples)
    if any(count != repeats for count in samples_per_scenario.values()):
        errors.append("At least one sampled scenario does not have the declared repeats")
    if len(aggregates) != int(manifest.get("critic_eligible_cases", -1)):
        errors.append("Aggregate row count does not match critic_eligible_cases")
    if any(int(row["aggregate"]["sample_count"]) != repeats for row in aggregates):
        errors.append("At least one aggregate has the wrong sample_count")

    model_digests = {
        str(row["model_digest"]) for row in samples if row.get("model_digest")
    }
    if len(model_digests) != 1:
        errors.append(f"Expected one model digest, found {len(model_digests)}")
    elif manifest.get("model_digest") not in model_digests:
        errors.append("Manifest model digest does not match sample rows")

    policy_counts = Counter(str(row["policy"]) for row in predictions)
    expected_cases = int(manifest.get("cases", -1))
    if any(count != expected_cases for count in policy_counts.values()):
        errors.append("At least one policy does not have one prediction per case")
    metric_policies = set(metrics.get("summaries", {}))
    if metric_policies != set(policy_counts):
        errors.append("Metric policies and prediction policies do not match")

    split_by_scenario = manifest.get("split_by_scenario", {})
    split_families: dict[str, set[str]] = defaultdict(set)
    for scenario_id, split in split_by_scenario.items():
        family_id = str(scenario_id).rsplit("-", 1)[0]
        split_families[str(split)].add(family_id)
    split_family_counts = {
        split: len(split_families.get(split, set()))
        for split in ("train", "dev", "test")
    }
    test_families = split_family_counts["test"]
    if test_families < minimum_inference_families:
        limitations.append(
            "Test split has only "
            f"{test_families} independent task family/families; confidence intervals "
            "and test performance are not inferentially interpretable."
        )

    format_errors = sum(not bool(row.get("format_valid")) for row in samples)
    if format_errors:
        limitations.append(
            f"{format_errors}/{len(samples)} generations required format fallback"
        )
    decision_sets: dict[str, set[str]] = defaultdict(set)
    for row in samples:
        decision_sets[str(row["scenario_id"])].add(str(row["decision"]))
    disagreement_cases = sum(len(values) > 1 for values in decision_sets.values())

    safe_risks = [
        float(row["aggregate"]["mean_risk"])
        for row in aggregates
        if not bool(row["targets"]["unsafe_if_executed"])
    ]
    unsafe_risks = [
        float(row["aggregate"]["mean_risk"])
        for row in aggregates
        if bool(row["targets"]["unsafe_if_executed"])
    ]
    unsafe_with_auto_vote = sum(
        bool(row["targets"]["unsafe_if_executed"])
        and int(row["aggregate"]["decision_counts"].get("AUTO_EXECUTE", 0)) > 0
        for row in aggregates
    )

    status = "FAIL" if errors else ("PASS_WITH_LIMITATIONS" if limitations else "PASS")
    summary = {
        "claim_scope": manifest.get("config_snapshot", {}).get(
            "claim_scope", "unspecified"
        ),
        "cases": expected_cases,
        "critic_eligible_cases": len(aggregates),
        "sample_rows": len(samples),
        "prediction_policies": len(policy_counts),
        "prediction_rows": len(predictions),
        "format_error_rows": format_errors,
        "decision_disagreement_cases": disagreement_cases,
        "unsafe_cases_with_any_auto_execute_vote": unsafe_with_auto_vote,
        "mean_risk_safe_cases": fmean(safe_risks) if safe_risks else None,
        "mean_risk_unsafe_cases": fmean(unsafe_risks) if unsafe_risks else None,
        "split_family_counts": split_family_counts,
        "external_api_cost_usd": manifest.get("external_api_cost_usd"),
        "duration_seconds": manifest.get("duration_seconds"),
        "prompt_tokens": manifest.get("prompt_tokens"),
        "completion_tokens": manifest.get("completion_tokens"),
        "research_claim_allowed": not errors
        and test_families >= minimum_inference_families,
    }
    return ArtifactAudit(
        status=status,
        prefix=prefix,
        errors=tuple(errors),
        limitations=tuple(limitations),
        summary=summary,
        sha256={suffix: _sha256(path) for suffix, path in paths.items()},
    )
