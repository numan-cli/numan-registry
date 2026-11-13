#!/usr/bin/env python3.12
"""Unit checks for scripts/validate.py download/verify path (no network)."""

from __future__ import annotations

import base64
import importlib.util
import json
import jsonschema
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SCRIPT = Path(__file__).resolve().parent / "validate.py"
ROOT = SCRIPT.parent.parent
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))


def load_validate():
    spec = importlib.util.spec_from_file_location("validate_verify", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


VALIDATE = load_validate()


MINIMAL_INDEX = {
    "schema_version": 1,
    "updated_at": "2026-07-29T00:00:00Z",
    "packages": [],
}


class DownloadAndVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_missing_sha256_short_circuits(self):
        ok, msg = self.validate.download_and_verify("https://example.com/a.zip", "")
        self.assertFalse(ok)
        self.assertEqual(msg, "missing expected sha256")

    def test_rejects_file_scheme_without_urlopen(self):
        with mock.patch.object(self.validate, "http_opener") as http_opener:
            ok, msg = self.validate.download_and_verify(
                "file:///etc/passwd", "a" * 64
            )
        self.assertFalse(ok)
        self.assertIn("http(s)", msg)
        http_opener.assert_not_called()

    def test_rejects_custom_scheme_without_urlopen(self):
        with mock.patch.object(self.validate, "http_opener") as http_opener:
            ok, msg = self.validate.download_and_verify(
                "ftp://example.com/a.zip", "a" * 64
            )
        self.assertFalse(ok)
        self.assertIn("http(s)", msg)
        http_opener.assert_not_called()

    def test_https_url_reaches_urlopen(self):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"payload"

        with mock.patch.object(self.validate, "http_opener") as http_opener:
            http_opener.return_value.open.return_value = _Resp()
            ok, msg = self.validate.download_and_verify(
                "https://example.com/a.zip",
                # sha256 of b"payload"
                "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
            )
        http_opener.assert_called_once()
        self.assertTrue(ok)
        self.assertEqual(msg, "ok")


class ValidateMainHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_load_index_missing_file_returns_none(self):
        buf = StringIO()
        with redirect_stdout(buf):
            loaded = self.validate._load_index("/nonexistent/index.json")
        self.assertIsNone(loaded)
        self.assertIn("FAIL: could not load index", buf.getvalue())

    def test_validate_schema_step_records_failure(self):
        errors: list[str] = []
        with mock.patch.object(
            self.validate,
            "validate_schema",
            side_effect=RuntimeError("boom"),
        ):
            buf = StringIO()
            with redirect_stdout(buf):
                ok = self.validate._validate_schema_step({}, "schema.json", errors)
        self.assertFalse(ok)
        self.assertEqual(errors, ["schema"])
        self.assertIn("FAIL: schema validation: boom", buf.getvalue())

    def test_validate_lifecycle_step_appends_errors_and_provisional_ok(self):
        errors: list[str] = []
        with mock.patch.object(
            self.validate,
            "lifecycle_evidence_errors",
            return_value=["acme/pkg@1.0.0: bad evidence"],
        ):
            buf = StringIO()
            with redirect_stdout(buf):
                self.validate._validate_lifecycle_step(
                    MINIMAL_INDEX,
                    allow_missing=True,
                    errors=errors,
                )
        self.assertEqual(len(errors), 1)
        self.assertIn("lifecycle_evidence:", errors[0])
        self.assertNotIn("provisional lifecycle evidence", buf.getvalue())

        errors = []
        with mock.patch.object(
            self.validate,
            "lifecycle_evidence_errors",
            return_value=[],
        ):
            buf = StringIO()
            with redirect_stdout(buf):
                self.validate._validate_lifecycle_step(
                    MINIMAL_INDEX,
                    allow_missing=True,
                    errors=errors,
                )
        self.assertEqual(errors, [])
        self.assertIn(
            "OK: provisional lifecycle evidence is allowed for staging",
            buf.getvalue(),
        )

    def test_validate_schema_version_rejects_non_one(self):
        errors: list[str] = []
        buf = StringIO()
        with redirect_stdout(buf):
            self.validate._validate_schema_version({"schema_version": 2}, errors)
        self.assertEqual(errors, ["schema_version"])
        self.assertIn("schema_version must be 1", buf.getvalue())

    def test_verify_one_artifact_fixture_strict_vs_lenient(self):
        errors: list[str] = []
        buf = StringIO()
        with redirect_stdout(buf):
            self.validate._verify_one_artifact(
                "acme/pkg@1.0.0",
                "https://example.com/pkg.zip",
                "a" * 64,
                strict_artifacts=False,
                errors=errors,
            )
        self.assertEqual(errors, [])
        self.assertIn("fixture URL skipped", buf.getvalue())

        errors = []
        buf = StringIO()
        with redirect_stdout(buf):
            self.validate._verify_one_artifact(
                "acme/pkg@1.0.0",
                "https://example.com/pkg.zip",
                "a" * 64,
                strict_artifacts=True,
                errors=errors,
            )
        self.assertEqual(errors, ["artifact:acme/pkg@1.0.0"])

    def test_validate_signature_step_skips_when_requested(self):
        args = self.validate._parse_args(["--skip-signature"])
        errors: list[str] = []
        buf = StringIO()
        with redirect_stdout(buf):
            self.validate._validate_signature_step(args, b"canonical", errors)
        self.assertEqual(errors, [])
        self.assertIn("signature verification skipped", buf.getvalue())

    def test_validate_signature_step_key_id_mismatch(self):
        args = self.validate._parse_args([])
        with tempfile.TemporaryDirectory() as tmp:
            pub_path = Path(tmp) / "official.pub"
            pub_path.write_text(
                json.dumps({"key_id": "key-a", "public_key_b64": "cGxhY2Vob2xkZXI="}),
                encoding="utf-8",
            )
            sig_path = Path(tmp) / "index.json.sig"
            sig_path.write_text(
                json.dumps({"key_id": "key-b", "algorithm": "ed25519", "signature": "c2ln"}),
                encoding="utf-8",
            )
            args.pub = str(pub_path)
            args.sig = str(sig_path)
            errors: list[str] = []
            buf = StringIO()
            with redirect_stdout(buf):
                self.validate._validate_signature_step(args, b"canonical", errors)
        self.assertEqual(errors, ["signature"])
        self.assertIn("does not match public key", buf.getvalue())

    def test_verify_one_artifact_empty_url_is_noop(self):
        errors: list[str] = []
        buf = StringIO()
        with redirect_stdout(buf):
            self.validate._verify_one_artifact(
                "acme/pkg@1.0.0", "", "a" * 64, strict_artifacts=False, errors=errors
            )
        self.assertEqual(errors, [])
        self.assertEqual(buf.getvalue(), "")

    def test_verify_one_artifact_real_download_success(self):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"payload"

        errors: list[str] = []
        buf = StringIO()
        with mock.patch.object(self.validate, "http_opener") as http_opener:
            http_opener.return_value.open.return_value = _Resp()
            with redirect_stdout(buf):
                self.validate._verify_one_artifact(
                    "acme/pkg@1.0.0",
                    "https://cdn.example.org/a.zip",
                    "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
                    strict_artifacts=False,
                    errors=errors,
                )
        self.assertEqual(errors, [])
        self.assertIn("artifact digest verified", buf.getvalue())

    def test_main_schema_failure_skips_lifecycle_traversal(self):
        malformed = {
            "schema_version": 1,
            "updated_at": "2026-07-29T00:00:00Z",
            "packages": [None],
        }
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index_path.write_text(json.dumps(malformed), encoding="utf-8")
            argv = [
                "--index",
                str(index_path),
                "--schema",
                str(ROOT / "schemas" / "index-v1.json"),
                "--skip-signature",
                "--skip-artifacts",
            ]
            with mock.patch.object(
                self.validate,
                "lifecycle_evidence_errors",
            ) as lifecycle_errors:
                code = self.validate.main(argv)
            lifecycle_errors.assert_not_called()
            self.assertEqual(code, 1)


class CanonicalJsonAndKeyLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_canonical_json_numeric_fallback(self):
        self.assertEqual(self.validate.canonical_json(42), "42")
        self.assertEqual(self.validate.canonical_json(1.5), "1.5")

    def test_canonical_json_bool(self):
        self.assertEqual(self.validate.canonical_json(True), "true")
        self.assertEqual(self.validate.canonical_json(False), "false")

    def test_load_pub_key_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official.pub"
            path.write_text(json.dumps({"key_id": "abc"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.validate.load_pub_key(str(path))

    def test_load_pub_key_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official.pub"
            path.write_text(
                json.dumps({"key_id": "abc", "public_key_b64": "PLACEHOLDER"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                self.validate.load_pub_key(str(path))

    def test_load_pub_key_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official.pub"
            path.write_text(
                json.dumps({"key_id": "abc", "public_key_b64": "cGxhY2Vob2xkZXI="}),
                encoding="utf-8",
            )
            key_id, pub_b64 = self.validate.load_pub_key(str(path))
            self.assertEqual(key_id, "abc")
            self.assertEqual(pub_b64, "cGxhY2Vob2xkZXI=")

    def test_load_sig_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json.sig"
            path.write_text(json.dumps({"key_id": "abc"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.validate.load_sig(str(path))

    def test_load_sig_unsupported_algorithm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json.sig"
            path.write_text(
                json.dumps({"key_id": "abc", "algorithm": "rsa", "signature": "x"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                self.validate.load_sig(str(path))

    def test_load_sig_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json.sig"
            path.write_text(
                json.dumps(
                    {"key_id": "abc", "algorithm": "ed25519", "signature": "PLACEHOLDER"}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                self.validate.load_sig(str(path))

    def test_load_sig_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json.sig"
            path.write_text(
                json.dumps({"key_id": "abc", "algorithm": "ed25519", "signature": "c2ln"}),
                encoding="utf-8",
            )
            key_id, sig_b64 = self.validate.load_sig(str(path))
            self.assertEqual(key_id, "abc")
            self.assertEqual(sig_b64, "c2ln")


class VerifyEd25519Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_round_trip_succeeds(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        pub_bytes = public_key.public_bytes_raw()
        data = b"canonical bytes"
        signature = private_key.sign(data)
        self.validate.verify_ed25519(
            base64.b64encode(pub_bytes).decode(),
            base64.b64encode(signature).decode(),
            data,
        )

    def test_wrong_public_key_length_raises(self):
        with self.assertRaises(ValueError):
            self.validate.verify_ed25519(
                base64.b64encode(b"short").decode(),
                base64.b64encode(b"a" * 64).decode(),
                b"data",
            )

    def test_wrong_signature_length_raises(self):
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes_raw()
        with self.assertRaises(ValueError):
            self.validate.verify_ed25519(
                base64.b64encode(pub_bytes).decode(),
                base64.b64encode(b"short").decode(),
                b"data",
            )

    def test_tampered_data_fails_verification(self):
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes_raw()
        signature = private_key.sign(b"original")
        with self.assertRaises(InvalidSignature):
            self.validate.verify_ed25519(
                base64.b64encode(pub_bytes).decode(),
                base64.b64encode(signature).decode(),
                b"tampered",
            )


class LifecycleEvidenceErrorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_plugin_missing_verified_with_reports_error(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "type": "plugin",
                    "versions": [{"version": "1.0.0", "nu_version": "0.100.0"}],
                }
            ]
        }
        errors = self.validate.lifecycle_evidence_errors(index)
        self.assertEqual(len(errors), 1)
        self.assertIn("acme/pkg@1.0.0", errors[0])

    def test_non_activatable_version_skipped(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "type": "script",
                    "versions": [{"version": "1.0.0", "nu_version": "0.100.0"}],
                }
            ]
        }
        self.assertEqual(self.validate.lifecycle_evidence_errors(index), [])

    def test_allow_missing_skips_versions_without_evidence(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "type": "plugin",
                    "versions": [{"version": "1.0.0", "nu_version": "0.100.0"}],
                }
            ]
        }
        errors = self.validate.lifecycle_evidence_errors(index, allow_missing=True)
        self.assertEqual(errors, [])

    def test_valid_evidence_reports_no_error(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "type": "plugin",
                    "versions": [
                        {
                            "version": "1.0.0",
                            "nu_version": "0.100.0",
                            "verified_with": ["0.100.0"],
                        }
                    ],
                }
            ]
        }
        self.assertEqual(self.validate.lifecycle_evidence_errors(index), [])


class CollectArtifactUrlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_non_binary_artifact(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "artifact": {"kind": "archive", "url": "https://example.com/a", "sha256": "x"},
                        }
                    ],
                }
            ]
        }
        results = list(self.validate.collect_artifact_urls(index))
        self.assertEqual(results, [("acme/pkg@1.0.0", "https://example.com/a", "x")])

    def test_binary_artifact_yields_per_target(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "artifact": {
                                "kind": "binary",
                                "targets": {
                                    "linux": {"url": "https://example.com/linux", "sha256": "l"},
                                    "windows": {"url": "https://example.com/win", "sha256": "w"},
                                },
                            },
                        }
                    ],
                }
            ]
        }
        results = sorted(self.validate.collect_artifact_urls(index))
        self.assertEqual(
            results,
            [
                ("acme/pkg@1.0.0 (linux)", "https://example.com/linux", "l"),
                ("acme/pkg@1.0.0 (windows)", "https://example.com/win", "w"),
            ],
        )


class DownloadAndVerifyRemainingBranchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_read_exception_reports_download_failed(self):
        with mock.patch.object(self.validate, "http_opener") as http_opener:
            http_opener.return_value.open.side_effect = OSError("connection reset")
            ok, msg = self.validate.download_and_verify(
                "https://example.com/a.zip", "a" * 64
            )
        self.assertFalse(ok)
        self.assertIn("download failed", msg)

    def test_sha256_mismatch_reported(self):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"payload"

        with mock.patch.object(self.validate, "http_opener") as http_opener:
            http_opener.return_value.open.return_value = _Resp()
            ok, msg = self.validate.download_and_verify(
                "https://example.com/a.zip", "0" * 64
            )
        self.assertFalse(ok)
        self.assertIn("sha256 mismatch", msg)


class MainEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = VALIDATE

    def test_main_success_with_real_signature_and_fixture_artifact(self):
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes_raw()

        index = {
            "schema_version": 1,
            "updated_at": "2026-07-29T00:00:00Z",
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "description": "test package",
                    "repo": "https://example.com/acme/pkg",
                    "type": "script",
                    "tags": [],
                    "versions": [
                        {
                            "version": "1.0.0",
                            "nu_version": "0.100.0",
                            "artifact": {
                                "kind": "archive",
                                "url": "https://example.com/a.zip",
                                "sha256": "a" * 64,
                            },
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index_path = tmp_path / "index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")

            canonical = self.validate.canonical_json(index).encode("utf-8")
            signature = private_key.sign(canonical)

            pub_path = tmp_path / "official.pub"
            pub_path.write_text(
                json.dumps(
                    {
                        "key_id": "test-key",
                        "public_key_b64": base64.b64encode(pub_bytes).decode(),
                    }
                ),
                encoding="utf-8",
            )
            sig_path = tmp_path / "index.json.sig"
            sig_path.write_text(
                json.dumps(
                    {
                        "key_id": "test-key",
                        "algorithm": "ed25519",
                        "signature": base64.b64encode(signature).decode(),
                    }
                ),
                encoding="utf-8",
            )

            argv = [
                "--index",
                str(index_path),
                "--sig",
                str(sig_path),
                "--pub",
                str(pub_path),
                "--schema",
                str(ROOT / "schemas" / "index-v1.json"),
            ]
            buf = StringIO()
            with redirect_stdout(buf):
                code = self.validate.main(argv)
            output = buf.getvalue()
            self.assertEqual(code, 0, output)
            self.assertIn("Validation passed", output)
            self.assertIn("Ed25519 signature verified", output)
            self.assertIn("fixture URL skipped", output)


class ActivationKindSchemaTests(unittest.TestCase):
    """Lock the closed activation.kind set and its per-kind requirements."""

    SCHEMA = ROOT / "schemas" / "index-v1.json"

    def _index_with(self, activation):
        return {
            "schema_version": 1,
            "updated_at": "2026-07-29T00:00:00Z",
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "description": "d",
                    "repo": "https://example.com/repo",
                    "type": "module",
                    "tags": [],
                    "versions": [
                        {
                            "version": "1.0.0",
                            "nu_version": "*",
                            "artifact": {
                                "kind": "archive",
                                "url": "https://example.com/a.tar.gz",
                                "sha256": "a" * 64,
                            },
                            "activation": activation,
                        }
                    ],
                }
            ],
        }

    def test_rejects_unknown_activation_kind(self):
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATE.validate_schema(
                self._index_with({"kind": "nu-moduel"}), str(self.SCHEMA)
            )

    def test_accepts_each_closed_activation_kind(self):
        activations = [
            {"kind": "nu-module"},
            {"kind": "nu-overlay", "entry": "overlay.nu"},
            {
                "kind": "nu-hook",
                "bindings": [
                    {"id": "b", "event": "pre_prompt", "handler": "h.nu"}
                ],
            },
            {"kind": "nu-script", "entry_points": [{"name": "run", "path": "run.nu"}]},
            {
                "kind": "nu-completion",
                "targets": [{"command": "git", "path": "git.nu", "kind": "static"}],
            },
        ]
        for activation in activations:
            VALIDATE.validate_schema(self._index_with(activation), str(self.SCHEMA))

    def test_requires_kind_specific_block(self):
        for activation in ({"kind": "nu-hook"}, {"kind": "nu-overlay"}):
            with self.assertRaises(jsonschema.ValidationError):
                VALIDATE.validate_schema(self._index_with(activation), str(self.SCHEMA))


