#!/usr/bin/env python3.12
"""Unit checks for scripts/lint_packages.py (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "lint_packages.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))


def load_lint():
    spec = importlib.util.spec_from_file_location("lint_packages", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base_package(**overrides):
    pkg = {
        "id": {"owner": "acme", "name": "nu_plugin_demo"},
        "description": "demo",
        "repo": "https://github.com/acme/nu_plugin_demo",
        "type": "plugin",
        "tags": ["plugin"],
        "versions": [
            {
                "version": "1.0.0",
                "nu_version": ">=0.113.0 <0.114.0",
                "verified_with": ["0.113.1"],
                "artifact": {
                    "kind": "binary",
                    "targets": {
                        "x86_64-unknown-linux-gnu": {
                            "url": "https://example.com/demo.tar.gz",
                            "sha256": "a" * 64,
                            "executable_path": "nu_plugin_demo",
                        }
                    },
                },
                "source": {
                    "git": "https://github.com/acme/nu_plugin_demo",
                    "rev": "v1.0.0",
                    "cargo_name": "nu_plugin_demo",
                },
            }
        ],
    }
    pkg.update(overrides)
    return pkg


class TestValidateArtifactUrl(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_missing_url_binary_wording(self):
        errors: list[str] = []
        what = "target 'x86_64-unknown-linux-gnu'"
        self.lint._validate_artifact_url(
            "", errors, what=what, what_url=f"{what} url", label="p@1"
        )
        self.assertEqual(errors, ["p@1: target 'x86_64-unknown-linux-gnu' missing url"])

    def test_missing_url_archive_wording(self):
        errors: list[str] = []
        self.lint._validate_artifact_url(
            "", errors, what="archive artifact", what_url="archive url", label="p@1"
        )
        self.assertEqual(errors, ["p@1: archive artifact missing url"])

    def test_unsupported_suffix_binary_wording(self):
        errors: list[str] = []
        what = "target 'x86_64-unknown-linux-gnu'"
        self.lint._validate_artifact_url(
            "https://x/a.rar", errors, what=what, what_url=f"{what} url", label="p@1"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("target 'x86_64-unknown-linux-gnu' url has unsupported archive suffix", errors[0])

    def test_unsupported_suffix_archive_wording(self):
        errors: list[str] = []
        self.lint._validate_artifact_url(
            "https://x/a.rar", errors, what="archive artifact", what_url="archive url", label="p@1"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("archive url has unsupported archive suffix", errors[0])

    def test_valid_url_no_error(self):
        errors: list[str] = []
        self.lint._validate_artifact_url(
            "https://x/a.tar.gz", errors, what="archive artifact", what_url="archive url", label="p@1"
        )
        self.assertEqual(errors, [])


class TestRecordSha256(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_malformed_binary_wording(self):
        errors: list[str] = []
        self.lint._record_sha256(
            "zz", errors, seen_sha256={}, dedupe_key="p@1/x",
            what="target 'x'", what_dup="target 'x'", label="p@1",
        )
        self.assertEqual(
            errors, ["p@1: target 'x' missing or malformed sha256 (expected 64 hex chars)"]
        )

    def test_malformed_archive_wording(self):
        errors: list[str] = []
        self.lint._record_sha256(
            "zz", errors, seen_sha256={}, dedupe_key="p@1",
            what="archive artifact", what_dup="archive", label="p@1",
        )
        self.assertEqual(
            errors, ["p@1: archive artifact missing or malformed sha256 (expected 64 hex chars)"]
        )

    def test_valid_records_dedupe(self):
        errors: list[str] = []
        seen: dict[str, str] = {}
        self.lint._record_sha256(
            "ab" * 32, errors, seen_sha256=seen, dedupe_key="p@1/a",
            what="target 'a'", what_dup="target 'a'", label="p@1",
        )
        self.assertEqual(errors, [])
        self.assertEqual(seen, {"ab" * 32: "p@1/a"})

    def test_duplicate_binary_wording(self):
        errors: list[str] = []
        seen = {"ab" * 32: "p@1/a"}
        self.lint._record_sha256(
            "ab" * 32, errors, seen_sha256=seen, dedupe_key="p@1/b",
            what="target 'b'", what_dup="target 'b'", label="p@1",
        )
        self.assertEqual(
            errors, ["p@1: duplicate sha256 for target 'b' (also used by p@1/a)"]
        )

    def test_duplicate_archive_wording(self):
        errors: list[str] = []
        seen = {"ab" * 32: "p@0/other"}
        self.lint._record_sha256(
            "ab" * 32, errors, seen_sha256=seen, dedupe_key="p@1",
            what="archive artifact", what_dup="archive", label="p@1",
        )
        self.assertEqual(
            errors, ["p@1: duplicate sha256 for archive (also used by p@0/other)"]
        )

    def test_same_dedupe_key_is_not_duplicate(self):
        errors: list[str] = []
        seen = {"ab" * 32: "p@1/a"}
        self.lint._record_sha256(
            "ab" * 32, errors, seen_sha256=seen, dedupe_key="p@1/a",
            what="target 'a'", what_dup="target 'a'", label="p@1",
        )
        self.assertEqual(errors, [])


class TestTagsClaimActivation(unittest.TestCase):
    """Unit tests for the _tags_claim_activation helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_activatable_tag(self):
        self.assertTrue(self.lint._tags_claim_activation(["module", "activatable"]))
        self.assertTrue(self.lint._tags_claim_activation(["Activatable"]))

    def test_no_activatable_tag(self):
        self.assertFalse(self.lint._tags_claim_activation(["module"]))
        self.assertFalse(self.lint._tags_claim_activation([]))

    def test_non_list(self):
        self.assertFalse(self.lint._tags_claim_activation(None))
        self.assertFalse(self.lint._tags_claim_activation("activatable"))


