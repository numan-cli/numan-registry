"""Publication metadata cannot accidentally include arbitrary environment values."""

import unittest
from datetime import datetime

from write_site_metadata import build_metadata


class SiteMetadataTests(unittest.TestCase):
    def test_public_fields_only(self):
        metadata = build_metadata("production", "a" * 40)
        self.assertEqual(set(metadata), {"environment", "source_revision", "built_at"})
        self.assertEqual(metadata["source_revision"], "a" * 40)
        self.assertIsNotNone(datetime.fromisoformat(metadata["built_at"]).tzinfo)

    def test_reject_invalid_revision_and_environment(self):
        for revision in ("", "main", "a" * 39, "<script>" + "a" * 32):
            with self.assertRaises(ValueError):
                build_metadata("production", revision)
        with self.assertRaises(ValueError):
            build_metadata("unknown", "a" * 40)
