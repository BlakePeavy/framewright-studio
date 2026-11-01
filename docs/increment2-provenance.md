# Increment 2: provenance and repair transactions

Implemented 2026-10-30 for FW-010/FW-013 and the metadata/landmark intake portion of FW-020. This increment does not approve art, license ownership, benchmark references or Sundown delivery.

## Asset evidence

`framewright.provenance` defines strict schema `1.0` JSON manifests. Each has a retained UUID, nullable source SHA256, named authoring recipe with parameters, references, hashed parent manifests, expected views and independent verification states. Unknown source hashes, origins and licenses remain unknown. Derivatives receive a new identity, preserve their direct parent's identity/hash and reference metadata, and start with every verification state unchecked. Source, export, native import, placement, cold verification, runtime binding and visual acceptance never imply one another. Checked states require caller-supplied evidence descriptions; the library does not certify those claims.

Canonical JSON uses sorted string keys, compact separators, UTF-8 and finite JSON values; it is this package's deterministic encoding, not a claim of RFC 8785 compliance. Manifest hashes cover that encoding. File hashes stream the actual bytes with a configurable size limit and detect ordinary file changes during reading. Save refuses existing destinations; load rejects oversized documents, duplicate keys and unsupported schemas.

`create_reference` records metadata without reading a file. `intake_reference` reads and hashes the explicitly supplied original file, records its resolved original path, and never copies, modifies or transmits it. Reference origin is `unknown`, `real_photo`, `generated`, `user_authored` or `external_asset`; license is a supplied string, default `unknown`. Views are user labels; landmarks have a name, listed view and normalized two-coordinate image position. Validation lists missing expected views. These records do not prove the image was visually reviewed. A reference-board UI and approved benchmark collection remain separate work.

Pure handlers accepting a parameters dictionary:

- `create_manifest({name, asset_id?, source_sha256?, recipe?, references?, expected_views?})`
- `validate_manifest({manifest})`: normalized manifest, canonical hash and missing views
- `derive_manifest({parent, name, source_sha256?, recipe?})`
- `create_reference({label, reference_id?, origin?, location?, license?, sha256?, views?, landmarks?})`
- `add_reference({manifest, reference})`
- `record_verification({manifest, stage, status, evidence})`, with evidence as an array of strings
- `intake_reference({path, label, origin?, license?, views?, landmarks?, max_bytes?})`

`save_manifest(path, manifest)` and `load_manifest(path)` are explicit local helpers. No source asset is automatically added to Git or uploaded.

## Supported repair transaction

`framewright.blender_transactions` exposes a bounded loose-vertex repair on eligible local static meshes. Planning is read-only. Apply requires the exact plan token, matching source fingerprint and `dry_run: false`; it creates a hidden editable derivative through the existing adapter. Source data, selection and active object remain unchanged. The derivative receives persistent UUID and ownership tags, but those tags alone never authorize rollback.

- `plan_remove_loose({object_name})` returns a deterministic plan for the current object state/session generation.
- `apply_plan({plan_token, source_fingerprint, dry_run: false})` consumes the plan and returns a transaction ID.
- `cancel_plan({plan_token})` invalidates a pending plan without changing the scene.
- `rollback_plan({transaction_id, dry_run: false})` deletes only the exact unchanged owned derivative and its unshared mesh.

Fingerprints stream topology, coordinates, normals, custom mesh attributes/UVs, supported transform channels, material identities, collection membership and custom properties. Blender `session_uid` prevents object memory-address reuse from authorizing stale plans. Derived cached world matrices are excluded: these sources cannot have parents, constraints, animation or modifiers, and their transform channels define the supported transform state. Selection/edit-visibility flags are UI state and excluded. Material shader graphs, image contents and external shared datablocks require separate checks; a geometry fingerprint does not certify them.

Plans and rollback records exist only in the current Blender Python process. A serialized token from a different process or reopened file is rejected. Batch callers must plan/apply in one process, for example through the workflow runner. Repeated application of a consumed token fails; a fresh explicit plan can start a new generation. Rollback refuses changed, replaced, renamed, foreign or shared derivatives. Ownership tags surviving a file save do not restore deletion authority after restart. Cross-process recovery is not implemented.

## Verification evidence

- Wrote provenance tests first; the initial run failed because `framewright.provenance` did not exist. Implemented the module; 20 pure-Python tests passed.
- Added a failing `external_asset` origin test for third-party authored assets; expanded the enum without implying authorship or verified licensing. All 21 provenance tests passed.
- Wrote transaction integration tests first; isolated Blender 5.2.1 failed because `blender_transactions` did not exist. Implemented the module; the initial 13 tests passed.
- Added real regressions for dependency refresh, cancellation and custom attributes/properties. The refresh test failed on a cached `matrix_world`; repeated fixture creation also exposed reuse of deleted object addresses. Removed the derived matrix from the supported-state hash and used `session_uid` identities. All 17 transaction tests then passed.
- Tests cover exact source preservation, changed coordinates/topology/UVs/material identities, explicit apply, cancellation, replay rejection, foreign-scene rejection, injected post-creation failure cleanup, rollback preservation of edited or forged objects, and shared-mesh refusal.

Run pure checks with `uv run python -m unittest discover -s tests -p test_provenance.py -v`. Run the transaction suite with Blender's `--background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_transactions.py`. No live scene or game files are used.
