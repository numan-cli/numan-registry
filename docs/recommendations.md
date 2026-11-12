# Cross-repo recommendations: descriptors, proof data, activation, storage, and registries

**Status:** proposal only. This document does not change runtime behavior, schemas, or the trust model.

**Date:** 2026-11-12

**Scope:** the three repositories currently checked out in this workspace:

- `numan` - client, lockfile, install/activation, registry verification
- `numan-plugins` - CI-built plugin manifest and generated intake specs
- `numan-registry` - signed index, intake scripts, lifecycle proofs, publication workflows

The proposal that prompted this document described several things as missing that already
exist. Those corrections are stated explicitly below and are part of the recommendation, not
an addendum. The trust model is unchanged by every item in this document: the registry index
remains an Ed25519-signed document verified as a whole, and no package-level digest, local
cache, or additional registry is allowed to become a substitute trust root.

## Ranked summary

| Rank | Item | Remaining work | Effort | Why this rank |
|---|---|---|---|---|
| 1 | Canonical package descriptor | Real project | 8-12 engineer-days plus releases | Only item that removes the root cause of manifest -> spec -> index -> lockfile drift |
| 2 | Lifecycle proof consolidation | Finish line, not a build-out | 1-2 engineer-days | The expensive part is already shipped; only the duplicate `verified_with` representation remains |
| 3 | Activation taxonomy normalization | Mostly finish line | 2-4 engineer-days | Closed `activation.kind` already exists; the missing explicit plugin/install-only kind is real but small |
| 4 | Multi-registry read support and `key_id` | Design exists, end-to-end behavior does not | 6-10 engineer-days for reads | Valuable before the catalog grows, but must follow lockfile changes from item 1 |
| 5 | Content-addressable payload store | High-risk migration | 15-25 engineer-days plus a major-release window | Useful, but cannot be made primary until the descriptor and lockfile are stable |

The ranking is by impact divided by effort **for the work that remains today**, not by the
historical value of each proposal. Item 2 and item 3 are already substantially implemented in
the current tree. Their high positions reflect that only a small, well-bounded slice remains.
Item 5 has a large long-term payoff but the worst effort-to-risk ratio and two hard
prerequisites, so it stays last.

## Premise corrections up front

These are the places where the current code contradicts the original proposal.

1. **There is no canonical package descriptor, but canonicalization already exists.**
   There is no `PackageDescriptor` type or descriptor schema in any of the three repositories.
   The registry has a whole-index schema, `numan-registry/schemas/index-v1.json`, and the client
   has `Package`, `VersionEntry`, and `RegistryIndex` in `numan/src/core/package.rs:92`,
   `:123`, and `:918`. Canonical JSON is implemented in
   `numan-registry/scripts/ci-sign.py:196`, `numan-registry/scripts/validate.py:28`,
   `numan-registry/scripts/materialize_candidate.py:34`, and
   `numan/src/core/official_registry.rs:170`. It is reusable, but it is duplicated and it is
   applied to the whole index, not to a stable package object. The descriptor work is therefore
   real schema work, not just exposing an existing object.

2. **Lifecycle proofs are already first-class signed data, not docs-only evidence.**
   `proofs` is in the schema at `numan-registry/schemas/index-v1.json:129`, the client models it
   with `LifecycleProof` and `ProofResult` in `numan/src/core/package.rs`, the production signer
   rejects activatable versions without matching passing proofs in
   `numan-registry/scripts/ci-sign.py:119-181` and `:243-263`, and `numan info` and `numan try`
   already render it (`numan/src/cmd/info.rs:154` and `:224`;
   `numan/src/cmd/try_cmd.rs:403`). The evidence docs are supplementary; they are not the only
   evidence. The remaining issue is duplication between `verified_with` and `proofs`, not the
   absence of a proof system.

3. **The closed activation-kind set already exists.**
   `numan-registry/schemas/index-v1.json:221-230` enumerates the activation kinds, and
   `ActivationKind` in `numan/src/core/package.rs:606` rejects unknown values at
   deserialization. The actual gap is that `activation` is optional and only describes the five
   command-backed kinds. Plugins and install-only packages have no explicit primary kind; the
   client infers those labels in display code such as `numan/src/cmd/info.rs:64-101`.

