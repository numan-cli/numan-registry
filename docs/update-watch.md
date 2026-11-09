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

- `auto-merge-eligible`:
  - Module/script/completion minor-or-patch bump (non-provisional).
  - Upstream-asset plugin minor-or-patch bump with full target parity.
  - CI-built plugin minor-or-patch bump whose rebuilt release (`{name}-{version}`) is already published on `numan-cli/numan-plugins` with full target parity.
  - Nu gap on the same artifact, with no provisional tier.
- `needs-review`: CI-built plugins awaiting `numan-plugins` rebuild, plugins missing indexed target assets, major bumps, unparsable versions, and anything provisional.

Eligible merges only when lifecycle proof passed on **both** Linux and
Windows. Everything else stays human-gated: unproven or `needs-review`
upstream hits get a tracking issue, and anything unproven in the Nu-gap
lane lives only in the uploaded report.

## What runs automatically

1. `watch-indexed-updates.yml` detects (Ubuntu), proves nu-gap hits
   (`lifecycle-prove.py` on Linux and Windows), then opens one
   `verified_with` PR and enables auto-merge when every package on it
   was eligible and green.
2. Eligible Type A upstream hits are synthesized into candidate specs via
   `scripts/prepare_upstream_candidate.py`, proven on both Linux and
   Windows via `lifecycle-prove.py`, and opened as auto-merging intake
   PRs via `scripts/open_intake_pr.py`.
3. Upstream-tag hits that are `needs-review` or fail dual-OS proof open
   one tracking issue per package with the exact five promotion commands.
4. `production.yml` starts automatically once `main` updates
   `registry/index.json`. Production signing requires reviewer approval,
   then materializes only proven entries
   (stripping any `provisional` entries before signing).

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
- The PR lanes need a repo-scoped PAT in the `WATCH_PAT` actions secret:
  PRs opened with `GITHUB_TOKEN` do not trigger checks, so auto-merge
  would stall. Without `WATCH_PAT`, the Nu-gap PR lane (`open-pr`) still
  opens the PR for human merge, whereas the upstream intake lane
  (`open-upstream-prs`) skips automated PR creation and falls back to
  `upstream-issues` filing tracking issues.
