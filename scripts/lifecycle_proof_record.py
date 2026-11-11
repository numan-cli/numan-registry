#!/usr/bin/env python3
"""Convert a lifecycle proof log into an index-compatible proof record."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
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
REQUIRED_HEADERS = ("package", "package_version", "nu_version", "platform", "started_at", "exit_code")
TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)


@dataclass(frozen=True)
class ProofExpectation:
    """Expected package metadata and commands for one proof log."""

    commands: list[str]
    package: str | None = None
    package_version: str | None = None
    nu_version: str | None = None
    evidence_url: str | None = None


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


def _decode_commands(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"commands is not valid JSON: {exc}") from exc


def _validate_commands(commands: object) -> list[str]:
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty JSON array")
    if not all(isinstance(command, str) and command.strip() for command in commands):
        raise ValueError("each command must be a non-empty string")
    return [command.strip() for command in commands]


def parse_commands(raw: str) -> list[str]:
    """Parse and validate the command list passed to the proof."""
    return _validate_commands(_decode_commands(raw))


def _require_headers(fields: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_HEADERS if not fields.get(key)]
    if missing:
        raise ValueError(f"proof log is missing header field(s): {', '.join(missing)}")


def _check_expected(fields: dict[str, str], expectation: ProofExpectation) -> None:
    expected = {
        "package": expectation.package,
        "package_version": expectation.package_version,
        "nu_version": expectation.nu_version,
    }
    for key, value in expected.items():
        if value is not None and fields[key] != value:
            raise ValueError(f"proof log {key} {fields[key]!r} does not match expected {value!r}")


def _parse_platform(fields: dict[str, str]) -> tuple[str, str]:
    platform = fields["platform"]
    if platform.count("/") != 1:
        raise ValueError(f"proof log platform must be os/arch, got {platform!r}")
    os_name, arch = platform.split("/", 1)
    if os_name not in OS_VALUES or arch not in ARCH_VALUES:
        raise ValueError(f"unsupported proof platform: {platform}")
    return os_name, arch


def _parse_timestamp(fields: dict[str, str]) -> str:
    timestamp = fields.get("finished_at") or fields["started_at"]
    if TIMESTAMP_RE.fullmatch(timestamp) is None:
        raise ValueError(f"proof log timestamp is invalid: {timestamp!r}")
    return timestamp


def _is_passed(fields: dict[str, str], text: str) -> bool:
    return fields["exit_code"] == "0" and "OK: lifecycle-prove passed." in text


def _make_proof(
    fields: dict[str, str],
    platform: tuple[str, str],
    passed: bool,
    expectation: ProofExpectation,
) -> dict:
    os_name, arch = platform
    proof = {
        "os": os_name,
        "arch": arch,
        "nu_version": fields["nu_version"],
        "result": "passed" if passed else "failed",
        "timestamp": _parse_timestamp(fields),
    }
    if passed:
        proof["commands"] = expectation.commands
    if expectation.evidence_url:
        proof["evidence_url"] = expectation.evidence_url
    return proof


def build_proof(text: str, expectation: ProofExpectation) -> dict:
    """Build the proof object consumed by the signed index."""
    fields = parse_header(text)
    _require_headers(fields)
    _check_expected(fields, expectation)
    os_name, arch = _parse_platform(fields)
    if EXACT_NU_VERSION.fullmatch(fields["nu_version"]) is None:
        raise ValueError(f"proof log Nu version is not exact: {fields['nu_version']!r}")
    return _make_proof(fields, (os_name, arch), _is_passed(fields, text), expectation)


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
        expectation = ProofExpectation(
            commands=parse_commands(args.commands_json),
            package=args.package,
            package_version=args.package_version,
            nu_version=args.nu_version,
            evidence_url=args.evidence_url,
        )
        proof = build_proof(text, expectation)
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
