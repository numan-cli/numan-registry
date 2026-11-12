#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_workflows

VALID = """\
name: ok
on:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""

MALFORMED = "name: bad\non: [push\n"

DUPLICATE_KEY = """\
name: dup
on: push
on: pull_request
"""


def init_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)


def add_workflow(root: Path, name: str, text: str, tracked: bool = True) -> Path:
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if tracked:
        subprocess.run(
            ["git", "-C", str(root), "add", ".github/workflows/" + name],
            check=True,
        )
    return path


class CheckWorkflowsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        init_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_workflow_passes(self):
        add_workflow(self.root, "ci.yml", VALID)
        self.assertEqual(check_workflows.validate_workflows(self.root), [])

    def test_malformed_yaml_fails(self):
        add_workflow(self.root, "ci.yml", MALFORMED)
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("ci.yml", errors[0])

    def test_duplicate_mapping_key_fails(self):
        add_workflow(self.root, "ci.yml", DUPLICATE_KEY)
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate", errors[0].lower())
        self.assertIn("ci.yml", errors[0])

    def test_on_key_stays_literal(self):
        path = add_workflow(self.root, "ci.yml", VALID)
        doc = check_workflows.load_workflow(path.read_text(encoding="utf-8"))
        self.assertIn("on", doc)
        self.assertNotIn(True, doc)

    def test_both_extensions_checked(self):
        add_workflow(self.root, "a.yml", VALID)
        add_workflow(self.root, "b.yaml", MALFORMED)
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("b.yaml", errors[0])

    def test_untracked_malformed_workflow_ignored(self):
        add_workflow(self.root, "ci.yml", VALID)
        add_workflow(self.root, "draft.yml", MALFORMED, tracked=False)
        self.assertEqual(check_workflows.validate_workflows(self.root), [])

    def test_no_tracked_workflows_fails(self):
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("no tracked workflow", errors[0].lower())

    def test_unhashable_key_and_other_errors_collected(self):
        add_workflow(self.root, "complex.yml", "name: x\n? [a, b]\n: value\n")
        add_workflow(self.root, "bad.yml", MALFORMED)
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 2)
        joined = "\n".join(errors)
        self.assertIn("complex.yml", joined)
        self.assertIn("bad.yml", joined)

    def test_load_workflow_rejects_undefined_alias(self):
        with self.assertRaises(check_workflows.yaml.YAMLError):
            check_workflows.load_workflow("key: *missing")

    def test_load_workflow_rejects_recursive_alias(self):
        with self.assertRaises(check_workflows.yaml.YAMLError):
            check_workflows.load_workflow("key: &self {child: *self}")

    def test_load_workflow_accepts_valid_alias(self):
        doc = check_workflows.load_workflow("a: &x 1\nb: *x\n")
        self.assertEqual(doc["b"], 1)

    def test_resolver_equivalent_duplicate_keys_fail(self):
        with self.assertRaises(check_workflows.yaml.YAMLError):
            check_workflows.load_workflow("1: a\n01: b\n")

    def test_boolean_forms_still_resolve(self):
        doc = check_workflows.load_workflow("a: true\nb: on\nc: yes\n")
        self.assertIs(doc["a"], True)
        self.assertEqual(doc["b"], "on")
        self.assertEqual(doc["c"], "yes")

    def test_main_enumerates_once_and_uses_passed_files(self):
        root = Path(check_workflows.__file__).resolve().parent.parent
        fake_files = [root / ".github" / "workflows" / "only.yml"]
        with patch.object(
            check_workflows, "workflow_files", return_value=fake_files
        ) as wf, patch.object(
            check_workflows, "validate_workflows", return_value=[]
        ) as vw, patch("builtins.print") as pr:
            rc = check_workflows.main([])
        self.assertEqual(rc, 0)
        wf.assert_called_once_with(root, include_untracked=False)
        vw.assert_called_once_with(root, files=fake_files)
        pr.assert_called_once_with("validated 1 workflow files")

    def test_include_untracked_validates_untracked_files(self):
        add_workflow(self.root, "ci.yml", VALID)
        add_workflow(self.root, "draft.yml", MALFORMED, tracked=False)
        errors = check_workflows.validate_workflows(
            self.root, include_untracked=True
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("draft.yml", errors[0])

    def test_main_can_include_untracked_workflows(self):
        root = Path(check_workflows.__file__).resolve().parent.parent
        fake_files = [root / ".github" / "workflows" / "only.yml"]
        with patch.object(
            check_workflows, "workflow_files", return_value=fake_files
        ) as wf, patch.object(
            check_workflows, "validate_workflows", return_value=[]
        ) as vw, patch("builtins.print"):
            rc = check_workflows.main(["--include-untracked"])
        self.assertEqual(rc, 0)
        wf.assert_called_once_with(root, include_untracked=True)
        vw.assert_called_once_with(root, files=fake_files)

    def test_invalid_non_first_workflow_still_found(self):
        add_workflow(self.root, "a.yml", VALID)
        add_workflow(self.root, "b.yml", VALID)
        add_workflow(self.root, "c.yml", MALFORMED)
        errors = check_workflows.validate_workflows(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("c.yml", errors[0])


class PlatformCoverageAuditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(check_workflows.__file__).resolve().parent.parent
        self.path = (
            self.root
            / ".github"
            / "workflows"
            / "platform-coverage-audit.yml"
        )

    def test_workflow_parses(self):
        self.assertEqual(
            check_workflows.validate_workflows(self.root, files=[self.path]), []
        )

    def test_workflow_is_index_scoped_and_read_only(self):
        doc = check_workflows.load_workflow(self.path.read_text(encoding="utf-8"))
        self.assertIn("registry/index.json", doc["on"]["pull_request"]["paths"])
        self.assertIn("registry/index.json", doc["on"]["push"]["paths"])
        self.assertTrue((self.root / "registry/index.json").is_file())
        self.assertEqual(doc["permissions"], {"contents": "read"})
        self.assertEqual(doc["on"]["workflow_dispatch"]["inputs"]["base_ref"]["type"], "string")

    def test_workflow_checks_out_shallow_and_resolves_an_explicit_base(self):
        doc = check_workflows.load_workflow(self.path.read_text(encoding="utf-8"))
        checkout = doc["jobs"]["audit"]["steps"][0]
        self.assertEqual(checkout["with"]["fetch-depth"], 1)
        self.assertEqual(
            doc["jobs"]["audit"]["steps"][2]["run"],
            "python scripts/resolve_coverage_base.py",
        )

    def test_workflow_runs_the_audit_and_publishes_reports(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("scripts/audit_platform_coverage.py", text)
        self.assertIn("scripts/resolve_coverage_base.py", text)
        self.assertIn("--base-index", text)
        self.assertIn("--base-missing", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("actions/upload-artifact@", text)


class PlatformGapWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(check_workflows.__file__).resolve().parent.parent
        self.path = (
            self.root
            / ".github"
            / "workflows"
            / "platform-gap-lifecycle-proof.yml"
        )

    def test_platform_gap_workflow_parses(self):
        self.assertEqual(
            check_workflows.validate_workflows(self.root, files=[self.path]), []
        )

    def test_platform_gap_workflow_is_reusable_and_forwards_contract(self):
        doc = check_workflows.load_workflow(
            self.path.read_text(encoding="utf-8")
        )
        call = doc["on"]["workflow_call"]
        self.assertEqual(
            set(call["inputs"]),
            {
                "package",
                "package_version",
                "nu_version",
                "targets",
                "activation_kind",
                "commands",
                "numan_version",
                "numan_repo",
                "registry_repository",
                "registry_ref",
                "registry_checkout",
                "artifact_prefix",
                "artifact_summary_prefix",
            },
        )
        for required in ("package", "package_version", "nu_version", "targets"):
            self.assertTrue(call["inputs"][required]["required"], required)
        self.assertEqual(
            call["outputs"]["proofs"]["value"],
            "${{ jobs.prove.outputs.proofs }}",
        )

        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        engine_inputs = set(engine["on"]["workflow_call"]["inputs"])
        self.assertEqual(set(call["inputs"]), engine_inputs)

        prove = doc["jobs"]["prove"]
        self.assertEqual(
            prove["uses"],
            "./.github/workflows/lifecycle-proof.yml",
        )
        self.assertNotIn("@", prove["uses"])
        self.assertTrue((self.root / prove["uses"]).is_file())
        self.assertEqual(set(prove["with"]), engine_inputs)
        for name in call["inputs"]:
            self.assertEqual(prove["with"][name], f"${{{{ inputs.{name} }}}}")

        dispatch = doc["on"]["workflow_dispatch"]
        self.assertEqual(
            set(dispatch["inputs"]), set(call["inputs"])
        )
        self.assertTrue(dispatch["inputs"]["targets"]["required"])
        self.assertEqual(doc["permissions"], {"contents": "read"})
        self.assertEqual(
            dispatch["inputs"]["targets"]["default"],
            '["linux/x86_64","linux/aarch64","macos/x86_64","macos/aarch64","windows/x86_64"]',
        )

    def test_pinned_linux_caller_routes_through_platform_gap_wrapper(self):
        wrapper = check_workflows.load_workflow(
            self.path.read_text(encoding="utf-8")
        )
        wrapper_inputs = set(wrapper["on"]["workflow_call"]["inputs"])
        caller = check_workflows.load_workflow(
            (
                self.root
                / ".github"
                / "workflows"
                / "linux-lifecycle-proof.yml"
            ).read_text(encoding="utf-8")
        )
        for job_name in ("nu-plugin-net", "nu-plugin-dns"):
            with self.subTest(job=job_name):
                job = caller["jobs"][job_name]
                self.assertEqual(
                    job["uses"],
                    "./.github/workflows/platform-gap-lifecycle-proof.yml",
                )
                self.assertTrue((self.root / job["uses"]).is_file())
                self.assertNotEqual(
                    job["uses"], "./.github/workflows/lifecycle-proof.yml"
                )
                self.assertTrue(set(job["with"]) <= wrapper_inputs)
                for required in (
                    "package",
                    "package_version",
                    "nu_version",
                    "targets",
                ):
                    self.assertIn(required, job["with"])
        self.assertIn(
            ".github/workflows/platform-gap-lifecycle-proof.yml",
            caller["on"]["pull_request"]["paths"],
        )

    def test_engine_supports_an_explicit_external_registry_checkout(self):
        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        for trigger in ("workflow_call", "workflow_dispatch"):
            with self.subTest(trigger=trigger):
                inputs = engine["on"][trigger]["inputs"]
                for name in (
                    "registry_repository",
                    "registry_ref",
                    "registry_checkout",
                ):
                    self.assertIn(name, inputs)
                    self.assertFalse(inputs[name].get("required", False))
                    self.assertEqual(inputs[name]["type"], "string")
                self.assertEqual(inputs["registry_checkout"]["default"], ".")

        env = engine["env"]
        self.assertIn("inputs.registry_checkout", env["PROOF_REGISTRY_CHECKOUT"])
        self.assertIn(
            "github.event.inputs.registry_checkout",
            env["PROOF_REGISTRY_CHECKOUT"],
        )
        self.assertIn("format(", env["PROOF_ARTIFACTS"])

        for job_name in ("plan", "prove", "collect"):
            steps = engine["jobs"][job_name]["steps"]
            by_name = {step.get("name"): step for step in steps if step.get("name")}
            self.assertIn("Validate explicit registry checkout", by_name)
            self.assertIn("Check out registry (external)", by_name)
            self.assertIn("Check out caller repository", by_name)
            external = by_name["Check out registry (external)"]
            self.assertEqual(external["if"], "env.PROOF_REGISTRY_REPOSITORY != ''")
            self.assertEqual(
                external["with"]["repository"], "${{ env.PROOF_REGISTRY_REPOSITORY }}"
            )
            self.assertEqual(
                external["with"]["ref"], "${{ env.PROOF_REGISTRY_REF }}"
            )
            self.assertEqual(
                external["with"]["path"], "${{ env.PROOF_REGISTRY_CHECKOUT }}"
            )
            caller = by_name["Check out caller repository"]
            self.assertEqual(caller["if"], "env.PROOF_REGISTRY_REPOSITORY == ''")
            self.assertEqual(
                caller["with"]["path"], "${{ env.PROOF_REGISTRY_CHECKOUT }}"
            )

        plan_step = next(
            step
            for step in engine["jobs"]["plan"]["steps"]
            if step.get("id") == "plan"
        )
        self.assertEqual(
            plan_step["working-directory"], "${{ env.PROOF_REGISTRY_CHECKOUT }}"
        )
        for job_name, step_names in {
            "prove": (
                "Install proof dependencies",
                "Run lifecycle proof",
                "Run lifecycle proof (Windows)",
                "Emit index proof record",
                "Emit index proof record (Windows)",
                "Verify proof record",
                "Verify proof record (Windows)",
            ),
            "collect": ("Collect proof records",),
        }.items():
            by_name = {
                step.get("name"): step
                for step in engine["jobs"][job_name]["steps"]
                if step.get("name")
            }
            for step_name in step_names:
                with self.subTest(job=job_name, step=step_name):
                    self.assertEqual(
                        by_name[step_name]["working-directory"],
                        "${{ env.PROOF_REGISTRY_CHECKOUT }}",
                    )

    def test_pinned_linux_caller_keeps_package_nu_target_tuples(self):
        workflow_path = (
            self.root
            / ".github"
            / "workflows"
            / "linux-lifecycle-proof.yml"
        )
        self.assertTrue(
            workflow_path.is_file(),
            f"missing pinned Linux proof workflow: {workflow_path}",
        )
        caller = check_workflows.load_workflow(
            workflow_path.read_text(encoding="utf-8")
        )
        expected = {
            "nu-plugin-net": {
                "package": "fennewald/nu_plugin_net",
                "package_version": "1.9.0",
                "nu_version": "0.103.0",
                "targets": '["linux/x86_64"]',
            },
            "nu-plugin-dns": {
                "package": "dead10ck/nu_plugin_dns",
                "package_version": "4.0.10",
                "nu_version": "0.113.1",
                "targets": '["linux/x86_64"]',
            },
        }
        self.assertEqual(
            set(caller["jobs"]),
            set(expected) | {"yaml-executor"},
            f"Linux proof job set drifted; expected {sorted(expected)}",
        )
        for job_name, expected_inputs in expected.items():
            with self.subTest(job=job_name):
                actual = {
                    key: caller["jobs"][job_name]["with"][key]
                    for key in expected_inputs
                }
                self.assertEqual(
                    actual,
                    expected_inputs,
                    f"{job_name} package/Nu/target tuple drifted",
                )

    def test_engine_has_windows_proof_steps_and_conditions(self):
        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        steps = engine["jobs"]["prove"]["steps"]
        by_name = {step.get("name"): step for step in steps if step.get("name")}
        for name in (
            "Check out Numan source (Windows)",
            "Build Numan (Windows)",
            "Install Nushell (Windows)",
            "Resolve and verify Nu (Windows)",
            "Run lifecycle proof (Windows)",
            "Emit index proof record (Windows)",
            "Verify proof record (Windows)",
        ):
            with self.subTest(step=name):
                self.assertIn(name, by_name)
                self.assertIn("runner.os == 'Windows'", by_name[name]["if"])
        self.assertEqual(
            by_name["Run lifecycle proof"]["if"], "runner.os != 'Windows'"
        )
        for name in (
            "Emit index proof record (Windows)",
            "Verify proof record (Windows)",
        ):
            self.assertEqual(
                by_name[name]["if"], "always() && runner.os == 'Windows'"
            )
        self.assertEqual(
            by_name["Run lifecycle proof (Windows)"]["shell"], "pwsh"
        )
        install_nu = by_name["Install Nushell (Windows)"]
        self.assertEqual(
            install_nu["uses"],
            "hustcer/setup-nu@1b8faed9a8ff673c8ce0beae243e0b72d0787241",
        )

    def test_engine_proof_record_guards_cover_required_failures(self):
        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        steps = engine["jobs"]["prove"]["steps"]
        by_name = {step.get("name"): step for step in steps if step.get("name")}
        guards = {
            "Verify proof record": {
                "if": "always() && runner.os != 'Windows'",
                "snippets": (
                    'if [ ! -s "${proof}" ]; then',
                    '("os", "arch", "nu_version", "result", "commands")',
                    'proof["os"] != os_name or proof["arch"] != arch',
                    'proof["nu_version"] != nu_version',
                    'proof["result"] != "passed"',
                    'not isinstance(proof["commands"], list) or not proof["commands"]',
                ),
            },
            "Verify proof record (Windows)": {
                "if": "always() && runner.os == 'Windows'",
                "snippets": (
                    "Get-Item -LiteralPath $proofPath).Length -eq 0",
                    '$required = @("os", "arch", "nu_version", "result", "commands")',
                    "$proof.os -ne $env:TARGET_OS -or $proof.arch -ne $env:TARGET_ARCH",
                    "$proof.nu_version -ne $env:NU_VERSION",
                    '$proof.result -ne "passed"',
                    "@($proof.commands).Count -eq 0",
                ),
            },
        }
        for name, contract in guards.items():
            with self.subTest(step=name):
                self.assertIn(name, by_name)
                self.assertEqual(by_name[name]["if"], contract["if"])
                run = by_name[name].get("run", "")
                for snippet in contract["snippets"]:
                    self.assertIn(snippet, run)

    def test_engine_artifact_summary_defaults_to_historical_name(self):
        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        for trigger in ("workflow_call", "workflow_dispatch"):
            with self.subTest(trigger=trigger):
                summary = engine["on"][trigger]["inputs"]["artifact_summary_prefix"]
                self.assertFalse(summary.get("required", False))
                self.assertEqual(summary["type"], "string")
                self.assertEqual(summary["default"], "lifecycle-proofs")

        fallback = engine["env"]["PROOF_SUMMARY_ARTIFACT"]
        self.assertIn("inputs.artifact_summary_prefix", fallback)
        self.assertIn("github.event.inputs.artifact_summary_prefix", fallback)
        self.assertIn("'lifecycle-proofs'", fallback)

        uploads = [
            step
            for step in engine["jobs"]["collect"]["steps"]
            if str(step.get("uses", "")).startswith("actions/upload-artifact")
        ]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(
            uploads[0]["with"]["name"], "${{ env.PROOF_SUMMARY_ARTIFACT }}"
        )
        self.assertEqual(
            uploads[0]["with"]["path"].splitlines(),
            [
                "${{ env.PROOF_REGISTRY_CHECKOUT }}/proofs.json",
                "${{ env.PROOF_REGISTRY_CHECKOUT }}/proofs.md",
            ],
        )

    def test_platform_gap_artifact_summary_has_distinct_default(self):
        doc = check_workflows.load_workflow(
            self.path.read_text(encoding="utf-8")
        )
        wrapper_default = None
        for trigger in ("workflow_call", "workflow_dispatch"):
            with self.subTest(trigger=trigger):
                summary = doc["on"][trigger]["inputs"]["artifact_summary_prefix"]
                self.assertFalse(summary.get("required", False))
                self.assertEqual(summary["type"], "string")
                self.assertEqual(summary["default"], "platform-gap-proofs")
                wrapper_default = summary["default"]

        prove = doc["jobs"]["prove"]
        self.assertEqual(
            prove["with"]["artifact_summary_prefix"],
            "${{ inputs.artifact_summary_prefix }}",
        )

        engine = check_workflows.load_workflow(
            (self.root / ".github" / "workflows" / "lifecycle-proof.yml").read_text(
                encoding="utf-8"
            )
        )
        engine_default = engine["on"]["workflow_call"]["inputs"][
            "artifact_summary_prefix"
        ]["default"]
        self.assertNotEqual(engine_default, wrapper_default)

    def test_lifecycle_workflows_watch_the_actual_prove_script(self):
        for name in ("lifecycle-proof.yml", "linux-lifecycle-proof.yml"):
            with self.subTest(name=name):
                doc = check_workflows.load_workflow(
                    (self.root / ".github" / "workflows" / name).read_text(
                        encoding="utf-8"
                    )
                )
                paths = doc["on"]["pull_request"]["paths"]
                self.assertIn("scripts/lifecycle-prove.py", paths)
                self.assertNotIn("scripts/lifecycle-proof.py", paths)

    def test_yaml_executor_job_runs_pinned_and_withheld_cases(self):
        caller = check_workflows.load_workflow(
            (
                self.root
                / ".github"
                / "workflows"
                / "linux-lifecycle-proof.yml"
            ).read_text(encoding="utf-8")
        )
        job = caller["jobs"]["yaml-executor"]
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        self.assertEqual(job["timeout-minutes"], 90)
        runs = [step.get("run", "") for step in job["steps"]]
        self.assertIn("bash scripts/run-workflow-executor-ci.sh", runs)
        paths = caller["on"]["pull_request"]["paths"]
        for path in (
            "scripts/workflow_executor.py",
            "scripts/run-workflow-executor-ci.sh",
            "scripts/test_workflow_executor.py",
            "scripts/test_check_workflows.py",
            ".github/workflows/linux-lifecycle-proof.yml",
            ".github/workflows/platform-gap-lifecycle-proof.yml",
            ".github/workflows/lifecycle-proof.yml",
        ):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
