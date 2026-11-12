#!/usr/bin/env python3
"""Unit checks for scripts/ci-sign.py (real crypto round trip, no network)."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SCRIPT = Path(__file__).resolve().parent / "ci-sign.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))


def load_ci_sign():
    spec = importlib.util.spec_from_file_location("ci_sign", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CI_SIGN = load_ci_sign()



class CanonicalJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci_sign = CI_SIGN

    def test_sorts_dict_keys(self):
        self.assertEqual(self.ci_sign.canonical_json({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_list_preserves_order(self):
        self.assertEqual(self.ci_sign.canonical_json([3, 1, 2]), "[3,1,2]")

    def test_bool_lowercase(self):
        self.assertEqual(self.ci_sign.canonical_json(True), "true")
        self.assertEqual(self.ci_sign.canonical_json(False), "false")

    def test_none_is_null(self):
        self.assertEqual(self.ci_sign.canonical_json(None), "null")

    def test_nested_structures_deterministic(self):
        value = {"z": [1, {"y": 2, "x": 3}], "a": "hi"}
        first = self.ci_sign.canonical_json(value)
        second = self.ci_sign.canonical_json(value)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith('{"a":"hi"'))


class SignIndexRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci_sign = CI_SIGN

    def test_sign_then_verify(self):
        private_key = Ed25519PrivateKey.generate()
        key_bytes = private_key.private_bytes_raw()
        public_key = private_key.public_key()
        data = b'{"packages":[]}'
        signature = self.ci_sign.sign_index(data, key_bytes)
        public_key.verify(signature, data)

    def test_verify_fails_on_tampered_data(self):
        private_key = Ed25519PrivateKey.generate()
        key_bytes = private_key.private_bytes_raw()
        public_key = private_key.public_key()
        signature = self.ci_sign.sign_index(b"original", key_bytes)
        with self.assertRaises(InvalidSignature):
            public_key.verify(signature, b"tampered")


class MainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci_sign = CI_SIGN

    def test_main_writes_valid_signature(self):
        private_key = Ed25519PrivateKey.generate()
        key_bytes = private_key.private_bytes_raw()
        public_key = private_key.public_key()
        priv_b64 = base64.b64encode(key_bytes).decode()

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            sig_path = Path(tmp) / "index.json.sig"
            index_path.write_text(json.dumps({"b": 1, "a": 2}), encoding="utf-8")

            argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                "test-key",
                "--priv-b64",
                priv_b64,
            ]
            with patch.object(sys, "argv", argv):
                rc = self.ci_sign.main()
            self.assertEqual(rc, 0)

            envelope = json.loads(sig_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["key_id"], "test-key")
            self.assertEqual(envelope["algorithm"], "ed25519")
            signature = base64.b64decode(envelope["signature"])
            canonical = self.ci_sign.canonical_json({"a": 2, "b": 1}).encode("utf-8")
            public_key.verify(signature, canonical)

    def test_main_rejects_wrong_length_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            sig_path = Path(tmp) / "index.json.sig"
            index_path.write_text("{}", encoding="utf-8")
            short_b64 = base64.b64encode(b"short").decode()
            argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                "test-key",
                "--priv-b64",
                short_b64,
            ]
            with patch.object(sys, "argv", argv):
                rc = self.ci_sign.main()
            self.assertEqual(rc, 1)
            self.assertFalse(sig_path.exists())

    def test_main_reads_key_from_file(self):
        private_key = Ed25519PrivateKey.generate()
        key_bytes = private_key.private_bytes_raw()

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            sig_path = Path(tmp) / "index.json.sig"
            key_path = Path(tmp) / "priv.key"
            index_path.write_text("{}", encoding="utf-8")
            key_path.write_bytes(key_bytes)

            argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                "file-key",
                "--priv-file",
                str(key_path),
            ]
            with patch.object(sys, "argv", argv):
                rc = self.ci_sign.main()
            self.assertEqual(rc, 0)
            envelope = json.loads(sig_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["key_id"], "file-key")


class ProductionLifecycleProofGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci_sign = CI_SIGN

    def _index(self, package):
        return {
            "schema_version": 1,
            "updated_at": "2026-10-18T00:00:00Z",
            "packages": [package],
        }

    def _package(
        self,
        *,
        package_type="plugin",
        activation=None,
        proofs=None,
        constraint=">=0.113.0 <0.114.0",
    ):
        version = {
            "version": "1.0.0",
            "nu_version": constraint,
            "verified_with": ["0.113.1"],
            "artifact": {
                "kind": "archive",
                "url": "https://example.com/pkg.zip",
                "sha256": "a" * 64,
            },
        }
        if activation is not None:
            version["activation"] = activation
        if proofs is not None:
            version["proofs"] = proofs
        return {
            "id": {"owner": "acme", "name": "pkg"},
            "description": "fixture",
            "repo": "https://example.com/acme/pkg",
            "type": package_type,
            "tags": [package_type],
            "versions": [version],
        }

    def _proof(
        self,
        *,
        nu_version="0.113.1",
        result="passed",
        commands=("install", "activate", "doctor"),
    ):
        proof = {
            "os": "linux",
            "arch": "x86_64",
            "nu_version": nu_version,
            "result": result,
            "timestamp": "2026-10-18T12:00:00Z",
        }
        if commands is not None:
            proof["commands"] = list(commands)
        return proof

    def _run(self, index, *, production=True):
        private_key = Ed25519PrivateKey.generate()
        priv_b64 = base64.b64encode(private_key.private_bytes_raw()).decode()

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            sig_path = Path(tmp) / "index.json.sig"
            index_path.write_text(json.dumps(index), encoding="utf-8")

            argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                "test-key",
                "--priv-b64",
                priv_b64,
            ]
            if production:
                argv.append("--production")

            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.object(sys, "argv", argv),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                rc = self.ci_sign.main()
            return rc, sig_path.exists(), stdout.getvalue(), stderr.getvalue()

    def test_rejects_explicitly_activated_package_with_no_proofs(self):
        package = self._package(
            package_type="module",
            activation={"kind": "nu-module", "import": "all"},
        )
        rc, signed, _stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 1)
        self.assertFalse(signed)
        self.assertIn("acme/pkg@1.0.0", stderr)
        self.assertIn("version.activation.kind == 'nu-module'", stderr)
        self.assertIn("no lifecycle proofs", stderr)
        self.assertIn("version.proofs is absent or empty", stderr)

    def test_rejects_activatable_package_with_only_failed_proofs(self):
        package = self._package(proofs=[self._proof(result="failed")])
        rc, signed, _stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 1)
        self.assertFalse(signed)
        self.assertIn("package.type == 'plugin'", stderr)
        self.assertIn("no successful proof", stderr)
        self.assertIn("'failed'", stderr)

    def test_rejects_passed_proof_without_usable_commands(self):
        for commands in (None, [], ["install", "  "]):
            with self.subTest(commands=commands):
                package = self._package(
                    proofs=[self._proof(commands=commands)]
                )
                rc, signed, _stdout, stderr = self._run(self._index(package))

                self.assertEqual(rc, 1)
                self.assertFalse(signed)
                self.assertIn("no usable successful proof", stderr)
                self.assertIn("at least one non-empty command", stderr)

    def test_legacy_failed_proof_without_commands_does_not_block_valid_proof(self):
        package = self._package(
            proofs=[
                self._proof(result="failed", commands=None),
                self._proof(),
            ]
        )
        rc, signed, _stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 0)
        self.assertTrue(signed)
        self.assertIn("lifecycle proof gate passed for 1", stderr)

    def test_rejects_successful_proof_outside_claimed_range(self):
        package = self._package(proofs=[self._proof(nu_version="0.114.1")])
        rc, signed, _stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 1)
        self.assertFalse(signed)
        self.assertIn("none match the claimed Nu range", stderr)
        self.assertIn("version.nu_version='>=0.113.0 <0.114.0'", stderr)
        self.assertIn("'0.114.1'", stderr)

    def test_signs_activatable_package_with_matching_successful_proof(self):
        package = self._package(proofs=[self._proof(nu_version="0.113.1")])
        rc, signed, stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 0)
        self.assertTrue(signed)
        self.assertIn("lifecycle proof gate passed for 1", stderr)
        self.assertIn("Signed", stdout)

    def test_install_only_package_signs_without_proofs(self):
        package = self._package(package_type="script")
        rc, signed, stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 0)
        self.assertTrue(signed)
        self.assertIn("lifecycle proof gate passed for 0", stderr)
        self.assertIn("Signed", stdout)

    def test_yanked_version_is_not_checked_for_proofs(self):
        package = self._package(proofs=[])
        package["versions"][0]["yanked"] = {
            "reason_code": "nu-parser-incompatible",
            "evidence_url": "https://example.com/evidence.md",
        }
        rc, signed, _stdout, stderr = self._run(self._index(package))

        self.assertEqual(rc, 0)
        self.assertTrue(signed)
        self.assertIn("lifecycle proof gate passed for 0", stderr)

    def test_non_production_signing_is_unchanged(self):
        package = self._package()
        rc, signed, stdout, stderr = self._run(self._index(package), production=False)

        self.assertEqual(rc, 0)
        self.assertTrue(signed)
        self.assertNotIn("Lifecycle proof gate", stderr)
        self.assertIn("Signed", stdout)

    def test_allow_missing_proofs_flag_is_rejected(self):
        package = self._package()
        private_key = Ed25519PrivateKey.generate()
        priv_b64 = base64.b64encode(private_key.private_bytes_raw()).decode()

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            sig_path = Path(tmp) / "index.json.sig"
            index_path.write_text(json.dumps(self._index(package)), encoding="utf-8")
            argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                "test-key",
                "--priv-b64",
                priv_b64,
                "--production",
                "--allow-missing-proofs",
            ]
            with (
                patch.object(sys, "argv", argv),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                self.ci_sign.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(sig_path.exists())


class SignedIndexLifecycleProofRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.add_package = load_script(
            "add_package_signed_roundtrip", SCRIPT.parent / "add-package.py"
        )
        cls.validate = load_script(
            "validate_signed_roundtrip", SCRIPT.parent / "validate.py"
        )

    def test_lifecycle_proofs_survive_intake_signing_and_verification(self):
        proof = {
            "os": "windows",
            "arch": "x86_64",
            "nu_version": "0.113.1",
            "result": "passed",
            "commands": [
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
            ],
            "timestamp": "2026-10-18T12:00:00Z",
            "evidence_url": "https://example.com/evidence/proof-plugin.log",
        }
        spec = {
            "owner": "acme",
            "name": "proof-plugin",
            "description": "fixture",
            "repo": "https://example.com/acme/proof-plugin",
            "type": "plugin",
            "tags": ["plugin"],
            "version": "1.0.0",
            "nu_version": ">=0.113.0 <0.114.0",
            "verified_with": ["0.113.1"],
            "proofs": [proof],
            "source": {
                "git": "https://example.com/acme/proof-plugin",
                "rev": "v1.0.0",
                "cargo_name": "nu_plugin_proof",
            },
            "artifact": {
                "kind": "binary",
                "targets": {
                    "x86_64-unknown-linux-gnu": {
                        "url": "https://example.com/proof-plugin.tar.gz",
                        "executable_path": "nu_plugin_proof",
                    }
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            spec_path = tmp_path / "spec.json"
            index_path = tmp_path / "index.json"
            sig_path = tmp_path / "index.json.sig"
            pub_path = tmp_path / "official.pub"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "updated_at": "2026-10-18T00:00:00Z",
                        "packages": [],
                    }
                ),
                encoding="utf-8",
            )

            intake_argv = [
                "add-package.py",
                "--spec",
                str(spec_path),
                "--write",
                "--index",
                str(index_path),
            ]
            with (
                patch.object(sys, "argv", intake_argv),
                patch.object(
                    self.add_package, "download_and_hash", return_value="a" * 64
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                self.assertEqual(self.add_package.main(), 0)

            intake_index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(
                intake_index["packages"][0]["versions"][0]["proofs"], [proof]
            )

            private_key = Ed25519PrivateKey.generate()
            key_id = "test-key"
            sign_argv = [
                "ci-sign.py",
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--key-id",
                key_id,
                "--priv-b64",
                base64.b64encode(private_key.private_bytes_raw()).decode(),
                "--production",
            ]
            with (
                patch.object(sys, "argv", sign_argv),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                self.assertEqual(CI_SIGN.main(), 0)

            pub_path.write_text(
                json.dumps(
                    {
                        "key_id": key_id,
                        "public_key_b64": base64.b64encode(
                            private_key.public_key().public_bytes_raw()
                        ).decode(),
                    }
                ),
                encoding="utf-8",
            )

            verify_argv = [
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--pub",
                str(pub_path),
                "--schema",
                str(SCRIPT.parent.parent / "schemas" / "index-v1.json"),
                "--skip-artifacts",
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(self.validate.main(verify_argv), 0, output.getvalue())
            self.assertIn("schema validation passed", output.getvalue())
            self.assertIn("Ed25519 signature verified", output.getvalue())

            verified_index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(
                verified_index["packages"][0]["versions"][0]["proofs"], [proof]
            )
            canonical = CI_SIGN.canonical_json(verified_index).encode("utf-8")
            self.assertEqual(
                canonical, self.validate.canonical_json(verified_index).encode("utf-8")
            )
            self.assertIn(b'"proofs"', canonical)
            self.assertIn(CI_SIGN.canonical_json(proof).encode("utf-8"), canonical)

            tampered = json.loads(index_path.read_text(encoding="utf-8"))
            tampered["packages"][0]["versions"][0]["proofs"][0][
                "result"
            ] = "failed"
            tampered_path = tmp_path / "tampered-index.json"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            tampered_output = StringIO()
            with redirect_stdout(tampered_output):
                tampered_code = self.validate.main(
                    [
                        "--index",
                        str(tampered_path),
                        "--sig",
                        str(sig_path),
                        "--pub",
                        str(pub_path),
                        "--schema",
                        str(SCRIPT.parent.parent / "schemas" / "index-v1.json"),
                        "--skip-artifacts",
                    ]
                )
            self.assertEqual(tampered_code, 1)
            self.assertIn("signature verification", tampered_output.getvalue())


if __name__ == "__main__":
    unittest.main()
