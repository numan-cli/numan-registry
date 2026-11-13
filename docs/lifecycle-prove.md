# Lifecycle-prove (Stage 1 intake gate)

An activatable package cannot earn lifecycle evidence until it is available to
Numan. Add it without `verified_with` using `scripts/add-package.py --spec …
--provisional --write`, then stage that candidate. Staging explicitly permits
missing evidence; production validation does not. Run lifecycle-prove against
the staged package on a **clean** Numan root and a **real** Nu matching the
package's `nu_version` constraint. After success, record the exact version(s) in
`verified_with`, rerun intake without `--provisional`, and only then promote it.

## Script

```bash
python3 scripts/lifecycle-prove.py \
  --package owner/name \
  --numan /path/to/numan \
  --nu /path/to/nu
```

Omit `--numan` / `--nu` to use whatever is on `PATH`.

## Reusable workflow

`.github/workflows/lifecycle-proof.yml` is the reusable runner. It accepts a
package id, exact package version, exact Nu version, a JSON target list, an
optional activation kind, and optional explicit lifecycle commands. The plan
job resolves the target matrix and command sequence; the proof jobs verify the
Nu archive against the upstream `SHA256SUMS`, download the matching Numan
release asset and verify it against `SHA256SUMS`, or build the tagged Numan
source when that platform asset is absent. Each target emits a log plus an
index-format proof record, and the collector writes `proofs.json` and
`proofs.md` artifacts. Windows uses the existing Windows proof mechanism:
`hustcer/setup-nu` installs the exact Nu version, `numan` is built from the
requested tag with `cargo build --locked --release`, and the same
`scripts/lifecycle-prove.py` commands run with `nu.exe` and `numan.exe`.
Windows logs carry the same headers and produce the same index-format proof
record as Linux and macOS. Because `setup-nu` installs Nu directly rather than
from the release archive, the Windows log records the installed `nu.exe`
SHA-256 and leaves `nu_archive_sha256` empty; the proof record still binds the
exact Nu version and target.

On 2026-11-12, the Windows x86_64 matrix target was exercised locally for
`tonythethompson/nu_plugin_qr_maker@1.2.0` on Nu 0.114.1. The planner emitted
`windows-latest`, `x86_64-pc-windows-msvc`, and `.zip`; the run used the
hash-verified Nu 0.114.1 Windows archive and Numan 0.4.0 (local debug build)
and passed the full plugin lifecycle with 0 doctor errors. The log and proof
record are in
[`evidence/2026-11-12-windows-x86_64-lifecycle/`](evidence/2026-11-12-windows-x86_64-lifecycle/).
The proof ran on the enrolled Windows host because the Windows workflow changes
were not yet published; it did not execute the GitHub-hosted Windows job.

On the same day, the platform-gap wrapper was exercised locally for
`wangjiawen2013/nu_plugin_charton@0.9.0` on Nu 0.116.1, closing its missing
`linux/x86_64` target. The local YAML-derived executor ran the wrapper and
reusable-runner steps in an `ubuntu:24.04` Docker container against the signed
candidate index; the artifact, Nu archive, and Numan release asset were all
hash-verified. The log, index-format proof record, collected proofs, and run
metadata are in
[`evidence/2026-11-12-platform-gap-charton-linux-x86_64/`](evidence/2026-11-12-platform-gap-charton-linux-x86_64/).
Because the local executor did not set `ImageOS`/`ImageVersion`, the summary
records the Docker runner instead of a GitHub-hosted runner image.

The supported target mapping is:

| Target | Runner |
|---|---|
| `linux/x86_64` | `ubuntu-24.04` |
| `linux/aarch64` | `ubuntu-24.04-arm` |
| `macos/x86_64` | `macos-15-intel` |
| `macos/aarch64` | `macos-15` |
| `windows/x86_64` | `windows-latest` |

Run it from the default branch after merge:

```bash
gh workflow run lifecycle-proof.yml \
  -f package=owner/name \
  -f package_version=1.2.3 \
  -f nu_version=0.116.1 \
  -f 'targets=["linux/aarch64","macos/aarch64"]'
```

`activation_kind` defaults to the kind declared by the package. When `commands`
is omitted, the plan uses the standard sequence for that kind: the full
`init -> registry sync -> search -> info -> install -> activate -> doctor ->
list -> deactivate -> remove -> gc` for plugins; module commands add the module
vendor-autoload probe where applicable; install-only and completion packages
use their narrower declared lifecycle. Pass `commands` as a JSON list to
override the sequence for a package with a specific contract.

