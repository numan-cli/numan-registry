# Upstream issue drafts

Copy-paste ready: each draft is written for its repo, not from a shared template.

## Existing (filed / resolved / blocked)

| Repo | Title | Status |
| ------ | ------- | -------- |
| [amtoine/nu-git-manager](https://github.com/amtoine/nu-git-manager) | Release zip for `pkgs/nu-git-manager` on tags? | **Blocked**: repo archived; no public fork/successor found; deprecated; watch-off; [#109](https://github.com/numan-cli/numan-registry/issues/109) closed as not planned; use `fj0r/git.nu` |
| [tesujimath/bash-env-nushell](https://github.com/tesujimath/bash-env-nushell) | Uploaded zip for tag releases? | Resolved [#50](https://github.com/tesujimath/bash-env-nushell/issues/50) |
| [nushell-prophet/numd](https://github.com/nushell-prophet/numd) | Release zip assets for dotnu + numd | Filed [#115](https://github.com/nushell-prophet/numd/issues/115): await / use [12](12-nushell-prophet-numd-nudge.md) |
| [nushell/nu_scripts](https://github.com/nushell/nu_scripts) | Release artifacts for nu-hooks / custom-completions | Filed [#1266](https://github.com/nushell/nu_scripts/issues/1266): zips declined; use [11](11-nushell-nu-scripts-followup-org.md) |

## Wave 3 + plugin backlog

Drafts 05–10 are pending; **11–12 are already posted** (see table). Stagger **one contact per week**. Wave 3A/3B registry mirrors are already live (`gh_status`, `hnews`, `nufetch`, `git-aliases`, plus cargo/npm/make/winget completions); cite those registry ids when filing courtesy zip asks.

| # | Repo | Ask | Draft | When to file |
| --- | ------ | ----- | ------- | -------------- |
| 05 | [SuaveIV/nu_script_wttr](https://github.com/SuaveIV/nu_script_wttr) (covers suite) | Optional release zips for wttr / gh_status / hnews | [05](05-suaveiv-script-suite.md) | **Ready now** — Wave 3A mirrors live; optional courtesy zip ask |
| 06 | [Sanceilaks/nufetch](https://github.com/Sanceilaks/nufetch) | Optional release zip | [06](06-sanceilaks-nufetch.md) | **Ready now** — `Sanceilaks/nufetch@0.1.0-15e0645` mirror live |
| 07 | [KamilKleina/git-aliases.nu](https://github.com/KamilKleina/git-aliases.nu) | Optional release zip | [07](07-kamilkleina-git-aliases.md) | **Ready now** — `KamilKleina/git-aliases@0.1.0-109cc61` mirror live |
| 08 | [FMotalleb/nu_plugin_clipboard](https://github.com/FMotalleb/nu_plugin_clipboard) | (Obsolete) no outreach | [08](08-fmotalleb-clipboard-nu114.md) | **Obsolete**: Nushell 0.111+ core includes builtin `clip` commands; repo archived |
| 09 | [Euphrasiologist/nu_plugin_plot](https://github.com/Euphrasiologist/nu_plugin_plot) | Please cut a version tag | [09](09-euphrasiologist-plot-tag.md) | When plot is next priority |
| 10 | [yybit/nu_plugin_compress](https://github.com/yybit/nu_plugin_compress) | Nu bump + tag | [10](10-yybit-compress-nu-bump.md) | After plot / when compress is next |
| 11 | nushell/nu_scripts #1266 | Follow-up: folder org, not zips | [11](11-nushell-nu-scripts-followup-org.md) | **Posted** 2026-08-06 ([comment](https://github.com/nushell/nu_scripts/issues/1266#issuecomment-5210338399)) |
| 12 | nushell-prophet/numd #115 | Polite nudge | [12](12-nushell-prophet-numd-nudge.md) | **Posted** 2026-08-06 ([comment](https://github.com/nushell-prophet/numd/issues/115#issuecomment-5210338541)) |

```bash
# Example: new upstream issue
gh issue create --repo SuaveIV/nu_script_wttr \
  --title "Optional release zips for Numan / hash-pinned installers?" \
  --body-file docs/outreach-issues/05-suaveiv-script-suite.md

# Example: comment follow-up (not a new issue)
gh issue comment 1266 --repo nushell/nu_scripts \
  --body-file docs/outreach-issues/11-nushell-nu-scripts-followup-org.md
```

See also [`../upstream-release-outreach.md`](../upstream-release-outreach.md) and [`../catalog-next-wave.md`](../catalog-next-wave.md).
