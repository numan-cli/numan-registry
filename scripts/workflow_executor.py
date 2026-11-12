#!/usr/bin/env python3
"""Resolve a pinned lifecycle job from workflow YAML and emit executable steps.

The executor is intentionally narrow: it reads the same reusable
``lifecycle-proof.yml`` steps that GitHub runs, resolves the caller's package
and target inputs, and emits a shell script for a bare Linux container. It
does not replace GitHub Actions; it makes the checked-in YAML independently
executable so CI can catch drift between the workflow and the scripts it
claims to run.

Supported actions are the ones used by the lifecycle proof workflow:
checkout, setup-python, the Rust toolchain, and artifact upload/download.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

CALLER_WORKFLOW = ".github/workflows/linux-lifecycle-proof.yml"
REUSABLE_WORKFLOW = ".github/workflows/lifecycle-proof.yml"
WRAPPER_WORKFLOW = ".github/workflows/platform-gap-lifecycle-proof.yml"
BASH = "bash"
if os.name == "nt":
    _git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if _git_bash.exists():
        BASH = str(_git_bash)

EXPR_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")
        |(?P<operator>==|!=|&&|\|\||!|\(|\)|,)
        |(?P<identifier>[A-Za-z_][A-Za-z0-9_.-]*)
    )""",
    re.VERBOSE,
)


def mapping_value(node, key):
    """Return a mapping node's value for ``key``, or ``None``."""
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if key_node.value == key:
            return value_node
    return None


def sequence_values(node):
    """Return a sequence node's values."""
    if not isinstance(node, yaml.SequenceNode):
        raise ValueError("expected a YAML sequence")
    return node.value


def line_number(node):
    """Return the one-based source line for a YAML node."""
    return node.start_mark.line + 1


def source_line(text, line):
    """Return the stripped source line at ``line``."""
    lines = text.splitlines()
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def load_workflow(path):
    """Load a workflow both as data (BaseLoader) and as line-aware nodes."""
    text = path.read_text(encoding="utf-8")
    return (
        yaml.load(text, Loader=yaml.BaseLoader),
        yaml.compose(text),
    )


def workflow_steps(data, root, job_name, text):
    """Return step mappings with their source locations."""
    job = data["jobs"][job_name]
    job_node = mapping_value(mapping_value(root, "jobs"), job_name)
    steps_node = mapping_value(job_node, "steps")
    result = []
    for index, step_node in enumerate(sequence_values(steps_node)):
        step = job["steps"][index]
        run_node = mapping_value(step_node, "run")
        uses_node = mapping_value(step_node, "uses")
        anchor = run_node or uses_node
        if anchor is None:
            raise ValueError(f"step {index} in {job_name} has neither run nor uses")
        line = line_number(anchor)
        result.append(
            {
                "step": step,
                "line": line,
                "line_text": source_line(text, line),
            }
        )
    return result


def _truthy(value) -> bool:
    return value not in (None, False, "", 0)


