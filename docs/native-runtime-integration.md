# Native runtime integration — unreleased

The initial native integration validated two production modules against isolated
UE 5.8.3 import/cold readback. The checkout now also includes [scoped texture
readiness](native-texture-readiness.md), requiring an editor companion. The
sealed 0.9 install/source archives remain unchanged.

- Resolve Unreal's trusted project-path result through its native absolute-path
  API before checking the exact target. Caller paths remain strictly validated.
- Preserve the optional GLB scene name. Admit only the matching owned plain actor
  with one empty root, an identity transform and exact source parent relationships.
  The container stays intact; only its verified hierarchy level is normalized in
  comparison. Extra/missing nodes, collisions and foreign/nonempty actors fail.
- Use the reflected actor root property and editor-property reads for material
  sidedness overrides, retaining inheritance and cyclic-parent guards.

## Verification

The [receipt](../artifacts/verification/native-integration-20261101.json) records
204 focused cases on Python 3.15.2: 202 initial passes plus two fixture rechecks.
Those fixtures modeled a non-reflected root getter; they now expose the actual
property. The positive root-mesh and negative offset-child checks both pass.
Four additional scene-name admission controls pass. Changed-file Ruff is clean.
Earlier failing-then-passing implementation evidence is retained; no full suite
or engine run was repeated for this byte-identical integration.

The [actual native receipt](../artifacts/verification/native-isolated-20261101.json)
uses the original 0.8 cabinet: 29 meshes, a door pivot and three 8192px textures.
Warm import saved 34 owned packages. Cold readback preserved all saved bytes and
restored Initial. That receipt pins the original engine-tested module bytes;
the later readiness increment has its own changed-source/native receipt.

Cold texture queries initially returned 32px asynchronous placeholders. The
disposable harness loaded owned packages and finished compilation before comparing
unchanged expectations. That process-wide compilation barrier is confined to the
isolated harness. The new companion completes only validated owned texture builds
before adapter readback; shader/GPU readiness remains open. Existing plans must be recompiled to include
the newly retained scene identity; plan verification still rejects changed inputs.

A later [two-view native base-color study](native-appearance-review.md) adds bounded
pixel evidence with material-loss controls. It leaves complete texture/lighting
appearance and production acceptance open.

This verifies bounded node/hierarchy/transform/count/material-slot/settings behavior.
Full surface geometry, decoded texture pixels, rendered appearance, collision/LOD,
runtime performance, artistic acceptance and Sundown integration remain open.
No Sundown asset, shared editor, release archive or Git staging was changed.
