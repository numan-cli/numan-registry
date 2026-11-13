#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workflow_executor

ROOT = Path(workflow_executor.__file__).resolve().parent.parent


def context() -> dict:
    return {
        "inputs": {"package": "fennewald/nu_plugin_net"},
        "needs": {},
        "matrix": {},
        "env": {},
        "runner": {"os": "Linux"},
    }


class ExpressionTests(unittest.TestCase):
    def test_linux_and_windows_conditions(self):
        ctx = context()
        self.assertTrue(
            workflow_executor.eval_expression("runner.os == 'Linux'", ctx)
        )
        self.assertTrue(
            workflow_executor.eval_expression("runner.os != 'Windows'", ctx)
        )
        self.assertFalse(
            workflow_executor.eval_expression("runner.os == 'Windows'", ctx)
        )

    def test_always_combines_with_platform_checks(self):
        ctx = context()
        self.assertTrue(
            workflow_executor.eval_expression(
                "always() && runner.os != 'Windows'", ctx
            )
        )
        self.assertFalse(
            workflow_executor.eval_expression(
                "always() && runner.os == 'Windows'", ctx
            )
        )

    def test_condition_reports_always_steps(self):
        ctx = context()
        self.assertEqual(
            workflow_executor.step_condition({"if": "always()"}, ctx),
            (True, True),
        )
        self.assertEqual(
            workflow_executor.step_condition(
                {"if": "runner.os != 'Windows'"}, ctx
            ),
            (True, False),
        )
        self.assertEqual(
            workflow_executor.step_condition(
                {"if": "runner.os == 'Windows'"}, ctx
            ),
            (False, False),
        )

    def test_values_and_format_are_available_to_expressions(self):
        ctx = context()
        self.assertEqual(
            workflow_executor.eval_expression("inputs.package", ctx),
            "fennewald/nu_plugin_net",
        )
        self.assertEqual(
            workflow_executor.eval_expression(
                "format('v{0}', '1.2.3')", ctx
            ),
            "v1.2.3",
        )


class ActionTests(unittest.TestCase):
    def test_checkout_copies_the_locked_requirements_file(self):
        commands = workflow_executor.action_commands(
            "actions/checkout@example", {}, context()
        )
        self.assertTrue(
            any("/src/requirements" in command for command in commands)
        )

    def test_cross_repository_checkout_uses_the_explicit_registry_mount(self):
        commands = workflow_executor.action_commands(
            "actions/checkout@example",
            {
                "repository": "numan-cli/numan-registry",
                "ref": "a" * 40,
                "path": "registry-src",
            },
            context(),
        )
        joined = "\n".join(commands)
        self.assertIn("/registry/scripts", joined)
        self.assertIn("/registry/requirements", joined)
        self.assertIn("cd /work/registry-src", joined)
        self.assertNotIn("cross-repository checkout is not supported", joined)

    def test_checkout_rejects_paths_outside_the_workspace(self):
        with self.assertRaisesRegex(RuntimeError, "must stay under the workspace"):
            workflow_executor.action_commands(
                "actions/checkout@example",
                {"repository": "numan-cli/numan-registry", "path": "../escape"},
                context(),
            )

    def test_setup_python_accepts_matching_patch_version(self):
        commands = workflow_executor.action_commands(
            "actions/setup-python@example",
            {"python-version": "3.12"},
            context(),
        )
        joined = "\n".join(commands)
        self.assertIn("grep -Eq '^Python 3\\.12(\\.[0-9]+)?$'", joined)
        self.assertIn("python3 --version", joined)
        self.assertIn("python --version", joined)

    def test_upload_artifact_honors_warn_mode(self):
        commands = workflow_executor.action_commands(
            "actions/upload-artifact@example",
            {
                "name": "summary",
                "path": "proofs.json\nproofs.md",
                "if-no-files-found": "warn",
            },
            context(),
        )
        joined = "\n".join(commands)
        self.assertIn("warning: no files found", joined)
        self.assertNotIn("exit 1", joined)


class EmitTests(unittest.TestCase):
    def test_emit_job_uses_pinned_inputs_and_collects_proof(self):
        script, manifest, inputs, plan = workflow_executor.emit_job(
            ROOT, ROOT, "nu-plugin-net"
        )
        self.assertEqual(inputs["package"], "fennewald/nu_plugin_net")
        self.assertEqual(inputs["nu_version"], "0.103.0")
        self.assertEqual(len(plan["matrix_value"]["include"]), 1)
        self.assertIn(
            'export PACKAGE="fennewald/nu_plugin_net"', script
        )
        self.assertIn('export PROOF_NU_VERSION="0.103.0"', script)
        self.assertIn("--output artifacts/proof.json", script)
        self.assertIn("WORKFLOW_DERIVED_JOB_OK", script)
        self.assertEqual(manifest[0]["job"], "plan")
        self.assertTrue(any(entry["job"] == "collect" for entry in manifest))

    def test_emit_job_honors_workflow_working_directory(self):
        script, _, _, _ = workflow_executor.emit_job(ROOT, ROOT, "nu-plugin-net")
        self.assertIn("\ncd .\n", script)


class WrapperResolutionTests(unittest.TestCase):
    def test_pinned_caller_resolves_through_platform_gap_wrapper(self):
        caller, _ = workflow_executor.load_workflow(
            ROOT / ".github" / "workflows" / "linux-lifecycle-proof.yml"
        )
        resolved = workflow_executor._resolve_reusable_with(
            ROOT, caller["jobs"]["nu-plugin-net"]
        )
        self.assertEqual(resolved["package"], "fennewald/nu_plugin_net")
        self.assertEqual(resolved["package_version"], "1.9.0")
        self.assertEqual(resolved["nu_version"], "0.103.0")
        self.assertEqual(resolved["targets"], '["linux/x86_64"]')
        self.assertEqual(resolved["artifact_prefix"], "linux-net")
        self.assertEqual(
            resolved["artifact_summary_prefix"], "linux-net-proofs"
        )


if __name__ == "__main__":
    unittest.main()
