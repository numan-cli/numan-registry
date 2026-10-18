#!/usr/bin/env python3
"""Regenerate docs/intake-candidates.md from intake-state.json + live signals.

Reads registry/index.json (what is pinned), optional gh CLI (open PRs, outreach
issues), and writes an updated markdown doc plus the outreach tracker table in
docs/upstream-release-outreach.md.

Usage:
  python scripts/sync-intake-candidates.py
  python scripts/sync-intake-candidates.py --hook stop   # Cursor hook entry
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_formats import SUPPORTED_ARCHIVE_SUFFIXES_MARKDOWN
from gh_helpers import gh_json, gh_text

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "docs" / "intake-state.json"
OUT_PATH = REPO_ROOT / "docs" / "intake-candidates.md"
INDEX_PATH = REPO_ROOT / "registry" / "index.json"
OUTREACH_DOC = REPO_ROOT / "docs" / "upstream-release-outreach.md"
CHECKSUM_CACHE = REPO_ROOT / ".mrge" / "sync-checksums.json"
REGISTRY_REPO = "numan-cli/numan-registry"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_provenance(url: str) -> str:
    """Classify a pinned artifact URL as mirror, ci-built, upstream, or other."""
    if (
        "numan-registry/releases/download/" in url
        or "numan-cli/numan-registry/releases/" in url
        or "tonythethompson/numan-registry/releases/" in url
    ):
        return "mirror"
    if "numan-plugins/releases/" in url or "tonythethompson/numan-plugins/releases/" in url or "numan-cli/numan-plugins/releases/" in url:
        return "ci-built"
    if url.startswith("http"):
        return "upstream"
    return "other"


def artifact_urls(artifact: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    top = artifact.get("url") or ""
    if top:
        urls.append(top)
    if artifact.get("kind") == "binary":
        for target in artifact.get("targets", {}).values():
            url = (target or {}).get("url") or ""
            if url:
                urls.append(url)
    return urls


def artifact_provenances(artifact: dict[str, Any]) -> set[str]:
    urls = artifact_urls(artifact)
    # Empty binary (no URLs) is "other", not an empty set, so package_kind stays defined.
    if not urls:
        return {"other"}
    return {artifact_provenance(url) for url in urls}


def package_kind(provenances: set[str]) -> str:
    return next(iter(provenances)) if len(provenances) == 1 else "mixed"


def registry_packages(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    live: dict[str, dict[str, Any]] = {}
    for pkg in index.get("packages", []):
        pid = pkg["id"]
        key = f"{pid['owner']}/{pid['name']}"
        versions = pkg.get("versions", [])
        latest = versions[-1] if versions else {}
        provenances = artifact_provenances(latest.get("artifact", {}))
        live[key] = {
            "version": latest.get("version", "?"),
            # Any mirror URL keeps mirror=True so outreach stays "mirror only"
            # until every target leaves the registry mirror.
            "mirror": "mirror" in provenances,
            "ci_built": provenances == {"ci-built"},
            "upstream_asset": provenances == {"upstream"},
            "mixed": len(provenances) > 1,
        }
    return live


def pr_state(number: int | None) -> str | None:
    if not number:
        return None
    data = gh_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            REGISTRY_REPO,
            "--json",
            "state,mergedAt,url",
        ]
    )
    if not data:
        return None
    state = data.get("state", "").upper()
    if state == "MERGED":
        return "merged"
    if state == "OPEN":
        return "open"
    if state == "CLOSED":
        return "closed"
    return state.lower() if state else None


def outreach_status(outreach: dict[str, Any]) -> dict[str, str]:
    """Return outreach fields: issue, opened, response, upstream_shipped."""
    result = {
        "issue": "",
        "opened": "",
        "response": "",
        "upstream_shipped": "",
        "summary": "not started",
    }
    repo = outreach.get("upstream_repo")
    if not repo:
        return result

    blocked = outreach.get("blocked")
    if blocked:
        result["issue"] = f"blocked ({blocked})"
        result["summary"] = f"blocked ({blocked})"
        return result

    issue_url = outreach.get("issue_url")
    issue_number: int | None = None
    if issue_url:
        m = re.search(r"/issues/(\d+)", issue_url)
        if m:
            issue_number = int(m.group(1))

    if issue_number is None:
        search = " ".join(outreach.get("search_terms", ["numan", "release zip"]))
        found = gh_json(
            [
                "issue",
                "list",
                "--repo",
                repo,
                "--author",
                "@me",
                "--state",
                "all",
                "--search",
                search,
                "--limit",
                "3",
                "--json",
                "number,title,state,url,comments,updatedAt",
            ]
        )
        if found:
            issue_number = found[0]["number"]
            issue_url = found[0]["url"]
            outreach["issue_url"] = issue_url  # persist discovery

    if issue_number is None:
        result["summary"] = "outreach pending"
        return result

    detail = gh_json(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "number,title,state,url,comments,createdAt,updatedAt",
        ]
    )
    if not detail:
        result["issue"] = issue_url or f"{repo}#{issue_number}"
        result["summary"] = "issue filed (status unknown)"
        return result

    result["issue"] = f"[#{detail['number']}]({detail['url']})"
    created = detail.get("createdAt", "")[:10]
    result["opened"] = created

    comments = gh_json(
        [
            "api",
            f"repos/{repo}/issues/{issue_number}/comments",
            "--jq",
            "[.[] | {user: .user.login, created_at: .created_at}]",
        ]
    )
    me = gh_text(["api", "user", "--jq", ".login"])
    if comments and me:
        others = [c for c in comments if c.get("user") != me]
        if others:
            result["response"] = f"yes ({others[-1]['created_at'][:10]})"
            result["summary"] = f"responded — see {repo}#{issue_number}"
        else:
            result["response"] = "awaiting"
            result["summary"] = f"issue open, awaiting response ({repo}#{issue_number})"
    else:
        result["response"] = "awaiting"
        result["summary"] = f"issue open ({repo}#{issue_number})"

    if detail.get("state") == "CLOSED":
        result["summary"] = f"issue closed ({repo}#{issue_number})"

    return result


def _live_status(
    entry: dict[str, Any], live: dict[str, dict[str, Any]]
) -> list[str] | None:
    """Status parts for an entry already in the registry index, else None."""
    pid = entry["id"]
    if pid not in live:
        return None
    info = live[pid]
    version = entry.get("version", "")
    parts: list[str] = []
    if info.get("mixed"):
        parts.append("live (mixed provenance)")
    elif info.get("mirror"):
        parts.append("live (registry mirror)")
    elif info.get("ci_built"):
        parts.append("live (ci-built asset)")
    elif info.get("upstream_asset"):
        parts.append("live (upstream asset)")
    else:
        parts.append("live")
    if version and info.get("version") != version:
        parts.append(f"index@{info['version']}")
    return parts


def _pr_status(entry: dict[str, Any], pr_map: dict[int, str | None]) -> list[str] | None:
    """Status parts for an entry with an intake PR, else None (no PR)."""
    pr_num = entry.get("pr")
    if not pr_num:
        return None
    pull = f"https://github.com/{REGISTRY_REPO}/pull/{pr_num}"
    ps = pr_map.get(pr_num)
    if ps == "merged":
        return [f"merged in [#{pr_num}]({pull}) — publish pending?"]
    if ps == "open":
        return [f"PR [#{pr_num}]({pull}) open"]
    if ps == "closed":
        return [f"PR #{pr_num} closed (not merged)"]
    return [f"pending [#{pr_num}]({pull})"]


def _candidate_status(entry: dict[str, Any]) -> list[str]:
    """Status parts for an entry not in the index and without an intake PR."""
    spec = entry.get("spec")
    if spec and (REPO_ROOT / spec).exists():
        return ["spec written, not in index"]
    return ["candidate"]


def package_status(
    entry: dict[str, Any],
    live: dict[str, dict[str, Any]],
    pr_map: dict[int, str | None],
    outreach_cache: dict[str, dict[str, str]],
) -> str:
    """Render the status cell for one intake entry.

    The three branch helpers are mutually exclusive: an entry is either live in
    the index, awaiting an intake PR, or a plain candidate.
    """
    pid = entry["id"]
    note = entry.get("note")

    parts = _live_status(entry, live)
    if parts is None:
        parts = _pr_status(entry, pr_map)
    if parts is None:
        parts = _candidate_status(entry)

    outreach = entry.get("outreach")
    if outreach:
        o = outreach_cache.get(pid, {})
        if o:
            parts.append(f"outreach: {o['summary']}")

    if note:
        parts.append(note)

    return " — ".join(parts)


def render_intake_doc(
    state: dict[str, Any],
    live: dict[str, dict[str, Any]],
    index: dict[str, Any],
    outreach_cache: dict[str, dict[str, str]],
) -> str:
    """
    Generate the Markdown document listing registry intake candidates and their statuses.
    
    Parameters:
    	state (dict[str, Any]): Intake candidates, blocked packages, and changelog entries.
    	live (dict[str, dict[str, Any]]): Current package information from the registry.
    	index (dict[str, Any]): Registry index data used to summarize package versions.
    	outreach_cache (dict[str, dict[str, str]]): Cached outreach statuses keyed by package identifier.
    
    Returns:
    	str: The rendered intake-candidates Markdown document.
    """
    pr_nums = {
        e.get("pr")
        for section in ("ready", "mirror")
        for e in state.get(section, [])
        if e.get("pr")
    }
    pr_map = {n: pr_state(n) for n in pr_nums if n}

    entries: list[tuple[str, str]] = []
    for pkg in index.get("packages", []):
        pid = pkg["id"]
        key = f"{pid['owner']}/{pid['name']}"
        version_data = [v for v in pkg.get("versions", []) if v.get("version")]
        if not version_data:
            continue
        versions = [v["version"] for v in version_data]
        provenances: set[str] = set()
        for version in version_data:
            provenances |= artifact_provenances(version.get("artifact", {}))
        kind = package_kind(provenances)
        if len(versions) == 1:
            text = f"`{key}@{versions[0]}` ({kind})"
        else:
            text = f"`{key}` ({', '.join(versions)}; {kind})"
        entries.append((key, text))
    entries.sort(key=lambda item: item[0].casefold())
    registry_line = ", ".join(text for _, text in entries) if entries else "(none)"

    lines = [
        "# Registry intake candidates",
        "",
        "Running list of packages evaluated for the official Numan registry.",
        "_Auto-synced from `docs/intake-state.json`, `registry/index.json`, and GitHub (via `gh`). Edit `intake-state.json` to add candidates; run `python scripts/sync-intake-candidates.py` to refresh._",
        "",
        f"**Intake rules:** artifact must be {SUPPORTED_ARCHIVE_SUFFIXES_MARKDOWN}; prefer upstream uploaded release assets over GitHub auto-generated `/archive/` zipballs; never hand-type `sha256` (use `scripts/add-package.py`); mirror packages via `scripts/build-mirror-zip.py` + registry release upload. After intake, the package **must be staged or published** in the configured registry before running Stage 1 lifecycle-prove (`scripts/lifecycle-prove.py --package owner/name`), unless a registry-target override is added. Run lifecycle-prove on a clean root against a real Nu matching the package constraint ([lifecycle-prove.md](lifecycle-prove.md)). For CI-built plugins from `numan-plugins` that have matching registry entries, keep known `nu_version` constraints in sync with `manifest.json` `active[]` (`scripts/lint-manifest-index.py` enforces this in repo-safety CI). See [upstream-release-outreach.md](upstream-release-outreach.md) for contacting maintainers to ship upstream assets.",
        "",
        f"**Currently in committed index** (source tree; unsigned until production publish signs and deploys): {registry_line}.",
        "",
        "---",
        "",
        "## Ready to add now",
        "",
        "Upstream ships byte-stable release assets in Numan-supported formats.",
        "",
        "| Package | Type | Version | Platforms | Status |",
        "|---------|------|---------|-----------|--------|",
    ]

    for entry in state.get("ready", []):
        link = f"[`{entry['id']}`]({entry['repo']})"
        status = package_status(entry, live, pr_map, outreach_cache)
        lines.append(
            f"| {link} | {entry['type']} | v{entry['version']} | {entry['platforms']} | {status} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Worth adding via registry mirror",
            "",
            "No compliant upstream release asset; pack a tag/commit snapshot as a registry-hosted zip (see `scripts/build-mirror-zip.py`).",
            "",
            "| Package | Type | Source | Status |",
            "|---------|------|--------|--------|",
        ]
    )

    for entry in state.get("mirror", []):
        link = f"[`{entry['id']}`]({entry['repo']})"
        status = package_status(entry, live, pr_map, outreach_cache)
        lines.append(
            f"| {link} | {entry['type']} | {entry['source']} | {status} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Blocked for now",
            "",
            "| Package | Blocker |",
            "|---------|---------|",
        ]
    )
    for entry in state.get("blocked", []):
        pkg = entry["id"]
        if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", pkg):
            link = f"[`{pkg}`](https://github.com/{pkg})"
        else:
            link = pkg
        lines.append(f"| {link} | {entry['blocker']} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## Changelog",
            "",
            "| Date | Change |",
            "|------|--------|",
        ]
    )
    for row in state.get("changelog", []):
        lines.append(f"| {row['date']} | {row['change']} |")

    lines.append("")
    return "\n".join(lines)


def update_outreach_tracker(
    state: dict[str, Any],
    live: dict[str, dict[str, Any]],
    outreach_cache: dict[str, dict[str, str]],
) -> bool:
    if not OUTREACH_DOC.exists():
        return False

    text = OUTREACH_DOC.read_text(encoding="utf-8")
    start = text.find("## Outreach tracker")
    if start == -1:
        return False
    end = text.find("\n---\n", start + 1)
    if end == -1:
        return False

    rows = [
        "| Upstream | Issue/PR | Opened | Response | Upstream asset shipped | Registry switched |",
        "|----------|----------|--------|----------|------------------------|-------------------|",
    ]

    for entry in state.get("mirror", []):
        outreach = entry.get("outreach") or {}
        if entry["owner"] == "nushell" and entry["name"] != "nu_scripts":
            upstream = f"nushell/nu_scripts ({entry['name']})"
        else:
            upstream = entry["id"]
        pid = entry["id"]
        o = outreach_cache.get(pid, {})
        switched = ""
        if pid in live and not live[pid].get("mirror"):
            switched = "yes"
        elif pid in live:
            switched = "mirror only"
        rows.append(
            "| "
            + " | ".join(
                [
                    upstream,
                    o.get("issue", ""),
                    o.get("opened", ""),
                    o.get("response", ""),
                    ("yes" if pid in live and not live[pid].get("mirror") else ""),
                    switched,
                ]
            )
            + " |"
        )

    new_section = "## Outreach tracker\n\n" + "\n".join(rows) + "\n\n"
    updated = text[:start] + new_section + text[end + 1 :]
    if updated == text:
        return False
    OUTREACH_DOC.write_text(updated, encoding="utf-8", newline="\n")
    return True


def sync() -> bool:
    if not STATE_PATH.exists():
        print(f"FAIL: missing {STATE_PATH}", file=sys.stderr)
        return False

    state = load_json(STATE_PATH)
    state_dirty = False

    index = load_json(INDEX_PATH) if INDEX_PATH.exists() else {"packages": []}
    live = registry_packages(index)

    outreach_cache: dict[str, dict[str, str]] = {}

    for section in ("mirror",):
        for entry in state.get(section, []):
            outreach = entry.get("outreach")
            if outreach:
                before = outreach.get("issue_url")
                status = outreach_status(outreach)
                outreach_cache[entry["id"]] = status
                if outreach.get("issue_url") != before:
                    state_dirty = True

    doc = render_intake_doc(state, live, index, outreach_cache)
    existing = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
    changed = False
    if existing != doc:
        OUT_PATH.write_text(doc, encoding="utf-8", newline="\n")
        changed = True

    if update_outreach_tracker(state, live, outreach_cache):
        changed = True

    if state_dirty:
        STATE_PATH.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        changed = True

    return changed


def compute_file_checksums(paths: list[Path]) -> dict[str, str]:
    checksums = {}
    for path in paths:
        if path.exists():
            checksums[str(path.relative_to(REPO_ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        else:
            checksums[str(path.relative_to(REPO_ROOT))] = ""
    return checksums


def files_changed_since_last_sync(paths: list[Path]) -> bool:
    if not CHECKSUM_CACHE.exists():
        return True

    try:
        cached = json.loads(CHECKSUM_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    current = compute_file_checksums(paths)
    return current != cached


def save_checksums(paths: list[Path]) -> None:
    checksums = compute_file_checksums(paths)
    CHECKSUM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHECKSUM_CACHE.write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def hook_main(hook_name: str) -> int:
    payload_raw = sys.stdin.read()
    payload: dict[str, Any] = {}
    if payload_raw.strip():
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {}

    if hook_name == "afterShellExecution":
        cmd = payload.get("command", "")
        triggers = ("gh ", "add-package.py", "build-mirror-zip.py", "sync-intake-candidates.py")
        if not any(t in cmd for t in triggers):
            print("{}")
            return 0

    if hook_name == "afterFileEdit":
        path = (payload.get("file_path") or payload.get("path") or "").replace("\\", "/")
        triggers = ("registry/index.json", "specs/", "intake-state.json")
        if path and not any(t in path for t in triggers):
            print("{}")
            return 0

    if hook_name == "stop":
        watched_files = [STATE_PATH, INDEX_PATH]
        if not files_changed_since_last_sync(watched_files):
            print("{}")
            return 0

    changed = sync()

    if hook_name == "stop":
        watched_files = [STATE_PATH, INDEX_PATH]
        save_checksums(watched_files)

    if hook_name == "stop" and changed:
        print(
            json.dumps(
                {
                    "followup_message": (
                        "Synced docs/intake-candidates.md (and outreach tracker) from "
                        "registry index + GitHub outreach state."
                    )
                }
            )
        )
    else:
        print("{}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hook",
        choices=("stop", "afterShellExecution", "afterFileEdit"),
        help="Cursor hook entry point (reads JSON from stdin)",
    )
    args = parser.parse_args()

    if args.hook:
        return hook_main(args.hook)

    changed = sync()
    print("OK: updated intake docs" if changed else "OK: intake docs already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
