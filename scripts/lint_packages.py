#!/usr/bin/env python3.12
"""Stage 2 package lint for the Numan registry index.

Reports actionable, deterministic errors for common intake mistakes before
lifecycle-prove / production. Complements schema validation in validate.py
and the plugins-manifest Nu constraint gate in lint-manifest-index.py.

Usage:
  python3 scripts/lint_packages.py
  python3 scripts/lint_packages.py --index registry/index.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from archive_formats import SUPPORTED_ARCHIVE_SUFFIXES
from nu_version_constraint import COMPARATOR, EXACT_NU_VERSION, MINOR_WILDCARD
from url_safety import ensure_http_url, fork_upstream_differs_from_git

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "registry" / "index.json"

KNOWN_TRIPLES = frozenset(
    {
        "x86_64-unknown-linux-gnu",
        "aarch64-unknown-linux-gnu",
        "x86_64-apple-darwin",
        "aarch64-apple-darwin",
        "x86_64-pc-windows-msvc",
        "aarch64-pc-windows-msvc",
    }
)

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
PACKAGE_TYPES = frozenset({"plugin", "module", "script", "completion"})
ARTIFACT_KINDS = frozenset({"binary", "archive", "source"})
ACTIVATABLE_TYPES = frozenset({"plugin", "module"})


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def package_label(pkg: dict, *, entry_index: int | None = None) -> str:
    pkg_id = pkg.get("id")
    if isinstance(pkg_id, dict):
        owner = pkg_id.get("owner")
        name = pkg_id.get("name")
        if isinstance(owner, str) and isinstance(name, str):
            return f"{owner}/{name}"
    if entry_index is not None:
        return f"<unknown-package#{entry_index}>"
    return "<unknown-package>"


def version_label(
    pkg: dict,
    version: object,
    *,
    entry_index: int | None = None,
    version_index: int | None = None,
) -> str:
    base = package_label(pkg, entry_index=entry_index)
    if isinstance(version, dict):
        ver = version.get("version")
        if isinstance(ver, str) and ver.strip():
            return f"{base}@{ver}"
    if version_index is not None:
        return f"{base}@?#{version_index}"
    return f"{base}@?"


def archive_suffix_ok(url: str) -> bool:
    lower = url.lower()
    return any(lower.endswith(suffix) for suffix in SUPPORTED_ARCHIVE_SUFFIXES)


def nu_constraint_error(constraint: object) -> str | None:
    if not isinstance(constraint, str) or not constraint.strip():
        return "nu_version must be a non-empty string"
    if constraint == "*":
        return None
    for token in constraint.split():
        if MINOR_WILDCARD.fullmatch(token) is not None:
            continue
        if COMPARATOR.fullmatch(token) is not None:
            operator_match = COMPARATOR.fullmatch(token)
            assert operator_match is not None
            _operator, required_text = operator_match.groups()
            if EXACT_NU_VERSION.fullmatch(required_text) is None:
                return (
                    f"nu_version token {token!r} has a malformed exact version "
                    f"(expected MAJOR.MINOR.PATCH after the comparator)"
                )
            continue
        if EXACT_NU_VERSION.fullmatch(token) is None:
            return (
                f"nu_version token {token!r} is not a supported constraint form "
                "(exact, comparator, minor wildcard, or *)"
            )
    return None


def lint_required_package_fields(
    pkg: dict, errors: list[str], *, entry_index: int | None = None
) -> None:
    label = package_label(pkg, entry_index=entry_index)
    pkg_id = pkg.get("id")
    if not isinstance(pkg_id, dict):
        errors.append(f"{label}: missing object field id.owner/id.name")
    else:
        if not isinstance(pkg_id.get("owner"), str) or not pkg_id["owner"].strip():
            errors.append(f"{label}: missing metadata id.owner")
        if not isinstance(pkg_id.get("name"), str) or not pkg_id["name"].strip():
            errors.append(f"{label}: missing metadata id.name")
    for field in ("description", "repo"):
        value = pkg.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: missing metadata {field}")
    pkg_type = pkg.get("type")
    if pkg_type not in PACKAGE_TYPES:
        errors.append(
            f"{label}: type must be one of {sorted(PACKAGE_TYPES)}, got {pkg_type!r}"
        )
    tags = pkg.get("tags")
    if not isinstance(tags, list) or not tags:
        errors.append(f"{label}: missing metadata tags (non-empty list required)")
    versions = pkg.get("versions")
    if not isinstance(versions, list) or not versions:
        errors.append(f"{label}: missing versions (non-empty list required)")


def _validate_artifact_url(
    url: object,
    errors: list[str],
    *,
    what: str,
    what_url: str,
    label: str,
) -> None:
    """Validate an artifact URL is present and uses a supported archive suffix.

    ``what`` supplies the subject for the missing-url message (e.g. ``"target
    'x86_64-unknown-linux-gnu'"`` or ``"archive artifact"``); ``what_url``
    supplies the subject for the unsupported-suffix message (e.g. ``"target
    'x86_64-unknown-linux-gnu' url"`` or ``"archive url"``).
    """
    if not isinstance(url, str) or not url.strip():
        errors.append(f"{label}: {what} missing url")
    elif not archive_suffix_ok(url):
        errors.append(
            f"{label}: {what_url} has unsupported archive suffix "
            f"(supported: {', '.join(SUPPORTED_ARCHIVE_SUFFIXES)})"
        )


def _record_sha256(
    sha256: object,
    errors: list[str],
    *,
    seen_sha256: dict[str, str],
    dedupe_key: str,
    what: str,
    what_dup: str,
    label: str,
) -> None:
    """Validate a SHA-256 digest and record cross-entry dedupe bookkeeping.

    ``what`` supplies the subject for the malformed-sha256 message; ``what_dup``
    for the duplicate-sha256 message (archive wording differs between them).
    """
    if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
        errors.append(
            f"{label}: {what} missing or malformed sha256 "
            "(expected 64 hex chars)"
        )
    else:
        # Reaching here means sha256 is a str (the not-isinstance disjunct
        # short-circuits the guard above), so it is safe to record dedupe.
        prior = seen_sha256.get(sha256.lower())
        if prior is not None and prior != dedupe_key:
            errors.append(
                f"{label}: duplicate sha256 for {what_dup} (also used by {prior})"
            )
        else:
            seen_sha256[sha256.lower()] = dedupe_key


def lint_artifact(
    pkg: dict,
    version: dict,
    errors: list[str],
    *,
    seen_sha256: dict[str, str],
    entry_index: int | None = None,
    version_index: int | None = None,
) -> None:
    label = version_label(
        pkg, version, entry_index=entry_index, version_index=version_index
    )
    artifact = version.get("artifact")
    if not isinstance(artifact, dict):
        errors.append(f"{label}: missing artifact object")
        return

    kind = artifact.get("kind")
    if kind not in ARTIFACT_KINDS:
        errors.append(
            f"{label}: artifact.kind must be one of {sorted(ARTIFACT_KINDS)}, "
            f"got {kind!r}"
        )
        return

    if kind == "source":
        errors.append(
            f"{label}: artifact.kind 'source' is not intake-ready "
            "(use binary/archive specs; source builds stay deferred)"
        )
        return

    if kind == "binary":
        targets = artifact.get("targets")
        if not isinstance(targets, dict) or not targets:
            errors.append(f"{label}: binary artifact requires non-empty targets")
            return
        for triple, target in targets.items():
            if triple not in KNOWN_TRIPLES:
                errors.append(
                    f"{label}: unknown target triple {triple!r} "
                    f"(known: {', '.join(sorted(KNOWN_TRIPLES))})"
                )
            if not isinstance(target, dict):
                errors.append(f"{label}: target {triple!r} must be an object")
                continue
            executable_path = target.get("executable_path")
            what = f"target {triple!r}"
            _validate_artifact_url(
                target.get("url"),
                errors,
                what=what,
                what_url=f"{what} url",
                label=label,
            )
            _record_sha256(
                target.get("sha256"),
                errors,
                seen_sha256=seen_sha256,
                dedupe_key=f"{label}/{triple}",
                what=what,
                what_dup=what,
                label=label,
            )
            if not isinstance(executable_path, str) or not executable_path.strip():
                errors.append(
                    f"{label}: target {triple!r} missing executable_path"
                )
        return

    # archive
    _validate_artifact_url(
        artifact.get("url"),
        errors,
        what="archive artifact",
        what_url="archive url",
        label=label,
    )
    _record_sha256(
        artifact.get("sha256"),
        errors,
        seen_sha256=seen_sha256,
        dedupe_key=label,
        what="archive artifact",
        what_dup="archive",
        label=label,
    )


def _tags_claim_activation(tags: object) -> bool:
    """Return whether any tag string claims the package is activatable."""
    if not isinstance(tags, list):
        return False
    return any(isinstance(tag, str) and "activat" in tag.lower() for tag in tags)


def _lint_activation(
    pkg: dict,
    version: dict,
    errors: list[str],
    *,
    label: str,
) -> None:
    """Validate the activation block for module packages.

    Plugins activate via plugin add (activation is optional); scripts and
    completions are not activatable. Only modules get checked, and only when
    they declare an activation block or are tagged as activatable.
    """
    pkg_type = pkg.get("type")
    activation = version.get("activation")
    if pkg_type != "module":
        return

    if not isinstance(activation, dict):
        # Install-only modules are allowed; only flag when tags claim activation
        if _tags_claim_activation(pkg.get("tags")):
            errors.append(
                f"{label}: module tagged for activation is missing "
                "activation declaration"
            )
        return

    kind = activation.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        errors.append(f"{label}: activation.kind is missing")
    import_mode = activation.get("import")
    if import_mode is not None and import_mode not in ("module", "all"):
        errors.append(
            f"{label}: activation.import must be 'module' or 'all', "
            f"got {import_mode!r}"
        )


def _lint_source_provenance(
    pkg: dict,
    version: dict,
    errors: list[str],
    *,
    label: str,
) -> None:
    """Validate the source provenance block (git/rev, plus cargo_name for plugins)."""
    source = version.get("source")
    if source is None:
        return
    if not isinstance(source, dict):
        errors.append(f"{label}: source must be an object when present")
        return
    required = ("git", "rev", "cargo_name") if pkg.get("type") == "plugin" else ("git", "rev")
    for field in required:
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: source.{field} is missing or empty")
    rev = source.get("rev")
    if isinstance(rev, str) and rev.strip().lower() in {"main", "master", "head"}:
        errors.append(
            f"{label}: source.rev {rev!r} is not immutable provenance "
            "(use a tag or full commit)"
        )


def _lint_fork_identity(
    pkg: dict,
    version: dict,
    errors: list[str],
    *,
    label: str,
) -> None:
    """Require source.upstream on every numan-maintained fork version.

    Fork identity must never let installing the original owner/name silently
    resolve to a fork -- source.upstream is what keeps that distinction
    machine-checkable, not just documented convention.
    """
    owner = (pkg.get("id") or {}).get("owner") if isinstance(pkg.get("id"), dict) else None
    source = version.get("source")
    if not isinstance(source, dict):
        if owner == "numan-maintained":
            errors.append(f"{label}: owner 'numan-maintained' requires source.upstream (original repo URL)")
        return
    upstream = source.get("upstream")
    if owner != "numan-maintained":
        if "upstream" in source:
            errors.append(
                f"{label}: source.upstream is only valid for owner 'numan-maintained'"
            )
        return
    if not isinstance(upstream, str) or not upstream.strip():
        errors.append(f"{label}: owner 'numan-maintained' requires source.upstream (original repo URL)")
        return
    try:
        ensure_http_url(upstream.strip())
    except ValueError as exc:
        errors.append(f"{label}: source.upstream {exc}")
        return
    git = source.get("git")
    if isinstance(git, str) and not fork_upstream_differs_from_git(git, upstream):
        errors.append(
            f"{label}: source.upstream must identify the original repository, "
            "not the fork's source.git"
        )


def lint_activation_and_provenance(
    pkg: dict,
    version: dict,
    errors: list[str],
    *,
    entry_index: int | None = None,
    version_index: int | None = None,
) -> None:
    label = version_label(
        pkg, version, entry_index=entry_index, version_index=version_index
    )
    _lint_activation(pkg, version, errors, label=label)
    _lint_source_provenance(pkg, version, errors, label=label)
    _lint_fork_identity(pkg, version, errors, label=label)


def lint_version(
    pkg: dict,
    version: object,
    errors: list[str],
    *,
    seen_sha256: dict[str, str],
    entry_index: int | None = None,
    version_index: int | None = None,
) -> None:
    if not isinstance(version, dict):
        pkg_label = package_label(pkg, entry_index=entry_index)
        if version_index is not None:
            errors.append(
                f"{pkg_label}: versions[{version_index}]: entry must be an object"
            )
        else:
            errors.append(f"{pkg_label}: versions entry must be an object")
        return
    label = version_label(
        pkg, version, entry_index=entry_index, version_index=version_index
    )
    if not isinstance(version.get("version"), str) or not version["version"].strip():
        errors.append(f"{label}: missing version string")
    constraint_error = nu_constraint_error(version.get("nu_version"))
    if constraint_error is not None:
        errors.append(f"{label}: {constraint_error}")
    verified = version.get("verified_with")
    if verified is not None:
        if not isinstance(verified, list) or not verified:
            errors.append(f"{label}: verified_with must be a non-empty list when set")
        else:
            for item in verified:
                if not isinstance(item, str) or EXACT_NU_VERSION.fullmatch(item) is None:
                    errors.append(
                        f"{label}: verified_with entry {item!r} must be "
                        "MAJOR.MINOR.PATCH"
                    )
    lint_artifact(
        pkg,
        version,
        errors,
        seen_sha256=seen_sha256,
        entry_index=entry_index,
        version_index=version_index,
    )
    lint_activation_and_provenance(
        pkg,
        version,
        errors,
        entry_index=entry_index,
        version_index=version_index,
    )


def lint_index(index: dict) -> list[str]:
    errors: list[str] = []
    packages = index.get("packages")
    if not isinstance(packages, list):
        return ["packages must be a list"]

    seen_ids: dict[str, int] = {}
    seen_sha256: dict[str, str] = {}
    for entry_index, pkg in enumerate(packages):
        if not isinstance(pkg, dict):
            errors.append(f"packages[{entry_index}]: entry must be an object")
            continue
        label = package_label(pkg, entry_index=entry_index)
        if label in seen_ids:
            errors.append(f"{label}: duplicate package id in index")
        else:
            seen_ids[label] = 1
        lint_required_package_fields(pkg, errors, entry_index=entry_index)
        versions = pkg.get("versions")
        if not isinstance(versions, list):
            continue
        seen_versions: set[str] = set()
        for version_index, version in enumerate(versions):
            if isinstance(version, dict) and isinstance(version.get("version"), str):
                ver = version["version"]
                if ver in seen_versions:
                    errors.append(f"{label}@{ver}: duplicate version entry")
                else:
                    seen_versions.add(ver)
            lint_version(
                pkg,
                version,
                errors,
                seen_sha256=seen_sha256,
                entry_index=entry_index,
                version_index=version_index,
            )
    return errors


def provisional_deferral_warnings(index: dict) -> list[str]:
    """Warn (non-fatally) about provisional versions missing a deferral reason.

    Kept separate from lint_index's error list on purpose: a missing
    deferral_reason on a pre-reform provisional entry is a migration-tolerance
    gap, not a hard validation failure.
    """
    warnings: list[str] = []
    packages = index.get("packages")
    if not isinstance(packages, list):
        return warnings
    for entry_index, pkg in enumerate(packages):
        if not isinstance(pkg, dict):
            continue
        versions = pkg.get("versions")
        if not isinstance(versions, list):
            continue
        for version_index, version in enumerate(versions):
            if not isinstance(version, dict):
                continue
            if version.get("evidence_tier") != "provisional":
                continue
            reason = version.get("deferral_reason")
            if not isinstance(reason, str) or not reason.strip():
                label = version_label(
                    pkg, version, entry_index=entry_index, version_index=version_index
                )
                warnings.append(f"{label}: evidence_tier is provisional but deferral_reason is missing/empty")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help=f"Path to registry index (default: {DEFAULT_INDEX})",
    )
    args = parser.parse_args(argv)

    try:
        index = load_json(args.index)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not load index {args.index}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(index, dict):
        print("FAIL: index root must be an object", file=sys.stderr)
        return 2

    errors = lint_index(index)
    # Deterministic ordering for before/after PR comparison.
    errors = sorted(set(errors))

    warnings = sorted(set(provisional_deferral_warnings(index)))
    if warnings:
        print(f"WARN: {len(warnings)} provisional entry warning(s):", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)

    if errors:
        print(f"FAIL: {len(errors)} package lint error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    package_count = len(index.get("packages") or [])
    print(f"OK: package lint passed for {package_count} package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
