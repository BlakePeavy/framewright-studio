# Convex hull correction and native derivative gap

> Scope update (2026-11-01): engine integration/testing is deferred. This record
> is historical, not an instruction to resume Unreal work. The Blender hull
> correction remains applicable; destination-specific follow-ups are outside scope.

The collision builder now creates a clean outer hull from evaluated source points.
The retained thin-fin fixture exposed internal source faces surviving the previous
`bmesh.ops.convex_hull` call. Passing existing faces and removing only the returned
interior/unused vertices was insufficient when interior faces joined hull vertices.

## Verified correction

One new Blender regression fails on the original builder, then passes with the
point-only construction. It checks closed manifold edges, Euler characteristic,
positive signed volume, outward convex planes, original object/selection/frame
preservation and matching derivative transforms. The existing collision and LOD
preservation checks also pass: three focused cases total, not a full-suite rerun.
Ruff passes; the import-order-only lint change does not alter test behavior.

The existing public `model.create_collision`, `model.create_lod`,
`mesh.compare_surface` and `asset.export` commands produced an editable fixture
and GLB. Independent GLB geometry inspection confirms:

| Exported collider | Before | After |
|---|---:|---:|
| Vertices | 14 | 14 |
| Triangles | 38 | 24 |
| Edges | 42 | 36 |
| Edges with three/four incident triangles | 17 | 0 |
| Euler characteristic | 10 | 2 |

All corrected edges have exactly two incident triangles, and every evaluated source
vertex lies inside or on every hull plane within 0.001 cm. The largest computed
outside distance is numerical noise (3.6e-15 cm). Source and LOD exported corner
attributes are unchanged. The original retained Blender file remains byte-identical.
The hull is physical geometry: newly created faces do not preserve render UVs.
Concavities are still approximated by one convex volume; this is not decomposition
or native contact/walkability acceptance.

See the [audit](../artifacts/native-derivatives-20261101/hull-audit.json),
[public-command result](../artifacts/native-derivatives-20261101/pilot3/report.json)
and [editable fixture](../artifacts/native-derivatives-20261101/pilot3/derivatives.blend).
The first harness attempt used the old documentation's incorrect command spelling
`lod.compare_surface`; it failed before export. That evidence is retained. The
registered command is `mesh.compare_surface`; the module function is
`framewright.lod.compare_surface`.

## Native gap reproduced

One isolated Unreal 5.8.3 import/readback took 15.00 seconds using companion 0.2.0.
The ordinary static scene metadata/settings checks pass, but the independent
derivative gate fails. All three actors remain visible; the base has one LOD
(36 triangles), the LOD helper is a separate 20-triangle mesh and the collider
is a separate 24-triangle mesh. All have zero simple and zero convex shapes.
Enabled component collision alone is not evidence of usable collision geometry.

The exported GLB retains source/role/LOD tags, but the current native compiler and
backend do not consume them as derivative assignments. Staged names also prefix
`UCX_`, so name inference cannot be the handoff contract. These meshes are not a
verified native LOD/collision asset. No cold or rendering pass was run on this
known failing assignment case.

[Native readback](../artifacts/native-derivatives-20261101/native/report.json) and
[receipt](../artifacts/verification/native-derivatives-20261101.json) retain the
failed gate explicitly. All 522 prior/input pins remain identical. Five imported
assets and one map exist only in the owned disposable namespace. No Sundown write,
8K bake, render, release change or Git staging change occurred.

## Next implementation

Add a validated derivative contract using source identities and explicit roles,
contiguous LOD indices, matching transforms and material compatibility. Attach the
authored LODs and convex hull to their base mesh; exclude helpers from rendering
and collision queries. Verify actual LOD geometry/UVs/materials, screen sizes,
cooked hull geometry and contact queries in fresh/cold native runs. Deliberately
missing/swapped derivatives and the original thin-fin loss must remain failures.
Use the existing public derivative builders and this retained small fixture.
Moving LOD transitions, performance, complex concavity and art acceptance stay open.
