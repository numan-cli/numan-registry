#!/usr/bin/env python3
"""Resolve reusable lifecycle proof inputs into a runner matrix and commands."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from nu_version_constraint import EXACT_NU_VERSION, matches_nu_constraint

TARGETS = {
    "linux/x86_64": {
        "os": "linux",
        "arch": "x86_64",
        "runner": "ubuntu-24.04",
        "triple": "x86_64-unknown-linux-gnu",
        "archive": "tar.gz",
        "numan_asset": "x86_64-unknown-linux-gnu",
    },
    "linux/aarch64": {
        "os": "linux",
        "arch": "aarch64",
        "runner": "ubuntu-24.04-arm",
        "triple": "aarch64-unknown-linux-gnu",
        "archive": "tar.gz",
        "numan_asset": "aarch64-unknown-linux-gnu",
    },
    "macos/x86_64": {
        "os": "macos",
        "arch": "x86_64",
        "runner": "macos-15-intel",
        "triple": "x86_64-apple-darwin",
        "archive": "tar.gz",
        "numan_asset": "x86_64-apple-darwin",
    },
    "macos/aarch64": {
        "os": "macos",
        "arch": "aarch64",
        "runner": "macos-15",
        "triple": "aarch64-apple-darwin",
        "archive": "tar.gz",
        "numan_asset": "aarch64-apple-darwin",
    },
    "windows/x86_64": {
        "os": "windows",
        "arch": "x86_64",
        "runner": "windows-latest",
        "triple": "x86_64-pc-windows-msvc",
        "archive": "zip",
        "numan_asset": "x86_64-pc-windows-msvc",
    },
}

STANDARD_COMMANDS = [
    "init",
    "registry sync",
    "search",
    "info",
    "install",
    "activate",
    "doctor",
    "list",
    "deactivate",
    "remove",
    "gc",
]
INSTALL_ONLY_COMMANDS = [
    "init",
    "registry sync",
    "search",
    "info",
    "install",
    "doctor",
    "list",
    "remove",
    "gc",
]
COMMANDS_BY_KIND = {
    "plugin": STANDARD_COMMANDS,
    "nu-module": STANDARD_COMMANDS,
    "nu-overlay": STANDARD_COMMANDS,
    "nu-hook": STANDARD_COMMANDS,
    "nu-script": STANDARD_COMMANDS,
    "nu-completion": STANDARD_COMMANDS,
    "install-only": INSTALL_ONLY_COMMANDS,
}
SUPPORTED_COMMANDS = set(STANDARD_COMMANDS)
PACKAGE_VERSION_RE = re.compile(r"^\S+$")
REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
PUBLISHED_ARTIFACT_KINDS = {"archive", "source"}


@dataclass(frozen=True)
class ProofRequest:
    """Validated user inputs for one package proof plan."""

    package: str
    package_version: str
    nu_version: str
    targets: str
    activation_kind: str = ""
    commands: str | None = None
    numan_version: str = "0.4.0"
    numan_repo: str = "numan-cli/numan"


def parse_json_list(raw: str, label: str) -> list:
    """Parse a non-empty JSON array from a workflow input."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty JSON array")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return value


def _target_spec(value: object) -> tuple[str, dict]:
    if not isinstance(value, str):
        raise ValueError("each target must be an os/arch string")
    target = value.strip()
    spec = TARGETS.get(target)
    if spec is None:
        allowed = ", ".join(sorted(TARGETS))
        raise ValueError(f"unsupported target {target!r}; choose from {allowed}")
    return target, spec


def parse_targets(raw: str) -> list[dict]:
    """Map target identifiers to real runner and Nu asset metadata."""
    values = parse_json_list(raw, "targets")
    if not values:
        raise ValueError("targets must contain at least one os/arch target")
    targets = []
    seen = set()
    for value in values:
        target, spec = _target_spec(value)
        if target in seen:
            raise ValueError(f"duplicate target: {target}")
        seen.add(target)
        targets.append({"target": target, **spec})
    return targets


def _commands_for_kind(activation_kind: str) -> list[str]:
    try:
        return list(COMMANDS_BY_KIND[activation_kind])
    except KeyError as exc:
        raise ValueError(f"unsupported activation kind: {activation_kind}") from exc


