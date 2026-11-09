#!/usr/bin/env python3.12
"""Synthesize a candidate intake spec for an already-indexed upstream release hit.

Inherits proven package metadata (description, tags, activation, entry,
executable_path, dependencies) from the latest indexed version in
registry/index.json and maps the new upstream release's assets or invokes
intake-archive.py for non-binary packages without uploaded release archives.

Usage:
  python scripts/prepare_upstream_candidate.py \\
    --index registry/index.json \\
    --hits hits.json \\
    --package owner/name \\
    --out-spec specs/owner-name-version.json
"""

from __future__ import annotations

import argparse
import base64
import copy
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from archive_formats import SUPPORTED_ARCHIVE_SUFFIXES
from gen_candidate import _match_target
from url_safety import ensure_http_url, github_repo_key, http_opener
from watch_indexed import latest_entry, split_scoped

REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"
GITHUB_API = "https://api.github.com"
USER_AGENT = "numan-registry-prepare-upstream/1.0"


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _clean_version(tag: str) -> str:
    """Strip leading v/V and trailing build metadata (+...) from a tag."""
    ver = str(tag).strip()
    if ver.startswith(("v", "V")) and len(ver) > 1 and ver[1].isdigit():
        ver = ver[1:]
    return ver.split("+")[0]


def _substitute_version(value: str, old_version: str, new_version: str) -> str:
    """Replace old_version (and v-prefixed old_version) with new_version in a path/root."""
    if not old_version or old_version == new_version:
        return value
    updated = value.replace(f"v{old_version}", f"v{new_version}")
    return updated.replace(old_version, new_version)


SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def _extract_nu_band_from_toml(content: str) -> str | None:
    """Extract a `>=M.m.0 <M.(m+1).0` Nu band from Cargo.toml text."""
    for dep in ("nu-plugin", "nu-protocol"):
        for match in re.finditer(
            rf'{dep}\s*=\s*(?:\{{[^}}]*version\s*=\s*)?["\']([^"\']+)["\']',
            content,
        ):
            ver_match = re.search(r"(\d+)\.(\d+)", match.group(1))
            if ver_match:
                major = int(ver_match.group(1))
                minor = int(ver_match.group(2))
                return f">={major}.{minor}.0 <{major}.{minor + 1}.0"
    return None


def _fetch_repo_file_text(owner_repo: str, path: str, quoted_ref: str) -> str | None:
    """Fetch a UTF-8 file from GitHub Contents API at `quoted_ref`, or None."""
    url = f"{GITHUB_API}/repos/{owner_repo}/contents/{path}?ref={quoted_ref}"
    ensure_http_url(url)
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with http_opener().open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or "content" not in data:
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_cargo_nu_constraint(
    repo_url: str, ref: str, cargo_name: str | None = None
) -> str | None:
    """Inspect upstream Cargo.toml at `ref` to derive a `>=0.X.0 <0.(X+1).0` Nu band."""
    owner_repo = github_repo_key(repo_url)
    if not owner_repo:
        return None
    quoted_ref = urllib.parse.quote(ref, safe="")
    paths = ["Cargo.toml"]
    if cargo_name:
        paths.extend([f"{cargo_name}/Cargo.toml", f"crates/{cargo_name}/Cargo.toml"])
    for path in paths:
        content = _fetch_repo_file_text(owner_repo, path, quoted_ref)
        if content:
            band = _extract_nu_band_from_toml(content)
            if band:
                return band
    return None


def resolve_tag_commit_sha(repo_url: str, ref: str) -> str | None:
    """Resolve `ref` on `repo_url` to a lowercase 40-char commit SHA via GitHub API."""
    owner_repo = github_repo_key(repo_url)
    if not owner_repo:
        return None
    quoted_ref = urllib.parse.quote(ref, safe="")
    url = f"{GITHUB_API}/repos/{owner_repo}/commits/{quoted_ref}"
    ensure_http_url(url)
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with http_opener().open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    sha = str(data.get("sha", "")).strip().lower()
    return sha if SHA40_RE.fullmatch(sha) else None


