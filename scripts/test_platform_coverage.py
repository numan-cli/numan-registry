#!/usr/bin/env python3
"""Unit checks for scripts/audit_platform_coverage.py."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "audit_platform_coverage.py"
SPEC = importlib.util.spec_from_file_location("audit_platform_coverage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)

LINUX_TRIPLE = "x86_64-unknown-linux-gnu"
WINDOWS_TRIPLE = "x86_64-pc-windows-msvc"


def proof(
    *,
    os_name: str = "linux",
    arch: str = "x86_64",
    nu_version: str = "0.114.1",
    result: str = "passed",
    commands: list[str] | None = None,
) -> dict:
    value = {
        "os": os_name,
        "arch": arch,
        "nu_version": nu_version,
        "result": result,
        "timestamp": "2026-11-12T00:00:00Z",
    }
    if commands is not None:
        value["commands"] = commands
    return value


def version(
    *,
    targets: tuple[str, ...] = (LINUX_TRIPLE,),
    proofs: list[dict] | None = None,
    yanked: bool = False,
    constraint: str = ">=0.114.0 <0.115.0",
    value: str = "1.0.0",
) -> dict:
    result = {
        "version": value,
        "nu_version": constraint,
        "artifact": {
            "kind": "binary",
            "targets": {
                triple: {
                    "url": f"https://example.invalid/{triple}.tar.gz",
                    "sha256": "a" * 64,
                    "executable_path": "nu_plugin_pkg",
                }
                for triple in targets
            },
        },
    }
    if proofs is not None:
        result["proofs"] = proofs
    if yanked:
        result["yanked"] = {
            "reason_code": "nu-plugin-protocol-mismatch",
            "evidence_url": "https://example.invalid/evidence.md",
        }
    return result


def package(package_version: dict, *, owner: str = "acme", name: str = "pkg") -> dict:
    return {
        "id": {"owner": owner, "name": name},
        "description": "fixture",
        "repo": f"https://example.invalid/{owner}/{name}",
        "type": "plugin",
        "tags": ["plugin"],
        "versions": [package_version],
    }


def index(pkg: dict) -> dict:
    return {
        "schema_version": 1,
        "updated_at": "2026-11-12T00:00:00Z",
        "registry_revision": "fixture",
        "packages": [pkg],
    }


class SnapshotTests(unittest.TestCase):
    def test_covered_requires_passing_proof_with_usable_commands(self):
        snapshot = AUDIT.build_snapshot(
            index(package(version(proofs=[proof(commands=["install"])]))),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "covered")
        self.assertEqual(snapshot["items"][0]["proof_nu_version"], "0.114.1")
        self.assertEqual(snapshot["totals"]["covered_targets"], 1)
        self.assertEqual(snapshot["totals"]["coverage_percent"], 100.0)

    def test_missing_proof_is_not_inferred_from_verified_with(self):
        fixture = version()
        fixture["verified_with"] = ["0.114.1"]
        snapshot = AUDIT.build_snapshot(index(package(fixture)), "fixture")
        self.assertEqual(snapshot["items"][0]["state"], "missing")
        self.assertEqual(snapshot["items"][0]["reason"], "no_proof")

    def test_failed_proof_is_missing(self):
        snapshot = AUDIT.build_snapshot(
            index(
                package(
                    version(
                        proofs=[proof(result="failed", commands=["install"])],
                    )
                )
            ),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "missing")
        self.assertEqual(snapshot["items"][0]["reason"], "failed")

    def test_passed_proof_without_commands_is_missing(self):
        snapshot = AUDIT.build_snapshot(
            index(package(version(proofs=[proof()]))),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "missing")
        self.assertEqual(snapshot["items"][0]["reason"], "unusable_commands")

    def test_proof_outside_claimed_nu_range_is_missing(self):
        snapshot = AUDIT.build_snapshot(
            index(
                package(
                    version(
                        proofs=[proof(nu_version="0.113.1", commands=["install"])],
                    )
                )
            ),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "missing")
        self.assertEqual(snapshot["items"][0]["reason"], "nu_mismatch")

    def test_newest_matching_proof_is_selected(self):
        snapshot = AUDIT.build_snapshot(
            index(
                package(
                    version(
                        proofs=[
                            proof(nu_version="0.114.1", commands=["install"]),
                            proof(nu_version="0.114.2", commands=["install"]),
                        ]
                    )
                )
            ),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["proof_nu_version"], "0.114.2")

    def test_yanked_is_separate_from_missing(self):
        snapshot = AUDIT.build_snapshot(
            index(
                package(
                    version(
                        proofs=[proof(commands=["install"])],
                        yanked=True,
                    )
                )
            ),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "yanked")
        self.assertEqual(snapshot["totals"]["missing_targets"], 0)
        self.assertEqual(snapshot["totals"]["yanked_targets"], 1)
        self.assertIsNone(snapshot["totals"]["coverage_percent"])

    def test_unmapped_artifact_triple_is_not_counted_as_covered_or_missing(self):
        snapshot = AUDIT.build_snapshot(
            index(package(version(targets=("aarch64-pc-windows-msvc",)))),
            "fixture",
        )
        self.assertEqual(snapshot["items"][0]["state"], "unmapped")
        self.assertEqual(snapshot["totals"]["unmapped_targets"], 1)
        self.assertEqual(snapshot["totals"]["covered_targets"], 0)
        self.assertEqual(snapshot["totals"]["missing_targets"], 0)


class DriftTests(unittest.TestCase):
    def test_newly_covered_and_delta(self):
        base = index(package(version(proofs=[])))
        head = index(package(version(proofs=[proof(commands=["install"])])))
        report = AUDIT.build_report(head, base)
        self.assertTrue(report["drift"]["changed"])
        self.assertEqual(len(report["drift"]["newly_covered"]), 1)
        self.assertEqual(report["drift"]["newly_missing"], [])
        self.assertEqual(report["drift"]["coverage_delta"]["covered_targets"], 1)
        self.assertEqual(report["drift"]["coverage_delta"]["missing_targets"], -1)

    def test_covered_to_missing_is_regression(self):
        base = index(package(version(proofs=[proof(commands=["install"])])))
        head = index(package(version(proofs=[])))
        report = AUDIT.build_report(head, base)
        self.assertTrue(report["drift"]["has_coverage_regression"])
        self.assertEqual(len(report["drift"]["newly_missing"]), 1)
        self.assertEqual(report["drift"]["coverage_delta"]["covered_targets"], -1)

    def test_covered_to_yanked_is_regression_but_not_missing(self):
        base = index(package(version(proofs=[proof(commands=["install"])])))
        head = index(package(version(proofs=[proof(commands=["install"])], yanked=True)))
        report = AUDIT.build_report(head, base)
        self.assertTrue(report["drift"]["has_coverage_regression"])
        self.assertEqual(report["drift"]["newly_missing"], [])
        self.assertEqual(len(report["drift"]["newly_yanked"]), 1)

    def test_removed_covered_target_is_regression(self):
        base = index(
            package(
                version(
                    targets=(LINUX_TRIPLE, WINDOWS_TRIPLE),
                    proofs=[proof(commands=["install"])],
                )
            )
        )
        head = index(
            package(
                version(
                    targets=(WINDOWS_TRIPLE,),
                    proofs=[proof(commands=["install"])],
                )
            )
        )
        report = AUDIT.build_report(head, base)
        self.assertTrue(report["drift"]["has_coverage_regression"])
        self.assertEqual(
            report["drift"]["coverage_regressions"][0]["target"],
            "linux/x86_64",
        )
        self.assertEqual(report["drift"]["removed_targets"][0]["target"], "linux/x86_64")

    def test_added_target_is_reported(self):
        base = index(package(version(proofs=[])))
        head = index(package(version(targets=(LINUX_TRIPLE, WINDOWS_TRIPLE), proofs=[])))
        report = AUDIT.build_report(head, base)
        self.assertEqual(len(report["drift"]["added_targets"]), 1)
        self.assertEqual(report["drift"]["added_targets"][0]["target"], "windows/x86_64")

    def test_identical_indexes_have_no_drift(self):
        fixture = index(package(version(proofs=[proof(commands=["install"])])))
        report = AUDIT.build_report(fixture, fixture)
        self.assertFalse(report["drift"]["changed"])
        self.assertIn("No platform-proof coverage drift detected.", AUDIT.render_markdown(report))

    def test_missing_base_reports_all_targets_as_new(self):
        fixture = index(package(version(proofs=[proof(commands=["install"])])))
        report = AUDIT.build_report(fixture, base_missing=True)
        self.assertTrue(report["base_missing"])
        self.assertTrue(report["drift"]["base_missing"])
        self.assertEqual(report["base"]["totals"]["published_targets"], 0)
        self.assertEqual(report["drift"]["newly_covered"], [])
        self.assertEqual(len(report["drift"]["added_targets"]), 1)
        self.assertIn(
            "No base index exists at the comparison revision",
            AUDIT.render_markdown(report),
        )


class CliTests(unittest.TestCase):
    def _write_index(self, path: Path, fixture: dict) -> None:
        path.write_text(json.dumps(fixture), encoding="utf-8")

    def test_cli_writes_reports_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head_path = root / "head.json"
            base_path = root / "base.json"
            report_path = root / "report.json"
            markdown_path = root / "report.md"
            summary_path = root / "summary.md"
            self._write_index(base_path, index(package(version(proofs=[]))))
            self._write_index(
                head_path,
                index(package(version(proofs=[proof(commands=["install"])]))),
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                rc = AUDIT.main(
                    [
                        "--index",
                        str(head_path),
                        "--base-index",
                        str(base_path),
                        "--report-json",
                        str(report_path),
                        "--report-md",
                        str(markdown_path),
                        "--summary",
                        str(summary_path),
                    ]
                )

            self.assertEqual(rc, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], AUDIT.AUDIT_SCHEMA)
            self.assertEqual(report["head"]["totals"]["covered_targets"], 1)
            self.assertIn("Newly covered (1)", markdown_path.read_text(encoding="utf-8"))
            self.assertIn("Newly covered (1)", summary_path.read_text(encoding="utf-8"))
            self.assertIn("# Platform-proof coverage audit", stdout.getvalue())

    def test_cli_fail_on_regression_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head_path = root / "head.json"
            base_path = root / "base.json"
            self._write_index(
                base_path,
                index(package(version(proofs=[proof(commands=["install"])]))),
            )
            self._write_index(head_path, index(package(version(proofs=[]))))

            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                rc = AUDIT.main(
                    [
                        "--index",
                        str(head_path),
                        "--base-index",
                        str(base_path),
                        "--fail-on-regression",
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertIn("coverage regressions detected", stderr.getvalue())

    def test_cli_base_missing_reports_all_targets_as_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            report_path = root / "report.json"
            summary_path = root / "summary.md"
            self._write_index(
                index_path,
                index(package(version(proofs=[proof(commands=["install"])]))),
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                rc = AUDIT.main(
                    [
                        "--index",
                        str(index_path),
                        "--base-missing",
                        "--report-json",
                        str(report_path),
                        "--summary",
                        str(summary_path),
                    ]
                )
            self.assertEqual(rc, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["base_missing"])
            self.assertEqual(len(report["drift"]["added_targets"]), 1)
            self.assertIn("No base index exists", summary_path.read_text(encoding="utf-8"))

    def test_cli_without_base_records_current_snapshot_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            self._write_index(
                index_path,
                index(package(version(proofs=[proof(commands=["install"])]))),
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                rc = AUDIT.main(["--index", str(index_path)])
            self.assertEqual(rc, 0)
            self.assertIn("No base index was supplied", stdout.getvalue())

    def test_cli_rejects_invalid_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index_path.write_text("not json", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                rc = AUDIT.main(["--index", str(index_path)])
            self.assertEqual(rc, 2)
            self.assertIn("cannot parse", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
