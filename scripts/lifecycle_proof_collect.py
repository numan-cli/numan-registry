#!/usr/bin/env python3
"""Collect per-target proof artifacts into a deterministic proof batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nu_version_constraint import EXACT_NU_VERSION

PROOF_KEYS = {"os", "arch", "nu_version", "result", "commands", "timestamp", "evidence_url"}
REQUIRED_KEYS = {"os", "arch", "nu_version", "result", "timestamp"}
OS_ORDER = {"windows": 0, "linux": 1, "macos": 2}
ARCH_ORDER = {"x86_64": 0, "aarch64": 1}


def _validate_proof(proof: object, source: Path) -> dict:
    if not isinstance(proof, dict):
        raise ValueError(f"{source}: proof must be a JSON object")
    missing = REQUIRED_KEYS - set(proof)
    extra = set(proof) - PROOF_KEYS
    if missing:
        raise ValueError(f"{source}: missing proof field(s): {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{source}: unsupported proof field(s): {', '.join(sorted(extra))}")
    if proof["os"] not in OS_ORDER:
        raise ValueError(f"{source}: unsupported os {proof['os']!r}")
    if proof["arch"] not in ARCH_ORDER:
        raise ValueError(f"{source}: unsupported arch {proof['arch']!r}")
    if proof["result"] not in {"passed", "failed"}:
        raise ValueError(f"{source}: unsupported result {proof['result']!r}")
    if EXACT_NU_VERSION.fullmatch(str(proof["nu_version"])) is None:
        raise ValueError(f"{source}: nu_version is not exact")
    if proof["result"] == "passed":
        commands = proof.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ValueError(f"{source}: passed proof requires commands")
    return proof


def load_proofs(artifacts_dir: Path) -> list[dict]:
    """Load proof.json files from downloaded workflow artifacts."""
    files = sorted(artifacts_dir.rglob("proof.json"))
    if not files:
        raise ValueError(f"no proof.json files under {artifacts_dir}")
    proofs = [_validate_proof(json.loads(path.read_text(encoding="utf-8")), path) for path in files]
    seen = set()
    for proof in proofs:
        key = (proof["os"], proof["arch"])
        if key in seen:
            raise ValueError(f"duplicate proof for {key[0]}/{key[1]}")
        seen.add(key)
    return sorted(
        proofs,
        key=lambda proof: (OS_ORDER[proof["os"]], ARCH_ORDER[proof["arch"]]),
    )


def render_summary(proofs: list[dict], package: str, package_version: str, nu_version: str) -> str:
    """Render a compact human-readable proof summary."""
    lines = [
        f"## Lifecycle proofs for `{package}@{package_version}` on Nu `{nu_version}`",
        "",
        "| OS | Arch | Result | Commands |",
        "|---|---|---|---|",
    ]
    for proof in proofs:
        commands = ", ".join(proof.get("commands", [])) or "—"
        lines.append(
            f"| {proof['os']} | {proof['arch']} | {proof['result']} | {commands} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--nu-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--fail-on-failure", action="store_true")
    args = parser.parse_args(argv)

    try:
        proofs = load_proofs(args.artifacts)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proofs, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.summary is not None:
        args.summary.write_text(
            render_summary(proofs, args.package, args.package_version, args.nu_version),
            encoding="utf-8",
            newline="\n",
        )
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"proofs={json.dumps(proofs, separators=(',', ':'))}\n")

    failed = [proof for proof in proofs if proof["result"] != "passed"]
    print(f"collected {len(proofs)} proof(s); {len(failed)} failed")
    if args.fail_on_failure and failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
