#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_intake_pr

BRANCH = "chore/sync-intake-candidates"
SCRIPTS_DIR = Path(__file__).resolve().parent
GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=check,
    )


class FakeGh:
    def __init__(self, remote=None):
        self.remote = remote
        self.prs = []
        self.fail_create = False
        self.fail_merge = False
        self.list_payload = None
        self.oid_override = None
        self.calls = []
        self._n = 0

    def _remote_oid(self):
        if self.remote is None:
            return ""
        r = subprocess.run(
            ["git", "rev-parse", f"refs/heads/{BRANCH}"],
            cwd=self.remote,
            capture_output=True,
            text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else ""

    def __call__(self, args, cwd):
        self.calls.append(list(args))

        def cp(rc, out=""):
            return subprocess.CompletedProcess(["gh", *args], rc, out, "")

        if args[:2] == ["pr", "list"]:
            if self.list_payload is not None:
                return cp(0, self.list_payload)
            oid = (
                self.oid_override
                if self.oid_override is not None
                else self._remote_oid()
            )
            for pr in self.prs:
                pr["headRefOid"] = oid
            return cp(0, json.dumps(self.prs))
        if args[:2] == ["pr", "create"]:
            if self.fail_create:
                return cp(1)
            self._n += 1
            url = f"https://example.test/repo/pull/{self._n}"
            self.prs.append(
                {"number": self._n, "url": url, "headRefOid": "", "autoMergeRequest": None}
            )
            return cp(0, url + "\n")
        if args[:2] == ["pr", "merge"]:
            if self.fail_merge:
                return cp(1)
            for pr in self.prs:
                if pr["url"] in args:
                    pr["autoMergeRequest"] = {"enabledAt": "now"}
            return cp(0)
        return cp(0)


class BareRemoteCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.remote = self.tmp / "remote.git"
        self.repo = self.tmp / "work"
        self.fake_gh = FakeGh(self.remote)
        self._gh_patch = patch.object(sync_intake_pr, "_gh", self.fake_gh)
        self._gh_patch.start()
        self._calls = []
        self.fail_push = False
        orig_run = sync_intake_pr._run

        def spy(cmd, cwd):
            self._calls.append([str(c) for c in cmd])
            if self.fail_push and list(cmd)[:2] == ["git", "push"]:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "! [rejected] non-fast-forward"
                )
            return orig_run(cmd, cwd)

        self._run_patch = patch.object(sync_intake_pr, "_run", spy)
        self._run_patch.start()
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        for rel in ("scripts/sync-intake-candidates.py", "scripts/archive_formats.py", "scripts/gh_helpers.py"):
            dst = self.repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(SCRIPTS_DIR / Path(rel).name, dst)
        (self.repo / "registry").mkdir()
        (self.repo / "registry" / "index.json").write_text(
            json.dumps({"packages": []}), encoding="utf-8"
        )
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "intake-state.json").write_text(
            json.dumps({"ready": [], "mirror": [], "blocked": [], "changelog": []}),
            encoding="utf-8",
        )
        (self.repo / "docs" / "upstream-release-outreach.md").write_text(
            "# Upstream release outreach\n", encoding="utf-8"
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "init")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.repo, "fetch", "-q", "origin")
        git(self.repo, "branch", "--set-upstream-to", "origin/main")

    def tearDown(self):
        self._run_patch.stop()
        self._gh_patch.stop()
        self._tmp.cleanup()

    def push_branch(self, message: str, path: str, content: str) -> str:
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(content, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        git(self.repo, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def test_initial_change_creates_one_pr(self):
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertTrue(url.endswith("/pull/1"))
        self.assertEqual(len(self.fake_gh.prs), 1)
        self.assertEqual(len([c for c in self.fake_gh.calls if c[:2] == ["pr", "create"]]), 1)
        remote = subprocess.run(
            ["git", "rev-parse", f"refs/heads/{BRANCH}"],
            cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(remote, git(self.repo, "rev-parse", "HEAD").stdout.strip())

    def test_noop_rerun_no_extra_commit_or_pr(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        creates = len([c for c in self.fake_gh.calls if c[:2] == ["pr", "create"]])
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertTrue(url.endswith("/pull/1"))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), head)
        self.assertEqual(len([c for c in self.fake_gh.calls if c[:2] == ["pr", "create"]]), creates)

    def test_tree_equal_to_main_returns_none_without_push_or_pr(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.fake_gh.prs.clear()
        git(self.repo, "push", "-q", "origin", f"{BRANCH}:refs/heads/main")
        git(self.repo, "fetch", "-q", "origin")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "merge", "--ff-only", "origin/main")
        before = len(self._calls)
        result = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIsNone(result)
        self.assertFalse(
            any(c[:2] == ["git", "push"] for c in self._calls[before:])
        )
        self.assertFalse(
            any(
                c[:3] in (["gh", "pr", "create"], ["gh", "pr", "merge"])
                for c in self._calls[before:]
            )
        )

    def test_second_change_updates_same_branch_and_pr(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        first_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "switch", "-q", "main")
        state = json.loads(
            (self.repo / "docs" / "intake-state.json").read_text(encoding="utf-8")
        )
        state["changelog"] = [{"date": "2026-01-01", "change": "second sync"}]
        (self.repo / "docs" / "intake-state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        git(self.repo, "add", "docs/intake-state.json")
        git(self.repo, "commit", "-q", "-m", "maintainer state change on main")
        git(self.repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.repo, "fetch", "-q", "origin")
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertTrue(url.endswith("/pull/1"))
        self.assertEqual(len(self.fake_gh.prs), 1)
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(head, first_head)
        ancestor = git(
            self.repo, "merge-base", "--is-ancestor", first_head, "HEAD", check=False
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_maintainer_commit_outside_scope_fails_review(self):
        sha = self.push_branch("maintainer edit", "docs/maintainer-note.md", "keep me\n")
        git(self.repo, "switch", "-q", "main")
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("outside the generated paths", str(ctx.exception))
        self.assertIn("docs/maintainer-note.md", str(ctx.exception))
        ancestor = git(
            self.repo, "merge-base", "--is-ancestor", sha, "HEAD", check=False
        )
        self.assertEqual(ancestor.returncode, 0)
        self.assertFalse(
            any("scripts/sync-intake-candidates.py" in c for c in self._calls)
        )
        self.assertFalse(any(c[:2] == ["git", "push"] for c in self._calls))
        self.assertEqual(self.fake_gh.prs, [])

    def test_maintainer_changelog_edit_survives_normal_sync(self):
        state = json.loads(
            (self.repo / "docs" / "intake-state.json").read_text(encoding="utf-8")
        )
        state["changelog"] = [
            {"date": "2026-02-02", "change": "maintainer triage note"}
        ]
        content = json.dumps(state)
        (self.repo / "docs" / "intake-state.json").write_text(
            content, encoding="utf-8"
        )
        sha = self.push_branch("maintainer changelog", "docs/intake-state.json", content)
        git(self.repo, "switch", "-q", "main")
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIsNotNone(url)
        ancestor = git(
            self.repo, "merge-base", "--is-ancestor", sha, "HEAD", check=False
        )
        self.assertEqual(ancestor.returncode, 0)
        doc = (self.repo / "docs" / "intake-candidates.md").read_text(encoding="utf-8")
        self.assertIn("maintainer triage note", doc)

    def test_open_pr_head_oid_mismatch_fails_before_mutation(self):
        sha = self.push_branch("synced docs", "docs/intake-state.json", '{"ready":[],"mirror":[],"blocked":[],"changelog":[]}')
        self.fake_gh.prs.append(
            {"number": 3, "url": "https://example.test/repo/pull/3",
             "headRefOid": "", "autoMergeRequest": None}
        )
        self.fake_gh.oid_override = "a" * 40
        git(self.repo, "switch", "-q", "main")
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("does not match", str(ctx.exception))
        allowed = {"status", "fetch", "rev-parse"}
        for c in self._calls:
            if c[0] == "git":
                self.assertIn(c[1], allowed)
            else:
                self.assertEqual(c[:3], ["gh", "pr", "list"])
        self.assertFalse(
            any("scripts/sync-intake-candidates.py" in c for c in self._calls)
        )
        self.assertEqual(sha, git(self.repo, "rev-parse", f"origin/{BRANCH}").stdout.strip())

    def test_malformed_pr_list_output_fails(self):
        self.fake_gh.list_payload = "not json"
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("malformed", str(ctx.exception))

    def test_duplicate_open_prs_fail(self):
        entry = {"number": 1, "url": "https://example.test/repo/pull/1",
                 "headRefOid": "a" * 40, "autoMergeRequest": None}
        self.fake_gh.prs.extend([entry, dict(entry, number=2, url="x/2")])
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("expected at most one", str(ctx.exception))



    def test_non_ff_push_fails_without_force_or_merge(self):
        self.fail_push = True
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("push", str(ctx.exception))
        flat = [c for cmd in self._calls for c in cmd]
        self.assertNotIn("--force", flat)
        self.assertNotIn("--force-with-lease", flat)
        self.assertNotIn("reset", flat)
        self.assertFalse(
            any(c[:2] == ["pr", "merge"] for c in self.fake_gh.calls)
        )
        self.assertFalse(
            any(c[:2] == ["pr", "create"] for c in self.fake_gh.calls)
        )

    def test_generated_path_symlink_rejected(self):
        with patch("pathlib.Path.is_symlink", return_value=True):
            with self.assertRaises(sync_intake_pr.SyncError) as ctx:
                sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("symlink", str(ctx.exception))
        self.assertIn("human review", str(ctx.exception))
        self.assertFalse(
            any("scripts/sync-intake-candidates.py" in c for c in self._calls)
        )
        self.assertFalse(any(c[:2] == ["git", "push"] for c in self._calls))
        self.assertFalse(
            any(c[:2] == ["pr", "create"] for c in self.fake_gh.calls)
        )
        self.assertFalse(
            any(c[:2] == ["pr", "merge"] for c in self.fake_gh.calls)
        )

    def test_reuse_after_squash_merge_persistent_branch(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "merge", "--squash", BRANCH)
        git(self.repo, "commit", "-q", "-m", "squash merge intake sync")
        git(self.repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.repo, "fetch", "-q", "origin")
        self.fake_gh.prs.clear()
        before_calls = len(self._calls)
        before_gh = len(self.fake_gh.calls)
        result = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIsNone(result)
        self.assertFalse(
            any(c[:2] == ["git", "push"] for c in self._calls[before_calls:])
        )
        self.assertFalse(
            any(c[:2] == ["pr", "create"] for c in self.fake_gh.calls[before_gh:])
        )

    def test_interrupted_before_pr_creation_reuses_branch(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.fake_gh.prs.clear()
        git(self.repo, "switch", "-q", "main")
        head = git(self.repo, "rev-parse", f"origin/{BRANCH}").stdout.strip()
        before = len(self.fake_gh.calls)
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        creates = [
            c for c in self.fake_gh.calls[before:] if c[:2] == ["pr", "create"]
        ]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(self.fake_gh.prs), 1)
        self.assertIn(url, [p["url"] for p in self.fake_gh.prs])
        self.assertEqual(
            git(self.repo, "rev-parse", "HEAD").stdout.strip(),
            git(self.repo, "merge-base", "HEAD", f"origin/{BRANCH}").stdout.strip(),
        )
        self.assertIn(head, git(self.repo, "rev-list", "HEAD").stdout)

    def test_pr_create_failure_surfaces_then_rerun_succeeds(self):
        self.fake_gh.fail_create = True
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("pr create", str(ctx.exception))
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.fake_gh.fail_create = False
        url = sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertTrue(url.endswith("/pull/1"))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), head)
        self.assertEqual(len(self.fake_gh.prs), 1)

    def test_auto_merge_failure_surfaces(self):
        self.fake_gh.fail_merge = True
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("auto", str(ctx.exception))
        self.assertIn("Recovery", str(ctx.exception))

    def test_branch_conflict_fails_without_force_or_reset(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        git(self.repo, "switch", "-q", "main")
        (self.repo / "docs" / "intake-candidates.md").write_text(
            "conflicting main content\n", encoding="utf-8"
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "main conflict")
        git(self.repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.repo, "fetch", "-q", "origin")
        before = len(self._calls)
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("conflict", str(ctx.exception))
        second = self._calls[before:]
        forbidden = [
            c for c in second
            if "--force" in c or "--force-with-lease" in c or "reset" in c
        ]
        self.assertEqual(forbidden, [])
        self.assertFalse(any(c[:2] == ["git", "push"] for c in second))

    def test_dirty_checkout_fails_before_mutation(self):
        (self.repo / "docs" / "unrelated.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(sync_intake_pr.SyncError) as ctx:
            sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        self.assertIn("dirty", str(ctx.exception))
        self.assertEqual(self._calls, [["git", "status", "--porcelain"]])

    def test_no_forbidden_git_or_push_to_main(self):
        sync_intake_pr.sync_pr(self.repo, repo="acme/registry")
        flat = [c for cmd in self._calls for c in cmd]
        self.assertNotIn("config", flat)
        self.assertNotIn("--force", flat)
        self.assertNotIn("--force-with-lease", flat)
        self.assertNotIn("reset", flat)
        for c in self._calls:
            if c[:2] == ["git", "push"]:
                self.assertNotIn("main", c)
                self.assertTrue(any(a.endswith(f"refs/heads/{BRANCH}") for a in c))
        for c in self._calls:
            if c[:2] == ["git", "add"]:
                staged = c[c.index("--") + 1:]
                self.assertEqual(staged, sync_intake_pr.GENERATED_PATHS)


class MockedSyncPrTests(unittest.TestCase):
    def test_mocked_happy_path_command_order(self):
        calls = []

        def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False):
            calls.append([str(c) for c in cmd])
            out = ""
            rc = 0
            if cmd[:3] == ["git", "status", "--porcelain"]:
                out = ""
            elif cmd[:4] == ["git", "rev-parse", "--verify", "--quiet"]:
                rc = 1
            elif cmd[:3] == ["git", "diff", "--cached"]:
                rc = 1
            elif cmd[:3] == ["git", "rev-parse", "HEAD^{tree}"]:
                out = "treeA\n"
            elif cmd[:2] == ["git", "rev-parse"] and "main" in cmd[2]:
                out = "treeB\n"
            elif cmd[:3] == ["git", "rev-parse", "HEAD"]:
                out = "h1\n"
            elif cmd[:3] == ["gh", "pr", "list"]:
                out = "[]"
            elif cmd[:3] == ["gh", "pr", "create"]:
                out = "https://example.test/repo/pull/7\n"
            return subprocess.CompletedProcess(cmd, rc, out, "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in sync_intake_pr.REQUIRED_INPUTS:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("x", encoding="utf-8")
            with patch.object(sync_intake_pr.subprocess, "run", side_effect=fake_run):
                url = sync_intake_pr.sync_pr(root, repo="acme/registry")
        self.assertEqual(url, "https://example.test/repo/pull/7")
        cmds_index = calls.index(["git", "add", "--", *sync_intake_pr.GENERATED_PATHS])
        self.assertEqual(calls[cmds_index][2:], ["--", *sync_intake_pr.GENERATED_PATHS])
        cmds = [c for c in calls if c[0] in ("git", "gh")]
        self.assertLess(
            cmds.index(["git", "fetch", "origin"]),
            cmds.index(["git", "add", "--", *sync_intake_pr.GENERATED_PATHS]),
        )
        self.assertFalse(any(c[0] == "git" and "config" in c for c in calls))

    def test_missing_input_fails_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            calls = []

            def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False):
                calls.append([str(c) for c in cmd])
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch.object(sync_intake_pr.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(sync_intake_pr.SyncError) as ctx:
                    sync_intake_pr.sync_pr(root, repo="acme/registry")
        self.assertIn("missing required input", str(ctx.exception))
        self.assertEqual(calls, [["git", "status", "--porcelain"]])

    def test_main_writes_summary_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            with patch.object(
                sync_intake_pr,
                "sync_pr",
                side_effect=sync_intake_pr.SyncError("boom\nRecovery: rerun"),
            ), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                rc = sync_intake_pr.main()
            self.assertEqual(rc, 1)
            content = summary.read_text(encoding="utf-8")
            self.assertIn("::error::boom", content)
            self.assertIn("Recovery: rerun", content)

    def test_env_forces_bot_identity_over_ambient(self):
        with patch.dict(os.environ, {"GIT_AUTHOR_NAME": "custom"}):
            self.assertEqual(
                sync_intake_pr._env()["GIT_AUTHOR_NAME"], "github-actions[bot]"
            )

    def test_sha256_pr_head_oid_accepted(self):
        existing = {"url": "https://example.test/pr/1", "headRefOid": "f" * 64}
        with patch.object(
            sync_intake_pr, "_ref_exists", return_value=True
        ), patch.object(sync_intake_pr, "_git_out", return_value="f" * 64):
            sync_intake_pr._verify_pr_head(Path("/repo"), existing)

    def test_short_pr_head_oid_rejected(self):
        existing = {"url": "https://example.test/pr/1", "headRefOid": "f" * 39}
        with patch.object(
            sync_intake_pr, "_ref_exists", return_value=True
        ), patch.object(sync_intake_pr, "_git_out", return_value="f" * 39):
            with self.assertRaises(sync_intake_pr.SyncError):
                sync_intake_pr._verify_pr_head(Path("/repo"), existing)

    def test_mid_length_pr_head_oid_rejected(self):
        for length in (41, 50, 63):
            existing = {
                "url": "https://example.test/pr/1",
                "headRefOid": "f" * length,
            }
            with patch.object(
                sync_intake_pr, "_ref_exists", return_value=True
            ), patch.object(sync_intake_pr, "_git_out", return_value="f" * length):
                with self.assertRaises(sync_intake_pr.SyncError):
                    sync_intake_pr._verify_pr_head(Path("/repo"), existing)


if __name__ == "__main__":
    unittest.main()
