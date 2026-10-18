#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANCH = "chore/sync-intake-candidates"
PR_TITLE = "chore(intake): sync candidates and signals"
COMMIT_MESSAGE = PR_TITLE
GENERATED_PATHS = [
    "docs/intake-candidates.md",
    "docs/intake-state.json",
    "docs/upstream-release-outreach.md",
]
REQUIRED_INPUTS = [
    "scripts/sync-intake-candidates.py",
    "docs/intake-state.json",
    "registry/index.json",
    "docs/upstream-release-outreach.md",
]
PR_BODY = """\
## Daily Intake Candidate & Signal Sync

Automated refresh of candidate status, intake state, and upstream outreach signals from live repository data.

- Updated `docs/intake-candidates.md`
- Updated `docs/intake-state.json`
- Updated `docs/upstream-release-outreach.md`

_Automated by `.github/workflows/daily-upstream-sync.yml`._
"""

GIT_ENV_DEFAULTS = {
    "GIT_AUTHOR_NAME": "github-actions[bot]",
    "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "github-actions[bot]",
    "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
}


class SyncError(RuntimeError):
    pass


def _env() -> dict[str, str]:
    return {**os.environ, **GIT_ENV_DEFAULTS}


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, env=_env(), capture_output=True, text=True
    )


def _must(cmd: list[str], cwd: Path, what: str, recovery: str) -> subprocess.CompletedProcess:
    result = _run(cmd, cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(
            f"{what} failed: {' '.join(str(c) for c in cmd)}\n{detail}\nRecovery: {recovery}"
        )
    return result


def _gh(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return _run(["gh", *args], cwd)


def _git_out(cwd: Path, args: list[str]) -> str:
    return _must(["git", *args], cwd, "git query", "inspect git state and rerun").stdout.strip()


def _assert_scope(cwd: Path, base_branch: str) -> None:
    for p in GENERATED_PATHS:
        if (cwd / p).is_symlink():
            raise SyncError(
                f"generated path {p} is a symlink; refusing to write outside "
                "the allowed scope.\n"
                "Recovery: human review required — remove the symlinked path "
                "from the sync branch, then rerun."
            )
    out = _must(
        ["git", "diff", "--name-only", "-z", f"origin/{base_branch}", "HEAD"],
        cwd,
        "scope diff",
        "inspect git state and rerun",
    ).stdout
    changed = {p for p in out.split("\0") if p}
    unexpected = sorted(changed - set(GENERATED_PATHS))
    if unexpected:
        raise SyncError(
            f"{BRANCH} differs from origin/{base_branch} outside the generated "
            f"paths: {', '.join(unexpected)}\n"
            "Recovery: commits are preserved for human review; reconcile or move "
            "those changes off the sync branch, then rerun."
        )


def _ref_exists(cwd: Path, ref: str) -> bool:
    return _run(["git", "rev-parse", "--verify", "--quiet", ref], cwd).returncode == 0


def _switch_branch(cwd: Path, base_branch: str) -> None:
    if _ref_exists(cwd, f"refs/remotes/origin/{BRANCH}"):
        if _ref_exists(cwd, f"refs/heads/{BRANCH}"):
            _must(
                ["git", "switch", BRANCH],
                cwd,
                "switch to sync branch",
                f"check out {BRANCH} manually and rerun",
            )
        else:
            _must(
                ["git", "switch", "-c", BRANCH, "--track", f"origin/{BRANCH}"],
                cwd,
                "create local tracking branch",
                f"check out {BRANCH} manually and rerun",
            )
        _must(
            ["git", "merge", "--ff-only", f"origin/{BRANCH}"],
            cwd,
            "fast-forward local sync branch",
            f"{BRANCH} diverged from origin; reconcile locally and rerun (no force-push)",
        )
    else:
        if _ref_exists(cwd, f"refs/heads/{BRANCH}"):
            _must(
                ["git", "switch", BRANCH],
                cwd,
                "switch to sync branch",
                f"check out {BRANCH} manually and rerun",
            )
        else:
            _must(
                ["git", "switch", "-c", BRANCH, f"origin/{base_branch}"],
                cwd,
                "create sync branch",
                f"create {BRANCH} from origin/{base_branch} manually and rerun",
            )


def _check_inputs_and_fetch(repo_root: Path) -> None:
    dirty = _git_out(repo_root, ["status", "--porcelain"])
    if dirty:
        raise SyncError(
            f"checkout at {repo_root} is dirty:\n{dirty}\n"
            "Recovery: commit or stash unrelated changes, then rerun."
        )
    missing = [p for p in REQUIRED_INPUTS if not (repo_root / p).exists()]
    if missing:
        raise SyncError(
            f"missing required input files: {', '.join(missing)}\n"
            "Recovery: restore the files on the checkout and rerun."
        )
    _must(
        ["git", "fetch", "origin"],
        repo_root,
        "fetch origin",
        "check network and credentials, then rerun",
    )


def _discover_pr(repo_root: Path, repo: str, base_branch: str) -> dict | None:
    listed = _gh(
        [
            "pr", "list",
            "--repo", repo,
            "--head", BRANCH,
            "--base", base_branch,
            "--state", "open",
            "--json", "number,url,headRefOid,autoMergeRequest",
        ],
        repo_root,
    )
    if listed.returncode != 0:
        raise SyncError(
            f"gh pr list failed: {listed.stderr.strip()}\n"
            "Recovery: check gh authentication and rerun."
        )
    try:
        open_prs = json.loads(listed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SyncError(
            f"gh pr list returned malformed output: {exc}\n"
            "Recovery: check gh CLI version/authentication and rerun."
        )
    required_fields = {"number", "url", "headRefOid", "autoMergeRequest"}
    if not isinstance(open_prs, list) or any(
        not isinstance(pr, dict) or not required_fields <= set(pr)
        for pr in open_prs
    ):
        raise SyncError(
            "gh pr list returned unexpected data shape.\n"
            "Recovery: check gh CLI version/authentication and rerun."
        )
    if len(open_prs) > 1:
        raise SyncError(
            f"found {len(open_prs)} open PRs for head {BRANCH}; expected at most one.\n"
            "Recovery: close the duplicates, keeping one, then rerun."
        )
    return open_prs[0] if open_prs else None


def _verify_pr_head(repo_root: Path, existing: dict) -> None:
    oid = existing.get("headRefOid") or ""
    remote_oid = (
        _git_out(repo_root, ["rev-parse", f"refs/remotes/origin/{BRANCH}"])
        if _ref_exists(repo_root, f"refs/remotes/origin/{BRANCH}")
        else None
    )
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid) or remote_oid != oid:
        raise SyncError(
            f"open PR {existing['url']} head oid {oid or '<missing>'} does not "
            f"match origin/{BRANCH} ({remote_oid or '<missing>'}).\n"
            "Recovery: reconcile the PR head with the remote sync branch, "
            "then rerun."
        )


def _merge_base(repo_root: Path, base_branch: str) -> None:
    _switch_branch(repo_root, base_branch)
    merged = _run(["git", "merge", "--no-edit", f"origin/{base_branch}"], repo_root)
    if merged.returncode != 0:
        _run(["git", "merge", "--abort"], repo_root)
        raise SyncError(
            f"merge of origin/{base_branch} into {BRANCH} has conflicts:\n"
            f"{merged.stdout}{merged.stderr}\n"
            f"Recovery: resolve the conflict on {BRANCH} locally, push it, then rerun."
        )
    _assert_scope(repo_root, base_branch)


def _refresh_docs(repo_root: Path, base_branch: str) -> None:
    _must(
        [sys.executable, "scripts/sync-intake-candidates.py"],
        repo_root,
        "sync-intake-candidates.py",
        "fix the sync failure and rerun",
    )
    _must(
        ["git", "add", "--", *GENERATED_PATHS],
        repo_root,
        "staging generated docs",
        "inspect git status and rerun",
    )
    staged = _run(["git", "diff", "--cached", "--quiet"], repo_root)
    if staged.returncode == 1:
        _must(
            ["git", "commit", "-m", COMMIT_MESSAGE],
            repo_root,
            "commit synced docs",
            "inspect git status and rerun",
        )
    elif staged.returncode != 0:
        raise SyncError(
            f"git diff --cached failed: {staged.stderr.strip()}\n"
            "Recovery: inspect git state and rerun."
        )
    _assert_scope(repo_root, base_branch)


def _push_sync_branch(repo_root: Path, base_branch: str) -> str | None:
    head_tree = _git_out(repo_root, ["rev-parse", "HEAD^{tree}"])
    base_tree = _git_out(repo_root, ["rev-parse", f"origin/{base_branch}^{{tree}}"])
    if head_tree == base_tree:
        return None
    head = _git_out(repo_root, ["rev-parse", "HEAD"])
    remote_head = (
        _git_out(repo_root, ["rev-parse", f"refs/remotes/origin/{BRANCH}"])
        if _ref_exists(repo_root, f"refs/remotes/origin/{BRANCH}")
        else None
    )
    if remote_head != head:
        _must(
            ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"],
            repo_root,
            "push sync branch",
            f"remote {BRANCH} moved or push rejected; reconcile origin/{BRANCH} "
            "locally and rerun (never force-push)",
        )
    return head


def _ensure_pr(
    repo_root: Path, repo: str, base_branch: str, existing: dict | None
) -> tuple[str, bool]:
    if existing:
        return existing["url"], bool(existing.get("autoMergeRequest"))
    created = _gh(
        [
            "pr", "create",
            "--repo", repo,
            "--title", PR_TITLE,
            "--body", PR_BODY,
            "--head", BRANCH,
            "--base", base_branch,
        ],
        repo_root,
    )
    if created.returncode != 0:
        raise SyncError(
            f"gh pr create failed: {created.stderr.strip()}\n"
            f"Recovery: rerun — pushed branch {BRANCH} is reused and the PR "
            "is created on retry."
        )
    return created.stdout.strip(), False


def _enable_auto_merge(repo_root: Path, repo: str, pr_url: str, head: str) -> None:
    # Enable auto-merge
    auto = _gh(
        [
            "pr", "merge", pr_url,
            "--repo", repo,
            "--auto",
            "--squash",
            "--match-head-commit", head,
        ],
        repo_root,
    )
    if auto.returncode != 0:
        raise SyncError(
            f"gh pr merge --auto failed for {pr_url}: {auto.stderr.strip()}\n"
            f"Recovery: enable auto-merge manually on {pr_url} or rerun; "
            "the branch and PR are reused."
        )


def sync_pr(
    repo_root: Path,
    repo: str = "numan-cli/numan-registry",
    base_branch: str = "main",
) -> str | None:
    _check_inputs_and_fetch(repo_root)
    existing = _discover_pr(repo_root, repo, base_branch)
    if existing:
        _verify_pr_head(repo_root, existing)
    _merge_base(repo_root, base_branch)
    _refresh_docs(repo_root, base_branch)
    head = _push_sync_branch(repo_root, base_branch)
    if head is None:
        return existing["url"] if existing else None
    pr_url, auto_merge_set = _ensure_pr(repo_root, repo, base_branch, existing)
    if not auto_merge_set:
        _enable_auto_merge(repo_root, repo, pr_url, head)
    return pr_url


def main() -> int:
    try:
        url = sync_pr(REPO_ROOT)
    except (SyncError, OSError, ValueError) as exc:
        message = f"::error::{exc}"
        print(message)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        return 1
    if url:
        print(f"OK: intake sync PR ready: {url}")
    else:
        print("OK: intake docs already in sync; no PR needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
