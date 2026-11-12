# Lifecycle proof backlog: versions with missing Unix target proofs

**Snapshot:** generated from the working-tree [registry/index.json](../registry/index.json) at `2026-11-12T14:03:58Z` (registry revision `seed-2026-07-02`). This is a planning snapshot, not a production-signed catalog.

**Scope:** a version is included when it has at least one Windows proof and at least one Linux or macOS artifact target without a passing proof. This deliberately excludes proof-less versions, versions with no Windows proof, and Windows-only packages with no Unix target.

**Counts:** **55** versions across **35** packages; **35** are each package's latest version and **20** are older versions. **54** have a passed Windows proof; **1** has a failed Windows proof and is yanked. **149** Linux/macOS target proofs are missing in total: **80** are actionable Linux targets, **60** are macOS targets blocked by this host, and **9** belong to held rows.

**Host-blocked:** macOS targets (`macos/aarch64`, `macos/x86_64`) cannot be executed in this Windows/WSL/Docker environment because no macOS runner is available. They remain open and are marked in the tables below; they are not unattempted Linux work.

## How to read the ranking

- **P0** - latest version, passing Windows proof, Nu lower bound **0.114 or newer**. Start here: these are the versions users resolve on current Nu.
- **P1** - latest version and passing Windows proof, but the package requires an older Nu branch. High-demand packages in this group are still worth proving when their Nu branch is supported.
- **P2** - historical version, passing Windows proof, Nu **0.114 or newer**. These preserve coverage for users pinned to an older Nu 0.114 package.
- **P3** - historical version on Nu **0.113 or older**. Lowest current impact.
- **Held** - credential-gated or terminal evidence. Do not mix these into the normal proof batch.

Within P0-P2, rows are ordered by known upstream demand (GitHub stars from `numan-plugins/docs/backlog.json`), then fewer missing target proofs. P3 is ordered by effort (fewest missing targets) first. A dash means the package was not present in the demand backlog; it is not a zero-star claim.

All rows are plugins. `Missing Linux` lists the Linux targets still open; `Host-blocked` lists the macOS targets that this host cannot run.

## Suggested first wave

The first five P0 rows with open Linux targets are a practical next batch: **5 Linux target proofs**. Run one wrapper invocation per package/version with the exact missing targets listed below.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Stars |
|---:|---|---|---|---|---|---:|
| 2 | `idanarye/nu_plugin_skim` | `0.31.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 85 |
| 3 | `cptpiepmatz/nu_plugin_highlight` | `1.4.17` | `0.115.1` | linux/aarch64 | macos/aarch64 | 82 |
| 4 | `fdncred/nu_plugin_regex` | `0.25.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 66 |
| 5 | `fdncred/nu_plugin_file` | `0.28.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 54 |
| 6 | `FMotalleb/nu_plugin_desktop_notifications` | `0.116.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 53 |

## P0 - current versions (start here)

