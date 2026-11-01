# Editable construction and review scenes

Implemented in `framewright/production_assets.py`, verified with Blender 5.2.1 LTS on Windows. This delivers a bounded foundation for FW-021, FW-051, FW-052 and FW-053. It does not close independent AAA reference/benchmark acceptance, broad modeling tools, measured runtime budgets or native Sundown integration.

The [0.5 construction review](increment11-cabinet-construction.md) corrects hinge
axes, panel seats, thin-board clearance and physical scene-unit conversion. It
also documents the static review-dependency boundary and omitted-parent shear
refusal. Its matched renders and cold measurements extend this initial record.

## Public functions

All functions return JSON-compatible dictionaries, reject unknown parameters and require Blender's main thread in Object Mode. Construction defaults to `dry_run: true`; explicit `false` creates owned, uniquely named data. No save, export, render or network request occurs implicitly.

| Function | Parameters and defaults |
|---|---|
| `build_prop` | `name="FW_WorkshopCabinet"`, `width=0.9`, `depth=0.5`, `height=1.25`, `board_thickness=0.024`, `bevel=0.003`, `door_open_degrees=0`, `location=[0,0,0]`, `dry_run=true` |
| `build_facade` | `name="FW_FacadeBay"`, `width=4`, `height=3.4`, `depth=0.25`, `door_width=0.95`, `door_height=2.15`, `window_width=1.5`, `window_height=1.35`, `sill_height=0.85`, `bevel=0.01`, `location=[0,0,0]`, `dry_run=true` |
| `setup_review_scene` | Exactly one of `object_names=[...]` or `collection_name="..."`; `name="FW_Review"`, `lighting="neutral"` (`day`/`dusk` also supported), `resolution=1024` (integer 64–8192), `dry_run=true` |
| `scene_resources` | Optional `scene_name`; otherwise the current scene |

Construction coordinates and dimensions are metres. The cabinet retains separate carcass, shelves, feet, framed door, hinge plates/pins/screws, latch and handle. The door has its own named pivot and an optional opening angle. The facade includes actual opening recesses, piers/lintels, separate door panels/handle, window frame/mullions/glass, sill, headers and parapet cap. Individual parts retain mesh data, planar UV islands, bevel and weighted-normal modifiers, and procedural/Principled materials.

Review scenes copy owned static meshes/empties into a new scene without changing the active scene, source objects or source mesh data. Four cameras provide front, side, back and three-quarter coverage. Three area lights, a floor and a world provide neutral/day/dusk starting recipes. Cycles, AgX and the requested output resolution are configured; selecting 8K only changes render settings and does not allocate or upscale textures. Rendering remains an explicit separate action.

Resource reports distinguish unique source mesh data, evaluated geometry, scene object occurrences and collection instances. Material slot counts are not engine draw calls. Texture byte estimates use base image dimensions/channels/sample width, with a separately labeled full-mip estimate; compression, runtime residency, tile/sequence caches and non-mesh geometry remain outside that estimate. Evaluated counts reflect the first view layer/current frame.

## TDD and verification

- Red: the first test run failed because the module did not exist.
- Green: 11 initial tests passed for dry-run/invalid inputs, editable parts/UVs, context retention, door pivot, unique names, failure rollback, separate review scenes, 8K settings without image allocation, source ownership and instance-aware resource counts.
- Visual QA found coplanar cabinet side/top surfaces. A new geometric join test reproduced the defect; side panels now stop at the underside of the top board.
- A malformed lighting-value test reproduced an unhashable-value exception; validation now rejects it as a clear `ValueError`.
- Final: **13 tests pass**, lint passes, and two 512×512 Cycles fixtures rendered at 24 samples were inspected.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_production_assets.py -- --render-dir artifacts/production-assets
```

Local ignored evidence: `artifacts/production-assets/WorkshopCabinet.png`, `PeriodFacade.png` and `fixtures.json`. The corrected cabinet image shows the top join without the original coplanar edge artifacts. Both images show readable construction and separate material regions. They remain development fixtures, not accepted AAA assets: wood grain/aging, facade interiors/glass context, detailed joinery, licensed period reference comparisons, high-resolution surface detail and broader shot/animation review remain open. Day/dusk recipes are starting lighting arrangements, not physically calibrated scenes or a universal studio lighting standard.