class LifecycleProofSchemaTests(unittest.TestCase):
    """Lock the optional per-platform lifecycle proof record."""

    SCHEMA = ROOT / "schemas" / "index-v1.json"

    def _index_with(self, proofs):
        return {
            "schema_version": 1,
            "updated_at": "2026-07-29T00:00:00Z",
            "packages": [
                {
                    "id": {"owner": "acme", "name": "pkg"},
                    "description": "d",
                    "repo": "https://example.com/repo",
                    "type": "module",
                    "tags": [],
                    "versions": [
                        {
                            "version": "1.0.0",
                            "nu_version": "*",
                            "artifact": {
                                "kind": "archive",
                                "url": "https://example.com/a.tar.gz",
                                "sha256": "a" * 64,
                            },
                            "proofs": proofs,
                        }
                    ],
                }
            ],
        }

    def test_accepts_minimal_and_full_proofs(self):
        proofs = [
            {
                "os": "windows",
                "arch": "x86_64",
                "nu_version": "0.114.1",
                "result": "passed",
                "timestamp": "2026-10-18T12:00:00Z",
            },
            {
                "os": "linux",
                "arch": "aarch64",
                "nu_version": "0.114.1",
                "result": "failed",
                "commands": ["install", "activate"],
                "timestamp": "2026-10-18T12:00:00.123+00:00",
                "evidence_url": "https://example.com/log",
            },
        ]
        VALIDATE.validate_schema(self._index_with(proofs), str(self.SCHEMA))

    def test_rejects_unknown_os(self):
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATE.validate_schema(
                self._index_with(
                    [
                        {
                            "os": "solaris",
                            "arch": "x86_64",
                            "nu_version": "0.114.1",
                            "result": "passed",
                            "timestamp": "2026-10-18T12:00:00Z",
                        }
                    ]
                ),
                str(self.SCHEMA),
            )

    def test_rejects_missing_required_proof_fields(self):
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATE.validate_schema(
                self._index_with(
                    [
                        {
                            "os": "linux",
                            "arch": "x86_64",
                            "nu_version": "0.114.1",
                            "result": "passed",
                        }
                    ]
                ),
                str(self.SCHEMA),
            )

    def test_rejects_malformed_timestamp_and_extra_fields(self):
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATE.validate_schema(
                self._index_with(
                    [
                        {
                            "os": "linux",
                            "arch": "x86_64",
                            "nu_version": "0.114.1",
                            "result": "passed",
                            "timestamp": "2026-10-18",
                        }
                    ]
                ),
                str(self.SCHEMA),
            )
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATE.validate_schema(
                self._index_with(
                    [
                        {
                            "os": "linux",
                            "arch": "x86_64",
                            "nu_version": "0.114.1",
                            "result": "passed",
                            "timestamp": "2026-10-18T12:00:00Z",
                            "unexpected": True,
                        }
                    ]
                ),
                str(self.SCHEMA),
            )


if __name__ == "__main__":
    unittest.main()
