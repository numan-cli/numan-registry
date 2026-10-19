#!/usr/bin/env python3
"""Materialize a filtered production-candidate index from a source index.

The protected production workflow signs and publishes registry/index.json
verbatim, so exclusions must be applied before dispatch. This script builds
the candidate:

- drops every version entry whose evidence_tier is "provisional"
- drops packages named on the --exclude list (approver keep/exclude decisions)
- drops packages left with zero versions after filtering
- writes the canonical JSON bytes ci-sign.py would sign, plus a report
  recording the canonical sha256 and every exclusion with its reason

Usage:
  python scripts/materialize_candidate.py \
      --index registry/index.json \
      --exclude owner/name --exclude owner2/name2 \
      --out candidate/index.json --report candidate/report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"


def canonical_json(value):
    """Return the canonical JSON string for a parsed JSON value.

    Mirrors ci-sign.py/validate.py and the client so the recorded
    candidate digest equals the bytes that would be signed.
    """
    if isinstance(value, dict):
        items = sorted((canonical_json(k), canonical_json(v)) for k, v in value.items())
        return "{" + ",".join(f"{k}:{v}" for k, v in items) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value, separators=(",", ":"))


def package_label(pkg: dict) -> str:
    pkg_id = pkg.get("id") or {}
    return f"{pkg_id.get('owner', '?')}/{pkg_id.get('name', '?')}"


def materialize_candidate(
    index: dict, excludes: set[str] | None = None
) -> tuple[dict, list[dict]]:
    """Return (filtered_index, exclusions) without mutating the source.

    exclusions entries record {package, version or "*", reason}.
    """
    excludes = excludes or set()
    removals: list[dict] = []
    packages = []
    for pkg in index.get("packages", []):
        if not isinstance(pkg, dict):
            packages.append(pkg)
            continue
        label = package_label(pkg)
        if label in excludes:
            removals.append({"package": label, "version": "*", "reason": "excluded"})
            continue
        kept_versions = []
        for ver in pkg.get("versions", []):
            if isinstance(ver, dict) and ver.get("evidence_tier") == "provisional":
                removals.append(
                    {
                        "package": label,
                        "version": ver.get("version", "?"),
                        "reason": "provisional",
                    }
                )
                continue
            kept_versions.append(ver)
        if "versions" in pkg and not kept_versions:
            removals.append({"package": label, "version": "*", "reason": "no_versions_left"})
            continue
        new_pkg = dict(pkg)
        if "versions" in new_pkg:
            new_pkg["versions"] = kept_versions
        packages.append(new_pkg)
    candidate = dict(index)
    candidate["packages"] = packages
    return candidate, removals


def main(argv: list[str] | None = None) -> int:
    """Build a filtered candidate index and record its canonical digest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="OWNER/NAME",
        help="Package id to drop entirely; repeatable",
    )
    parser.add_argument("--out", type=Path, required=True, help="Candidate index output path")
    parser.add_argument("--report", type=Path, help="JSON report output path")
    args = parser.parse_args(argv)

    index = json.loads(args.index.read_text(encoding="utf-8"))
    candidate, removals = materialize_candidate(index, set(args.exclude))
    matched = {r["package"] for r in removals if r["reason"] == "excluded"}
    unmatched = sorted(set(args.exclude) - matched)
    for label in unmatched:
        removals.append({"package": label, "version": "*", "reason": "unmatched_exclude"})
    if unmatched:
        sys.stderr.write(
            "error: --exclude matched no package: " + ", ".join(unmatched) + "\n"
        )
        return 1

    canonical = canonical_json(candidate).encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical)

    digest = hashlib.sha256(canonical).hexdigest()
    report = {
        "schema_version": 1,
        "record_type": "materialized-candidate",
        "source_index": str(args.index),
        "source_package_count": len(index.get("packages", [])),
        "candidate_package_count": len(candidate.get("packages", [])),
        "canonical_index_sha256": digest,
        "exclusions": removals,
        "explicit_excludes": sorted(set(args.exclude)),
    }
    report_text = json.dumps(report, indent=1) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text, encoding="utf-8", newline="\n")
    sys.stderr.write(report_text)
    print(f"wrote {args.out} ({len(candidate.get('packages', []))} packages, sha256 {digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
