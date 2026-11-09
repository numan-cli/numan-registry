#!/usr/bin/env python3.12
"""Unit tests for scripts/prepare_upstream_candidate.py."""

from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
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


class PrepareUpstreamCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_module_with_upstream_zip_asset_updates_archive_root_and_preserves_activation(self):
        index = {
            "schema_version": 1,
            "packages": [
                {
                    "id": {"owner": "vyadh", "name": "nutest"},
                    "description": "Test framework",
                    "repo": "https://github.com/vyadh/nutest",
                    "type": "module",
                    "tags": ["module", "testing"],
                    "versions": [
                        {
                            "version": "1.2.0",
                            "nu_version": ">=0.114.0",
                            "verified_with": ["0.114.0"],
                            "artifact": {
                                "kind": "archive",
                                "url": "https://github.com/vyadh/nutest/releases/download/v1.2.0/nutest-1.2.0.zip",
                                "sha256": "a" * 64,
                                "entry": "nutest/mod.nu",
                                "archive_root": "nutest-1.2.0",
                            },
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
                    "package": "vyadh/nutest",
                    "type": "module",
                    "indexed": "1.2.0",
                    "upstream": "v1.3.0",
                    "assets": [
                        {
                            "name": "nutest-1.3.0.zip",
                            "url": "https://github.com/vyadh/nutest/releases/download/v1.3.0/nutest-1.3.0.zip",
                        }
                    ],
                }
            ]
        }
        spec = self.mod.prepare_candidate(index, hits, "vyadh/nutest")
        self.assertEqual(spec["version"], "1.3.0")
        self.assertEqual(
            spec["artifact"]["url"],
            "https://github.com/vyadh/nutest/releases/download/v1.3.0/nutest-1.3.0.zip",
        )
        self.assertEqual(spec["artifact"]["entry"], "nutest/mod.nu")
        self.assertEqual(spec["artifact"]["archive_root"], "nutest-1.3.0")
        self.assertEqual(spec["activation"], {"kind": "nu-module", "import": "all"})

    def test_module_without_upstream_asset_invokes_intake_archive(self):
        index = {
            "schema_version": 1,
            "packages": [
                {
                    "id": {"owner": "nushell-prophet", "name": "numd"},
                    "description": "Markdown utility",
                    "repo": "https://github.com/nushell-prophet/numd",
                    "type": "module",
                    "tags": ["module", "markdown"],
                    "versions": [
                        {
                            "version": "0.4.0",
                            "nu_version": ">=0.114.0",
                            "verified_with": ["0.114.1"],
                            "artifact": {
                                "kind": "archive",
                                "url": "https://github.com/numan-cli/numan-registry/releases/download/archive-nushell-prophet-numd-0.4.0/nushell-prophet-numd-0.4.0.tar.gz",
                                "sha256": "b" * 64,
                                "entry": "numd/mod.nu",
                            },
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
                    "package": "nushell-prophet/numd",
                    "type": "module",
                    "indexed": "0.4.0",
                    "upstream": "0.5.0",
                    "assets": [],
                }
            ]
        }

        class FakeIntakeArchive:
            @staticmethod
            def main(argv: list[str]) -> int:
                out_idx = argv.index("--out") + 1
                out_path = Path(argv[out_idx])
                out_path.write_text(
                    json.dumps(
                        {
                            "owner": "nushell-prophet",
                            "name": "numd",
                            "description": "Markdown utility",
                            "repo": "https://github.com/nushell-prophet/numd",
                            "type": "module",
                            "tags": ["module", "markdown"],
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

        with mock.patch.object(self.mod, "_load_intake_archive", return_value=FakeIntakeArchive):
            spec = self.mod.prepare_candidate(index, hits, "nushell-prophet/numd")
        self.assertEqual(spec["version"], "0.5.0")
        self.assertEqual(spec["artifact"]["entry"], "numd/mod.nu")
        self.assertEqual(spec["activation"], {"kind": "nu-module", "import": "all"})
        self.assertEqual(spec["source"]["rev"], "c" * 40)

    def test_upstream_asset_plugin_maps_targets_and_cargo_nu_constraint(self):
        index = {
            "schema_version": 1,
            "packages": [
                {
                    "id": {"owner": "SuaveIV", "name": "nu_plugin_audio"},
                    "description": "Audio plugin",
                    "repo": "https://github.com/SuaveIV/nu_plugin_audio",
                    "type": "plugin",
                    "tags": ["plugin", "audio"],
                    "versions": [
                        {
                            "version": "0.2.10",
                            "nu_version": ">=0.114.0 <0.115.0",
                            "verified_with": ["0.114.1"],
                            "artifact": {
                                "kind": "binary",
                                "targets": {
                                    "x86_64-unknown-linux-gnu": {
                                        "url": "https://github.com/SuaveIV/nu_plugin_audio/releases/download/v0.2.10/nu_plugin_audio-0.2.10-x86_64-unknown-linux-gnu.tar.gz",
                                        "sha256": "1" * 64,
                                        "executable_path": "nu_plugin_audio-0.2.10/nu_plugin_audio",
                                    },
                                    "x86_64-pc-windows-msvc": {
                                        "url": "https://github.com/SuaveIV/nu_plugin_audio/releases/download/v0.2.10/nu_plugin_audio-0.2.10-x86_64-pc-windows-msvc.zip",
                                        "sha256": "2" * 64,
                                        "executable_path": "nu_plugin_audio.exe",
                                    },
                                },
                            },
                        }
                    ],
                }
            ],
        }
        hits = {
            "upstream_updates": [
                {
                    "kind": "upstream",
                    "package": "SuaveIV/nu_plugin_audio",
                    "type": "plugin",
                    "indexed": "0.2.10",
                    "upstream": "v0.2.13",
                    "assets": [
                        {
                            "name": "nu_plugin_audio-0.2.13-x86_64-unknown-linux-gnu.tar.gz",
                            "url": "https://github.com/SuaveIV/nu_plugin_audio/releases/download/v0.2.13/nu_plugin_audio-0.2.13-x86_64-unknown-linux-gnu.tar.gz",
                        },
                        {
                            "name": "nu_plugin_audio-0.2.13-x86_64-pc-windows-msvc.zip",
                            "url": "https://github.com/SuaveIV/nu_plugin_audio/releases/download/v0.2.13/nu_plugin_audio-0.2.13-x86_64-pc-windows-msvc.zip",
                        },
                    ],
                }
            ]
        }
        with mock.patch.object(
            self.mod, "fetch_cargo_nu_constraint", return_value=">=0.116.0 <0.117.0"
        ):
            spec = self.mod.prepare_candidate(index, hits, "SuaveIV/nu_plugin_audio")
        self.assertEqual(spec["version"], "0.2.13")
        self.assertEqual(spec["nu_version"], ">=0.116.0 <0.117.0")
        self.assertEqual(
            spec["artifact"]["targets"]["x86_64-unknown-linux-gnu"]["executable_path"],
            "nu_plugin_audio-0.2.13/nu_plugin_audio",
        )
        self.assertEqual(
            spec["artifact"]["targets"]["x86_64-pc-windows-msvc"]["executable_path"],
            "nu_plugin_audio.exe",
        )

    def test_plugin_rejects_missing_target(self):
        index = {
            "schema_version": 1,
            "packages": [
                {
                    "id": {"owner": "SuaveIV", "name": "nu_plugin_audio"},
                    "description": "Audio plugin",
                    "repo": "https://github.com/SuaveIV/nu_plugin_audio",
                    "type": "plugin",
                    "tags": ["plugin"],
                    "versions": [
                        {
                            "version": "0.2.10",
                            "nu_version": ">=0.114.0 <0.115.0",
                            "artifact": {
                                "kind": "binary",
                                "targets": {
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
                                },
                            },
                        }
                    ],
                }
            ],
        }
        hits = {
            "upstream_updates": [
                {
                    "kind": "upstream",
                    "package": "SuaveIV/nu_plugin_audio",
                    "type": "plugin",
                    "indexed": "0.2.10",
                    "upstream": "v0.2.13",
                    "assets": [
                        {
                            "name": "nu_plugin_audio-x86_64-unknown-linux-gnu.tar.gz",
                            "url": "https://e/l2.tar.gz",
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(ValueError):
            self.mod.prepare_candidate(index, hits, "SuaveIV/nu_plugin_audio")

    def test_fetch_cargo_nu_constraint_parses_base64_cargo_toml(self):
        cargo_toml = b'[dependencies]\nnu-plugin = "0.116.1"\n'
        payload = json.dumps({"content": base64.b64encode(cargo_toml).decode("ascii")}).encode("utf-8")

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
