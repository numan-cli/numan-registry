# Upstream release asset outreach plan

How to contact mirrored-package maintainers and help them ship **byte-stable release assets**, so the official registry can pin upstream URLs instead of registry-hosted mirrors.

**Precedent:** [vyadh/nutest#29](https://github.com/vyadh/nutest/issues/29) — packaging suggestion (not a bug). Maintainer added `nutest-X.Y.Z.zip` in v1.2.0 and a release workflow in [vyadh/nutest#31](https://github.com/vyadh/nutest/pull/31). Registry switched from mirror to upstream asset in [numan-registry#9](https://github.com/numan-cli/numan-registry/pull/9).

---

## Goals

1. **Upstream owns the artifact** — registry pins their uploaded zip, not our mirror.
2. **Reproducible layout** — archive contains a single top-level directory `{name}-{version}/` with predictable `mod.nu` (or named entry) paths.
3. **Low maintainer burden** — offer a copy-paste release workflow PR when helpful.
4. **Graceful relationship** — mirror stays live until upstream ships; no pressure, short thank-you if they decline.

---

## When to reach out

| Milestone | Action |
|-----------|--------|
| Mirror PR merged + production published | Registry works today; outreach is optional hardening |
| `numan install <pkg>` smoke-tested once | You can cite a working registry entry in the issue |
| Before opening upstream issue | Search existing issues for "release", "zip", "nupm", "package" |

**Do not** open six issues in one day. Stagger **one per week** unless maintainers are the same org (nushell-prophet).

---

## What to ask for (module packages)

Minimum viable upstream asset for Numan (and other hash-pinned consumers):

```text
{name}-{version}.zip
└── {name}-{version}/
    ├── mod.nu              # or named entry (e.g. bash-env.nu)
    └── …                   # rest of module tree
```

Requirements:

- **Uploaded** GitHub Release asset (not `/archive/refs/tags/…` auto-zip)
- Format: `.zip` (or `.tar.gz`)
- **Stable bytes** per tag — re-upload only if tag is moved (avoid tag moves)

Optional PR: GitHub Actions workflow on tag push that runs `git archive` or a small pack script and attaches the zip (see nutest `release.yaml`).

---

## Per-repo outreach plan

### 1. `amtoine/nu-git-manager` — **Issue first**

| Field | Detail |
|-------|--------|
| Contact | [@amtoine](https://github.com/amtoine) (nupm ecosystem regular) |
| Current state | Tags through **0.8.0**; releases have **zero assets** |
| Registry mirror | `mirror-amtoine-nu-git-manager-0.8.0` |
| Suggested entry | `pkgs/nu-git-manager/` → zip root `nu-git-manager-{version}/` |
| Issue vs PR | **Issue** — offer PR for release workflow after they agree on layout |
| Tone | Peer nupm/Numan maintainer; reference nupm.nuon layout they already publish |

**Issue title:** `Release zip for pkgs/nu-git-manager on tags?`

**Key points:**

- Already in [nupm registry](https://github.com/nushell/nupm); Numan mirrors tag 0.8.0 today
- Ask for zip of `pkgs/nu-git-manager/` at `{version}` tags
- Entry path: `pkgs/nu-git-manager/nu-git-manager/mod.nu`

---

### 2. `tesujimath/bash-env-nushell` — **Resolved**

| Field | Detail |
|-------|--------|
| Contact | [@tesujimath](https://github.com/tesujimath) |
| Current state | Tag **0.19.0** ships `bash-env-nushell-0.19.0.zip`; [release workflow](https://github.com/tesujimath/bash-env-nushell/blob/main/.github/workflows/release.yaml) for future tags |
| Registry | Upstream asset (switched from `mirror-tesujimath-bash-env-nushell-0.19.0`) |
| Layout | `bash-env-nushell-{version}/bash-env.nu` |
| Outreach | [#50](https://github.com/tesujimath/bash-env-nushell/issues/50), workflow in [#51](https://github.com/tesujimath/bash-env-nushell/pull/51) |

**Key points:**

- High visibility replacement for deprecated `nu_plugin_bash_env`
- Note external dep `bash-env-json` in issue (not a blocker for release zip)
- Entry is `bash-env.nu`, not `mod.nu` — document that in the issue

---

### 3. `nushell-prophet/dotnu` — **Issue first (batch with numd?)**

| Field | Detail |
|-------|--------|
| Contact | nushell-prophet org maintainers |
| Current state | Tag **0.0.18**; no assets; has `nupm.nuon` |
| Registry mirror | `mirror-nushell-prophet-dotnu-0.0.18` |
| Layout | `dotnu-{version}/dotnu/mod.nu` + `nupm.nuon` |

**Key points:**

- Module-author tooling; same audience as nupm
- Could combine outreach with numd in one org-level issue if preferred

---

### 4. `nushell-prophet/numd` — **Issue first**

| Field | Detail |
|-------|--------|
| Contact | nushell-prophet org maintainers |
| Current state | Tags through **0.4.0**; releases have **zero assets** |
| Registry mirror | `mirror-nushell-prophet-numd-0.4.0` |
| Layout | `numd-{version}/numd/mod.nu` + `nupm.nuon` |

**Suggested approach:** Single issue on **numd** or **dotnu** repo titled *"Release zip assets for nupm/Numan (dotnu + numd)"* covering both packages.

---

### 5. `nushell/nu_scripts` — **Issue only (no PR without maintainer buy-in)**

Two registry entries from one monorepo:

| Entry | Pin | Problem |
|-------|-----|---------|
| `nushell/nu-hooks@0.1.0` | commit `f04cb44` | No `mod.nu`; hook collection |
| `nushell/custom-completions@0.1.0-f04cb44` | same commit | Large tree; completion activation targets now declared in the registry |

| Field | Detail |
|-------|--------|
| Contact | nushell/nu_scripts maintainers (fdncred ecosystem) |
| Current state | Monorepo; nupm pins git revisions, not release zips |
| Issue vs PR | **Issue only** — propose policy, not a 2000-file release workflow |

**Ask (realistic):**

1. **Policy** — Are tagged release zips for individual nupm packages in scope?
2. **nu-hooks** — Would a subfolder zip (`nu-hooks-{version}.zip`) on releases be acceptable?
3. **custom-completions** — Likely stays mirrored long-term unless they want a split repo or periodic snapshot releases

**Do not** PR a workflow that zipballs the entire repo on every tag without discussion.

---

## Issue bodies

Ready-to-post drafts live in [`docs/outreach-issues/`](outreach-issues/README.md) — **one file per repo**, written for that maintainer's context (not a shared template). Skim before posting; tweak if their CONTRIBUTING or release habits differ.

**Closing:** Keep it short if they ship — thank-you only (see nutest follow-up).

---

## Optional PR offer (after issue ACK)

When a maintainer says yes, PR should include:

1. `.github/workflows/release.yaml` (or extend existing release workflow)
2. Pack script: `git archive` at tag **or** copy named paths into staging dir
3. Upload `{name}-{version}.zip` as release asset
4. Document expected zip layout in README or `nupm.nuon`

**Reference implementation:** [vyadh/nutest `release.yaml`](https://github.com/vyadh/nutest/blob/v1.2.0/.github/workflows/release.yaml)

**Do not** PR to upstream before issue acknowledgment unless the repo explicitly welcomes drive-by CI (check CONTRIBUTING.md).

---

## After upstream ships

1. Add spec with upstream URL → `scripts/add-package.py --spec … --write`
2. The package **must be staged or published** in the configured registry before running lifecycle-prove, unless a registry-target override is added
3. Prove on a clean root: `python scripts/lifecycle-prove.py --package owner/name` (see [lifecycle-prove.md](lifecycle-prove.md))
4. Keep mirror version in index **or** deprecate after one release cycle
5. Update `docs/intake-state.json` — move from mirror to ready-now, then run `python scripts/sync-intake-candidates.py` to regenerate
6. Comment on upstream issue with brief thanks (no registry internals)

---

## Outreach tracker

| Upstream | Issue/PR | Opened | Response | Upstream asset shipped | Registry switched |
|----------|----------|--------|----------|------------------------|-------------------|
| amtoine/nu-git-manager | blocked (repo archived (read-only); cannot open issues or comments) |  |  |  | mirror only |
| nushell-prophet/dotnu | [#115](https://github.com/nushell-prophet/numd/issues/115) | 2026-07-06 | awaiting |  | mirror only |
| nushell-prophet/numd | [#115](https://github.com/nushell-prophet/numd/issues/115) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (nu-hooks) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (custom-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| SuaveIV/nu_script_wttr |  |  |  |  | mirror only |
| SuaveIV/nu_script_gh_status |  |  |  |  | mirror only |
| SuaveIV/nu_script_hnews |  |  |  |  | mirror only |
| Sanceilaks/nufetch |  |  |  |  | mirror only |
| amtoine/nu-git-manager-sugar | blocked (repo archived (read-only); cannot open issues or comments) |  |  |  | mirror only |
| nushell/nu_scripts (git-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (cargo-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (npm-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (make-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (winget-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| KamilKleina/git-aliases |  |  |  |  | mirror only |
| fj0r/ai.nu |  |  |  |  | mirror only |
| fj0r/docker.nu |  |  |  |  |  |
| fj0r/kubernetes.nu |  |  |  |  |  |
| fj0r/git.nu |  |  |  |  | mirror only |
| lassoColombo/conventional-commits |  |  |  |  | mirror only |
| nushell-prophet/nu-history-tools |  |  |  |  |  |
| ArmoredPony/nu-digital-rain |  |  |  |  | mirror only |
| yh17549/nu-dir-bookmark |  |  |  |  |  |
| nushell/nu_scripts (docker-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (gh-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (dotnet-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (uv-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (pnpm-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (ssh-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| Yethal/terraform-importer |  |  |  |  |  |
| nushell/nu_scripts (bat-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (aws-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |
| nushell/nu_scripts (rg-completions) | [#1266](https://github.com/nushell/nu_scripts/issues/1266) | 2026-07-06 | awaiting |  | mirror only |

---

## Suggested schedule (next)

Prior schedule (amtoine / bash-env / prophet / nu_scripts) is largely done or blocked. Wave 3A/3B install-only mirrors are live in the registry (2026-08-06/07); remaining Wave 3 outreach is optional courtesy zip asks, not a wait-for-mirror gate. For Wave 3 + deferred plugins, see also [`catalog-next-wave.md`](catalog-next-wave.md).

| Week | Action |
|------|--------|
| 1 (done 2026-08-06) | Commented on [nu_scripts#1266](https://github.com/nushell/nu_scripts/issues/1266#issuecomment-5210338399) (org follow-up) and [numd#115](https://github.com/nushell-prophet/numd/issues/115#issuecomment-5210338541) (nudge) |
| 2 | File SuaveIV suite courtesy issue ([05](outreach-issues/05-suaveiv-script-suite.md)); mirrors already live (`wttr`, `gh_status`, `hnews`) |
| 3 | File nufetch ([06](outreach-issues/06-sanceilaks-nufetch.md)); mirror already live |
| 4 | File git-aliases ([07](outreach-issues/07-kamilkleina-git-aliases.md)); mirror already live |
| 5 | ~~File clipboard Nu-bump ask ([08](outreach-issues/08-fmotalleb-clipboard-nu114.md))~~ (Obsolete: Nushell 0.111+ core includes builtin `clip` commands; evaluated & rejected under ADR 0001) |
| 6 | File plot tag ask ([09](outreach-issues/09-euphrasiologist-plot-tag.md)) |
| 7 | File compress Nu-bump ask ([10](outreach-issues/10-yybit-compress-nu-bump.md)) |
| Ongoing | PR workflows only when invited; update `docs/intake-state.json` + run sync script; **one new contact per week** |

---

## What not to do

- Frame as "your package is broken" — it's a packaging enhancement
- Dump Numan architecture in the issue — link registry + nutest precedent only
- Remove mirrors before upstream assets exist
- Open duplicate issues if one org owns multiple packages (batch politely)
