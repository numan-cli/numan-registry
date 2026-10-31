# Catalog next wave: non-plugin gaps

_Research date: 2026-08-06. Sources: live `docs/catalog-compat.md` (generated 2026-08-05), `numan-plugins/docs/backlog.json` (69 plugins), [awesome-nu](https://github.com/nushell/awesome-nu) README, `nushell/nu_scripts`, `docs/intake-candidates.md`, client install-only rules in `numan/docs/plans/consolidated-multi-repo-roadmap.md`._

_Status refreshed 2026-08-07: Wave 3A + 3B install-only mirrors are live in the registry (see [`intake-candidates.md`](intake-candidates.md))._

## Verdict

The official catalog is **plugin-heavy and script-thin**. Further plugin waves yield diminishing returns: almost every backlog entry that can be CI-built on a supported Nu minor is already `PROMOTED`. The critical adoption gaps for a less experienced user are **scripts, per-tool completions, and a few everyday modules**, delivered as **install-only mirrors** until activation contracts exist.

Do not treat "next wave" as another `numan-plugins` CI batch by default. Prefer registry mirror packages from `nu_scripts` slices and standalone Nu module/script repos.

## Current catalog shape

From the committed index (44 packages):

| Type | Count | Share |
|------|------:|------:|
| plugin | 26 | 59% |
| module | 7 | 16% |
| completion | 6 | 14% |
| script | 5 | 11% |

Notes on non-plugins already present:

- **Modules:** `bash-env-nushell`, `nutest`, `dotnu`, `numd`, `nu-hooks`, `nu-git-manager` (+ sugar; archived upstream).
- **Completions:** `nushell/custom-completions` (whole tree snapshot), `nushell/git-completions` (git slice), plus cargo / npm / make / winget splits (Wave 3B). All install-only mirrors at commit `f04cb44`.
- **Scripts:** `SuaveIV/nu_script_wttr`, `nu_script_gh_status`, `nu_script_hnews`, `Sanceilaks/nufetch`, and `KamilKleina/git-aliases` (all install-only mirrors).

`numan try` starters are still almost all plugins/modules (`skim`, Windows `semver`, `nutest`). Script-shaped installs now exist (`nufetch`, `wttr`), but `try` has no install-only starter path yet — see Wave 3C.

## Plugin backlog is not the bottleneck

`numan-plugins/docs/backlog.json` status mix (69 entries):

| Status | Count | Implication |
|--------|------:|-------------|
| PROMOTED | 19 | Already in registry via CI-built or related path |
| NO_RELEASE | 38 | Needs upstream tags or commit-snapshot policy |
| PRE_0_112 | 10 | Deferred until upstream Nu bump |
| CREDENTIALS | 1 | `galuszkak/nu_plugin_bigquery` (needs cred lifecycle plan) |
| ELIGIBLE | 1 | `SuaveIV/nu_plugin_audio` already live in registry |

Highest-demand **deferred** plugins (outreach / wait, not next registry PR):

1. `FMotalleb/nu_plugin_clipboard` (85★, pinned ~0.110)
2. `Euphrasiologist/nu_plugin_plot` (71★, no tags)
3. `yybit/nu_plugin_compress` (42★, pinned ~0.103)
4. `devyn/nu_plugin_dbus` (34★, pinned ~0.101, not Windows)

Secondary registry polish (not gap-filling): multi-OS `abusch/nu_plugin_semver` intake; `fennewald/nu_plugin_net` when Windows assets exist.

## Gap analysis vs awesome-nu / nu_scripts

### Scripts (largest gap)

awesome-nu lists ~50 Script entries. Catalog has **1**. High-value install-only candidates that fit the existing `build-mirror-zip.py` path:

| Priority | Candidate | Why | Packaging notes |
|----------|-----------|-----|-----------------|
| ✅ P0 | `SuaveIV/nu_script_gh_status` | Shipped 2026-08-06 (`@0.1.0-81756dc`); same author/pattern as live `nu_script_wttr` | Mirror whole repo |
| ✅ P0 | `SuaveIV/nu_script_hnews` | Shipped 2026-08-06 (`@0.1.0-6cd8aef`); browser-less HN demo | Mirror whole repo |
| ✅ P0 | `Sanceilaks/nufetch` | Shipped 2026-08-06 (`@0.1.0-15e0645`); no LICENSE at pin (noted in intake) | Mirror; confirm license + layout |
| ✅ P1 | `KamilKleina/git-aliases` | Shipped 2026-08-07 (`@0.1.0-109cc61`); typed `script`, overlay use after install | Mirror; type `module` or `script` after inspect |
| P1 | `nushell/nu_scripts` weather + extract slices | Already known upstream; complements wttr | Mirror paths like git-completions (`modules/weather`, `modules/data_extraction`) |
| P1 | `fj0r/docker.nu`, `fj0r/git.nu` | Popular structured CLI wrappers | Mirror; smoke with Docker/git present |
| P2 | `yh17549/nu-dir-bookmark` | Jump/bookmark UX | Mirror |
| P2 | `SuaveIV/nu_script_time_sync` (+ world-time) | Small companion suite | Mirror |
| P2 | `nushell-prophet/nu-history-tools`, `nu-cmd-stack` | Same provenance family as `numd`/`dotnu` | Mirror; heavier UX surface |
| Defer | `fj0r/ai.nu`, Salesforce/QuickBooks, telegram bots | Credentials / niche; poorer first-use | Outreach later |
| Defer | Prompt themes (`powerline.nu`, catppuccin) | Config mutation risk; needs activation story | After script activation design |

### Completions (second gap)

awesome-nu highlights cargo / git / make / npm / winget. Catalog ships the mega `custom-completions` tree **plus** a git slice only. Users searching `cargo` or `winget` do not see discrete packages.

Recommended wave: **split top-N completion packages** as install-only mirrors (same commit pin as existing `f04cb44` or refresh together):

1. `nushell/cargo-completions`
2. `nushell/npm-completions`
3. `nushell/make-completions`
4. `nushell/winget-completions` (Windows-first demo)
5. `nushell/aws-completions` (if present under `custom-completions/aws`)
6. Later: docker / kubectl / gh / bat once the packaging pattern is boring

Keep the mega `nushell/custom-completions` package; do not remove it. Splits improve discoverability in `search`.

### Modules (smaller gap, better activation story)

Modules can already activate. Prefer packages with clear exports and low host coupling:

| Priority | Candidate | Why |
|----------|-----------|-----|
| P1 | Refresh / add `nu_scripts` docker, kubernetes helpers if they load as modules | Real day-job demos without ABI |
| P1 | Confirm whether `git-aliases.nu` activates cleanly as a module | Better than install-only for UX |
| P2 | `amasialabs/nushell-modules` (snip) | Snippet manager |
| Defer | Archived `nu-git-manager` replacements | Already have archived mirrors; avoid more archive debt |

## Recommended Wave 3 (registry-first)

Goal: make `search` / first-use demos feel like a shell ecosystem, not only a plugin ABI zoo. **Wave 3 shipped 2026-08-06/07** (11 new install-only mirrors); the balance below is what remains or was dropped.

### Wave 3A: Scripts (prove diversity) — ✅ all live

- [x] `SuaveIV/nu_script_gh_status` → `@0.1.0-81756dc` (mirror)
- [x] `SuaveIV/nu_script_hnews` → `@0.1.0-6cd8aef` (mirror)
- [x] `Sanceilaks/nufetch` → `@0.1.0-15e0645` (mirror)
- [x] `KamilKleina/git-aliases` → `@0.1.0-109cc61` (mirror; typed `script`)

Intake steps per package: `scripts/discover.py` → `build-mirror-zip.py` → registry release asset → `add-package.py --write` → sync intake docs → staging → lifecycle evidence consistent with install-only type → production.

### Wave 3B: Completions (discoverability) — ✅ 4 of 5 shipped

- [x] cargo, npm, make, winget → `@0.1.0-f04cb44` (mirrors, 2026-08-07)
- [ ] aws-completions (not present under `custom-completions/aws` at the pin — dropped)
- [x] Refresh pin: existing nu_scripts mirrors share commit `f04cb44`

### Wave 3C: Client honesty (same timeframe, separate PRs)

- [ ] Document in README / search UX which scripts & completions declare activation and which stay install-only (path printed; no silent activate)
- [ ] Consider adding one **install-only** starter path to `numan try` docs (or a follow-up `try` fallback) now that Wave 3A is live: e.g. wttr or nufetch on any Nu
- [x] Do **not** invent script/completion activation in the catalog wave (roadmap: still deferred at Wave 3 time; contracts landed later, see Tracking debt note 3)

### Explicit non-goals for Wave 3 (now unblocked for Wave 4+)

- Commit-snapshot CI for `nu_plugin_plot` / other NO_RELEASE plugins (now unblocked via P1 commit-snapshot mode in numan-plugins)
- Non-binary archive intake for standalone scripts & modules (now automated via P2 `intake-archive.py`)
- Credentialed BigQuery promotion (now unblocked via P6 `evidence_tier: provisional`)
- Transparent maintained forks for abandoned high-demand plugins (now governed via P4 ADR 0001)

## Wave 4 (Intake Reform Execution: Plugins, Modules & Expansions)

Following the August 2026 Intake Process Reform (governed by ADR 0001 and implemented in numan, numan-plugins, and numan-registry), the previous intake bottlenecks are resolved across five distinct workstreams:

### 1. High-Demand Tag-less Plugins (P1 Commit-Snapshot Mode)

- [ ] `Euphrasiologist/nu_plugin_plot` (⭐ 71) — terminal plotting
- [ ] `Euphrasiologist/nu_plugin_bio` (⭐ 31) — bioinformatics file format parser
- [ ] `fdncred/nu_plugin_pnet` (⭐ 9) — network interface inspection
- [ ] `WindSoilder/nu_plugin_mongo` (⭐ 8) — MongoDB query client
- [ ] `hulthe/nu_plugin_msgpack` (⭐ 7) — MessagePack data converter
- [ ] `kik4444/nu_plugin_mime` (⭐ 6) — in-memory MIME inspection
- [ ] `oderwat/nu_plugin_logfmt` (⭐ 5) — logfmt structured parser
- [ ] `yybit/nu_plugin_x509` (⭐ 5) — X.509 certificate generator/parser

### 2. Standalone Script & Module Expansion (P2 Archive Intake Lane)

Automated via `scripts/intake-archive.py` with commit-level SHA256 pinning:

- [x] `fj0r/ai.nu` — OpenAI & Ollama LLM integration client
- [x] `fj0r/docker.nu` — Docker container management tools
- [x] `fj0r/kubernetes.nu` — Kubernetes kubectl client toolset
- [x] `fj0r/git.nu` — Git toolset & helpers
- [x] `lassoColombo/conventional-commits` — conventional commits parser
- [x] `nushell-prophet/nu-history-tools` — shell history analytics & graphs
- [x] `ArmoredPony/nu-digital-rain` — terminal digital rain effect
- [x] `yh17549/nu-dir-bookmark` — directory bookmarking & jump
- [ ] `freepicheep/nu-salesforce` & `freepicheep/nu-quickbooks` — enterprise data clients
- [x] `Yethal/terraform-importer` — Terraform state importer

### 3. Credential-Bound Packages (P6 Provisional Evidence Tier)

- [x] `galuszkak/nu_plugin_bigquery` — BigQuery query plugin; ship with `evidence_tier: provisional` and deferral reason documenting GCP credentials requirement.

### 4. Multi-OS Expansions & Upstream `.tar.xz` Assets (P3)

- [x] `abusch/nu_plugin_semver` — add Linux/macOS `.tar.xz` assets to complete multi-OS matrix
- [x] `Trivernis/nu-plugin-dialog` — add Linux/macOS `.tar.xz` assets
- [x] `fennewald/nu_plugin_net` — intake Linux/macOS `.tar.xz` assets

### 5. Maintained Forks for Abandoned Plugins (P4 Lane 3)

Evaluated for `numan-maintained` distribution per ADR 0001 stewardship criteria:

- [x] `FMotalleb/nu_plugin_clipboard` (⭐ 85) — evaluated: rejected for fork stewardship; superseded by Nushell 0.111+ core builtin `clip`
- [x] `yybit/nu_plugin_compress` (⭐ 42) — evaluated: approved for `numan-maintained/nu_plugin_compress` (Nu 0.114 bump)
- [x] `devyn/nu_plugin_dbus` (⭐ 34) — evaluated: conditionally approved for Linux-only `numan-maintained/nu_plugin_dbus` (Nu 0.114 bump)
- [ ] `FMotalleb/nu_plugin_audio_hook` (⭐ 24, pinned to Nu 0.110)
- [ ] `JosephTLyons/nu_plugin_units` (⭐ 18, pinned to Nu 0.106)

| Do now (low risk) | Courtesy zips (mirrors live) | Parallel plugin track | Do not |
|-------------------|------------------------------|------------------------|--------|
| Follow-up comment on [nu_scripts#1266](https://github.com/nushell/nu_scripts/issues/1266): folder org only, not zips ([draft 11](outreach-issues/11-nushell-nu-scripts-followup-org.md)) | Optional-zip issues for SuaveIV suite, nufetch, git-aliases ([05](outreach-issues/05-suaveiv-script-suite.md)–[07](outreach-issues/07-kamilkleina-git-aliases.md)); cite live registry ids | Clipboard / plot / compress Nu-tag asks ([08](outreach-issues/08-fmotalleb-clipboard-nu114.md)–[10](outreach-issues/10-yybit-compress-nu-bump.md)) | Re-ask nu_scripts for release zips (already declined) |
| Optional nudge [numd#115](https://github.com/nushell-prophet/numd/issues/115) ([draft 12](outreach-issues/12-nushell-prophet-numd-nudge.md)) | Mirrors live; upstream assets optional | One upstream per week | Spam amtoine (archived) |

## Tracking debt to open

1. **`numan-registry/docs/non-plugin-backlog.json`** (or extend intake-state): plugin backlog does not cover scripts/modules/completions.
2. **`numan try` starter diversity**: add at least one Nu-agnostic script now that Wave 3A mirrors are live.
3. **Activation contracts** for scripts/completions have since landed (client nu-script in numan #14, nu-completion in numan #15; registry declarations followed). Catalog growth is no longer required to stay install-only, though packages whose payloads cannot honestly declare an entry point or target stay install-only.

## Success criteria

Wave 3 is done when:

- Catalog type mix moves toward roughly **≥6 scripts or completion packages** (now 11: 5 scripts + 6 completions) — **met**.
- `numan search weather` / `git` / `cargo` / `fetch` return obvious non-plugin hits with honest install-only behavior.
- Lifecycle-prove (or type-appropriate install smoke) passes on at least Linux and Windows for the new packages.
- Plugin backlog status counts are unchanged except for genuine upstream Nu bumps.

## Related docs

- [`catalog-compat.md`](catalog-compat.md): live package list
- [`intake-candidates.md`](intake-candidates.md): intake status
- [`numan-plugins/docs/backlog.json`](https://github.com/numan-cli/numan-plugins/blob/main/docs/backlog.json): plugin candidates only
- [`numan/docs/plans/consolidated-multi-repo-roadmap.md`](https://github.com/numan-cli/numan/blob/master/docs/plans/consolidated-multi-repo-roadmap.md): install-only package types