4. **Everything is hashed, but there is no content-addressable store.**
   Installs currently live under
   `packages/<type>/<owner>/<name>/<version>-<first-8-of-artifact-sha>`:
   `numan/src/install/transaction.rs:246-256`. The download cache uses the full SHA
   (`:264`), and the lockfile records `payload_sha256`, `revision_id`, and `payload_path`
   (`numan/src/state/lockfile.rs:304-345`; revision computation at `:842`). No
   content-addressed layout or migration path exists in the client.

5. **Multi-registry configuration and verification exist, but user-facing reads are still
   default-only.**
   `Config.registries` and `RegistryConfig` already support a registry map and a per-registry
   trust key (`numan/src/config.rs:10-17`, `:38-46`), and `RegistryManager` can verify and load
   any named registry, including last-known-good and derived keys
   (`numan/src/core/registry.rs:57-109`, `:248-349`). But `search` and `find_package` always use
   the default registry (`numan/src/core/registry.rs:180-202`), `install` passes
   `registry_name: None` (`numan/src/cmd/install.rs:78`) and diagnoses against the default
   (`:104`), and `try` loads the default (`numan/src/cmd/try_cmd.rs:299`). `update` is the
   exception: it resolves each entry's recorded registry
   (`numan/src/cmd/update.rs:828`). The design is partly present; the end-to-end read feature is
   not.

## 1. Canonical package descriptor

### Problem

One package version has several representations that are manually kept in sync: a manifest
entry, a generated intake spec, a checked-in registry spec, a version object in the signed index,
and a reconstructed lockfile view. No single immutable object is authoritative.

### What the code shows

- `numan-plugins/manifest.json` is `numan-plugin-build-manifest-v0`. Each active entry carries
  `repo`, `name`, `owner`, `plugin_bin`, `tag`, `source_commit`, `version`, `nu_version`,
  `verified_with`, `description`, and `tags`.
- `numan-plugins/scripts/gen_spec.py:146-287` (`build_spec`) already emits a near-complete
  per-version spec: identity, description, repo, type, tags, version, Nu constraint, evidence,
  `source`, and artifact targets. It intentionally omits artifact hashes because the registry
  computes them. It does not emit `proofs`; `grep` finds no proof emission in that script.
- `numan-registry/scripts/add-package.py:317-365` (`build_version_entry`,
  `build_package_entry`) rebuilds the index version object from the spec, downloads artifacts,
  and inserts their SHA-256. `merge_into_index` at `:495-530` also overwrites the existing
  package's `description`, `repo`, and `tags` from the newest spec (`:524-527`). The intake is a
  scaffolder and metadata synchronizer, not a verifier of immutable producer bytes.
- The index schema requires package identity and metadata at the package level and repeats
  version-specific data under `versions`
  (`numan-registry/schemas/index-v1.json:54-95`). There is no descriptor definition, no
  descriptor digest, and no rule for hashing one version independently of `updated_at`.
- The lockfile does not store the signed package object. `LockfileEntry` carries selected fields:
  `artifact_url`, `artifact_sha256`, `executable_path`, activation records, `registry_url`,
  `registry_revision`, `index_sha256`, and `signing_key_fingerprint`
  (`numan/src/state/lockfile.rs:304-345`). The install path fills those fields at
  `numan/src/install/transaction.rs:534-537`. It does not record the package's description,
  tags, provenance object, proof records, or a descriptor digest.
- `numan-registry/specs/` contains checked-in per-package intake specs alongside the index,
  which adds another copy to keep aligned.

### Corrections to the proposal

- "You already have most of the pieces" is true for field coverage, not for identity. The
  pieces exist in three different shapes, and canonicalization is duplicated rather than shared.
- The registry does not rewrite identity, Nu constraints, or provenance values. It copies them
  from the spec. The real problem is that it **reconstructs** the entry and can replace
  package-level metadata; calling that "rewriting" overstates the bug.
