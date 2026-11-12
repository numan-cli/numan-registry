# Registry incident response and user remediation

This policy covers the public official registry at
`https://numan-cli.github.io/numan-registry/`. It does not weaken Numan's
signature, digest, or immutable-lockfile guarantees.

## Report a security concern

Do not publish exploit details, suspected private keys, or unverified artifact
content in a public issue. If GitHub offers private reporting for your account,
start a report at
<https://github.com/numan-cli/numan-registry/security/advisories/new>.
Otherwise, open a public issue titled **Security contact request** with no
technical details; the maintainer will establish a private channel before
collecting the report.

Include the package ID and version, affected target triple, artifact URL and
digest, registry revision or index hash, and enough reproduction detail to
independently verify the claim.

## Triage rules

1. Preserve the reported index, signature, artifact URL, digest, and relevant
   CI logs before changing the catalog.
2. Determine whether the issue affects an artifact, package metadata, the
   signed index, or signing-key material.
3. Do not silently replace an artifact at the same URL or digest. Publish a
   reviewed, signed index revision and a public advisory once disclosure is
   safe.
4. Record the affected package IDs, versions, target triples, replacement
   versions, and user action in the advisory.

## Yank or revoke a package version

Registry schema v1 uses an optional version-level `yanked` object. A yank is a
reviewed, signed catalog revision that adds `{reason_code, evidence_url}` to the
affected version while retaining the artifact and hashes for audit.

1. Add `yanked` to the affected version in `registry/index.json` and its source
   spec; keep the version and artifact so the withdrawal remains auditable.
2. Run the normal schema, artifact-digest, and Numan-parser checks.
3. Merge the reviewed change to `main` and dispatch the protected production
   workflow with the incident reference as its reason.
4. Verify the published index and detached signature before announcing the
   yank.

Removing a version is reserved for cases where it must not remain in the
catalog at all, such as a legal removal or malformed metadata. Existing
lockfiles remain immutable evidence of an earlier selection. Production
materialization excludes yanked versions, so clients that have not adopted the
field are protected after their next registry sync. A yank does not remotely
delete a user's payload or rewrite their lockfile.

## Compromised or incorrect artifact

For an artifact whose bytes do not match its recorded digest, or whose recorded
digest identifies compromised bytes:

1. Treat the affected target as unavailable. Yank it or replace it with a new
   version and a newly verified digest; never edit a published version in
   place.
2. Publish the reviewed signed index revision through the protected production
   workflow.
3. State the exact affected IDs, versions, targets, URLs, and SHA-256 values
   in the advisory.
4. If signing-key material, release automation, or the signing environment may
   be involved, also follow the key-exposure procedure in
   [production-cutover-checklist.md](production-cutover-checklist.md) and the
   [key rotation checklist](key-rotation-checklist.md).

## Index rollback

Rollback means returning the catalog source on `main` to a previously verified
revision, then publishing a newly signed production index from that reviewed
commit. Do not copy files directly into the `gh-pages` branch and do not reuse
an old detached signature for changed index bytes.

1. Identify the last verified source commit and its published index hash.
2. Revert the unsafe catalog change on `main` in a reviewable PR.
3. Run schema, artifact-digest, and Numan-parser checks.
4. Dispatch the protected production workflow from `main`.
5. Verify the live index hash, signature envelope key ID, and affected package
   set before announcing the rollback.

## User remediation

Advisories must tell users exactly which package IDs and versions are affected.
For an affected install, users should sync first, inspect their installed
state, then remove the package only when the advisory requires it:

```bash
numan registry sync
numan doctor
numan list
numan remove --force <owner/name>
numan gc
```

`numan gc` preserves payloads referenced by snapshots. If a user must remove
an affected payload retained solely by a snapshot, they should first inspect
and explicitly delete that snapshot with `numan snapshot list`,
`numan snapshot inspect <id>`, and `numan snapshot delete <id> --yes`.
After a vetted replacement is available, install and activate its explicitly
named version, then run `numan doctor` again.
