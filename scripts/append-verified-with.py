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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"


def split_scoped(package: dict) -> str:
    pid = package.get("id") or {}
    return f"{pid.get('owner', '?')}/{pid.get('name', '?')}"


def apply(index: dict, hits: dict, proven: set[str], target_nu: str) -> list[str]:
    """Append target_nu to verified_with for proven nu-gap hits. Returns changed ids."""
    wanted = {h["package"] for h in hits.get("nu_gaps", [])
              if h.get("verdict") == "auto-merge-eligible" and h["package"] in proven}
    changed: list[str] = []
    for package in index.get("packages", []):
        if not isinstance(package, dict) or split_scoped(package) not in wanted:
            continue
        versions = [v for v in package.get("versions", []) if isinstance(v, dict)]
        if not versions:
            continue
        latest = max(versions, key=lambda v: str(v.get("version", "")))
        if latest.get("version") != next(
                h["indexed"] for h in hits["nu_gaps"]
                if h["package"] == split_scoped(package)):
            continue  # artifact moved under us; refuse
        verified = latest.setdefault("verified_with", [])
        if target_nu not in verified:
            verified.append(target_nu)
            verified.sort()
            changed.append(split_scoped(package))
    return changed


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
        changed = apply(index, hits, proven, target_nu)
        print(f"would update: {', '.join(changed) or 'none'}")
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
