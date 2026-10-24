#!/usr/bin/env python3.12
"""Unit checks for scripts/watch_indexed.py (TDD: RED before implementation)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "watch_indexed.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("watch_indexed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def pkg(owner, name, ptype, repo, versions, tags=None):
    return {
        "id": {"owner": owner, "name": name},
        "type": ptype,
        "repo": repo,
        "tags": tags or [],
        "versions": versions,
    }


def ver(version, nu="*", verified=None, tier=None):
    entry = {"version": version, "nu_version": nu, "verified_with": verified or []}
    if tier:
        entry["evidence_tier"] = tier
    return entry


class WatchIndexedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_mod()

    def setUp(self) -> None:
        os.environ.pop("GITHUB_OUTPUT", None)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def test_parse_version_tuple(self):
        self.assertEqual(self.mod.parse_version_tuple("v1.2.3"), (1, 2, 3))
        self.assertEqual(self.mod.parse_version_tuple("0.114.1"), (0, 114, 1))
        self.assertIsNone(self.mod.parse_version_tuple("0.1.0-81756dc"))
        self.assertIsNone(self.mod.parse_version_tuple("main"))
        self.assertIsNone(self.mod.parse_version_tuple(""))

    def test_is_newer(self):
        self.assertTrue(self.mod.is_newer("v1.1.0", "1.0.0"))
        self.assertFalse(self.mod.is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(self.mod.is_newer("v0.9.0", "1.0.0"))
        self.assertIsNone(self.mod.is_newer("main", "1.0.0"))

    def test_repo_key_reuses_url_safety(self):
        key_https = self.mod.repo_key("https://github.com/a/mod")
        key_ssh = self.mod.repo_key("git@github.com:a/mod.git")
        self.assertEqual(key_https, "a/mod")
        self.assertEqual(key_ssh, "a/mod")
        self.assertIsNone(self.mod.repo_key("https://example.com/a/mod"))

    def test_detect_upstream_hit(self):
        packages = [pkg("a", "mod", "module", "https://github.com/a/mod", [ver("1.0.0")])]
        releases = {"a/mod": {"tag_name": "v1.1.0", "html_url": "https://example.com/r"}}
        gaps = self.mod.detect(packages, releases, "0.114.1")
        self.assertEqual(len(gaps["upstream_updates"]), 1)
        self.assertEqual(gaps["upstream_updates"][0]["upstream"], "v1.1.0")
        self.assertEqual(gaps["nu_gaps"], [])

    def test_detect_skips_current_and_watch_off(self):
        packages = [
            pkg("a", "mod", "module", "https://github.com/a/mod", [ver("1.0.0")]),
            pkg("b", "old", "module", "https://github.com/b/old", [ver("1.0.0")], tags=["watch-off"]),
        ]
        releases = {
            "a/mod": {"tag_name": "v1.0.0", "html_url": "https://example.com/r"},
            "b/old": {"tag_name": "v9.9.9", "html_url": "https://example.com/r"},
        }
        gaps = self.mod.detect(packages, releases, "0.114.1")
        self.assertEqual(gaps["upstream_updates"], [])
        self.assertEqual(gaps["nu_gaps"], [])

    def test_detect_nu_gap(self):
        packages = [
            pkg("a", "mod", "module", "https://github.com/a/mod",
                [ver("1.0.0", ">=0.113.0 <0.114.0", ["0.113.1"])])
        ]
        gaps = self.mod.detect(packages, {}, "0.114.1")
        self.assertEqual(gaps["upstream_updates"], [])
        self.assertEqual(len(gaps["nu_gaps"]), 1)
        self.assertEqual(gaps["nu_gaps"][0]["package"], "a/mod")

    def test_detect_no_gap_when_verified(self):
        packages = [
            pkg("a", "mod", "module", "https://github.com/a/mod",
                [ver("1.0.0", ">=0.113.0 <0.114.0", ["0.113.1", "0.114.1"])])
        ]
        gaps = self.mod.detect(packages, {}, "0.114.1")
        self.assertEqual(gaps["nu_gaps"], [])

    def test_module_patch_is_eligible(self):
        hit = {"kind": "upstream", "package": "a/mod", "type": "module",
               "indexed": "1.0.1", "upstream": "v1.0.2"}
        d = self.mod.decide(hit, ver("1.0.1"))
        self.assertEqual(d["verdict"], "auto-merge-eligible")

    def test_module_major_needs_review(self):
        hit = {"kind": "upstream", "package": "a/mod", "type": "module",
               "indexed": "1.0.0", "upstream": "v2.0.0"}
        d = self.mod.decide(hit, ver("1.0.0"))
        self.assertEqual(d["verdict"], "needs-review")

    def test_plugin_upstream_needs_rebuild(self):
        hit = {"kind": "upstream", "package": "b/plug", "type": "plugin",
               "indexed": "2.0.0", "upstream": "v2.1.0"}
        d = self.mod.decide(hit, ver("2.0.0"))
        self.assertEqual(d["verdict"], "needs-review")
        self.assertTrue(any("rebuild" in r for r in d["reasons"]))

    def test_script_upstream_is_eligible(self):
        hit = {"kind": "upstream", "package": "s/wttr", "type": "script",
               "indexed": "0.1.0", "upstream": "v0.1.1"}
        d = self.mod.decide(hit, ver("0.1.0"))
        self.assertEqual(d["verdict"], "auto-merge-eligible")

    def test_unparsed_versions_need_review(self):
        hit = {"kind": "upstream", "package": "s/wttr", "type": "script",
               "indexed": "0.1.0-main", "upstream": "v0.2.0"}
        d = self.mod.decide(hit, ver("0.1.0-main"))
        self.assertEqual(d["verdict"], "needs-review")

    def test_module_nu_gap_is_eligible(self):
        hit = {"kind": "nu-gap", "package": "a/mod", "type": "module",
               "indexed": "1.0.0", "constraint": ">=0.113.0 <0.114.0", "target_nu": "0.114.1"}
        d = self.mod.decide(hit, ver("1.0.0", ">=0.113.0 <0.114.0", ["0.113.1"]))
        self.assertEqual(d["verdict"], "auto-merge-eligible")

    def test_snapshot_single_version_nu_gap_is_eligible(self):
        hit = {"kind": "nu-gap", "package": "a/mod", "type": "module",
               "indexed": "0.1.0-abc1234", "constraint": ">=0.114.0 <0.115.0",
               "target_nu": "0.115.1"}
        d = self.mod.decide(hit, ver("0.1.0-abc1234", ">=0.114.0 <0.115.0", ["0.114.1"]),
                            version_count=1)
        self.assertEqual(d["verdict"], "auto-merge-eligible")

    def test_snapshot_multi_version_nu_gap_needs_review(self):
        hit = {"kind": "nu-gap", "package": "a/mod", "type": "module",
               "indexed": "0.1.0-abc1234", "constraint": ">=0.114.0 <0.115.0",
               "target_nu": "0.115.1"}
        d = self.mod.decide(hit, ver("0.1.0-abc1234", ">=0.114.0 <0.115.0", ["0.114.1"]),
                            version_count=2)
        self.assertEqual(d["verdict"], "needs-review")

    def test_plugin_nu_gap_needs_review(self):
        hit = {"kind": "nu-gap", "package": "b/plug", "type": "plugin",
               "indexed": "2.0.0", "constraint": ">=0.113.0 <0.114.0", "target_nu": "0.114.1"}
        d = self.mod.decide(hit, ver("2.0.0", ">=0.113.0 <0.114.0", ["0.113.1"]))
        self.assertEqual(d["verdict"], "needs-review")

    def test_provisional_needs_review(self):
        hit = {"kind": "upstream", "package": "a/mod", "type": "module",
               "indexed": "1.0.0", "upstream": "v1.0.1"}
        d = self.mod.decide(hit, ver("1.0.0", tier="provisional"))
        self.assertEqual(d["verdict"], "needs-review")

    def test_process_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.json"
            out_json = Path(tmp) / "hits.json"
            out_md = Path(tmp) / "report.md"
            index.write_text(json.dumps({
                "schema_version": 1,
                "packages": [pkg("a", "mod", "module",
                                  "https://github.com/a/mod", [ver("1.0.0")])],
            }), encoding="utf-8")
            with mock.patch.object(
                self.mod, "fetch_stable_releases",
                return_value=[{"tag_name": "v1.0.0", "html_url": "https://example.com"}],
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = self.mod.process(
                        index_path=index, target_nu="0.114.1", write=False,
                        report_json=out_json, report_md=out_md)
                self.assertEqual(code, 0)
                self.assertFalse(out_json.exists())
                self.assertFalse(out_md.exists())
                self.assertIn("dry-run", buf.getvalue().lower())

    def test_assets_are_briefed_and_capped(self):
        rel = {"assets": [{"name": f"f{i}.zip", "browser_download_url": f"https://e/{i}"}
                           for i in range(25)] + [{"name": "", "browser_download_url": ""}]}
        briefs = self.mod._asset_briefs(rel)
        self.assertEqual(len(briefs), 20)
        self.assertEqual(briefs[0], {"name": "f0.zip", "url": "https://e/0"})
        self.assertEqual(self.mod._asset_briefs({}), [])

    def test_detect_carries_assets(self):
        packages = [pkg("a", "mod", "module", "https://github.com/a/mod", [ver("1.0.0")])]
        releases = {"a/mod": {"tag_name": "v1.1.0", "html_url": "https://example.com/r",
                              "assets": [{"name": "m.zip",
                                          "browser_download_url": "https://example.com/m.zip"}]}}
        gaps = self.mod.detect(packages, releases, "0.114.1")
        self.assertEqual(gaps["upstream_updates"][0]["assets"],
                         [{"name": "m.zip", "url": "https://example.com/m.zip"}])

    def test_write_outputs_includes_workflow_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "github-output"
            gaps = {
                "upstream_updates": [
                    {"package": "a/mod", "verdict": "needs-review"},
                    {"package": "b/plug", "verdict": "needs-review"},
                ],
                "nu_gaps": [
                    {"package": "c/wttr", "verdict": "auto-merge-eligible"},
                ],
            }
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                self.mod.write_outputs(gaps, "0.114.1")
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("has_updates=true\n", text)
            self.assertIn("hit_count=3\n", text)
            self.assertIn("upstream_count=2\n", text)
            self.assertIn("nu_gap_count=1\n", text)
            self.assertIn("eligible_count=1\n", text)
            self.assertIn("target_nu=0.114.1\n", text)

    def test_version_key_orders_numerically(self):
        versions = ["0.9.0", "0.10.0", "0.2.10", "0.2.8", "main"]
        self.assertEqual(sorted(versions, key=self.mod.version_key),
                         ["main", "0.2.8", "0.2.10", "0.9.0", "0.10.0"])

    def test_widen_constraint_single_minor(self):
        self.assertEqual(
            self.mod.widen_constraint(">=0.113.0 <0.114.0", "0.114.1"),
            ">=0.113.0 <0.115.0")
        self.assertIsNone(
            self.mod.widen_constraint(">=0.113.0 <0.114.0", "0.116.1"))
        self.assertIsNone(self.mod.widen_constraint("*", "0.114.1"))
        self.assertIsNone(
            self.mod.widen_constraint(">=0.113.0 <=0.114.1", "0.114.1"))

    def test_widen_rejects_ragged_upper_bound(self):
        self.assertIsNone(
            self.mod.widen_constraint(">=0.113.0 <0.114.5", "0.114.6"))
        self.assertIsNone(
            self.mod.widen_constraint(">=0.113.0", "0.114.1"))
        self.assertIsNone(
            self.mod.widen_constraint(">=0.113.0 <0.114.0 <0.115.0", "0.114.1"))

    def test_dirty_bound_nu_gap_needs_review(self):
        hit = {"kind": "nu-gap", "package": "a/mod", "type": "module",
               "indexed": "1.0.0", "constraint": ">=1.0.0 <1.1.5",
               "target_nu": "1.1.6", "artifact_id": ""}
        d = self.mod.decide(hit, ver("1.0.0", ">=1.0.0 <1.1.5", []))
        self.assertEqual(d["verdict"], "needs-review")

    def test_nu_gap_plan(self):
        self.assertEqual(
            self.mod.nu_gap_plan(">=0.113.0", "0.114.1"), "append")
        self.assertEqual(
            self.mod.nu_gap_plan(">=0.113.0 <0.114.0", "0.114.1"), "widen")
        self.assertIsNone(
            self.mod.nu_gap_plan(">=0.113.0 <0.114.0", "0.116.1"))
        self.assertIsNone(self.mod.nu_gap_plan("bogus", "0.114.1"))

    def test_unparsed_indexed_nu_gap_needs_review(self):
        hit = {"kind": "nu-gap", "package": "s/wttr", "type": "script",
               "indexed": "0.1.0-main", "constraint": "*",
               "target_nu": "0.114.1", "artifact_id": ""}
        d = self.mod.decide(hit, ver("0.1.0-main", "*"))
        self.assertEqual(d["verdict"], "needs-review")

    def test_detect_carries_artifact_id(self):
        entry = ver("1.0.0")
        entry["artifact"] = {"kind": "archive", "url": "https://example.com/m.zip"}
        packages = [pkg("a", "mod", "module", "https://github.com/a/mod", [entry])]
        releases = {"a/mod": {"tag_name": "v1.1.0", "html_url": "https://example.com/r"}}
        gaps = self.mod.detect(packages, releases, "0.114.1")
        expected = self.mod.artifact_id(entry)
        self.assertTrue(expected)
        self.assertEqual(gaps["upstream_updates"][0]["artifact_id"], expected)

    def test_read_target_nu_file_rejects_non_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.json"
            target.write_text('["0.114.1"]', encoding="utf-8")
            with mock.patch.object(self.mod, "DEFAULT_TARGET_FILE", target):
                self.assertEqual(self.mod._read_target_nu_file(), "")

    def test_process_rejects_invalid_target_nu(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.json"
            index.write_text(json.dumps({"schema_version": 1, "packages": []}),
                             encoding="utf-8")
            with self.assertRaises(ValueError):
                self.mod.process(
                    index_path=index, target_nu="not-a-version", write=False,
                    report_json=Path(tmp) / "h.json", report_md=Path(tmp) / "r.md")

    def test_fetch_latest_release_prefers_highest_semver(self):
        payload = json.dumps([
            {"tag_name": "v1.9.1", "draft": False, "prerelease": False,
             "html_url": "https://example.com/1"},
            {"tag_name": "v2.0.0", "draft": False, "prerelease": False,
             "html_url": "https://example.com/2"},
        ]).encode("utf-8")

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
            rel = self.mod.fetch_latest_release("a/mod")
            self.assertEqual(rel["tag_name"], "v2.0.0")

    def test_fetch_stable_releases_paginates(self):
        full = [{"tag_name": f"v1.0.{i}", "draft": False, "prerelease": False}
                for i in range(35)]

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(self.mod, "http_opener") as opener_fn:
            opener = mock.MagicMock()
            opener.open.side_effect = [
                FakeResp(json.dumps(full[:30]).encode("utf-8")),
                FakeResp(json.dumps(full[30:]).encode("utf-8")),
            ]
            opener_fn.return_value = opener
            stable = self.mod.fetch_stable_releases("a/mod", pages=5)
            self.assertEqual(len(stable), 35)
            self.assertEqual(opener.open.call_count, 2)

    def test_fetch_latest_release_skips_unstable(self):
        payload = json.dumps([
            {"tag_name": "v2.0.0-rc.1", "draft": False, "prerelease": True},
            {"tag_name": "v1.9.0", "draft": False, "prerelease": False,
             "html_url": "https://example.com"},
        ]).encode("utf-8")

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
            rel = self.mod.fetch_latest_release("a/mod")
            self.assertEqual(rel["tag_name"], "v1.9.0")

    def test_select_latest_release_band_scheme_ignores_product_tags(self):
        stable = [{"tag_name": "v1.2.12"}, {"tag_name": "v0.116.0"},
                  {"tag_name": "v0.115.0"}]
        rel = self.mod.select_latest_release(stable, "0.116.0")
        self.assertEqual(rel["tag_name"], "v0.116.0")

    def test_select_latest_release_band_scheme_sees_new_band(self):
        stable = [{"tag_name": "v1.2.12"}, {"tag_name": "v0.117.0"},
                  {"tag_name": "v0.116.0"}]
        rel = self.mod.select_latest_release(stable, "0.116.0")
        self.assertEqual(rel["tag_name"], "v0.117.0")

    def test_select_latest_release_plain_semver_sees_next_major(self):
        stable = [{"tag_name": "v1.0.0"}, {"tag_name": "v0.9.0"},
                  {"tag_name": "v3.5.0"}]
        rel = self.mod.select_latest_release(stable, "0.9.0")
        self.assertEqual(rel["tag_name"], "v1.0.0")

    def test_select_latest_release_band_without_band_releases_is_none(self):
        stable = [{"tag_name": "v1.2.12"}, {"tag_name": "v1.2.11"}]
        self.assertIsNone(self.mod.select_latest_release(stable, "0.116.0"))

    def test_select_latest_release_plain_semver_without_indexed_tag(self):
        # Indexed tag fell out of the paginated window: selection still
        # caps at the next major instead of jumping schemes.
        stable = [{"tag_name": "v1.0.0"}, {"tag_name": "v3.5.0"}]
        rel = self.mod.select_latest_release(stable, "0.9.0")
        self.assertEqual(rel["tag_name"], "v1.0.0")

    def test_select_latest_release_unanchored_falls_back_to_global_max(self):
        stable = [{"tag_name": "v2.0.0"}, {"tag_name": "v1.9.0"}]
        rel = self.mod.select_latest_release(stable, "0.1.0-main")
        self.assertEqual(rel["tag_name"], "v2.0.0")

    def test_select_latest_release_unparsable_returns_newest(self):
        stable = [{"tag_name": "nightly"}, {"tag_name": "edge"}]
        rel = self.mod.select_latest_release(stable, "1.0.0")
        self.assertEqual(rel["tag_name"], "nightly")
        self.assertIsNone(self.mod.select_latest_release([], "1.0.0"))


if __name__ == "__main__":
    unittest.main()
