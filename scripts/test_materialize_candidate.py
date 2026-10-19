import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import materialize_candidate as mc


def pkg(owner, name, versions):
    return {
        "id": {"owner": owner, "name": name},
        "type": "plugin",
        "versions": versions,
    }


def ver(version, **kw):
    v = {"version": version, "nu_version": "*"}
    v.update(kw)
    return v


class MaterializeCandidateTests(unittest.TestCase):
    def setUp(self):
        self.index = {
            "schema_version": 1,
            "updated_at": "2026-10-19T00:00:00Z",
            "packages": [
                pkg("a", "keep", [ver("1.0.0")]),
                pkg("b", "prov", [
                    ver("1.0.0"),
                    ver("2.0.0", evidence_tier="provisional", deferral_reason="x"),
                ]),
                pkg("c", "allprov", [
                    ver("1.0.0", evidence_tier="provisional", deferral_reason="y"),
                ]),
                pkg("d", "drop", [ver("1.0.0")]),
            ],
        }

    def test_provisional_versions_dropped(self):
        cand, rem = mc.materialize_candidate(self.index)
        kept = {mc.package_label(p): p for p in cand["packages"]}
        self.assertEqual([v["version"] for v in kept["b/prov"]["versions"]], ["1.0.0"])
        self.assertIn(
            {"package": "b/prov", "version": "2.0.0", "reason": "provisional"}, rem
        )

    def test_package_with_no_versions_left_removed(self):
        cand, rem = mc.materialize_candidate(self.index)
        labels = [mc.package_label(p) for p in cand["packages"]]
        self.assertNotIn("c/allprov", labels)
        self.assertIn(
            {"package": "c/allprov", "version": "1.0.0", "reason": "provisional"}, rem
        )
        self.assertIn(
            {"package": "c/allprov", "version": "*", "reason": "no_versions_left"}, rem
        )

    def test_explicit_exclude_removes_package(self):
        cand, rem = mc.materialize_candidate(self.index, {"d/drop"})
        labels = [mc.package_label(p) for p in cand["packages"]]
        self.assertNotIn("d/drop", labels)
        self.assertIn({"package": "d/drop", "version": "*", "reason": "excluded"}, rem)

    def test_source_not_mutated(self):
        before = json.dumps(self.index, sort_keys=True)
        mc.materialize_candidate(self.index, {"d/drop"})
        self.assertEqual(json.dumps(self.index, sort_keys=True), before)

    def test_main_writes_canonical_bytes_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "index.json"
            src.write_text(json.dumps(self.index), encoding="utf-8")
            out = Path(td) / "cand" / "index.json"
            rep = Path(td) / "cand" / "report.json"
            rc = mc.main([
                "--index", str(src),
                "--exclude", "d/drop",
                "--out", str(out),
                "--report", str(rep),
            ])
            self.assertEqual(rc, 0)
            canonical = out.read_bytes()
            self.assertEqual(canonical, mc.canonical_json(
                json.loads(canonical)).encode("utf-8"))
            report = json.loads(rep.read_text(encoding="utf-8"))
            self.assertEqual(report["candidate_package_count"], 2)
            self.assertEqual(report["source_package_count"], 4)
            self.assertEqual(report["explicit_excludes"], ["d/drop"])
            self.assertEqual(len(report["exclusions"]), 4)
            import hashlib
            self.assertEqual(
                report["canonical_index_sha256"],
                hashlib.sha256(canonical).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
