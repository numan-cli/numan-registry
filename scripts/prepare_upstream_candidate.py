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
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
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
CLEAN_VER_RE = re.compile(r"^[vV](?=\d)")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class CandidateContext:
    """Immutable context for preparing a single upstream candidate spec."""

    package: dict
    latest: dict
    hit: dict
    release_repo: str = "numan-cli/numan-registry"

    @property
    def owner(self) -> str:
        return str((self.package.get("id") or {}).get("owner", ""))

    @property
    def name(self) -> str:
        return str((self.package.get("id") or {}).get("name", ""))

    @property
    def repo(self) -> str:
        return str(self.package.get("repo", ""))

    @property
    def ptype(self) -> str:
        return str(self.package.get("type", ""))

    @property
    def old_version(self) -> str:
        return str(self.latest.get("version", ""))

    @property
    def upstream_tag(self) -> str:
        return str(self.hit.get("upstream", ""))

    @property
    def new_version(self) -> str:
        return _clean_version(self.upstream_tag)


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _clean_version(tag: str) -> str:
    """Strip leading v/V (when followed by a digit) and trailing build metadata (+...)."""
    ver = CLEAN_VER_RE.sub("", str(tag).strip())
    return ver.split("+")[0]


def _substitute_version(value: str, old_version: str, new_version: str) -> str:
    """Replace old_version (and v-prefixed old_version) with new_version in a path/root."""
    if not old_version or old_version == new_version:
        return value
    updated = value.replace(f"v{old_version}", f"v{new_version}")
    return updated.replace(old_version, new_version)


def _extract_nu_band_from_toml(content: str) -> str | None:
    """Extract a `>=M.m.0 <M.(m+1).0` Nu band from Cargo.toml text."""
    for dep in ("nu-plugin", "nu-protocol"):
        pattern = rf'{dep}\s*=\s*(?:\{{[^}}]*version\s*=\s*)?["\']([^"\']+)["\']'
        for match in re.finditer(pattern, content):
            ver_match = re.search(r"(\d+)\.(\d+)", match.group(1))
            if ver_match:
                major = int(ver_match.group(1))
                minor = int(ver_match.group(2))
                return f">={major}.{minor}.0 <{major}.{minor + 1}.0"
    return None


def _decode_github_content(data: object) -> str | None:
    """Decode base64 file content from a GitHub Contents API response dict."""
    if not isinstance(data, dict):
        return None
    encoded = data.get("content")
    if not isinstance(encoded, str):
        return None
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
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
    return _decode_github_content(data)


def _cargo_toml_paths(cargo_name: str | None) -> list[str]:
    """Candidate Cargo.toml paths in an upstream repository."""
    if not cargo_name:
        return ["Cargo.toml"]
    return ["Cargo.toml", f"{cargo_name}/Cargo.toml", f"crates/{cargo_name}/Cargo.toml"]


def fetch_cargo_nu_constraint(
    repo_url: str, ref: str, cargo_name: str | None = None
) -> str | None:
    """Inspect upstream Cargo.toml at `ref` to derive a `>=0.X.0 <0.(X+1).0` Nu band."""
    owner_repo = github_repo_key(repo_url)
    if not owner_repo:
        return None
    quoted_ref = urllib.parse.quote(ref, safe="")
    for path in _cargo_toml_paths(cargo_name):
        content = _fetch_repo_file_text(owner_repo, path, quoted_ref)
        band = _extract_nu_band_from_toml(content) if content else None
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
    markers = (
        "/numan-registry/releases/download/archive-",
        "/numan-registry/releases/download/mirror-",
        "/numan-plugins/releases/download/archive-",
    )
    return any(marker in prev_url for marker in markers)


