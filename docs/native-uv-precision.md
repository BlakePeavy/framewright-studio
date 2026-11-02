# Full-precision native UV import

The unreleased native importer now preserves full-precision UVs at initial import.
The original half-precision path shifted UVs by up to two pixels at 8K. A fresh
import and cold reload now preserve both exported UV channels exactly across all
5,836 triangles of the 29-mesh cabinet. This closes the bounded UV transport defect.

## Implementation

**FramewrightNativeBridge 0.2.0** adds a no-argument editor function that duplicates
the fixed installed `DefaultGLTFSceneAssetsPipeline` into the transient package.
It verifies that the copy and its instanced mesh properties differ from the
original, then changes only `bUseFullPrecisionUVs`. The installed asset is unchanged.
Caller-selected paths, classes or scripts are not accepted. The function requires
the editor game thread outside PIE and performs no import or save.

The Python backend requires an active owner lease and a valid transient pipeline
with full precision enabled before invoking the existing synchronous importer.
The other two fixed GLTF/scene pipeline entries stay in order. Readback independently
requires LOD0 full-precision build settings and records `mesh_precision` in inspection
and apply receipts. Missing/older companions or half-precision meshes refuse;
there is no fallback or automatic migration of existing assets.

Full precision consumes more UV vertex-buffer memory than half precision. This
change prioritizes faithful transport; game performance budgets still need actual
runtime measurement. It does not raise texture resolution or certify artistic quality.

## Evidence

[Receipt](../artifacts/verification/native-uv-precision-20261101.json),
[fresh comparison](../artifacts/native-uv-precision-20261101/native-comparison.json)
and [cold comparison](../artifacts/native-uv-precision-20261101/cold-comparison.json).

- Nine new regressions failed before implementation and pass afterward. They cover
  initial pipeline selection, missing/invalid companions, saved/half-precision
  pipeline rejection, expired ownership and independent mesh-setting readback.
- All 51 affected native contract/readiness cases pass on Python 3.15.2; Ruff passes.
  No full suite ran. The existing 14-test independent geometry decoder/matcher is reused.
- The editor companion builds with the verified VS2022 toolchain in 16.67 seconds.
- One fresh import takes 63.48 seconds; one cold readback takes 20.50 seconds.
  Both SourceModel and RenderData match all 5,836 triangles, winding, explicit split
  normals, both UV channels and material assignments. Maximum position error is
  0.00000191 cm, split-normal error 0.33769 degrees and UV error zero. Cached bounds
  match measured vertices; the original hierarchy/transform/bounds gates also pass.
- Three cold 8K textures complete through the scoped texture bridge (pending 3→0).
  The new namespace contains 34 imported assets and one map. All 462 old/new
  source, code, engine pipeline and saved-file pins remain identical after cold reload.

The existing cabinet GLB and explicit 512 MiB / 201,326,592-pixel admission budgets
were reused. No texture bake, render, old-fixture rewrite or Sundown write occurred.
The earlier unsaved-rebuild bounds failure remains unexplained; this successful
initial-import route does not weaken its gate or erase that evidence.

## Companion and remaining scope

Use the [0.2.0 Win64 companion](../artifacts/native-uv-precision-20261101/framewright-native-bridge-0.2.0-ue5.8.3-win64.zip)
with this checkout. It includes source, GPL license, DLL and module manifest for
Unreal 5.8.3 build ID `55116800`. Installation and compatibility rules are in
[native texture readiness](native-texture-readiness.md). The Blender 0.9 ZIP and
the earlier 0.1.0 companion remain immutable historical releases.

The regular import receipt still reports only its implemented metadata/settings
scope. Full triangle comparison is independent fixture evidence, not an automatic
production acceptance field. The fixture has no exported tangents or vertex colors
and only one material. Broader geometry/material cases, collision/LOD, linked-map
minification, shader/GPU readiness, lighting, runtime and art acceptance remain open.
Next: native collision/LOD checks against the existing Blender derivatives.
