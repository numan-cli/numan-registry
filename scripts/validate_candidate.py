#!/usr/bin/env python3.12
"""Stage 5: Validation harness for a candidate registry spec.

Orchestrates existing tools (add-package.py, lint_packages.py, validate.py,
lifecycle-prove.py) to download artifacts, compute hashes, lint, and optionally
run the full lifecycle against a real Nu binary.

Usage:
  python scripts/validate_candidate.py --spec spec.json
  python scripts/validate_candidate.py --spec spec.json --prove --numan /path/to/numan --nu /path/to/nu
  python scripts/validate_candidate.py --spec spec.json --out evidence.json

Steps:
  1. add-package.py --spec <spec> --write --index <tmp> --provisional  (download + hash)
  2. lint_packages.py --index <tmp>                                    (structural lint)
  3. validate.py --index <tmp> --skip-signature --skip-artifacts --allow-provisional-lifecycle
  4. lifecycle-prove.py --package owner/name [--numan ...] [--nu ...]  (opt-in via --prove)

Exit 0 if steps 1–3 pass. Step 4 is advisory unless --strict.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from gh_helpers import gh_json

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _intake_branch_name(owner: str, name: str, version: str) -> str:
    """Match open_intake_pr branch naming for open-PR lookup."""
    parts = []
    for value in (owner, name, version):
        cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", value).strip("-") or "unknown"
        parts.append(cleaned)
    return f"intake/{parts[0]}-{parts[1]}-{parts[2]}"


def _warn_open_intake_prs(owner: str, name: str, version: str) -> None:
    """Fail-soft: warn when an open intake PR already exists for this package.

    Uses the shared gh wrappers so Stage 5 can surface duplicate intake work
    without aborting validation when ``gh`` is missing or the query fails.
    """
    branch = _intake_branch_name(owner, name, version)
    existing = gh_json([
        "pr", "list", "--head", branch, "--state", "open", "--json", "number,url",
    ])
    if not isinstance(existing, list) or not existing:
        return
    for pr in existing:
        if not isinstance(pr, dict):
            continue
        number = pr.get("number", "?")
        url = pr.get("url", "")
        suffix = f": {url}" if url else ""
        print(
            f"warning: open intake PR #{number} already exists for "
            f"{owner}/{name}@{version}{suffix}",
            file=sys.stderr,
        )


def _run_script(args: list[str], *, label: str) -> tuple[bool, str]:
    """Run a Python script and capture output. Returns (success, output)."""
    try:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, f"{label}: timed out after 300s"
    except FileNotFoundError as exc:
        return False, f"{label}: {exc}"
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output


def _is_activatable(spec_data: dict) -> bool:
    """Return True if the package requires lifecycle evidence before promotion.

    Plugins are always activatable; modules, completions, and scripts are
    activatable only when they declare an `activation` section.
    """
    pkg_type = spec_data.get("type", "plugin")
    if pkg_type == "plugin":
        return True
    return pkg_type in ("module", "completion", "script") and "activation" in spec_data


def _load_spec(spec_path: Path) -> dict:
    """Load a candidate spec, unwrapping the {spec, _meta} wrapper if present.

    Raises ValueError when the JSON root or the unwrapped spec is not a JSON
    object, so the CLI can report a controlled error instead of a traceback.
    """
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec_data, dict):
        raise ValueError("spec must be a JSON object at the top level")
    if "spec" in spec_data and "_meta" in spec_data:
        spec_data = spec_data["spec"]
        if not isinstance(spec_data, dict):
            raise ValueError("spec must be a JSON object")
    return spec_data


def _seed_workdir(tmp_dir: Path, spec_data: dict) -> tuple[Path, Path]:
    """Write the effective spec and a schema-valid empty index into tmp_dir.

    add-package.py expects top-level spec fields, not the {spec, _meta}
    wrapper, so the effective spec is the unwrapped dict.

    Returns:
        tuple[Path, Path]: The effective spec path and the temporary index path.
    """
    effective_spec = tmp_dir / "spec.json"
    tmp_index = tmp_dir / "index.json"
    effective_spec.write_text(
        json.dumps(spec_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Seed a schema-valid index for add-package.py to merge into
    tmp_index.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "1970-01-01T00:00:00Z",
        "packages": [],
    }), encoding="utf-8")
    return effective_spec, tmp_index


def _count_targets(tmp_index: Path) -> int:
    """Count artifact targets in the merged temporary index."""
    targets_count = 0
    try:
        idx = json.loads(tmp_index.read_text(encoding="utf-8"))
        for pkg in idx.get("packages", []):
            for ver in pkg.get("versions", []):
                artifact = ver.get("artifact", {})
                if artifact.get("kind") == "binary":
                    targets_count += len(artifact.get("targets", {}))
                else:
                    targets_count += 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: cannot read temporary index: {exc}", file=sys.stderr)
    return targets_count


def _step_download_and_hash(effective_spec: Path, tmp_index: Path,
                             lifecycle_deferral: str = "") -> dict:
    """Step 1: download artifacts and compute hashes via add-package.py."""
    command = [
        str(SCRIPTS / "add-package.py"),
        "--spec", str(effective_spec),
        "--write", "--index", str(tmp_index),
    ]
    # Provisional entries must carry the lifecycle deferral reason through to
    # add-package.py; without a deferral, require the spec's verified_with.
    if lifecycle_deferral:
        command += ["--provisional", "--deferral-reason", lifecycle_deferral]
    ok, output = _run_script(command, label="add-package")
    targets_count = _count_targets(tmp_index) if ok else 0
    return {
        "name": "download_and_hash",
        "status": "pass" if ok else "fail",
        "targets": targets_count,
        "detail": "" if ok else output[-500:],
    }


def _extract_lint_errors(output_lint: str) -> list[str]:
    """Extract actionable FAIL diagnostics from lint_packages.py output.

    lint_packages.py reports failures as a FAIL header followed by indented
    bullet diagnostics; preserve those actionable messages, bounded to the
    last 2000 characters while retaining the end of diagnostics.
    """
    lines = output_lint.splitlines()
    capturing = False
    lint_errors = []
    for line in lines:
        if line.strip().startswith("FAIL:"):
            capturing = True
        if capturing:
            lint_errors.append(line)
    if not lint_errors:
        lint_errors = lines
    joined = "\n".join(lint_errors)
    return joined[-2000:].splitlines()


def _step_lint(tmp_index: Path) -> dict:
    """Step 2: structural lint via lint_packages.py."""
    ok_lint, output_lint = _run_script(
        [str(SCRIPTS / "lint_packages.py"), "--index", str(tmp_index)],
        label="lint",
    )
    return {
        "name": "lint",
        "status": "pass" if ok_lint else "fail",
        "errors": [] if ok_lint else _extract_lint_errors(output_lint),
    }


def _step_schema(tmp_index: Path) -> dict:
    """Step 3: schema validation via validate.py."""
    ok_schema, output_schema = _run_script(
        [str(SCRIPTS / "validate.py"),
         "--index", str(tmp_index),
         "--skip-signature", "--skip-artifacts",
         "--allow-provisional-lifecycle"],
        label="validate",
    )
    return {
        "name": "schema",
        "status": "pass" if ok_schema else "fail",
        "detail": "" if ok_schema else output_schema[-500:],
    }


def _step_lifecycle(package_id: str, *, prove: bool, numan: str | None,
                    nu: str | None, deferral: str) -> dict:
    """Step 4: lifecycle-prove (opt-in) or record the deferral/skip.

    NOTE: lifecycle-prove runs against the configured production registry,
    not the candidate index. For new packages not yet staged/published,
    this step will fail with "package not found" — that is expected.
    Use --prove only after the package is in the live registry.
    """
    if prove:
        lifecycle_args = [
            str(SCRIPTS / "lifecycle-prove.py"),
            "--package", package_id,
        ]
        if numan:
            lifecycle_args += ["--numan", numan]
        if nu:
            lifecycle_args += ["--nu", nu]
        ok_life, output_life = _run_script(lifecycle_args, label="lifecycle-prove")
        return {
            "name": "lifecycle",
            "status": "pass" if ok_life else "fail",
            "detail": "" if ok_life else (
                "lifecycle-prove runs against the live registry; "
                "new packages must be staged first. " + output_life[-400:]
            ),
        }
    detail = "not requested (use --prove)"
    if deferral:
        detail = f"deferred: {deferral}"
    return {
        "name": "lifecycle",
        "status": "skip",
        "detail": detail,
    }


def _compute_overall(checks: list[dict], *, strict: bool, deferral: str,
                     lifecycle_required: bool) -> str:
    """Derive the overall pass/fail verdict from the step checks."""
    core_checks = [c for c in checks if c["name"] != "lifecycle"]
    if not all(c["status"] == "pass" for c in core_checks):
        return "fail"
    lifecycle_check = next((c for c in checks if c["name"] == "lifecycle"), None)
    status = lifecycle_check["status"]
    if status == "pass":
        return "pass"
    if status == "fail":
        # Strict mode treats a failed proof as fatal; otherwise lifecycle
        # failure only fails when the package is activatable.
        return "fail" if (strict or lifecycle_required) else "pass"
    # status == "skip"
    if lifecycle_required and not deferral:
        return "fail"
    return "pass"


def _lifecycle_summary_text(status: str, *, deferral: str,
                            lifecycle_required: bool, overall: str) -> str | None:
    """Return the human summary sentence for a lifecycle check, or None."""
    if status == "pass":
        return "Lifecycle passed."
    if status == "fail":
        return "Lifecycle FAILED."
    if status == "skip":
        if deferral:
            return "Lifecycle deferred."
        if lifecycle_required and overall == "fail":
            return "Lifecycle evidence required for activatable package."
    return None


def _human_summary(checks: list[dict], *, deferral: str,
                   lifecycle_required: bool, overall: str) -> str:
    """Build the one-line human summary from the step checks."""
    parts = []
    dl = next(c for c in checks if c["name"] == "download_and_hash")
    if dl["status"] == "pass":
        parts.append(f"{dl['targets']} artifact(s) downloaded and hashed.")
    else:
        parts.append("Download/hash FAILED.")
    lint_c = next(c for c in checks if c["name"] == "lint")
    parts.append("Lint clean." if lint_c["status"] == "pass" else "Lint FAILED.")
    schema_c = next(c for c in checks if c["name"] == "schema")
    parts.append("Schema valid." if schema_c["status"] == "pass" else "Schema FAILED.")
    lifecycle_check = next((c for c in checks if c["name"] == "lifecycle"), None)
    if lifecycle_check:
        text = _lifecycle_summary_text(
            lifecycle_check["status"], deferral=deferral,
            lifecycle_required=lifecycle_required, overall=overall,
        )
        if text:
            parts.append(text)
    return " ".join(parts)


def validate_candidate(spec_path: Path, *, prove: bool = False,
                       numan: str | None = None, nu: str | None = None,
                       strict: bool = False,
                       lifecycle_deferral: str | None = None) -> dict:
    """Run all validation steps and return an evidence report."""
    spec_data = _load_spec(spec_path)

    owner = spec_data.get("owner", "unknown")
    name = spec_data.get("name", "unknown")
    version = str(spec_data.get("version", "0.0.0"))
    package_id = f"{owner}/{name}"
    deferral = (lifecycle_deferral or "").strip()
    if prove and deferral:
        raise ValueError("--prove and --lifecycle-deferral are mutually exclusive")

    _warn_open_intake_prs(owner, name, version)

    with tempfile.TemporaryDirectory(prefix="numan-validate-") as tmp:
        effective_spec, tmp_index = _seed_workdir(Path(tmp), spec_data)
        checks = [
            _step_download_and_hash(effective_spec, tmp_index, deferral),
            _step_lint(tmp_index),
            _step_schema(tmp_index),
        ]

    checks.append(
        _step_lifecycle(package_id, prove=prove, numan=numan, nu=nu, deferral=deferral)
    )

    lifecycle_required = _is_activatable(spec_data)
    overall = _compute_overall(
        checks, strict=strict, deferral=deferral, lifecycle_required=lifecycle_required
    )

    evidence = {
        "schema_version": 1,
        "spec_file": str(spec_path),
        "package_id": package_id,
        "checks": checks,
        "overall": overall,
        "human_summary": _human_summary(
            checks, deferral=deferral, lifecycle_required=lifecycle_required,
            overall=overall,
        ),
    }
    if deferral:
        evidence["lifecycle_deferral"] = {"reason": deferral}
    return evidence


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 5: validate a candidate spec")
    parser.add_argument("--spec", required=True, help="Path to spec JSON (Stage 4 output or raw spec)")
    parser.add_argument("--prove", action="store_true", help="Run lifecycle-prove (requires numan + nu)")
    parser.add_argument("--numan", help="Path to numan binary (for --prove)")
    parser.add_argument("--nu", help="Path to nu binary (for --prove)")
    parser.add_argument("--strict", action="store_true", help="Fail if lifecycle fails (with --prove)")
    parser.add_argument(
        "--lifecycle-deferral",
        help="Reason for skipping lifecycle-prove on an activatable package",
    )
    parser.add_argument("--out", help="Write evidence JSON to file instead of stdout")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"error: spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        evidence = validate_candidate(
            spec_path,
            prove=args.prove,
            numan=args.numan,
            nu=args.nu,
            strict=args.strict,
            lifecycle_deferral=args.lifecycle_deferral,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Evidence written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    print(f"\n  {evidence['human_summary']}", file=sys.stderr)
    sys.exit(0 if evidence["overall"] == "pass" else 1)


if __name__ == "__main__":
    main()
