# Numan Official Registry

Curated registry index for the [Numan](https://github.com/numan-cli/numan) Nushell package manager.

This repository is **not** the package manager itself. It publishes the signed registry index that Numan clients download, verify, and install from.

## Status

The official production registry is live at [numan-cli.github.io/numan-registry](https://numan-cli.github.io/numan-registry/) (human landing page) and signed with the `official-2026-07-01` trust root built into Numan. Clients sync [`index.json`](https://numan-cli.github.io/numan-registry/index.json) and verify [`index.json.sig`](https://numan-cli.github.io/numan-registry/index.json.sig); do not treat the HTML landing page as machine input.

**Catalog (committed production candidate):** **56** packages (34 plugins, 10 modules, 6 completions, 6 scripts). The public CDN updates only after production signing/publish. Six failed lifecycle candidates are preserved in [`registry/provisional.json`](registry/provisional.json), outside the production index; staging merges them with the production catalog before ephemeral signing. See the generated master list with Nu constraints in [`docs/catalog-compat.md`](docs/catalog-compat.md) and the [October 18 lifecycle evidence](docs/evidence/2026-10-18-lifecycle/summary.json). Demand-ranked *plugin candidates* still outside the catalog live in [`numan-plugins/docs/backlog.json`](https://github.com/numan-cli/numan-plugins/blob/main/docs/backlog.json).

This `main` branch is the catalog source. Its committed `registry/index.json.sig` is deliberately a placeholder: the protected production workflow signs the catalog with `NUMAN_REGISTRY_PRIVATE_KEY` and publishes the resulting detached signature to GitHub Pages. Do not use the source-tree signature for an install; use Numan's `official` registry URL.

## Layout

```text
.
├── docs/
│   ├── key-provisioning.md            # WSL-first maintainer key-provisioning instructions
│   ├── production-cutover-checklist.md # Step-by-step cutover runbook with rollback steps
│   ├── key-rotation-checklist.md      # Rotation runbook: successor-key ordering, propagation wait, rollback
│   ├── incident-response.md            # Yank, rollback, compromise, and user-remediation policy
│   ├── intake-candidates.md           # Running intake list (auto-synced; edit intake-state.json)
│   ├── intake-state.json              # Machine-readable intake catalog (source for sync)
│   ├── catalog-compat.md              # Master catalog × Nu compat table (from index.json)
│   ├── upstream-release-outreach.md   # Outreach plan + tracker (tracker auto-synced)
│   ├── lifecycle-prove.md             # Stage 1: scripted search→…→gc against real Nu
│   └── outreach-issues/               # Copy-paste GitHub issue drafts for upstream contact
├── .cursor/
│   └── hooks.json                     # Agent hooks: auto-sync intake docs after edits/gh/stop
├── keys/
│   └── official.pub               # Committed production public key
├── registry/
│   ├── index.html                 # Human-facing GitHub Pages landing (not signed)
│   ├── index.json                 # Signed registry index
│   ├── provisional.json           # Quarantined candidates, merged into staging only
│   └── index.json.sig             # Detached signature envelope
├── schemas/
│   └── index-v1.json              # JSON schema for index.json
├── scripts/
│   ├── validate.py                    # Index + signature validator
│   ├── ci-sign.py                     # CI signer (used by staging/production workflows)
│   ├── provision-production-key.sh    # WSL keypair generator / public-key verifier
│   ├── preflight.py                   # Key/workflow consistency checks (no secrets, no network)
│   ├── scan_for_secrets.py            # CI scan for probable private-key material
│   ├── add-package.py                 # Scaffold a package entry from a spec (computes sha256, never hand-typed)
│   ├── lifecycle-prove.py             # Stage 1 acceptance: prove a package on a clean root + real Nu
│   ├── lint-manifest-index.py         # Fail if numan-plugins manifest Nu range ≠ index (when both known)
│   ├── build-mirror-zip.py            # Build registry-hosted mirror zips from git tags/commits
│   ├── sync-intake-candidates.py      # Regenerate intake-candidates.md from state + gh
│   └── render_catalog_compat.py       # Regenerate docs/catalog-compat.md from index.json
├── tools/
│   └── numan-parser-check/             # Pinned check using Numan's production registry parser
└── .github/workflows/
    ├── staging.yml                # Deploy staging index with ephemeral key
    ├── production.yml             # Deploy production index from protected environment
    └── repo-safety.yml            # Secret scan, preflight, Numan parser, manifest↔index Nu lint
```

## Schema

The registry index is JSON with a required top-level `schema_version` of `1`. The canonical JSON form (sorted object keys, compact encoding, no whitespace) is what is signed and digested. See `schemas/index-v1.json` and the Numan source `src/core/official_registry.rs` for the exact canonicalization rules.

## Signing

The detached signature file `registry/index.json.sig` is a JSON envelope:

```json
{
  "key_id": "official-YYYY-MM",
  "algorithm": "ed25519",
  "signature": "base64..."
}
```

The `signature` value is an Ed25519 signature over the **canonical JSON bytes** of `registry/index.json`. The SHA-256 of those canonical bytes is the `index_sha256` that Numan clients record in their lockfiles.

## Key management

The registry private key is **never** committed, printed, or handled by coding agents. See `docs/key-provisioning.md` for the manual, WSL-first maintainer process, and `docs/production-cutover-checklist.md` for the original cutover runbook. For an active incident, follow `docs/incident-response.md`; it covers yanks, compromised artifacts, index rollback, key exposure, and user remediation. `scripts/provision-production-key.sh` generates the keypair locally and never prints the private key.

## Environments

- **Build validation**: every PR runs secret scan, preflight, schema and parser
  checks, script tests on Windows and Ubuntu, and manifest/index linting. It has
  read-only permissions and no production secret access.
- **Staging**: the default branch is signed with an ephemeral CI key after a
  read-only validation job; only the separate staging publication job receives
  `contents: write`. Staging does not assert production trust.
- **Production signing**: manual dispatch first reruns all no-secret validation,
  including artifact digests. Only after it succeeds can the protected
  `production` environment expose `NUMAN_REGISTRY_PRIVATE_KEY` to the signing
  and publication job.

## Validation

```bash
python scripts/validate.py --index registry/index.json --sig registry/index.json.sig --pub keys/official.pub
```

CI validates the JSON schema, verifies the signed production candidate, downloads and verifies artifact digests for non-fixture entries, and parses the catalog with a pinned revision of Numan's production Rust registry parser.

For the remaining registry intake, catalog growth, and production publication
plan, see [docs/roadmap.md](docs/roadmap.md).

## Intake prove (Stage 1)

For an activatable package without evidence yet, use `add-package.py
--provisional --write` and stage that candidate. Staging permits an omitted
`verified_with`; production does not. After lifecycle-prove succeeds, add the
exact compatible Nu version(s) to `verified_with`, rerun intake without
`--provisional`, and only then promote the package. Prove the staged package on
a clean root with a real Nu that matches its constraint:

```bash
python scripts/lifecycle-prove.py --package owner/name --numan /path/to/numan --nu /path/to/nu
```

See [docs/lifecycle-prove.md](docs/lifecycle-prove.md).
Successful lifecycle evidence is mandatory before promoting any activatable
package to production; staging and build validation do not replace it. The
signed version entry's `verified_with` list records the Nu versions with a
successful real-Nu lifecycle proof. Each value is an exact `MAJOR.MINOR.PATCH`
version satisfying `nu_version`; the intake PR carries the command, OS, package
version, and detailed result.

## Security

Report vulnerabilities and see the trust summary in [SECURITY.md](SECURITY.md).
Operational yank, rollback, and user-remediation procedures are in
[docs/incident-response.md](docs/incident-response.md).

## Operations

- [Security policy](SECURITY.md)
- [Incident response and user remediation](docs/incident-response.md)
- [Production cutover and key-exposure runbook](docs/production-cutover-checklist.md)
- [Signing-key rotation checklist](docs/key-rotation-checklist.md)