class TestLintActivation(unittest.TestCase):
    """Unit tests for _lint_activation extracted from lint_activation_and_provenance()."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    @staticmethod
    def _pkg(pkg_type, *, tags=None, activation=None) -> tuple[dict[str, object], dict[str, object]]:
        pkg = {"type": pkg_type, "tags": tags if tags is not None else [pkg_type]}
        version = {}
        if activation is not None:
            version["activation"] = activation
        return pkg, version

    def test_plugin_activation_ignored(self):
        pkg, version = self._pkg("plugin", activation={"kind": "bogus"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_script_activation_ignored(self):
        pkg, version = self._pkg("script", activation={"kind": "bogus"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_module_missing_activation_tagged_activatable(self):
        pkg, version = self._pkg("module", tags=["module", "activatable"])
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertEqual(
            errors, ["p@1: module tagged for activation is missing activation declaration"]
        )

    def test_module_missing_activation_not_tagged_ok(self):
        pkg, version = self._pkg("module", tags=["module"])
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_module_missing_kind(self):
        pkg, version = self._pkg("module", activation={"import": "all"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertIn("p@1: activation.kind is missing", errors)

    def test_module_bad_import_mode(self):
        pkg, version = self._pkg("module", activation={"kind": "nu-module", "import": "bogus"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertIn(
            "p@1: activation.import must be 'module' or 'all', got 'bogus'", errors
        )

    def test_module_valid_activation_ok(self):
        pkg, version = self._pkg("module", activation={"kind": "nu-module", "import": "all"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertEqual(errors, [])


class TestLintSourceProvenance(unittest.TestCase):
    """Unit tests for _lint_source_provenance extracted from lint_activation_and_provenance()."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_no_source_ok(self):
        errors: list[str] = []
        self.lint._lint_source_provenance({}, {}, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_source_not_dict(self):
        errors: list[str] = []
        self.lint._lint_source_provenance({}, {"source": "nope"}, errors, label="p@1")
        self.assertEqual(errors, ["p@1: source must be an object when present"])

    def test_missing_source_fields(self):
        source = {"git": "", "rev": "  ", "cargo_name": None}
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "plugin"}, {"source": source}, errors, label="p@1"
        )
        self.assertEqual(
            errors,
            [
                "p@1: source.git is missing or empty",
                "p@1: source.rev is missing or empty",
                "p@1: source.cargo_name is missing or empty",
            ],
        )

    def test_non_plugin_source_without_cargo_name_ok(self):
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "module"},
            {"source": {"git": "g", "rev": "abc123def456"}},
            errors,
            label="p@1",
        )
        self.assertEqual(errors, [])

    def test_non_plugin_source_still_requires_git_rev(self):
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "module"}, {"source": {"git": "g"}}, errors, label="p@1"
        )
        self.assertEqual(errors, ["p@1: source.rev is missing or empty"])

    def test_non_immutable_rev(self):
        for rev in ("main", "MASTER", "Head"):
            errors: list[str] = []
            self.lint._lint_source_provenance(
                {"type": "plugin"},
                {"source": {"git": "g", "rev": rev, "cargo_name": "c"}},
                errors,
                label="p@1",
            )
            self.assertEqual(
                errors,
                [f"p@1: source.rev {rev!r} is not immutable provenance (use a tag or full commit)"],
            )

    def test_immutable_rev_ok(self):
        for rev in ("v1.0.0", "abc123def456"):
            errors: list[str] = []
            self.lint._lint_source_provenance(
                {"type": "plugin"},
                {"source": {"git": "g", "rev": rev, "cargo_name": "c"}},
                errors,
                label="p@1",
            )
            self.assertEqual(errors, [])


