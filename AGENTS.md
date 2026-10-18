# Numan Registry — Official Signed Package Index

Data-only repository containing the signed Numan registry index and Python CI tooling under `scripts/`.

## CI & Validation Commands

```bash
python3 scripts/scan_for_secrets.py       # Secret scanner for private key material
python3 scripts/preflight.py              # Key/workflow consistency checks
python3 scripts/check_workflows.py        # Strict workflow YAML parse + duplicate-key check
python3 scripts/validate.py --index registry/index.json --sig registry/index.json.sig --pub keys/official.pub --skip-artifacts # Schema + signature checks
cargo run --locked --manifest-path tools/numan-parser-check/Cargo.toml -- registry/index.json # Numan Rust parser validation
```

## Key Invariants & Gotchas

1. **Production Signature**: Committed `registry/index.json.sig` uses a `PLACEHOLDER`. Production signing occurs only in CI deployment; GitHub Pages hosts the signed artifact. Never overwrite the placeholder in source control.
2. **Local Signing**: Test sign/verify by generating an ephemeral Ed25519 keypair and signing into a temp directory with `scripts/ci-sign.py`.
3. **Secret Safety**: Never commit private key material (`*.key`, `*.pem`, `*_private_key*`).
4. **Dependencies**: Python 3.12 with `cryptography`, `jsonschema`, and `PyYAML`.

## Reference Documentation

- **PR Review Guidance**: [`REVIEW.md`](REVIEW.md)
- **Development & Local Testing**: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- **Lifecycle Proving**: [`docs/lifecycle-prove.md`](docs/lifecycle-prove.md)
- **Key Provisioning**: [`docs/key-provisioning.md`](docs/key-provisioning.md)