def _is_supported_archive_url(url: str) -> bool:
    lower = url.lower()
    return any(lower.endswith(suffix) for suffix in SUPPORTED_ARCHIVE_SUFFIXES)


def _uses_hosted_archive(prev_url: str) -> bool:
    """True when the previous version used a numan-hosted archive or mirror release."""
    return (
        "/numan-registry/releases/download/archive-" in prev_url
        or "/numan-registry/releases/download/mirror-" in prev_url
        or "/numan-plugins/releases/download/archive-" in prev_url
    )


def _load_intake_archive():
    spec = importlib.util.spec_from_file_location(
        "intake_archive", SCRIPT_DIR / "intake-archive.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load scripts/intake-archive.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_direct_archive_spec(
    package: dict,
    latest: dict,
    old_version: str,
    new_version: str,
    nu_version: str,
    chosen_url: str,
) -> dict:
    """Build a direct archive spec from an uploaded upstream release asset."""
    pid = package.get("id") or {}
    prev_artifact = latest.get("artifact") or {}
    artifact: dict = {
        "kind": "archive",
        "url": chosen_url,
        "entry": str(prev_artifact.get("entry", "mod.nu")),
    }
    if "archive_root" in prev_artifact:
        artifact["archive_root"] = _substitute_version(
            str(prev_artifact["archive_root"]), old_version, new_version
        )
    if "include" in prev_artifact:
        artifact["include"] = copy.deepcopy(prev_artifact["include"])

    ptype = str(package.get("type", ""))
    spec: dict = {
        "owner": str(pid.get("owner", "")),
        "name": str(pid.get("name", "")),
        "description": str(package.get("description", "")),
        "repo": str(package.get("repo", "")),
        "type": ptype,
        "tags": list(package.get("tags") or [ptype]),
        "version": new_version,
        "nu_version": nu_version,
        "artifact": artifact,
    }
    if "activation" in latest:
        spec["activation"] = copy.deepcopy(latest["activation"])
    if "dependencies" in latest:
        spec["dependencies"] = copy.deepcopy(latest["dependencies"])
    return spec


def _run_intake_archive_fallback(
    package: dict,
    latest: dict,
    upstream_tag: str,
    new_version: str,
    nu_version: str,
    release_repo: str,
    manifest_archives: Path | None,
) -> dict:
    """Invoke intake-archive.py to build and upload a deterministic .tar.gz archive."""
    import tempfile

    pid = package.get("id") or {}
    owner = str(pid.get("owner", ""))
    name = str(pid.get("name", ""))
    ptype = str(package.get("type", ""))
    prev_artifact = latest.get("artifact") or {}
    entry = str(prev_artifact.get("entry", "mod.nu"))
    tags = list(package.get("tags") or [ptype])
    intake_mod = _load_intake_archive()

    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / f"spec-{owner}-{name}.json"
        argv = [
            "--git-url", str(package.get("repo", "")),
            "--ref", upstream_tag,
            "--version", new_version,
            "--entry", entry,
            "--owner", owner,
            "--name", name,
            "--type", ptype,
            "--description", str(package.get("description", "")),
            "--tags", json.dumps(tags),
            "--nu-version", nu_version,
            "--release-repo", release_repo,
            "--out", str(out_file),
        ]
        if manifest_archives is not None:
            argv.extend(["--manifest-archives", str(manifest_archives)])
        activation = latest.get("activation")
        if isinstance(activation, dict) and activation.get("kind") == "nu-module":
            argv.extend([
                "--activation-kind", "nu-module",
                "--activation-import", str(activation.get("import", "all")),
                "--provisional",
                "--deferral-reason", "pending CI dual-OS lifecycle proof",
            ])
        rc = intake_mod.main(argv)
        if rc != 0 or not out_file.is_file():
            raise RuntimeError(f"intake-archive.py failed for {owner}/{name}@{upstream_tag}")
        spec = json.loads(out_file.read_text(encoding="utf-8"))

    if "activation" in latest:
        spec["activation"] = copy.deepcopy(latest["activation"])
    if "dependencies" in latest:
        spec["dependencies"] = copy.deepcopy(latest["dependencies"])
    if "include" in prev_artifact and isinstance(spec.get("artifact"), dict):
        spec["artifact"]["include"] = copy.deepcopy(prev_artifact["include"])
    return spec