class TestLintForkIdentity(unittest.TestCase):
    """Unit tests for _lint_fork_identity extracted from lint_activation_and_provenance()."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_non_fork_owner_is_ignored(self):
        errors: list[str] = []
        self.lint._lint_fork_identity({"id": {"owner": "acme"}}, {}, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_fork_owner_without_source_is_error(self):
        errors: list[str] = []
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, {}, errors, label="p@1"
        )
        self.assertEqual(
            errors, ["p@1: owner 'numan-maintained' requires source.upstream (original repo URL)"]
        )

    def test_fork_owner_with_source_but_no_upstream_is_error(self):
        errors: list[str] = []
        version = {"source": {"git": "g", "rev": "r", "cargo_name": "c"}}
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, version, errors, label="p@1"
        )
        self.assertEqual(
            errors, ["p@1: owner 'numan-maintained' requires source.upstream (original repo URL)"]
        )

    def test_fork_owner_with_upstream_is_ok(self):
        errors: list[str] = []
        version = {
            "source": {
                "git": "g",
                "rev": "r",
                "cargo_name": "c",
                "upstream": "https://github.com/original/pkg",
            }
        }
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, version, errors, label="p@1"
        )
        self.assertEqual(errors, [])

    def test_non_fork_with_upstream_is_error(self):
        errors: list[str] = []
        version = {"source": {"upstream": "https://github.com/original/pkg"}}
        self.lint._lint_fork_identity(
            {"id": {"owner": "acme"}}, version, errors, label="p@1"
        )
        self.assertEqual(
            errors,
            ["p@1: source.upstream is only valid for owner 'numan-maintained'"],
        )

    def test_non_fork_with_null_upstream_is_error(self):
        errors: list[str] = []
        version = {"source": {"upstream": None}}
        self.lint._lint_fork_identity(
            {"id": {"owner": "acme"}}, version, errors, label="p@1"
        )
        self.assertEqual(
            errors,
            ["p@1: source.upstream is only valid for owner 'numan-maintained'"],
        )

    def test_fork_owner_with_dotgit_suffix_self_upstream_is_error(self):
        errors: list[str] = []
        version = {
            "source": {
                "git": "https://github.com/numan-maintained/pkg",
                "rev": "r",
                "cargo_name": "c",
                "upstream": "https://github.com/numan-maintained/pkg.git",
            }
        }
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, version, errors, label="p@1"
        )
        self.assertEqual(
            errors,
            [
                "p@1: source.upstream must identify the original repository, "
                "not the fork's source.git"
            ],
        )

    def test_fork_owner_with_invalid_upstream_is_error(self):
        errors: list[str] = []
        version = {
            "source": {
                "git": "g",
                "rev": "r",
                "cargo_name": "c",
                "upstream": "typo",
            }
        }
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, version, errors, label="p@1"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("source.upstream", errors[0])

    def test_fork_owner_with_self_upstream_is_error(self):
        errors: list[str] = []
        version = {
            "source": {
                "git": "https://github.com/numan-maintained/pkg",
                "rev": "r",
                "cargo_name": "c",
                "upstream": "https://github.com/numan-maintained/pkg",
            }
        }
        self.lint._lint_fork_identity(
            {"id": {"owner": "numan-maintained"}}, version, errors, label="p@1"
        )
        self.assertEqual(
            errors,
            [
                "p@1: source.upstream must identify the original repository, "
                "not the fork's source.git"
            ],
        )


class TestLintActivationAndProvenance(unittest.TestCase):
    """Locks that the orchestrator reports activation AND source errors together."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_both_error_sets_reported_for_one_version(self):
        pkg = {
            "id": {"owner": "acme", "name": "module"},
            "type": "module",
            "tags": ["module", "activatable"],
        }
        version = {
            "version": "1.0.0",
            "activation": {"import": "bogus"},
            "source": {"git": "g", "rev": "main", "cargo_name": "c"},
        }
        errors: list[str] = []
        self.lint.lint_activation_and_provenance(pkg, version, errors)
        self.assertIn(
            "acme/module@1.0.0: activation.import must be 'module' or 'all', got 'bogus'",
            errors,
        )
        self.assertIn(
            "acme/module@1.0.0: source.rev 'main' is not immutable provenance "
            "(use a tag or full commit)",
            errors,
        )
        self.assertIn("acme/module@1.0.0: activation.kind is missing", errors)
        self.assertEqual(len(errors), 3)


class LintPackagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_clean_index_passes(self):
        errors = self.lint.lint_index({"packages": [base_package()]})
        self.assertEqual(errors, [])

    def test_missing_metadata_is_error(self):
        pkg = base_package(description="")
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("missing metadata description" in e for e in errors))

    def test_unknown_triple_is_error(self):
        pkg = base_package()
        pkg["versions"][0]["artifact"]["targets"] = {
            "powerpc-unknown-linux-gnu": {
                "url": "https://example.com/demo.tar.gz",
                "sha256": "b" * 64,
                "executable_path": "nu_plugin_demo",
            }
        }
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("unknown target triple" in e for e in errors))

    def test_unsupported_archive_suffix_is_error(self):
        pkg = base_package()
        pkg["versions"][0]["artifact"]["targets"]["x86_64-unknown-linux-gnu"][
            "url"
        ] = "https://example.com/demo.rar"
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("unsupported archive suffix" in e for e in errors))

    def test_malformed_nu_constraint_is_error(self):
        pkg = base_package()
        pkg["versions"][0]["nu_version"] = "latest"
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("nu_version token" in e for e in errors))

    def test_duplicate_sha256_is_error(self):
        pkg = base_package()
        pkg["versions"][0]["artifact"]["targets"]["aarch64-unknown-linux-gnu"] = {
            "url": "https://example.com/demo2.tar.gz",
            "sha256": "a" * 64,
            "executable_path": "nu_plugin_demo",
        }
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("duplicate sha256" in e for e in errors))

    def test_source_rev_head_is_error(self):
        pkg = base_package()
        pkg["versions"][0]["source"]["rev"] = "HEAD"
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("not immutable provenance" in e for e in errors))


    def test_fork_owner_without_upstream_is_index_error(self):
        pkg = base_package(id={"owner": "numan-maintained", "name": "nu_plugin_x"})
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertIn(
            "numan-maintained/nu_plugin_x@1.0.0: owner 'numan-maintained' requires "
            "source.upstream (original repo URL)",
            errors,
        )

    def test_fork_owner_with_upstream_passes(self):
        pkg = base_package(id={"owner": "numan-maintained", "name": "nu_plugin_x"})
        pkg["versions"][0]["source"]["upstream"] = "https://github.com/original/nu_plugin_x"
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertEqual(errors, [])

    def test_module_activation_tag_requires_declaration(self):
        pkg = base_package(
            type="module",
            tags=["module", "activatable"],
            id={"owner": "acme", "name": "demo_mod"},
        )
        pkg["versions"][0]["artifact"] = {
            "kind": "archive",
            "url": "https://example.com/mod.zip",
            "sha256": "c" * 64,
        }
        pkg["versions"][0].pop("source", None)
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertTrue(any("missing activation declaration" in e for e in errors))

    def test_main_ok_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index_path.write_text(
                '{"packages": ['
                + json.dumps(base_package())
                + "]}",
                encoding="utf-8",
            )
            code = self.lint.main(["--index", str(index_path)])
            self.assertEqual(code, 0)

    def test_errors_are_sorted_deterministic(self):
        # Process zz before aa so generation order differs from sorted order.
        # Repeat zz so main()'s sorted(set(...)) collapses duplicate messages.
        zz = base_package(
            id={"owner": "zz", "name": "pkg"},
            description="",
            repo="",
        )
        aa = base_package(
            id={"owner": "aa", "name": "pkg"},
            description="",
            repo="",
        )
        index = {"packages": [zz, "not-a-package", aa, zz]}
        raw = self.lint.lint_index(index)
        expected = sorted(set(raw))
        self.assertNotEqual(raw, expected)
        self.assertLess(len(expected), len(raw))
        expected_lines = [f"  - {error}" for error in expected]

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                code = self.lint.main(["--index", str(index_path)])
            self.assertEqual(code, 1)
            emitted = [
                line for line in buf.getvalue().splitlines() if line.startswith("  - ")
            ]
            self.assertEqual(emitted, expected_lines)
            self.assertTrue(emitted[0].startswith("  - aa/"))
            self.assertTrue(any("packages[1]:" in line for line in emitted))

    def test_malformed_entries_keep_distinct_labels(self):
        errors = self.lint.lint_index(
            {"packages": ["x", "y", {"description": "no-id"}]}
        )
        self.assertIn("packages[0]: entry must be an object", errors)
        self.assertIn("packages[1]: entry must be an object", errors)
        self.assertTrue(
            any(e.startswith("<unknown-package#2>:") for e in errors)
        )

    def test_malformed_version_entries_keep_distinct_labels(self):
        pkg = base_package()
        pkg["versions"] = ["bad", {"nu_version": "*"}, "also-bad"]
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertIn(
            "acme/nu_plugin_demo: versions[0]: entry must be an object", errors
        )
        self.assertIn(
            "acme/nu_plugin_demo: versions[2]: entry must be an object", errors
        )
        self.assertTrue(
            any(e.startswith("acme/nu_plugin_demo@?#1:") for e in errors)
        )
        self.assertEqual(len(set(errors)), len(errors))


class ProvisionalDeferralWarningsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_warns_when_deferral_reason_missing(self):
        pkg = base_package()
        del pkg["versions"][0]["verified_with"]
        pkg["versions"][0]["evidence_tier"] = "provisional"
        warnings = self.lint.provisional_deferral_warnings({"packages": [pkg]})
        self.assertEqual(len(warnings), 1)
        self.assertIn("deferral_reason is missing/empty", warnings[0])

    def test_warns_when_deferral_reason_blank(self):
        pkg = base_package()
        del pkg["versions"][0]["verified_with"]
        pkg["versions"][0]["evidence_tier"] = "provisional"
        pkg["versions"][0]["deferral_reason"] = "   "
        warnings = self.lint.provisional_deferral_warnings({"packages": [pkg]})
        self.assertEqual(len(warnings), 1)

    def test_no_warning_when_deferral_reason_present(self):
        pkg = base_package()
        del pkg["versions"][0]["verified_with"]
        pkg["versions"][0]["evidence_tier"] = "provisional"
        pkg["versions"][0]["deferral_reason"] = "requires cloud credentials"
        warnings = self.lint.provisional_deferral_warnings({"packages": [pkg]})
        self.assertEqual(warnings, [])

    def test_no_warning_for_proven_entries(self):
        warnings = self.lint.provisional_deferral_warnings({"packages": [base_package()]})
        self.assertEqual(warnings, [])

    def test_missing_deferral_reason_is_warning_not_error(self):
        pkg = base_package()
        del pkg["versions"][0]["verified_with"]
        pkg["versions"][0]["evidence_tier"] = "provisional"
        errors = self.lint.lint_index({"packages": [pkg]})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
