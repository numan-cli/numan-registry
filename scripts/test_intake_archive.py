#!/usr/bin/env python3
"""Unit checks for scripts/intake-archive.py (no network: mocks git/gh)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "intake-archive.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))


def load_mod():
    spec = importlib.util.spec_from_file_location("intake_archive", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ResolveRefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def _fake_run(self, mapping):
        def run(cmd, **kwargs):
            key = cmd[-1]
            stdout = mapping.get(key, "")
            return subprocess.CompletedProcess(cmd, 0 if stdout else 1, stdout=stdout, stderr="")

        return run

    def test_resolves_branch_head(self):
        sha = "a" * 40
        with mock.patch.object(
            self.mod.subprocess, "run", side_effect=self._fake_run({"main": f"{sha}\tHEAD\n"})
        ):
            self.assertEqual(self.mod.resolve_ref("https://example.invalid/x", "main"), sha)

    def test_resolves_annotated_tag_via_peel(self):
        sha = "b" * 40
        with mock.patch.object(
            self.mod.subprocess,
            "run",
            side_effect=self._fake_run({"refs/tags/v1.0.0^{}": f"{sha}\trefs/tags/v1.0.0^{{}}\n"}),
        ):
            self.assertEqual(self.mod.resolve_ref("https://example.invalid/x", "v1.0.0"), sha)

    def test_falls_back_to_ref_when_it_is_already_a_sha(self):
        sha = "c" * 40
        with mock.patch.object(self.mod.subprocess, "run", side_effect=self._fake_run({})):
            self.assertEqual(self.mod.resolve_ref("https://example.invalid/x", sha), sha)

    def test_raises_when_unresolvable(self):
        with mock.patch.object(self.mod.subprocess, "run", side_effect=self._fake_run({})):
            with self.assertRaisesRegex(ValueError, "could not resolve ref"):
                self.mod.resolve_ref("https://example.invalid/x", "no-such-ref")


class ShallowCloneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_issues_init_remote_fetch_checkout_in_order(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run):
                self.mod.shallow_clone_at(
                    "https://example.invalid/x", "d" * 40, Path(tmp) / "dest"
                )

        self.assertEqual(calls[0][:2], ["git", "init"])
        self.assertIn("remote", calls[1])
        self.assertIn("fetch", calls[2])
        self.assertIn("--depth", calls[2])
        self.assertIn("checkout", calls[3])

    def test_propagates_failure(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            self.mod.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, ["git", "fetch"]),
        ), self.assertRaises(subprocess.CalledProcessError):
            self.mod.shallow_clone_at(
                "https://example.invalid/x", "e" * 40, Path(tmp) / "dest"
            )


class ArchiveDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def _write_tree(self, root: Path) -> None:
        (root / "sub").mkdir()
        (root / "mod.nu").write_text("export def run [] {}\n", encoding="utf-8")
        (root / "sub" / "helper.nu").write_text("export def helper [] {}\n", encoding="utf-8")
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    def test_excludes_dot_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_tree(root)
            files = self.mod.sorted_files(root)
            self.assertNotIn(Path(".git/HEAD"), files)
            self.assertIn(Path("mod.nu"), files)
            self.assertIn(Path("sub/helper.nu"), files)

    def test_sorted_files_is_deterministic_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_tree(root)
            self.assertEqual(
                [p.as_posix() for p in self.mod.sorted_files(root)],
                ["mod.nu", "sub/helper.nu"],
            )

    def test_archive_bytes_are_stable_across_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            root.mkdir()
            self._write_tree(root)
            first = Path(tmp) / "first.tar.gz"
            second = Path(tmp) / "second.tar.gz"
            self.mod.build_archive(root, first)
            self.mod.build_archive(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_archive_contains_expected_entries_and_no_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            root.mkdir()
            self._write_tree(root)
            out = Path(tmp) / "out.tar.gz"
            self.mod.build_archive(root, out)
            with tarfile.open(out, "r:gz") as tar:
                names = tar.getnames()
            self.assertEqual(names, ["mod.nu", "sub/helper.nu"])


class UploadToReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()
        import gh_helpers

        cls.gh_helpers = gh_helpers

    def test_refuses_existing_tag(self):
        with mock.patch.object(
            self.gh_helpers,
            "gh_run",
            return_value=subprocess.CompletedProcess([], 0, stdout="{}", stderr=""),
        ):
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.mod.upload_to_release(
                    "owner/repo", "archive-owner-pkg-1.0.0", "title", Path("asset.tar.gz")
                )

    def test_refuses_existing_tag_without_release(self):
        def fake_gh_run(args):
            if args[:2] == ["release", "view"]:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="release not found")
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

        with mock.patch.object(self.gh_helpers, "gh_run", side_effect=fake_gh_run):
            with self.assertRaisesRegex(ValueError, "tag .* already exists"):
                self.mod.upload_to_release(
                    "owner/repo", "archive-owner-pkg-1.0.0", "title", Path("asset.tar.gz")
                )

    def test_creates_release_and_returns_download_url(self):
        view_result = subprocess.CompletedProcess([], 1, stdout="", stderr="release not found")
        create_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")

        calls = []

        def fake_gh_run(args):
            calls.append(args)
            return view_result

        def fake_gh_run_with_timeout(args, timeout):
            calls.append(args)
            return create_result

        with (
            mock.patch.object(self.gh_helpers, "gh_run", side_effect=fake_gh_run),
            mock.patch.object(
                self.gh_helpers, "gh_run_with_timeout", side_effect=fake_gh_run_with_timeout
            ),
        ):
            url = self.mod.upload_to_release(
                "owner/repo", "archive-owner-pkg-1.0.0", "title", Path("asset.tar.gz")
            )
        self.assertEqual(
            url,
            "https://github.com/owner/repo/releases/download/archive-owner-pkg-1.0.0/asset.tar.gz",
        )
        self.assertEqual(calls[0][:2], ["release", "view"])
        self.assertEqual(calls[1], ["api", "repos/owner/repo/git/refs/tags/archive-owner-pkg-1.0.0"])
        self.assertEqual(calls[2][:2], ["release", "create"])

    def test_raises_when_gh_unavailable(self):
        with (
            mock.patch.object(self.gh_helpers, "gh_run", return_value=None),
            mock.patch.object(self.gh_helpers, "gh_run_with_timeout", return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "gh CLI unavailable"):
                self.mod.upload_to_release("owner/repo", "tag", "title", Path("asset.tar.gz"))

    def test_raises_indeterminate_on_timeout(self):
        with (
            mock.patch.object(
                self.gh_helpers,
                "gh_run",
                return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="not found"),
            ),
            mock.patch.object(
                self.gh_helpers,
                "gh_run_with_timeout",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=300),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "timed out.*manual cleanup"):
                self.mod.upload_to_release("owner/repo", "tag", "title", Path("asset.tar.gz"))


class BuildSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_module_spec_includes_activation(self):
        spec = self.mod.build_spec(
            owner="someone",
            name="cool-module",
            description="desc",
            git_url="https://github.com/someone/cool-module",
            pkg_type="module",
            tags=["module"],
            version="1.0.0",
            nu_version=">=0.114.0",
            entry="mod.nu",
            url="https://github.com/owner/repo/releases/download/tag/asset.tar.gz",
            resolved_sha="d" * 40,
            activation_kind="nu-module",
            activation_import="all",
        )
        self.assertEqual(spec["activation"], {"kind": "nu-module", "import": "all"})
        self.assertEqual(
            spec["artifact"],
            {
                "kind": "archive",
                "url": "https://github.com/owner/repo/releases/download/tag/asset.tar.gz",
                "entry": "mod.nu",
            },
        )
        self.assertEqual(
            spec["source"],
            {
                "git": "https://github.com/someone/cool-module",
                "rev": "d" * 40,
            },
        )

    def test_script_spec_omits_activation(self):
        spec = self.mod.build_spec(
            owner="someone",
            name="cool-script",
            description="desc",
            git_url="https://github.com/someone/cool-script",
            pkg_type="script",
            tags=["script"],
            version="0.1.0-abc1234",
            nu_version="*",
            entry="run.nu",
            url="https://example.invalid/asset.tar.gz",
            resolved_sha="e" * 40,
        )
        self.assertNotIn("activation", spec)


class DeriveVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_uses_semver_tag_stripped_of_v_prefix(self):
        self.assertEqual(self.mod.derive_version("v1.2.3", "a" * 40), "1.2.3")

    def test_uses_bare_semver_tag(self):
        self.assertEqual(self.mod.derive_version("1.2.3", "a" * 40), "1.2.3")

    def test_falls_back_to_short_sha_for_branch_ref(self):
        sha = "abcdef0123456789abcdef0123456789abcdef01"
        self.assertEqual(self.mod.derive_version("main", sha), "0.1.0-abcdef0")


class RecordArchiveManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_creates_new_manifest_with_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest-archives.json"
            self.mod.record_archive_manifest(
                path,
                git_url="https://github.com/someone/cool-module",
                ref="v1.0.0",
                resolved_sha="a" * 40,
                entry="mod.nu",
                name="cool-module",
                owner="someone",
                pkg_type="module",
            )
            entries = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["resolved_sha"], "a" * 40)

    def test_upserts_existing_record_for_same_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest-archives.json"
            for ref, sha in (("v1.0.0", "a" * 40), ("v1.1.0", "b" * 40)):
                self.mod.record_archive_manifest(
                    path,
                    git_url="https://github.com/someone/cool-module",
                    ref=ref,
                    resolved_sha=sha,
                    entry="mod.nu",
                    name="cool-module",
                    owner="someone",
                    pkg_type="module",
                )
            entries = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["ref"], "v1.1.0")
            self.assertEqual(entries[0]["resolved_sha"], "b" * 40)

    def test_keeps_distinct_packages_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest-archives.json"
            self.mod.record_archive_manifest(
                path,
                git_url="https://github.com/a/pkg-a",
                ref="v1.0.0",
                resolved_sha="a" * 40,
                entry="mod.nu",
                name="pkg-a",
                owner="a",
                pkg_type="module",
            )
            self.mod.record_archive_manifest(
                path,
                git_url="https://github.com/b/pkg-b",
                ref="main",
                resolved_sha="b" * 40,
                entry="run.nu",
                name="pkg-b",
                owner="b",
                pkg_type="script",
            )
            entries = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 2)
            names = {e["name"] for e in entries}
            self.assertEqual(names, {"pkg-a", "pkg-b"})

    def test_raises_clear_error_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest-archives.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                self.mod.record_archive_manifest(
                    path,
                    git_url="https://github.com/someone/cool-module",
                    ref="v1.0.0",
                    resolved_sha="a" * 40,
                    entry="mod.nu",
                    name="cool-module",
                    owner="someone",
                    pkg_type="module",
                )

    def test_raises_clear_error_on_non_list_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest-archives.json"
            path.write_text('{"not": "a list"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must contain a JSON array"):
                self.mod.record_archive_manifest(
                    path,
                    git_url="https://github.com/someone/cool-module",
                    ref="v1.0.0",
                    resolved_sha="a" * 40,
                    entry="mod.nu",
                    name="cool-module",
                    owner="someone",
                    pkg_type="module",
                )


class MainEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_full_flow_writes_spec_and_manifest_without_write_flag(self):
        sha = "f" * 40

        def fake_ls_remote(cmd, **kwargs):
            if cmd[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{sha}\tHEAD\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_clone(git_url, resolved_sha, dest):
            dest.mkdir(parents=True)
            (dest / "mod.nu").write_text("export def run [] {}\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "spec.json"
            manifest_path = Path(tmp) / "manifest-archives.json"

            with (
                mock.patch.object(self.mod.subprocess, "run", side_effect=fake_ls_remote),
                mock.patch.object(self.mod, "shallow_clone_at", side_effect=fake_clone),
                mock.patch.object(
                    self.mod,
                    "upload_to_release",
                    return_value="https://github.com/owner/repo/releases/download/tag/asset.tar.gz",
                ),
            ):
                code = self.mod.main(
                    [
                        "--git-url", "https://github.com/someone/cool-module",
                        "--ref", "main",
                        "--entry", "mod.nu",
                        "--name", "cool-module",
                        "--owner", "someone",
                        "--type", "module",
                        "--description", "A cool module",
                        "--tags", '["module"]',
                        "--nu-version", ">=0.114.0",
                        "--activation-kind", "nu-module",
                        "--activation-import", "all",
                        "--provisional",
                        "--deferral-reason", "test deferral",
                        "--release-repo", "owner/repo",
                        "--out", str(out_path),
                        "--manifest-archives", str(manifest_path),
                    ]
                )

            self.assertEqual(code, 0)
            spec = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(spec["owner"], "someone")
            self.assertEqual(spec["artifact"]["kind"], "archive")
            self.assertEqual(spec["version"], "0.1.0-fffffff")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest[0]["resolved_sha"], sha)

    def test_rejects_invalid_tags_json(self):
        code = self.mod.main(
            [
                "--git-url", "https://github.com/someone/cool-module",
                "--ref", "main",
                "--entry", "mod.nu",
                "--name", "cool-module",
                "--owner", "someone",
                "--type", "module",
                "--description", "A cool module",
                "--tags", "not-json",
                "--nu-version", ">=0.114.0",
                "--release-repo", "owner/repo",
            ]
        )
        self.assertEqual(code, 1)

    def test_rejects_bad_activation_import_mode_before_network(self):
        calls = []
        with mock.patch.object(
            self.mod.subprocess, "run", side_effect=lambda *a, **k: calls.append(1)
        ):
            code = self.mod.main(
                [
                    "--git-url", "https://github.com/someone/nutest",
                    "--ref", "v1.0.0",
                    "--entry", "mod.nu",
                    "--name", "nutest",
                    "--owner", "someone",
                    "--type", "module",
                    "--description", "desc",
                    "--tags", "[]",
                    "--nu-version", ">=0.114.0",
                    "--activation-kind", "nu-module",
                    "--activation-import", "module",
                    "--release-repo", "owner/repo",
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(calls, [], "should fail fast before any git/network call")

    def test_missing_entry_file_after_clone_fails(self):
        def fake_ls_remote(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=("a" * 40) + "\tHEAD\n", stderr="")

        def fake_clone(git_url, resolved_sha, dest):
            dest.mkdir(parents=True)
            # entry file deliberately not created

        with mock.patch.object(self.mod.subprocess, "run", side_effect=fake_ls_remote), mock.patch.object(
            self.mod, "shallow_clone_at", side_effect=fake_clone
        ):
            code = self.mod.main(
                [
                    "--git-url", "https://github.com/someone/cool-module",
                    "--ref", "main",
                    "--entry", "mod.nu",
                    "--name", "cool-module",
                    "--owner", "someone",
                    "--type", "module",
                    "--description", "desc",
                    "--tags", "[]",
                    "--nu-version", ">=0.114.0",
                    "--release-repo", "owner/repo",
                ]
            )
        self.assertEqual(code, 1)

    def test_write_flag_success_chains_into_add_package_after_upload(self):
        sha = "e" * 40
        upload_url = "https://github.com/owner/repo/releases/download/tag/asset.tar.gz"
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{sha}\tHEAD\n", stderr="")
            if "add-package.py" in cmd[1]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_clone(git_url, resolved_sha, dest):
            dest.mkdir(parents=True)
            (dest / "run.nu").write_text("export def main [] {}\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "spec.json"
            manifest_path = Path(tmp) / "manifest-archives.json"

            with (
                mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run),
                mock.patch.object(self.mod, "shallow_clone_at", side_effect=fake_clone),
                mock.patch.object(self.mod, "upload_to_release", return_value=upload_url) as mock_upload,
            ):
                code = self.mod.main(
                    [
                        "--git-url", "https://github.com/someone/cool-script",
                        "--ref", "main",
                        "--entry", "run.nu",
                        "--name", "cool-script",
                        "--owner", "someone",
                        "--type", "script",
                        "--description", "A cool script",
                        "--tags", '["script"]',
                        "--nu-version", ">=0.114.0",
                        "--release-repo", "owner/repo",
                        "--out", str(out_path),
                        "--manifest-archives", str(manifest_path),
                        "--write",
                    ]
                )

            self.assertEqual(code, 0)
            mock_upload.assert_called_once()
            add_package_calls = [c for c in calls if len(c) > 1 and "add-package.py" in c[1]]
            self.assertEqual(len(add_package_calls), 1)
            self.assertIn("--write", add_package_calls[0])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest[0]["resolved_sha"], sha)

    def test_write_flag_failure_after_upload_propagates_returncode_without_recording_manifest(self):
        sha = "d" * 40

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{sha}\tHEAD\n", stderr="")
            if len(cmd) > 1 and "add-package.py" in cmd[1]:
                return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="registry validation failed")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_clone(git_url, resolved_sha, dest):
            dest.mkdir(parents=True)
            (dest / "run.nu").write_text("export def main [] {}\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "spec.json"
            manifest_path = Path(tmp) / "manifest-archives.json"

            with (
                mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run),
                mock.patch.object(self.mod, "shallow_clone_at", side_effect=fake_clone),
                mock.patch.object(
                    self.mod,
                    "upload_to_release",
                    return_value="https://github.com/owner/repo/releases/download/tag/asset.tar.gz",
                ) as mock_upload,
            ):
                code = self.mod.main(
                    [
                        "--git-url", "https://github.com/someone/cool-script",
                        "--ref", "main",
                        "--entry", "run.nu",
                        "--name", "cool-script",
                        "--owner", "someone",
                        "--type", "script",
                        "--description", "A cool script",
                        "--tags", '["script"]',
                        "--nu-version", ">=0.114.0",
                        "--release-repo", "owner/repo",
                        "--out", str(out_path),
                        "--manifest-archives", str(manifest_path),
                        "--write",
                    ]
                )

            self.assertEqual(code, 3)
            mock_upload.assert_called_once()
            self.assertFalse(manifest_path.exists(), "manifest should not record a package the registry rejected")

    def test_repo_and_commit_aliases_and_deferral_reason(self):
        sha = "f" * 40
        upload_url = "https://github.com/numan-cli/numan-registry/releases/download/archive-someone-cool-mod-0.1.0-fffffff/someone-cool-mod-0.1.0-fffffff.tar.gz"
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{sha}\tHEAD\n", stderr="")
            if len(cmd) > 1 and "add-package.py" in cmd[1]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_clone(git_url, resolved_sha, dest):
            dest.mkdir(parents=True)
            (dest / "mod.nu").write_text("export def main [] {}\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "spec.json"
            manifest_path = Path(tmp) / "manifest-archives.json"

            with (
                mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run),
                mock.patch.object(self.mod, "shallow_clone_at", side_effect=fake_clone),
                mock.patch.object(self.mod, "upload_to_release", return_value=upload_url) as mock_upload,
            ):
                code = self.mod.main(
                    [
                        "--repo", "someone/cool-mod",
                        "--commit", sha,
                        "--entry", "mod.nu",
                        "--type", "module",
                        "--description", "A cool module",
                        "--tags", '["module"]',
                        "--nu-version", ">=0.114.0 <0.115.0",
                        "--activation-kind", "nu-module",
                        "--activation-import", "all",
                        "--provisional",
                        "--deferral-reason", "Wave 4 Lane 2 non-binary script archive intake",
                        "--out", str(out_path),
                        "--manifest-archives", str(manifest_path),
                        "--write",
                    ]
                )

            self.assertEqual(code, 0)
            mock_upload.assert_called_once()
            add_package_calls = [c for c in calls if len(c) > 1 and "add-package.py" in c[1]]
            self.assertEqual(len(add_package_calls), 1)
            self.assertIn("--provisional", add_package_calls[0])
            self.assertIn("--deferral-reason", add_package_calls[0])
            self.assertIn("Wave 4 Lane 2 non-binary script archive intake", add_package_calls[0])

    def test_extract_owner_name_from_url(self):
        cases = [
            ("git@github.com:owner/repo.git", ("owner", "repo")),
            ("https://github.com/owner/repo.git", ("owner", "repo")),
            ("https://github.com/owner/repo", ("owner", "repo")),
            ("git://github.com/owner/repo.git", ("owner", "repo")),
            ("ssh://git@github.com/owner/repo.git", ("owner", "repo")),
            ("owner/repo.git", ("owner", "repo")),
            ("owner/repo", ("owner", "repo")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                if not any(url.startswith(p) for p in ("http://", "https://", "git://", "ssh://", "git@")):
                    norm_url = f"https://github.com/{url}"
                else:
                    norm_url = url
                self.assertEqual(self.mod._extract_owner_name_from_url(norm_url), expected)

    def test_provisional_requires_deferral_reason_fails_fast(self):
        mock_upload = mock.MagicMock()
        with mock.patch.object(self.mod, "upload_to_release", mock_upload):
            code = self.mod.main(
                [
                    "--repo", "someone/cool-mod",
                    "--commit", "a" * 40,
                    "--entry", "mod.nu",
                    "--type", "module",
                    "--description", "desc",
                    "--tags", "[]",
                    "--nu-version", ">=0.114.0",
                    "--activation-kind", "nu-module",
                    "--provisional",
                ]
            )
        self.assertEqual(code, 1)
        mock_upload.assert_not_called()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
