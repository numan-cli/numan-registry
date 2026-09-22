#!/usr/bin/env python3
"""Unit checks for source provenance passthrough in add-package.py.

No network: tests copy_source_field only.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "add-package.py"


def load_add_package():
    scripts_dir = str(SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("add_package", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class CopySourceFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ap = load_add_package()

    def test_copies_source_when_present(self):
        version_entry = {"version": "1.0.0", "nu_version": ">=0.113.0 <0.114.0"}
        spec = {
            "source": {
                "git": "https://github.com/example/nu_plugin_x",
                "rev": "v1.0.0",
                "cargo_name": "nu_plugin_x",
            }
        }
        self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(
            version_entry["source"],
            {
                "git": "https://github.com/example/nu_plugin_x",
                "rev": "v1.0.0",
                "cargo_name": "nu_plugin_x",
            },
        )

    def test_copies_optional_cargo_lock_sha256(self):
        version_entry = {}
        spec = {
            "source": {
                "git": "https://github.com/example/nu_plugin_x",
                "rev": "v1.0.0",
                "cargo_name": "nu_plugin_x",
                "cargo_lock_sha256": "a" * 64,
            }
        }
        self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(version_entry["source"]["cargo_lock_sha256"], "a" * 64)


    def test_copies_optional_upstream(self):
        version_entry = {}
        spec = {
            "source": {
                "git": "https://github.com/numan-maintained/nu_plugin_x",
                "rev": "a" * 40,
                "cargo_name": "nu_plugin_x",
                "upstream": "https://github.com/original-author/nu_plugin_x",
            }
        }
        self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(
            version_entry["source"]["upstream"],
            "https://github.com/original-author/nu_plugin_x",
        )

    def test_omits_upstream_when_absent(self):
        version_entry = {}
        spec = {
            "source": {
                "git": "https://github.com/owner/nu_plugin_x",
                "rev": "v1.0.0",
                "cargo_name": "nu_plugin_x",
            }
        }
        self.ap.copy_source_field(spec, version_entry)
        self.assertNotIn("upstream", version_entry["source"])

    def test_noop_when_source_absent(self):
        version_entry = {"version": "1.0.0"}
        self.ap.copy_source_field({}, version_entry)
        self.assertNotIn("source", version_entry)

    def test_rejects_plugin_source_without_cargo_name(self):
        """Plugin specs must still carry source.cargo_name."""
        version_entry = {}
        spec = {
            "type": "plugin",
            "source": {"git": "https://github.com/example/x", "rev": "v1"},
        }
        with self.assertRaises(SystemExit) as ctx:
            self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(ctx.exception.code, 1)

    def test_rejects_source_missing_rev(self):
        """All source specs require an immutable git revision."""
        version_entry = {}
        spec = {"type": "module", "source": {"git": "https://github.com/example/x"}}
        with self.assertRaises(SystemExit) as ctx:
            self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(ctx.exception.code, 1)

    def test_copies_non_plugin_source_without_cargo_name(self):
        """Non-plugin sources may omit cargo_name and keep git/rev."""
        version_entry = {}
        spec = {
            "type": "module",
            "source": {"git": "https://github.com/example/x", "rev": "a" * 40},
        }
        self.ap.copy_source_field(spec, version_entry)
        self.assertEqual(
            version_entry["source"],
            {"git": "https://github.com/example/x", "rev": "a" * 40},
        )


class BuildVersionEntryEvidenceTierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ap = load_add_package()

    def test_sets_evidence_tier_when_deferral_reason_given(self):
        spec = {
            "version": "1.0.0",
            "nu_version": "*",
            "artifact": {
                "kind": "binary",
                "targets": {
                    "x86_64-unknown-linux-gnu": {
                        "url": "https://example.invalid/a.tar.gz",
                        "executable_path": "p",
                    }
                },
            },
        }
        with mock.patch.object(self.ap, "download_and_hash", return_value="a" * 64):
            version_entry = self.ap.build_version_entry(
                spec, deferral_reason="requires cloud credentials"
            )
        self.assertEqual(version_entry["evidence_tier"], "provisional")
        self.assertEqual(version_entry["deferral_reason"], "requires cloud credentials")

    def test_omits_evidence_tier_when_no_deferral_reason(self):
        spec = {
            "version": "1.0.0",
            "nu_version": "*",
            "artifact": {
                "kind": "binary",
                "targets": {
                    "x86_64-unknown-linux-gnu": {
                        "url": "https://example.invalid/a.tar.gz",
                        "executable_path": "p",
                    }
                },
            },
        }
        with mock.patch.object(self.ap, "download_and_hash", return_value="a" * 64):
            version_entry = self.ap.build_version_entry(spec)
        self.assertNotIn("evidence_tier", version_entry)
        self.assertNotIn("deferral_reason", version_entry)


class SchemaProvisionalTierTests(unittest.TestCase):
    """Confirm the schema itself rejects a provisional entry missing deferral_reason."""

    @classmethod
    def setUpClass(cls) -> None:
        import json as _json

        try:
            import jsonschema

            cls.jsonschema = jsonschema
        except ImportError:
            cls.jsonschema = None
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "index-v1.json"
        cls.schema = _json.loads(schema_path.read_text(encoding="utf-8"))

    def _index(self, version_entry):
        return {
            "schema_version": 1,
            "updated_at": "2026-01-01T00:00:00Z",
            "packages": [
                {
                    "id": {"owner": "o", "name": "p"},
                    "description": "p",
                    "repo": "https://example.invalid/o/p",
                    "type": "plugin",
                    "tags": [],
                    "versions": [version_entry],
                }
            ],
        }

    def test_provisional_without_deferral_reason_is_rejected(self):
        if self.jsonschema is None:
            self.skipTest("jsonschema not installed")
        index = self._index(
            {
                "version": "1.0.0",
                "nu_version": "*",
                "evidence_tier": "provisional",
                "artifact": {"kind": "binary", "targets": {}},
            }
        )
        with self.assertRaises(self.jsonschema.ValidationError):
            self.jsonschema.validate(index, self.schema)

    def test_provisional_with_deferral_reason_is_accepted(self):
        if self.jsonschema is None:
            self.skipTest("jsonschema not installed")
        index = self._index(
            {
                "version": "1.0.0",
                "nu_version": "*",
                "evidence_tier": "provisional",
                "deferral_reason": "requires cloud credentials",
                "artifact": {"kind": "binary", "targets": {}},
            }
        )
        self.jsonschema.validate(index, self.schema)


class SchemaSourceCargoNameTests(unittest.TestCase):
    """Confirm the schema requires source.cargo_name only for plugin packages."""

    @classmethod
    def setUpClass(cls) -> None:
        import json as _json

        try:
            import jsonschema

            cls.jsonschema = jsonschema
        except ImportError:
            cls.jsonschema = None
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "index-v1.json"
        cls.schema = _json.loads(schema_path.read_text(encoding="utf-8"))

    def _index(self, pkg_type, version_entry):
        """Wrap a version entry in a minimal single-package index."""
        return {
            "schema_version": 1,
            "updated_at": "2026-01-01T00:00:00Z",
            "packages": [
                {
                    "id": {"owner": "o", "name": "p"},
                    "description": "p",
                    "repo": "https://example.invalid/o/p",
                    "type": pkg_type,
                    "tags": [],
                    "versions": [version_entry],
                }
            ],
        }

    def _version(self, source):
        """Build a minimal archive version entry carrying the given source."""
        return {
            "version": "1.0.0",
            "nu_version": "*",
            "artifact": {"kind": "archive", "url": "https://example.invalid/a.tar.gz"},
            "source": source,
        }

    def test_plugin_source_without_cargo_name_is_rejected(self):
        """Plugin source records must carry cargo_name."""
        if self.jsonschema is None:
            self.skipTest("jsonschema not installed")
        index = self._index(
            "plugin", self._version({"git": "https://example.invalid/o/p", "rev": "a" * 40})
        )
        with self.assertRaises(self.jsonschema.ValidationError):
            self.jsonschema.validate(index, self.schema)

    def test_plugin_source_with_cargo_name_is_accepted(self):
        """Plugin source records with cargo_name pass the schema."""
        if self.jsonschema is None:
            self.skipTest("jsonschema not installed")
        index = self._index(
            "plugin",
            self._version(
                {
                    "git": "https://example.invalid/o/p",
                    "rev": "a" * 40,
                    "cargo_name": "nu_plugin_p",
                }
            ),
        )
        self.jsonschema.validate(index, self.schema)

    def test_non_plugin_source_without_cargo_name_is_accepted(self):
        """Module/script sources may omit cargo_name and keep git/rev."""
        if self.jsonschema is None:
            self.skipTest("jsonschema not installed")
        for pkg_type in ("module", "script", "completion"):
            index = self._index(
                pkg_type,
                self._version({"git": "https://example.invalid/o/p", "rev": "a" * 40}),
            )
            self.jsonschema.validate(index, self.schema)


class BuildVersionEntryProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ap = load_add_package()

    def test_passes_through_provenance_when_present(self):
        spec = {
            "version": "0.0.0-snapshot.20260809.5a1ca2a",
            "nu_version": ">=0.114.0 <0.115.0",
            "provenance": "commit-snapshot",
            "artifact": {
                "kind": "binary",
                "targets": {
                    "x86_64-unknown-linux-gnu": {
                        "url": "https://example.invalid/a.tar.gz",
                        "executable_path": "nu_plugin_plot",
                    }
                },
            },
        }
        with mock.patch.object(self.ap, "download_and_hash", return_value="a" * 64):
            version_entry = self.ap.build_version_entry(spec)
        self.assertEqual(version_entry["provenance"], "commit-snapshot")

    def test_omits_provenance_when_absent(self):
        spec = {
            "version": "1.0.0",
            "nu_version": "*",
            "artifact": {
                "kind": "binary",
                "targets": {
                    "x86_64-unknown-linux-gnu": {
                        "url": "https://example.invalid/a.tar.gz",
                        "executable_path": "p",
                    }
                },
            },
        }
        with mock.patch.object(self.ap, "download_and_hash", return_value="a" * 64):
            version_entry = self.ap.build_version_entry(spec)
        self.assertNotIn("provenance", version_entry)

    def test_rejects_unsupported_provenance_marker(self):
        spec = {
            "owner": "o",
            "name": "p",
            "description": "p",
            "repo": "https://github.com/o/p",
            "type": "plugin",
            "tags": [],
            "version": "1.0.0",
            "nu_version": ">=0.114.0 <0.115.0",
            "verified_with": ["0.114.1"],
            "artifact": {"kind": "binary", "targets": {}},
            "provenance": "hand-wavy",
        }
        with self.assertRaises(SystemExit) as ctx:
            self.ap.validate_spec(spec)
        self.assertEqual(ctx.exception.code, 1)

    def test_rejects_commit_snapshot_without_source(self):
        spec = {
            "owner": "o",
            "name": "p",
            "description": "p",
            "repo": "https://github.com/o/p",
            "type": "plugin",
            "tags": [],
            "version": "0.0.0-snapshot.20260809.5a1ca2a",
            "nu_version": ">=0.114.0 <0.115.0",
            "verified_with": ["0.114.1"],
            "artifact": {"kind": "binary", "targets": {}},
            "provenance": "commit-snapshot",
        }
        with self.assertRaises(SystemExit) as ctx:
            self.ap.validate_spec(spec)
        self.assertEqual(ctx.exception.code, 1)

    def test_accepts_commit_snapshot_with_source_rev(self):
        spec = {
            "owner": "o",
            "name": "p",
            "description": "p",
            "repo": "https://github.com/o/p",
            "type": "plugin",
            "tags": [],
            "version": "0.0.0-snapshot.20260809.5a1ca2a",
            "nu_version": ">=0.114.0 <0.115.0",
            "verified_with": ["0.114.1"],
            "artifact": {"kind": "binary", "targets": {}},
            "provenance": "commit-snapshot",
            "source": {
                "git": "https://github.com/o/p",
                "rev": "5a1ca2a5ceba60108a4ca6d45ec18d213abb5227",
                "cargo_name": "p",
            },
        }
        self.ap.validate_spec(spec)

    def test_rejects_commit_snapshot_with_non_object_source(self):
        spec = {
            "owner": "o",
            "name": "p",
            "description": "p",
            "repo": "https://github.com/o/p",
            "type": "plugin",
            "tags": [],
            "version": "0.0.0-snapshot.20260809.5a1ca2a",
            "nu_version": ">=0.114.0 <0.115.0",
            "verified_with": ["0.114.1"],
            "artifact": {"kind": "binary", "targets": {}},
            "provenance": "commit-snapshot",
            "source": "5a1ca2a5ceba60108a4ca6d45ec18d213abb5227",
        }
        with self.assertRaises(SystemExit) as ctx:
            self.ap.validate_spec(spec)
        self.assertEqual(ctx.exception.code, 1)

    def test_rejects_commit_snapshot_with_branch_name_as_rev(self):
        spec = {
            "owner": "o",
            "name": "p",
            "description": "p",
            "repo": "https://github.com/o/p",
            "type": "plugin",
            "tags": [],
            "version": "0.0.0-snapshot.20260809.5a1ca2a",
            "nu_version": ">=0.114.0 <0.115.0",
            "verified_with": ["0.114.1"],
            "artifact": {"kind": "binary", "targets": {}},
            "provenance": "commit-snapshot",
            "source": {
                "git": "https://github.com/o/p",
                "rev": "main",
                "cargo_name": "p",
            },
        }
        with self.assertRaises(SystemExit) as ctx:
            self.ap.validate_spec(spec)
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