- `numan-plugins` is closer to a descriptor producer than the proposal assumes. The missing
  pieces are a stable schema, a digest rule, and proof emission, not all of the metadata.

### Incremental delivery

**Step 0 - make canonicalization a shared primitive (1-2 days).**
Extract one Python canonical-JSON implementation used by
`numan-registry/scripts/ci-sign.py`, `numan-registry/scripts/validate.py`, and
`numan-registry/scripts/materialize_candidate.py`. Keep the Rust implementation in
`numan/src/core/official_registry.rs` and add a cross-language golden fixture for the same input
bytes. A descriptor digest is worthless if the producer and verifier disagree about key order,
Unicode escaping, or number formatting.

**Step 1 - define a versioned descriptor schema and its digest rule (1 day).**
Add the schema under the existing `numan-registry/schemas/` directory; the file name is an
implementation detail. The descriptor is per package version, because that is the immutable
unit the index, resolver, and lockfile actually select. Include:

- descriptor schema version;
- package identity, description, repo, type, and tags;
- version, Nu constraint, source, provenance, and activation/primary kind;
- proof records;
- artifact target declarations (URL, executable path, archive root, entry), but no SHA-256.

Define `descriptor_sha256 = SHA-256(canonical_json(descriptor))`. Exclude `updated_at`, index
revision, and artifact hashes from the descriptor. Those change when the catalog is republished
or when assets are uploaded; the package's identity and behavior do not. Reject floats and
unknown fields so the canonical form is not dependent on serializer behavior.

**Step 2 - producer emits the descriptor and digest (1 day).**
Extend `gen_spec.build_spec` to emit the descriptor plus `descriptor_sha256`. It already has all
the inputs. The registry may still compute artifact hashes, but it must not alter the descriptor
bytes it receives.

**Step 3 - intake verifies, hashes, and signs (2-3 days).**
`numan-registry/scripts/add-package.py` should validate the descriptor schema and digest,
download the declared artifacts, and attach a separate resolution object containing the
per-target SHA-256 values. It should reject a bad descriptor, never normalize one.
`merge_into_index` must stop replacing
description, repo, or tags from a newer version. `prepare-staging.merge_catalogs` already
rejects candidate type/repo changes at `numan-registry/scripts/prepare-staging.py:10-55`; extend
that rule to descriptor identity and digest.

**Step 4 - index schema v2, dual-written (2-3 days).**
Publish index entries containing both the descriptor fields and the legacy fields for one or two
releases. A v2 version entry can carry `descriptor`, `descriptor_sha256`, and `artifacts`, while
still carrying the existing `version`, `nu_version`, `artifact`, `activation`, and `proofs`
fields. The signature still covers the entire canonical index. The descriptor digest is an
integrity reference inside that signed document, not a second signature.

The client cannot accept this immediately. `verify_registry_index` currently rejects any
`schema_version` other than 1 (`numan/src/core/official_registry.rs:249-258`). The client release
that accepts both 1 and 2 must ship before the registry publishes a v2 index. That ordering is a
hard gate, not a rollout preference.

**Step 5 - lockfile stores the exact descriptor (2-3 days).**
Bump the lockfile to a new version and add:

- `descriptor` as the exact canonical descriptor string, or a content-addressed local reference
  in a new descriptor store keyed by `descriptor_sha256` (the directory name is chosen at
  implementation);
- `descriptor_sha256`;
- the existing registry URL/revision/index hash fields, retained for compatibility.

Store the exact string first. It is small, makes the lockfile self-auditing, and avoids a new
local garbage-collection problem. A content-addressed reference can replace the inline copy
after the descriptor store has its own migration and GC story.

On load, a new client prefers the stored descriptor, verifies its digest, and verifies that the
descriptor appears in the signed index revision it records. If the descriptor is absent, it
falls back to the existing reconstructed view. Old lockfiles continue to load; new code must
not require a descriptor to operate during the transition.

### Backward compatibility

- Client first, index second: v2 clients read v1 and v2; v1 clients reject v2. No v2 index is
  published until the minimum supported client can read it.
