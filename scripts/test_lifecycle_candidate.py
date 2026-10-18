"""Safety and signature checks for real-Nu candidate lifecycle proving."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import http.client
import urllib.parse
from contextlib import contextmanager

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def load_module():
    spec = importlib.util.spec_from_file_location("candidate_lifecycle_test", Path(__file__).with_name("lifecycle-prove.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def loopback_response(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValueError("test requests must use loopback HTTP")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        connection.request("GET", parsed.path)
        response = connection.getresponse()
        if response.status >= 400:
            raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
        yield response
    finally:
        connection.close()


class CandidateLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_environment_drops_inherited_secrets_and_unsigned_bypass(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NUMAN_ALLOW_UNSIGNED": "1", "SERVICE_TOKEN": "not-a-real-token", "NUPM_HOME": "/caller/nupm"}):
            home = Path(tmp) / "home"
            env = self.mod.isolated_environment(home)
            self.assertNotIn("NUMAN_ALLOW_UNSIGNED", env)
            self.assertNotIn("SERVICE_TOKEN", env)
            self.assertNotIn("NUPM_HOME", env)
            for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "TEMP", "TMP"):
                self.assertTrue(Path(env[key]).is_relative_to(home.resolve()))
                self.assertTrue(Path(env[key]).is_dir())

    def test_probe_rejects_config_and_data_path_escape_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            data = home / "data/nushell"
            good = {"version": "0.114.1", "plugin_path": str(home / "plugin.msgpackz"), "data_dir": str(data), "vendor": [str(data / "vendor/autoload")]}
            with mock.patch.object(self.mod.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(good))):
                self.assertEqual(self.mod.probe_isolated_nu(Path("nu"), home, {})["version"], "0.114.1")
            for key in ("plugin_path", "data_dir"):
                bad = {**good, key: str(Path(tmp) / "outside")}
                with mock.patch.object(self.mod.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(bad))), self.assertRaisesRegex(ValueError, "escaped"):
                    self.mod.probe_isolated_nu(Path("nu"), home, {})
            with mock.patch.object(self.mod.subprocess, "run", return_value=mock.Mock(stdout=json.dumps({**good, "vendor": []}))):
                self.assertEqual(self.mod.probe_isolated_nu(Path("nu"), home, {})["vendor"], [])

    def test_candidate_registry_signs_canonical_bytes_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            original = b'{ "packages": [], "schema_version": 1, "updated_at": "2026-10-18T00:00:00Z" }\n'
            path.write_bytes(original)
            with self.mod.candidate_registry(path) as (url, public):
                with loopback_response(url) as response:
                    self.assertEqual(response.read(), original)
                with loopback_response(url + ".sig") as response:
                    envelope = json.load(response)
                self.assertEqual(envelope["key_id"], "lifecycle-candidate")
                canonical = json.dumps(json.loads(original), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
                Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(envelope["signature"]), canonical)
                with self.assertRaises(urllib.error.HTTPError):
                    with loopback_response(url.replace("index.json", "private.key")):
                        self.fail("private key path must not be served")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["index.json"])

    def test_version_is_pinned_only_for_install(self):
        steps = {step.name: step.args for step in self.mod.build_steps("owner/pkg", "1.0.0-commit")}
        self.assertEqual(steps["install"], ["install", "owner/pkg@1.0.0-commit"])
        self.assertEqual(steps["activate"], ["activate", "owner/pkg"])

    def test_candidate_version_mismatch_cannot_earn_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "root"
            root.mkdir()
            index = base / "index.json"
            index.write_text(json.dumps({"packages": [{"id": {"owner": "owner", "name": "pkg"}, "type": "plugin", "versions": [{"version": "1.0.0", "nu_version": ">=0.114.0 <0.115.0"}]}]}))
            calls = []

            def run(step, **_kwargs):
                calls.append(step.name)
                if step.name == "install":
                    (root / "lockfile").write_text(json.dumps({"packages": {"owner/pkg": {"version": "2.0.0"}}}))
                return subprocess.CompletedProcess([], 0)

            with mock.patch.object(self.mod, "probe_isolated_nu", return_value={"version": "0.114.1"}), mock.patch.object(self.mod, "sha256_file", return_value="a" * 64), mock.patch.object(self.mod, "prepare_nu_search_dir", side_effect=lambda _nu, directory: directory), mock.patch.object(self.mod, "run_step", side_effect=run):
                status = self.mod.prove("owner/pkg", numan=Path("numan"), nu=Path("nu"), root=root, keep_root=True, candidate_index=index)
            self.assertEqual(status, 2)
            self.assertNotIn("activate", calls)
            self.assertIn("add signed candidate registry", calls)
