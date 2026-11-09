#!/usr/bin/env python3.12
"""Stage 4: Generate a draft registry spec from a discovery report.

Transforms the Stage 3 discovery JSON into a spec file in the exact shape
that add-package.py expects. Includes a _meta provenance block so reviewers
can see what was discovered vs. guessed vs. unresolved.

Usage:
  python scripts/gen_candidate.py --report report.json [--out spec.json]
  python scripts/gen_candidate.py --report report.json --owner override --nu-version ">=0.114.0 <0.115.0"

Output (stdout or --out):
  {"spec": {...add-package.py compatible...}, "_meta": {...provenance...}}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lint_packages import KNOWN_TRIPLES

# ---------------------------------------------------------------------------
# Target-mapping heuristics
# ---------------------------------------------------------------------------

# Ordered patterns: first match wins for each asset filename.
_TARGET_PATTERNS: list[tuple[str, list[str]]] = [
    ("aarch64-pc-windows-msvc", ["aarch64-pc-windows-msvc", "aarch64-windows", "windows-aarch64", "win-arm64"]),
    ("x86_64-pc-windows-msvc", ["x86_64-pc-windows-msvc", "x86_64-windows", "windows-x86_64", "win-x64", "windows.zip"]),
    ("aarch64-unknown-linux-gnu", ["aarch64-unknown-linux-gnu", "aarch64-unknown-linux-musl", "aarch64-linux", "linux-aarch64", "linux-arm64"]),
    ("x86_64-unknown-linux-gnu", ["x86_64-unknown-linux-gnu", "x86_64-unknown-linux-musl", "x86_64-linux", "linux-x86_64", "linux-gnu", "linux.tar"]),
    ("aarch64-apple-darwin", ["aarch64-apple-darwin", "aarch64-macos", "macos-aarch64", "darwin-aarch64", "apple-aarch64"]),
    ("x86_64-apple-darwin", ["x86_64-apple-darwin", "x86_64-macos", "macos-x86_64", "darwin-x86_64", "apple-x86_64"]),
]


def _match_target(filename: str) -> str | None:
    """Match an asset filename to a known target triple."""
    lower = filename.lower()
    for triple, patterns in _TARGET_PATTERNS:
        for pattern in patterns:
            if pattern in lower:
                return triple
    return None


def _executable_path(name: str, target: str) -> str:
    """Infer the executable path inside an archive for a plugin."""
    exe_name = name if name.startswith("nu_plugin_") or name.startswith("nu-plugin-") else f"nu_plugin_{name}"
    if "windows" in target:
        return f"{exe_name}.exe"
    return exe_name


# ---------------------------------------------------------------------------
# Spec generation
# ---------------------------------------------------------------------------


def _pick_best_release(releases: list[dict]) -> dict | None:
    """Pick the first release with assets, else the first release overall."""
    for rel in releases:
        if rel.get("assets"):
            return rel
    return releases[0] if releases else None


def _owner_provenance(facts: dict, owner_override: str | None,
                      field_provenance: dict, unresolved: list[str]) -> None:
    """Record how the owner field was determined (or that it is unresolved)."""
    if owner_override:
        field_provenance["owner"] = f"CLI override: {owner_override}"
    elif facts.get("owner"):
        field_provenance["owner"] = "github repo owner"
    else:
        unresolved.append("owner not determined; use --owner")


def _nu_version_provenance(facts: dict, nu_version_override: str | None,
                           field_provenance: dict, warnings: list[str]) -> None:
    """Record how nu_version was determined, warning when defaulted."""
    if nu_version_override:
        field_provenance["nu_version"] = f"CLI override: {nu_version_override}"
    elif facts.get("nu_constraint_hint"):
        field_provenance["nu_version"] = "Cargo.toml nu-plugin dependency version"
    else:
        field_provenance["nu_version"] = "defaulted to * (not declared)"
        warnings.append("nu_version constraint not declared; defaulted to *")


def _release_version(best_release: dict | None,
                     field_provenance: dict, unresolved: list[str]) -> str:
    """Derive the version from the best release's tag (or leave unresolved)."""
    if not best_release:
        unresolved.append("version not determined; no releases found")
        return ""
    tag = best_release.get("tag", "")
    field_provenance["version"] = f"release tag {tag}"
    return tag[1:] if tag.startswith("v") else tag