- Index dual-write keeps every legacy field for at least two production releases.
- Lockfile dual-read keeps the reconstructed path for v1 entries and writes the descriptor for
  new entries.
- The intake compatibility adapter (`numan-registry/scripts/add-package.py` accepting a legacy
  spec) remains for the same two releases.

### Exit criterion

Delete the old reconstruction path only when all of the following hold:

1. 100% of production versions have a descriptor and a matching digest.
2. The minimum supported client has accepted index schema 2 for at least two production
   releases.
3. The lockfile reader no longer needs to reconstruct any field for a registry-installed entry.
4. A CI check fails if a legacy-only version reaches production.

At that point remove the legacy index fields, the reconstruction branch in
`numan-registry/scripts/add-package.py`, and the client fallback. Keep the descriptor schema and digest rule as the stable contract.

### Trust model

Unchanged. The registry still signs the canonical bytes of the whole index with the same
Ed25519 key and key-id envelope. The client still verifies that signature before parsing. The
descriptor digest is only a consistency check inside signed bytes; it is not a new trust root,
does not authorize a key, and cannot make an unsigned descriptor trusted. No trust-on-first-use
path is introduced.

### Effort

8-12 engineer-days for one engineer familiar with all three repos: 1-2 canonicalization and
fixtures, 1 schema, 1 producer, 2-3 intake/validator, 2-3 client/lockfile, 2 dual-write and
rollout tests. Add review time and two registry releases. This is the largest item that still
has a clean, incremental path.

## 2. Lifecycle proofs as signed data

### Problem

The proposal asks for proofs to become signed, machine-readable data and for production to
reject activatable versions without a matching successful proof. That is already the behavior.
The remaining problem is a smaller one: evidence is represented twice, as aggregate
`verified_with` and as per-platform `proofs`, and nothing derives one from the other.

### What the code shows

- `proofs` is optional in the signed schema
  (`numan-registry/schemas/index-v1.json:129-161`) and modeled as `LifecycleProof` with
  `ProofOs`, `ProofArch`, `ProofResult`, optional commands, timestamp, and optional evidence URL
  in `numan/src/core/package.rs`.
- Production signing calls `lifecycle_proof_errors` before signing and refuses on any error
  (`numan-registry/scripts/ci-sign.py:243-263`). The gate covers plugin packages and versions
  with an `activation` object, requires a passing proof whose `nu_version` satisfies the claimed
  range, and exempts yanked versions (`:119-181`).
- `numan info` formats per-platform proof lines, coverage counts, and host warnings
  (`numan/src/cmd/info.rs:154`, `:224-237`); `numan info --json` serializes the full records.
  `numan try` prints the same proof information before installing
  (`numan/src/cmd/try_cmd.rs:403-410`).
- The Rust tests cover byte-identical proof round-trips, tampering, malformed records, and
  unknown fields (`numan/tests/lifecycle_proofs.rs:99-206`). The Python signer tests cover
  rejection and successful signing (`numan-registry/scripts/test_ci_sign.py:184-535`).
- Current local index census (`numan-registry/registry/index.json`, checked 2026-11-12):
  94 versions total, 89 activatable versions, all 89 carry proof records, 5 proof-less versions
  are install-only, and 3 failed-proof versions are yanked. Running
  `lifecycle_proof_errors` over the index returns **86 checked activatable versions, 0 errors**.
  The 86 are the non-yanked activatable versions; the three failed records are withdrawn and
  excluded by the gate.

### Corrections to the proposal

- "Evidence currently lives in docs and is only loosely linked" is false. The signed index
  carries structured proof records; the docs are additional evidence, not the source of truth.
- "Add an optional proofs array, then later require it" is already complete for activatable
  packages. `proofs` is optional in the schema and mandatory in production through the signer
  policy.
- "Surface it in `numan info` and `numan try`" is already complete, including JSON output.

### Remaining incremental work

1. **Make `verified_with` a projection for activatable versions.** In descriptor v1, derive
   `verified_with` from the unique passed `proof.nu_version` values. The current data happens to
   match (`0` mismatches across the 86 live activatable versions), but that is convention, not
   enforcement: `numan-plugins/scripts/gen_spec.py` writes `verified_with` independently and
   `numan-registry/scripts/add-package.py` copies it independently of `proofs`.
