#!/usr/bin/env python3.12
"""Static release-workflow safety checks."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_USE = re.compile(r"^\s*(?:-\s+)?uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#.*)?$", re.MULTILINE)
ANY_USE = re.compile(r"^\s*(?:-\s+)?uses:\s+\S+", re.MULTILINE)


def job_block(text: str, name: str, next_name: str | None = None) -> str:
    """
    Extract a named job section from workflow text.
    
    Parameters:
    	text (str): Workflow YAML content.
    	name (str): Job name whose section should be extracted.
    	next_name (str | None): Optional name of the following job that marks the section boundary.
    
    Returns:
    	str: The text spanning the named job section.
    
    Raises:
    	ValueError: If the named job or specified following job is not found.
    """
    start = text.index(f"  {name}:\n")
    end = text.index(f"  {next_name}:\n", start) if next_name else len(text)
    return text[start:end]


class WorkflowSafetyTests(unittest.TestCase):
    def test_every_action_is_pinned_to_full_commit(self):
        """Verify that every GitHub Actions workflow action references a full commit SHA."""
        for name in ("repo-safety.yml", "staging.yml", "production.yml", "watch-indexed-updates.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertEqual(
                len(ANY_USE.findall(text)),
                len(SHA_USE.findall(text)),
                f"{name} contains an action not pinned to a 40-character commit",
            )

    def test_workflows_default_to_read_only(self):
        for name in ("repo-safety.yml", "staging.yml", "production.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")

    def test_production_secret_is_only_in_protected_publish_job(self):
        text = (WORKFLOWS / "production.yml").read_text(encoding="utf-8")
        validate = job_block(text, "validate", "sign-and-publish")
        publish = job_block(text, "sign-and-publish")
        self.assertNotIn("${{ secrets.", validate)
        self.assertNotIn("environment:", validate)
        self.assertIn("needs: validate", publish)
        self.assertIn("environment: production", publish)
        self.assertIn("contents: write", publish)
        self.assertIn("secrets.NUMAN_REGISTRY_PRIVATE_KEY", publish)
        self.assertNotIn("--allow-provisional-lifecycle", text)
        for command in (
            "scan_for_secrets.py",
            "preflight.py",
            "validate.py",
            "--skip-signature",
            "numan-parser-check/Cargo.toml",
            "lint-manifest-index.py",
        ):
            self.assertIn(command, validate)
        self.assertNotIn("--skip-signature", publish)

    def test_staging_write_permission_is_only_in_publish_job(self):
        """Verify that staging write permission is restricted to the publish job."""
        text = (WORKFLOWS / "staging.yml").read_text(encoding="utf-8")
        validate = job_block(text, "validate", "publish")
        publish = job_block(text, "publish")
        self.assertNotIn("contents: write", validate)
        self.assertIn("needs: validate", publish)
        self.assertIn("contents: write", publish)

    def test_signing_values_are_passed_as_data_not_shell_templates(self):
        production = (WORKFLOWS / "production.yml").read_text(encoding="utf-8")
        production_publish = job_block(production, "sign-and-publish")
        self.assertIn("PRODUCTION_KEY_ID: ${{ steps.key_id.outputs.key_id }}", production_publish)
        self.assertIn('--key-id "${PRODUCTION_KEY_ID}"', production_publish)
        self.assertNotIn('--key-id "${{ steps.key_id.outputs.key_id }}"', production_publish)
        self.assertIn("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", production_publish)

        staging = (WORKFLOWS / "staging.yml").read_text(encoding="utf-8")
        staging_validate = job_block(staging, "validate", "publish")
        self.assertIn('STAGING_PUB="${RUNNER_TEMP}/staging-key.pub.json"', staging_validate)
        self.assertIn("trap 'rm -f \"${STAGING_PUB}\"' EXIT", staging_validate)
        self.assertIn("--allow-provisional-lifecycle", staging_validate)
        self.assertIn("export STAGING_PRIVATE_KEY", staging_validate)
        self.assertNotIn("steps.sign.outputs", staging_validate)
        self.assertNotIn("GITHUB_OUTPUT", staging_validate)

    def test_lifecycle_tests_run_on_windows_and_ubuntu(self):
        text = (WORKFLOWS / "repo-safety.yml").read_text(encoding="utf-8")
        self.assertIn("os: [ubuntu-latest, windows-latest]", text)
        self.assertIn("python -m pip install cryptography jsonschema", text)
        self.assertRegex(
            text,
            r'(?:python -m )?coverage run\s+-m unittest discover -s scripts -p "test_\*\.py" -v',
        )

    def test_manifest_lint_uses_immutable_plugins_merge(self):
        sha = "eb435983cfd8bed568a3c275ba6518607e904e89"
        for name in ("repo-safety.yml", "production.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertIn(f"ref: {sha}", text)

    def test_production_materializes_candidate_before_validate_and_sign(self):
        text = (WORKFLOWS / "production.yml").read_text(encoding="utf-8")
        validate = job_block(text, "validate", "sign-and-publish")
        publish = job_block(text, "sign-and-publish")
        self.assertIn("materialize_candidate.py", validate)
        self.assertIn("materialize_candidate.py", publish)
        self.assertLess(validate.index("materialize_candidate.py"), validate.index("validate.py"))
        self.assertLess(
            validate.index('cp "${RUNNER_TEMP}/materialized-index.json"'),
            validate.index("validate.py"),
        )
        self.assertLess(publish.index("materialize_candidate.py"), publish.index("ci-sign.py"))
        self.assertLess(
            publish.index('cp "${RUNNER_TEMP}/materialized-index.json"'),
            publish.index("ci-sign.py"),
        )
        self.assertIn("branches: [main]", text)
        self.assertIn("- 'registry/index.json'", text)


if __name__ == "__main__":
    unittest.main()