def _validate_command_values(commands: list) -> None:
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("each command must be a non-empty string")


def _validate_unique_commands(commands: list[str]) -> None:
    if len(set(commands)) != len(commands):
        raise ValueError("commands must not contain duplicates")


def _validate_supported_commands(commands: list[str]) -> None:
    unknown = sorted(set(commands) - SUPPORTED_COMMANDS)
    if unknown:
        raise ValueError(f"unsupported lifecycle command(s): {', '.join(unknown)}")


def _clean_commands(raw: str) -> list[str]:
    commands = parse_json_list(raw, "commands")
    if not commands:
        raise ValueError("commands must be non-empty")
    _validate_command_values(commands)
    cleaned = [command.strip() for command in commands]
    _validate_unique_commands(cleaned)
    _validate_supported_commands(cleaned)
    return cleaned


def parse_commands(raw: str | None, activation_kind: str) -> list[str]:
    """Return the declared command sequence for an activation kind."""
    if raw is None or not raw.strip():
        commands = _commands_for_kind(activation_kind)
    else:
        commands = _clean_commands(raw)
    if "init" not in commands:
        raise ValueError("commands must include init")
    return commands


def _package_id(item: dict) -> str:
    identity = item.get("id", {})
    return identity.get("owner", "") + "/" + identity.get("name", "")


def _load_index(index_path: Path) -> dict:
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read candidate index {index_path}: {exc}") from exc


def _find_package(index: dict, package_id: str) -> dict | None:
    return next(
        (item for item in index.get("packages", []) if _package_id(item) == package_id),
        None,
    )


def _find_version(package: dict, package_version: str) -> dict | None:
    return next(
        (item for item in package.get("versions", []) if item.get("version") == package_version),
        None,
    )


def load_version(index_path: Path, package_id: str, package_version: str) -> tuple[dict, dict]:
    """Load the package and exact version from the candidate index."""
    package = _find_package(_load_index(index_path), package_id)
    if package is None:
        raise ValueError(f"package absent from candidate index: {package_id}")
    version = _find_version(package, package_version)
    if version is None:
        raise ValueError(f"version absent from candidate index: {package_id}@{package_version}")
    return package, version


def infer_activation_kind(package: dict, version: dict) -> str:
    """Infer the lifecycle kind from package type and activation metadata."""
    if package.get("type") == "plugin":
        return "plugin"
    activation = version.get("activation")
    if isinstance(activation, dict):
        kind = activation.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip()
    return "install-only"


def _validate_package(package: str) -> None:
    if package.count("/") != 1 or not all(package.split("/")):
        raise ValueError(f"package must be owner/name, got {package!r}")


def _validate_pattern(value: str, pattern: re.Pattern, message: str) -> None:
    if pattern.fullmatch(value) is None:
        raise ValueError(message)


def validate_request(request: ProofRequest) -> None:
    """Reject malformed workflow inputs before touching the candidate index."""
    _validate_package(request.package.strip())
    _validate_pattern(
        request.package_version,
        PACKAGE_VERSION_RE,
        f"package version must not contain whitespace: {request.package_version!r}",
    )
    _validate_pattern(
        request.nu_version,
        EXACT_NU_VERSION,
        f"Nu version must be exact MAJOR.MINOR.PATCH, got {request.nu_version!r}",
    )
    _validate_pattern(
        request.numan_version,
        EXACT_NU_VERSION,
        f"Numan version must be exact MAJOR.MINOR.PATCH, got {request.numan_version!r}",
    )
    _validate_pattern(
        request.numan_repo,
        REPO_RE,
        f"Numan repo must be owner/name, got {request.numan_repo!r}",
    )


def _validate_requested_kind(requested: str, inferred: str) -> None:
    if not requested:
        return
    if requested not in COMMANDS_BY_KIND:
        raise ValueError(f"unsupported activation kind: {requested}")
    if requested != inferred:
        raise ValueError(f"activation kind {requested!r} does not match candidate {inferred!r}")


