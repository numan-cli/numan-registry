#!/usr/bin/env python3.12
"""Unit checks for scripts/append-verified-with.py."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "append-verified-with.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("append_verified_with", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def index_doc():
    return {
        "schema_version": 1,
        "packages": [
            {
                "id": {"owner": "a", "name": "mod"},
                "type": "module",
                "versions": [
                    {"version": "1.0.0", "nu_version": ">=0.113.0 <0.114.0",
                     "verified_with": ["0.113.1"]}
                ],
            }
        ],
    }


def hits_doc():
    return {
        "upstream_updates": [],
        "nu_gaps": [
            {"kind": "nu-gap", "package": "a/mod", "type": "module",
             "indexed": "1.0.0", "constraint": ">=0.113.0 <0.114.0",
             "target_nu": "0.114.1", "verdict": "auto-merge-eligible", "reasons": []}
        ],
    }


class AppendVerifiedWithTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def test_apply_appends_and_sorts(self):
        index = index_doc()
        changed = self.mod.apply(index, hits_doc(), {"a/mod"}, "0.114.1")
        self.assertEqual(changed, ["a/mod"])
        verified = index["packages"][0]["versions"][0]["verified_with"]
        self.assertEqual(verified, ["0.113.1", "0.114.1"])

    def test_apply_skips_unproven_and_review_hits(self):
        index = index_doc()
        hits = hits_doc()
        hits["nu_gaps"][0]["verdict"] = "needs-review"
        changed = self.mod.apply(index, hits, {"a/mod"}, "0.114.1")
        self.assertEqual(changed, [])
        self.assertEqual(
            index["packages"][0]["versions"][0]["verified_with"], ["0.113.1"])

    def test_apply_refuses_moved_artifact(self):
        index = index_doc()
        index["packages"][0]["versions"][0]["version"] = "2.0.0"
        changed = self.mod.apply(index, hits_doc(), {"a/mod"}, "0.114.1")
        self.assertEqual(changed, [])

    def test_apply_is_idempotent(self):
        index = index_doc()
        self.mod.apply(index, hits_doc(), {"a/mod"}, "0.113.1")
        verified = index["packages"][0]["versions"][0]["verified_with"]
        self.assertEqual(verified, ["0.113.1"])

    def test_cli_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            hits_path = Path(tmp) / "hits.json"
            index_path.write_text(json.dumps(index_doc()), encoding="utf-8")
            hits_path.write_text(json.dumps(hits_doc()), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = self.mod.main([
                    "--index", str(index_path), "--hits", str(hits_path),
                    "--proven", "a/mod", "--target-nu", "0.114.1"])
            self.assertEqual(code, 0)
            self.assertIn("dry-run", buf.getvalue().lower())
            reloaded = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(
                reloaded["packages"][0]["versions"][0]["verified_with"], ["0.113.1"])


if __name__ == "__main__":
    unittest.main()