The workflow has three triggers. `pull_request` runs the checked-in default
self-test before the runner lands on the default branch. `workflow_dispatch`
can run any branch containing the workflow before merge and remains available
from the default branch afterward. `workflow_call` lets another workflow
reuse it and receive the collected proof array as an output. `artifact_prefix`
is an optional `workflow_call` input for callers that launch parallel proofs;
it keeps each call's logs and collected proofs distinct. `artifact_summary_prefix`
names the collected summary artifact and defaults to the historical
`lifecycle-proofs` name, so callers that do not set it keep their existing
artifact names.

### Platform-gap proof job

`.github/workflows/platform-gap-lifecycle-proof.yml` is the permanent entry
point for a package that needs lifecycle coverage on one or more supported
targets that still need proof. It is a thin `workflow_call` / `workflow_dispatch`
wrapper around the reusable runner above and re-exports the collected `proofs`
array to callers. The wrapper calls the runner as
`./.github/workflows/lifecycle-proof.yml`, so the runner is always the version
at the same commit as the caller. That lets pull requests exercise the workflow
they change and avoids a mutable `@main` reference. The wrapper is intended for
callers in this repository. It does not sign, publish, or mutate the registry. For the current ranked list of
versions with missing Linux/macOS target proofs, see
[`lifecycle-proof-backlog.md`](lifecycle-proof-backlog.md).

Run it from the Actions UI or dispatch it with exact package and Nu versions:

```bash
gh workflow run platform-gap-lifecycle-proof.yml \
  -f package=owner/name \
  -f package_version=1.2.3 \
  -f nu_version=0.116.1 \
  -f 'targets=["linux/x86_64","linux/aarch64","windows/x86_64"]'
```

`targets` must contain one or more targets from the supported mapping above.
A new OS/architecture needs a mapping in `scripts/lifecycle_proof_plan.py`
first; unsupported targets fail closed before any proof job runs. `artifact_prefix`
defaults to `platform-gap`; set both it and `artifact_summary_prefix` to
call-specific values when launching parallel proofs on the same ref, because
artifact and concurrency names must remain distinct. A caller receives the same
collected proof records. A workflow in this repository calls it with the local
path:

```yaml
jobs:
  prove-gap:
    uses: ./.github/workflows/platform-gap-lifecycle-proof.yml
    with:
      package: owner/name
      package_version: 1.2.3
      nu_version: 0.116.1
      targets: '["linux/x86_64","linux/aarch64","windows/x86_64"]'
      artifact_prefix: gap-owner-name-all
      artifact_summary_prefix: gap-owner-name-all-proofs
```

### External-repository callers

An external repository should call the reusable runner directly, not the wrapper.
The runner can check out an explicit registry revision into a workspace-relative
path before it reads the candidate index or runs any proof scripts:

```yaml
jobs:
  prove:
    permissions:
      contents: read
    uses: numan-cli/numan-registry/.github/workflows/lifecycle-proof.yml@<full-sha>
    with:
      registry_repository: numan-cli/numan-registry
      registry_ref: <full-sha>
      registry_checkout: .numan-registry
      package: owner/name
      package_version: 1.2.3
      nu_version: 0.116.1
      targets: '["linux/x86_64","linux/aarch64"]'
      artifact_prefix: external-owner-name
      artifact_summary_prefix: external-owner-name-proofs
```

`registry_repository` and `registry_ref` are required together for an external
caller. `registry_checkout` defaults to `.` and must stay inside the workflow
workspace. The checkout is placed by the called workflow itself, because a
reusable workflow does not receive files checked out by the caller's jobs. Use
the same immutable ref for the `uses:` reference and `registry_ref`, as shown
above. Same-repository callers can leave all three inputs at their defaults and
continue using the local wrapper.

### Platform-proof coverage audit