def _prepare_archive_spec(
    package: dict,
    latest: dict,
    hit: dict,
    *,
    release_repo: str = "numan-cli/numan-registry",
    manifest_archives: Path | None = None,
) -> dict:
    """Build a candidate spec for a module, script, or completion update."""
    old_version = str(latest.get("version", ""))
    upstream_tag = str(hit.get("upstream", ""))
    new_version = _clean_version(upstream_tag)
    nu_version = str(latest.get("nu_version", "*"))
    prev_url = str((latest.get("artifact") or {}).get("url", ""))
    assets = [
        a for a in (hit.get("assets") or [])
        if isinstance(a, dict) and _is_supported_archive_url(str(a.get("url", "")))
    ]
    if assets and not _uses_hosted_archive(prev_url):
        return _build_direct_archive_spec(
            package, latest, old_version, new_version, nu_version, str(assets[0]["url"])
        )
    return _run_intake_archive_fallback(
        package, latest, upstream_tag, new_version, nu_version, release_repo, manifest_archives
    )


def _resolve_plugin_source(
    package: dict, latest: dict, hit: dict, upstream_tag: str
) -> dict | None:
    """Recompute `source` provenance when `latest` carries `source` or is CI-built."""
    prev_source = latest.get("source")
    psource = str(hit.get("plugin_source", ""))
    needs_source = isinstance(prev_source, dict) or psource.startswith("ci-built") or (
        "ci-built" in (package.get("tags") or [])
    )
    if not needs_source:
        return None
    pid = package.get("id") or {}
    name = str(pid.get("name", ""))
    git_url = str(
        (prev_source.get("git") if isinstance(prev_source, dict) else None)
        or package.get("repo", "")
    )
    cargo_name = str(
        (prev_source.get("cargo_name") if isinstance(prev_source, dict) else None)
        or name
    )
    rev = resolve_tag_commit_sha(git_url, upstream_tag)
    if not rev:
        raise ValueError(
            f"{pid.get('owner', '')}/{name}@{upstream_tag}: could not resolve 40-char commit SHA for source provenance"
        )
    out: dict = {
        "git": git_url,
        "rev": rev,
        "cargo_name": cargo_name,
    }
    if isinstance(prev_source, dict) and "upstream" in prev_source:
        out["upstream"] = prev_source["upstream"]
    return out


