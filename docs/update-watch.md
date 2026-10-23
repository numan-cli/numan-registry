# Indexed-package update watch

Nightly rails for packages that are **already indexed**. New-package
intake keeps using the Stage 3-6 pipeline (`discover.py` →
`gen_candidate.py` → `validate_candidate.py` → `open_intake_pr.py`).
This loop answers a different question: did an upstream move, or did a
new Nushell minor leave an indexed entry behind?

## The two hit kinds

- **Type A — upstream release:** the indexed `repo` has a newer stable
  GitHub release than the indexed version. The issue carries the tag,
  the release URL, and the asset list so a spec can be drafted without
  hunting for URLs.
- **Type B — Nu gap:** the indexed version's `nu_version` excludes the
  target Nu in `docs/watch-target-nu.json` and `verified_with` does not
  list it yet. Same artifact, new runtime: re-prove, then append.

## Verdicts

`scripts/watch_indexed.py` attaches one verdict per hit:

- `auto-merge-eligible`: module/script/completion minor-or-patch bump,
  or a Nu gap on the same artifact, with no provisional tier.
- `needs-review`: plugins (rebuild via `numan-plugins` first), major
  bumps, unparsable versions, and anything provisional.

Eligible merges only when lifecycle proof passed on **both** Linux and
Windows. Everything else stays human-gated: upstream hits get a tracking
issue, and anything unproven lives only in the uploaded report.

## What runs automatically

1. `watch-indexed-updates.yml` detects (Ubuntu), proves nu-gap hits
   (`lifecycle-prove.py` on Linux and Windows), then opens one
   `verified_with` PR and enables auto-merge when every package on it
   was eligible and green.
2. Upstream-tag hits open one tracking issue per package with the exact
   five promotion commands. Maintainers run intake; the bot never writes
   `registry/index.json` for these.
3. Production signing is untouched. It stays human-gated in
   `production.yml` as before.

## Nu-gap reconciliation

Appending `verified_with` alone fails validation when the new Nu sits
outside the indexed `nu_version` constraint, so the lane reconciles the
two: when the constraint is a single `<M.m.0`-style upper bound exactly
one minor behind the target, the PR widens it by that minor (backed by
the passing proof) and appends the evidence. Anything bigger, any other
shape, or any changed artifact bytes refuses and stays human-gated.

## Maintainer overrides

- Tag a package `watch-off` to silence it (archived/abandoned upstream).
- Bump `docs/watch-target-nu.json` when a new Nushell minor lands; the
  next run queues every entry that excludes it.
- `workflow_dispatch` accepts `target_nu` and `packages` to scope a live
  run, plus `dry_run: true` for detect-only (skips proof, PRs, issues).
