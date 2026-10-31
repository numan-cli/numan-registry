#!/usr/bin/env python3.12
"""Tests for scripts/validate_candidate.py (Stage 5: validation harness)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import validate_candidate


def _write_spec(tmp: str) -> Path:
    """Write a minimal valid spec fixture and return its path."""
    spec = {
        "owner": "vyadh",
        "name": "nutest",
        "description": "Test framework",
        "repo": "https://github.com/vyadh/nutest",
        "type": "module",
        "tags": ["module"],
        "version": "1.2.0",
        "nu_version": "*",
        "artifact": {"kind": "archive", "url": "https://example.com/nutest.zip", "entry": "mod.nu"},
    }
    path = Path(tmp) / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


class TestLoadSpec(unittest.TestCase):
    def test_raw_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps({"owner": "a", "name": "b"}), encoding="utf-8")
            self.assertEqual(validate_candidate._load_spec(path), {"owner": "a", "name": "b"})

    def test_wrapped_spec_unwraps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps({"spec": {"owner": "a"}, "_meta": {"x": 1}}), encoding="utf-8")
            self.assertEqual(validate_candidate._load_spec(path), {"owner": "a"})

    def test_scalar_or_array_root_raises(self):
        for payload in ("[]", "42", "\"not-an-object\""):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "spec.json"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_candidate._load_spec(path)

    def test_wrapped_scalar_or_array_spec_raises(self):
        for inner in ("[]", "42", "\"not-an-object\""):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "spec.json"
                path.write_text(
                    json.dumps({"spec": json.loads(inner), "_meta": {"x": 1}}),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    validate_candidate._load_spec(path)


class TestIsActivatable(unittest.TestCase):
    def test_plugin_always(self):
        self.assertTrue(validate_candidate._is_activatable({"type": "plugin"}))

    def test_module_requires_activation(self):
        self.assertFalse(validate_candidate._is_activatable({"type": "module"}))
        self.assertTrue(validate_candidate._is_activatable(
            {"type": "module", "activation": {"kind": "nu-module"}}
        ))

    def test_completion_requires_activation(self):
        self.assertFalse(validate_candidate._is_activatable({"type": "completion"}))
        self.assertTrue(validate_candidate._is_activatable(
            {"type": "completion", "activation": {"kind": "nu-completion"}}
        ))

    def test_script_requires_activation(self):
        self.assertFalse(validate_candidate._is_activatable({"type": "script"}))
        self.assertTrue(validate_candidate._is_activatable(
            {"type": "script", "activation": {"kind": "nu-script"}}
        ))


class TestSeedWorkdir(unittest.TestCase):
    def test_writes_spec_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec, index = validate_candidate._seed_workdir(Path(tmp), {"owner": "a"})
            self.assertEqual(json.loads(spec.read_text()), {"owner": "a"})
            seeded = json.loads(index.read_text())
            self.assertEqual(seeded["schema_version"], 1)
            self.assertEqual(seeded["packages"], [])


class TestStepHelpers(unittest.TestCase):
    """Lock in the evidence-check dict shapes emitted by each step helper."""

    def test_step_download_and_hash_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text(json.dumps({
                "schema_version": 1,
                "packages": [{
                    "id": {"owner": "o", "name": "n"},
                    "versions": [{"version": "1.0.0", "artifact": {"kind": "binary", "targets": {"a": {}, "b": {}}}}],
                }],
            }), encoding="utf-8")
            with patch("validate_candidate._run_script", return_value=(True, "ok")):
                check = validate_candidate._step_download_and_hash(Path(tmp) / "spec.json", idx)
        self.assertEqual(check["name"], "download_and_hash")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["targets"], 2)
        self.assertEqual(check["detail"], "")

    def test_step_download_and_hash_fail_truncates_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text(json.dumps({"schema_version": 1, "packages": []}), encoding="utf-8")
            with patch("validate_candidate._run_script", return_value=(False, "x" * 1000)):
                check = validate_candidate._step_download_and_hash(Path(tmp) / "spec.json", idx)
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["targets"], 0)
        self.assertEqual(len(check["detail"]), 500)

    def test_extract_lint_errors_captures_fail_block(self):
        out = "PASS line\nFAIL: 2 errors:\n  - pkg: bad\n  - pkg: worse"
        self.assertEqual(
            validate_candidate._extract_lint_errors(out),
            ["FAIL: 2 errors:", "  - pkg: bad", "  - pkg: worse"],
        )

    def test_extract_lint_errors_falls_back_to_all_lines(self):
        self.assertEqual(validate_candidate._extract_lint_errors("weird output"), ["weird output"])

    def test_step_lint_pass_has_empty_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("validate_candidate._run_script", return_value=(True, "")):
                check = validate_candidate._step_lint(Path(tmp) / "index.json")
        self.assertEqual(check["name"], "lint")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["errors"], [])

    def test_step_schema_fail_truncates_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("validate_candidate._run_script", return_value=(False, "y" * 1000)):
                check = validate_candidate._step_schema(Path(tmp) / "index.json")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(len(check["detail"]), 500)

    def test_step_lifecycle_prove_builds_args(self):
        with patch("validate_candidate._run_script") as run:
            run.return_value = (True, "")
            check = validate_candidate._step_lifecycle(
                "a/b", prove=True, numan="/numan", nu="/nu", deferral=""
            )
        args = run.call_args.args[0]
        self.assertIn("lifecycle-prove.py", " ".join(args))
        self.assertIn("--numan", args)
        self.assertIn("--nu", args)
        self.assertEqual(check["status"], "pass")

    def test_step_lifecycle_skip_with_deferral(self):
        check = validate_candidate._step_lifecycle("a/b", prove=False, numan=None, nu=None, deferral="pending")
        self.assertEqual(check["status"], "skip")
        self.assertEqual(check["detail"], "deferred: pending")


class TestComputeOverall(unittest.TestCase):
    def _checks(self, lifecycle="skip"):
        return [
            {"name": "download_and_hash", "status": "pass", "targets": 1, "detail": ""},
            {"name": "lint", "status": "pass", "errors": []},
            {"name": "schema", "status": "pass", "detail": ""},
            {"name": "lifecycle", "status": lifecycle, "detail": ""},
        ]

    def test_pass_with_satisfied_lifecycle(self):
        self.assertEqual(
            validate_candidate._compute_overall(self._checks("pass"), strict=False, deferral="", lifecycle_required=True),
            "pass",
        )

    def test_fail_when_core_fails(self):
        checks = self._checks("pass")
        checks[1]["status"] = "fail"
        self.assertEqual(
            validate_candidate._compute_overall(checks, strict=False, deferral="", lifecycle_required=True),
            "fail",
        )

    def test_fail_when_lifecycle_required_but_skipped(self):
        self.assertEqual(
            validate_candidate._compute_overall(self._checks("skip"), strict=False, deferral="", lifecycle_required=True),
            "fail",
        )

    def test_pass_when_skipped_with_deferral(self):
        self.assertEqual(
            validate_candidate._compute_overall(self._checks("skip"), strict=False, deferral="pending", lifecycle_required=True),
            "pass",
        )

    def test_fail_when_strict_and_lifecycle_fails(self):
        self.assertEqual(
            validate_candidate._compute_overall(self._checks("fail"), strict=True, deferral="", lifecycle_required=True),
            "fail",
        )


class TestHumanSummary(unittest.TestCase):
    def _checks(self, lifecycle="skip"):
        return [
            {"name": "download_and_hash", "status": "pass", "targets": 3, "detail": ""},
            {"name": "lint", "status": "pass", "errors": []},
            {"name": "schema", "status": "pass", "detail": ""},
            {"name": "lifecycle", "status": lifecycle, "detail": ""},
        ]

    def test_pass_summary(self):
        summary = validate_candidate._human_summary(
            self._checks("pass"), deferral="", lifecycle_required=True, overall="pass"
        )
        self.assertIn("3 artifact(s) downloaded and hashed.", summary)
        self.assertIn("Lint clean.", summary)
        self.assertIn("Schema valid.", summary)
        self.assertIn("Lifecycle passed.", summary)

    def test_deferral_summary(self):
        summary = validate_candidate._human_summary(
            self._checks("skip"), deferral="pending", lifecycle_required=True, overall="pass"
        )
        self.assertIn("Lifecycle deferred.", summary)

    def test_required_evidence_summary(self):
        summary = validate_candidate._human_summary(
            self._checks("skip"), deferral="", lifecycle_required=True, overall="fail"
        )
        self.assertIn("Lifecycle evidence required for activatable package.", summary)


class TestRunScript(unittest.TestCase):
    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        ok, output = validate_candidate._run_script(["script.py"], label="test")
        self.assertTrue(ok)
        self.assertEqual(output, "ok")

    @patch("subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error: bad")
        ok, output = validate_candidate._run_script(["script.py"], label="test")
        self.assertFalse(ok)
        self.assertIn("error: bad", output)

    @patch("subprocess.run", side_effect=FileNotFoundError("no python"))
    def test_missing_binary(self, mock_run):
        ok, output = validate_candidate._run_script(["script.py"], label="test")
        self.assertFalse(ok)
        self.assertIn("no python", output)


class TestIntakeBranchName(unittest.TestCase):
    def test_matches_open_intake_pr_shape(self):
        self.assertEqual(
            validate_candidate._intake_branch_name("fdncred", "nu_plugin_emoji", "0.23.0"),
            "intake/fdncred-nu_plugin_emoji-0.23.0",
        )

    def test_sanitizes_unsafe_chars(self):
        self.assertEqual(
            validate_candidate._intake_branch_name("a/b", "c d", "1.0.0"),
            "intake/a-b-c-d-1.0.0",
        )


class TestWarnOpenIntakePrs(unittest.TestCase):
    @patch("validate_candidate.gh_json", return_value=None)
    def test_silent_when_gh_unavailable(self, mock_gh):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            validate_candidate._warn_open_intake_prs("acme", "pkg", "1.0.0")
        self.assertEqual(buf.getvalue(), "")
        mock_gh.assert_called_once()

    @patch("validate_candidate.gh_json", return_value=[])
    def test_silent_when_no_open_prs(self, mock_gh):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            validate_candidate._warn_open_intake_prs("acme", "pkg", "1.0.0")
        self.assertEqual(buf.getvalue(), "")

    @patch(
        "validate_candidate.gh_json",
        return_value=[{"number": 42, "url": "https://example.com/pull/42"}],
    )
    def test_warns_for_each_open_pr(self, mock_gh):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            validate_candidate._warn_open_intake_prs("acme", "pkg", "1.0.0")
        out = buf.getvalue()
        self.assertIn("open intake PR #42", out)
        self.assertIn("acme/pkg@1.0.0", out)
        self.assertIn("https://example.com/pull/42", out)
        args = mock_gh.call_args.args[0]
        self.assertEqual(args[0], "pr")
        self.assertIn("intake/acme-pkg-1.0.0", args)


@patch("validate_candidate.gh_json", return_value=None)
class TestValidateCandidate(unittest.TestCase):
    @patch("validate_candidate._run_script")
    def test_all_pass(self, mock_run, _mock_gh):
        # Simulate all steps passing
        def side_effect(args, *, label):
            if label == "add-package":
                # Write a fake index so target counting works
                idx_arg = args.index("--index") + 1 if "--index" in args else None
                if idx_arg:
                    Path(args[idx_arg]).write_text(json.dumps({
                        "schema_version": 1,
                        "registry": "test",
                        "packages": [{"id": "vyadh/nutest", "versions": [{"version": "1.2.0", "artifact": {"kind": "archive", "url": "x"}}]}],
                    }))
                return True, "ok"
            return True, ""

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = _write_spec(tmp)
            evidence = validate_candidate.validate_candidate(spec_path)

        self.assertEqual(evidence["overall"], "pass")
        self.assertEqual(evidence["package_id"], "vyadh/nutest")
        self.assertEqual(len(evidence["checks"]), 4)
        # Lifecycle should be skip (no --prove)
        lifecycle = next(c for c in evidence["checks"] if c["name"] == "lifecycle")
        self.assertEqual(lifecycle["status"], "skip")

    @patch("validate_candidate._run_script")
    def test_download_fail(self, mock_run, _mock_gh):
        def side_effect(args, *, label):
            if label == "add-package":
                return False, "download failed: 404"
            return True, ""

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = _write_spec(tmp)
            evidence = validate_candidate.validate_candidate(spec_path)

        self.assertEqual(evidence["overall"], "fail")
        dl = next(c for c in evidence["checks"] if c["name"] == "download_and_hash")
        self.assertEqual(dl["status"], "fail")

    @patch("validate_candidate._run_script")
    def test_wrapped_spec_format(self, mock_run, _mock_gh):
        """Handles {spec, _meta} wrapped format from gen_candidate."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            wrapped = {
                "spec": {
                    "owner": "test",
                    "name": "pkg",
                    "description": "d",
                    "repo": "https://x",
                    "type": "module",
                    "tags": ["module"],
                    "version": "1.0.0",
                    "nu_version": "*",
                    "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
                },
                "_meta": {"generated_from": "discovery-v1"},
            }
            path = Path(tmp) / "wrapped.json"
            path.write_text(json.dumps(wrapped), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path)

        self.assertEqual(evidence["package_id"], "test/pkg")

    @patch("validate_candidate._run_script")
    def test_activatable_plugin_requires_lifecycle_evidence(self, mock_run, _mock_gh):
        """A plugin without --prove or deferral cannot report overall pass."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "nu_plugin_x",
                "description": "d",
                "repo": "https://x",
                "type": "plugin",
                "tags": ["plugin"],
                "version": "1.0.0",
                "nu_version": ">=0.114.0 <0.115.0",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path)

        self.assertEqual(evidence["overall"], "fail")
        lifecycle = next(c for c in evidence["checks"] if c["name"] == "lifecycle")
        self.assertEqual(lifecycle["status"], "skip")
        self.assertIn("Lifecycle evidence required", evidence["human_summary"])

    @patch("validate_candidate._run_script")
    def test_activatable_plugin_with_deferral_passes(self, mock_run, _mock_gh):
        """A plugin can pass when lifecycle is explicitly deferred with a reason."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "nu_plugin_x",
                "description": "d",
                "repo": "https://x",
                "type": "plugin",
                "tags": ["plugin"],
                "version": "1.0.0",
                "nu_version": ">=0.114.0 <0.115.0",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(
                path, lifecycle_deferral="not yet in live registry",
            )

        self.assertEqual(evidence["overall"], "pass")
        lifecycle = next(c for c in evidence["checks"] if c["name"] == "lifecycle")
        self.assertEqual(lifecycle["detail"], "deferred: not yet in live registry")
        self.assertEqual(evidence.get("lifecycle_deferral"), {"reason": "not yet in live registry"})
        self.assertIn("Lifecycle deferred", evidence["human_summary"])

    @patch("validate_candidate._run_script")
    def test_non_activatable_module_passes_without_lifecycle(self, mock_run, _mock_gh):
        """A module without activation does not require lifecycle evidence."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "pkg",
                "description": "d",
                "repo": "https://x",
                "type": "module",
                "tags": ["module"],
                "version": "1.0.0",
                "nu_version": "*",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path)

        self.assertEqual(evidence["overall"], "pass")

    @patch("validate_candidate._run_script")
    def test_activatable_module_requires_lifecycle_evidence(self, mock_run, _mock_gh):
        """A module with activation requires lifecycle evidence or deferral."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "pkg",
                "description": "d",
                "repo": "https://x",
                "type": "module",
                "tags": ["module"],
                "version": "1.0.0",
                "nu_version": "*",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
                "activation": {"kind": "nu-module", "import": "all"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path)

        self.assertEqual(evidence["overall"], "fail")


    @patch("validate_candidate._run_script")
    def test_failed_lifecycle_proof_fails_activatable(self, mock_run, _mock_gh):
        """A failed lifecycle proof must not satisfy lifecycle evidence."""
        def side_effect(args, *, label):
            if label == "add-package":
                idx_arg = args.index("--index") + 1 if "--index" in args else None
                if idx_arg:
                    Path(args[idx_arg]).write_text(json.dumps({
                        "schema_version": 1,
                        "registry": "test",
                        "packages": [{
                            "id": "test/nu_plugin_x",
                            "versions": [{"version": "1.0.0", "artifact": {"kind": "archive", "url": "x"}}],
                        }],
                    }))
                return True, "ok"
            if label == "lifecycle-prove":
                return False, "package not found in live registry"
            return True, ""

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "nu_plugin_x",
                "description": "d",
                "repo": "https://x",
                "type": "plugin",
                "tags": ["plugin"],
                "version": "1.0.0",
                "nu_version": ">=0.114.0 <0.115.0",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path, prove=True)

        self.assertEqual(evidence["overall"], "fail")
        lifecycle = next(c for c in evidence["checks"] if c["name"] == "lifecycle")
        self.assertEqual(lifecycle["status"], "fail")
        self.assertIn("Lifecycle FAILED", evidence["human_summary"])

    @patch("validate_candidate._run_script")
    def test_whitespace_deferral_treated_as_missing(self, mock_run, _mock_gh):
        """A whitespace-only deferral is not a valid reason."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "nu_plugin_x",
                "description": "d",
                "repo": "https://x",
                "type": "plugin",
                "tags": ["plugin"],
                "version": "1.0.0",
                "nu_version": ">=0.114.0 <0.115.0",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            evidence = validate_candidate.validate_candidate(path, lifecycle_deferral="   ")

        self.assertEqual(evidence["overall"], "fail")
        self.assertNotIn("lifecycle_deferral", evidence)
        self.assertIn("Lifecycle evidence required", evidence["human_summary"])

    @patch("validate_candidate._run_script")
    def test_prove_and_deferral_mutually_exclusive(self, mock_run, _mock_gh):
        """--prove cannot be combined with --lifecycle-deferral."""
        mock_run.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {
                "owner": "test",
                "name": "nu_plugin_x",
                "description": "d",
                "repo": "https://x",
                "type": "plugin",
                "tags": ["plugin"],
                "version": "1.0.0",
                "nu_version": ">=0.114.0 <0.115.0",
                "artifact": {"kind": "archive", "url": "https://x/a.zip", "entry": "mod.nu"},
            }
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_candidate.validate_candidate(
                    path, prove=True, lifecycle_deferral="not yet staged"
                )


if __name__ == "__main__":
    unittest.main()