def _prepare_plugin_spec(package: dict, latest: dict, hit: dict) -> dict:
    """Build a candidate spec for a binary plugin update with target parity verification."""
    pid = package.get("id") or {}
    owner = str(pid.get("owner", ""))
    name = str(pid.get("name", ""))
    repo = str(package.get("repo", ""))
    description = str(package.get("description", ""))
    tags = list(package.get("tags") or ["plugin"])

    old_version = str(latest.get("version", ""))
    upstream_tag = str(hit.get("upstream", ""))
    new_version = _clean_version(upstream_tag)

    prev_targets = ((latest.get("artifact") or {}).get("targets") or {})
    if not isinstance(prev_targets, dict) or not prev_targets:
        raise ValueError(f"{owner}/{name}: latest entry has no binary targets")

    assets = hit.get("assets") or []
    asset_by_triple: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name", ""))
        asset_url = str(asset.get("url", ""))
        if not asset_url or not _is_supported_archive_url(asset_url):
            continue
        triple = _match_target(asset_name)
        if triple and triple not in asset_by_triple:
            asset_by_triple[triple] = asset_url

    missing = sorted(set(prev_targets.keys()) - set(asset_by_triple.keys()))
    if missing:
        raise ValueError(
            f"{owner}/{name}@{upstream_tag}: missing target asset(s) for: {', '.join(missing)}"
        )

    new_targets: dict[str, dict] = {}
    for triple, prev_target in prev_targets.items():
        prev_exe = str(prev_target.get("executable_path", name))
        new_targets[triple] = {
            "url": asset_by_triple[triple],
            "executable_path": _substitute_version(prev_exe, old_version, new_version),
        }

    prev_source = latest.get("source")
    cargo_name = (
        str(prev_source.get("cargo_name"))
        if isinstance(prev_source, dict) and prev_source.get("cargo_name")
        else name
    )
    inferred_nu = fetch_cargo_nu_constraint(repo, upstream_tag, cargo_name=cargo_name)
    if not inferred_nu:
        raise ValueError(
            f"{owner}/{name}@{upstream_tag}: could not infer Cargo Nu constraint from upstream Cargo.toml"
        )

    source_block = _resolve_plugin_source(package, latest, hit, upstream_tag)

    spec: dict = {
        "owner": owner,
        "name": name,
        "description": description,
        "repo": repo,
        "type": "plugin",
        "tags": tags,
        "version": new_version,
        "nu_version": inferred_nu,
        "artifact": {
            "kind": "binary",
            "targets": new_targets,
        },
    }
    if source_block is not None:
        spec["source"] = source_block
    if "dependencies" in latest:
        spec["dependencies"] = copy.deepcopy(latest["dependencies"])
    return spec


def prepare_candidate(
    index: dict,
    hits: dict,
    package_scoped: str,
    *,
    release_repo: str = "numan-cli/numan-registry",
    manifest_archives: Path | None = None,
) -> dict:
    """Find `package_scoped` in `index` and `hits['upstream_updates']` and return its spec."""
    by_pkg = {
        split_scoped(p): p
        for p in index.get("packages", [])
        if isinstance(p, dict)
    }
    if package_scoped not in by_pkg:
        raise KeyError(f"package not found in index: {package_scoped}")
    package = by_pkg[package_scoped]
    latest = latest_entry(package)
    if latest is None:
        raise ValueError(f"package has no versions in index: {package_scoped}")

    hit = next(
        (
            h for h in hits.get("upstream_updates", [])
            if isinstance(h, dict) and h.get("package") == package_scoped
        ),
        None,
    )
    if hit is None:
        raise KeyError(f"package not found in upstream_updates hits: {package_scoped}")

    ptype = str(package.get("type", ""))
    if ptype == "plugin":
        return _prepare_plugin_spec(package, latest, hit)
    if ptype in ("module", "script", "completion"):
        return _prepare_archive_spec(
            package,
            latest,
            hit,
            release_repo=release_repo,
            manifest_archives=manifest_archives,
        )
    raise ValueError(f"unsupported package type {ptype!r} for {package_scoped}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--hits", type=Path, required=True, help="Path to hits.json from watch_indexed.py")
    parser.add_argument("--package", required=True, help="Scoped package ID (owner/name)")
    parser.add_argument("--release-repo", default="numan-cli/numan-registry")
    parser.add_argument("--out-spec", type=Path, required=True, help="Output path for generated spec JSON")
    args = parser.parse_args(argv)

    try:
        index = json.loads(args.index.read_text(encoding="utf-8"))
        hits = json.loads(args.hits.read_text(encoding="utf-8"))
        spec = prepare_candidate(
            index,
            hits,
            args.package,
            release_repo=args.release_repo,
        )
        args.out_spec.parent.mkdir(parents=True, exist_ok=True)
        args.out_spec.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"Prepared upstream candidate spec: {args.out_spec}", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"error preparing candidate for {args.package}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
