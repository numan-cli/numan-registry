#!/usr/bin/env python3
"""Convert a lifecycle proof log into an index-compatible proof record."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from nu_version_constraint import EXACT_NU_VERSION

HEADER_KEYS = {
    "package",
    "package_version",
    "nu_version",
    "started_at",
    "platform",
    "runner_image",
    "uname",
    "numan_version",
    "numan_source",
    "numan_asset_url",
    "numan_sha256",
    "candidate_index_sha256",
    "nu_archive_url",
    "nu_archive_sha256",
    "nu_exe_sha256",
    "finished_at",
    "exit_code",
}
OS_VALUES = {"windows", "linux", "macos"}
ARCH_VALUES = {"x86_64", "aarch64"}
TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)


def parse_header(text: str) -> dict[str, str]:
    """Read the first occurrence of each known header field."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([a-z0-9_]+)=(.*)$", line)
        if match is None:
            continue
        key, value = match.groups()
        if key in HEADER_KEYS and key not in fields:
            fields[key] = value
    return fields


def parse_commands(raw: str) -> list[str]:
    """Parse and validate the command list passed to the proof."""
    try:
        commands = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"commands is not valid JSON: {exc}") from exc
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty JSON array")
    if not all(isinstance(command, str) and command.strip() for command in commands):
        raise ValueError("each command must be a non-empty string")
    return [command.strip() for command in commands]


def build_proof(
    text: str,
    *,
    commands: list[str],
    package: str | None = None,
    package_version: str | None = None,
    nu_version: str | None = None,
    evidence_url: str | None = None,
) -> dict:
    """Build the proof object consumed by the signed index."""
    fields = parse_header(text)
    required = ("package", "package_version", "nu_version", "platform", "started_at", "exit_code")
    missing = [key for key in required if not fields.get(key)]
    if missing:
        raise ValueError(f"proof log is missing header field(s): {', '.join(missing)}")
    expected = {
        "package": package,
        "package_version": package_version,
        "nu_version": nu_version,
    }
    for key, value in expected.items():
        if value is not None and fields[key] != value:
            raise ValueError(f"proof log {key} {fields[key]!r} does not match expected {value!r}")

    platform = fields["platform"]
    if platform.count("/") != 1:
        raise ValueError(f"proof log platform must be os/arch, got {platform!r}")
    os_name, arch = platform.split("/", 1)
    if os_name not in OS_VALUES or arch not in ARCH_VALUES:
        raise ValueError(f"unsupported proof platform: {platform}")
    if EXACT_NU_VERSION.fullmatch(fields["nu_version"]) is None:
        raise ValueError(f"proof log Nu version is not exact: {fields['nu_version']!r}")

    timestamp = fields.get("finished_at") or fields["started_at"]
    if TIMESTAMP_RE.fullmatch(timestamp) is None:
        raise ValueError(f"proof log timestamp is invalid: {timestamp!r}")
    passed = fields["exit_code"] == "0" and "OK: lifecycle-prove passed." in text
    result = "passed" if passed else "failed"

    proof = {
        "os": os_name,
        "arch": arch,
        "nu_version": fields["nu_version"],
        "result": result,
        "timestamp": timestamp,
    }
    if passed:
        proof["commands"] = commands
    if evidence_url:
        proof["evidence_url"] = evidence_url
    return proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--commands-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package")
    parser.add_argument("--package-version")
    parser.add_argument("--nu-version")
    parser.add_argument("--evidence-url")
    parser.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="Exit nonzero after writing a failed proof record",
    )
    args = parser.parse_args(argv)

    try:
        text = args.log.read_text(encoding="utf-8")
        commands = parse_commands(args.commands_json)
        proof = build_proof(
            text,
            commands=commands,
            package=args.package,
            package_version=args.package_version,
            nu_version=args.nu_version,
            evidence_url=args.evidence_url,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proof, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(proof, separators=(",", ":"), ensure_ascii=False))
    if args.fail_on_failure and proof["result"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