**25** versions.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Stars | Windows |
|---:|---|---|---|---|---|---|---:|---|
| 1 | `wangjiawen2013/nu_plugin_charton` | `0.9.0` | `0.116.1` | — | macos/aarch64 | 448 | passed |
| 2 | `idanarye/nu_plugin_skim` | `0.31.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 85 | passed |
| 3 | `cptpiepmatz/nu_plugin_highlight` | `1.4.17` | `0.115.1` | linux/aarch64 | macos/aarch64 | 82 | passed |
| 4 | `fdncred/nu_plugin_regex` | `0.25.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 66 | passed |
| 5 | `fdncred/nu_plugin_file` | `0.28.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 54 | passed |
| 6 | `FMotalleb/nu_plugin_desktop_notifications` | `0.116.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 53 | passed |
| 7 | `fdncred/nu_plugin_emoji` | `0.25.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 27 | passed |
| 8 | `fdncred/nu_plugin_json_path` | `0.26.1` | `0.116.1` | linux/aarch64 | macos/aarch64 | 22 | passed |
| 9 | `FMotalleb/nu_plugin_image` | `0.116.0` | `0.116.1` | linux/aarch64 | macos/aarch64, macos/x86_64 | 22 | passed |
| 10 | `fdncred/nu_plugin_parquet` | `0.26.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 18 | passed |
| 11 | `drbrain/nu_plugin_prometheus` | `0.13.0` | `0.115.1` | — | macos/aarch64, macos/x86_64 | 16 | passed |
| 12 | `FMotalleb/nu_plugin_port_extension` | `0.116.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 16 | passed |
| 13 | `fdncred/nu_plugin_jwalk` | `0.26.0` | `0.114.1` | linux/aarch64 | macos/aarch64 | 9 | passed |
| 14 | `fdncred/nu_plugin_query_git` | `0.26.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 8 | passed |
| 15 | `WindSoilder/nu_plugin_mongo` | `0.0.0-snapshot.20260816.47854d9` | `0.114.1` | linux/aarch64 | macos/aarch64 | 8 | passed |
| 16 | `kik4444/nu_plugin_mime` | `0.0.0-snapshot.20260816.8e5872a` | `0.114.1` | linux/aarch64 | macos/aarch64 | 6 | passed |
| 17 | `lizclipse/nu_plugin_ulid` | `0.23.0` | `0.114.1` | linux/aarch64 | macos/aarch64 | 6 | passed |
| 18 | `fdncred/nu_plugin_strutils` | `0.25.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 5 | passed |
| 19 | `Yethal/nu_plugin_hcl` | `0.114.1` | `0.114.1` | linux/aarch64 | macos/aarch64 | 4 | passed |
| 20 | `idanarye/nu_plugin_handlebars` | `0.3.0` | `0.116.1` | linux/aarch64 | macos/aarch64 | 1 | passed |
| 21 | `rhino-linux/nu_plugin_nutext` | `0.6.2` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 1 | passed |
| 22 | `kaathewisegit/nu_plugin_endecode` | `0.0.0-snapshot.20261019.2fe5276` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 0 | passed |
| 23 | `Kissaki/nu_plugin_bson` | `26.1160.0` | `0.116.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 0 | passed |
| 24 | `tonythethompson/nu_plugin_qr_maker` | `1.2.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 0 | passed |
| 25 | `SuaveIV/nu_plugin_audio` | `0.2.13` | `0.116.1` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | 0 | passed |

## P1 - latest versions on older Nu branches

**8** versions.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Stars | Windows |
|---:|---|---|---|---|---|---|---:|---|
| 26 | `Euphrasiologist/nu_plugin_plot` | `0.0.0-snapshot.20260816.5a1ca2a` | `0.105.0` | linux/x86_64, linux/aarch64 | — | 71 | passed |
| 27 | `Euphrasiologist/nu_plugin_bio` | `0.0.0-snapshot.20260816.49ab341` | `0.104.0` | linux/x86_64, linux/aarch64 | macos/aarch64 | 31 | passed |
| 28 | `oderwat/nu_plugin_logfmt` | `0.0.0-snapshot.20260816.892c4f9` | `0.101.0` | linux/x86_64, linux/aarch64 | macos/aarch64 | 5 | passed |
| 29 | `yybit/nu_plugin_x509` | `0.0.0-snapshot.20260816.15518dd` | `0.109.0` | linux/x86_64, linux/aarch64 | macos/aarch64 | 5 | passed |
| 30 | `fnuttens/nu_plugin_hmac` | `0.27.0` | `0.113.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 0 | passed |
| 31 | `abusch/nu_plugin_semver` | `0.11.17` | `0.113.1` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | — | passed |
| 32 | `b4nst/nu_plugin_format_pcap` | `0.1.0` | `0.101.0` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | — | passed |
| 33 | `nushell-works/nu_plugin_nw_ulid` | `0.2.0` | `0.111.0` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | — | passed |

## P2 - historical versions on Nu 0.114+

