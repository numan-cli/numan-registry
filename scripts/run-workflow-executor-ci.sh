#!/usr/bin/env bash
set -euo pipefail

# Exercise the checked-in lifecycle workflow through the YAML-derived
# executor. The success cases run the two pinned Linux callers in a bare
# ubuntu:24.04 image. The negative case mutates the reusable workflow to write
# its proof record to artifacts/withheld.json and requires the run to fail.

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="${PYTHON:-python}"
OUT="${RUNNER_TEMP:-/tmp}/numan-yaml-executor"
rm -rf "${OUT}"
mkdir -p "${OUT}"

host_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s\n' "$1"
  fi
}

emit() {
  local name=$1
  local job=$2
  local workflow_root=$3
  local directory="${OUT}/${name}"
  mkdir -p "${directory}/out"
  "${PYTHON}" "${ROOT}/scripts/workflow_executor.py" \
    --workflow-root "${workflow_root}" \
    --repo-root "${ROOT}" \
    --job "${job}" \
    --script "${directory}/run.sh" \
    --manifest "${directory}/manifest.json" \
    --emit-only > "${directory}/emit.log"
  printf '%s\n' "${directory}"
}

run_container() {
  local directory=$1
  MSYS_NO_PATHCONV=1 docker run --rm \
    --volume "$(host_path "${ROOT}"):/src:ro" \
    --volume "$(host_path "${directory}/out"):/out" \
    --volume "$(host_path "${directory}/run.sh"):/tmp/workflow-executor.sh:ro" \
    ubuntu:24.04 \
    bash /tmp/workflow-executor.sh 2>&1 | tee "${directory}/run.log"
}

assert_passed_summary() {
  local directory=$1
  local prefix=$2
  local nu_version=$3
  local proof="${directory}/out/artifacts/${prefix}-linux-x86_64/proof.json"
  local proofs="${directory}/out/artifacts/${prefix}-proofs/proofs.json"
  test -s "${proof}"
  test -s "${proofs}"
  "${PYTHON}" - "${proofs}" "${nu_version}" <<'PY'
import json
import sys

path, nu_version = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    proofs = json.load(handle)
if not isinstance(proofs, list) or len(proofs) != 1:
    raise SystemExit(f"expected one collected proof, got {proofs!r}")
proof = proofs[0]
if proof.get("os") != "linux" or proof.get("arch") != "x86_64":
    raise SystemExit(f"unexpected proof platform: {proof!r}")
if proof.get("nu_version") != nu_version:
    raise SystemExit(f"unexpected proof Nu version: {proof!r}")
if proof.get("result") != "passed":
    raise SystemExit(f"proof did not pass: {proof!r}")
if not proof.get("commands"):
    raise SystemExit(f"proof has no commands: {proof!r}")
print(f"validated {proof['os']}/{proof['arch']} proof on Nu {proof['nu_version']}")
PY
}

run_success() {
  local name=$1
  local job=$2
  local prefix=$3
  local nu_version=$4
  local directory
  directory=$(emit "${name}" "${job}" "${ROOT}")
  echo "=== ${name}: ${job} ==="
  if ! run_container "${directory}"; then
    echo "error: ${name} executor run failed" >&2
    return 1
  fi
  grep -q '^WORKFLOW_DERIVED_JOB_OK$' "${directory}/run.log"
  assert_passed_summary "${directory}" "${prefix}" "${nu_version}"
}

run_withheld_negative() {
  local negative_root="${OUT}/negative-workflow"
  rm -rf "${negative_root}"
  mkdir -p "${negative_root}"
  cp -a "${ROOT}/.github" "${negative_root}/.github"
  "${PYTHON}" - "${negative_root}/.github/workflows/lifecycle-proof.yml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
needle = "--output artifacts/proof.json"
replacement = "--output artifacts/withheld.json"
if text.count(needle) != 1:
    raise SystemExit(f"expected exactly one {needle!r}, found {text.count(needle)}")
path.write_text(text.replace(needle, replacement), encoding="utf-8", newline="\n")
PY

  local directory
  directory=$(emit "withheld" "nu-plugin-net" "${negative_root}")
  echo "=== withheld record: nu-plugin-net ==="
  if run_container "${directory}"; then
    echo "error: withheld-record case unexpectedly passed" >&2
    return 1
  fi
  grep -q 'no proof.json files' "${directory}/run.log"
  test -s "${directory}/out/artifacts/linux-net-linux-x86_64/withheld.json"
  test ! -e "${directory}/out/artifacts/linux-net-linux-x86_64/proof.json"
  grep -q '^WORKFLOW_DERIVED_JOB_FAILED$' "${directory}/run.log"
}

run_success "nu-plugin-net" "nu-plugin-net" "linux-net" "0.103.0"
run_success "nu-plugin-dns" "nu-plugin-dns" "linux-dns" "0.113.1"
run_withheld_negative
echo "YAML_EXECUTOR_CI_OK"