def _load_intake_archive():
    spec = importlib.util.spec_from_file_location(
        "intake_archive", SCRIPT_DIR / "intake-archive.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load scripts/intake-archive.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_optional_latest_fields(latest: dict, spec: dict) -> None:
    """Copy activation and dependencies from `latest` into `spec` when present."""
    if "activation" in latest:
        spec["activation"] = copy.deepcopy(latest["activation"])
    if "dependencies" in latest:
        spec["dependencies"] = copy.deepcopy(latest["dependencies"])


def _build_direct_archive_spec(ctx: CandidateContext, chosen_url: str) -> dict:
    """Build a direct archive spec from an uploaded upstream release asset."""
    prev_artifact = ctx.latest.get("artifact") or {}
    artifact: dict = {
        "kind": "archive",
        "url": chosen_url,
        "entry": str(prev_artifact.get("entry", "mod.nu")),
    }
    if "archive_root" in prev_artifact:
        artifact["archive_root"] = _substitute_version(
            str(prev_artifact["archive_root"]), ctx.old_version, ctx.new_version
        )
    if "include" in prev_artifact:
        artifact["include"] = copy.deepcopy(prev_artifact["include"])

    spec: dict = {
        "owner": ctx.owner,
        "name": ctx.name,
        "description": str(ctx.package.get("description", "")),
        "repo": ctx.repo,
        "type": ctx.ptype,
        "tags": list(ctx.package.get("tags") or [ctx.ptype]),
        "version": ctx.new_version,
        "nu_version": str(ctx.latest.get("nu_version", "*")),
        "artifact": artifact,
    }
    _copy_optional_latest_fields(ctx.latest, spec)
    return spec


def _build_intake_archive_argv(ctx: CandidateContext, out_file: Path) -> list[str]:
    """Build CLI argv for intake-archive.py."""
    prev_artifact = ctx.latest.get("artifact") or {}
    entry = str(prev_artifact.get("entry", "mod.nu"))
    tags = list(ctx.package.get("tags") or [ctx.ptype])
    argv = [
        "--git-url", ctx.repo,
        "--ref", ctx.upstream_tag,
        "--version", ctx.new_version,
        "--entry", entry,
        "--owner", ctx.owner,
        "--name", ctx.name,
        "--type", ctx.ptype,
        "--description", str(ctx.package.get("description", "")),
        "--tags", json.dumps(tags),
        "--nu-version", str(ctx.latest.get("nu_version", "*")),
        "--release-repo", ctx.release_repo,
        "--out", str(out_file),
    ]
    activation = ctx.latest.get("activation")
    if isinstance(activation, dict) and activation.get("kind") == "nu-module":
        argv.extend([
            "--activation-kind", "nu-module",
            "--activation-import", str(activation.get("import", "all")),
            "--provisional",
            "--deferral-reason", "pending CI dual-OS lifecycle proof",
        ])
    return argv


def _run_intake_archive_fallback(ctx: CandidateContext) -> dict:
    """Invoke intake-archive.py to build and upload a deterministic .tar.gz archive."""
    intake_mod = _load_intake_archive()
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / f"spec-{ctx.owner}-{ctx.name}.json"
        argv = _build_intake_archive_argv(ctx, out_file)
        rc = intake_mod.main(argv)
        if rc != 0 or not out_file.is_file():
            raise RuntimeError(
                f"intake-archive.py failed for {ctx.owner}/{ctx.name}@{ctx.upstream_tag}"
            )
        spec = json.loads(out_file.read_text(encoding="utf-8"))

    _copy_optional_latest_fields(ctx.latest, spec)
    prev_artifact = ctx.latest.get("artifact") or {}
    if "include" in prev_artifact and isinstance(spec.get("artifact"), dict):
        spec["artifact"]["include"] = copy.deepcopy(prev_artifact["include"])
    return spec


def _supported_asset_urls(hit: dict) -> list[str]:
    """Return supported archive URLs from `hit['assets']`."""
    urls: list[str] = []
    for asset in hit.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        url = str(asset.get("url", ""))
        if _is_supported_archive_url(url):
            urls.append(url)
    return urls


def _prepare_archive_spec(ctx: CandidateContext) -> dict:
    """Build a candidate spec for a module, script, or completion update."""
    prev_url = str((ctx.latest.get("artifact") or {}).get("url", ""))
    asset_urls = _supported_asset_urls(ctx.hit)
    if asset_urls and not _uses_hosted_archive(prev_url):
        return _build_direct_archive_spec(ctx, asset_urls[0])
    return _run_intake_archive_fallback(ctx)


def _needs_plugin_source(ctx: CandidateContext) -> bool:
    """Return True when the plugin spec must include a `source` provenance block."""
    if isinstance(ctx.latest.get("source"), dict):
        return True
    if str(ctx.hit.get("plugin_source", "")).startswith("ci-built"):
        return True
    return "ci-built" in (ctx.package.get("tags") or [])


def _plugin_cargo_name(ctx: CandidateContext) -> str:
    """Return the Cargo package name for a plugin."""
    prev_source = ctx.latest.get("source")
    if isinstance(prev_source, dict) and prev_source.get("cargo_name"):
        return str(prev_source["cargo_name"])
    return ctx.name


def _resolve_plugin_source(ctx: CandidateContext) -> dict | None:
    """Recompute `source` provenance when `latest` carries `source` or is CI-built."""
    if not _needs_plugin_source(ctx):
        return None
    prev_source = ctx.latest.get("source")
    prev_git = prev_source.get("git") if isinstance(prev_source, dict) else None
    git_url = str(prev_git or ctx.repo)
    rev = resolve_tag_commit_sha(git_url, ctx.upstream_tag)
    if not rev:
        raise ValueError(
            f"{ctx.owner}/{ctx.name}@{ctx.upstream_tag}: could not resolve 40-char commit SHA for source provenance"
        )
    out: dict = {
        "git": git_url,
        "rev": rev,
        "cargo_name": _plugin_cargo_name(ctx),
    }
    if isinstance(prev_source, dict) and "upstream" in prev_source:
        out["upstream"] = prev_source["upstream"]
    return out


def _map_assets_by_triple(assets: list) -> dict[str, str]:
    """Map release assets to target triples using filename heuristics."""
    asset_by_triple: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_url = str(asset.get("url", ""))
        if not _is_supported_archive_url(asset_url):
            continue
        triple = _match_target(str(asset.get("name", "")))
        if triple and triple not in asset_by_triple:
            asset_by_triple[triple] = asset_url
    return asset_by_triple


def _extract_prev_targets(latest: dict, owner: str, name: str) -> dict[str, dict]:
    artifact = latest.get("artifact")
    targets = artifact.get("targets") if isinstance(artifact, dict) else None
    if not isinstance(targets, dict) or not targets:
        raise ValueError(f"{owner}/{name}: latest entry has no binary targets")
    return targets


def _verify_target_parity(
    prev_targets: dict[str, dict],
    asset_by_triple: dict[str, str],
    ctx: CandidateContext,
) -> None:
    missing = sorted(set(prev_targets.keys()) - set(asset_by_triple.keys()))
    if missing:
        raise ValueError(
            f"{ctx.owner}/{ctx.name}@{ctx.upstream_tag}: missing target asset(s) for: {', '.join(missing)}"
        )


def _build_plugin_targets(ctx: CandidateContext) -> dict[str, dict]:
    """Build target map for a binary plugin update after verifying 100% target parity."""
    prev_targets = _extract_prev_targets(ctx.latest, ctx.owner, ctx.name)
    asset_by_triple = _map_assets_by_triple(ctx.hit.get("assets") or [])
    _verify_target_parity(prev_targets, asset_by_triple, ctx)

    new_targets: dict[str, dict] = {}
    for triple, prev_target in prev_targets.items():
        prev_exe = str(prev_target.get("executable_path", ctx.name))
        new_targets[triple] = {
            "url": asset_by_triple[triple],
            "executable_path": _substitute_version(prev_exe, ctx.old_version, ctx.new_version),
        }
    return new_targets


def _prepare_plugin_spec(ctx: CandidateContext) -> dict:
    """Build a candidate spec for a binary plugin update with target parity verification."""
    new_targets = _build_plugin_targets(ctx)
    cargo_name = _plugin_cargo_name(ctx)
    inferred_nu = fetch_cargo_nu_constraint(ctx.repo, ctx.upstream_tag, cargo_name=cargo_name)
    if not inferred_nu:
        raise ValueError(
            f"{ctx.owner}/{ctx.name}@{ctx.upstream_tag}: could not infer Cargo Nu constraint from upstream Cargo.toml"
        )

    source_block = _resolve_plugin_source(ctx)
    spec: dict = {
        "owner": ctx.owner,
        "name": ctx.name,
        "description": str(ctx.package.get("description", "")),
        "repo": ctx.repo,
        "type": "plugin",
        "tags": list(ctx.package.get("tags") or ["plugin"]),
        "version": ctx.new_version,
        "nu_version": inferred_nu,
        "artifact": {
            "kind": "binary",
            "targets": new_targets,
        },
    }
    if source_block is not None:
        spec["source"] = source_block
    if "dependencies" in ctx.latest:
        spec["dependencies"] = copy.deepcopy(ctx.latest["dependencies"])
    return spec


def _lookup_package_and_latest(index: dict, package_scoped: str) -> tuple[dict, dict]:
    """Locate `package_scoped` and its latest version entry in `index`."""
    by_pkg = {split_scoped(p): p for p in index.get("packages", []) if isinstance(p, dict)}
    if package_scoped not in by_pkg:
        raise KeyError(f"package not found in index: {package_scoped}")
    package = by_pkg[package_scoped]
    latest = latest_entry(package)
    if latest is None:
        raise ValueError(f"package has no versions in index: {package_scoped}")
    return package, latest


def _lookup_upstream_hit(hits: dict, package_scoped: str) -> dict:
    """Locate `package_scoped` in `hits['upstream_updates']`."""
    for item in hits.get("upstream_updates", []):
        if isinstance(item, dict) and item.get("package") == package_scoped:
            return item
    raise KeyError(f"package not found in upstream_updates hits: {package_scoped}")


def prepare_candidate(
    index: dict,
    hits: dict,
    package_scoped: str,
    release_repo: str = "numan-cli/numan-registry",
) -> dict:
    """Find `package_scoped` in `index` and `hits['upstream_updates']` and return its spec."""
    package, latest = _lookup_package_and_latest(index, package_scoped)
    hit = _lookup_upstream_hit(hits, package_scoped)
    ctx = CandidateContext(
        package=package,
        latest=latest,
        hit=hit,
        release_repo=release_repo,
    )
    if ctx.ptype == "plugin":
        return _prepare_plugin_spec(ctx)
    if ctx.ptype in ("module", "script", "completion"):
        return _prepare_archive_spec(ctx)
    raise ValueError(f"unsupported package type {ctx.ptype!r} for {package_scoped}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument(
        "--hits", type=Path, required=True, help="Path to hits.json from watch_indexed.py"
    )
    parser.add_argument("--package", required=True, help="Scoped package ID (owner/name)")
    parser.add_argument("--release-repo", default="numan-cli/numan-registry")
    parser.add_argument(
        "--out-spec", type=Path, required=True, help="Output path for generated spec JSON"
    )
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