def _binary_artifact(name: str, best_release: dict | None,
                     warnings: list[str], unresolved: list[str]) -> dict:
    """Build a binary artifact block, mapping assets to known target triples."""
    targets: dict[str, dict] = {}
    skipped: list[str] = []
    if best_release:
        for asset in best_release.get("assets", []):
            target = _match_target(asset["name"])
            if target and target in KNOWN_TRIPLES:
                targets[target] = {
                    "url": asset["url"],
                    "executable_path": _executable_path(name, target),
                }
            else:
                skipped.append(asset["name"])
    if skipped:
        warnings.append(f"unmapped assets skipped: {', '.join(skipped)}")
    if not targets:
        unresolved.append("no release assets matched known target triples")
    return {"kind": "binary", "targets": targets}


def _archive_artifact(best_release: dict | None,
                      field_provenance: dict, unresolved: list[str]) -> dict:
    """Build an archive artifact block for module/script/completion packages."""
    url = ""
    if best_release and best_release.get("assets"):
        url = best_release["assets"][0].get("url", "")
        field_provenance["artifact_url"] = f"first asset from release {best_release.get('tag', '')}"
    if not url:
        unresolved.append("no archive URL found; may need registry-hosted mirror")
    artifact: dict = {"kind": "archive", "url": url, "entry": "mod.nu"}
    return artifact


def _default_spec_base(owner: str | None, name: str, description: str,
                       repo_url: str, package_type: str, version: str,
                       nu_version: str) -> dict:
    """Build the add-package.py-compatible spec fields shared by all types."""
    return {
        "owner": owner or "TODO",
        "name": name,
        "description": description,
        "repo": repo_url,
        "type": package_type,
        "tags": [package_type, "ci-built"],
        "version": version or "0.0.0",
        "nu_version": nu_version,
    }


def generate_spec(report: dict, *, owner_override: str | None = None,
                  nu_version_override: str | None = None) -> dict:
    """Generate a candidate spec + provenance metadata from a discovery report."""
    facts = report.get("facts", {})
    guesses = report.get("guesses", {})

    owner = owner_override or facts.get("owner")
    name = facts.get("name", "")
    description = facts.get("description", "")
    package_type = facts.get("package_type") or guesses.get("registry_type")
    nu_version = nu_version_override or facts.get("nu_constraint_hint") or "*"
    releases = facts.get("releases", [])

    field_provenance: dict[str, str] = {}
    unresolved: list[str] = []
    warnings: list[str] = []

    _owner_provenance(facts, owner_override, field_provenance, unresolved)
    _nu_version_provenance(facts, nu_version_override, field_provenance, warnings)

    best_release = _pick_best_release(releases)
    version = _release_version(best_release, field_provenance, unresolved)

    repo_url = report.get("source", {}).get("url", "")
    if not repo_url and owner and name:
        repo_url = f"https://github.com/{owner}/{name}"

    if not package_type:
        unresolved.append("package_type not determined; defaulting to plugin — verify manually")
        package_type = "plugin"

    spec = _default_spec_base(
        owner, name, description, repo_url, package_type, version, nu_version
    )

    if package_type == "plugin":
        spec["artifact"] = _binary_artifact(name, best_release, warnings, unresolved)
    elif package_type in ("module", "script", "completion"):
        spec["artifact"] = _archive_artifact(best_release, field_provenance, unresolved)
        if package_type == "module":
            spec["activation"] = {"kind": "nu-module", "import": "all"}  # mod.nu → "all" per add-package.py convention
    else:
        unresolved.append(f"unsupported package_type '{package_type}'; cannot generate artifact block")

    unresolved.append("verified_with not populated — run lifecycle-prove")

    return {
        "spec": spec,
        "_meta": {
            "generated_from": "discovery-v1",
            "field_provenance": field_provenance,
            "unresolved": unresolved,
            "warnings": warnings,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 4: generate draft spec from discovery report")
    parser.add_argument("--report", required=True, help="Path to discovery report JSON (Stage 3 output)")
    parser.add_argument("--out", help="Write candidate to file instead of stdout")
    parser.add_argument("--owner", help="Override the registry owner field")
    parser.add_argument("--nu-version", help="Override the nu_version constraint")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"error: report file not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1:
        print(f"warning: unexpected discovery schema_version {report.get('schema_version')}", file=sys.stderr)

    candidate = generate_spec(report, owner_override=args.owner, nu_version_override=args.nu_version)

    output = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Candidate spec written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    # Print warnings to stderr for visibility
    for w in candidate["_meta"]["warnings"]:
        print(f"  warning: {w}", file=sys.stderr)
    for u in candidate["_meta"]["unresolved"]:
        print(f"  unresolved: {u}", file=sys.stderr)


if __name__ == "__main__":
    main()
