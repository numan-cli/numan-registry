#!/usr/bin/env python3
"""Render docs/catalog-compat.md from registry/index.json.

This is the human-readable master list of official-registry packages and their
Nu version constraints. Edit the index via add-package.py; regenerate this file
(do not hand-edit the table).

Usage:
  python scripts/render_catalog_compat.py           # write docs/catalog-compat.md
  python scripts/render_catalog_compat.py --check    # exit 1 if committed file drifts
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "registry" / "index.json"
OUT_PATH = REPO_ROOT / "docs" / "catalog-compat.md"

NU_BANDS = ("0.114", "0.113", "0.112", "other", "*")
# Named minor bands only (derived so nu_band cannot drift from NU_BANDS).
KNOWN_MINOR_BANDS = tuple(b for b in NU_BANDS if b not in ("other", "*"))
# Accept >= and strict > lower bounds (repo constraint lint allows both).
_LOWER_BOUND = re.compile(r">=?\s*0\.(\d+)")


def load_index(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def package_id(pkg: dict[str, Any]) -> str:
    pid = pkg["id"]
    return f"{pid['owner']}/{pid['name']}"


def nu_band(constraint: str) -> str:
    """Coarse band from the constraint lower bound (not the exclusive upper)."""
    text = (constraint or "").strip()
    if not text or text == "*":
        return "*"
    match = _LOWER_BOUND.search(text)
    if match:
        band = f"0.{match.group(1)}"
        if band in KNOWN_MINOR_BANDS:
            return band
        return "other"
    # Fallback: bare minor mention without a comparator (rare). Prefer the
    # earliest occurrence so upper-bound minors (e.g. <0.114.0) do not win.
    hits = [(text.find(band), band) for band in KNOWN_MINOR_BANDS if band in text]
    if hits:
        return min(hits)[1]
    return "other"


def target_labels(artifact: dict[str, Any]) -> str:
    if artifact.get("kind") != "binary":
        return "—"
    targets = artifact.get("targets") or {}
    if not targets:
        return "(none)"
    # Compact OS labels from triples.
    labels: list[str] = []
    seen: set[str] = set()
    for triple in sorted(targets):
        if "windows" in triple:
            key = "win"
        elif "apple-darwin" in triple:
            key = "mac"
        elif "linux" in triple:
            key = "linux"
        else:
            key = triple
        if key not in seen:
            seen.add(key)
            labels.append(key)
    return ",".join(labels)


def provenance_hint(artifact: dict[str, Any]) -> str:
    urls: list[str] = []
    top = artifact.get("url") or ""
    if top:
        urls.append(top)
    if artifact.get("kind") == "binary":
        for target in (artifact.get("targets") or {}).values():
            url = (target or {}).get("url") or ""
            if url:
                urls.append(url)
    if not urls:
        return "other"
    kinds: set[str] = set()
    for url in urls:
        if (
            "numan-registry/releases/download/" in url
            or "numan-cli/numan-registry/releases/" in url
            or "tonythethompson/numan-registry/releases/" in url
        ):
            kinds.add("mirror")
        elif "numan-plugins/releases/" in url:
            kinds.add("ci-built")
        elif url.startswith("http"):
            kinds.add("upstream")
        else:
            kinds.add("other")
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def rows_from_index(index: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pkg in index.get("packages", []):
        versions = pkg.get("versions") or []
        if not versions:
            continue
        latest = versions[-1]
        artifact = latest.get("artifact") or {}
        constraint = latest.get("nu_version") or ""
        rows.append(
            {
                "id": package_id(pkg),
                "type": pkg.get("type") or "?",
                "version": latest.get("version") or "?",
                "nu_version": constraint or "*",
                "band": nu_band(constraint),
                "targets": target_labels(artifact),
                "provenance": provenance_hint(artifact),
                "version_count": len(versions),
            }
        )
    rows.sort(key=lambda r: r["id"].casefold())
    return rows


def render(index: dict[str, Any], generated_at: str) -> str:
    rows = rows_from_index(index)
    type_counts = Counter(r["type"] for r in rows)
    band_counts = Counter(r["band"] for r in rows)
    updated = index.get("updated_at") or "?"
    revision = index.get("registry_revision") or "?"

    lines = [
        "# Official registry catalog compatibility",
        "",
        "_Auto-generated from `registry/index.json`. Do not hand-edit._",
        "",
        f"Generated: `{generated_at}` · Index `updated_at`: `{updated}` · "
        f"`registry_revision`: `{revision}`",
        "",
        "This is the **master list** of packages in the committed `registry/index.json` "
        "(in-tree; the public CDN updates after production signing/publish) "
        "and the Nu constraint on each package's **latest** version. For demand-"
        "ranked *plugin candidates* not yet in the registry, see "
        "[`numan-plugins/docs/backlog.json`](https://github.com/numan-cli/numan-plugins/blob/main/docs/backlog.json). "
        "For intake workflow status, see [`intake-candidates.md`](intake-candidates.md).",
        "",
        "## Summary",
        "",
        f"- **{len(rows)}** packages total",
        "- By type: "
        + ", ".join(f"`{k}` {type_counts[k]}" for k in sorted(type_counts)),
        "- Latest version Nu band: "
        + ", ".join(
            f"`{b}` {band_counts.get(b, 0)}" for b in NU_BANDS if band_counts.get(b, 0)
        ),
        "",
        "Nu band is a coarse label from the constraint **lower bound** "
        "(`>=0.114` / `>0.113` → `0.114` / `0.113`, etc.; else `*` or `other`). "
        "Exact constraints are in the table and in the signed index.",
        "",
        "## Catalog (latest version per package)",
        "",
        "| Package | Type | Latest | Nu constraint | Band | Targets | Provenance | Versions |",
        "|---------|------|--------|---------------|------|---------|------------|----------|",
    ]
    for r in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{r['id']}`",
                    r["type"],
                    r["version"],
                    f"`{r['nu_version']}`",
                    r["band"],
                    r["targets"],
                    r["provenance"],
                    str(r["version_count"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## How to refresh",
            "",
            "```bash",
            "python scripts/render_catalog_compat.py",
            "python scripts/render_catalog_compat.py --check   # CI drift gate",
            "```",
            "",
            "Run after every index-changing PR (`add-package.py --write`, mirrors, "
            "Nu constraint edits). Commit the regenerated markdown with the index.",
            "",
            "## Related lists",
            "",
            "| List | Role |",
            "|------|------|",
            "| `registry/index.json` | Signed source of truth (all versions + hashes) |",
            "| `docs/catalog-compat.md` | This file: human catalog × Nu overview |",
            "| `docs/intake-state.json` / `intake-candidates.md` | Intake pipeline status |",
            "| `numan-plugins/manifest.json` | CI-built plugins currently built |",
            "| `numan-plugins/docs/backlog.json` | Demand-ranked plugin candidates |",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if docs/catalog-compat.md does not match a fresh render",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=INDEX_PATH,
        help="path to registry/index.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help="path to docs/catalog-compat.md",
    )
    args = parser.parse_args(argv)

    index = load_index(args.index)
    # Stable timestamp for --check: use index updated_at so reruns don't churn.
    generated_at = index.get("updated_at") or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    text = render(index, generated_at)

    if args.check:
        if not args.out.exists():
            print(f"FAIL: missing {args.out}", file=sys.stderr)
            return 1
        current = args.out.read_text(encoding="utf-8")
        if current != text:
            print(
                f"FAIL: {args.out} is stale; run "
                "`python scripts/render_catalog_compat.py`",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.out} matches index")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Explicit newline keeps LF on Windows hosts too.
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"Wrote {args.out} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
