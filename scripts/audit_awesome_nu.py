#!/usr/bin/env python3
"""Audit awesome-nu inventory against numan-registry and numan-plugins."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from url_safety import ensure_http_url, http_opener  # noqa: E402

AWESOME_NU_DEFAULT_URL = (
    "https://raw.githubusercontent.com/nushell/awesome-nu/main/README.md"
)


def normalize_name(raw_name: str) -> str:
    """Normalize a package or tool name for fuzzy comparison."""
    clean = re.sub(r"\s+by\s+.*$", "", raw_name, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s*\(.*\)$", "", clean).strip()
    clean = clean.lower().replace("-", "_")
    if clean.endswith(".nu"):
        clean = clean[:-3]
    return clean


def parse_awesome_nu_markdown(content: str) -> dict[str, list[dict[str, str]]]:
    """Parse sections and items from awesome-nu markdown content."""
    item_re = re.compile(r"^- \[([^\]]+)\]\(([^)]+)\):\s*(.*)$")
    sections: dict[str, list[dict[str, str]]] = {}
    curr_sec: str | None = None

    for line in content.splitlines():
        heading_match = re.match(r"^##\s+(.*)", line)
        if heading_match:
            curr_sec = heading_match.group(1).strip()
            sections[curr_sec] = []
        elif curr_sec and line.strip().startswith("- ["):
            item_match = item_re.match(line.strip())
            if item_match:
                name, url, desc = item_match.groups()
                sections[curr_sec].append(
                    {
                        "name": name.strip(),
                        "url": url.strip(),
                        "desc": desc.strip(),
                    }
                )

    return sections


def build_registry_indices(
    registry_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Build name-based and repo-based lookup indices for registry packages."""
    by_name: dict[str, Any] = {}
    by_repo: dict[str, list[Any]] = {}

    for pkg in registry_data.get("packages", []):
        name = pkg["id"]["name"].lower()
        owner = pkg["id"]["owner"].lower()
        repo = pkg.get("repo", "").lower().rstrip("/")

        by_name[name] = pkg
        by_name[f"{owner}/{name}"] = pkg

        if repo:
            by_repo.setdefault(repo, []).append(pkg)

    return by_name, by_repo


def extract_repo_slug(url: str) -> str | None:
    """Extract repository slug from GitHub, Codeberg, or GitLab URL, or return slug directly."""
    low = url.lower().rstrip("/")
    if "github.com/" in low:
        return low.split("github.com/")[-1].split("/tree/")[0].split("/blob/")[0]
    if "codeberg.org/" in low:
        return low.split("codeberg.org/")[-1].split("/src/")[0]
    if "gitlab.com/" in low:
        return low.split("gitlab.com/")[-1].split("/-/tree/")[0].split("/-/blob/")[0]
    if "/" in low and not low.startswith("http://") and not low.startswith("https://"):
        return low
    return None


