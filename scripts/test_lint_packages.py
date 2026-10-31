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

    def test_plugin_activation_targets_rejected(self):
        pkg, version = self._pkg("plugin", activation={
            "kind": "nu-completion",
            "targets": [{"command": "git", "path": "git.nu", "kind": "command-backed"}],
        })
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertTrue(
            any("activation.targets is only valid for completion/script" in e for e in errors),
            errors,
        )

    def test_module_activation_entry_points_rejected(self):
        pkg, version = self._pkg("module", activation={
            "kind": "nu-script",
            "entry_points": [{"name": "run", "path": "run.nu"}],
        })
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertTrue(
            any("activation.entry_points is only valid for completion/script" in e for e in errors),
            errors,
        )

    def test_script_activation_wrong_kind_is_error(self):
        pkg, version = self._pkg("script", activation={"kind": "bogus"})
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        self.assertTrue(any("must be 'nu-script'" in e for e in errors), errors)

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


class TestLintCompletionActivation(unittest.TestCase):
    """Unit tests for completion activation lint in _lint_activation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    @staticmethod
    def _target(command="git", path="custom-completions/git/git-completions.nu",
                kind="command-backed"):
        return {"command": command, "path": path, "kind": kind}

    @classmethod
    def _pkg(cls, *, tags=None, activation="valid"):
        pkg = {"type": "completion", "tags": tags if tags is not None else ["completion"]}
        version = {}
        if activation == "valid":
            version["activation"] = {
                "kind": "nu-completion",
                "targets": [cls._target()],
            }
        elif activation is not None:
            version["activation"] = activation
        return pkg, version

    def _errors(self, pkg, version):
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        return errors

    def test_valid_declaration_passes(self):
        pkg, version = self._pkg()
        self.assertEqual(self._errors(pkg, version), [])

    def test_valid_static_target_passes(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(kind="static")],
        })
        self.assertEqual(self._errors(pkg, version), [])

    def test_install_only_completion_ok(self):
        pkg, version = self._pkg(activation=None)
        self.assertEqual(self._errors(pkg, version), [])

    def test_install_only_completion_tagged_activatable_is_error(self):
        pkg, version = self._pkg(tags=["completion", "activatable"], activation=None)
        self.assertEqual(
            self._errors(pkg, version),
            ["p@1: completion tagged for activation is missing activation declaration"],
        )

    def test_wrong_kind_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-module",
            "targets": [self._target()],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("must be 'nu-completion'" in e for e in errors), errors)

    def test_missing_targets_is_error(self):
        pkg, version = self._pkg(activation={"kind": "nu-completion"})
        errors = self._errors(pkg, version)
        self.assertTrue(any("non-empty list" in e for e in errors), errors)

    def test_empty_targets_is_error(self):
        pkg, version = self._pkg(activation={"kind": "nu-completion", "targets": []})
        errors = self._errors(pkg, version)
        self.assertTrue(any("non-empty list" in e for e in errors), errors)

    def test_duplicate_command_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [
                self._target(),
                self._target(path="custom-completions/git/other.nu"),
            ],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("duplicate activation target command 'git'" in e for e in errors), errors)

    def test_duplicate_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [
                self._target(),
                self._target(command="git2"),
            ],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("duplicate activation target path" in e for e in errors), errors)

    def test_reserved_keyword_command_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(command="export")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("reserved keyword" in e for e in errors), errors)

    def test_invalid_command_name_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(command="9git")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("not a valid command name" in e for e in errors), errors)

    def test_traversal_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path="../outside.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_absolute_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path="/abs/git.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_backslash_traversal_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path=r"..\outside.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_windows_drive_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path=r"C:\outside.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_dotfile_nu_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path="custom-completions/git/.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_non_nu_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(path="custom-completions/git/git.txt")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_bad_target_kind_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [self._target(kind="dynamic")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("must be 'static' or 'command-backed'" in e for e in errors), errors)

    def test_extra_target_key_is_error(self):
        target = self._target()
        target["extra"] = "x"
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": [target],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("exactly the keys command, path, kind" in e for e in errors), errors)

    def test_non_object_target_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-completion",
            "targets": ["git"],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("must be an object" in e for e in errors), errors)


class TestLintScriptActivation(unittest.TestCase):
    """Unit tests for script activation lint in _lint_activation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    @staticmethod
    def _ep(name="wttr", path="wttr.nu"):
        return {"name": name, "path": path}

    @classmethod
    def _pkg(cls, *, tags=None, activation="valid"):
        pkg = {"type": "script", "tags": tags if tags is not None else ["script"]}
        version = {}
        if activation == "valid":
            version["activation"] = {
                "kind": "nu-script",
                "entry_points": [cls._ep()],
            }
        elif activation is not None:
            version["activation"] = activation
        return pkg, version

    def _errors(self, pkg, version):
        errors: list[str] = []
        self.lint._lint_activation(pkg, version, errors, label="p@1")
        return errors

    def test_valid_declaration_passes(self):
        pkg, version = self._pkg()
        self.assertEqual(self._errors(pkg, version), [])

    def test_install_only_script_ok(self):
        pkg, version = self._pkg(activation=None)
        self.assertEqual(self._errors(pkg, version), [])

    def test_install_only_script_tagged_activatable_is_error(self):
        pkg, version = self._pkg(tags=["script", "activatable"], activation=None)
        self.assertEqual(
            self._errors(pkg, version),
            ["p@1: script tagged for activation is missing activation declaration"],
        )

    def test_wrong_kind_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-module",
            "entry_points": [self._ep()],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("must be 'nu-script'" in e for e in errors), errors)

    def test_missing_entry_points_is_error(self):
        pkg, version = self._pkg(activation={"kind": "nu-script"})
        errors = self._errors(pkg, version)
        self.assertTrue(any("non-empty list" in e for e in errors), errors)

    def test_empty_entry_points_is_error(self):
        pkg, version = self._pkg(activation={"kind": "nu-script", "entry_points": []})
        errors = self._errors(pkg, version)
        self.assertTrue(any("non-empty list" in e for e in errors), errors)

    def test_duplicate_name_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(), self._ep(path="other.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("duplicate script entry point name 'wttr'" in e for e in errors), errors)

    def test_duplicate_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(), self._ep(name="wttr2")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("duplicate script entry point path" in e for e in errors), errors)

    def test_duplicate_path_curdir_normalized_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(), self._ep(name="wttr2", path="./wttr.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("duplicate script entry point path" in e for e in errors), errors)

    def test_reserved_keyword_name_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(name="if")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("reserved keyword" in e for e in errors), errors)

    def test_invalid_name_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(name="9wttr")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("not a valid command name" in e for e in errors), errors)

    def test_traversal_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(path="../escape.nu")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_non_nu_path_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [self._ep(path="wttr.txt")],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("safe relative path" in e for e in errors), errors)

    def test_extra_entry_point_key_is_error(self):
        ep = self._ep()
        ep["kind"] = "static"
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": [ep],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("exactly the keys name, path" in e for e in errors), errors)

    def test_non_object_entry_point_is_error(self):
        pkg, version = self._pkg(activation={
            "kind": "nu-script",
            "entry_points": ["wttr"],
        })
        errors = self._errors(pkg, version)
        self.assertTrue(any("must be an object" in e for e in errors), errors)


