#!/usr/bin/env python3
"""Materialize the base index used by the platform-coverage audit.

The workflow checks out only the head commit. This helper fetches the exact
base revision (PR base SHA, push ``before`` SHA, or dispatch ref), reads
``registry/index.json`` from that commit, and writes ``base_index`` /
``base_missing`` GitHub outputs. If the base commit exists but has no index,
the audit is told to report every current target as new. It never mutates the
index and performs no write requests; the API fallback is a content GET only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib import error, parse, request

ZERO_SHA = "0" * 40
BASE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^{}~:-]*$")
DEFAULT_INDEX_PATH = "registry/index.json"
DEFAULT_API_URL = "https://api.github.com"


class ResolveError(RuntimeError):
    """Raised when the resolver cannot write its required outputs."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _git(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=False,
    )


def _is_zero_sha(value: str) -> bool:
    return len(value) == 40 and set(value) == {"0"}


def _base_ref(event: str, pr_base: str, before: str, input_ref: str) -> str:
    if event == "pull_request":
        return pr_base.strip()
    if event == "push":
        before = before.strip()
        return before if before and not _is_zero_sha(before) else ""
    if event == "workflow_dispatch":
        return input_ref.strip()
    return ""


def _append_summary(message: str) -> None:
    path = _env("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8", newline="\n") as summary:
        summary.write(message)
        summary.write("\n")


def _write_outputs(base_path: Path | None, missing: bool) -> None:
    output = _env("GITHUB_OUTPUT")
    if not output:
        raise ResolveError("GITHUB_OUTPUT is required")
    with Path(output).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"base_index={base_path if base_path else ''}\n")
        handle.write(f"base_missing={'true' if missing else 'false'}\n")


def _base_missing(reason: str) -> int:
    base_path = Path(_env("RUNNER_TEMP", ".")) / "base-index.json"
    base_path.unlink(missing_ok=True)
    _write_outputs(None, True)
    _append_summary(
        f"No base index: {reason}; all current targets are reported as new."
    )
    print(f"warning: {reason}; reporting all current targets as new", file=sys.stderr)
    return 0


def _resolve_commit(base_ref: str) -> tuple[str | None, str]:
    # ``rev-parse --verify`` accepts a syntactically valid SHA even when the
    # object is absent from a shallow clone. Check object presence explicitly
    # before treating the revision as local.
    present = _git("cat-file", "-e", f"{base_ref}^{{commit}}")
    if present.returncode == 0:
        direct = _git("rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}")
        if direct.returncode == 0:
            return direct.stdout.strip(), "local"

    fetched = _git("fetch", "--no-tags", "--depth=1", "origin", base_ref)
    if fetched.returncode != 0:
        detail = fetched.stderr.strip() or "git fetch failed"
        return None, detail

    resolved = _git("rev-parse", "--verify", "--quiet", "FETCH_HEAD")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        return None, "fetched base did not resolve to a commit"
    return resolved.stdout.strip(), "fetched"


def _read_index(commit: str, index_path: str) -> tuple[str | None, str | None]:
    exists = _git("cat-file", "-e", f"{commit}:{index_path}")
    if exists.returncode != 0:
        return None, f"base commit has no {index_path}"
    shown = _git("show", f"{commit}:{index_path}")
    if shown.returncode != 0:
        return None, f"cannot read {index_path} from base commit"
    return shown.stdout, None


def _api_fetch(base_ref: str, index_path: str) -> tuple[str | None, str | None]:
    token = _env("GITHUB_TOKEN")
    repository = _env("GITHUB_REPOSITORY")
    if not token or not repository:
        return None, "GitHub API fallback is unavailable without a token/repository"

    api_url = _env("GITHUB_API_URL", DEFAULT_API_URL).rstrip("/")
    encoded_path = parse.quote(index_path, safe="/")
    query = parse.urlencode({"ref": base_ref})
    url = f"{api_url}/repos/{repository}/contents/{encoded_path}?{query}"
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "Authorization": f"Bearer {token}",
            "User-Agent": "numan-registry-coverage-audit",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8"), None
    except error.HTTPError as exc:
        if exc.code == 404:
            return None, f"base index is absent from the base revision (HTTP 404)"
        return None, f"GitHub API returned HTTP {exc.code}"
    except (error.URLError, TimeoutError) as exc:
        return None, f"GitHub API request failed: {exc}"


def _materialize(base_ref: str, index_path: str, base_path: Path) -> str | None:
    commit, commit_detail = _resolve_commit(base_ref)
    if commit:
        contents, read_detail = _read_index(commit, index_path)
        if contents is not None:
            base_path.write_text(contents, encoding="utf-8", newline="\n")
            return f"`{base_ref}` (`{commit[:12]}`)"
        if read_detail:
            _base_missing(read_detail)
            return None

    contents, api_detail = _api_fetch(base_ref, index_path)
    if contents is None:
        _base_missing(api_detail or commit_detail or "base index unavailable")
        return None
    base_path.write_text(contents, encoding="utf-8", newline="\n")
    return f"`{base_ref}` (GitHub contents API)"


def main() -> int:
    event = _env("GITHUB_EVENT_NAME")
    base_ref = _base_ref(
        event,
        _env("PR_BASE_SHA"),
        _env("PUSH_BEFORE"),
        _env("INPUT_BASE_REF"),
    )
    if not base_ref:
        return _base_missing("no base revision exists for this run")
    if BASE_REF_RE.fullmatch(base_ref) is None:
        return _base_missing(f"invalid base revision: {base_ref!r}")

    index_path = _env("INDEX_PATH", DEFAULT_INDEX_PATH)
    base_path = Path(_env("RUNNER_TEMP", ".")) / "base-index.json"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source = _materialize(base_ref, index_path, base_path)
        if source is None:
            return 0
        if not base_path.is_file() or not base_path.read_text(encoding="utf-8").strip():
            return _base_missing("base index is empty")
        _write_outputs(base_path, False)
        _append_summary(f"Base comparison: {source}.")
        print(f"base index materialized from {source}")
        return 0
    except (OSError, ResolveError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
