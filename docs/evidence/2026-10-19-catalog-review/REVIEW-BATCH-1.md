# Catalog review batch 1 — production candidate

Reconciles `main` (`be65d58`, 65 packages) against the archived signed
production baseline (`docs/evidence/2026-10-18-production-baseline/`,
44 packages, key `official-2026-07-01`, canonical index sha256
`674c49f971ed1bd4f2dee329e1ba07a648dd12b659176171dfe0009c644eed5c`). Machine-readable detail: `catalog-review-batch-1.json`
in this directory.

Every unpublished difference is classified below. Approving this batch
means approving the production-candidate rule at the end; anything not
explicitly approved is excluded by the provisional filter.

## Summary

| Bucket | Count | Disposition |
| --- | --- | --- |
| Removed from catalog | 0 | Nothing to lose |
| Changed: URL migration only | 37 | Approve as a batch |
| Changed: target expansion + metadata | 2 | Approve per package |
| Added: non-provisional | 12 | Approve per package |
| Added: provisional (`evidence_tier`) | 9 | Excluded mechanically |

## A. URL migration only (37 packages)

Artifact URLs moved from `tonythethompson/*` release hosts to
`numan-cli/*`. Every `sha256` digest is byte-identical between baseline
and `main`; no version, target, constraint, or evidence field changed.
This is the org-transfer rewrite.

Approval note: the migration assumes `numan-cli` release assets are
byte-identical to the old host (sha256 equality is already asserted by
the index). Spot-checking 2 to 3 URLs end-to-end before sign-off is
cheap belt-and-suspenders, not strictly required.

## B. Target expansion + metadata refresh (2 packages)

These entries already pointed at upstream release hosts in production,
so no URL migration applies; the shared `x86_64-pc-windows-msvc`
target is byte-identical.

| Package | Version | New targets | Artifact host |
| --- | --- | --- | --- |
| `abusch/nu_plugin_semver` | 0.11.17 | aarch64-apple-darwin, aarch64-unknown-linux-gnu, x86_64-apple-darwin, x86_64-unknown-linux-gnu | upstream `abusch/nu_plugin_semver` release |
| `Trivernis/nu-plugin-dialog` | 0.1.0 | aarch64-apple-darwin, x86_64-apple-darwin, x86_64-unknown-linux-gnu | upstream `Trivernis/nu-plugin-dialog` release |

Expansions only; no target was removed. The new digests point at
upstream release assets and should be spot-verified before approval.
Both entries also carried description/tags refreshes.

## C. New packages — non-provisional (12)

These carry `stable` or `proven` evidence tiers. Each needs an explicit
keep/exclude decision.

| Package | Type | Version | Evidence | Host |
| --- | --- | --- | --- | --- |
| `fennewald/nu_plugin_net` | plugin | 1.9.0 | stable | upstream `fennewald/nu_plugin_net` |
| `nushell/aws-completions` | completion | 0.1.0-44f8f25 | stable | `numan-cli/numan-registry` mirror |
| `nushell/rg-completions` | completion | 0.1.0-44f8f25 | stable | `numan-cli/numan-registry` mirror |
| `Euphrasiologist/nu_plugin_bio` | plugin | 0.0.0-snapshot.20260816.49ab341 | proven | `numan-cli/numan-plugins` |
| `Euphrasiologist/nu_plugin_plot` | plugin | 0.0.0-snapshot.20260816.5a1ca2a | proven | `numan-cli/numan-plugins` |
| `WindSoilder/nu_plugin_mongo` | plugin | 0.0.0-snapshot.20260816.47854d9 | proven | `numan-cli/numan-plugins` |
| `kik4444/nu_plugin_mime` | plugin | 0.0.0-snapshot.20260816.8e5872a | proven | `numan-cli/numan-plugins` |
| `oderwat/nu_plugin_logfmt` | plugin | 0.0.0-snapshot.20260816.892c4f9 | proven | `numan-cli/numan-plugins` |
| `yybit/nu_plugin_x509` | plugin | 0.0.0-snapshot.20260816.15518dd | proven | `numan-cli/numan-plugins` |
| `fj0r/ai.nu` | module | 0.1.0-2e71068 | proven | `numan-cli/numan-registry` mirror |
| `fj0r/git.nu` | module | 0.1.0-2241050 | proven | `numan-cli/numan-registry` mirror |
| `lassoColombo/conventional-commits` | module | 0.1.0-44dc459 | proven | `numan-cli/numan-registry` mirror |

Snapshot versions (`0.0.0-snapshot.*`) are commit-pinned plugin builds
from `numan-plugins`; `proven` means lifecycle evidence exists for the
recorded Nushell band.

## D. New packages — provisional, excluded mechanically (9)

`evidence_tier: provisional` entries never enter a production
candidate. Listed here only for visibility; no decision needed.

- `ArmoredPony/nu-digital-rain` — Wave 4 script-archive intake
- `galuszkak/nu_plugin_bigquery` — needs live GCP credentials
- `nushell/{bat,docker,dotnet,gh,pnpm,ssh,uv}-completions` — wave-5
  install-only mirrors; lifecycle-prove against real Nu not run

## Proposed production-candidate rule

1. Baseline bytes + all 37 URL-migration diffs (A).
2. Both target-expanded packages (B), after new-target digest
   spot-checks.
3. Each section-C package marked **keep** below.
4. Hard filter: any version with `evidence_tier: provisional` is
   excluded regardless of approval.

## Sign-off

- [ ] Approve bucket A (URL migration, 37 packages)
- [ ] `abusch/nu_plugin_semver` 0.11.17 target expansion
- [ ] `Trivernis/nu-plugin-dialog` 0.1.0 target expansion
- [ ] Section C keep-list (mark each keep/exclude):

| Keep? | Package |
| --- | --- |
| [ ] | `fennewald/nu_plugin_net` |
| [ ] | `nushell/aws-completions` |
| [ ] | `nushell/rg-completions` |
| [ ] | `Euphrasiologist/nu_plugin_bio` |
| [ ] | `Euphrasiologist/nu_plugin_plot` |
| [ ] | `WindSoilder/nu_plugin_mongo` |
| [ ] | `kik4444/nu_plugin_mime` |
| [ ] | `oderwat/nu_plugin_logfmt` |
| [ ] | `yybit/nu_plugin_x509` |
| [ ] | `fj0r/ai.nu` |
| [ ] | `fj0r/git.nu` |
| [ ] | `lassoColombo/conventional-commits` |

After sign-off, the approved candidate is built from `main` minus
provisional entries minus excluded additions, then dispatched through
the protected `production` workflow. Post-deploy verification compares
public index bytes, signature, key id, source commit, and digest
against this batch's records.