def _stringify(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def _lookup(token: str, ctx: dict):
    token = token.strip()
    if token in {"true", "True"}:
        return True
    if token in {"false", "False"}:
        return False
    if token in {"null", "Null"}:
        return None
    if token == "runner.os":
        return ctx.get("runner", {}).get("os", "Linux")
    if token == "github.ref":
        return "refs/heads/main"
    if token.startswith("github.event.inputs."):
        return ""
    if token.startswith("inputs."):
        return ctx["inputs"].get(token.split(".", 1)[1], "")
    if token.startswith("env."):
        return ctx["env"].get(token.split(".", 1)[1], "")
    if token.startswith("matrix."):
        return ctx["matrix"].get(token.split(".", 1)[1], "")
    if token.startswith("needs."):
        rest = token[len("needs.") :]
        job_name, separator, output = rest.partition(".outputs.")
        if separator:
            return (
                ctx.get("needs", {})
                .get(job_name, {})
                .get("outputs", {})
                .get(output, "")
            )
    if token.startswith("steps."):
        return ""
    return ""


def _call_function(name: str, args: list, ctx: dict):
    if name in {"always", "success"}:
        return True
    if name in {"failure", "cancelled"}:
        return False
    if name == "format":
        if not args:
            raise ValueError("format() requires a format string")
        return str(args[0]).format(*[_stringify(value) for value in args[1:]])
    if name == "contains":
        if len(args) != 2:
            raise ValueError("contains() requires two arguments")
        return _stringify(args[1]) in _stringify(args[0])
    if name == "startsWith":
        if len(args) != 2:
            raise ValueError("startsWith() requires two arguments")
        return _stringify(args[0]).startswith(_stringify(args[1]))
    if name == "endsWith":
        if len(args) != 2:
            raise ValueError("endsWith() requires two arguments")
        return _stringify(args[0]).endswith(_stringify(args[1]))
    raise ValueError(f"unsupported expression function: {name}")


class _ExpressionParser:
    """Small parser for the GitHub expression subset used by the workflow."""

    def __init__(self, text: str, ctx: dict):
        self.ctx = ctx
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> list[tuple[str, str]]:
        tokens = []
        position = 0
        while position < len(text):
            match = TOKEN_RE.match(text, position)
            if match is None:
                if text[position:].strip() == "":
                    break
                raise ValueError(f"cannot parse expression near {text[position:]!r}")
            kind = match.lastgroup
            value = match.group(kind)
            if kind == "string":
                quote = value[0]
                value = value[1:-1].replace(quote * 2, quote)
            tokens.append((kind, value))
            position = match.end()
        return tokens

    def _peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _advance(self):
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        self.index += 1
        return token

    def _match(self, kind: str, value: str | None = None):
        token = self._peek()
        if token is None or token[0] != kind:
            return False
        if value is not None and token[1] != value:
            return False
        self.index += 1
        return True

    def _expect(self, kind: str, value: str | None = None):
        if not self._match(kind, value):
            token = self._peek()
            raise ValueError(f"expected {value or kind}, got {token!r}")

    def parse(self):
        value = self._or()
        if self._peek() is not None:
            raise ValueError(f"unexpected token {self._peek()!r}")
        return value

    def _or(self):
        value = self._and()
        while self._match("operator", "||"):
            right = self._and()
            value = value if _truthy(value) else right
        return value

    def _and(self):
        value = self._comparison()
        while self._match("operator", "&&"):
            right = self._comparison()
            value = right if _truthy(value) else value
        return value

    def _comparison(self):
        left = self._unary()
        token = self._peek()
        if token is not None and token[0] == "operator" and token[1] in {"==", "!="}:
            operator = self._advance()[1]
            right = self._unary()
            return left == right if operator == "==" else left != right
        return left

    def _unary(self):
        if self._match("operator", "!"):
            return not _truthy(self._unary())
        if self._match("operator", "("):
            value = self._or()
            self._expect("operator", ")")
            return value
        kind, value = self._advance()
        if kind == "string":
            return value
        if kind != "identifier":
            raise ValueError(f"unexpected expression token: {value!r}")
        if self._match("operator", "("):
            args = []
            if not self._match("operator", ")"):
                while True:
                    args.append(self._or())
                    if self._match("operator", ")"):
                        break
                    self._expect("operator", ",")
            return _call_function(value, args, self.ctx)
        return _lookup(value, self.ctx)


def eval_expression(expression: str, ctx: dict):
    """Evaluate one GitHub expression."""
    return _ExpressionParser(expression.strip(), ctx).parse()


def eval_expr(expression: str, ctx: dict):
    """Evaluate a value expression used inside ``${{ ... }}``."""
    return eval_expression(expression, ctx)


def resolve_text(value, ctx: dict):
    """Substitute ``${{ ... }}`` expressions in a scalar value."""
    if not isinstance(value, str):
        return _stringify(value)

    def replacement(match):
        return _stringify(eval_expr(match.group(1), ctx))

    return EXPR_RE.sub(replacement, value)


def resolve_map(values, ctx: dict):
    """Resolve a mapping of scalar workflow values."""
    if not values:
        return {}
    return {key: resolve_text(value, ctx) for key, value in values.items()}


def step_condition(step, ctx: dict) -> tuple[bool, bool]:
    """Return ``(enabled, always)`` for a step's ``if`` expression."""
    condition = step.get("if")
    if condition is None or condition == "":
        return True, False
    text = str(condition).strip()
    always = "always()" in text
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return bool(eval_expression(text, ctx)), always


def _workflow_call_defaults(workflow: dict) -> dict[str, str]:
    call = workflow.get("on", {}).get("workflow_call", {})
    inputs = call.get("inputs", {})
    return {
        name: _stringify(spec.get("default", ""))
        for name, spec in inputs.items()
    }


def _base_context(inputs: dict[str, str]) -> dict:
    return {
        "inputs": inputs,
        "needs": {},
        "matrix": {},
        "env": {},
        "runner": {"os": "Linux"},
    }


def _resolve_reusable_with(workflow_root: Path, caller_job: dict) -> dict:
    """Resolve a caller job into the inputs passed to the reusable workflow."""
    uses = caller_job.get("uses")
    if uses == f"./{REUSABLE_WORKFLOW}":
        return dict(caller_job.get("with", {}) or {})

    if uses == f"./{WRAPPER_WORKFLOW}":
        wrapper_path = workflow_root / WRAPPER_WORKFLOW
        wrapper, _ = load_workflow(wrapper_path)
        inputs = _workflow_call_defaults(wrapper)
        inputs.update(
            {
                key: _stringify(value)
                for key, value in (caller_job.get("with", {}) or {}).items()
            }
        )
        prove = wrapper["jobs"]["prove"]
        if prove.get("uses") != f"./{REUSABLE_WORKFLOW}":
            raise RuntimeError(
                f"wrapper prove job does not call {REUSABLE_WORKFLOW}"
            )
        return resolve_map(prove.get("with", {}), _base_context(inputs))

    raise RuntimeError(
        f"{caller_job.get('name', 'caller job')} does not call "
        f"{REUSABLE_WORKFLOW} or {WRAPPER_WORKFLOW}"
    )


def run_plan_scaffold(
    reusable: dict,
    inputs: dict[str, str],
    repo_root: Path,
    reusable_path: Path,
):
    """Run the reusable plan step on the host to resolve matrix/outputs."""
    ctx = _base_context(inputs)
    ctx["env"] = resolve_map(reusable.get("env", {}), ctx)
    with tempfile.TemporaryDirectory() as temporary:
        temp_path = Path(temporary)
        output = temp_path / "github-output"
        output.write_text("", encoding="utf-8")
        env = os.environ.copy()
        env.update(ctx["env"])
        env["GITHUB_OUTPUT"] = str(output)
        env["RUNNER_TEMP"] = str(temp_path / "runner-temp")
        Path(env["RUNNER_TEMP"]).mkdir()
        python_dir = Path(sys.executable).parent.as_posix()
        if os.name == "nt":
            try:
                python_dir = subprocess.check_output(
                    ["cygpath", "-u", python_dir], text=True
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                pass
        # The plan step runs under bash, including Git Bash on Windows, where
        # PATH uses ':' rather than Windows' ';' separator.
        env["PATH"] = python_dir + ":" + env.get("PATH", "")
        reusable_text = reusable_path.read_text(encoding="utf-8")
        steps = workflow_steps(reusable, yaml.compose(reusable_text), "plan", reusable_text)
        plan_step = next(item["step"] for item in steps if item["step"].get("id") == "plan")
        script = resolve_text(plan_step["run"], ctx)
        result = subprocess.run(
            [BASH, "-c", script],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"plan step failed:\nstdout={result.stdout}\nstderr={result.stderr}"
            )
        outputs = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                outputs[key] = value
        for required in (
            "package",
            "package_version",
            "nu_version",
            "activation_kind",
            "commands",
            "matrix",
            "numan_version",
            "numan_repo",
        ):
            if required not in outputs:
                raise RuntimeError(f"plan did not emit {required}")
        outputs["matrix_value"] = json.loads(outputs["matrix"])
        return outputs, ctx


def _python_version_check(executable: str, version: str) -> str:
    """Accept the requested Python series or one of its patch releases."""
    pattern = re.escape(version)
    return (
        f"{executable} --version 2>&1 | "
        f"grep -Eq '^Python {pattern}(\\.[0-9]+)?$'"
    )


def action_commands(action: str, with_values: dict, ctx: dict) -> list[str]:
    """Translate a supported GitHub action into shell commands."""
    action_name = action.split("@", 1)[0]
    if action_name == "actions/checkout":
        if with_values.get("repository"):
            raise RuntimeError("cross-repository checkout is not supported")
        return [
            "rm -rf /work",
            "mkdir -p /work",
            "cp -a /src/scripts /src/registry /src/schemas /src/requirements /work/",
            "cd /work",
        ]
    if action_name == "actions/setup-python":
        version = with_values.get("python-version", "")
        if not version:
            raise RuntimeError("setup-python has no python-version")
        return [
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get -o Acquire::ForceIPv4=true update -qq",
            "apt-get -o Acquire::ForceIPv4=true install -y -qq --no-install-recommends python3 python3-venv",
            _python_version_check("python3", version),
            "python3 -m venv /opt/venv",
            "export PATH=\"/opt/venv/bin:${PATH}\"",
            _python_version_check("python", version),
        ]
    if action_name == "dtolnay/rust-toolchain":
        toolchain = with_values.get("toolchain", "")
        if not toolchain:
            raise RuntimeError("rust-toolchain has no toolchain")
        return [
            "export RUSTUP_HOME=/opt/rustup",
            "export CARGO_HOME=/opt/cargo",
            "mkdir -p \"${RUSTUP_HOME}\" \"${CARGO_HOME}\"",
            "curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o /tmp/rustup-init.sh",
            f"sh /tmp/rustup-init.sh -y --no-modify-path --profile minimal --default-toolchain {toolchain} >/tmp/rustup.log 2>&1",
            "export PATH=\"${CARGO_HOME}/bin:${PATH}\"",
            f"rustc --version 2>&1 | grep -q '^rustc {toolchain} '",
        ]
    if action_name == "actions/upload-artifact":
        name = with_values.get("name", "")
        path = with_values.get("path", "")
        if not name or not path:
            raise RuntimeError("upload-artifact needs name and path")
        commands = [f"mkdir -p /out/artifacts/{name}", "matched=0"]
        for item in [line.strip() for line in path.splitlines() if line.strip()]:
            if item.endswith("/"):
                commands.append(
                    f"if [ -d '{item}' ]; then cp -a '{item}/.' /out/artifacts/{name}/; matched=1; fi"
                )
            else:
                commands.append(
                    f"if [ -e '{item}' ]; then cp -a '{item}' /out/artifacts/{name}/; matched=1; fi"
                )
        missing = with_values.get("if-no-files-found", "warn")
        if missing == "error":
            commands.append(
                f"if [ \"${{matched}}\" -eq 0 ]; then echo 'no files found for artifact {name}' >&2; exit 1; fi"
            )
        else:
            commands.append(
                f"if [ \"${{matched}}\" -eq 0 ]; then echo 'warning: no files found for artifact {name}' >&2; fi"
            )
        return commands
    if action_name == "actions/download-artifact":
        path = with_values.get("path", "")
        pattern = with_values.get("pattern", "")
        if not path or not pattern:
            raise RuntimeError("download-artifact needs path and pattern")
        return [
            f"mkdir -p '{path}'",
            f"matched=0; for src in /out/artifacts/{pattern}; do [ -e \"$src\" ] || continue; cp -a \"$src\" '{path}/'; matched=1; done",
            "if [ \"${matched}\" -eq 0 ]; then echo 'no matching artifacts for pattern' >&2; exit 1; fi",
        ]
    if action_name == "hustcer/setup-nu":
        raise RuntimeError("hustcer/setup-nu is only supported by GitHub-hosted Windows runners")
    raise RuntimeError(f"unsupported action: {action}")


def emit_job(workflow_root: Path, repo_root: Path, job_name: str):
    """Emit a shell script and manifest for one pinned caller job."""
    caller_path = workflow_root / CALLER_WORKFLOW
    reusable_path = workflow_root / REUSABLE_WORKFLOW
    caller, _ = load_workflow(caller_path)
    reusable, reusable_root = load_workflow(reusable_path)
    caller_job = caller["jobs"][job_name]
    resolved_with = _resolve_reusable_with(workflow_root, caller_job)

    inputs = _workflow_call_defaults(reusable)
    inputs.update(
        {key: _stringify(value) for key, value in resolved_with.items()}
    )
    plan_outputs, plan_ctx = run_plan_scaffold(
        reusable, inputs, repo_root, reusable_path
    )
    matrix = plan_outputs["matrix_value"]["include"]
    if len(matrix) != 1:
        raise RuntimeError(f"expected one matrix target, got {matrix}")
    matrix_entry = matrix[0]
    ctx = {
        "inputs": inputs,
        "needs": {"plan": {"outputs": plan_outputs}},
        "matrix": matrix_entry,
        "env": {},
        "runner": {"os": "Linux"},
    }
    ctx["env"] = resolve_map(reusable.get("env", {}), ctx)

    manifest = []
    script_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Generated from workflow YAML; do not edit.",
        "mkdir -p /out/artifacts /tmp/runner-temp",
        "export RUNNER_TEMP=/tmp/runner-temp",
        "for tool in python python3 pip pip3 curl git xz cargo rustc uv; do",
        "  if command -v \"$tool\" >/dev/null 2>&1; then",
        "    echo \"unexpected preinstalled tool: $tool\" >&2",
        "    exit 1",
        "  fi",
        "done",
        "echo BARE_IMAGE_ASSERTION_OK",
        "mkdir -p /work",
        "cd /work",
        "export PATH=\"/opt/venv/bin:/opt/cargo/bin:${PATH}\"",
        "export RUSTUP_HOME=/opt/rustup",
        "export CARGO_HOME=/opt/cargo",
        "OVERALL_FAILED=0",
    ]

    def add_step(step, line, file_path, job_label, job_env, extra_ctx):
        step_ctx = dict(extra_ctx)
        step_ctx["env"] = {**extra_ctx["env"], **job_env}
        step_ctx["env"].update(
            {
                key: resolve_text(value, step_ctx)
                for key, value in (step.get("env", {}) or {}).items()
            }
        )
        enabled, always = step_condition(step, step_ctx)
        if not enabled:
            return
        source = f"{file_path.relative_to(workflow_root)}:{line}"
        if "uses" in step:
            with_values = resolve_map(step.get("with", {}), step_ctx)
            commands = action_commands(step["uses"], with_values, step_ctx)
            kind = step["uses"]
        else:
            if "run" not in step:
                raise RuntimeError(f"step at {source} has neither run nor uses")
            commands = [resolve_text(step["run"], step_ctx)]
            kind = "run"
        manifest.append(
            {
                "job": job_label,
                "source": source,
                "line_text": source_line(file_path.read_text(encoding="utf-8"), line),
                "kind": kind,
                "commands": commands,
            }
        )
        script_lines.extend(
            [
                "",
                f"# source: {source}",
                "STEP_ALWAYS=1" if always else "STEP_ALWAYS=0",
                "STEP_RC=0",
                'if [ "${JOB_FAILED}" -eq 0 ] || [ "${STEP_ALWAYS}" -eq 1 ]; then',
                "(",
                "set -euo pipefail",
                "cd /work 2>/dev/null || true",
            ]
        )
        for key, value in {**job_env, **resolve_map(step.get("env", {}), step_ctx)}.items():
            script_lines.append(f"export {key}={json.dumps(str(value))}")
        script_lines.extend(commands)
        script_lines.extend(
            [
                ") || STEP_RC=$?",
                "fi",
                'if [ "${STEP_RC}" -ne 0 ]; then JOB_FAILED=1; fi',
                'if [ -s "${GITHUB_ENV:-/dev/null}" ]; then set -a; . "${GITHUB_ENV}"; set +a; fi',
            ]
        )

    for job_label, job in (
        ("plan", reusable["jobs"]["plan"]),
        ("prove", reusable["jobs"]["prove"]),
        ("collect", reusable["jobs"]["collect"]),
    ):
        job_ctx = {
            "inputs": inputs,
            "needs": {"plan": {"outputs": plan_outputs}},
            "matrix": matrix_entry,
            "env": {},
            "runner": {"os": "Linux"},
        }
        job_ctx["env"] = resolve_map(reusable.get("env", {}), job_ctx)
        job_env = resolve_map(job.get("env", {}), job_ctx)
        job_env = {**job_ctx["env"], **job_env}
        script_lines.extend(
            [
                "",
                f"# job: {job_label}",
                "JOB_FAILED=0",
                f"export GITHUB_OUTPUT=/tmp/github-output-{job_label}",
                f": > \"$GITHUB_OUTPUT\"",
                f"export GITHUB_ENV=/tmp/github-env-{job_label}",
                f": > \"$GITHUB_ENV\"",
                f"export GITHUB_STEP_SUMMARY=/tmp/github-summary-{job_label}",
                f": > \"$GITHUB_STEP_SUMMARY\"",
            ]
        )
        for key, value in job_env.items():
            script_lines.append(f"export {key}={json.dumps(str(value))}")
        reusable_text = reusable_path.read_text(encoding="utf-8")
        steps = workflow_steps(reusable, reusable_root, job_label, reusable_text)
        for item in steps:
            add_step(
                item["step"],
                item["line"],
                reusable_path,
                job_label,
                job_env,
                job_ctx,
            )
        script_lines.append(
            'if [ "${JOB_FAILED}" -ne 0 ]; then OVERALL_FAILED=1; fi'
        )
    script_lines.extend(
        [
            'if [ "${OVERALL_FAILED}" -ne 0 ]; then',
            "  echo WORKFLOW_DERIVED_JOB_FAILED >&2",
            "  exit 1",
            "fi",
            "echo WORKFLOW_DERIVED_JOB_OK",
        ]
    )
    script = "\n".join(script_lines) + "\n"
    return script, manifest, inputs, plan_outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--emit-only", action="store_true")
    args = parser.parse_args(argv)

    script, manifest, inputs, plan_outputs = emit_job(
        args.workflow_root, args.repo_root, args.job
    )
    args.script.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.script.write_text(script, encoding="utf-8", newline="\n")
    args.manifest.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"job={args.job}")
    print(f"inputs={json.dumps(inputs, sort_keys=True)}")
    print(f"matrix={json.dumps(plan_outputs['matrix_value'], sort_keys=True)}")
    for entry in manifest:
        print(f"{entry['source']} [{entry['kind']}]")
        for command in entry["commands"]:
            print(f"  {command}")
    if not args.emit_only:
        print(f"script={args.script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
