#!/usr/bin/env python3.12
"""Unit tests for scripts/prepare_upstream_candidate.py."""

from __future__ import annotations

import base64
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "prepare_upstream_candidate.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("prepare_upstream_candidate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_module_fixture(
    owner: str,
    name: str,
    old_ver: str,
    new_tag: str,
    prev_url: str,
    entry: str,
    assets: list[dict],
    archive_root: str | None = None,
) -> tuple[dict, dict]:
    artifact: dict = {
        "kind": "archive",
        "url": prev_url,
        "sha256": "a" * 64,
        "entry": entry,
    }
    if archive_root:
        artifact["archive_root"] = archive_root
    index = {
        "schema_version": 1,
        "packages": [
            {
                "id": {"owner": owner, "name": name},
                "description": f"{name} module",
                "repo": f"https://github.com/{owner}/{name}",
                "type": "module",
                "tags": ["module"],
                "versions": [
                    {
                        "version": old_ver,
                        "nu_version": ">=0.114.0",
                        "verified_with": ["0.114.0"],
                        "artifact": artifact,
                        "activation": {"kind": "nu-module", "import": "all"},
                    }
                ],
            }
        ],
    }
    hits = {
        "upstream_updates": [
            {
                "kind": "upstream",
                "package": f"{owner}/{name}",
                "type": "module",
                "indexed": old_ver,
                "upstream": new_tag,
                "assets": assets,
            }
        ]
    }
    return index, hits


def _make_plugin_fixture(
    owner: str,
    name: str,
    old_ver: str,
    new_tag: str,
    targets: dict[str, dict],
    assets: list[dict],
    tags: list[str] | None = None,
    source: dict | None = None,
    plugin_source: str | None = None,
) -> tuple[dict, dict]:
    ver_entry: dict = {
        "version": old_ver,
        "nu_version": ">=0.114.0 <0.115.0",
        "verified_with": ["0.114.1"],
        "artifact": {"kind": "binary", "targets": targets},
    }
    if source is not None:
        ver_entry["source"] = source
    hit_entry: dict = {
        "kind": "upstream",
        "package": f"{owner}/{name}",
        "type": "plugin",
        "indexed": old_ver,
        "upstream": new_tag,
        "assets": assets,
    }
    if plugin_source is not None:
        hit_entry["plugin_source"] = plugin_source
    index = {
        "schema_version": 1,
        "packages": [
            {
                "id": {"owner": owner, "name": name},
                "description": f"{name} plugin",
                "repo": f"https://github.com/{owner}/{name}",
                "type": "plugin",
                "tags": tags or ["plugin"],
                "versions": [ver_entry],
            }
        ],
    }
    return index, {"upstream_updates": [hit_entry]}


class _FakeIntakeArchive:
    @staticmethod
    def main(argv: list[str]) -> int:
        assert argv[argv.index("--git-url") + 1] == "https://github.com/nushell-prophet/numd"
        assert argv[argv.index("--ref") + 1] == "0.5.0"
        assert argv[argv.index("--version") + 1] == "0.5.0"
        assert argv[argv.index("--entry") + 1] == "numd/mod.nu"
        assert argv[argv.index("--activation-kind") + 1] == "nu-module"
        assert argv[argv.index("--activation-import") + 1] == "all"
        out_path = Path(argv[argv.index("--out") + 1])
        out_path.write_text(
            json.dumps(
                {
                    "owner": "nushell-prophet",
                    "name": "numd",
                    "description": "numd module",
                    "repo": "https://github.com/nushell-prophet/numd",
                    "type": "module",
                    "tags": ["module"],
                    "version": "0.5.0",
                    "nu_version": ">=0.114.0",
                    "artifact": {
                        "kind": "archive",
                        "url": "https://github.com/numan-cli/numan-registry/releases/download/archive-nushell-prophet-numd-0.5.0/nushell-prophet-numd-0.5.0.tar.gz",
                        "entry": "numd/mod.nu",
                    },
                    "source": {
                        "git": "https://github.com/nushell-prophet/numd",
                        "rev": "c" * 40,
                        "cargo_name": "numd",
                    },
                }
            ),
            encoding="utf-8",
        )
        return 0


class PrepareUpstreamCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_module_with_upstream_zip_asset_updates_archive_root_and_preserves_activation(self):
        new_url = "https://github.com/vyadh/nutest/releases/download/v1.3.0/nutest-1.3.0.zip"
        index, hits = _make_module_fixture(
            owner="vyadh",
            name="nutest",
            old_ver="1.2.0",
            new_tag="v1.3.0",
            prev_url="https://github.com/vyadh/nutest/releases/download/v1.2.0/nutest-1.2.0.zip",
            entry="nutest/mod.nu",
            assets=[{"name": "nutest-1.3.0.zip", "url": new_url}],
            archive_root="nutest-1.2.0",
        )
        spec = self.mod.prepare_candidate(index, hits, "vyadh/nutest")
        self.assertEqual(spec["version"], "1.3.0")
        self.assertEqual(spec["artifact"]["url"], new_url)
        self.assertEqual(spec["artifact"]["entry"], "nutest/mod.nu")
        self.assertEqual(spec["artifact"]["archive_root"], "nutest-1.3.0")
        self.assertEqual(spec["activation"], {"kind": "nu-module", "import": "all"})

    def test_module_without_upstream_asset_invokes_intake_archive(self):
        prev_url = (
            "https://github.com/numan-cli/numan-registry/releases/download/"
            "archive-nushell-prophet-numd-0.4.0/nushell-prophet-numd-0.4.0.tar.gz"
        )
        index, hits = _make_module_fixture(
            owner="nushell-prophet",
            name="numd",
            old_ver="0.4.0",
            new_tag="0.5.0",
            prev_url=prev_url,
            entry="numd/mod.nu",
            assets=[],
        )
        with mock.patch.object(self.mod, "_load_intake_archive", return_value=_FakeIntakeArchive):
            spec = self.mod.prepare_candidate(index, hits, "nushell-prophet/numd")
        self.assertEqual(spec["version"], "0.5.0")
        self.assertEqual(spec["artifact"]["entry"], "numd/mod.nu")
        self.assertEqual(spec["activation"], {"kind": "nu-module", "import": "all"})
        self.assertEqual(spec["source"]["rev"], "c" * 40)

    def test_upstream_asset_plugin_maps_targets_and_cargo_nu_constraint(self):
        base = "https://github.com/SuaveIV/nu_plugin_audio/releases/download"
        targets = {
            "x86_64-unknown-linux-gnu": {
                "url": f"{base}/v0.2.10/nu_plugin_audio-0.2.10-x86_64-unknown-linux-gnu.tar.gz",
                "sha256": "1" * 64,
                "executable_path": "nu_plugin_audio-0.2.10/nu_plugin_audio",
            },
            "x86_64-pc-windows-msvc": {
                "url": f"{base}/v0.2.10/nu_plugin_audio-0.2.10-x86_64-pc-windows-msvc.zip",
                "sha256": "2" * 64,
                "executable_path": "nu_plugin_audio.exe",
            },
        }
        assets = [
            {
                "name": "nu_plugin_audio-0.2.13-x86_64-unknown-linux-gnu.tar.gz",
                "url": f"{base}/v0.2.13/nu_plugin_audio-0.2.13-x86_64-unknown-linux-gnu.tar.gz",
            },
            {
                "name": "nu_plugin_audio-0.2.13-x86_64-pc-windows-msvc.zip",
                "url": f"{base}/v0.2.13/nu_plugin_audio-0.2.13-x86_64-pc-windows-msvc.zip",
            },
        ]
        index, hits = _make_plugin_fixture(
            "SuaveIV", "nu_plugin_audio", "0.2.10", "v0.2.13", targets, assets
        )
        with mock.patch.object(
            self.mod, "fetch_cargo_nu_constraint", return_value=">=0.116.0 <0.117.0"
        ):
            spec = self.mod.prepare_candidate(index, hits, "SuaveIV/nu_plugin_audio")
        self.assertEqual(spec["version"], "0.2.13")
        self.assertEqual(spec["nu_version"], ">=0.116.0 <0.117.0")
        linux_target = spec["artifact"]["targets"]["x86_64-unknown-linux-gnu"]
        win_target = spec["artifact"]["targets"]["x86_64-pc-windows-msvc"]
        self.assertEqual(linux_target["url"], assets[0]["url"])
        self.assertEqual(linux_target["executable_path"], "nu_plugin_audio-0.2.13/nu_plugin_audio")
        self.assertEqual(win_target["url"], assets[1]["url"])
        self.assertEqual(win_target["executable_path"], "nu_plugin_audio.exe")

    def test_ci_built_plugin_preserves_and_resolves_source_provenance(self):
        base = "https://github.com/numan-cli/numan-plugins/releases/download"
        targets = {
            "aarch64-unknown-linux-gnu": {
                "url": f"{base}/nu_plugin_file-0.28.0/nu_plugin_file-0.28.0-aarch64-linux.tar.gz",
                "sha256": "1" * 64,
                "executable_path": "nu_plugin_file",
            },
            "x86_64-unknown-linux-gnu": {
                "url": f"{base}/nu_plugin_file-0.28.0/nu_plugin_file-0.28.0-linux.tar.gz",
                "sha256": "2" * 64,
                "executable_path": "nu_plugin_file",
            },
        }
        assets = [
            {
                "name": "nu_plugin_file-0.29.0-aarch64-linux.tar.gz",
                "url": f"{base}/nu_plugin_file-0.29.0/nu_plugin_file-0.29.0-aarch64-linux.tar.gz",
            },
            {
                "name": "nu_plugin_file-0.29.0-linux.tar.gz",
                "url": f"{base}/nu_plugin_file-0.29.0/nu_plugin_file-0.29.0-linux.tar.gz",
            },
        ]
        source = {
            "git": "https://github.com/fdncred/nu_plugin_file",
            "rev": "a" * 40,
            "cargo_name": "nu_plugin_file",
        }
        index, hits = _make_plugin_fixture(
            "fdncred",
            "nu_plugin_file",
            "0.28.0",
            "v0.29.0",
            targets,
            assets,
            tags=["plugin", "ci-built"],
            source=source,
            plugin_source="ci-built-ready",
        )
        with (
            mock.patch.object(
                self.mod, "fetch_cargo_nu_constraint", return_value=">=0.116.0 <0.117.0"
            ),
            mock.patch.object(self.mod, "resolve_tag_commit_sha", return_value="b" * 40),
        ):
            spec = self.mod.prepare_candidate(index, hits, "fdncred/nu_plugin_file")
        self.assertEqual(spec["source"]["rev"], "b" * 40)
        self.assertEqual(
            spec["artifact"]["targets"]["aarch64-unknown-linux-gnu"]["url"], assets[0]["url"]
        )
        self.assertEqual(
            spec["artifact"]["targets"]["x86_64-unknown-linux-gnu"]["url"], assets[1]["url"]
        )

    def test_plugin_rejects_unresolvable_cargo_nu_constraint(self):
        targets = {
            "x86_64-unknown-linux-gnu": {
                "url": "https://e/l.tar.gz",
                "sha256": "1" * 64,
                "executable_path": "nu_plugin_audio",
            }
        }
        assets = [
            {
                "name": "nu_plugin_audio-x86_64-unknown-linux-gnu.tar.gz",
                "url": "https://e/l2.tar.gz",
            }
        ]
        index, hits = _make_plugin_fixture(
            "SuaveIV", "nu_plugin_audio", "0.2.10", "v0.2.13", targets, assets
        )
        with mock.patch.object(self.mod, "fetch_cargo_nu_constraint", return_value=None):
            with self.assertRaises(ValueError):
                self.mod.prepare_candidate(index, hits, "SuaveIV/nu_plugin_audio")

    def test_plugin_rejects_missing_target(self):
        targets = {
            "x86_64-unknown-linux-gnu": {
                "url": "https://e/l.tar.gz",
                "sha256": "1" * 64,
                "executable_path": "nu_plugin_audio",
            },
            "x86_64-pc-windows-msvc": {
                "url": "https://e/w.zip",
                "sha256": "2" * 64,
                "executable_path": "nu_plugin_audio.exe",
            },
        }
        assets = [
            {
                "name": "nu_plugin_audio-x86_64-unknown-linux-gnu.tar.gz",
                "url": "https://e/l2.tar.gz",
            }
        ]
        index, hits = _make_plugin_fixture(
            "SuaveIV", "nu_plugin_audio", "0.2.10", "v0.2.13", targets, assets
        )
        with self.assertRaises(ValueError):
            self.mod.prepare_candidate(index, hits, "SuaveIV/nu_plugin_audio")

    def test_fetch_cargo_nu_constraint_parses_base64_cargo_toml(self):
        cargo_toml = b'[dependencies]\nnu-plugin = "0.116.1"\n'
        payload = json.dumps({"content": base64.b64encode(cargo_toml).decode("ascii")}).encode(
            "utf-8"
        )

        class FakeResp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(self.mod, "http_opener") as opener_fn:
            opener = mock.MagicMock()
            opener.open.return_value = FakeResp()
            opener_fn.return_value = opener
            band = self.mod.fetch_cargo_nu_constraint(
                "https://github.com/SuaveIV/nu_plugin_audio", "v0.2.13"
            )
            self.assertEqual(band, ">=0.116.0 <0.117.0")


if __name__ == "__main__":
    unittest.main()
