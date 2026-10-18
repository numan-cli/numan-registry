# Numan Registry Roadmap

**Status date:** 2026-10-18

**Consolidated plan:** Cross-repo priorities and the 1.0 gate live in
[`numan/docs/plans/consolidated-multi-repo-roadmap.md`](https://github.com/numan-cli/numan/blob/master/docs/plans/consolidated-multi-repo-roadmap.md).
This file keeps registry-local operational detail.

This repository is the source of truth for the signed official Numan registry.
It should grow through small, evidenced catalog changes, not broad hand-written
JSON edits.

## Current Baseline

- Production registry publication is live through the protected
  `Production registry` workflow.
- Source-tree `registry/index.json.sig` remains a placeholder by design;
  production signing happens in the protected workflow.
- Committed production candidate: **56** packages (34 plugins, 10 modules, 6 completions, 6 scripts).
  Public CDN updates after production signing/publish.
  Human overview: [`docs/catalog-compat.md`](catalog-compat.md) (regenerated from
  `registry/index.json`). Latest-version Nu bands: **26** on **0.114.x**, plus
  older minors and `*` / install-only entries (see catalog-compat summary).
- Intake tooling scaffolds entries from specs, computes artifact hashes,
  validates schemas, scans secrets, runs preflight checks, parses the catalog
  with the production Numan parser, and lints Nu constraints against
  `numan-plugins/manifest.json`.
- Stage 1 lifecycle evidence is mandatory for activatable package promotion.
- Nine previously provisional versions now have real Windows x86_64 lifecycle
  evidence, with all their published artifact digests verified. Six failed
  candidates remain in `registry/provisional.json`, merged into staging only.
  See [the recorded results](evidence/2026-10-18-lifecycle/summary.json).
- Stage 2 package lint + PR evidence checklist landed in
  [PR #31](https://github.com/numan-cli/numan-registry/pull/31).
- Intake Stages 3–6 landed in
  [PR #37](https://github.com/numan-cli/numan-registry/pull/37).
- Wave 1 and Wave 2 CI-built Nu 0.114 plugins are in production.
- Wave 3A install-only script mirrors and Wave 3B completion mirrors are in
  the committed index (2026-08-06/07): `SuaveIV/nu_script_gh_status`,
  `SuaveIV/nu_script_hnews`, `Sanceilaks/nufetch`, `KamilKleina/git-aliases`,
  plus cargo / npm / make / winget completion splits. See the intake changelog
  in [`intake-state.json`](intake-state.json).
- The live candidate list is
  [`docs/intake-candidates.md`](intake-candidates.md).

## Highest Priority: Grow Catalog Depth For 1.0

Continue promoting demand-ranked plugins from
[`numan-plugins/docs/backlog.json`](https://github.com/numan-cli/numan-plugins/blob/main/docs/backlog.json)
through build → spec → intake → lifecycle-prove → production.

Keep growing non-plugin install-only mirrors (scripts / completions / modules)
where they improve first-use demos. Track outreach for mirrored packages in
[`upstream-release-outreach.md`](upstream-release-outreach.md).

Keep multi-OS coverage honest: prefer packages with Linux + Windows + macOS
targets when choosing the next plugin wave.

## Catalog Lists (Do Not Duplicate By Hand)

| List | Role |
|------|------|
| `registry/index.json` | Signed source of truth |
| [`catalog-compat.md`](catalog-compat.md) | Master package × Nu overview (generated) |
| [`intake-state.json`](intake-state.json) / [`intake-candidates.md`](intake-candidates.md) | Intake pipeline status |
| `numan-plugins/manifest.json` | CI-built plugins currently built |
| `numan-plugins/docs/backlog.json` | Demand-ranked plugin candidates |

Refresh after index changes:

```bash
python scripts/render_catalog_compat.py
python scripts/sync-intake-candidates.py   # needs gh for PR/outreach columns
```

## Ongoing Ops

- [ ] Keep every live entry tied to provenance: upstream URL, source revision,
  asset URL, hashes, Nu constraints, targets, package type.
- [ ] Track outreach in [`upstream-release-outreach.md`](upstream-release-outreach.md).
- [ ] Revisit blocked packages when upstreams add archives, Nu pins, or platforms.
- [ ] Never mix catalog expansion with workflow/signing refactors unless the
  catalog change depends on the safety change.
- [ ] Never treat the source-tree placeholder signature as production evidence.

## 1.0 Contribution (Registry Slice)

Registry is healthy for 1.0 when routine additions are spec-driven, every
activatable package has lifecycle evidence or a documented exception, mirrors
and outreach status are clear, and multi-OS coverage in the live catalog is
meaningful for first-use demos. See the unified gate in the consolidated plan.
