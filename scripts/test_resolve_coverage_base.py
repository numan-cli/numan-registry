#!/usr/bin/env python3
"""Integration checks for the shallow-clone coverage base resolver."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
ZERO_SHA = "0" * 40
INDEX_PATH = "registry/index.json"
COPIED_SCRIPTS = (
    "audit_platform_coverage.py",
    "resolve_coverage_base.py",
    "lifecycle_proof_plan.py",
    "nu_version_constraint.py",
)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        text=True,
        capture_output=True,
        check=True,
    )


def index_with_proof(*, with_proof: bool) -> dict:
    version = {
        "version": "1.0.0",
        "nu_version": ">=0.114.0 <0.115.0",
        "artifact": {
            "kind": "binary",
            "targets": {
                "x86_64-unknown-linux-gnu": {
                    "url": "https://example.invalid/pkg.tar.gz",
                    "sha256": "a" * 64,
                    "executable_path": "nu_plugin_pkg",
                }
            },
        },
    }
    if with_proof:
        version["proofs"] = [
            {
                "os": "linux",
                "arch": "x86_64",
                "nu_version": "0.114.1",
                "result": "passed",
                "commands": ["install"],
                "timestamp": "2026-11-12T00:00:00Z",
            }
        ]
    return {
        "schema_version": 1,
        "updated_at": "2026-11-12T00:00:00Z",
        "registry_revision": "fixture",
        "packages": [
            {
                "id": {"owner": "acme", "name": "pkg"},
                "description": "fixture",
                "repo": "https://example.invalid/acme/pkg",
                "type": "plugin",
                "tags": ["plugin"],
                "versions": [version],
            }
        ],
    }


def write_index(repo: Path, *, with_proof: bool) -> None:
    target = repo / INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index_with_proof(with_proof=with_proof)), encoding="utf-8")


def copy_scripts(repo: Path) -> None:
    destination = repo / "scripts"
    destination.mkdir(parents=True, exist_ok=True)
    for name in COPIED_SCRIPTS:
        shutil.copy2(SCRIPTS / name, destination / name)


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "coverage-test@example.invalid")
    git(repo, "config", "user.name", "Coverage Test")
    copy_scripts(repo)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def shallow_clone(origin: Path, destination: Path) -> None:
    subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            "--no-local",
            origin.as_uri(),
            str(destination),
        ],
        text=True,
        capture_output=True,
        check=True,
    )


def parse_outputs(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def runner_env(repo: Path, *, event: str, base_sha: str = "", before: str = "") -> dict:
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_NAME": event,
            "PR_BASE_SHA": base_sha,
            "PUSH_BEFORE": before,
            "INPUT_BASE_REF": "",
            "RUNNER_TEMP": str(repo / ".runner-temp"),
            "GITHUB_OUTPUT": str(repo / ".github-output"),
            "GITHUB_STEP_SUMMARY": str(repo / ".step-summary.md"),
            "GITHUB_REPOSITORY": "example/repo",
            "INDEX_PATH": INDEX_PATH,
        }
    )
    env.pop("GITHUB_TOKEN", None)
    return env


def resolve(repo: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/resolve_coverage_base.py"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )


def audit(repo: Path, *, base_index: str = "", base_missing: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GITHUB_STEP_SUMMARY"] = str(repo / ".step-summary.md")
    args = [
        sys.executable,
        "scripts/audit_platform_coverage.py",
        "--index",
        INDEX_PATH,
        "--report-json",
        str(repo / "coverage.json"),
        "--report-md",
        str(repo / "coverage.md"),
        "--summary",
        env["GITHUB_STEP_SUMMARY"],
    ]
    if base_index:
        args.extend(["--base-index", base_index])
    elif base_missing:
        args.append("--base-missing")
    return subprocess.run(args, cwd=repo, env=env, text=True, capture_output=True)


class ResolveCoverageBaseTests(unittest.TestCase):
    def test_index_path_is_the_real_tracked_path(self):
        self.assertTrue((ROOT / INDEX_PATH).is_file())

    def test_shallow_pull_request_fetches_exact_base_and_audits_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin"
            init_repo(origin)
            write_index(origin, with_proof=False)
            base_sha = commit(origin, "base")
            write_index(origin, with_proof=True)
            commit(origin, "head")

            clone = root / "clone"
            shallow_clone(origin, clone)
            self.assertEqual(
                git(clone, "rev-list", "--count", "HEAD").stdout.strip(),
                "1",
            )
            self.assertNotEqual(
                subprocess.run(
                    ["git", "-C", str(clone), "cat-file", "-e", base_sha],
                    capture_output=True,
                ).returncode,
                0,
                "base commit unexpectedly present in shallow clone",
            )

            env = runner_env(clone, event="pull_request", base_sha=base_sha)
            result = resolve(clone, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = parse_outputs(clone / ".github-output")
            self.assertEqual(outputs["base_missing"], "false")
            base_index = Path(outputs["base_index"])
            self.assertTrue(base_index.is_file())
            self.assertFalse(json.loads(base_index.read_text(encoding="utf-8"))["packages"][0]["versions"][0].get("proofs"))
            self.assertIn("Base comparison", (clone / ".step-summary.md").read_text(encoding="utf-8"))

            audit_result = audit(clone, base_index=str(base_index))
            self.assertEqual(audit_result.returncode, 0, audit_result.stderr)
            report = json.loads((clone / "coverage.json").read_text(encoding="utf-8"))
            self.assertFalse(report["base_missing"])
            self.assertEqual(len(report["drift"]["newly_covered"]), 1)
            self.assertEqual(report["drift"]["newly_missing"], [])
            self.assertTrue((clone / "coverage.md").read_text(encoding="utf-8").strip())
            self.assertIn(
                "Newly covered",
                (clone / "coverage.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((clone / ".step-summary.md").read_text(encoding="utf-8").strip())

            push_clone = root / "push-clone"
            shallow_clone(origin, push_clone)
            push_env = runner_env(push_clone, event="push", before=base_sha)
            push_result = resolve(push_clone, push_env)
            self.assertEqual(push_result.returncode, 0, push_result.stderr)
            push_outputs = parse_outputs(push_clone / ".github-output")
            self.assertEqual(push_outputs["base_missing"], "false")
            self.assertTrue(Path(push_outputs["base_index"]).is_file())

    def test_shallow_first_commit_reports_all_targets_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin"
            init_repo(origin)
            write_index(origin, with_proof=True)
            commit(origin, "first index")

            clone = root / "clone"
            shallow_clone(origin, clone)
            env = runner_env(clone, event="push", before=ZERO_SHA)
            result = resolve(clone, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = parse_outputs(clone / ".github-output")
            self.assertEqual(outputs["base_index"], "")
            self.assertEqual(outputs["base_missing"], "true")
            self.assertIn(
                "all current targets are reported as new",
                (clone / ".step-summary.md").read_text(encoding="utf-8"),
            )

            audit_result = audit(clone, base_missing=True)
            self.assertEqual(audit_result.returncode, 0, audit_result.stderr)
            report = json.loads((clone / "coverage.json").read_text(encoding="utf-8"))
            self.assertTrue(report["base_missing"])
            self.assertEqual(report["base"]["totals"]["published_targets"], 0)
            self.assertEqual(len(report["drift"]["added_targets"]), 1)
            self.assertIn(
                "No base index exists at the comparison revision",
                (clone / "coverage.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((clone / ".step-summary.md").read_text(encoding="utf-8").strip())

    def test_api_fallback_materializes_base_when_git_fetch_fails(self):
        body = json.dumps(index_with_proof(with_proof=False)).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.github.raw")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "repo"
                init_repo(repo)
                env = runner_env(repo, event="pull_request", base_sha="a" * 40)
                env.update(
                    {
                        "GITHUB_TOKEN": "test-token",
                        "GITHUB_REPOSITORY": "example/repo",
                        "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}",
                    }
                )
                result = resolve(repo, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs = parse_outputs(repo / ".github-output")
                self.assertEqual(outputs["base_missing"], "false")
                base_index = Path(outputs["base_index"])
                self.assertEqual(
                    json.loads(base_index.read_text(encoding="utf-8")),
                    json.loads(body),
                )
                self.assertIn(
                    "GitHub contents API",
                    (repo / ".step-summary.md").read_text(encoding="utf-8"),
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_base_commit_without_index_reports_all_targets_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin"
            init_repo(origin)
            base_sha = commit(origin, "base without index")
            write_index(origin, with_proof=False)
            commit(origin, "head introduces index")

            clone = root / "clone"
            shallow_clone(origin, clone)
            env = runner_env(clone, event="pull_request", base_sha=base_sha)
            result = resolve(clone, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = parse_outputs(clone / ".github-output")
            self.assertEqual(outputs["base_index"], "")
            self.assertEqual(outputs["base_missing"], "true")
            self.assertIn(
                "base commit has no registry/index.json",
                (clone / ".step-summary.md").read_text(encoding="utf-8"),
            )

            audit_result = audit(clone, base_missing=True)
            self.assertEqual(audit_result.returncode, 0, audit_result.stderr)
            report = json.loads((clone / "coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["drift"]["added_targets"]), 1)
            self.assertEqual(report["base"]["totals"]["published_targets"], 0)


if __name__ == "__main__":
    unittest.main()