def resolve_kind(requested: str, inferred: str) -> str:
    """Use the explicit kind only when it agrees with the candidate."""
    requested = requested.strip()
    _validate_requested_kind(requested, inferred)
    return requested or inferred


def _validate_nu(
    nu_version: str,
    version: dict,
    package: str,
    package_version: str,
) -> None:
    if not matches_nu_constraint(nu_version, version["nu_version"]):
        raise ValueError(
            f"Nu {nu_version} does not satisfy {version['nu_version']} for "
            f"{package}@{package_version}"
        )


def _artifact_for_target(version: dict, package_version: str, target: dict) -> dict:
    artifact = version.get("artifact", {})
    available = artifact.get("targets")
    if isinstance(available, dict):
        if target["triple"] not in available:
            raise ValueError(
                f"no published artifact for {target['target']} "
                f"({target['triple']}) in {package_version}"
            )
        return available[target["triple"]]
    if artifact.get("kind") not in PUBLISHED_ARTIFACT_KINDS:
        raise ValueError(
            f"{package_version} has no target map; cannot select {target['target']}"
        )
    return {}


def _target_entry(request: ProofRequest, target: dict, artifact: dict) -> dict:
    package = request.package.strip()
    return {
        **target,
        "artifact_url": artifact.get("url", ""),
        "artifact_sha256": artifact.get("sha256", ""),
        "label": f"{target['os']}-{target['arch']}",
        "log_name": (
            f"{package.replace('/', '__')}__{request.package_version}__nu-{request.nu_version}__"
            f"{target['os']}-{target['arch']}.log"
        ),
    }


def resolve_targets(request: ProofRequest, version_entry: dict) -> list[dict]:
    """Attach artifact metadata and log names to each requested target."""
    resolved = []
    for target in parse_targets(request.targets):
        artifact = _artifact_for_target(version_entry, request.package_version, target)
        resolved.append(_target_entry(request, target, artifact))
    return resolved


def build_plan(request: ProofRequest, index_path: Path) -> dict:
    """Validate inputs and return a workflow-ready proof plan."""
    package = request.package.strip()
    validate_request(request)
    package_entry, version_entry = load_version(index_path, package, request.package_version)
    kind = resolve_kind(
        request.activation_kind,
        infer_activation_kind(package_entry, version_entry),
    )
    resolved_commands = parse_commands(request.commands, kind)
    _validate_nu(request.nu_version, version_entry, package, request.package_version)
    resolved_targets = resolve_targets(request, version_entry)
    return {
        "package": package,
        "package_version": request.package_version,
        "nu_version": request.nu_version,
        "activation_kind": kind,
        "commands": resolved_commands,
        "numan_version": request.numan_version,
        "numan_repo": request.numan_repo,
        "matrix": {"include": resolved_targets},
    }


def write_github_output(path: Path, plan: dict) -> None:
    """Write compact JSON values for a prepare job's GitHub outputs."""
    values = {
        "package": plan["package"],
        "package_version": plan["package_version"],
        "nu_version": plan["nu_version"],
        "activation_kind": plan["activation_kind"],
        "commands": json.dumps(plan["commands"], separators=(",", ":")),
        "matrix": json.dumps(plan["matrix"], separators=(",", ":")),
        "numan_version": plan["numan_version"],
        "numan_repo": plan["numan_repo"],
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="Package id (owner/name)")
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--nu-version", required=True, help="Exact Nu version")
    parser.add_argument("--targets", required=True, help="JSON array of os/arch targets")
    parser.add_argument("--activation-kind", default="", help="Optional explicit kind")
    parser.add_argument("--commands", default="", help="Optional JSON array of lifecycle commands")
    parser.add_argument("--numan-version", default="0.4.0")
    parser.add_argument("--numan-repo", default="numan-cli/numan")
    parser.add_argument("--index", type=Path, default=Path("registry/index.json"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    request = ProofRequest(
        package=args.package,
        package_version=args.package_version,
        nu_version=args.nu_version,
        targets=args.targets,
        activation_kind=args.activation_kind,
        commands=args.commands,
        numan_version=args.numan_version,
        numan_repo=args.numan_repo,
    )
    try:
        plan = build_plan(request, args.index)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.github_output is not None:
        write_github_output(args.github_output, plan)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
