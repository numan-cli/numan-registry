# Archive/successor audit: `nu-git-manager` modules

Date: 2026-11-11

Scope: `amtoine/nu-git-manager` and `amtoine/nu-git-manager-sugar`.

Verdict: no maintained public fork or successor was found in the sources that
could be enumerated. The registry keeps both packages as archived, provisional
upstream mirrors, excludes them from production signing, and points users at
`fj0r/git.nu` as the maintained alternative.

## GitHub

| Endpoint | Observed |
|---|---|
| `GET https://api.github.com/repos/amtoine/nu-git-manager` | HTTP 200; `archived: true`, `forks_count: 0`, `network_count: 0`, `pushed_at: 2025-02-18T18:56:48Z` |
| `GET https://api.github.com/repos/amtoine/nu-git-manager/forks?per_page=100` | HTTP 200; empty array |
| `GET https://github.com/amtoine/nu-git-manager/forks` | HTTP 200; body contains “No one has forked this repository yet” |

The live repository HTML contains `forksCount:0`. The older search-indexed
snippet still says “Fork 1”; there is no fork list entry behind that stale
indicator.

## GitLab

| Endpoint | Observed |
|---|---|
| `GET https://gitlab.com/api/v4/projects?search=nu-git-manager&per_page=100` | HTTP 200; `[]` |
| `GET https://gitlab.com/api/v4/projects?search=nu-git-manager-sugar&per_page=100` | HTTP 200; `[]` |
| `GET https://gitlab.com/api/v4/projects?search=git-manager&per_page=100` | HTTP 200; unrelated `git manager app 2` |
| `GET https://gitlab.com/api/v4/projects?search=nupm&per_page=100` | HTTP 200; unrelated `FormacionUPM` |

## Codeberg

The Gitea API search returned HTTP 429 for `nu-git-manager`, `git-manager`,
`nupm`, and `nu-git-manager-sugar` on attempts with 0, 2, 5, and 10 second
backoff. The response body was:

```text
Search and filtering is seeing a high influx of requests for this repository,
to preserve the availability of Codeberg, your search request will not be
processed. Sorry for the inconvenience and please try again later.
```

The web search views were reachable:

| Endpoint | Observed |
|---|---|
| `GET https://codeberg.org/explore/repos?q=nu-git-manager&only_show_relevant=0&sort=recentupdate` | HTTP 200; zero repository links |
| `GET https://codeberg.org/explore/repos?q=git-manager&only_show_relevant=0&sort=recentupdate` | HTTP 200; zero repository links |
| `GET https://codeberg.org/explore/repos?q=nupm&only_show_relevant=0&sort=recentupdate` | HTTP 200; zero repository links |
| `GET https://codeberg.org/explore/repos?q=nu-git-manager-sugar&only_show_relevant=0&sort=recentupdate` | HTTP 200; zero repository links |

Direct repository lookups on `https://codeberg.org/api/v1/repos/` returned
HTTP 404 with `{"message":"The target couldn't be found."}` for
`amtoine/nu-git-manager` and `amtoine/nu-git-manager-sugar`. The `nupm`,
`nushell`, and `fj0r` namespaces also returned HTTP 404 (user namespace does
not exist).

## SourceHut

SourceHut’s project and search endpoints returned HTTP 418 with a `go-away`
anti-bot page. The body begins:

```html
<title>Checking you are not a bot</title>
```

The observed endpoints were:

| Endpoint | Observed |
|---|---|
| `GET https://sr.ht/projects?search=nu-git-manager` | HTTP 418 goaway meta-refresh challenge |
| `GET https://sr.ht/projects?search=nu-git-manager-sugar` | HTTP 418 goaway challenge |
| `GET https://git.sr.ht/search?search=nu-git-manager` | HTTP 418 goaway challenge |
| `GET https://git.sr.ht/search?q=nu-git-manager` | HTTP 418 goaway challenge |
| `GET https://git.sr.ht/projects?search=nu-git-manager` | HTTP 418 goaway challenge |
| `GET https://git.sr.ht/?search=nu-git-manager` | HTTP 200; generic git.sr.ht welcome page, no result links |
| `GET https://sr.ht/api/projects` | HTTP 404 `{"errors":[{"reason":"404 not found"}]}` |
| `GET https://sr.ht/query` | HTTP 401; Authorization header required |

Direct guessed project paths on `https://git.sr.ht/~owner/repo` returned HTTP
404 for `~amtoine/nu-git-manager`, `~amtoine/nu-git-manager-sugar`,
`~nupm/nu-git-manager`, and `~nushell/nu-git-manager`.

SourceHut search could not be enumerated through the public endpoint because
the service deliberately blocks automated requests; the exact 418 status and
goaway body are the block evidence, not a “no results” claim.

## nupm

| Endpoint | Observed |
|---|---|
| `GET https://raw.githubusercontent.com/nushell/nupm/main/registry/nu-git-manager.nuon` | HTTP 200; versions 0.1.0–0.7.0, all with `url: "https://github.com/amtoine/nu-git-manager"` |
| `GET https://raw.githubusercontent.com/nushell/nupm/main/registry/nu-git-manager-sugar.nuon` | HTTP 200; versions 0.1.0–0.7.0, all with the same archived upstream URL |
| `GET https://api.github.com/search/code?q=nu-git-manager+repo:nushell/nupm` | HTTP 200; only the two registry files and nupm registry docs, no renamed continuation |

## Conclusion

- GitHub has no fork behind the archived repository; the “1 fork” label is stale.
- GitLab, Codeberg web search, and nupm contain no maintained successor.
- Codeberg’s API and SourceHut’s search endpoint are blocked (429 and 418);
  SourceHut direct paths are 404.
- No candidate exists to evaluate for activation contract, release artifacts,
  lifecycle proofs, or upstream provenance.
- Registry state remains: both entries `archived` + `deprecated` + `watch-off` +
  `alternative:fj0r/git.nu`, `evidence_tier: provisional`, production-excluded.

## Watch issue

The stale `[watch] amtoine/nu-git-manager-sugar upstream updates` issue
[#109](https://github.com/numan-cli/numan-registry/issues/109) was closed as
not planned on 2026-11-12. Both packages remain `watch-off`, `yanked` with
reason `nu-parser-incompatible`, deprecated, and production-excluded; `fj0r/git.nu` remains
the maintained alternative. A future maintained fork should be handled as a
new intake request, not by reopening the stale watch.