2. **Add a consistency check.** Reject an activatable version whose stored `verified_with` does
   not equal the derived set. Run it in validation and signing, not only in a one-off script.
3. **Dual-write one release.** Emit both fields and compare them in CI. Keep the stored field
   readable for old clients. No lockfile or index-shape change is required for this step.

This work can ride inside the descriptor v2 change; it does not need its own schema release.

### Backward compatibility

The aggregate field remains emitted for one release and readable for old clients. New clients
derive and compare it; old clients never need proof records merely to display compatibility.

### Exit criterion

Once all consumers read proofs directly, remove independent writes of `verified_with` for
activatable versions and keep it only as a compatibility projection for one more release.
Install-only packages can continue to omit proofs and carry no aggregate.

### Trust model

Unchanged. Proof records are signed as part of the index, and the signer's coverage policy is
enforced before signing. A proof is evidence attached to signed data, not a separate
attestation authority, and no proof is trusted unless the index signature verifies.

### Effort

1-2 engineer-days: half a day for the derived check, half a day for validator/signer wiring, and
one day for tests and a dual-write release. The expensive, real-Nu lifecycle execution already
exists.

## 3. Activation taxonomy

### Problem

The five command-backed activation kinds are explicit, but there is no single required primary
kind for every package. Plugins and install-only packages are implicit, and the relationship
between `type` and `activation.kind` is not enforced by the schema.

### What the code shows

- The schema's `activation.kind` enum is closed
  (`numan-registry/schemas/index-v1.json:221-230`), and Rust's `ActivationKind` rejects unknown
  values (`numan/src/core/package.rs:606`). `RegistryActivationSpec` contains the per-kind
  fields (`:637`).
- `VersionEntry.activation` is `Option`, and its comment says `None` means plugins and
  install-only packages (`numan/src/core/package.rs:123-150`). `PackageType` is a separate
  closed enum with `plugin`, `module`, `script`, and `completion`; there is no explicit
  `install-only` type.
- The client infers display labels from package type and activation presence:
  `numan/src/cmd/info.rs:64-101` distinguishes declared scripts/completions from install-only
  ones. Install logic switches on `ActivationKind` in
  `numan/src/install/transaction.rs:425`, `:441`, `:501`, and `:648`.
- Activation behavior is spread across `numan/src/cmd/activate.rs`,
  `numan/src/cmd/plugin_lifecycle.rs`, `numan/src/cmd/hook.rs`, and
  `numan/src/cmd/deactivate.rs`. The `RegistryActivationSpec` doc comment states that each kind
  is handled by its explicit capability command. That is a coherent contract, but not a single
  dispatch point.
- The schema does not express conditionals such as "module requires `nu-module`" or
  "overlay requires `nu-overlay` and an entry." Those checks currently live in client code and
  intake helpers.

### Corrections to the proposal

- "Introduce a closed set of `activation.kind` values" is already done. Do not add
  `plugin` or `install-only` to `ActivationKind`: that enum is the runtime wiring contract for
  activation commands. A plugin is not a way to activate; it is a package behavior.
- Add a separate required `primary_kind` (or `behavior.kind`) to the descriptor with the closed
  set: `plugin`, `nu-module`, `nu-overlay`, `nu-hook`, `nu-script`, `nu-completion`,
  `install-only`. Keep `activation` for the configuration of the five command-backed kinds.
  This correction avoids overloading a field whose runtime meaning is already precise.

### Incremental delivery

1. Add `primary_kind` to descriptor v1 and index schema v2. Make it required for new entries.
2. Add schema conditionals and a registry validator for the type/kind table:
   module -> `nu-module`; overlay -> `nu-overlay` plus entry; hook -> `nu-hook`; script ->
   `nu-script` or `install-only`; completion -> `nu-completion` or `install-only`; plugin ->
   `plugin` and no activation object.
3. Add one client mapping function that converts `(package_type, primary_kind, activation)` into
   the behavior used by install/activate/doctor. Keep the existing command paths; do not perform
   a broad activation refactor in the descriptor release.
