#!/usr/bin/env python3
"""Package the course supplement from tracked research files, without model calls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "03_最终报告/Project_Final_Supplement_Yu_Yeung_Guo.zip"
INCLUDED_DIRECTORIES = (
    "05_代码与实验/",
    "03_最终报告/figures/",
    "04_项目展示/figures/",
    "CVPR2026_模板源码/官方源码/",
)
INCLUDED_FILES = {
    "README.md",
    "AGENTS.md",
    "项目复盘.md",
    ".gitattributes",
    ".github/workflows/research-checks.yml",
    "03_最终报告/final_report.tex",
    "04_项目展示/README.md",
    "04_项目展示/Agent_Memory_Playbook.md",
    "04_项目展示/demo-story-preview.png",
}


def main() -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    names = sorted(
        name for name in tracked
        if name and (name in INCLUDED_FILES or name.startswith(INCLUDED_DIRECTORIES))
    )
    contents = {name: (ROOT / name).read_bytes() for name in names}
    source_bytes = sum(
        len(data) for name, data in contents.items()
        if name.endswith((".py", ".yml", ".toml", ".sh"))
    )
    if source_bytes > 10_000_000:
        raise SystemExit("source code exceeds the course's 10 MB limit")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    changed = subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    manifest = {
        "status": "team_review",
        "source_git_revision": revision,
        "modified_included_files": [name for name in changed if name in contents],
        "source_code_bytes": source_bytes,
        "reproduction_guide": "05_代码与实验/README.md",
        "files_sha256": {
            name: hashlib.sha256(data).hexdigest() for name, data in contents.items()
        },
    }
    contents["SUPPLEMENT_MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    contents["START_HERE.txt"] = (
        "ARIN 5203 course-project supplement, team-review copy\n\n"
        "Authors: Qingcheng Yu, Siu Kwun Yeung, Qingyin Guo\n"
        "Use Python 3.12 or newer. The deterministic checks need no model or API key.\n"
        "Enter 05_代码与实验 and run:\n"
        "  python3 scripts/verify_results_integrity.py --check\n"
        "  python3 scripts/index_experiment_artifacts.py --check\n"
        "  python3 -m unittest discover -s tests -v\n"
        "  python3 examples/guarded_hotel_workflow.py --json\n"
        "  python3 scripts/serve_memory_crash_test.py --port 8765\n\n"
        "Open http://127.0.0.1:8765 for the frozen-trace replay.\n"
        "05_代码与实验/README.md documents the CLI red/green example and evidence.\n"
        "04_项目展示/figures contains presentation figures derived from frozen results.\n"
        "The main report PDF is delivered separately. The root README records\n"
        "remaining team review and the report-sharing declaration.\n"
        "SUPPLEMENT_MANIFEST.json records hashes and the source revision.\n"
    ).encode("utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, data in sorted(contents.items()):
                entry = zipfile.ZipInfo(f"ARIN5203_Supplement/{name}")
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        if temporary.stat().st_size > 10_000_000:
            raise SystemExit("supplement ZIP exceeds 10 MB")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise SystemExit("supplement ZIP integrity check failed")
            for name, digest in manifest["files_sha256"].items():
                actual = hashlib.sha256(
                    archive.read(f"ARIN5203_Supplement/{name}")
                ).hexdigest()
                if actual != digest:
                    raise SystemExit(f"supplement hash mismatch: {name}")
        temporary.replace(OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Packaged {len(names)} source/evidence files: {OUTPUT.name}")
    print(f"ZIP bytes: {OUTPUT.stat().st_size}; code bytes: {source_bytes}")
    print(f"SHA-256: {hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
