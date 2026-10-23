#!/usr/bin/env python3.12
"""Watch already-indexed packages for upstream releases and Nu-version gaps.

Detection plus verdicts only. This script never mutates the registry
index, never signs, and never publishes. With ``--write`` it saves a
machine-readable hits file and a Markdown report; promotion stays
gated: the workflow proves each hit with lifecycle-prove and opens a
per-package PR, auto-merging only ``auto-merge-eligible`` hits whose
proof passed. Plugins always need review (rebuild via numan-plugins).

Usage:
  python scripts/watch_indexed.py [--dry-run] [--write]
      [--index registry/index.json] [--target-nu 0.114.1]
      [--report-json hits.json] [--report-md report.md]
      [--packages owner/name,...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from nu_version_constraint import (
    matches_nu_constraint,
    parse_exact_nu_version,
)
from url_safety import ensure_http_url, github_repo_key

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"
DEFAULT_TARGET_FILE = REPO_ROOT / "docs" / "watch-target-nu.json"
GITHUB_API = "https://api.github.com"
USER_AGENT = "numan-registry-watch-indexed/1.0"
HTTP_SCHEMES = frozenset({"https", "http"})
WATCH_OFF_TAG = "watch-off"
RELEASES_PER_PAGE = 30

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version_tuple(value: str) -> tuple[int, int, int] | None:
    """Parse a plain MAJOR.MINOR.PATCH tag. None for anything else."""
    m = SEMVER.fullmatch(str(value).strip().split("+")[0])
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer(upstream_tag: str, indexed_version: str) -> bool | None:
    """True when the upstream tag is a newer semver. None if uncomparable."""
    up = parse_version_tuple(upstream_tag)
    cur = parse_version_tuple(indexed_version)
    if up is None or cur is None:
        return None
    return up > cur


def repo_key(repo_url: str) -> str | None:
    """Lowercase ``owner/name`` for a GitHub repo URL, else None."""
    if not isinstance(repo_url, str) or not repo_url.strip():
        return None
    return github_repo_key(repo_url.strip())


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class _HttpOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpOnlyRedirectHandler())


def fetch_stable_releases(owner_repo: str, pages: int = 5) -> list[dict]:
    """Stable (non-draft, non-prerelease) releases, newest API order first."""
    stable: list[dict] = []
    for page in range(1, pages + 1):
        url = (f"{GITHUB_API}/repos/{owner_repo}/releases?"
               f"{urlencode({'per_page': RELEASES_PER_PAGE, 'page': page})}")
        ensure_http_url(url)
        req = urllib.request.Request(url, headers=_github_headers())
        with http_opener().open(req, timeout=30) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
        if not isinstance(releases, list):
            return stable
        stable.extend(
            rel for rel in releases
            if isinstance(rel, dict) and not rel.get("draft") and not rel.get("prerelease")
        )
        if len(releases) < RELEASES_PER_PAGE:
            break
    return stable


def fetch_latest_release(owner_repo: str) -> dict | None:
    """Highest-semver stable release, or the newest stable one when none parse."""
    stable = fetch_stable_releases(owner_repo)
    if not stable:
        return None
    parsable = [rel for rel in stable
                if parse_version_tuple(str(rel.get("tag_name", ""))) is not None]
    if parsable:
        return max(parsable,
                   key=lambda rel: parse_version_tuple(str(rel.get("tag_name", ""))))
    return stable[0]


def split_scoped(package: dict) -> str:
    pid = package.get("id") or {}
    return f"{pid.get('owner', '?')}/{pid.get('name', '?')}"


def version_key(version: str) -> tuple[tuple[int, int, int], str]:
    """Numeric semver ordering with a deterministic string tiebreak."""
    return (parse_version_tuple(version) or (0, 0, 0), str(version))


def latest_entry(package: dict) -> dict | None:
    versions = [v for v in package.get("versions", []) if isinstance(v, dict)]
    if not versions:
        return None
    return max(versions, key=lambda v: version_key(str(v.get("version", ""))))


def artifact_id(entry: dict) -> str:
    """Stable identity for a version's artifact block (empty when absent)."""
    import hashlib

    artifact = entry.get("artifact")
    if not isinstance(artifact, dict):
        return ""
    return hashlib.sha256(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def widen_constraint(constraint: str, target_nu: str) -> str | None:
    """Extend a single clean `<M.m.0` upper bound to cover one new minor.

    Returns the widened constraint, or None when the step is bigger than
    one minor, the bound is not a clean minor floor, or the shape is not
    a plain upper bound. Proof on the target Nu is what backs the widened
    claim; anything else stays human-gated.
    """
    target = parse_version_tuple(target_nu)
    if target is None:
        return None
    tokens = str(constraint).split()
    upper = [t for t in tokens if t.startswith("<") and not t.startswith("<=")]
    if len(upper) != 1:
        return None
    bound = parse_version_tuple(upper[0][1:])
    if bound is None or bound[2] != 0:
        return None
    if (bound[0], bound[1]) != (target[0], target[1]):
        return None
    widened = [t for t in tokens if t != upper[0]]
    widened.append(f"<{target[0]}.{target[1] + 1}.0")
    candidate = " ".join(widened)
    try:
        if not matches_nu_constraint(target_nu, candidate):
            return None
    except ValueError:
        return None
    return candidate


def nu_gap_plan(constraint: str, target_nu: str) -> str | None:
    """How a Nu gap can close: 'append', 'widen', or None (human-gated)."""
    try:
        if matches_nu_constraint(target_nu, constraint):
            return "append"
    except ValueError:
        return None
    if widen_constraint(constraint, target_nu) is not None:
        return "widen"
    return None


def should_skip(package: dict) -> bool:
    return WATCH_OFF_TAG in (package.get("tags") or [])


def _asset_briefs(release: dict, limit: int = 20) -> list[dict]:
    """Name + URL for release assets so issues carry the exact spec inputs."""
    briefs: list[dict] = []
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return briefs
    for asset in assets[:limit]:
        if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url"):
            briefs.append({"name": str(asset["name"]),
                           "url": str(asset["browser_download_url"])})
    return briefs


def detect(packages: list[dict], releases: dict[str, dict], target_nu: str) -> dict:
    """Type A: newer upstream tag. Type B: indexed constraint excludes target Nu."""
    upstream_updates: list[dict] = []
    nu_gaps: list[dict] = []
    for package in packages:
        if not isinstance(package, dict) or should_skip(package):
            continue
        scoped = split_scoped(package)
        latest = latest_entry(package)
        if latest is None:
            continue
        indexed = str(latest.get("version", "0.0.0"))
        ptype = str(package.get("type", ""))
        rel = releases.get(scoped)
        if rel and rel.get("tag_name"):
            newer = is_newer(str(rel["tag_name"]), indexed)
            if newer:
                upstream_updates.append({
                    "kind": "upstream",
                    "package": scoped,
                    "type": ptype,
                    "indexed": indexed,
                    "upstream": str(rel["tag_name"]),
                    "url": str(rel.get("html_url", "")),
                    "assets": _asset_briefs(rel),
                    "artifact_id": artifact_id(latest),
                })
            elif newer is None:
                upstream_updates.append({
                    "kind": "upstream-unparsed",
                    "package": scoped,
                    "type": ptype,
                    "indexed": indexed,
                    "upstream": str(rel["tag_name"]),
                    "url": str(rel.get("html_url", "")),
                    "assets": _asset_briefs(rel),
                    "artifact_id": artifact_id(latest),
                })
        constraint = str(latest.get("nu_version", "*"))
        verified = [str(v) for v in (latest.get("verified_with") or [])]
        try:
            excluded = not matches_nu_constraint(target_nu, constraint)
        except ValueError:
            excluded = True
        if excluded and target_nu not in verified:
            nu_gaps.append({
                "kind": "nu-gap",
                "package": scoped,
                "type": ptype,
                "indexed": indexed,
                "constraint": constraint,
                "target_nu": target_nu,
                "artifact_id": artifact_id(latest),
            })
    upstream_updates.sort(key=lambda h: h["package"])
    nu_gaps.sort(key=lambda h: h["package"])
    return {"upstream_updates": upstream_updates, "nu_gaps": nu_gaps}


def _is_major_bump(hit: dict) -> bool | None:
    """True on a major bump, False on minor/patch, None when uncomparable."""
    upstream = parse_version_tuple(str(hit.get("upstream", "")))
    indexed = parse_version_tuple(str(hit.get("indexed", ""))) or (0, 0, 0)
    if upstream is None:
        return None
    return upstream[0] > indexed[0]


def _decide_upstream(hit: dict, ptype: str, reasons: list[str]) -> dict:
    newer = is_newer(str(hit.get("upstream", "")), str(hit.get("indexed", "")))
    if newer is None:
        reasons.append("version is not plain semver; map it by hand")
    elif _is_major_bump(hit):
        reasons.append("major version bump; review behavior changes")
    elif ptype in ("module", "script", "completion") and newer and not reasons:
        return {"verdict": "auto-merge-eligible",
                "reasons": ["minor/patch bump; lifecycle proof required before merge"]}
    elif not newer:
        return {"verdict": "up-to-date",
                "reasons": ["indexed version already covers upstream"]}
    return {"verdict": "needs-review", "reasons": reasons or ["manual mapping needed"]}


def _decide_nu_gap(hit: dict, ptype: str, reasons: list[str]) -> dict:
    if ptype not in ("module", "script", "completion") or reasons:
        return {"verdict": "needs-review", "reasons": reasons or ["manual mapping needed"]}
    if parse_version_tuple(str(hit.get("indexed", ""))) is None:
        return {"verdict": "needs-review",
                "reasons": ["indexed version is not plain semver; map it by hand"]}
    plan = nu_gap_plan(str(hit.get("constraint", "*")), str(hit.get("target_nu", "")))
    if plan == "append":
        return {"verdict": "auto-merge-eligible",
                "reasons": ["same artifact; re-prove on the new Nu then append verified_with"]}
    if plan == "widen":
        return {"verdict": "auto-merge-eligible",
                "reasons": ["same artifact; re-prove on the new Nu, then append verified_with "
                            "and widen the constraint by one minor"]}
    return {"verdict": "needs-review",
            "reasons": ["constraint step is bigger than one minor; widen it by hand"]}


def _plugin_reasons(kind: str, reasons: list[str]) -> list[str]:
    if kind == "upstream":
        reasons.append("plugins rebuild via numan-plugins before intake")
    else:
        reasons.append("plugins are ABI-locked; a new Nu minor needs a rebuild check")
    return reasons or ["plugin gate"]


def decide(hit: dict, latest: dict) -> dict:
    """Verdict for one hit. Proof still runs in CI; eligible merges only on green."""
    kind = hit.get("kind", "")
    ptype = hit.get("type", "")
    if kind == "upstream-unparsed":
        return {"verdict": "needs-review",
                "reasons": ["upstream tag is not plain semver; map it by hand"]}
    reasons: list[str] = []
    if (latest.get("evidence_tier") or "") == "provisional":
        reasons.append("evidence_tier is provisional; a human owns the deferral")
    if ptype == "plugin":
        return {"verdict": "needs-review", "reasons": _plugin_reasons(kind, reasons)}
    if kind == "upstream":
        return _decide_upstream(hit, ptype, reasons)
    if kind == "nu-gap":
        return _decide_nu_gap(hit, ptype, reasons)
    return {"verdict": "needs-review", "reasons": ["unknown hit kind"]}


def attach_verdicts(gaps: dict, by_package: dict[str, dict]) -> dict:
    """Add a decide() verdict to every hit. Returns the same gaps dict."""
    for section in ("upstream_updates", "nu_gaps"):
        for hit in gaps.get(section, []):
            latest = latest_entry(by_package.get(hit["package"], {})) or {}
            outcome = decide(hit, latest)
            hit["verdict"] = outcome["verdict"]
            hit["reasons"] = outcome["reasons"]
    return gaps


def format_markdown(gaps: dict, target_nu: str) -> str:
    checked = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Indexed-package watch report",
        "",
        f"Checked at {checked} against Nushell {target_nu}. "
        "Detection plus verdicts only: nothing here is published automatically.",
        "",
    ]
    for section, title in (("upstream_updates", "## New upstream releases (Type A)"),
                           ("nu_gaps", f"## Nu {target_nu} gaps (Type B)")):
        lines += ["", title, ""]
        hits = gaps.get(section, [])
        if not hits:
            lines.append("None.")
        for hit in hits:
            if section == "upstream_updates":
                detail = f"indexed {hit['indexed']} -> upstream {hit.get('upstream', '?')} ({hit.get('url', '')})"
            else:
                detail = (f"v{hit['indexed']} needs Nu {hit.get('constraint', '?')} "
                          f"(target {hit.get('target_nu', target_nu)})")
            lines.append(
                f"- `{hit['package']}` [{hit.get('type', '')}] {detail} "
                f"**{hit.get('verdict', 'needs-review')}** "
                f"({'; '.join(hit.get('reasons', []))})"
            )
    lines += [
        "",
        "## Promotion checklist (per package)",
        "",
        "- [ ] Draft spec with provenance via existing intake tooling (no hand-typed hashes)",
        "- [ ] Run validate + parser-check + manifest lint",
        "- [ ] Run lifecycle-prove on the target Nu; attach evidence",
        "- [ ] Append verified_with only if lifecycle proof passed",
        "- [ ] Auto-merge only when verdict is auto-merge-eligible AND proof passed",
        "",
    ]
    return "\n".join(lines)


