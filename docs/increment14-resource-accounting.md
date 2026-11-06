# Evaluated resource accounting

`scene.resources` previously failed when Blender supplied an evaluated mesh whose
original data was an editable curve or text object. Reading
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

## Regression coverage

Ten new Blender tests and nine independent review tests pass, with genuine failing
baselines retained. They cover legacy/modern converted sources, shared data with
distinct modifiers, nested instances, generated materials/images, mixed components,
LOD typing and source/temporary-ID preservation. The 16 existing production tests,
two benchmark fixtures and five callback tests also pass.

Focused evidence is retained locally under `artifacts/resource-reporting/` and
`artifacts/resource-review/`. These generated reports are not included in Git.

The complete release aggregate is recorded separately in [verification](verification.md).
These tests establish this reporting scope, not artistic or native-game acceptance.
