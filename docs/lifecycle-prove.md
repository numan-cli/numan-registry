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
under the test root. Inherited credentials are not forwarded unless explicitly
named with `--forward-env`, and then only to the Nu check process; `NUPM_HOME`,
`NUMAN_ROOT` and unsigned-verification bypasses are always refused. A real-Nu preflight refuses plugin registry or data
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
the client was `numan 0.4.0` (debug); downloaded Nu archives were verified
against the release `SHA256SUMS`, and 0.113.1 reused a cached real-Nu root pinned by `nu_exe_sha256`. The logs and per-run metadata are in
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

The three remaining 2026-11-11 failures were moved to
`evidence_tier: provisional` in `registry/index.json` with their failed proof
records and concrete deferral reasons. `nu_plugin_net` and `nu_plugin_dns` were
restored to `evidence_tier: proven` after their Linux x86_64 proofs passed. The
triage record is in
[`evidence/2026-11-11-lifecycle/triage.json`](evidence/2026-11-11-lifecycle/triage.json).
`scripts/materialize_candidate.py` excludes the remaining provisional versions,
so they cannot claim a production lifecycle pass and do not block signing. The earlier
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
`registry/index.json`, record `verified_with`, set `evidence_tier` to `proven`, remove its deferral, and remove it
from the provisional catalog. The staging merge rejects an attempt to overwrite
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
