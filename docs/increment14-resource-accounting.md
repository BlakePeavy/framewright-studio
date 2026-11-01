# Evaluated resource accounting

The carrier cinematic exposed a real `scene.resources` failure: Blender supplied an
evaluated mesh whose original data was an editable curve or text object. Reading
that original's `polygons` raised `AttributeError`. The correction counts evaluated
mesh components while retaining the distinction between original meshes and other
source types. It also includes materials/images introduced by Geometry Nodes.

Blender can expose both a legacy curve/text/surface/metaball occurrence and its
implicit mesh component. The implementation counts the component once and matches
its exact source/parent/persistent path to classify it as direct or instanced.
Real collection and Geometry Nodes instances retain their separate occurrences.
Blender's [geometry-set documentation](https://developer.blender.org/docs/features/objects/geometry_sets/)
explains why one evaluated object may contain multiple component types.

## Output contract

- `mesh_objects`, `referenced_mesh_objects`, `unique_mesh_datablocks` and
  `source_triangles_unique` retain their original-mesh meanings.
- `referenced_converted_source_objects`, `unique_converted_source_datablocks` and
  `converted_source_objects` identify conversion-eligible legacy sources, including
  hidden sources, and other non-mesh sources actually observed producing meshes.
  They do not assert that every source has a visible evaluated mesh.
- `geometry_by_source_type` separates original types and reports measured mesh
  occurrences, triangle/vertex/edge totals and unique source data. Evaluated uniqueness
  is a source-object/evaluated-data pair, not a GPU allocation.
- `unsupported_geometry_outputs` identifies unmeasured curves, point clouds,
  volumes and Grease Pencil components, including mixed Geometry Nodes outputs.
  These are observations and can overlap; do not add them as physical geometry counts.
- LOD counts remain original-mesh only; non-mesh LOD metadata is reported explicitly.
  Material/image counts cover original and evaluated references, including unused slots.

The command remains read-only and uses the first view layer at the current time.
It does not measure rendered visibility, native draw calls, GPU residency or whole
animation memory. Temporary `to_mesh` data is released on success and failure.

## Test-first and retained-scene evidence

Ten new Blender tests and nine independent review tests pass, with genuine failing
baselines retained. They cover legacy/modern converted sources, shared data with
distinct modifiers, nested instances, generated materials/images, mixed components,
LOD typing and source/temporary-ID preservation. The 16 existing production tests,
two benchmark fixtures and five callback tests also pass.

The unchanged original **Blue Horizon.blend** now succeeds directly at frames 1 and
330, without conversion or a saved derivative. At each frame it reports **458,951
evaluated triangles**: 249,846 from original meshes, 124,176 from curves and 84,929
from text. It identifies 1,662 original mesh objects and 769 curve/text sources;
the authored instance count is zero. All 60 materials are procedural (zero images).
Original objects/data/actions, selection, frame and saved file bytes are preserved.

Evidence: `artifacts/resource-reporting/focused-receipt.json`,
`artifacts/resource-review/independent-review-receipt.json`, and
`artifacts/resource-reporting/retained-carrier-{before,final}.json`.
The actual source `.blend` SHA256 remains
`b3024a2934d99605ef153604d4e99bcdd85392278c223b8e8d734fdb6c951b6f`.
The tested runtime SHA256 is
`59f9c5bbdd6c827d30dca073e5d6f1858df0134e54dbcf9c7bfa92f6df67f3d4`.

The complete release aggregate is recorded separately in [verification](verification.md).
These tests establish this reporting scope, not artistic or native-game acceptance.