def build_manifest_indices(
    manifest_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build name-based and repo-based lookup indices for manifest plugins."""
    by_name: dict[str, Any] = {}
    by_repo: dict[str, Any] = {}

    for entry in manifest_data.get("active", []):
        c_name = entry.get("name", "").lower().replace("-", "_")
        repo = entry.get("repo", "").lower().rstrip("/")
        if c_name:
            by_name[c_name] = entry
        if repo:
            by_repo[repo] = entry
            slug = extract_repo_slug(repo)
            if slug:
                by_repo[slug] = entry

    return by_name, by_repo


def build_backlog_indices(
    backlog_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build name-based and repo-based lookup indices for backlog plugins."""
    by_name: dict[str, Any] = {}
    by_repo: dict[str, Any] = {}

    for entry in backlog_data.get("plugins", []):
        if "name" in entry:
            by_name[normalize_name(entry["name"])] = entry
        if "repo" in entry:
            repo = entry["repo"].lower().rstrip("/")
            by_repo[repo] = entry
            slug = extract_repo_slug(repo)
            if slug:
                by_repo[slug] = entry

    return by_name, by_repo


def match_registry_package(
    clean_name: str,
    url: str,
    by_name: dict[str, Any],
    by_repo: dict[str, list[Any]],
) -> Any | None:
    """Match an awesome-nu item to a registry package, disambiguating multi-package repos."""
    if clean_name in by_name:
        return by_name[clean_name]

    url_clean = url.lower().rstrip("/")
    candidates: list[Any] = []

    if url_clean in by_repo:
        candidates.extend(by_repo[url_clean])

    repo_slug = extract_repo_slug(url)
    for r_url, pkgs in by_repo.items():
        if (repo_slug and repo_slug in r_url) or (r_url and r_url in url_clean):
            for p in pkgs:
                if p not in candidates:
                    candidates.append(p)

    for p in candidates:
        if clean_name == normalize_name(p["id"]["name"]):
            return p

    for p in candidates:
        p_norm = normalize_name(p["id"]["name"])
        if clean_name in p_norm or p_norm in clean_name:
            return p

    if len(candidates) == 1:
        return candidates[0]

    return None


def build_intake_indices(
    state_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Build name and repo lookups for intake-state candidates (all lanes)."""
    by_name: dict[str, Any] = {}
    by_repo: dict[str, list[Any]] = {}

    for lane in ("ready", "mirror", "blocked"):
        for entry in state_data.get(lane, []):
            if entry.get("name"):
                by_name[normalize_name(entry["name"])] = entry
            if entry.get("id"):
                by_name[normalize_name(entry["id"])] = entry
            repo = entry.get("repo", "")
            slug = extract_repo_slug(repo) if repo else None
            if slug:
                by_repo.setdefault(slug, []).append(entry)

    return by_name, by_repo


def build_non_plugin_backlog_indices(
    backlog_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Build name and repo lookups for non-plugin backlog candidates."""
    by_name: dict[str, Any] = {}
    by_repo: dict[str, list[Any]] = {}

    for entry in backlog_data.get("candidates", []):
        if entry.get("name"):
            by_name[normalize_name(entry["name"])] = entry
        repo = entry.get("repo", "")
        slug = extract_repo_slug(repo) if repo else None
        if slug:
            by_repo.setdefault(slug, []).append(entry)

    return by_name, by_repo


def _match_named_or_unique_repo(
    clean_name: str,
    repo_slug: str | None,
    by_name: dict[str, Any],
    by_repo: dict[str, list[Any]],
) -> Any | None:
    """Match by name, or by repo only when the repo has a single entry.

    A shared repo (for example nushell/nu_scripts) hosts many distinct
    candidates, so for multi-entry repos the name must match one of the
    entries; a bare repo match would misattribute the rest.
    """
    if clean_name in by_name:
        return by_name[clean_name]
    if repo_slug and repo_slug in by_repo:
        entries = by_repo[repo_slug]
        for entry in entries:
            if normalize_name(entry.get("name", "")) == clean_name:
                return entry
        if len(entries) == 1:
            return entries[0]
    return None


def _url_subpath(url: str) -> str | None:
    """Return the path below the branch in a /blob/ or /tree/ URL, if any."""
    match = re.search(r"/(?:blob|tree)/[^/]+/(.+)$", url.lower().rstrip("/"))
    return match.group(1) if match else None


def _registry_match_ok(item: dict[str, str], pkg: dict[str, Any]) -> bool:
    """Guard a registry match against shared-repo misattribution.

    When an item URL points into a subdirectory of a shared repo (a /blob/
    or /tree/ path), the matched package must live at a compatible subpath.
    Without this, the single-candidate fallback in match_registry_package
    attributes every file of a shared repo to its one packaged member.
    """
    item_sub = _url_subpath(item["url"])
    if item_sub is None:
        return True
    pkg_sub = _url_subpath(pkg.get("repo", ""))
    if pkg_sub is None:
        return False
    return (
        item_sub == pkg_sub
        or item_sub.startswith(pkg_sub + "/")
        or pkg_sub.startswith(item_sub + "/")
    )


def audit_non_plugins(
    items: list[dict[str, str]],
    reg_by_name: dict[str, Any],
    reg_by_repo: dict[str, list[Any]],
    prov_by_name: dict[str, Any],
    prov_by_repo: dict[str, list[Any]],
    intake_by_name: dict[str, Any],
    intake_by_repo: dict[str, list[Any]],
    np_by_name: dict[str, Any],
    np_by_repo: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    """Audit a non-plugin awesome-nu section against registry and backlog."""
    results: list[dict[str, Any]] = []

    for item in items:
        c_name = normalize_name(item["name"])
        url = item["url"]
        repo_slug = extract_repo_slug(url)

        match_reg = match_registry_package(c_name, url, reg_by_name, reg_by_repo)
        if match_reg and not _registry_match_ok(item, match_reg):
            match_reg = None
        if match_reg:
            results.append({"item": item, "status": "IN_REGISTRY", "match": match_reg})
            continue

        match_prov = match_registry_package(c_name, url, prov_by_name, prov_by_repo)
        if match_prov and not _registry_match_ok(item, match_prov):
            match_prov = None
        if match_prov:
            results.append({"item": item, "status": "IN_PROVISIONAL", "match": match_prov})
            continue

        match_intake = _match_named_or_unique_repo(
            c_name, repo_slug, intake_by_name, intake_by_repo
        )
        if match_intake:
            results.append({"item": item, "status": "IN_INTAKE", "match": match_intake})
            continue

        match_np = _match_named_or_unique_repo(c_name, repo_slug, np_by_name, np_by_repo)
        if match_np:
            results.append({"item": item, "status": "IN_BACKLOG", "match": match_np})
            continue

        results.append({"item": item, "status": "UNTRACKED", "match": None})

    return results


def format_section_audit(title: str, audit_results: list[dict[str, Any]]) -> str:
    """Format non-plugin audit results into report string."""
    in_reg = [r for r in audit_results if r["status"] == "IN_REGISTRY"]
    in_prov = [r for r in audit_results if r["status"] == "IN_PROVISIONAL"]
    in_intake = [r for r in audit_results if r["status"] == "IN_INTAKE"]
    in_bl = [r for r in audit_results if r["status"] == "IN_BACKLOG"]
    untracked = [r for r in audit_results if r["status"] == "UNTRACKED"]

    lines = [
        "",
        "=================================================================",
        f"{title.upper()} AUDIT",
        "=================================================================",
        f"Awesome-Nu {title} Total: {len(audit_results)}",
        f"  [+] In Numan Registry: {len(in_reg)}",
        f"  [~] In Provisional Catalog: {len(in_prov)}",
        f"  [~] In Intake State: {len(in_intake)}",
        f"  [.] In Non-Plugin Backlog: {len(in_bl)}",
        f"  [-] Untracked / Missing: {len(untracked)}",
        "",
        "[-] UNTRACKED CANDIDATES:",
    ]
    for r in untracked:
        lines.append(f"  * {r['item']['name']} ({r['item']['url']}) - {r['item']['desc']}")

    return "\n".join(lines)


def audit_plugins(
    items: list[dict[str, str]],
    reg_by_name: dict[str, Any],
    reg_by_repo: dict[str, list[Any]],
    man_by_name: dict[str, Any],
    man_by_repo: dict[str, Any],
    backlog_by_name: dict[str, Any],
    backlog_by_repo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Audit plugins from awesome-nu against catalog and backlog."""
    results: list[dict[str, Any]] = []

    for item in items:
        raw_name = item["name"]
        c_name = normalize_name(raw_name)
        url = item["url"]
        repo_slug = extract_repo_slug(url)

        match_reg = match_registry_package(c_name, url, reg_by_name, reg_by_repo)
        if match_reg:
            results.append({"item": item, "status": "IN_REGISTRY", "match": match_reg})
            continue

        match_man = man_by_name.get(c_name)
        if not match_man and repo_slug:
            match_man = man_by_repo.get(repo_slug)
        if match_man:
            results.append({"item": item, "status": "IN_MANIFEST", "match": match_man})
            continue

        match_bl = backlog_by_name.get(c_name)
        if not match_bl and repo_slug:
            match_bl = backlog_by_repo.get(repo_slug)
        if match_bl:
            results.append({"item": item, "status": "IN_BACKLOG", "match": match_bl})
            continue

        results.append({"item": item, "status": "UNTRACKED", "match": None})

    return results


def format_plugin_audit(audit_results: list[dict[str, Any]]) -> str:
    """Format plugin audit results into report string."""
    in_reg = [r for r in audit_results if r["status"] == "IN_REGISTRY"]
    in_man = [r for r in audit_results if r["status"] == "IN_MANIFEST"]
    in_bl = [r for r in audit_results if r["status"] == "IN_BACKLOG"]
    untracked = [r for r in audit_results if r["status"] == "UNTRACKED"]

    lines = [
        "=================================================================",
        "PLUGINS AUDIT",
        "=================================================================",
        f"Awesome-Nu Plugins Total: {len(audit_results)}",
        f"  [+] In Numan Registry: {len(in_reg)}",
        f"  [~] In numan-plugins CI Manifest: {len(in_man)}",
        f"  [.] In numan-plugins Backlog: {len(in_bl)}",
        f"  [-] Untracked / Missing: {len(untracked)}",
        "",
        "[+] IN REGISTRY:",
    ]

    for r in sorted(in_reg, key=lambda x: x["match"]["id"]["name"]):
        pkg = r["match"]
        versions = [f"{v['version']} (Nu: {v.get('nu_version', '*')})" for v in pkg.get("versions", [])]
        lines.append(f"  * {pkg['id']['owner']}/{pkg['id']['name']} (awesome-nu: '{r['item']['name']}')")
        lines.append(f"      Versions: {', '.join(versions)}")

    lines.extend(["", "[-] UNTRACKED CANDIDATES:"])
    for r in untracked:
        lines.append(f"  * {r['item']['name']} ({r['item']['url']}) - {r['item']['desc']}")

    return "\n".join(lines)


def fetch_readme(path: Path | None, url: str = AWESOME_NU_DEFAULT_URL) -> str:
    """Read awesome-nu README from local path or fetch via HTTP."""
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"README file not found: {path}")
        return path.read_text(encoding="utf-8")

    ensure_http_url(url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "numan-catalog-audit/1.0"},
    )
    with http_opener().open(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/numan-cli/numan-plugins/main/manifest.json"
)
DEFAULT_BACKLOG_URL = (
    "https://raw.githubusercontent.com/numan-cli/numan-plugins/main/docs/backlog.json"
)


def load_json_file(
    path: Path | None,
    fallback_url: str | None = None,
    dataset_name: str = "dataset",
) -> dict[str, Any]:
    """Load JSON from local path or fallback URL; fail fast on error."""
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    if fallback_url:
        try:
            content = fetch_readme(None, url=fallback_url)
            return json.loads(content)
        except Exception as err:
            raise RuntimeError(
                f"Failed to load {dataset_name} from local path {path} or fallback URL {fallback_url}: {err}"
            ) from err

    if path:
        raise FileNotFoundError(f"{dataset_name} not found at {path}")

    raise ValueError(f"No path or fallback URL provided for {dataset_name}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for audit_awesome_nu."""
    parser = argparse.ArgumentParser(description="Audit awesome-nu catalog coverage")
    parser.add_argument("--readme", type=Path, default=None, help="Path to awesome-nu README.md")
    parser.add_argument("--index", type=Path, default=Path(__file__).resolve().parent.parent / "registry" / "index.json")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parent.parent.parent / "numan-plugins" / "manifest.json")
    parser.add_argument("--backlog", type=Path, default=Path(__file__).resolve().parent.parent.parent / "numan-plugins" / "docs" / "backlog.json")
    parser.add_argument("--provisional", type=Path, default=Path(__file__).resolve().parent.parent / "registry" / "provisional.json")
    parser.add_argument("--intake-state", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "intake-state.json")
    parser.add_argument("--non-plugin-backlog", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "non-plugin-backlog.json")
    args = parser.parse_args(argv)

    readme_content = fetch_readme(args.readme)
    sections = parse_awesome_nu_markdown(readme_content)

    reg_data = load_json_file(args.index, dataset_name="registry index")
    man_data = load_json_file(
        args.manifest,
        fallback_url=DEFAULT_MANIFEST_URL,
        dataset_name="numan-plugins manifest",
    )
    bl_data = load_json_file(
        args.backlog,
        fallback_url=DEFAULT_BACKLOG_URL,
        dataset_name="numan-plugins backlog",
    )

    reg_by_name, reg_by_repo = build_registry_indices(reg_data)
    man_by_name, man_by_repo = build_manifest_indices(man_data)
    bl_by_name, bl_by_repo = build_backlog_indices(bl_data)

    plugin_results = audit_plugins(
        sections.get("Plugins", []),
        reg_by_name,
        reg_by_repo,
        man_by_name,
        man_by_repo,
        bl_by_name,
        bl_by_repo,
    )

    report = format_plugin_audit(plugin_results)
    print(report)

    prov_data = load_json_file(args.provisional, dataset_name="provisional catalog")
    intake_data = load_json_file(args.intake_state, dataset_name="intake state")
    try:
        np_data = load_json_file(
            args.non_plugin_backlog, dataset_name="non-plugin backlog"
        )
    except FileNotFoundError:
        # The backlog file is optional: without it, everything not tracked
        # elsewhere simply reports as untracked.
        np_data = {"candidates": []}

    prov_by_name, prov_by_repo = build_registry_indices(prov_data)
    intake_by_name, intake_by_repo = build_intake_indices(intake_data)
    np_by_name, np_by_repo = build_non_plugin_backlog_indices(np_data)

    for section in ("Scripts", "Custom Completions"):
        section_results = audit_non_plugins(
            sections.get(section, []),
            reg_by_name,
            reg_by_repo,
            prov_by_name,
            prov_by_repo,
            intake_by_name,
            intake_by_repo,
            np_by_name,
            np_by_repo,
        )
        print(format_section_audit(section, section_results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