4. Dual-write: synthesize `primary_kind` for old entries from `package_type` and activation
   presence, and prefer an explicit value when present. Old clients ignore the new field.

### Backward compatibility

The existing `activation` object and `package_type` remain authoritative for old entries and old
clients. New clients synthesize a missing `primary_kind` during the transition; no lockfile
migration is required until the field becomes required.

### Exit criterion

After two releases, require `primary_kind` in validation and remove the inference branches.
Delete the synthesis path when no supported index lacks the field.

### Trust model

Unchanged. `primary_kind` is signed data inside the same index. It changes which local behavior
is selected, not which key is trusted or how a signature is verified.

### Effort

2-4 engineer-days: one day for schema/conditionals, one day for validator/tests, one to two days
for the client mapping and compatibility checks. If done inside the descriptor release, the
incremental cost is closer to 1-2 days.

## 4. Multi-registry read support and key identity

### Problem

The trust model is close to multi-registry, and configuration/verification partly exist, but
the user-facing read commands still use one default registry, and the lockfile discards the
key-id that verified the entry.

### What the code shows

- `Config` has a `HashMap<String, RegistryConfig>` and `RegistryConfig` has `url`,
  `sync_interval`, `enabled`, and optional `trust_key` (`numan/src/config.rs:10-17`, `:38-46`).
  `numan registry add` writes the key into `TrustStore` keyed by registry name and stores the
  same key in config (`numan/src/cmd/registry.rs:139-165`).
- `RegistryManager` supports named indexes, signature verification, last-known-good indexes, and
  derived successor keys (`numan/src/core/registry.rs:57-109`, `:248-349`). This is real read
  infrastructure, not a blank design.
- `search` and `find_package` are hard-wired to `default_registry()`
  (`numan/src/core/registry.rs:180-202`). `install` constructs `InstallOptions` with
  `registry_name: None` (`numan/src/cmd/install.rs:78`) and resolves compatibility against the
  default (`:104`). `try` loads the default (`numan/src/cmd/try_cmd.rs:299`). `update` resolves
  each entry's recorded registry (`numan/src/cmd/update.rs:828`).
- `LockfileEntry` records `registry_url` as `registry:<name>`, plus `registry_revision`,
  `index_sha256`, and `signing_key_fingerprint` (`numan/src/state/lockfile.rs:304-345`;
  populated at `numan/src/install/transaction.rs:534-537`). It does not record `key_id`, even
  though `VerifiedRegistry` carries one (`numan/src/core/registry.rs:18-23`).
- Custom-registry trust is keyed by registry name. `base_trust_root_for` explicitly uses the
  registry name as the key-id for backward compatibility until explicit key-id support exists
  (`numan/src/core/registry.rs:57-69`). The official registry uses the built-in trust root.

### Corrections to the proposal

- "Keep the built-in official trust root as the default first entry" is already true: the
  official registry is the default, and `init` ensures it when the key is not a placeholder
  (`numan/src/cmd/init.rs`).
- "Implement read support for additional signed registries first" is only partly true. The
  manager can load a named signed registry; the commands cannot yet choose one consistently.
- "Record registry + key_id in the lockfile" is not done. Recording only a fingerprint is
  weaker for auditing and for distinguishing a rotated key with the same registry name.

### Incremental delivery

**Phase A - lockfile identity (1-2 days).**
Add `registry_name` and `key_id` to new lockfile entries. Keep `registry_url` for old readers.
Derive old entries from the existing `registry:<name>` string and leave `key_id` absent when it
cannot be recovered. The new fields come from `VerifiedRegistry.registry_name` and
`.key_id`, which already exist.

**Phase B - trust configuration (1-2 days).**
Add optional `key_id` to `RegistryConfig` and let `TrustStore` store a key under
`(registry_name, key_id)`. Preserve the current name-as-key fallback for existing configs.
This does not change signature verification; it only identifies which already-trusted key
verified the index. Successor keys introduced by a signed index continue through the existing
`persist_derived_keys` path.