class TestLintSourceProvenance(unittest.TestCase):
    """Unit tests for _lint_source_provenance extracted from lint_activation_and_provenance()."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    def test_no_source_ok(self):
        """Absent source blocks are always fine."""
        errors: list[str] = []
        self.lint._lint_source_provenance({}, {}, errors, label="p@1")
        self.assertEqual(errors, [])

    def test_source_not_dict(self):
        """A non-object source is rejected for any package type."""
        errors: list[str] = []
        self.lint._lint_source_provenance({}, {"source": "nope"}, errors, label="p@1")
        self.assertEqual(errors, ["p@1: source must be an object when present"])

    def test_missing_source_fields(self):
        """Plugin sources must supply git, rev, and cargo_name."""
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
        """Non-plugin sources may omit cargo_name entirely."""
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "module"},
            {"source": {"git": "g", "rev": "a" * 40}},
            errors,
            label="p@1",
        )
        self.assertEqual(errors, [])

    def test_non_plugin_source_still_requires_git_rev(self):
        """Non-plugin sources still require git and rev."""
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "module"}, {"source": {"git": "g"}}, errors, label="p@1"
        )
        self.assertEqual(errors, ["p@1: source.rev is missing or empty"])

    def test_non_immutable_rev(self):
        """Branch names and abbreviated SHAs are rejected for every package type."""
        for rev in ("main", "MASTER", "Head", "develop", "abc123def456"):
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
        """Tag and commit revisions pass provenance checks."""
        for rev in (
            "v1.0.0",
            "1.2.3-alpha.1",
            "1.2.3+build.5",
            "v1.2.3-rc.1+build.5",
            "a" * 40,
        ):
            errors: list[str] = []
            self.lint._lint_source_provenance(
                {"type": "plugin"},
                {"source": {"git": "g", "rev": rev, "cargo_name": "c"}},
                errors,
                label="p@1",
            )
            self.assertEqual(errors, [])

    def test_arbitrarily_long_malformed_version_tag_is_rejected(self):
        rev = "v1.2.3" + "-a" * 50_000 + "!"
        errors: list[str] = []
        self.lint._lint_source_provenance(
            {"type": "plugin"},
            {"source": {"git": "g", "rev": rev, "cargo_name": "c"}},
            errors,
            label="p@1",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("not immutable provenance", errors[0])


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


class CrossPackageOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lint = load_lint()

    @staticmethod
    def _completion_pkg(owner, name, command):
        pkg = base_package(
            id={"owner": owner, "name": name},
            type="completion",
            tags=["completion"],
        )
        pkg["versions"][0]["activation"] = {
            "kind": "nu-completion",
            "targets": [
                {
                    "command": command,
                    "path": f"custom-completions/{command}/{command}-completions.nu",
                    "kind": "command-backed",
                }
            ],
        }
        return pkg

    @staticmethod
    def _script_pkg(owner, name, entry_name):
        pkg = base_package(
            id={"owner": owner, "name": name},
            type="script",
            tags=["script"],
        )
        pkg["versions"][0]["activation"] = {
            "kind": "nu-script",
            "entry_points": [{"name": entry_name, "path": f"{entry_name}.nu"}],
        }
        return pkg

    def _ownership_errors(self, packages):
        errors = self.lint.lint_index({"packages": packages})
        return [e for e in errors if e.startswith("activation ownership:")]

    def test_duplicate_completion_target_across_packages_is_error(self):
        errors = self._ownership_errors(
            [
                self._completion_pkg("nushell", "custom-completions", "git"),
                self._completion_pkg("nushell", "git-completions", "git"),
            ]
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("'git'", errors[0])
        self.assertIn("nushell/custom-completions", errors[0])
        self.assertIn("nushell/git-completions", errors[0])

    def test_distinct_completion_targets_pass(self):
        errors = self._ownership_errors(
            [
                self._completion_pkg("nushell", "git-completions", "git"),
                self._completion_pkg("nushell", "cargo-completions", "cargo"),
            ]
        )
        self.assertEqual(errors, [])

    def test_same_package_two_versions_same_target_passes(self):
        pkg = self._completion_pkg("nushell", "git-completions", "git")
        second = json.loads(json.dumps(pkg["versions"][0]))
        second["version"] = "1.0.1"
        pkg["versions"].append(second)
        self.assertEqual(self._ownership_errors([pkg]), [])

    def test_duplicate_script_entry_point_across_packages_is_error(self):
        errors = self._ownership_errors(
            [
                self._script_pkg("acme", "weather-a", "weather"),
                self._script_pkg("acme", "weather-b", "weather"),
            ]
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("script entry point", errors[0])

    def test_completion_and_script_same_name_are_separate_lanes(self):
        errors = self._ownership_errors(
            [
                self._completion_pkg("acme", "weather-completions", "weather"),
                self._script_pkg("acme", "weather-script", "weather"),
            ]
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
