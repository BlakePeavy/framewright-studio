# Evaluated mesh and surface diagnostics

Implemented FW-011/FW-012 inspection capabilities on 2026-10-30. These produce structural evidence, not artistic approval or an exporter compatibility certificate.

## API

`mesh.inspect_evaluated` dispatches to `mesh_diagnostics.inspect_mesh(params, context=None)`. `surfaces.inspect` dispatches to `surface_diagnostics.inspect_surfaces(params, context=None)`.

Both accept:

| Parameter | Meaning |
|---|---|
| `object_name` | Required exact name of one mesh in the active scene; ambiguous local/linked names are rejected |
| `evaluated` | Boolean, default `true`; inspect current-frame viewport modifier output |
| `max_triangles` | Positive integer, default 20,000, maximum 200,000; deterministic triangle prefix for intersection/UV analysis |
| `max_pairs` | Positive integer, default 100,000, maximum 2,000,000; bounds X-overlapping candidate visits |

Mesh inspection also accepts `open_boundary_allowed` (boolean, default `false`). Surface inspection accepts `allow_stacked_uvs` (boolean, default `false`) and optional `uv_layer` (exact layer name; otherwise active layer).

The standalone functions validate these arguments independently of the dispatcher, enforce main-thread/Object Mode access, and do not select objects or change modes. Both original and evaluated inspection use a temporary `to_mesh()` result with all data layers preserved; `to_mesh_clear()` runs in `finally`, including failure paths. Linked assets are read-only inputs.

## Findings and coverage

Mesh results include counts for vertices, edges, faces, actual tessellated triangles, boundary/wire/branching edges, exact-position duplicate faces and zero-area faces. Intersection checks use an X-axis sweep, bounding boxes and triangle geometry. Coplanar triangles are clipped in 2D; noncoplanar triangles use overlap of plane-intersection segments. Same-polygon tessellation pairs and true noncoplanar shared-edge neighbors are excluded. Folded coplanar neighbors with positive-area overlap remain findings.

UV checks detect sampled zero-area triangles and positive-area overlaps. Shared edges/points are not overlaps. Intentional stacking suppresses the overlap finding while retaining its measured count. UVs stay in absolute coordinates, so distinct UDIM tiles are not wrapped together. Tile IDs are inferred from sampled triangle vertices nudged toward the centroid; crossing-tile triangles and coordinates outside the supported 1001–2000 grid are reported.

Material checks inspect effective mesh material slots, object material overrides, active output graphs, directly connected Principled surfaces, unsupported nodes, tangent normal-map space, referenced external files and data color-space metadata. Roughness, metallic and normal input traces report observed image/channel mappings. Feeding metallic and roughness from the same image channel requests a packing review; an image's alpha output is not incorrectly treated as color-transformed RGB. Node-group socket semantics are explicitly uninspected. Generated/packed images are distinguished from missing external files by the existing adapter helper.

`coverage` is `partial` when the intersection/UV budget omits work, a UV layer is missing, or unsupported material groups/graph limits prevent complete tracing. Pair reports retain total/tested/omitted triangle counts, candidate visits, triangle and polygon pair samples, and sample truncation. Pair/finding element samples are capped at 100. Empty findings on a partial report do not establish a clean asset.

## Verification

- Wrote pure geometry tests before implementation: initial pytest collection failed because `mesh_diagnostics` did not exist. Implemented the algorithms; 15 tests passed.
- Added a translated small-UV regression; it failed because the original area sum lost precision far from the origin. Replaced it with origin-relative triangle area accumulation; **16 pure tests pass**.
- Wrote real Blender fixtures before surface implementation: initial background run failed because `surface_diagnostics` did not exist.
- First integrated run exposed a linked/local name collision. Added explicit ambiguity rejection and verified separately named linked assets without changing their data.
- **9 Blender fixtures pass** on Blender 5.2.1 LTS, including evaluated Array output, selection/source preservation, cleanup after injected diagnostic failure, boundary policy, duplicates, crossing triangles, bounded coverage, UV policy, linked files, color/data encoding, packed channels and missing images.
- Ruff lint and formatting pass for the two modules and their tests.

```powershell
uv run --python 3.11 python -m pytest tests/test_geometry_algorithms.py -q
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_diagnostics.py
```

## Limits requiring later gates

Dependency-graph evaluation and Blender tessellation can still be expensive and are not interruptible inside this call. Topology counts/duplicate-face inspection read the complete produced mesh; triangle/pair bounds apply to the more expensive overlap stages, not Blender's modifier allocation. Geometry is measured in object-local coordinates with a fixed `1e-8` length tolerance; near-degenerate geometry and point contacts below tolerance need review. Exact duplicate-face detection uses matching vertex positions, not a tolerant spatial weld.

Only the current viewport evaluation/frame is inspected. Render-only modifiers, geometry-node instances that remain unrealized, motion/deformation through time, topology intent, texel density, tangent parity, texture contents, complete UDIM tile coverage, all sequence frames, bake results, and export/native rendering remain separate gates. Material procedural/group graphs require bake/export review; the supported node subset is a diagnostic heuristic.

The linked fixture writes only an isolated synthetic **object** library into a temporary folder. It does not save any live Scene-ID or game asset. No private reference or game asset was modified.

## Source basis

Consulted bundled official Blender API/manual documentation for `Object.to_mesh(preserve_all_data_layers=True, depsgraph=...)`, temporary mesh ownership and `to_mesh_clear()`, plus Normal Map and glTF material rules. Corresponding official references: [Object API](https://docs.blender.org/api/5.2/bpy.types.Object.html), [Dependency graph examples](https://docs.blender.org/api/5.2/bpy.types.Depsgraph.html), [Normal Map](https://docs.blender.org/manual/en/5.2/render/shader_nodes/vector/normal_map.html), [glTF materials](https://docs.blender.org/manual/en/5.2/addons/import_export/scene_gltf2.html).
