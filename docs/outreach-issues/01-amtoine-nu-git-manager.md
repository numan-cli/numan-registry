> **Do not send — upstream archived.** `amtoine/nu-git-manager` is archived and no maintained public fork or successor was found. Both `nu-git-manager` entries are `deprecated`, `watch-off`, `yanked` (`nu-parser-incompatible`), and production-excluded; use `fj0r/git.nu`. The stale watch issue [#109](https://github.com/numan-cli/numan-registry/issues/109) is closed as not planned. This draft is retained for history only.

Hi. I'm adding NGM to the [Numan](https://github.com/numan-cli/numan) registry (same general idea as nupm: install from a curated index, verify artifacts by hash).

You're already listed in the [nupm registry](https://github.com/nushell/nupm) with git pins on `pkgs/nu-git-manager`. For Numan I need something with stable bytes per tag, so right now I'm hosting a mirror of **0.8.0** myself (`pkgs/nu-git-manager/` zipped as `nu-git-manager-0.8.0.zip`).

The awkward part is GitHub's tag archive URLs (`/archive/refs/tags/0.8.0.zip` and friends) aren't something I'd trust to stay byte-identical forever. GitHub has changed how those archives are built before, and hash-pinned installs fail integrity checks when the bytes drift.

Would you be open to attaching a small release zip on future tags? Something like:

```text
nu-git-manager-{version}.zip
└── nu-git-manager-{version}/
    └── …contents of pkgs/nu-git-manager/…
```

No rush on my side. The mirror works. If an uploaded asset is something you'd want, I can send a PR for a tiny release workflow (vyadh did this for [nutest](https://github.com/vyadh/nutest/releases/tag/v1.2.0) and it was straightforward).