**14** versions.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Stars | Windows |
|---:|---|---|---|---|---|---|---:|---|
| 34 | `idanarye/nu_plugin_skim` | `0.29.1` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 85 | passed |
| 35 | `cptpiepmatz/nu_plugin_highlight` | `1.4.16` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 82 | passed |
| 36 | `fdncred/nu_plugin_regex` | `0.23.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 66 | passed |
| 37 | `fdncred/nu_plugin_file` | `0.26.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 54 | passed |
| 38 | `FMotalleb/nu_plugin_desktop_notifications` | `0.114.1` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 53 | passed |
| 39 | `fdncred/nu_plugin_emoji` | `0.23.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 27 | passed |
| 40 | `fdncred/nu_plugin_json_path` | `0.24.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 22 | passed |
| 41 | `fdncred/nu_plugin_parquet` | `0.24.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 18 | passed |
| 42 | `drbrain/nu_plugin_prometheus` | `0.12.0` | `0.114.1` | linux/x86_64 | macos/aarch64, macos/x86_64 | 16 | passed |
| 43 | `FMotalleb/nu_plugin_port_extension` | `0.114.1` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 16 | passed |
| 44 | `fdncred/nu_plugin_query_git` | `0.24.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 8 | passed |
| 45 | `fdncred/nu_plugin_strutils` | `0.22.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 5 | passed |
| 46 | `Kissaki/nu_plugin_bson` | `26.1140.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 0 | passed |
| 47 | `SuaveIV/nu_plugin_audio` | `0.2.10` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | 0 | passed |

## P3 - historical versions on Nu 0.113 and older

**5** versions.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Stars | Windows |
|---:|---|---|---|---|---|---|---:|---|
| 48 | `SuaveIV/nu_plugin_audio` | `0.2.8` | `0.113.1` | linux/aarch64 | — | 0 | passed |
| 49 | `cptpiepmatz/nu_plugin_highlight` | `1.4.15` | `0.113.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 82 | passed |
| 50 | `fdncred/nu_plugin_regex` | `0.22.0` | `0.113.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | 66 | passed |
| 51 | `FMotalleb/nu_plugin_image` | `0.112.2` | `0.112.2` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | 22 | passed |
| 52 | `FMotalleb/nu_plugin_port_extension` | `0.113.1` | `0.113.1` | linux/x86_64, linux/aarch64 | macos/aarch64, macos/x86_64 | 16 | passed |

## Held - credentials or terminal evidence

**3** versions.

| Rank | Package | Version | Proof Nu | Missing Linux | Host-blocked | Windows | Why held |
|---:|---|---|---|---|---|---|---|
| 53 | `galuszkak/nu_plugin_bigquery` | `0.5.1` | `0.116.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | passed | Requires GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_CLOUD_PROJECT; do not run without a credential-forwarding plan. |
| 54 | `galuszkak/nu_plugin_bigquery` | `0.3.0` | `0.114.1` | linux/x86_64, linux/aarch64 | macos/aarch64 | passed | Requires GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_CLOUD_PROJECT; do not run without a credential-forwarding plan. |
| 55 | `Trivernis/nu-plugin-dialog` | `0.1.0` | `0.107.0` | linux/x86_64 | macos/aarch64, macos/x86_64 | failed | Failed Windows proof and yanked; do not spend Linux/macOS proof time unless the package is reintroduced. |

## Host-blocked targets

The following targets are explicitly blocked by the current host, not by package behavior:

- `macos/aarch64` - no macOS aarch64 runner available.
- `macos/x86_64` - no macOS x86_64 runner available.

Across ready rows this leaves **60** macOS target proofs open.

## Attempted but failed

No attempted target failed in this batch.

## Execution template

Run from the default branch after the proof workflow lands. Replace the package, version, Nu, and target list with one row above; keep the artifact prefixes unique per invocation.

```bash
gh workflow run platform-gap-lifecycle-proof.yml --ref main \
  -f package=owner/name \
  -f package_version=1.2.3 \
  -f nu_version=0.116.1 \
  -f 'targets=["linux/x86_64","linux/aarch64"]' \
  -f artifact_prefix=backlog-owner-name-1.2.3 \
  -f artifact_summary_prefix=backlog-owner-name-1.2.3-proofs
```

The wrapper is a `workflow_dispatch`/`workflow_call` workflow. It must exist on the default branch before manual dispatch; see [lifecycle-prove.md](lifecycle-prove.md). Download the per-target log and `proof.json` plus the collected `proofs.json`/`proofs.md` artifacts, then attach them to the intake evidence rather than treating this planning snapshot as proof.

## Refresh

Recompute the predicate after any index change; do not hand-edit this snapshot. The machine-readable companion is [lifecycle-proof-backlog.json](lifecycle-proof-backlog.json).
