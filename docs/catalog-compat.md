# Official registry catalog compatibility

_Auto-generated from `registry/index.json`. Do not hand-edit._

Generated: `2026-10-24T06:06:33Z` · Index `updated_at`: `2026-10-24T06:06:33Z` · `registry_revision`: `seed-2026-07-02`

This is the **master list** of packages in the committed `registry/index.json` (in-tree; the public CDN updates after production signing/publish) and the Nu constraint on each package's **latest** version. For demand-ranked *plugin candidates* not yet in the registry, see [`numan-plugins/docs/backlog.json`](https://github.com/numan-cli/numan-plugins/blob/main/docs/backlog.json). For intake workflow status, see [`intake-candidates.md`](intake-candidates.md).

## Summary

- **68** packages total
- By type: `completion` 15, `module` 10, `plugin` 37, `script` 6
- Latest version Nu band: `0.114` 14, `0.113` 3, `other` 28, `*` 23

Nu band is a coarse label from the constraint **lower bound** (`>=0.114` / `>0.113` → `0.114` / `0.113`, etc.; else `*` or `other`). Exact constraints are in the table and in the signed index.

## Catalog (latest version per package)

| Package | Type | Latest | Nu constraint | Band | Targets | Provenance | Versions |
|---------|------|--------|---------------|------|---------|------------|----------|
| `abusch/nu_plugin_semver` | plugin | 0.11.17 | `>=0.113.0 <0.114.0` | 0.113 | mac,linux,win | upstream | 1 |
| `alex-kattathra-johnson/nu_plugin_ws` | plugin | 1.0.6 | `>=0.107.0 <0.108.0` | other | mac,win,linux | upstream | 1 |
| `amtoine/nu-git-manager` | module | 0.8.0 | `>=0.92.0` | other | — | mirror | 1 |
| `amtoine/nu-git-manager-sugar` | module | 0.7.0 | `>=0.92.0` | other | — | mirror | 1 |
| `ArmoredPony/nu-digital-rain` | script | 0.1.0-6602c6a | `>=0.114.0 <0.115.0` | 0.114 | — | mirror | 1 |
| `b4nst/nu_plugin_format_pcap` | plugin | 0.1.0 | `>=0.101.0 <0.102.0` | other | mac,linux,win | upstream | 1 |
| `cptpiepmatz/nu_plugin_highlight` | plugin | 1.4.17 | `>=0.115.0 <0.116.0` | other | mac,linux,win | ci-built | 3 |
| `dead10ck/nu_plugin_dns` | plugin | 4.0.10 | `>=0.113.0 <0.114.0` | 0.113 | mac,linux | ci-built | 1 |
| `drbrain/nu_plugin_prometheus` | plugin | 0.13.0 | `>=0.115.0 <0.116.0` | other | mac,win,linux | ci-built | 2 |
| `Euphrasiologist/nu_plugin_bio` | plugin | 0.0.0-snapshot.20260816.49ab341 | `>=0.104.0 <0.105.0` | other | mac,linux,win | ci-built | 1 |
| `Euphrasiologist/nu_plugin_plot` | plugin | 0.0.0-snapshot.20260816.5a1ca2a | `>=0.105.0 <0.106.0` | other | linux,win | ci-built | 1 |
| `fdncred/nu_plugin_emoji` | plugin | 0.25.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `fdncred/nu_plugin_file` | plugin | 0.28.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 3 |
| `fdncred/nu_plugin_json_path` | plugin | 0.26.1 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `fdncred/nu_plugin_jwalk` | plugin | 0.26.0 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `fdncred/nu_plugin_parquet` | plugin | 0.26.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `fdncred/nu_plugin_query_git` | plugin | 0.26.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `fdncred/nu_plugin_regex` | plugin | 0.25.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 3 |
| `fdncred/nu_plugin_strutils` | plugin | 0.25.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `fennewald/nu_plugin_net` | plugin | 1.9.0 | `>=0.103.0 <0.104.0` | other | mac,linux | upstream | 1 |
| `fj0r/ai.nu` | module | 0.1.0-2e71068 | `>=0.114.0 <0.115.0` | 0.114 | — | mirror | 1 |
| `fj0r/git.nu` | module | 0.1.0-2241050 | `>=0.114.0 <0.116.0` | 0.114 | — | mirror | 1 |
| `FMotalleb/nu_plugin_desktop_notifications` | plugin | 0.116.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `FMotalleb/nu_plugin_image` | plugin | 0.116.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `FMotalleb/nu_plugin_port_extension` | plugin | 0.116.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 3 |
| `fnuttens/nu_plugin_hmac` | plugin | 0.27.0 | `>=0.113.0 <0.114.0` | 0.113 | mac,linux,win | ci-built | 1 |
| `galuszkak/nu_plugin_bigquery` | plugin | 0.3.0 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `idanarye/nu_plugin_handlebars` | plugin | 0.3.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 1 |
| `idanarye/nu_plugin_skim` | plugin | 0.31.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `JosephTLyons/nu_plugin_units` | plugin | 0.1.9 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 1 |
| `kaathewisegit/nu_plugin_endecode` | plugin | 0.0.0-snapshot.20261019.2fe5276 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `KamilKleina/git-aliases` | script | 0.1.0-109cc61 | `*` | * | — | mirror | 1 |
| `kik4444/nu_plugin_mime` | plugin | 0.0.0-snapshot.20260816.8e5872a | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `Kissaki/nu_plugin_bson` | plugin | 26.1160.0 | `>=0.116.0 <0.117.0` | other | mac,linux,win | ci-built | 2 |
| `lassoColombo/conventional-commits` | module | 0.1.0-44dc459 | `>=0.114.0 <0.115.0` | 0.114 | — | mirror | 1 |
| `lizclipse/nu_plugin_ulid` | plugin | 0.23.0 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `nushell-prophet/dotnu` | module | 0.0.18 | `*` | * | — | mirror | 1 |
| `nushell-prophet/numd` | module | 0.5.0 | `*` | * | — | mirror | 2 |
| `nushell-works/nu_plugin_nw_ulid` | plugin | 0.2.0 | `>=0.111.0 <0.112.0` | other | mac,linux,win | upstream | 1 |
| `nushell/aws-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/bat-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/cargo-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `nushell/custom-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `nushell/docker-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/dotnet-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/gh-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/git-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `nushell/make-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `nushell/npm-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `nushell/nu-hooks` | module | 0.1.0 | `*` | * | — | mirror | 1 |
| `nushell/pnpm-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/rg-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/ssh-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/uv-completions` | completion | 0.1.0-44f8f25 | `*` | * | — | mirror | 1 |
| `nushell/winget-completions` | completion | 0.1.0-f04cb44 | `*` | * | — | mirror | 1 |
| `oderwat/nu_plugin_logfmt` | plugin | 0.0.0-snapshot.20260816.892c4f9 | `>=0.101.0 <0.102.0` | other | mac,linux,win | ci-built | 1 |
| `rhino-linux/nu_plugin_nutext` | plugin | 0.6.2 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `Sanceilaks/nufetch` | script | 0.1.0-15e0645 | `*` | * | — | mirror | 1 |
| `SuaveIV/nu_plugin_audio` | plugin | 0.2.10 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | upstream | 2 |
| `SuaveIV/nu_script_gh_status` | script | 0.1.0-81756dc | `*` | * | — | mirror | 1 |
| `SuaveIV/nu_script_hnews` | script | 0.1.0-6cd8aef | `>=0.97.0` | other | — | mirror | 1 |
| `SuaveIV/nu_script_wttr` | script | 0.1.0-main | `*` | * | — | mirror | 1 |
| `tesujimath/bash-env-nushell` | module | 0.19.0 | `*` | * | — | upstream | 1 |
| `Trivernis/nu-plugin-dialog` | plugin | 0.1.0 | `>=0.107.0 <0.108.0` | other | mac,win,linux | upstream | 1 |
| `vyadh/nutest` | module | 1.2.0 | `>=0.114.0` | 0.114 | — | upstream | 2 |
| `WindSoilder/nu_plugin_mongo` | plugin | 0.0.0-snapshot.20260816.47854d9 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `Yethal/nu_plugin_hcl` | plugin | 0.114.1 | `>=0.114.0 <0.115.0` | 0.114 | mac,linux,win | ci-built | 1 |
| `yybit/nu_plugin_x509` | plugin | 0.0.0-snapshot.20260816.15518dd | `>=0.109.0 <0.110.0` | other | mac,linux,win | ci-built | 1 |

## How to refresh

```bash
python scripts/render_catalog_compat.py
python scripts/render_catalog_compat.py --check   # CI drift gate
```

Run after every index-changing PR (`add-package.py --write`, mirrors, Nu constraint edits). Commit the regenerated markdown with the index.

## Related lists

| List | Role |
|------|------|
| `registry/index.json` | Signed source of truth (all versions + hashes) |
| `docs/catalog-compat.md` | This file: human catalog × Nu overview |
| `docs/intake-state.json` / `intake-candidates.md` | Intake pipeline status |
| `numan-plugins/manifest.json` | CI-built plugins currently built |
| `numan-plugins/docs/backlog.json` | Demand-ranked plugin candidates |
