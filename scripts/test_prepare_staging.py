"""The staging merge must preserve production records and prevent substitutions."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("prepare_staging", Path(__file__).with_name("prepare-staging.py"))
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


def package(name, version):
    return {"id": {"owner": "owner", "name": name}, "type": "module", "repo": "https://example.com/repo", "versions": [{"version": version}]}


class PrepareStagingTests(unittest.TestCase):
    def test_committed_production_and_provisional_catalogs_respect_evidence_boundary(self):
        root = Path(__file__).resolve().parent.parent
        production = json.loads((root / "registry/index.json").read_text(encoding="utf-8"))
        provisional = json.loads((root / "registry/provisional.json").read_text(encoding="utf-8"))
        for package in production["packages"]:
            for version in package["versions"]:
                if package["type"] == "plugin" or version.get("activation", {}).get("kind") == "nu-module":
                    self.assertTrue(version.get("verified_with"), package["id"])
        for package in provisional["packages"]:
            for version in package["versions"]:
                self.assertEqual(version["evidence_tier"], "provisional")
                self.assertTrue(version["deferral_reason"])
        staging.merge_catalogs(production, provisional)
        production_workflow = (root / ".github/workflows/production.yml").read_text(encoding="utf-8")
        staging_workflow = (root / ".github/workflows/staging.yml").read_text(encoding="utf-8")
        self.assertNotIn("prepare-staging.py", production_workflow)
        self.assertIn("prepare-staging.py", staging_workflow)

    def test_merge_does_not_mutate_production_or_provisional(self):
        production = {"schema_version": 1, "packages": [package("first", "1.0.0")]}
        pending = {"schema_version": 1, "packages": [package("second", "1.0.0")]}
        before = copy.deepcopy((production, pending))
        merged = staging.merge_catalogs(production, pending)
        self.assertEqual(len(merged["packages"]), 2)
        self.assertEqual((production, pending), before)

    def test_new_versions_append_but_existing_versions_cannot_be_replaced(self):
        production = {"schema_version": 1, "packages": [package("first", "1.0.0")]}
        pending = {"schema_version": 1, "packages": [package("first", "2.0.0")]}
        merged = staging.merge_catalogs(production, pending)
        self.assertEqual([v["version"] for v in merged["packages"][0]["versions"]], ["1.0.0", "2.0.0"])
        pending["packages"][0]["versions"][0]["version"] = "1.0.0"
        with self.assertRaisesRegex(ValueError, "overwrite"):
            staging.merge_catalogs(production, pending)

    def test_reject_identity_substitution_and_duplicate_candidates(self):
        production = {"schema_version": 1, "packages": [package("first", "1.0.0")]}
        pending = {"schema_version": 1, "packages": [package("first", "2.0.0")]}
        pending["packages"][0]["repo"] = "https://different.example/repo"
        with self.assertRaisesRegex(ValueError, "identity"):
            staging.merge_catalogs(production, pending)
        pending = {"schema_version": 1, "packages": [package("second", "1.0.0"), package("second", "2.0.0")]}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            staging.merge_catalogs(production, pending)