**Phase C - command-level read selection (3-5 days).**
Add a registry selector to `install`, `try`, `info`, and `search`, and define ambiguity policy
when the same package ID exists in multiple enabled registries. Prefer an explicit `--registry`
over the configured default, and keep the official registry first. Reuse the existing
`update` entry-registry behavior as the model.

**Phase D - dual-read and migration (1-2 days).**
Old lockfile entries continue to reconstruct the registry name. New entries always carry
`registry_name`, `key_id`, and the descriptor digest from item 1. Keep write/publish
official-only. Multi-registry writes are a separate product and trust decision, not part of this
item.

### Backward compatibility

Old configs and lockfiles keep working through the name-as-key fallback and the existing
`registry_url` string. New `key_id` fields are optional for old entries and required for entries
written after the client migration. No existing registry trust root changes.

### Exit criterion

Every read command honors an explicit registry and all new lockfile entries carry key identity.
Remove the name-as-key fallback only after that migration window; keep write/publish
official-only.

### Trust model

Unchanged, and this is the item where that must be stated most carefully. Each additional
registry is trusted only through its own explicitly configured trust root. Listing a registry
in config does not trust its index; a valid signature under a trusted key does. The official
built-in key remains the default. There is no fallback to unsigned data, no automatic trust of
an arbitrary URL, and `NUMAN_ALLOW_UNSIGNED=1` remains a development-only escape hatch, not a
multi-registry feature. An index-declared successor key is still accepted only through the
existing signed trust-extension path.

### Effort

6-10 engineer-days for read support: 1-2 lockfile, 1-2 trust identity, 3-5 command/policy work,
1-2 tests and migration. Publishing/writing to non-official registries would add roughly 10-15
days and is deliberately not scheduled here.

## 5. Content-addressable payload store

### Problem

Payloads are immutable and hashed, but storage is still keyed by package version plus an
eight-character prefix. Identical payloads across versions are not shared, and migration,
garbage collection, and multi-root experiments all have to reason about version-shaped paths.

### What the code shows

- The install directory is
  `packages/<type-dir>/<owner>/<name>/<version>-<first-8-of-artifact-sha>`
  (`numan/src/install/transaction.rs:246-256`). The download cache uses the full artifact SHA
  (`:264`).
- The lockfile records `payload_path`, `payload_sha256`, `revision_id`, and
  `artifact_sha256` (`numan/src/state/lockfile.rs:304-345`). `revision_id` is a deterministic
  manifest hash over sorted `path:sha256:kind` lines (`:842`), and it is computed at install
  time (`numan/src/install/transaction.rs:492`).
- There is no content-addressed directory, no content-addressed path helper, and no migration
  command in the client. A repository search found no such implementation.
- The lockfile already has the integrity primitives needed for CAS. The missing part is a
  resolver and migration story, not hashing.

### Why this is not next

The proposal is right to call this "carefully." A CAS changes the meaning of `payload_path`,
touches activation records, doctor/gc/update/rollback/snapshot, and has to preserve the journal
and lockfile guarantees throughout. Doing it before the descriptor and lockfile schemas are
stable would force a second migration immediately afterward.

### Incremental delivery

1. **Freeze the identity inputs first.** Land descriptor/lockfile v3 and make `revision_id`
   mandatory for new installs. Define two content identities: the archive digest
   (`payload_sha256`) and the installed-tree manifest (`revision_id`). Do not conflate them.
2. **Add a read-only CAS resolver behind the current path API.** New installs write to a new
   content-addressed directory keyed by `revision_id` and also keep the legacy path available.
   Activation records reference the revision identity, not a version-shaped directory. The
   lockfile can carry both `payload_path` (resolved) and an optional legacy path.
3. **Migrate in a doctor command.** `numan doctor --migrate-cas` should copy or hardlink
   verified trees, verify every file against `revision_id`, and be idempotent. Run it on a
   snapshot/rollback test before enabling automatic migration.
4. **Move all operations to the resolver.** `activate`, `remove`, `gc`, `update`, `rollback`,
   `snapshot`, and `try` must use the same path helper. Keep reads of the legacy layout for one
   release.