def write_outputs(gaps: dict, target_nu: str) -> None:
    upstream_updates = gaps.get("upstream_updates", [])
    nu_gaps = gaps.get("nu_gaps", [])
    hits = upstream_updates + nu_gaps
    eligible = [h for h in hits if h.get("verdict") == "auto-merge-eligible"]
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"has_updates={'true' if hits else 'false'}\n")
            f.write(f"hit_count={len(hits)}\n")
            f.write(f"upstream_count={len(upstream_updates)}\n")
            f.write(f"nu_gap_count={len(nu_gaps)}\n")
            f.write(f"eligible_count={len(eligible)}\n")
            f.write(f"target_nu={target_nu}\n")
            f.write(f"hits_json={json.dumps(hits)}\n")
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as f:
            f.write(format_markdown(gaps, target_nu))
            f.write("\n")


def _read_target_nu_file() -> str:
    """Target Nu from the checked-in default file, or '' when unreadable."""
    try:
        state = json.loads(DEFAULT_TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(state, dict):
        return ""
    return str(state.get("target_nu", "")).strip().lstrip("vV")


def resolve_target_nu(explicit: str | None) -> str:
    if explicit:
        return explicit.lstrip("vV")
    version = _read_target_nu_file()
    if version:
        return version
    raise ValueError(f"no --target-nu and no readable {DEFAULT_TARGET_FILE}")


def process(index_path: Path, target_nu: str, write: bool,
            report_json: Path, report_md: Path,
            package_filter: list[str] | None = None) -> int:
    parse_exact_nu_version(target_nu)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    packages = [p for p in index.get("packages", []) if isinstance(p, dict)]
    if package_filter:
        wanted = set(package_filter)
        packages = [p for p in packages if split_scoped(p) in wanted]
    releases: dict[str, dict] = {}
    for package in packages:
        if should_skip(package):
            continue
        key = repo_key(str(package.get("repo", "")))
        if key is None:
            continue
        scoped = split_scoped(package)
        try:
            rel = fetch_latest_release(key)
        except Exception as exc:  # one bad repo must not sink the whole run
            print(f"warning: {scoped}: release lookup failed: {exc}", file=sys.stderr)
            continue
        if rel is not None:
            releases[scoped] = rel
    by_package = {split_scoped(p): p for p in packages if isinstance(p, dict)}
    gaps = attach_verdicts(detect(packages, releases, target_nu), by_package)
    report = format_markdown(gaps, target_nu)
    print(report)
    if not write:
        print("[dry-run] reports not written. Pass --write to save them.")
        write_outputs(gaps, target_nu)
        return 0
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(gaps, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(report, encoding="utf-8")
    print(f"Updated {report_json} and {report_md}")
    write_outputs(gaps, target_nu)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch indexed packages for updates (detection plus verdicts).")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--target-nu", default=None,
                        help="Target Nu version (default: docs/watch-target-nu.json).")
    parser.add_argument("--dry-run", action="store_true", help="Print only (default).")
    parser.add_argument("--write", action="store_true", help="Write JSON and Markdown reports.")
    parser.add_argument("--report-json", type=Path, default=REPO_ROOT / "hits.json")
    parser.add_argument("--report-md", type=Path, default=REPO_ROOT / "watch-indexed-report.md")
    parser.add_argument("--packages", default=None, help="Comma-separated owner/name filter.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    package_filter = [s.strip() for s in args.packages.split(",")] if args.packages else None
    try:
        target_nu = resolve_target_nu(args.target_nu)
        return process(
            index_path=args.index,
            target_nu=target_nu,
            write=bool(args.write and not args.dry_run),
            report_json=args.report_json,
            report_md=args.report_md,
            package_filter=package_filter,
        )
    except Exception as exc:
        print(f"Error watching indexed packages: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
