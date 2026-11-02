# Bounded native mesh fidelity

The original 8K cabinet's **29 SourceModel meshes / 5,836 triangles** preserve all
measured GLB attributes. Saved RenderData fails UV precision. An unsaved
full-precision UV rebuild passes. This is diagnostic evidence; the production
importer still used the original precision settings at this checkpoint. The later
[initial-import fix](native-uv-precision.md) passes fresh/cold full mesh checks.

See the [receipt](../artifacts/verification/native-mesh-fidelity-20261101.json)
and [per-mesh results](../artifacts/native-mesh-fidelity-20261101/native-comparison.json).

## Measurement

An independent geometry-only decoder reads the pinned GLB's indexed triangles,
explicit split normals, both UV channels and material names without decoding its
8K textures. It maps local meters into Unreal centimeters. Native GeometryScript
readback retrieves every corner attribute and per-triangle material ID from both
SourceModel and RenderData. Triangle ordering may change; winding may not.

A bounded bijective matcher preserves multiplicity, cyclic corner correspondence,
UV channel counts and material identity. Position tolerance is 0.001 cm, split
normal tolerance 1 degree and UV tolerance 1e-6 (about 0.0082 pixels at 8K).
The normal tolerance accommodates the observed quantized tangent basis; this is
separate from the [rendered normal field gates](native-normal-validation.md).

| Observation | Matched triangles | Max position error, cm | Max normal error | Max UV error |
|---|---:|---:|---:|---:|
| Saved SourceModel | 5,836 | 0.00000191 | 0.00000121 degrees | 0 |
| Saved RenderData | 0 complete matches | 0.00000191 | 0.33769 degrees | 0.000244140625 |
| Unsaved full-precision RenderData | 5,836 | 0.00000191 | 0.33769 degrees | 0 |

Every saved render triangle has corresponding positions/winding, but its UVs
exceed the strict preservation threshold. The maximum displacement is two pixels
at 8192 resolution. Both UV channels and material assignments are included.

## Verification and preservation

Eight comparator tests cover reordering, tolerance boundaries, winding, interior
vertex changes, corrupt normals/UVs/materials, coincident-triangle multiplicity,
missing UV channels and invalid values. Six decoder tests cover asymmetric
axes/units, interleaved normalized UVs, view boundaries, channel gaps, source pins,
unknown attributes and nonfinite coordinates. New boundary/channel regressions
failed before their fixes. Python 3.15.2 and Ruff pass; no full suite ran.

One hidden Unreal 5.8.3 worker took 15.92 seconds. It read the original saved
assets, temporarily changed only full-precision UV build settings, captured
RenderData, restored the settings and discarded owned dirty packages on exit.
All 354 input/source/package pins remain identical. No import, bake, render,
Sundown write or saved fixture change occurred.

Cached bounds exactly match measured vertex bounds before/after this rebuild.
The earlier [bounds discrepancy](native-surface-review.md) was not reproduced;
its failed evidence is retained and its original gate is unchanged. This result
does not explain the earlier failure or authorize weakening the bounds gate.

## Remaining work

The [initial-import follow-up](native-uv-precision.md) now implements and verifies
full precision using a fixed transient pipeline copy. Collision/LOD is next.

This fixture has no exported tangents or vertex colors; the decoder rejects
unmeasured attributes. It consumes an already admitted GLB, not arbitrary input.
Collision, LOD transitions, broader material-slot cases, linked-map minification,
shader/GPU readiness, lighting, runtime performance and artistic acceptance remain
open. The sealed 0.9 package and roadmap row states are unchanged.
