#!/usr/bin/env python3
"""Automate registry intake for non-binary packages (modules, scripts, completions).

The CI plugin lane cross-compiles Rust; modules/scripts/completions need no
compilation at all -- they're just archives of source files. This script
turns "here's a Git repo with Nu files" into a registry-intake-ready spec:

  1. Resolve the given ref (branch, tag, or commit SHA) to its full 40-char
     commit SHA via `git ls-remote` (immutable provenance anchor, matching
     the CI plugin lane's `source_commit` convention).
  2. Shallow-clone the repo and check out exactly that SHA.
  3. Verify the declared entry file exists in the checkout.
  4. Archive the checked-out tree (minus .git) as a deterministic .tar.gz --
     sorted entries, fixed mtime, gzip mtime=0 -- matching numan-plugins'
     scripts/package_plugin.py conventions, so repeat builds are byte-stable.
  5. Upload the archive to a GitHub Release on --release-repo.
  6. Emit a spec JSON compatible with `add-package.py --spec ... --write`.
  7. Record the resolved SHA + original ref in manifest-archives.json for
     repeatable re-intake on version bumps.

The spec omits `artifact.sha256`: add-package.py computes the hash itself
when downloading the artifact, so an authored hash would be ignored (or
worse, mask a substitution). The resolved SHA is preserved as
`source.rev` -- immutable upstream provenance for non-plugin sources,
which carry no cargo_name.

Usage:
  python scripts/intake-archive.py \\
    --git-url https://github.com/owner/repo --ref v1.0.0 \\
    --entry mod.nu --name cool-module --owner someone --type module \\
    --description "..." --tags '["module"]' --nu-version ">=0.114.0" \\
    --activation-kind nu-module --activation-import all \\
    --release-repo numan-cli/numan-registry \\
    --out spec-someone-cool-module.json --write
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMMAND_TIMEOUT_SECONDS = 120
FIXED_MTIME = 315532800  # 1980-01-01 UTC; matches package_plugin.py
VALID_TYPES = ("module", "script", "completion")
VALID_GIT_URL_RE = re.compile(
    r"^(https?://|git://|ssh://|git@[\w.-]+:)"
)
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def _load_add_package() -> ModuleType:
    """Dynamically load add-package.py (hyphenated filename, not import-able)."""
    spec = importlib.util.spec_from_file_location(
        "add_package", Path(__file__).resolve().parent / "add-package.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load scripts/add-package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_git_url(git_url: str) -> None:
    """Validate that git_url is a safe URL scheme and doesn't start with option syntax.

    Raises ValueError if the URL is invalid.
    """
    if git_url.startswith("-"):
        raise ValueError(f"git URL may not start with '-': {git_url!r}")
    if not VALID_GIT_URL_RE.match(git_url):
        raise ValueError(
            f"git URL must use https://, http://, git://, ssh://, or git@: {git_url!r}"
        )


def resolve_ref(git_url: str, ref: str) -> str:
    """Resolve a branch, tag, or commit SHA on `git_url` to its full 40-char commit SHA."""
    for candidate in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}", ref):
        result = subprocess.run(
            ["git", "ls-remote", git_url, candidate],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not result.stdout.strip():
            continue
        lines = result.stdout.strip().splitlines()
        if len(lines) > 1:
            raise ValueError(f"ref {ref!r} is ambiguous on {git_url}: {len(lines)} matches")
        return lines[0].split()[0]
    if SHA_RE.fullmatch(ref):
        return ref
    raise ValueError(f"could not resolve ref {ref!r} on {git_url}")


def shallow_clone_at(git_url: str, sha: str, dest: Path) -> None:
    """Clone `git_url` into `dest` and check out exactly `sha`, shallow (depth=1)."""
    subprocess.run(
        ["git", "init", "--quiet", str(dest)], check=True, timeout=COMMAND_TIMEOUT_SECONDS
    )
    subprocess.run(
        ["git", "-C", str(dest), "remote", "add", "origin", git_url],
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin", sha],
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", "--quiet", sha],
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def sorted_files(root: Path) -> list[Path]:
    """List regular files under `root` (excluding .git), sorted for deterministic archiving."""
    files = []
    resolved_root = root.resolve()
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError(f"symlink not allowed in archive source: {p.relative_to(root)}")
        if not p.is_file():
            continue
        try:
            p.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"archive source path resolves outside checkout: {p.relative_to(root)}") from exc
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] == ".git":
            continue
        files.append(rel)
    return sorted(files, key=lambda p: p.as_posix())


def build_archive(src_dir: Path, out: Path) -> None:
    """Build a deterministic .tar.gz of `src_dir`: sorted entries, fixed mtime, gzip mtime=0."""
    rels = sorted_files(src_dir)
    if len(rels) > MAX_ARCHIVE_FILES:
        raise ValueError(f"{len(rels)} files exceeds client limit of {MAX_ARCHIVE_FILES}")
    total = sum((src_dir / r).stat().st_size for r in rels)
    if total > MAX_ARCHIVE_BYTES:
        raise ValueError(f"{total} bytes exceeds client limit of {MAX_ARCHIVE_BYTES}")

    with out.open("wb") as fh:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0)
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for rel in rels:
                full = src_dir / rel
                info = tarfile.TarInfo(name=rel.as_posix())
                info.size = full.stat().st_size
                info.mtime = FIXED_MTIME
                info.mode = 0o755 if full.stat().st_mode & 0o111 else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with full.open("rb") as src:
                    tar.addfile(info, src)
        gz.close()


def upload_to_release(release_repo: str, tag: str, title: str, asset: Path) -> str:
    """Create a new GitHub release on `release_repo` and upload `asset`.

    Refuses to reuse an existing tag (immutable-per-intake, like the CI
    plugin lane's release_transaction.py). Returns the asset's download URL.
    """
    gh_helpers = importlib.import_module("gh_helpers")

    existing_release = gh_helpers.gh_run(["release", "view", tag, "--repo", release_repo])
    if existing_release is not None and existing_release.returncode == 0:
        raise ValueError(f"release tag {tag!r} already exists on {release_repo}; refusing to overwrite")

    existing_tag = gh_helpers.gh_run(["api", f"repos/{release_repo}/git/refs/tags/{tag}"])
    if existing_tag is not None and existing_tag.returncode == 0:
        raise ValueError(f"tag {tag!r} already exists on {release_repo}; refusing to overwrite")

    try:
        result = gh_helpers.gh_run_with_timeout(
            [
                "release",
                "create",
                tag,
                str(asset),
                "--repo",
                release_repo,
                "--title",
                title,
                "--notes",
                f"Non-binary archive intake: {asset.name}",
            ],
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(
            f"gh release create timed out after 300s; release tag {tag!r} may already exist and require manual cleanup"
        )

    if result is None:
        raise ValueError("gh CLI unavailable")
    if result.returncode != 0:
        raise ValueError(f"gh release create failed: {result.stderr.strip()}")
    return f"https://github.com/{release_repo}/releases/download/{tag}/{asset.name}"


def derive_version(ref: str, resolved_sha: str) -> str:
    """Derive a version string when the caller doesn't supply one explicitly.

    A tag-shaped ref (optionally 'v'-prefixed semver) uses its own version.
    Otherwise falls back to the 0.1.0-<short-sha> convention already used by
    this registry's existing script/completion entries pinned to a branch.
    """
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+(?:[-+].+)?)", ref)
    if match:
        return match.group(1)
    return f"0.1.0-{resolved_sha[:7]}"


def build_spec(
    *,
    owner: str,
    name: str,
    description: str,
    git_url: str,
    pkg_type: str,
    tags: list[str],
    version: str,
    nu_version: str,
    entry: str,
    url: str,
    resolved_sha: str,
    activation_kind: str | None = None,
    activation_import: str | None = None,
) -> dict:
    """Build a registry intake spec for a non-binary (archive-kind) package.

    ``source.rev`` is the resolved, immutable upstream commit (never the
    input ref). Emitted specs include ``source.cargo_name`` as a temporary
    compatibility placeholder, using the package name for archive-backed
    modules that have no Rust crate.

    ``artifact.sha256`` is intentionally omitted: add-package.py
    computes the digest from the downloaded artifact, so an authored hash
    would be ignored or worse mask a substitution. Only publish such entries
    once the numan client deserializes ``source.cargo_name`` as optional
    (numan-cli/numan#137); the pinned numan-parser-check gate blocks
    cargo-less entries until then.
    """
    spec: dict = {
        "owner": owner,
        "name": name,
        "description": description,
        "repo": git_url,
        "type": pkg_type,
        "tags": tags,
        "version": version,
        "nu_version": nu_version,
        "artifact": {
            "kind": "archive",
            "url": url,
            "entry": entry,
        },
        "source": {
            "git": git_url,
            "rev": resolved_sha,
            # Temporary: include cargo_name for client compatibility until
            # numan-cli/numan#137 makes SourceInfo.cargo_name optional.
            # Archive-backed modules don't have a Rust crate, so use the
            # package name as a placeholder.
            "cargo_name": name,
        },
    }
    if activation_kind:
        activation = {"kind": activation_kind}
        if activation_import:
            activation["import"] = activation_import
        spec["activation"] = activation
    return spec


def record_archive_manifest(
    path: Path,
    *,
    git_url: str,
    ref: str,
    resolved_sha: str,
    entry: str,
    name: str,
    owner: str,
    pkg_type: str,
) -> None:
    """Upsert this intake's re-intake tracking record into manifest-archives.json.

    Raises ValueError if the existing file is present but not a JSON array of objects.
    """
    if path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValueError(f"{path} must contain a JSON array of objects")
    else:
        entries = []
    record = {
        "git": git_url,
        "ref": ref,
        "resolved_sha": resolved_sha,
        "entry": entry,
        "name": name,
        "owner": owner,
        "type": pkg_type,
    }
    entries = [e for e in entries if not (e.get("owner") == owner and e.get("name") == name)]
    entries.append(record)
    entries.sort(key=lambda e: (e.get("owner", ""), e.get("name", "")))
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _parse_tags(raw: str) -> list[str]:
    """Parse and validate the --tags JSON array. Raises ValueError/JSONDecodeError."""
    tags = json.loads(raw)
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("--tags must be a JSON array of strings")
    return tags


def _validate_activation(args: argparse.Namespace) -> int | None:
    """Check activation prerequisites: --provisional and import-mode coherence."""
    if args.activation_kind and not args.provisional:
        print(
            "FAIL: --activation-kind requires --provisional (no lifecycle evidence was provided)",
            file=sys.stderr,
        )
        return 1
    if args.provisional and not (args.deferral_reason and args.deferral_reason.strip()):
        print(
            "FAIL: --provisional requires non-blank --deferral-reason",
            file=sys.stderr,
        )
        return 1
    if args.activation_kind:
        add_package = _load_add_package()
        try:
            add_package.check_module_import_mode(
                {"entry": args.entry},
                {"kind": args.activation_kind, "import": args.activation_import or "module"},
            )
        except SystemExit:
            return 1
    return None


def _checkout_and_validate_entry(args: argparse.Namespace, resolved_sha: str, tmp: str) -> Path | int:
    """Clone at resolved_sha and verify --entry exists inside the checkout.

    Returns the checkout directory, or an exit code on failure.
    """
    src_dir = Path(tmp) / "src"
    try:
        shallow_clone_at(args.git_url, resolved_sha, src_dir)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: could not clone/checkout {resolved_sha}: {exc}", file=sys.stderr)
        return 1

    entry_path = src_dir / args.entry
    try:
        if Path(args.entry).is_absolute():
            raise ValueError
        entry_path.resolve().relative_to(src_dir.resolve())
    except ValueError:
        print(f"FAIL: entry path escapes checkout: {args.entry}", file=sys.stderr)
        return 1
    if not entry_path.is_file():
        print(f"FAIL: entry file not found in checkout: {args.entry}", file=sys.stderr)
        return 1
    return src_dir


def _build_and_publish(args: argparse.Namespace, src_dir: Path, tag: str, version: str) -> tuple[str, str] | int:
    """Build the deterministic archive and upload it to the release.

    Retains the pre-upload digest and verifies the downloaded release asset
    matches that digest before returning. Rejects mismatches to prevent
    publishing substituted bytes under the original source.rev.

    Returns (url, sha256), or an exit code on failure.
    """
    import urllib.request

    archive_path = src_dir.parent / f"{args.owner}-{args.name}-{version}.tar.gz"
    try:
        build_archive(src_dir, archive_path)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    pre_upload_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    print(f"Built {archive_path.name} sha256={pre_upload_digest}", file=sys.stderr)

    try:
        url = upload_to_release(args.release_repo, tag, f"{args.owner}/{args.name} {version}", archive_path)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    # Verify the published asset matches the pre-upload digest
    print(f"Verifying published asset integrity at {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            downloaded_bytes = response.read()
        post_upload_digest = hashlib.sha256(downloaded_bytes).hexdigest()
    except Exception as exc:
        print(f"FAIL: could not download published asset for verification: {exc}", file=sys.stderr)
        return 1

    if post_upload_digest != pre_upload_digest:
        print(f"FAIL: published asset digest mismatch: expected {pre_upload_digest}, got {post_upload_digest}", file=sys.stderr)
        return 1
    return url, pre_upload_digest


def _write_registry_and_manifest(args: argparse.Namespace, out_path: Path, resolved_sha: str, tag: str) -> int | None:
    """Chain into add-package.py --write (if requested) and record re-intake tracking.

    Returns an exit code on failure, None on success.
    """
    if args.write:
        add_package_script = REPO_ROOT / "scripts" / "add-package.py"
        cmd = [
            sys.executable,
            str(add_package_script),
            "--spec",
            str(out_path),
            "--write",
        ]
        if args.provisional:
            cmd.append("--provisional")
            if getattr(args, "deferral_reason", None):
                cmd.extend(["--deferral-reason", args.deferral_reason])
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"FAIL: registry update failed; release {tag} was already published on {args.release_repo}",
                file=sys.stderr,
            )
            return result.returncode
        print("registry update succeeded", file=sys.stderr)

    try:
        record_archive_manifest(
            args.manifest_archives,
            git_url=args.git_url,
            ref=args.ref,
            resolved_sha=resolved_sha,
            entry=args.entry,
            name=args.name,
            owner=args.owner,
            pkg_type=args.pkg_type,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"recorded re-intake tracking in {args.manifest_archives}", file=sys.stderr)
    return None


def _extract_owner_name_from_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, name) from a git URL or repo slug, stripping any .git suffix."""
    m = re.search(r"[:/]([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$", url)
    if m:
        owner, name = m.group(1), m.group(2)
        if "@" in owner:
            owner = owner.split("@", 1)[1]
        return owner, name
    return None


def _resolve_owner_name(args: argparse.Namespace) -> None:
    """Infer owner and name from --git-url if not explicitly provided."""
    if args.owner and args.name:
        return
    parsed = _extract_owner_name_from_url(args.git_url)
    if parsed:
        owner, name = parsed
        args.owner = args.owner or owner
        args.name = args.name or name


def _normalize_cli_args(args: argparse.Namespace) -> int | None:
    """Normalize and validate CLI arguments, resolving aliases and repo slugs."""
    git_url = args.git_url or args.repo
    if not git_url:
        print("FAIL: either --git-url or --repo is required", file=sys.stderr)
        return 1
    if not any(git_url.startswith(p) for p in ("http://", "https://", "git://", "ssh://", "git@")):
        git_url = f"https://github.com/{git_url}"
    args.git_url = git_url

    ref = args.ref or args.commit
    if not ref:
        print("FAIL: either --ref or --commit is required", file=sys.stderr)
        return 1
    args.ref = ref

    _resolve_owner_name(args)
    if not args.owner or not args.name:
        print("FAIL: --owner and --name are required", file=sys.stderr)
        return 1
    return None


def main(argv: list[str] | None = None) -> int:
    """Resolve, archive, publish, and emit a registry spec for a non-binary package."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--git-url", default=None, help="Git clone URL")
    ap.add_argument("--repo", default=None, help="Repository URL or owner/name slug")
    ap.add_argument("--ref", default=None, help="Branch, tag, or commit ref")
    ap.add_argument("--commit", default=None, help="Commit SHA or ref alias")
    ap.add_argument("--entry", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--owner", default=None)
    ap.add_argument("--type", required=True, choices=VALID_TYPES, dest="pkg_type")
    ap.add_argument("--description", required=True)
    ap.add_argument("--tags", required=True, help="JSON array of tag strings")
    ap.add_argument("--nu-version", required=True)
    ap.add_argument("--activation-kind", default=None)
    ap.add_argument("--activation-import", default=None, choices=("module", "all"))
    ap.add_argument(
        "--provisional",
        action="store_true",
        help="Allow activation-bearing specs without lifecycle evidence",
    )
    ap.add_argument(
        "--deferral-reason",
        default=None,
        help="Reason for provisional intake (passed to add-package.py)",
    )
    ap.add_argument(
        "--version",
        default=None,
        help=(
            "Version string for this intake; derived from --ref if omitted. "
            "A semver-shaped --ref (e.g. '1.2.3' or 'v1.2.3') will be treated "
            "as a version regardless of whether it's a tag or branch name; "
            "other refs fall back to 0.1.0-<short-sha>."
        ),
    )
    ap.add_argument(
        "--release-repo",
        default="numan-cli/numan-registry",
        help="owner/repo to publish the archive as a GitHub release asset on",
    )
    ap.add_argument(
        "--manifest-archives",
        type=Path,
        default=REPO_ROOT / "manifest-archives.json",
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--write", action="store_true", help="Chain into add-package.py --write")
    args = ap.parse_args(argv)

    norm_err = _normalize_cli_args(args)
    if norm_err is not None:
        return norm_err

    activation_err = _validate_activation(args)
    if activation_err is not None:
        return activation_err

    try:
        tags = _parse_tags(args.tags)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    try:
        validate_git_url(args.git_url)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    try:
        resolved_sha = resolve_ref(args.git_url, args.ref)
    except (ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Resolved {args.git_url}@{args.ref} -> {resolved_sha}", file=sys.stderr)

    version = args.version or derive_version(args.ref, resolved_sha)
    tag = f"archive-{args.owner}-{args.name}-{version}"

    with tempfile.TemporaryDirectory() as tmp:
        src_dir = _checkout_and_validate_entry(args, resolved_sha, tmp)
        if isinstance(src_dir, int):
            return src_dir

        published = _build_and_publish(args, src_dir, tag, version)
        if isinstance(published, int):
            return published
        url, _ = published

        spec = build_spec(
            owner=args.owner,
            name=args.name,
            description=args.description,
            git_url=args.git_url,
            pkg_type=args.pkg_type,
            tags=tags,
            version=version,
            nu_version=args.nu_version,
            entry=args.entry,
            url=url,
            resolved_sha=resolved_sha,
            activation_kind=args.activation_kind,
            activation_import=args.activation_import,
        )

        out_path = args.out or (REPO_ROOT / f"spec-{args.owner}-{args.name}.json")
        out_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}", file=sys.stderr)

        write_err = _write_registry_and_manifest(args, out_path, resolved_sha, tag)
        if write_err is not None:
            return write_err

    if not args.write:
        rerun_cmd = f"python scripts/add-package.py --spec {out_path} --write"
        if args.provisional:
            rerun_cmd += " --provisional"
        print(f"\nRe-run with the emitted spec: {rerun_cmd}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
