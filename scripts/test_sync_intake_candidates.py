#!/usr/bin/env python3
"""Unit checks for scripts/sync-intake-candidates.py (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "sync-intake-candidates.py"


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_intake_candidates", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SYNC = load_sync()



class SyncIntakeCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_artifact_provenance_classes(self):
        self.assertEqual(
            self.sync.artifact_provenance(
                "https://github.com/numan-cli/numan-registry/releases/download/mirror-x/x.zip"
            ),
            "mirror",
        )
        self.assertEqual(
            self.sync.artifact_provenance(
                "https://github.com/numan-cli/numan-registry/releases/download/archive-fj0r-ai.nu-0.1.0-2e71068/fj0r-ai.nu-0.1.0-2e71068.tar.gz"
            ),
            "mirror",
        )
        self.assertEqual(
            self.sync.artifact_provenance(
                "https://github.com/numan-cli/numan-plugins/releases/download/p-1.0.0/p.tar.gz"
            ),
            "ci-built",
        )
        self.assertEqual(
            self.sync.artifact_provenance(
                "https://github.com/acme/nu_plugin_x/releases/download/v1.0.0/x.tar.gz"
            ),
            "upstream",
        )
        self.assertEqual(self.sync.artifact_provenance(""), "other")

    def test_registry_packages_marks_ci_built(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "FMotalleb", "name": "nu_plugin_image"},
                    "versions": [
                        {
                            "version": "0.112.2",
                            "artifact": {
                                "kind": "binary",
                                "targets": {
                                    "x86_64-unknown-linux-gnu": {
                                        "url": (
                                            "https://github.com/numan-cli/"
                                            "numan-plugins/releases/download/"
                                            "nu_plugin_image-0.112.2/"
                                            "nu_plugin_image-0.112.2-x86_64-unknown-linux-gnu.tar.gz"
                                        ),
                                        "sha256": "abc",
                                    }
                                },
                            },
                        }
                    ],
                }
            ]
        }
        live = self.sync.registry_packages(index)
        info = live["FMotalleb/nu_plugin_image"]
        self.assertTrue(info["ci_built"])
        self.assertFalse(info["upstream_asset"])
        self.assertFalse(info["mirror"])
        self.assertFalse(info["mixed"])

    def test_registry_packages_preserves_mirror_when_mixed(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "nu_plugin_partial"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "artifact": {
                                "kind": "binary",
                                "targets": {
                                    "x86_64-pc-windows-msvc": {
                                        "url": (
                                            "https://github.com/numan-cli/"
                                            "numan-registry/releases/download/"
                                            "mirror-partial/win.zip"
                                        ),
                                    },
                                    "x86_64-unknown-linux-gnu": {
                                        "url": (
                                            "https://github.com/acme/plugin/"
                                            "releases/download/v1.0.0/linux.zip"
                                        ),
                                    },
                                },
                            },
                        }
                    ],
                }
            ]
        }
        live = self.sync.registry_packages(index)
        info = live["acme/nu_plugin_partial"]
        self.assertTrue(info["mixed"])
        self.assertTrue(info["mirror"])
        self.assertFalse(info["ci_built"])
        self.assertFalse(info["upstream_asset"])

    def test_package_status_uses_ci_built_label(self):
        entry = {
            "id": "FMotalleb/nu_plugin_image",
            "version": "0.112.2",
            "note": "ci-built via numan-plugins; wave1; Nu 0.112",
        }
        live = {
            "FMotalleb/nu_plugin_image": {
                "version": "0.112.2",
                "mirror": False,
                "ci_built": True,
                "upstream_asset": False,
                "mixed": False,
            }
        }
        status = self.sync.package_status(entry, live, {}, {})
        self.assertTrue(status.startswith("live (ci-built asset)"))
        self.assertIn("ci-built via numan-plugins; wave1; Nu 0.112", status)
        self.assertNotIn("upstream asset", status)

    def test_package_status_prefers_mixed_over_mirror(self):
        entry = {"id": "acme/nu_plugin_partial", "version": "1.0.0"}
        live = {
            "acme/nu_plugin_partial": {
                "version": "1.0.0",
                "mirror": True,
                "ci_built": False,
                "upstream_asset": False,
                "mixed": True,
            }
        }
        status = self.sync.package_status(entry, live, {}, {})
        self.assertTrue(status.startswith("live (mixed provenance)"))
        self.assertNotIn("registry mirror", status)

    def test_live_status_none_when_not_in_index(self):
        entry = {"id": "acme/nu_plugin_x", "version": "1.0.0"}
        self.assertIsNone(self.sync._live_status(entry, {}))

    def test_live_status_all_provenance_flavors(self):
        live = {
            "acme/a": {"version": "1.0.0", "mirror": False, "ci_built": False, "upstream_asset": True, "mixed": False},
            "acme/b": {"version": "2.0.0", "mirror": True, "ci_built": False, "upstream_asset": False, "mixed": False},
            "acme/c": {"version": "3.0.0", "mirror": False, "ci_built": True, "upstream_asset": False, "mixed": False},
            "acme/d": {"version": "4.0.0", "mirror": True, "ci_built": False, "upstream_asset": False, "mixed": True},
            "acme/e": {"version": "5.0.0", "mirror": False, "ci_built": False, "upstream_asset": False, "mixed": False},
        }
        expected = {
            "acme/a": "live (upstream asset)",
            "acme/b": "live (registry mirror)",
            "acme/c": "live (ci-built asset)",
            "acme/d": "live (mixed provenance)",
            "acme/e": "live",
        }
        for pid, want in expected.items():
            self.assertEqual(
                self.sync._live_status({"id": pid, "version": "0.0.0"}, live),
                [want, "index@" + live[pid]["version"]],
            )

    def test_live_status_skips_index_note_when_versions_match(self):
        live = {
            "acme/x": {"version": "1.0.0", "mirror": False, "ci_built": False, "upstream_asset": True, "mixed": False}
        }
        self.assertEqual(
            self.sync._live_status({"id": "acme/x", "version": "1.0.0"}, live),
            ["live (upstream asset)"],
        )

    def test_pr_status_none_without_pr_number(self):
        self.assertIsNone(self.sync._pr_status({"id": "acme/x"}, {}))

    def test_pr_status_all_states(self):
        pr_map = {1: "merged", 2: "open", 3: "closed", 4: None}
        base = "https://github.com/numan-cli/numan-registry/pull"
        self.assertEqual(
            self.sync._pr_status({"id": "acme/x", "pr": 1}, pr_map),
            [f"merged in [#1]({base}/1) — publish pending?"],
        )
        self.assertEqual(
            self.sync._pr_status({"id": "acme/x", "pr": 2}, pr_map),
            [f"PR [#2]({base}/2) open"],
        )
        self.assertEqual(
            self.sync._pr_status({"id": "acme/x", "pr": 3}, pr_map),
            ["PR #3 closed (not merged)"],
        )
        self.assertEqual(
            self.sync._pr_status({"id": "acme/x", "pr": 4}, pr_map),
            [f"pending [#4]({base}/4)"],
        )

    def test_candidate_status_spec_written_vs_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_file = Path(tmp) / "specs" / "acme-x-1.0.0.json"
            spec_file.parent.mkdir(parents=True)
            spec_file.write_text("{}", encoding="utf-8")
            with patch.object(self.sync, "REPO_ROOT", Path(tmp)):
                self.assertEqual(
                    self.sync._candidate_status({"id": "acme/x", "spec": "specs/acme-x-1.0.0.json"}),
                    ["spec written, not in index"],
                )
                self.assertEqual(self.sync._candidate_status({"id": "acme/x"}), ["candidate"])

    def test_package_status_appends_outreach_and_note_tail(self):
        entry = {"id": "acme/pr1", "pr": 1, "outreach": {"x": 1}, "note": "wave2"}
        status = self.sync.package_status(
            entry, {}, {1: "open"}, {"acme/pr1": {"summary": "responded — see acme/foo#3"}}
        )
        self.assertIn("PR [#1]", status)
        self.assertIn("outreach: responded — see acme/foo#3", status)
        self.assertTrue(status.endswith("— wave2"))

    def test_pr_status_not_used_when_entry_is_live(self):
        entry = {"id": "acme/x", "version": "1.0.0", "pr": 99}
        live = {
            "acme/x": {"version": "1.0.0", "mirror": False, "ci_built": False, "upstream_asset": True, "mixed": False}
        }
        status = self.sync.package_status(entry, live, {99: "open"}, {})
        self.assertTrue(status.startswith("live (upstream asset)"))
        self.assertNotIn("PR [#99]", status)

    def test_registry_summary_sorts_and_marks_mixed_versions(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "vyadh", "name": "nutest"},
                    "versions": [
                        {"version": "1.1.0", "artifact": {"url": "https://github.com/numan-cli/numan-registry/releases/download/mirror-x/a.zip"}},
                        {"version": "1.2.0", "artifact": {"url": "https://github.com/acme/nutest/releases/download/v1.2.0/a.zip"}},
                    ],
                },
                {
                    "id": {"owner": "abusch", "name": "nu_plugin_semver"},
                    "versions": [{"version": "0.11.17", "artifact": {"url": "https://github.com/acme/semver/releases/download/v/a.zip"}}],
                },
            ]
        }
        rendered = self.sync.render_intake_doc({}, {}, index, {})
        self.assertIn("`abusch/nu_plugin_semver@0.11.17` (upstream)", rendered)
        self.assertIn("`vyadh/nutest` (1.1.0, 1.2.0; mixed)", rendered)

    def test_registry_summary_marks_mixed_binary_targets(self):
        index = {
            "packages": [
                {
                    "id": {"owner": "acme", "name": "nu_plugin_mixed"},
                    "versions": [
                        {
                            "version": "1.0.0",
                            "artifact": {
                                "kind": "binary",
                                "targets": {
                                    "x86_64-pc-windows-msvc": {
                                        "url": "https://github.com/numan-cli/numan-plugins/releases/download/x/win.zip"
                                    },
                                    "x86_64-unknown-linux-gnu": {
                                        "url": "https://github.com/acme/plugin/releases/download/v1.0.0/linux.zip"
                                    },
                                },
                            },
                        }
                    ],
                },
                {
                    "id": {"owner": "acme", "name": "nu_plugin_empty_binary"},
                    "versions": [
                        {
                            "version": "0.1.0",
                            "artifact": {"kind": "binary", "targets": {}},
                        }
                    ],
                },
            ]
        }
        rendered = self.sync.render_intake_doc({}, {}, index, {})
        self.assertIn("`acme/nu_plugin_mixed@1.0.0` (mixed)", rendered)
        self.assertIn("`acme/nu_plugin_empty_binary@0.1.0` (other)", rendered)

    def test_render_intake_doc_full_sections(self):
        state = {
            "ready": [
                {
                    "id": "acme/ready1",
                    "repo": "https://github.com/acme/ready1",
                    "type": "plugin",
                    "version": "1.0.0",
                    "platforms": "linux",
                }
            ],
            "mirror": [
                {
                    "id": "acme/mirror1",
                    "repo": "https://github.com/acme/mirror1",
                    "type": "script",
                    "source": "tag v1",
                }
            ],
            "blocked": [
                {"id": "acme/blocked1", "blocker": "no releases"},
                {"id": "some free text blocker", "blocker": "n/a"},
            ],
            "changelog": [
                {"date": "2024-01-01", "change": "added acme/ready1"},
            ],
        }
        rendered = self.sync.render_intake_doc(state, {}, {"packages": []}, {})
        self.assertIn(
            "| [`acme/ready1`](https://github.com/acme/ready1) | plugin | v1.0.0 "
            "| linux | candidate |",
            rendered,
        )
        self.assertIn("[`acme/mirror1`](https://github.com/acme/mirror1)", rendered)
        self.assertIn("[`acme/blocked1`](https://github.com/acme/blocked1)", rendered)
        self.assertIn("some free text blocker | n/a", rendered)
        self.assertIn("2024-01-01 | added acme/ready1", rendered)

    def test_undated_historical_changelog_does_not_block_regeneration(self):
        state = {"changelog": [{"change": "Historical decision with no recorded date"}]}
        rendered = self.sync.render_intake_doc(state, {}, {"packages": []}, {})
        self.assertIn("| Not recorded | Historical decision with no recorded date |", rendered)

    def test_render_intake_doc_empty_registry_line(self):
        rendered = self.sync.render_intake_doc({}, {}, {"packages": []}, {})
        self.assertIn(
            "**Currently in committed index** (source tree; unsigned until "
            "production publish signs and deploys): (none).",
            rendered,
        )


class PrStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_maps_gh_response_states(self):
        with patch.object(self.sync, "gh_json", return_value={"state": "MERGED"}):
            self.assertEqual(self.sync.pr_state(42), "merged")
        with patch.object(self.sync, "gh_json", return_value={"state": "OPEN"}):
            self.assertEqual(self.sync.pr_state(42), "open")
        with patch.object(self.sync, "gh_json", return_value={"state": "CLOSED"}):
            self.assertEqual(self.sync.pr_state(42), "closed")
        with patch.object(self.sync, "gh_json", return_value=None):
            self.assertIsNone(self.sync.pr_state(42))

    def test_none_without_number(self):
        self.assertIsNone(self.sync.pr_state(None))


class OutreachStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_no_upstream_repo(self):
        self.assertEqual(self.sync.outreach_status({})["summary"], "not started")

    def test_blocked(self):
        result = self.sync.outreach_status(
            {"upstream_repo": "acme/x", "blocked": "no maintainer response"}
        )
        self.assertEqual(result["summary"], "blocked (no maintainer response)")

    def test_pending_when_no_issue_found(self):
        with patch.object(self.sync, "gh_json", return_value=None):
            result = self.sync.outreach_status({"upstream_repo": "acme/x"})
        self.assertEqual(result["summary"], "outreach pending")

    def test_responded(self):
        detail = {
            "number": 9,
            "url": "https://github.com/acme/x/issues/9",
            "state": "OPEN",
            "createdAt": "2024-01-01T00:00:00Z",
        }
        comments = [{"user": "someone_else", "created_at": "2024-02-01T00:00:00Z"}]

        def fake_gh_json(args):
            if args[:2] == ["issue", "view"]:
                return detail
            if args[0] == "api" and "comments" in args[1]:
                return comments
            return None

        with patch.object(self.sync, "gh_json", side_effect=fake_gh_json), patch.object(
            self.sync, "gh_text", return_value="me"
        ):
            result = self.sync.outreach_status(
                {"upstream_repo": "acme/x", "issue_url": "https://github.com/acme/x/issues/9"}
            )
        self.assertTrue(result["response"].startswith("yes"))
        self.assertIn("responded", result["summary"])

    def test_issue_closed(self):
        detail = {
            "number": 9,
            "url": "https://github.com/acme/x/issues/9",
            "state": "CLOSED",
            "createdAt": "2024-01-01T00:00:00Z",
        }

        def fake_gh_json(args):
            if args[:2] == ["issue", "view"]:
                return detail
            if args[0] == "api" and "comments" in args[1]:
                return []
            return None

        with patch.object(self.sync, "gh_json", side_effect=fake_gh_json), patch.object(
            self.sync, "gh_text", return_value="me"
        ):
            result = self.sync.outreach_status(
                {"upstream_repo": "acme/x", "issue_url": "https://github.com/acme/x/issues/9"}
            )
        self.assertIn("issue closed", result["summary"])


class UpdateOutreachTrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_missing_doc_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "outreach.md"
            with patch.object(self.sync, "OUTREACH_DOC", missing):
                self.assertFalse(self.sync.update_outreach_tracker({}, {}, {}))

    def test_missing_marker_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "outreach.md"
            doc.write_text("# No tracker section here\n", encoding="utf-8")
            with patch.object(self.sync, "OUTREACH_DOC", doc):
                self.assertFalse(self.sync.update_outreach_tracker({}, {}, {}))

    def test_rewrites_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "outreach.md"
            doc.write_text(
                "# Upstream release outreach\n\n"
                "## Outreach tracker\n\n"
                "old content here\n\n"
                "---\n\n"
                "## Notes\n",
                encoding="utf-8",
            )
            state = {
                "mirror": [
                    {"id": "acme/x", "owner": "acme", "name": "x", "outreach": {}},
                    {
                        "id": "nushell/foo",
                        "owner": "nushell",
                        "name": "foo",
                        "outreach": {},
                    },
                ]
            }
            live = {"acme/x": {"mirror": False}}
            outreach_cache = {
                "acme/x": {
                    "issue": "[#1](url)",
                    "opened": "2024-01-01",
                    "response": "yes (2024-01-02)",
                    "summary": "responded",
                },
            }
            with patch.object(self.sync, "OUTREACH_DOC", doc):
                changed = self.sync.update_outreach_tracker(state, live, outreach_cache)
            self.assertTrue(changed)
            text = doc.read_text(encoding="utf-8")
        self.assertIn("acme/x", text)
        self.assertIn("nushell/nu_scripts (foo)", text)
        self.assertIn("[#1](url)", text)
        self.assertNotIn("old content here", text)

    def test_returns_false_when_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "outreach.md"
            doc.write_text(
                "# Doc\n\n## Outreach tracker\n\nplaceholder\n\n---\n\nfooter\n",
                encoding="utf-8",
            )
            with patch.object(self.sync, "OUTREACH_DOC", doc):
                first = self.sync.update_outreach_tracker({}, {}, {})
                self.assertTrue(first)
                second = self.sync.update_outreach_tracker({}, {}, {})
            self.assertFalse(second)


class SyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_returns_false_when_state_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "intake-state.json"
            with patch.object(self.sync, "STATE_PATH", state_path):
                self.assertFalse(self.sync.sync())

    def test_writes_new_doc_and_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "intake-state.json"
            out_path = root / "intake-candidates.md"
            index_path = root / "index.json"
            outreach_doc = root / "outreach.md"

            state = {"ready": [], "mirror": [], "blocked": [], "changelog": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(self.sync, "STATE_PATH", state_path), patch.object(
                self.sync, "OUT_PATH", out_path
            ), patch.object(self.sync, "INDEX_PATH", index_path), patch.object(
                self.sync, "OUTREACH_DOC", outreach_doc
            ):
                changed = self.sync.sync()

            self.assertTrue(changed)
            self.assertTrue(out_path.exists())
            self.assertIn("Registry intake candidates", out_path.read_text(encoding="utf-8"))

    def test_returns_false_when_nothing_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "intake-state.json"
            out_path = root / "intake-candidates.md"
            index_path = root / "index.json"
            outreach_doc = root / "outreach.md"

            state = {"ready": [], "mirror": [], "blocked": [], "changelog": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(self.sync, "STATE_PATH", state_path), patch.object(
                self.sync, "OUT_PATH", out_path
            ), patch.object(self.sync, "INDEX_PATH", index_path), patch.object(
                self.sync, "OUTREACH_DOC", outreach_doc
            ):
                self.sync.sync()
                changed_again = self.sync.sync()

            self.assertFalse(changed_again)

    def test_persists_discovered_issue_url_and_marks_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "intake-state.json"
            out_path = root / "intake-candidates.md"
            index_path = root / "index.json"
            outreach_doc = root / "outreach.md"

            state = {
                "ready": [],
                "mirror": [
                    {
                        "id": "acme/x",
                        "owner": "acme",
                        "name": "x",
                        "repo": "https://github.com/acme/x",
                        "type": "plugin",
                        "source": "tag v1",
                        "outreach": {"upstream_repo": "acme/x"},
                    }
                ],
                "blocked": [],
                "changelog": [],
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            found_issue = [
                {
                    "number": 5,
                    "title": "t",
                    "state": "OPEN",
                    "url": "https://github.com/acme/x/issues/5",
                    "comments": 0,
                    "updatedAt": "2024-01-01",
                }
            ]
            detail = {
                "number": 5,
                "title": "t",
                "state": "OPEN",
                "url": "https://github.com/acme/x/issues/5",
                "comments": 0,
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }

            def fake_gh_json(args):
                if args[:2] == ["issue", "list"]:
                    return found_issue
                if args[:2] == ["issue", "view"]:
                    return detail
                if args[0] == "api" and "comments" in args[1]:
                    return []
                return None

            with patch.object(self.sync, "STATE_PATH", state_path), patch.object(
                self.sync, "OUT_PATH", out_path
            ), patch.object(self.sync, "INDEX_PATH", index_path), patch.object(
                self.sync, "OUTREACH_DOC", outreach_doc
            ), patch.object(
                self.sync, "gh_json", side_effect=fake_gh_json
            ), patch.object(
                self.sync, "gh_text", return_value="me"
            ):
                changed = self.sync.sync()

            self.assertTrue(changed)
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved_state["mirror"][0]["outreach"]["issue_url"],
                "https://github.com/acme/x/issues/5",
            )


class FilesChangedSinceLastSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_true_when_no_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".mrge" / "sync-checksums.json"
            watched = Path(tmp) / "a.json"
            watched.write_text("{}", encoding="utf-8")
            with patch.object(self.sync, "CHECKSUM_CACHE", cache):
                self.assertTrue(self.sync.files_changed_since_last_sync([watched]))

    def test_false_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".mrge" / "sync-checksums.json"
            watched = Path(tmp) / "a.json"
            watched.write_text("{}", encoding="utf-8")
            with patch.object(self.sync, "CHECKSUM_CACHE", cache), patch.object(
                self.sync, "REPO_ROOT", Path(tmp)
            ):
                self.sync.save_checksums([watched])
                self.assertFalse(self.sync.files_changed_since_last_sync([watched]))

    def test_true_after_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".mrge" / "sync-checksums.json"
            watched = Path(tmp) / "a.json"
            watched.write_text("{}", encoding="utf-8")
            with patch.object(self.sync, "CHECKSUM_CACHE", cache), patch.object(
                self.sync, "REPO_ROOT", Path(tmp)
            ):
                self.sync.save_checksums([watched])
                watched.write_text('{"changed": true}', encoding="utf-8")
                self.assertTrue(self.sync.files_changed_since_last_sync([watched]))

    def test_true_on_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".mrge" / "sync-checksums.json"
            cache.parent.mkdir(parents=True)
            cache.write_text("not json", encoding="utf-8")
            watched = Path(tmp) / "a.json"
            watched.write_text("{}", encoding="utf-8")
            with patch.object(self.sync, "CHECKSUM_CACHE", cache):
                self.assertTrue(self.sync.files_changed_since_last_sync([watched]))

    def test_handles_missing_watched_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".mrge" / "sync-checksums.json"
            watched = Path(tmp) / "missing.json"
            with patch.object(self.sync, "CHECKSUM_CACHE", cache), patch.object(
                self.sync, "REPO_ROOT", Path(tmp)
            ):
                self.sync.save_checksums([watched])
                self.assertFalse(self.sync.files_changed_since_last_sync([watched]))


class DeterministicRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = SYNC

    def test_render_identical_across_mocked_dates(self):
        state = {"ready": [], "mirror": [], "blocked": [], "changelog": []}
        renders = []
        for year in (2020, 2030):
            with patch.object(self.sync, "datetime", create=True) as mock_dt:
                mock_dt.now.return_value = datetime(year, 1, 1, tzinfo=timezone.utc)
                renders.append(
                    self.sync.render_intake_doc(state, {}, {"packages": []}, {})
                )
        self.assertEqual(renders[0], renders[1])
        self.assertNotRegex(renders[0], r"Auto-synced \d{4}-\d{2}-\d{2}")
        self.assertIn("_Auto-synced from `docs/intake-state.json`", renders[0])

    def test_sync_bytes_identical_across_utc_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "intake-state.json"
            out_path = root / "intake-candidates.md"
            index_path = root / "index.json"
            outreach_doc = root / "outreach.md"
            state = {"ready": [], "mirror": [], "blocked": [], "changelog": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            first = None
            for year in (2020, 2030):
                with patch.object(self.sync, "STATE_PATH", state_path), patch.object(
                    self.sync, "OUT_PATH", out_path
                ), patch.object(self.sync, "INDEX_PATH", index_path), patch.object(
                    self.sync, "OUTREACH_DOC", outreach_doc
                ), patch.object(self.sync, "datetime", create=True) as mock_dt:
                    mock_dt.now.return_value = datetime(year, 6, 15, tzinfo=timezone.utc)
                    changed = self.sync.sync()
                snapshot = out_path.read_bytes()
                if first is None:
                    first = snapshot
                else:
                    self.assertFalse(changed)
                    self.assertEqual(first, snapshot)


if __name__ == "__main__":
    unittest.main()
