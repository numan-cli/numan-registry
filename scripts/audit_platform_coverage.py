#!/usr/bin/env python3
"""Report platform-proof coverage drift between two registry indexes.

A target is covered only when a proof record for that OS/architecture has a
passing result, at least one lifecycle command, and a Nu version that satisfies
the version's claimed ``nu_version`` range. This mirrors the production signing
gate; a target with no usable proof is reported as missing rather than inferred
from ``verified_with`` or another platform's proof.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lifecycle_proof_plan import TARGETS
from nu_version_constraint import matches_nu_constraint, parse_exact_nu_version

AUDIT_SCHEMA = "numan-platform-coverage-audit-v1"
TARGET_ORDER = (
    "linux/x86_64",
    "linux/aarch64",
    "macos/x86_64",
    "macos/aarch64",
    "windows/x86_64",
)
TARGET_BY_TRIPLE = {
    spec["triple"]: target for target, spec in TARGETS.items()
}
COVERED = "covered"
MISSING = "missing"
YANKED = "yanked"
UNMAPPED = "unmapped"


class CoverageError(ValueError):
    """Raised when an index cannot be audited safely."""


def _package_label(package: dict) -> str:
    identity = package.get("id")
    if not isinstance(identity, dict):
        raise CoverageError("package.id must be an object")
    owner = identity.get("owner")
    name = identity.get("name")
    if not isinstance(owner, str) or not owner or not isinstance(name, str) or not name:
        raise CoverageError("package.id must contain non-empty owner and name")
    return f"{owner}/{name}"


def _version_label(version: dict) -> str:
    value = version.get("version")
    if not isinstance(value, str) or not value:
        raise CoverageError("version.version must be a non-empty string")
    return value


def _artifact_targets(version: dict) -> list[str]:
    artifact = version.get("artifact")
    if not isinstance(artifact, dict):
        return []
    targets = artifact.get("targets")
    if not isinstance(targets, dict):
        return []
    return sorted(targets)


def _usable_commands(proof: dict) -> bool:
    commands = proof.get("commands")
    return (
        isinstance(commands, list)
        and bool(commands)
        and all(isinstance(command, str) and command.strip() for command in commands)
    )


def _target_proofs(version: dict, target: str) -> tuple[list[dict], str | None]:
    proofs = version.get("proofs")
    if not isinstance(proofs, list):
        return [], "no_proof"
    os_name, _, arch = target.partition("/")
    matching = [
        proof
        for proof in proofs
        if isinstance(proof, dict)
        and proof.get("os") == os_name
        and proof.get("arch") == arch
    ]
    return (matching, None) if matching else ([], "no_proof")


def _usable_target_proofs(proofs: list[dict]) -> tuple[list[dict], str | None]:
    passing = [proof for proof in proofs if proof.get("result") == "passed"]
    if not passing:
        return [], "failed"
    usable = [proof for proof in passing if _usable_commands(proof)]
    return (usable, None) if usable else ([], "unusable_commands")


def _newest_matching_proof(version: dict, proofs: list[dict]) -> tuple[dict | None, str | None]:
    constraint = version.get("nu_version")
    if not isinstance(constraint, str) or not constraint.strip():
        return None, "invalid_constraint"

    matching: list[tuple[tuple[int, int, int], dict]] = []
    invalid_constraint = False
    for proof in proofs:
        value = proof.get("nu_version")
        if not isinstance(value, str):
            continue
        try:
            if matches_nu_constraint(value, constraint):
                matching.append((parse_exact_nu_version(value), proof))
        except ValueError:
            invalid_constraint = True
    if not matching:
        return None, "nu_mismatch" if not invalid_constraint else "invalid_constraint"
    _, newest = max(matching, key=lambda item: item[0])
    return newest, None


def _matching_target_proofs(
    version: dict,
    target: str,
) -> tuple[list[dict], str | None]:
    """Return usable passing proofs for a target, plus the failure reason."""
    target_proofs, reason = _target_proofs(version, target)
    if reason:
        return [], reason
    usable, reason = _usable_target_proofs(target_proofs)
    if reason:
        return [], reason
    proof, reason = _newest_matching_proof(version, usable)
    return ([proof], None) if proof else ([], reason)


def _target_entry(package: str, version: dict, triple: str) -> dict:
    target = TARGET_BY_TRIPLE.get(triple)
    version_value = _version_label(version)
    entry = {
        "package": package,
        "version": version_value,
        "triple": triple,
        "target": target or triple,
        "mapped": target is not None,
        "state": UNMAPPED,
        "reason": "unmapped_target_triple",
        "proof_nu_version": None,
        "proof_timestamp": None,
        "yanked": bool(version.get("yanked")),
    }
    if target is None:
        return entry
    if version.get("yanked"):
        entry.update(state=YANKED, reason="yanked")
        return entry

    matching, reason = _matching_target_proofs(version, target)
    if matching:
        proof = matching[0]
        entry.update(
            state=COVERED,
            reason=None,
            proof_nu_version=proof.get("nu_version"),
            proof_timestamp=proof.get("timestamp"),
        )
    else:
        entry.update(state=MISSING, reason=reason)
    return entry


def _entry_key(entry: dict) -> tuple[str, str, str]:
    return entry["package"], entry["version"], entry["target"]


def _entry_sort_key(entry: dict) -> tuple[str, str, str]:
    return _entry_key(entry)


def _brief(entry: dict) -> dict:
    return {
        key: entry.get(key)
        for key in (
            "package",
            "version",
            "target",
            "state",
            "reason",
            "proof_nu_version",
            "yanked",
        )
    }


def _briefs(entries: list[dict]) -> list[dict]:
    return [_brief(entry) for entry in entries]


def _percent(covered: int, total: int) -> float | None:
    return round(100.0 * covered / total, 2) if total else None


def _platform_summary(entries: list[dict], target: str) -> dict:
    platform_entries = [entry for entry in entries if entry["target"] == target]
    active = [entry for entry in platform_entries if entry["state"] != YANKED]
    covered = [entry for entry in active if entry["state"] == COVERED]
    missing = [entry for entry in active if entry["state"] == MISSING]
    return {
        "published": len(platform_entries),
        "covered": len(covered),
        "missing": len(missing),
        "yanked": len(platform_entries) - len(active),
        "coverage_percent": _percent(len(covered), len(covered) + len(missing)),
    }


def _summary_totals(entries: list[dict], mapped: list[dict]) -> dict:
    active = [entry for entry in mapped if entry["state"] != YANKED]
    covered = [entry for entry in active if entry["state"] == COVERED]
    missing = [entry for entry in active if entry["state"] == MISSING]
    return {
        "versions": len({(entry["package"], entry["version"]) for entry in entries}),
        "packages": len({entry["package"] for entry in entries}),
        "published_targets": len(mapped),
        "covered_targets": len(covered),
        "missing_targets": len(missing),
        "yanked_targets": len(mapped) - len(active),
        "unmapped_targets": len(entries) - len(mapped),
        "coverage_percent": _percent(len(covered), len(covered) + len(missing)),
    }


def _summarize(entries: list[dict], source: str) -> dict:
    mapped = [entry for entry in entries if entry["mapped"]]
    return {
        "source": source,
        "updated_at": None,
        "registry_revision": None,
        "totals": _summary_totals(entries, mapped),
        "by_platform": {
            target: _platform_summary(mapped, target) for target in TARGET_ORDER
        },
    }


def build_snapshot(index: dict, source: str = "head") -> dict:
    """Build a deterministic target-level coverage snapshot."""
    if not isinstance(index, dict):
        raise CoverageError("index must be a JSON object")
    packages = index.get("packages")
    if not isinstance(packages, list):
        raise CoverageError("index.packages must be a list")

    entries: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise CoverageError("each package must be an object")
        package_label = _package_label(package)
        versions = package.get("versions")
        if not isinstance(versions, list):
            raise CoverageError(f"{package_label}: versions must be a list")
        for version in versions:
            if not isinstance(version, dict):
                raise CoverageError(f"{package_label}: each version must be an object")
            version_label = _version_label(version)
            for triple in _artifact_targets(version):
                entry = _target_entry(package_label, version, triple)
                key = _entry_key(entry)
                if key in seen:
                    raise CoverageError(
                        "duplicate package/version/target: "
                        + " / ".join(key)
                    )
                seen.add(key)
                entries.append(entry)

    entries.sort(key=_entry_sort_key)
    summary = _summarize(entries, source)
    summary["updated_at"] = index.get("updated_at")
    summary["registry_revision"] = index.get("registry_revision")
    summary["items"] = entries
    return summary


def _public_snapshot(snapshot: dict) -> dict:
    return {
        key: value
        for key, value in snapshot.items()
        if key != "items"
    }


def _select_changed(
    keys: list[tuple[str, str, str]],
    base_by_key: dict,
    head_by_key: dict,
    predicate,
) -> list[dict]:
    return [
        head_by_key[key]
        for key in keys
        if predicate(base_by_key[key], head_by_key[key])
    ]


def _state_changed(old: dict, new: dict) -> bool:
    return old["state"] != new["state"]


def _became_covered(old: dict, new: dict) -> bool:
    return old["state"] != COVERED and new["state"] == COVERED


def _lost_coverage(old: dict, new: dict) -> bool:
    return old["state"] == COVERED and new["state"] != COVERED


def _became_missing(old: dict, new: dict) -> bool:
    return old["state"] == COVERED and new["state"] == MISSING


def _became_yanked(old: dict, new: dict) -> bool:
    return old["state"] != YANKED and new["state"] == YANKED


def _diff_entries(base: list[dict], head: list[dict]) -> dict:
    base_by_key = {_entry_key(entry): entry for entry in base}
    head_by_key = {_entry_key(entry): entry for entry in head}
    base_keys = set(base_by_key)
    head_keys = set(head_by_key)
    common = sorted(base_keys & head_keys)
    added = [head_by_key[key] for key in sorted(head_keys - base_keys)]
    removed = [base_by_key[key] for key in sorted(base_keys - head_keys)]
    changed = _select_changed(common, base_by_key, head_by_key, _state_changed)
    newly_covered = _select_changed(common, base_by_key, head_by_key, _became_covered)
    newly_missing = _select_changed(common, base_by_key, head_by_key, _became_missing)
    newly_yanked = _select_changed(common, base_by_key, head_by_key, _became_yanked)
    removed_covered = [entry for entry in removed if entry["state"] == COVERED]
    coverage_regressions = (
        _select_changed(common, base_by_key, head_by_key, _lost_coverage)
        + removed_covered
    )
    base_versions = {(entry["package"], entry["version"]) for entry in base}
    head_versions = {(entry["package"], entry["version"]) for entry in head}
    return {
        "changed": bool(added or removed or changed),
        "added_targets": _briefs(added),
        "removed_targets": _briefs(removed),
        "newly_covered": _briefs(newly_covered),
        "newly_missing": _briefs(newly_missing),
        "newly_yanked": _briefs(newly_yanked),
        "coverage_regressions": _briefs(
            sorted(coverage_regressions, key=_entry_sort_key)
        ),
        "has_coverage_regression": bool(coverage_regressions),
        "versions_added": sorted(head_versions - base_versions),
        "versions_removed": sorted(base_versions - head_versions),
    }


def build_report(
    head_index: dict,
    base_index: dict | None = None,
    *,
    base_missing: bool = False,
) -> dict:
    if base_missing and base_index is not None:
        raise CoverageError("base_index and base_missing are mutually exclusive")
    head = build_snapshot(head_index, "registry/index.json")
    if base_missing:
        base = build_snapshot({"packages": []}, "base-index.json")
        base["missing"] = True
    elif base_index is not None:
        base = build_snapshot(base_index, "base-index.json")
    else:
        base = None
    drift = _diff_entries(base["items"], head["items"]) if base else None
    if drift is not None:
        drift["base_missing"] = base_missing
        drift["coverage_delta"] = {
            "covered_targets": (
                head["totals"]["covered_targets"] - base["totals"]["covered_targets"]
            ),
            "missing_targets": (
                head["totals"]["missing_targets"] - base["totals"]["missing_targets"]
            ),
            "yanked_targets": (
                head["totals"]["yanked_targets"] - base["totals"]["yanked_targets"]
            ),
            "unmapped_targets": (
                head["totals"]["unmapped_targets"] - base["totals"]["unmapped_targets"]
            ),
        }
    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": _public_snapshot(head),
        "base": _public_snapshot(base) if base else None,
        "base_missing": base_missing,
        "drift": drift,
        "items": head["items"],
    }


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _delta(value: int) -> str:
    return f"{value:+d}"


def _table(entries: list[dict], *, include_reason: bool = False) -> list[str]:
    if not entries:
        return []
    if include_reason:
        lines = [
            "| Package | Version | Target | Reason |",
            "|---|---|---|---|",
        ]
        for entry in entries:
            lines.append(
                "| "
                + entry["package"]
                + " | "
                + entry["version"]
                + " | "
                + entry["target"]
                + " | "
                + str(entry.get("reason") or "")
                + " |"
            )
        return lines
    lines = [
        "| Package | Version | Target | Proof Nu |",
        "|---|---|---|---|",
    ]
    for entry in entries:
        lines.append(
            "| "
            + entry["package"]
            + " | "
            + entry["version"]
            + " | "
            + entry["target"]
            + " | "
            + str(entry.get("proof_nu_version") or "—")
            + " |"
        )
    return lines


def render_markdown(report: dict) -> str:
    head = report["head"]
    totals = head["totals"]
    lines = [
        "# Platform-proof coverage audit",
        "",
        f"**Head:** `{head['source']}`"
        f" updated `{head.get('updated_at') or 'unknown'}`"
        f" (registry revision `{head.get('registry_revision') or 'unknown'}`).",
        "",
        "A target is covered only when a proof record for that platform has a "
        "passing result, at least one non-empty lifecycle command, and a Nu "
        "version that satisfies the version's claimed `nu_version` range. "
        "Yanked and unmapped targets are kept out of the coverage percentage.",
        "",
        "## Current coverage",
        "",
        f"**{totals['covered_targets']} / "
        f"{totals['covered_targets'] + totals['missing_targets']}** active mapped "
        f"targets covered (**{_format_percent(totals['coverage_percent'])}**); "
        f"**{totals['missing_targets']}** missing, "
        f"**{totals['yanked_targets']}** yanked, and "
        f"**{totals['unmapped_targets']}** unmapped artifact targets.",
        "",
        "| Platform | Published | Covered | Missing | Yanked | Coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for target in TARGET_ORDER:
        values = head["by_platform"][target]
        lines.append(
            f"| {target} | {values['published']} | {values['covered']} | "
            f"{values['missing']} | {values['yanked']} | "
            f"{_format_percent(values['coverage_percent'])} |"
        )
    lines.append("")
    if totals["unmapped_targets"]:
        lines.append(
            "Unmapped targets use artifact triples outside the supported proof "
            "target map; they are reported separately and are not counted as "
            "covered or missing."
        )
        lines.append("")

    base = report["base"]
    drift = report["drift"]
    lines.extend(["## Drift", ""])
    if base is None:
        lines.append(
            "No base index was supplied, so this run records the current "
            "snapshot only. Pass `--base-index` to compare revisions or "
            "`--base-missing` to report every current target as new."
        )
    elif not drift["changed"] and not drift.get("base_missing"):
        lines.append("No platform-proof coverage drift detected.")
    else:
        if drift.get("base_missing"):
            lines.append(
                "No base index exists at the comparison revision; all current "
                "targets are reported as new."
            )
        else:
            delta = drift["coverage_delta"]
            lines.append(
                f"Coverage delta: covered **{_delta(delta['covered_targets'])}**, "
                f"missing **{_delta(delta['missing_targets'])}**, "
                f"yanked **{_delta(delta['yanked_targets'])}**, "
                f"unmapped **{_delta(delta['unmapped_targets'])}**."
            )
        lines.append("")
        sections = (
            ("Newly covered", drift["newly_covered"], False),
            ("Newly missing", drift["newly_missing"], True),
            ("Newly yanked", drift["newly_yanked"], True),
            ("Added targets", drift["added_targets"], False),
            ("Removed targets", drift["removed_targets"], False),
        )
        for title, entries, include_reason in sections:
            if not entries:
                continue
            lines.extend([f"### {title} ({len(entries)})", ""])
            lines.extend(_table(entries, include_reason=include_reason))
            lines.append("")
        lines.append(
            "`newly missing` means a covered target became missing; a covered "
            "target that became yanked appears under `Newly yanked`, and a "
            "removed target appears under `Removed targets`. The JSON artifact "
            "has the complete per-target state and reasons."
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "This audit reports only platform-proof coverage. It does not sign, "
            "publish, or mutate the registry, and it does not replace the "
            "production signing gate.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CoverageError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CoverageError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CoverageError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("registry/index.json"))
    parser.add_argument(
        "--base-index",
        type=Path,
        help="Optional previous index used to compute coverage drift",
    )
    parser.add_argument(
        "--base-missing",
        action="store_true",
        help=(
            "Treat the base as absent and report every current target as new; "
            "used for first-commit histories and base commits without an index"
        ),
    )
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument(
        "--summary",
        type=Path,
        help="Append the Markdown report to a GitHub step summary file",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 when a covered target becomes missing, yanked, or removed",
    )
    args = parser.parse_args(argv)
    if args.base_missing and args.base_index:
        parser.error("--base-missing cannot be combined with --base-index")

    try:
        head_index = _load_json(args.index)
        base_index = _load_json(args.base_index) if args.base_index else None
        report = build_report(head_index, base_index, base_missing=args.base_missing)
        markdown = render_markdown(report)
    except CoverageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report_json:
        _write(args.report_json, payload)
    if args.report_md:
        _write(args.report_md, markdown)
    if args.summary:
        with args.summary.open("a", encoding="utf-8", newline="\n") as summary:
            summary.write(markdown)
            summary.write("\n")
    print(markdown)

    if (
        args.fail_on_regression
        and report["drift"]
        and report["drift"]["has_coverage_regression"]
    ):
        print(
            "error: platform-proof coverage regressions detected: "
            f"{len(report['drift']['coverage_regressions'])} target(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
