# Numan Registry Development Guide

This document details the CI tooling, local verification workflows, and environment gotchas for `numan-registry`.

## Dependencies

- **Python 3.12**: Core runtime matching CI.
- **Third-Party Python Packages**: `cryptography`, `jsonschema`, and `PyYAML` (installed via `python3 -m pip install --user cryptography jsonschema PyYAML==6.0.3`). `PyYAML` is required by `scripts/check_workflows.py`.
- **CI Test Tooling**: `coverage` (e.g. `coverage==7.15.4`) used in `repo-safety.yml` for statement-coverage reports.

## CI Validation Suite

- `python3 scripts/scan_for_secrets.py` — Scans git-tracked files for private key leaks.
- `python3 scripts/preflight.py` — Runs key and workflow consistency checks.
- `python3 scripts/check_workflows.py` — Strict YAML parse of every tracked workflow plus duplicate-key detection.
- `python3 scripts/validate.py --index registry/index.json --sig registry/index.json.sig --pub keys/official.pub` — Validates schema, canonical JSON, and Ed25519 signature. Use `--skip-artifacts` to skip network artifact-digest verification.
- `cargo run --locked --manifest-path tools/numan-parser-check/Cargo.toml -- registry/index.json` — Parses catalog using Numan's Rust parser.
- `python3 scripts/lint-manifest-index.py --index registry/index.json --manifest <numan-plugins/manifest.json>` — Stage 2 gate checking active plugin version agreement.

## Local Sign & Verify Workflows

- **Production Placeholder**: Committed `registry/index.json.sig` contains a `PLACEHOLDER` because production signing is performed during deployment.
- **Local Verification**: Generate an ephemeral Ed25519 keypair, sign with `scripts/ci-sign.py`, and validate using `scripts/validate.py` pointing `--sig` and `--pub` at temp files.
- **Artifact Hashes**: `scripts/add-package.py` downloads artifacts to compute SHA256 hashes (requires network).
- **Lifecycle Proving**: `scripts/lifecycle-prove.py` requires network and `numan` + `nu` binaries on `PATH`. See [`docs/lifecycle-prove.md`](lifecycle-prove.md).
