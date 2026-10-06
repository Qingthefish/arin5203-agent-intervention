from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
INDEX_PATH = RESULTS / "index.json"
SCHEMA_VERSION = "experiment-artifact-index-v1"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first(manifest: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = manifest.get(name)
        if value is not None:
            return value
    return None


def _normalize_status(value: Any) -> str:
    raw = str(value or "MISSING").upper()
    return "COMPLETED" if raw == "COMPLETE" else raw


def _artifact_path(results_dir: Path, prefix: str, suffix: str) -> Path:
    return results_dir / f"{prefix}_{suffix}"


def build_index(results_dir: Path = RESULTS) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    manifests = sorted(results_dir.glob("*_manifest.json"))
    for manifest_path in manifests:
        prefix = manifest_path.name.removesuffix("_manifest.json")
        manifest = _load_json(manifest_path)
        status = _normalize_status(manifest.get("status"))
        paths = {
            "manifest": manifest_path,
            "raw": _artifact_path(results_dir, prefix, "raw.jsonl"),
            "summary": _artifact_path(results_dir, prefix, "summary.csv"),
            "audit": _artifact_path(results_dir, prefix, "audit.json"),
        }
        present = {name: path.exists() for name, path in paths.items()}
        audit = _load_json(paths["audit"]) if present["audit"] else {}
        if status in {"FAILED", "ABORTED_DESIGN_REVIEW"}:
            evidence_tier = "FAILED_OR_ABORTED"
        elif status == "COMPLETED" and all(present.values()):
            evidence_tier = "FROZEN_GATE_BUNDLE"
        else:
            evidence_tier = "LEGACY_OR_INCOMPLETE_METADATA"
        if status == "MISSING":
            warnings.append(
                {"prefix": prefix, "code": "MISSING_MANIFEST_STATUS"}
            )
        if status == "COMPLETED" and not present["raw"]:
            warnings.append(
                {"prefix": prefix, "code": "COMPLETED_WITHOUT_RAW_TRACE"}
            )
        runs.append(
            {
                "prefix": prefix,
                "status": status,
                "evidence_tier": evidence_tier,
                "experiment": manifest.get("experiment"),
                "scenario_set": manifest.get("scenario_set"),
                "model": _first(manifest, "model_id", "model"),
                "provider": manifest.get("provider"),
                "git_commit": manifest.get("git_commit"),
                "measured_generation_calls": _first(
                    manifest,
                    "measured_generation_calls_completed",
                    "completed_measured_generations",
                    "completed_model_calls",
                ),
                "prompt_tokens": _first(
                    manifest, "prompt_tokens", "total_prompt_tokens"
                ),
                "completion_tokens": _first(
                    manifest, "completion_tokens", "total_completion_tokens"
                ),
                "external_api_cost_usd": manifest.get("external_api_cost_usd"),
                "started_at": _first(
                    manifest, "started_at_hong_kong", "started_at_utc"
                ),
                "finished_at": _first(
                    manifest, "finished_at_hong_kong", "finished_at_utc"
                ),
                "audit_status": audit.get("status"),
                "recommendation": _first(
                    manifest, "direction_recommendation", "recommendation"
                )
                or audit.get("recommendation"),
                "claim_scope": manifest.get("claim_scope"),
                "artifacts": {
                    name: (
                        f"results/{path.name}" if path.exists() else None
                    )
                    for name, path in paths.items()
                },
                "manifest_sha256": _sha256(manifest_path),
                "audit_sha256": _sha256(paths["audit"])
                if present["audit"]
                else None,
            }
        )
    statuses = Counter(run["status"] for run in runs)
    tiers = Counter(run["evidence_tier"] for run in runs)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "results/*_manifest.json",
        "policy": (
            "Machine-generated discovery index only. Manifests and audits remain "
            "the evidence sources; evidence_tier is not a publication claim."
        ),
        "totals": {
            "runs": len(runs),
            "statuses": dict(sorted(statuses.items())),
            "evidence_tiers": dict(sorted(tiers.items())),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "runs": runs,
    }


def render_index(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Index immutable experiment artifacts")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()
    rendered = render_index(build_index(args.results_dir))
    if args.write:
        args.index.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.index}")
        return
    if not args.index.exists() or args.index.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            "experiment artifact index is stale; run "
            "python3 scripts/index_experiment_artifacts.py --write"
        )
    print(f"artifact index is current: {args.index}")


if __name__ == "__main__":
    main()
