#!/usr/bin/env python3
"""Resolve reusable lifecycle proof inputs into a runner matrix and commands."""

from __future__ import annotations

import argparse
import json
import re
import sys
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


def parse_targets(raw: str) -> list[dict]:
    """Map target identifiers to real runner and Nu asset metadata."""
    values = parse_json_list(raw, "targets")
    if not values:
        raise ValueError("targets must contain at least one os/arch target")
    targets = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("each target must be an os/arch string")
        target = value.strip()
        if target in seen:
            raise ValueError(f"duplicate target: {target}")
        spec = TARGETS.get(target)
        if spec is None:
            allowed = ", ".join(sorted(TARGETS))
            raise ValueError(f"unsupported target {target!r}; choose from {allowed}")
        seen.add(target)
        targets.append({"target": target, **spec})
    return targets


def parse_commands(raw: str | None, activation_kind: str) -> list[str]:
    """Return the declared command sequence for an activation kind."""
    if raw is None or not raw.strip():
        try:
            commands = list(COMMANDS_BY_KIND[activation_kind])
        except KeyError as exc:
            raise ValueError(f"unsupported activation kind: {activation_kind}") from exc
    else:
        commands = parse_json_list(raw, "commands")
        if not commands:
            raise ValueError("commands must be non-empty")
        if not all(isinstance(command, str) and command.strip() for command in commands):
            raise ValueError("each command must be a non-empty string")
        commands = [command.strip() for command in commands]
        if len(set(commands)) != len(commands):
            raise ValueError("commands must not contain duplicates")
        unknown = sorted(set(commands) - SUPPORTED_COMMANDS)
        if unknown:
            raise ValueError(f"unsupported lifecycle command(s): {', '.join(unknown)}")
    if "init" not in commands:
        raise ValueError("commands must include init")
    return commands


def load_version(index_path: Path, package_id: str, package_version: str) -> tuple[dict, dict]:
    """Load the package and exact version from the candidate index."""
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read candidate index {index_path}: {exc}") from exc
    package = next(
        (
            item
            for item in index.get("packages", [])
            if item.get("id", {}).get("owner", "") + "/" + item.get("id", {}).get("name", "") == package_id
        ),
        None,
    )
    if package is None:
        raise ValueError(f"package absent from candidate index: {package_id}")
    version = next(
        (item for item in package.get("versions", []) if item.get("version") == package_version),
        None,
    )
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


def build_plan(
    *,
    package: str,
    package_version: str,
    nu_version: str,
    targets: str,
    activation_kind: str,
    commands: str | None,
    numan_version: str,
    numan_repo: str,
    index_path: Path,
) -> dict:
    """Validate inputs and return a workflow-ready proof plan."""
    package = package.strip()
    if package.count("/") != 1 or not all(package.split("/")):
        raise ValueError(f"package must be owner/name, got {package!r}")
    if not PACKAGE_VERSION_RE.fullmatch(package_version):
        raise ValueError(f"package version must not contain whitespace: {package_version!r}")
    if EXACT_NU_VERSION.fullmatch(nu_version) is None:
        raise ValueError(f"Nu version must be exact MAJOR.MINOR.PATCH, got {nu_version!r}")
    if EXACT_NU_VERSION.fullmatch(numan_version) is None:
        raise ValueError(f"Numan version must be exact MAJOR.MINOR.PATCH, got {numan_version!r}")
    if REPO_RE.fullmatch(numan_repo) is None:
        raise ValueError(f"Numan repo must be owner/name, got {numan_repo!r}")

    package_entry, version_entry = load_version(index_path, package, package_version)
    inferred = infer_activation_kind(package_entry, version_entry)
    requested = activation_kind.strip()
    if requested and requested not in COMMANDS_BY_KIND:
        raise ValueError(f"unsupported activation kind: {requested}")
    if requested and requested != inferred:
        raise ValueError(
            f"activation kind {requested!r} does not match candidate {inferred!r}"
        )
    kind = requested or inferred
    if kind not in COMMANDS_BY_KIND:
        raise ValueError(f"unsupported activation kind: {kind}")
    resolved_commands = parse_commands(commands, kind)
    if not matches_nu_constraint(nu_version, version_entry["nu_version"]):
        raise ValueError(
            f"Nu {nu_version} does not satisfy {version_entry['nu_version']} for "
            f"{package}@{package_version}"
        )

    resolved_targets = parse_targets(targets)
    available = version_entry.get("artifact", {}).get("targets")
    for target in resolved_targets:
        if isinstance(available, dict):
            if target["triple"] not in available:
                raise ValueError(
                    f"no published artifact for {target['target']} "
                    f"({target['triple']}) in {package}@{package_version}"
                )
            target["artifact_url"] = available[target["triple"]].get("url", "")
            target["artifact_sha256"] = available[target["triple"]].get("sha256", "")
        elif version_entry.get("artifact", {}).get("kind") not in {"archive", "source"}:
            raise ValueError(
                f"{package}@{package_version} has no target map; cannot select {target['target']}"
            )
        target["label"] = f"{target['os']}-{target['arch']}"
        target["log_name"] = (
            f"{package.replace('/', '__')}__{package_version}__nu-{nu_version}__"
            f"{target['os']}-{target['arch']}.log"
        )

    return {
        "package": package,
        "package_version": package_version,
        "nu_version": nu_version,
        "activation_kind": kind,
        "commands": resolved_commands,
        "numan_version": numan_version,
        "numan_repo": numan_repo,
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

    try:
        plan = build_plan(
            package=args.package,
            package_version=args.package_version,
            nu_version=args.nu_version,
            targets=args.targets,
            activation_kind=args.activation_kind,
            commands=args.commands,
            numan_version=args.numan_version,
            numan_repo=args.numan_repo,
            index_path=args.index,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.github_output is not None:
        write_github_output(args.github_output, plan)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
