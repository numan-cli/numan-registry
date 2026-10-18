# Numan Registry Development Guide

This document details the CI tooling, local verification workflows, and environment gotchas for `numan-registry`.

## Dependencies

- **Python 3.12**: Core runtime matching CI.
- **Third-Party Python Packages**: `cryptography` and `jsonschema` (installed via `python3 -m pip install --user cryptography jsonschema`).
- **CI Test Tooling**: `coverage` (e.g. `coverage==7.15.4`) used in `repo-safety.yml` for statement-coverage reports.
- **Node.js 22+**: Runs dependency-free registry browser logic tests with `node --test scripts/test_catalog.cjs`. Python 3 must also be on PATH as `python3` for constraint parity tests (or set `PYTHON` to its executable).

## Registry Website

The production and staging workflows publish `registry/` as static files. The site reads its sibling `index.json`; it never substitutes the source-tree catalog for the endpoint catalog. Package descriptions, targets, version history, provenance, and lifecycle-tested Nu versions come from that index. Only versions with a supported activation path receive activation commands. Untargeted archives are explicitly labelled as requiring upstream platform checks.

Preview with `python -m http.server 4173 --bind 127.0.0.1 --directory registry`, then open `http://127.0.0.1:4173/`. Test search, package types, exact Nu input, target selection, matching-only mode, empty-result reset, package/version links, browser back, and copy commands. Check a narrow viewport and keyboard focus as well. Filters live in URL query parameters; package and version selection live in the fragment.

`scripts/write_site_metadata.py` writes public, unsigned `publication.json` during publication builds. It records the source SHA, build time, and staging/production environment. It does not alter the signed index or assert deployment success. Local previews and older publications show an explicit metadata-unavailable message. Never generate or commit a replacement for the source-tree placeholder signature.

Catalog updates remain a separate intake task: do not widen Nu ranges or add platform targets to make browser filters pass. Follow the artifact and lifecycle proof requirements before promoting new versions. The website can ship through the existing protected production workflow after review; a local preview is not a production deployment.

`registry/index.json` contains production candidates that meet the evidence gate. Failed or unproved activatable candidates live in `registry/provisional.json`. The staging workflow merges both with `python scripts/prepare-staging.py --output <temporary-path>` before ephemeral signing. Production continues signing only `registry/index.json`; no unsigned fallback or production evidence exception is introduced.

## CI Validation Suite

- `python3 scripts/scan_for_secrets.py` — Scans git-tracked files for private key leaks.
- `python3 scripts/preflight.py` — Runs key and workflow consistency checks.
- `python3 scripts/validate.py --index registry/index.json --sig registry/index.json.sig --pub keys/official.pub` — Validates schema, canonical JSON, and Ed25519 signature. Use `--skip-artifacts` to skip network artifact-digest verification.
- `cargo run --locked --manifest-path tools/numan-parser-check/Cargo.toml -- registry/index.json` — Parses catalog using Numan's Rust parser.
- `python3 scripts/lint-manifest-index.py --index registry/index.json --manifest <numan-plugins/manifest.json>` — Stage 2 gate checking active plugin version agreement.

## Local Sign & Verify Workflows

- **Production Placeholder**: Committed `registry/index.json.sig` contains a `PLACEHOLDER` because production signing is performed during deployment.
- **Local Verification**: Generate an ephemeral Ed25519 keypair, sign with `scripts/ci-sign.py`, and validate using `scripts/validate.py` pointing `--sig` and `--pub` at temp files.
- **Artifact Hashes**: `scripts/add-package.py` downloads artifacts to compute SHA256 hashes (requires network).
- **Lifecycle Proving**: `scripts/lifecycle-prove.py` requires network and `numan` + `nu` binaries on `PATH`. See [`docs/lifecycle-prove.md`](lifecycle-prove.md).
