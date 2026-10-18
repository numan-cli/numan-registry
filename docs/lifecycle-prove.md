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

For an unpublished local candidate, use a loopback registry with an ephemeral
Ed25519 key. This exercises signature verification without production secrets,
an unsigned bypass, or publishing to a shared registry:

```bash
python scripts/lifecycle-prove.py \
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
bypasses are not forwarded. A real-Nu preflight refuses plugin registry or data
paths outside that home. Modules also require an isolated vendor-autoload target;
plugins can be proved on older Nu versions without that module target. Each step
has a five-minute timeout. Logs print executable hashes and the candidate file
hash. Older Nu binaries missing the path APIs required by current Numan cannot
earn lifecycle proof by substituting synthetic probe output.

The October 18, 2026 results, exact tested versions and logs are in
[`evidence/2026-10-18-lifecycle/summary.json`](evidence/2026-10-18-lifecycle/summary.json).
Nine versions passed; six failed with specific reasons. All published target
artifact digests for the nine passed versions were re-downloaded and verified;
runtime evidence is Windows x86_64 only.

The six failures remain in `registry/provisional.json`, outside the production
index. Staging combines both catalogs using `scripts/prepare-staging.py`; its
ephemeral signature does not grant production trust. To reproduce a quarantined
candidate locally:

```bash
python scripts/prepare-staging.py --output /tmp/staging-index.json
python scripts/lifecycle-prove.py --package owner/name \
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