5. **Make CAS primary in a major release.** New installs never create a version-shaped payload
   path. The old path becomes read-only for migration, then is deleted.

### Backward compatibility

The legacy version-shaped payload path remains readable for one full release while new installs
write both locations. Existing lockfiles keep their `payload_path`; activation records are
migrated or resolved through the new helper. No lockfile is rewritten in place until the
migration command has verified every payload against `revision_id`.

### Exit criterion

CAS is primary only when all new installs resolve through it, the migration command has run
successfully against a representative root, all operation tests pass with both layouts, and one
full release has shipped with dual-read. Then remove the legacy path writer, keep a read-only
migration path for one more release, and delete it at the next major.

### Trust model

Unchanged. CAS is local storage. The registry signature still authenticates the artifact URL and
declared SHA-256; the client still verifies the downloaded artifact before writing it. CAS
adds a local content check, not a new registry authority, and it must never allow an unsigned
artifact to be treated as verified.

### Effort

15-25 engineer-days plus a major-release window: 3-4 for the store/resolver, 4-6 for migration
and GC, 4-6 for operation integration and rollback testing, 4-6 for cross-platform tests and
rollout. This is the highest-risk item and the only one where a partial migration can leave
users with broken activation records.

## Recommended sequence

1. **Client compatibility release:** accept index schema 1 and 2; add lockfile v3 read/write
   scaffolding for descriptor and registry/key identity. No registry v2 publication yet.
2. **Descriptor v1 + index v2 dual-write:** canonicalization module, descriptor schema,
   producer emission, intake verification, proof/primary-kind fields, legacy fields retained.
3. **Proof and activation cleanup:** derive `verified_with`, add the consistency check, require
   `primary_kind`, keep synthesis for old entries.
4. **Multi-registry reads:** lockfile `registry_name`/`key_id`, explicit registry selection,
   ambiguity policy. Writes stay official-only.
5. **CAS parallel store:** new installs write CAS plus legacy, migration command, resolver
   across operations.
6. **CAS primary:** only after the descriptor and lockfile are stable and one release of
   dual-read has passed.

Do not run steps 4 and 5 as parallel "design now, implement soon" work. Both touch the lockfile;
step 5 also touches activation and rollback state. Sequential delivery is cheaper than resolving
two migrations in the same release.

## What is already done vs. still open

**Already done, and should not be rebuilt:**

- Lifecycle proofs in the signed schema, typed client model, production gate, and `info`/`try`
  display.
- Closed activation-kind enum and typed deserialization.
- Whole-index Ed25519 signing and verification, including successor-key handling and
  last-known-good indexes.
- Per-registry config, trust-key storage, and named-index verification in `RegistryManager`.
- Artifact SHA-256 verification, immutable payload directories, `payload_sha256`, and
  `revision_id` computation.

**Still open:**

- A versioned descriptor schema and digest.
- Descriptor storage in the lockfile.
- Derived `verified_with` and its consistency check.
- A required primary kind for plugin/install-only packages.
- End-to-end registry selection for all read commands and key-id recording in the lockfile.
- A CAS layout, migration command, and resolver.
- Multi-registry writes, which this document deliberately leaves out of scope.

## Verification of the claims in this document

- All cited paths were checked in the three local repositories on 2026-11-12.
- The current-index census and proof-gate result were produced by loading
  `numan-registry/registry/index.json` and calling `lifecycle_proof_errors` from
  `numan-registry/scripts/ci-sign.py`: 94 versions, 89 activatable, 86 live activatable checked,
  0 proof errors, 5 install-only versions without proofs, 3 failed-proof yanked versions.
- `verified_with` and passed proof `nu_version` sets match for all 86 live activatable versions
  in the current index. The recommendation is to make that invariant enforced rather than
  conventional.
- No runtime code, schema, or workflow was changed to produce this document.
- Final-tree checks completed on 2026-11-12: the Python discovery suite ran 911 tests and passed
  with 1 skipped; the Node catalog suite passed 11 of 11 tests; the workflow checker validated
  10 tracked workflow files and 12 when untracked files were included, both passing.