[`platform-coverage-audit.yml`](../.github/workflows/platform-coverage-audit.yml)
runs when `registry/index.json` changes on a pull request or lands on `main`.
The job deliberately checks out only the head commit, then
`scripts/resolve_coverage_base.py` fetches the exact pull-request base SHA (or
the pushed commit's parent). Fork pull requests use the base repository's SHA;
if the runner rejects an exact-SHA fetch, the resolver falls back to a read-only
GitHub contents API request. `workflow_dispatch` can compare against an
explicit ref. If the base commit has no index—including the first commit that
introduces
`registry/index.json`—the resolver sets `base_missing=true` and the audit
reports every current target as new instead of failing or claiming zero
drift. It then classifies every published binary target as covered, missing,
yanked, or unmapped. A target is covered only when a proof for that exact
platform has a passing result, a non-empty lifecycle command list, and a Nu
version satisfying the version's claimed `nu_version` range. This is the same
proof standard used by production signing; `verified_with` and another
platform's proof are not substitutes.

The job appends a target-level report to the GitHub step summary and uploads
`platform-coverage.json` and `platform-coverage.md`. It is report-only: it does
not sign, publish, or mutate the registry. To run the same audit locally with a
materialized base index:

```bash
python scripts/audit_platform_coverage.py \
  --index registry/index.json \
  --base-index /path/to/base-index.json \
  --report-json /tmp/platform-coverage.json \
  --report-md /tmp/platform-coverage.md
```

For a first-commit or otherwise missing base index, use `--base-missing`; it
reports every current target as added rather than silently producing a
current-only snapshot:

```bash
python scripts/audit_platform_coverage.py \
  --index registry/index.json \
  --base-missing \
  --report-json /tmp/platform-coverage.json \
  --report-md /tmp/platform-coverage.md
```

`--fail-on-regression` is available for callers that want a covered target
becoming missing, yanked, or removed to fail the command. The workflow does
not enable it by default, so drift is reported without silently turning an
intentional catalog change into a blocked merge.

### Pinned Linux reproducibility

`.github/workflows/linux-lifecycle-proof.yml` re-proves the two packages whose
Linux x86_64 evidence is recorded in
[`evidence/2026-11-11-linux-lifecycle/summary.json`](evidence/2026-11-11-linux-lifecycle/summary.json):

| Package | Version | Nu | Target |
|---|---|---|---|
| `fennewald/nu_plugin_net` | 1.9.0 | 0.103.0 | `linux/x86_64` |
| `dead10ck/nu_plugin_dns` | 4.0.10 | 0.113.1 | `linux/x86_64` |

It invokes the platform-gap wrapper twice with distinct artifact prefixes, so
CI exercises the same permanent entry point that future gap-fillers use. It
runs on pull requests touching the pinned caller, the wrapper, the reusable
runner, proof scripts, the YAML executor harness, the locked requirements, the
two specs, or `registry/index.json`; it also runs weekly and on manual
dispatch. The workflow reads the committed candidate index and does not sign
or publish anything.

The same caller has a `yaml-executor` job that treats the checked-in workflow
as the source of truth. `scripts/workflow_executor.py` resolves both pinned
caller jobs through the platform-gap wrapper, emits the exact shell steps, and
`scripts/run-workflow-executor-ci.sh` runs them in bare `ubuntu:24.04`
containers. It then reruns the net job with the proof record redirected to
`artifacts/withheld.json`; that case must fail because the collector receives
no `proof.json`. This catches drift between the workflow, the executor, and
the scripts the workflow invokes.

To add proofs for a new package, run the workflow with that package, version,
Nu version, and target list, download the `lifecycle-proofs` artifact, copy the
per-target logs into a new directory under `docs/evidence/`, append the proof
records to the version's `proofs` array with each log's committed
`evidence_url`, and run the schema, production-gate, unit, catalog, and parser
checks before publishing. The run URL and artifact names belong in the
evidence batch's `summary.json`.

For a package that needs live credentials, add `--forward-env NAME` and an
optional `--nu-check '…'`. Only explicitly named variables are forwarded, and
only to the isolated post-activation Nu process; they are not passed to install,
activation, doctor, deactivation, removal, cleanup, or the Nu probe, and their
values are never printed. A nonzero Nu check fails the proof before doctor. The
2026-11-11 BigQuery run used:

```bash
python3 scripts/lifecycle-prove.py \
  --package galuszkak/nu_plugin_bigquery --package-version 0.3.0 \
  --candidate-index registry/index.json \
  --numan /path/to/numan --nu /path/to/nu/0.114.1/nu.exe \
  --forward-env GOOGLE_APPLICATION_CREDENTIALS \
  --forward-env GOOGLE_CLOUD_PROJECT \
  --nu-check 'let rows = (bq query "SELECT 1 AS proof"); let proof = ($rows | get proof | first); if $proof != 1 { error make { msg: "BigQuery proof query returned an unexpected value" } }; $"bigquery proof: SELECT 1 returned ($proof)"'
```

For an unpublished local candidate, use a loopback registry with an ephemeral
Ed25519 key. This exercises signature verification without production secrets,
an unsigned bypass, or publishing to a shared registry:

```bash
python3 scripts/lifecycle-prove.py \
  --package owner/name --package-version 1.2.3 \
  --candidate-index registry/index.json \
  --numan /path/to/numan --nu /path/to/nu
```

The candidate file is served unchanged; its signature and private key exist
only in memory. The disposable root selects `lifecycle-candidate` as its default
registry and removes the seeded official registry from that test root. Install
is pinned to the selected version and the resulting lockfile version is checked
before activation. The source-tree signature is never modified. A successful
local candidate run is package lifecycle evidence, not production trust or a
production deployment.

Child processes receive a private home, config, data, cache and temp directory
under the test root. Inherited credentials, `NUPM_HOME` and unsigned-verification
bypasses are not forwarded unless explicitly named with `--forward-env`, and
then only to the Nu check process. A real-Nu preflight refuses plugin registry or data
paths outside that home. Modules also require an isolated vendor-autoload target;
plugins can be proved on older Nu versions without that module target. Each step
has a five-minute timeout. Logs print executable hashes and the candidate file
hash. Older Nu binaries missing the path APIs required by current Numan cannot
earn lifecycle proof by substituting synthetic probe output.

The October 18, 2026 results, exact tested versions and logs are in
[`evidence/2026-10-18-lifecycle/summary.json`](evidence/2026-10-18-lifecycle/summary.json).
Nine versions passed; six failed with specific reasons. All published target
artifact digests for the nine passed versions were re-downloaded and verified;
runtime evidence is Windows x86_64 only. The nine October 18 `proofs` records use
`2026-10-18T00:00:00Z` because the captured logs record the run date but not a
wall-clock time; each evidence URL points at the commit that added the log.

Three additional versions passed independent Windows x86_64 lifecycle
re-verification on October 19, 2026: `JosephTLyons/nu_plugin_units@0.1.9`,
`idanarye/nu_plugin_handlebars@0.3.0`, and
`kaathewisegit/nu_plugin_endecode@0.0.0-snapshot.20261019.2fe5276`. Their logs
are in [`evidence/2026-10-19-lifecycle/`](evidence/2026-10-19-lifecycle/) and
are recorded with `2026-10-19T00:00:00Z` for the same reason; each evidence URL
points at commit `82b2ce7`. On 2026-11-11, the 76 remaining activatable versions were run on Windows
x86_64 against their exact `verified_with` Nu versions (83 runs). The
candidate index was served over a loopback registry with an ephemeral key;
the client was `numan 0.4.0` (debug) and every Nu archive was verified
against the release `SHA256SUMS`. The logs and per-run metadata are in
[`evidence/2026-11-11-lifecycle/`](evidence/2026-11-11-lifecycle/).
The batch produced 78 passes and 5 failures. Passing runs are
recorded with their actual timestamps; failed runs are recorded with
`result: "failed"` and remain unproved for production.

The 2026-11-11 failures were:

- `fennewald/nu_plugin_net@1.9.0` on Nu 0.103.0 — no Windows artifact.
- `Trivernis/nu-plugin-dialog@0.1.0` on Nu 0.107.0 — plugin registration
  failed with a protocol decode error.
- `amtoine/nu-git-manager@0.8.0` and
  `amtoine/nu-git-manager-sugar@0.7.0` on Nu 0.113.1 — module activation
  failed on incompatible Nushell syntax.
- `dead10ck/nu_plugin_dns@4.0.10` on Nu 0.113.1 — no Windows artifact.

Each failure is recorded with `result: "failed"` and its log; none is a
production proof. On 2026-11-11, Linux x86_64 proofs were run for two of these
Windows-only failures: `fennewald/nu_plugin_net@1.9.0` on Nu 0.103.0 and
`dead10ck/nu_plugin_dns@4.0.10` on Nu 0.113.1. Both passed the full lifecycle
with Numan 0.4.0 and hash-verified Linux Nu releases. Their logs and per-run
metadata are in
[`evidence/2026-11-11-linux-lifecycle/`](evidence/2026-11-11-linux-lifecycle/).
On the same day, GitHub-hosted runners completed the remaining published
targets for both versions: macOS x86_64 and macOS arm64 for
`fennewald/nu_plugin_net@1.9.0` on Nu 0.103.0, and macOS arm64 plus Linux arm64
for `dead10ck/nu_plugin_dns@4.0.10` on Nu 0.113.1. The jobs built Numan 0.4.0
from the `v0.4.0` tag, verified every Nu archive against the upstream
`SHA256SUMS`, and ran the same loopback-signed candidate lifecycle. All four
passed. Their logs and per-run metadata are in
[`evidence/2026-11-11-cross-platform-lifecycle/`](evidence/2026-11-11-cross-platform-lifecycle/).

On 2026-11-11 the reusable workflow itself proved
`JosephTLyons/nu_plugin_units@0.1.9` on Linux arm64 and macOS arm64 with Nu
0.116.1. Both targets passed the full lifecycle, selected `ubuntu-24.04-arm`
and `macos-15`, and used hash-verified Numan 0.4.0 release assets. The run is
[43017573551](https://github.com/numan-cli/numan-registry/actions/runs/43017573551);
its logs and per-run metadata are in
[`evidence/2026-11-11-reusable-lifecycle-proof/`](evidence/2026-11-11-reusable-lifecycle-proof/).


The credential-gated `galuszkak/nu_plugin_bigquery@0.3.0` was proven separately
on 2026-11-11 on Windows x86_64 with Nu 0.114.1. The run used the loopback-signed
candidate index and explicit `--forward-env` flags for
`GOOGLE_APPLICATION_CREDENTIALS` and `GOOGLE_CLOUD_PROJECT`; the live
`bq query "SELECT 1 AS proof"` returned `1`, and the full lifecycle completed.
The log and metadata are in
[`evidence/2026-11-11-bigquery-0.3.0/`](evidence/2026-11-11-bigquery-0.3.0/).
Version 0.3.0 is now `evidence_tier: proven` with a passed Windows x86_64 proof
for Nu 0.114.1.

`scripts/materialize_candidate.py` excludes versions still marked
`evidence_tier: provisional` before production signing, so they cannot claim a
lifecycle pass.

The three remaining 2026-11-11 failures were marked `yanked` in
`registry/index.json` after their failed proof records and concrete deferral
reasons established that no supported Numan/Nu host could activate them. The
provisional evidence tier is retained as history; `yanked` is the terminal
availability signal. `nu_plugin_net` and `nu_plugin_dns` were restored to
`evidence_tier: proven` after their Linux x86_64 proofs passed. The triage
record is in
[`evidence/2026-11-11-lifecycle/triage.json`](evidence/2026-11-11-lifecycle/triage.json).
`scripts/materialize_candidate.py` excludes both provisional and yanked
versions, so they cannot claim a production lifecycle pass and do not block
signing. The earlier
`dead10ck/nu_plugin_dns@4.0.11` candidate remains in
`registry/provisional.json`. Staging combines both catalogs using
`scripts/prepare-staging.py`; its ephemeral signature does not grant production
trust. To reproduce a quarantined
candidate locally:

```bash
python3 scripts/prepare-staging.py --output /tmp/staging-index.json
python3 scripts/lifecycle-prove.py --package owner/name \
  --candidate-index /tmp/staging-index.json --numan /path/to/numan --nu /path/to/nu
```

After a candidate earns real lifecycle evidence, move that exact version into
`registry/index.json`, record `verified_with`, set `evidence_tier` to `proven`,
remove its deferral and any `yanked` marker, and remove it from the provisional
catalog. The staging merge rejects an attempt to overwrite
a version already in production. Keep package identity, immutable source, and
artifact hashes intact; changed payloads require a new version and intake.

The script creates a temporary `--root`, runs:

`init → registry sync → search → info → install → activate → doctor → list → deactivate → remove → gc`

and exits nonzero on the first failing step (printing the step name). Use
`--keep-root` to retain the temp root for debugging, or `--root PATH` to reuse
a directory (never auto-deleted).

## Requirements

- Network access to the official registry (and package artifact URLs)
- A `numan` build new enough for the package under test
- A `nu` binary compatible with the package's `nu_version`

## Promotion requirement

Lifecycle evidence is mandatory before an activatable package is promoted to
production. Paste the successful command, OS, Nu version, and package version
into the intake PR, and record every successfully proved Nu version in the
version entry's non-empty `verified_with` list. Production validation rejects
plugins and explicitly activated modules unless every entry is an exact
`MAJOR.MINOR.PATCH` Nu version satisfying the package's `nu_version` constraint.
Build validation proves archive structure and hashes;
staging proves the unsigned catalog and ephemeral signature path; neither is a
substitute for exercising install, activation, deactivation, removal, and
cleanup against a real Nu. If the lifecycle prove cannot run, keep the package
out of the production catalog until the evidence is available.

## Production signing gate

Production signing (`scripts/ci-sign.py --production`) refuses to sign an
activatable package version unless `proofs` contains a `result: "passed"`
record whose exact `nu_version` satisfies the version's `nu_version` range.
This is stricter than the existing `verified_with` validation. There is no
production bypass: a missing or non-matching proof refuses the signature.
