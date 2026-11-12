#!/usr/bin/env python3
"""Append-only SHA-256 ledger for ``results/`` (frozen artifacts stay immutable).

``--check`` fails if a ledgered file changed or disappeared, or if a results
file is not yet ledgered. Manifest-embedded ``artifact_sha256`` values are also
verified. ``--append`` adds new files only and refuses to rewrite any existing
entry, so a changed frozen artifact can never be "fixed" by regenerating it.

    python3 scripts/verify_results_integrity.py --check
    python3 scripts/verify_results_integrity.py --append   # after adding a new bundle
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LEDGER = RESULTS / "SHA256SUMS"
# The generated index changes whenever a bundle is added; --check of the
# indexer guards it instead.
EXCLUDED = {"SHA256SUMS", "index.json", ".DS_Store"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_ledger(path: Path = LEDGER) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name or name in entries:
            raise SystemExit(f"malformed or duplicate ledger line {number}: {line!r}")
        entries[name] = digest
    return entries


def current_files(results: Path = RESULTS) -> dict[str, Path]:
    return {
        str(p.relative_to(results)): p
        for p in sorted(results.rglob("*"))
        if p.is_file() and p.name not in EXCLUDED
    }


def manifest_problems(results: Path = RESULTS) -> list[str]:
    problems: list[str] = []
    for manifest in sorted(results.glob("*_manifest.json")):
        recorded = json.loads(manifest.read_text(encoding="utf-8")).get("artifact_sha256") or {}
        prefix = manifest.name.removesuffix("_manifest.json")
        for kind, digest in recorded.items():
            matches = [p for p in results.glob(f"{prefix}_{kind}.*")]
            if len(matches) != 1:
                problems.append(f"{manifest.name}: cannot resolve artifact '{kind}'")
            elif _sha(matches[0]) != digest:
                problems.append(f"{matches[0].name}: differs from its manifest artifact_sha256")
    return problems


def check(results: Path = RESULTS, ledger: Path = LEDGER) -> list[str]:
    entries = read_ledger(ledger)
    files = current_files(results)
    problems = [f"missing ledgered file: {n}" for n in entries if n not in files]
    problems += [f"changed frozen file: {n}" for n, d in entries.items() if n in files and _sha(files[n]) != d]
    problems += [f"not in ledger (run --append after review): {n}" for n in files if n not in entries]
    return problems + manifest_problems(results)


def append(results: Path = RESULTS, ledger: Path = LEDGER) -> list[str]:
    entries = read_ledger(ledger)
    files = current_files(results)
    changed = [n for n, d in entries.items() if n in files and _sha(files[n]) != d]
    missing = [n for n in entries if n not in files]
    if changed or missing:
        raise SystemExit("refusing to append while frozen files changed or vanished: "
                         + ", ".join(changed + missing))
    added = [n for n in files if n not in entries]
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        for name in added:
            handle.write(f"{_sha(files[name])}  {name}\n")
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--append", action="store_true")
    args = parser.parse_args()
    if args.append:
        added = append()
        print(f"appended {len(added)} file(s) to {LEDGER.relative_to(ROOT)}")
        for name in added:
            print(f"  + {name}")
        return
    problems = check()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(f"results integrity check failed ({len(problems)} problem(s))")
    print(f"results integrity OK: {len(read_ledger())} ledgered files, manifest hashes verified")


if __name__ == "__main__":
    main()
