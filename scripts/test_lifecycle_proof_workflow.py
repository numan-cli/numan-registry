#!/usr/bin/env python3
"""Unit checks for the reusable lifecycle proof workflow helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def load_mod(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plan_mod = load_mod("lifecycle_proof_plan", "lifecycle_proof_plan.py")
record_mod = load_mod("lifecycle_proof_record", "lifecycle_proof_record.py")
collect_mod = load_mod("lifecycle_proof_collect", "lifecycle_proof_collect.py")

WINDOWS_PASS_LOG = """\
package=acme/pkg
package_version=1.2.3
nu_version=0.116.1
started_at=2026-11-11T12:00:00Z
platform=windows/x86_64
runner_image=Windows Server 2025 test
numan_version=numan 0.4.0
numan_source=source-build
numan_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
candidate_index_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
nu_archive_url=https://example.invalid/nu.zip
nu_archive_sha256=
nu_exe_sha256=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
command: lifecycle-prove
OK: lifecycle-prove passed.
finished_at=2026-11-11T12:01:00Z
exit_code=0
"""

PASS_LOG = """\
package=acme/pkg
package_version=1.2.3
nu_version=0.116.1
started_at=2026-11-11T12:00:00Z
platform=linux/aarch64
runner_image=ubuntu24-arm64 test
numan_version=numan 0.4.0
numan_source=release-asset
numan_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
candidate_index_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
nu_archive_url=https://example.invalid/nu.tar.gz
nu_archive_sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
nu_exe_sha256=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
command: lifecycle-prove
OK: lifecycle-prove passed.
finished_at=2026-11-11T12:01:00Z
exit_code=0
"""


def index_for(package_type="plugin", activation=None):
    version = {
        "version": "1.2.3",
        "nu_version": ">=0.116.0 <0.117.0",
        "artifact": {
            "kind": "binary",
            "targets": {
                "aarch64-unknown-linux-gnu": {
                    "url": "https://example.invalid/linux.tar.gz",
                    "sha256": "a" * 64,
                    "executable_path": "nu_plugin_pkg",
                },
                "aarch64-apple-darwin": {
                    "url": "https://example.invalid/macos.tar.gz",
                    "sha256": "b" * 64,
                    "executable_path": "nu_plugin_pkg",
                },
                "x86_64-pc-windows-msvc": {
                    "url": "https://example.invalid/windows.zip",
                    "sha256": "c" * 64,
                    "executable_path": "nu_plugin_pkg.exe",
                },
            },
        },
    }
    if activation is not None:
        version["activation"] = activation
    return {
        "schema_version": 1,
        "updated_at": "2026-11-11T00:00:00Z",
        "packages": [
            {
                "id": {"owner": "acme", "name": "pkg"},
                "description": "test",
                "repo": "https://example.invalid/repo",
                "type": package_type,
                "tags": [],
                "versions": [version],
            }
        ],
    }


class LifecycleProofPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.index_path = Path(self.tmp.name) / "index.json"
        self.index_path.write_text(json.dumps(index_for()), encoding="utf-8")

    def build(self, **overrides):
        values = {
            "package": "acme/pkg",
            "package_version": "1.2.3",
            "nu_version": "0.116.1",
            "targets": '["linux/aarch64","macos/aarch64"]',
            "activation_kind": "",
            "commands": "",
            "numan_version": "0.4.0",
            "numan_repo": "numan-cli/numan",
            "index_path": self.index_path,
        }
        index_path = values.pop("index_path")
        values.update(overrides)
        return plan_mod.build_plan(plan_mod.ProofRequest(**values), index_path)

    def test_resolves_real_runner_matrix_and_default_commands(self):
        plan = self.build()
        self.assertEqual(plan["activation_kind"], "plugin")
        self.assertEqual(plan["commands"], plan_mod.STANDARD_COMMANDS)
        targets = plan["matrix"]["include"]
        self.assertEqual(targets[0]["runner"], "ubuntu-24.04-arm")
        self.assertEqual(targets[1]["runner"], "macos-15")
        self.assertEqual(
            targets[0]["log_name"],
            "acme__pkg__1.2.3__nu-0.116.1__linux-aarch64.log",
        )
        self.assertEqual(targets[0]["artifact_sha256"], "a" * 64)

    def test_resolves_windows_target_to_hosted_runner_and_zip(self):
        target = self.build(targets='["windows/x86_64"]')["matrix"]["include"][0]
        self.assertEqual(target["runner"], "windows-latest")
        self.assertEqual(target["triple"], "x86_64-pc-windows-msvc")
        self.assertEqual(target["archive"], "zip")
        self.assertEqual(target["artifact_sha256"], "c" * 64)
        self.assertEqual(
            target["log_name"],
            "acme__pkg__1.2.3__nu-0.116.1__windows-x86_64.log",
        )

    def test_infers_module_and_install_only_kinds(self):
        self.index_path.write_text(
            json.dumps(index_for("module", {"kind": "nu-module"})), encoding="utf-8"
        )
        self.assertEqual(self.build()["activation_kind"], "nu-module")
        self.index_path.write_text(json.dumps(index_for("module")), encoding="utf-8")
        plan = self.build()
        self.assertEqual(plan["activation_kind"], "install-only")
        self.assertEqual(plan["commands"], plan_mod.INSTALL_ONLY_COMMANDS)

    def test_explicit_commands_override_kind_defaults(self):
        plan = self.build(commands='["init","install","gc"]')
        self.assertEqual(plan["commands"], ["init", "install", "gc"])

    def test_rejects_invalid_inputs(self):
        cases = [
            ({"targets": '["solaris/sparc"]'}, "unsupported target"),
            ({"targets": '["linux/aarch64","linux/aarch64"]'}, "duplicate target"),
            ({"activation_kind": "nu-module"}, "does not match"),
            ({"commands": '["init","explode"]'}, "unsupported lifecycle command"),
            ({"commands": '["install"]'}, "must include init"),
            ({"nu_version": "0.115.1"}, "does not satisfy"),
            ({"nu_version": "0.116"}, "exact MAJOR.MINOR.PATCH"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    self.build(**overrides)

    def test_rejects_target_without_published_artifact(self):
        data = index_for()
        del data["packages"][0]["versions"][0]["artifact"]["targets"]["aarch64-apple-darwin"]
        self.index_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no published artifact"):
            self.build(targets='["macos/aarch64"]')

    def test_github_output_is_compact_single_line_values(self):
        plan = self.build()
        output = Path(self.tmp.name) / "github-output"
        plan_mod.write_github_output(output, plan)
        lines = output.read_text(encoding="utf-8").splitlines()
        values = dict(line.split("=", 1) for line in lines)
        self.assertEqual(values["package"], "acme/pkg")
        self.assertEqual(json.loads(values["commands"]), plan["commands"])
        self.assertEqual(json.loads(values["matrix"])["include"][0]["runner"], "ubuntu-24.04-arm")


class LifecycleProofRecordTests(unittest.TestCase):
    def test_creates_passed_record_with_commands(self):
        proof = record_mod.build_proof(
            PASS_LOG,
            record_mod.ProofExpectation(
                commands=["init", "install", "gc"],
                package="acme/pkg",
                package_version="1.2.3",
                nu_version="0.116.1",
            ),
        )
        self.assertEqual(
            proof,
            {
                "os": "linux",
                "arch": "aarch64",
                "nu_version": "0.116.1",
                "result": "passed",
                "timestamp": "2026-11-11T12:01:00Z",
                "commands": ["init", "install", "gc"],
            },
        )

    def test_creates_windows_passed_record(self):
        proof = record_mod.build_proof(
            WINDOWS_PASS_LOG,
            record_mod.ProofExpectation(
                commands=["init", "install", "gc"],
                package="acme/pkg",
                package_version="1.2.3",
                nu_version="0.116.1",
            ),
        )
        self.assertEqual(proof["os"], "windows")
        self.assertEqual(proof["arch"], "x86_64")
        self.assertEqual(proof["result"], "passed")
        self.assertEqual(proof["commands"], ["init", "install", "gc"])

    def test_creates_failed_record_without_commands(self):
        failed = PASS_LOG.replace("OK: lifecycle-prove passed.\n", "").replace(
            "exit_code=0", "exit_code=7"
        )
        proof = record_mod.build_proof(
            failed, record_mod.ProofExpectation(commands=["init", "install"])
        )
        self.assertEqual(proof["result"], "failed")
        self.assertNotIn("commands", proof)

    def test_rejects_mismatched_expected_package(self):
        with self.assertRaisesRegex(ValueError, "does not match expected"):
            record_mod.build_proof(
                PASS_LOG,
                record_mod.ProofExpectation(commands=["init"], package="other/pkg"),
            )

    def test_later_equals_lines_do_not_overwrite_header(self):
        text = PASS_LOG + "sha256=not-a-header\nnu_version=9.9.9\n"
        proof = record_mod.build_proof(text, record_mod.ProofExpectation(commands=["init"]))
        self.assertEqual(proof["nu_version"], "0.116.1")


class LifecycleProofCollectTests(unittest.TestCase):
    def make_artifacts(self, proofs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for index, proof in enumerate(proofs):
            directory = root / f"lifecycle-proof-{index}"
            directory.mkdir()
            (directory / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
        return root

    def test_collects_sorted_proofs_and_summary(self):
        root = self.make_artifacts(
            [
                {
                    "os": "macos",
                    "arch": "aarch64",
                    "nu_version": "0.116.1",
                    "result": "passed",
                    "timestamp": "2026-11-11T12:00:00Z",
                    "commands": ["init"],
                },
                {
                    "os": "linux",
                    "arch": "aarch64",
                    "nu_version": "0.116.1",
                    "result": "passed",
                    "timestamp": "2026-11-11T12:00:00Z",
                    "commands": ["init"],
                },
                {
                    "os": "windows",
                    "arch": "x86_64",
                    "nu_version": "0.116.1",
                    "result": "passed",
                    "timestamp": "2026-11-11T12:00:00Z",
                    "commands": ["init"],
                },
            ]
        )
        proofs = collect_mod.load_proofs(root)
        self.assertEqual(
            [proof["os"] for proof in proofs], ["windows", "linux", "macos"]
        )
        summary = collect_mod.render_summary(proofs, "acme/pkg", "1.2.3", "0.116.1")
        self.assertIn("acme/pkg@1.2.3", summary)
        self.assertIn("| windows | x86_64 | passed |", summary)
        self.assertIn("| linux | aarch64 | passed |", summary)

    def test_rejects_duplicate_targets(self):
        root = self.make_artifacts(
            [
                {
                    "os": "linux",
                    "arch": "aarch64",
                    "nu_version": "0.116.1",
                    "result": "passed",
                    "timestamp": "2026-11-11T12:00:00Z",
                    "commands": ["init"],
                },
                {
                    "os": "linux",
                    "arch": "aarch64",
                    "nu_version": "0.116.1",
                    "result": "passed",
                    "timestamp": "2026-11-11T12:00:00Z",
                    "commands": ["init"],
                },
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate proof"):
            collect_mod.load_proofs(root)

    def test_main_writes_batch_and_fails_on_failed_proof(self):
        root = self.make_artifacts(
            [
                {
                    "os": "linux",
                    "arch": "aarch64",
                    "nu_version": "0.116.1",
                    "result": "failed",
                    "timestamp": "2026-11-11T12:00:00Z",
                }
            ]
        )
        output = root / "proofs.json"
        summary = root / "proofs.md"
        code = collect_mod.main(
            [
                "--artifacts",
                str(root),
                "--package",
                "acme/pkg",
                "--package-version",
                "1.2.3",
                "--nu-version",
                "0.116.1",
                "--output",
                str(output),
                "--summary",
                str(summary),
                "--fail-on-failure",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))[0]["result"], "failed")
        self.assertIn("failed", summary.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
