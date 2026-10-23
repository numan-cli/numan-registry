#!/usr/bin/env python3.12
"""Append lifecycle-proven Nu versions to indexed entries (nu-gap lane).

Reads a hits file from watch_indexed.py and, for every nu-gap hit whose
proof passed, appends the target Nu to that version's verified_with.
Only touches entries where the artifact is unchanged (same version
string); anything else is refused. Never commits, pushes, or signs.

Usage:
  python scripts/append-verified-with.py --hits hits.json --proven a/mod,b/other --write
  python scripts/append-verified-with.py --hits hits.json --proven a/mod --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from watch_indexed import artifact_id, latest_entry, nu_gap_plan, widen_constraint

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"


def split_scoped(package: dict) -> str:
    pid = package.get("id") or {}
    return f"{pid.get('owner', '?')}/{pid.get('name', '?')}"


def apply(index: dict, hits: dict, proven: set[str], target_nu: str
          ) -> tuple[list[str], list[str]]:
    """Close proven nu-gap hits. Returns (changed ids, refused ids).

    Appends target_nu to verified_with, widening a single-minor upper
    bound first when the plan calls for it. Refuses anything else: the
    artifact must be byte-identical to detection time, the indexed
    version must still match, and the constraint step must be closable
    by append or one-minor widen.
    """
    wanted = {h["package"] for h in hits.get("nu_gaps", [])
              if h.get("verdict") == "auto-merge-eligible" and h["package"] in proven}
    by_package = {split_scoped(p): p for p in index.get("packages", [])
                  if isinstance(p, dict)}
    changed: list[str] = []
    refused: list[str] = []
    for hit in hits.get("nu_gaps", []):
        scoped = hit.get("package", "")
        if scoped not in wanted:
            continue
        package = by_package.get(scoped)
        latest = latest_entry(package) if package else None
        if latest is None or str(latest.get("version", "")) != str(hit.get("indexed", "")):
            refused.append(scoped)  # artifact moved under us; refuse
            continue
        if hit.get("artifact_id") and artifact_id(latest) != hit["artifact_id"]:
            refused.append(scoped)  # same version string, different bytes; refuse
            continue
        plan = nu_gap_plan(str(latest.get("nu_version", "*")), target_nu)
        if plan == "widen":
            widened = widen_constraint(str(latest.get("nu_version", "*")), target_nu)
            if widened is None:
                refused.append(scoped)
                continue
            latest["nu_version"] = widened
        elif plan != "append":
            refused.append(scoped)
            continue
        verified = latest.setdefault("verified_with", [])
        if target_nu not in verified:
            verified.append(target_nu)
            verified.sort()
        if scoped not in changed:
            changed.append(scoped)
    return changed, refused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append proven Nu versions to the index.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--hits", type=Path, required=True)
    parser.add_argument("--proven", default="",
                        help="Comma-separated owner/name hits whose proof passed.")
    parser.add_argument("--target-nu", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    try:
        index = json.loads(args.index.read_text(encoding="utf-8"))
        hits = json.loads(args.hits.read_text(encoding="utf-8"))
        proven = {s.strip() for s in args.proven.split(",") if s.strip()}
        target_nu = args.target_nu or next(
            (h.get("target_nu") for h in hits.get("nu_gaps", []) if h.get("target_nu")),
            None,
        )
        if not target_nu:
            print("no target Nu: pass --target-nu or include nu-gap hits", file=sys.stderr)
            return 1
        changed, refused = apply(index, hits, proven, target_nu)
        print(f"would update: {', '.join(changed) or 'none'}")
        if refused:
            print(f"refused (needs a human): {', '.join(refused)}", file=sys.stderr)
            print("[refused] index not written. Resolve the refusals first.")
            return 1
        if args.write and not args.dry_run:
            args.index.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            print(f"Updated {args.index}")
        else:
            print("[dry-run] index not written. Pass --write to save it.")
        return 0
    except Exception as exc:
        print(f"Error appending verified_with: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
