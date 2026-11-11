#!/usr/bin/env python3
"""Sign a registry index with an Ed25519 private key.

This script is used by CI workflows. It accepts the private key as a base64
string or from a file. The private key is never logged or persisted beyond the
caller's responsibility.

Production signing (``--production``) additionally requires every activatable
package version to have a successful lifecycle proof covering the Nu version
range claimed by that version. Staging and local signing keep their existing
behaviour.
"""

import argparse
import base64
import json
import sys

from nu_version_constraint import matches_nu_constraint

PROOF_POLICY_SUMMARY = (
    "activatable = package.type == 'plugin' or version.activation present; "
    "claimed range = version.nu_version"
)


def package_label(package):
    package_id = package.get("id") if isinstance(package, dict) else None
    if isinstance(package_id, dict):
        owner = package_id.get("owner")
        name = package_id.get("name")
        if isinstance(owner, str) and isinstance(name, str):
            return f"{owner}/{name}"
    return "<unknown-package>"


def version_label(package, version):
    package_id = package_label(package)
    value = version.get("version") if isinstance(version, dict) else None
    return f"{package_id}@{value}" if isinstance(value, str) and value else f"{package_id}@<unknown>"


def activation_source(package, version):
    """Return the existing field that makes this version activatable, or None."""
    if package.get("type") == "plugin":
        return "package.type == 'plugin'"
    if "activation" not in version:
        return None
    activation = version.get("activation")
    if isinstance(activation, dict):
        kind = activation.get("kind")
        if isinstance(kind, str) and kind.strip():
            return f"version.activation.kind == {kind!r}"
    return "version.activation present"


def _proof_requirement(constraint):
    return (
        "add a proof with result='passed' and proof.nu_version satisfying "
        f"version.nu_version={constraint!r}"
    )


def _successful_proofs(proofs):
    return [
        proof
        for proof in proofs
        if isinstance(proof, dict) and proof.get("result") == "passed"
    ]


def _no_successful_proof_error(proofs, required):
    results = sorted(
        {
            repr(proof.get("result"))
            for proof in proofs
            if isinstance(proof, dict)
        }
    )
    result_text = ", ".join(results) if results else "no usable proof records"
    return (
        "version.proofs has no successful proof: all proof.result values are "
        f"{result_text}; {required}"
    )


def _proof_nu_match(proof, constraint):
    proof_nu = proof.get("nu_version")
    if not isinstance(proof_nu, str):
        return None, repr(proof_nu)
    try:
        if matches_nu_constraint(proof_nu, constraint):
            return proof_nu, None
    except ValueError as exc:
        return None, f"{proof_nu!r} ({exc})"
    return None, None


def _matching_proof_versions(successful, constraint):
    results = [_proof_nu_match(proof, constraint) for proof in successful]
    matching = [match for match, _ in results if match]
    unusable = [issue for _, issue in results if issue]
    return matching, unusable


def _no_matching_proof_error(constraint, successful, unusable):
    successful_versions = ", ".join(
        repr(proof.get("nu_version")) for proof in successful
    )
    detail = f"successful proof.nu_version values: {successful_versions}"
    if unusable:
        detail += f"; unusable values: {', '.join(unusable)}"
    return (
        "successful proofs exist but none match the claimed Nu range "
        f"version.nu_version={constraint!r}; {detail}"
    )


def proof_coverage_error(version):
    """Return why a version's proofs do not cover its Nu range, or None."""
    proofs = version.get("proofs")
    constraint = version.get("nu_version")
    required = _proof_requirement(constraint)

    if not isinstance(proofs, list) or not proofs:
        return f"no lifecycle proofs: version.proofs is absent or empty; {required}"

    successful = _successful_proofs(proofs)
    if not successful:
        return _no_successful_proof_error(proofs, required)

    matching, unusable = _matching_proof_versions(successful, constraint)
    if matching:
        return None

    return _no_matching_proof_error(constraint, successful, unusable)


def _version_proof_error(package, version):
    if not isinstance(version, dict):
        return 0, None
    source = activation_source(package, version)
    if source is None:
        return 0, None
    error = proof_coverage_error(version)
    if error is None:
        return 1, None
    return 1, (
        f"{version_label(package, version)}: activatable from "
        f"{source}; {error}"
    )


def _package_proof_errors(package):
    if not isinstance(package, dict):
        return 0, []
    versions = package.get("versions")
    if not isinstance(versions, list):
        return 0, []
    results = [_version_proof_error(package, version) for version in versions]
    checked = sum(count for count, _ in results)
    errors = [error for _, error in results if error]
    return checked, errors


def lifecycle_proof_errors(index):
    """Return (errors, activatable_count) for production proof coverage."""
    packages = index.get("packages")
    if not isinstance(packages, list):
        return ["index.packages is not a list"], 0
    results = [_package_proof_errors(package) for package in packages]
    checked = sum(count for count, _ in results)
    errors = [error for _, package_errors in results for error in package_errors]
    return errors, checked


def sign_index(index_bytes, key_bytes):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise RuntimeError(
            "The 'cryptography' package is required for signing. "
            "Install it with: pip install cryptography"
        ) from exc

    private_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    signature = private_key.sign(index_bytes)
    return signature


def canonical_json(value):
    if isinstance(value, dict):
        items = sorted((canonical_json(k), canonical_json(v)) for k, v in value.items())
        return "{" + ",".join(f"{k}:{v}" for k, v in items) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser(description="Sign a Numan registry index")
    parser.add_argument("--index", required=True)
    parser.add_argument("--sig", required=True)
    parser.add_argument("--key-id", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--priv-b64", help="Base64-encoded Ed25519 private key (32 bytes)")
    group.add_argument("--priv-file", help="Path to a raw 32-byte Ed25519 private key file")
    parser.add_argument(
        "--production",
        action="store_true",
        help=(
            "Require a successful lifecycle proof covering version.nu_version "
            "for every activatable package version"
        ),
    )
    args = parser.parse_args()

    if args.priv_b64:
        key_bytes = base64.b64decode(args.priv_b64)
    else:
        with open(args.priv_file, "rb") as f:
            key_bytes = f.read()

    if len(key_bytes) != 32:
        print(f"Private key must be 32 bytes, got {len(key_bytes)}", file=sys.stderr)
        return 1

    with open(args.index, "r", encoding="utf-8") as f:
        raw = f.read()
    parsed = json.loads(raw)

    if args.production:
        print(f"Lifecycle proof gate: {PROOF_POLICY_SUMMARY}", file=sys.stderr)
        proof_errors, checked = lifecycle_proof_errors(parsed)
        if proof_errors:
            for error in proof_errors:
                print(f"FAIL: {error}", file=sys.stderr)
            print(
                "Refusing to sign: lifecycle proof gate rejected "
                f"{len(proof_errors)} of {checked} activatable version(s). "
                "Add matching version.proofs records.",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK: lifecycle proof gate passed for {checked} activatable version(s)",
            file=sys.stderr,
        )

    canonical = canonical_json(parsed).encode("utf-8")

    signature = sign_index(canonical, key_bytes)
    envelope = {
        "key_id": args.key_id,
        "algorithm": "ed25519",
        "signature": base64.b64encode(signature).decode(),
    }

    with open(args.sig, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)
        f.write("\n")

    print(f"Signed {args.index} -> {args.sig} with key_id {args.key_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
