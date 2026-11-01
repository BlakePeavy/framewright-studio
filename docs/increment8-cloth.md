# Evaluated cloth and embedded-cache verification

This 0.3 development increment tests actual cloth dynamics and corrects collider scope. It does not alter the verified 0.2 archive or receipts. `secondary.create_cloth_proxy` remains a setup command: its response still says `simulation_evaluated: false`, and it does not bake or write files. The trusted background test harness performs the simulation and selected-cache bake separately.

## Reproduced defect and fix

Previously, `collider_names` created collider copies but left `cloth.collision_settings.collection` unset. Blender therefore considered unrelated collision objects in the scene. The same selected floor produced minimum cloth height **0.928409 m** without an unrelated obstacle and **1.226753 m** with one: a **0.298343 m** unintended change. An empty collider selection also collided with the unrelated obstacle instead of falling to **0.499028 m**. `artifacts/cloth-collider-scope-red.log` records those failing tests before the fix.

Each proxy now receives its own collection containing exactly its selected collider derivatives. An empty selection creates an empty collision collection, excluding other scene colliders. The response reports `collision_scope: selected_collider_derivatives_only` and the actual `collision_collection` name after application. Only owned collider copies are linked into this collection. Failed setup removes its new objects, meshes and collection while retaining preexisting data.

## Measured fixture

The fixture is an authored 9×9 horizontal sheet (81 vertices, 64 quads) with nine full-weight vertices pinned along one edge. It sags under gravity onto an explicitly selected horizontal floor. Scene scale is one meter per Blender unit; time is 24 FPS; every frame from 1 through 61 is evaluated. Proxy and collider copies are explicitly revealed for this owned simulation. The source sheet and floor remain intact.

| Measurement | Observed |
|---|---:|
| Maximum pinned-vertex displacement over all 61 frames | 0 m |
| Maximum free-vertex drop | 0.5715908408 m |
| Minimum free-vertex height over all 61 frames | 0.9284091592 m |
| Floor height | 0.9 m |
| Cold reopened baked playback maximum vertex error | 0 m |
| External `.bphys` files in the owned fixture directory | 0 |

Zero-gravity and missing-collider controls verify that the checks detect absent motion and missing collision response. Tests compare explicit-collider results with and without an unrelated obstacle, including empty collider selection. This is a narrow floor fixture; it does not establish robust collision on arbitrary geometry, self-collision quality, garment fit, hair behavior or production motion quality.

The bake uses the selected proxy's `point_cache` context with `ptcache.bake_from_cache`, never a global bake-all operator. A second proxy retains its distinct, unbaked cache. `use_disk_cache` and `use_external` remain false. After saving a separate owned file, a second factory-startup, offline, auto-execution-disabled Blender opens it and checks baked geometry in deliberately nonsequential frame order (61, 1, 41, 21). It also verifies saved collider membership, cache ownership, source object data and the unchanged authored-file SHA-256. Blender documents this embedded-bake storage separately from external disk cache; this fixture verifies the installed build's actual behavior. [Blender physics cache documentation](https://docs.blender.org/UATEST/manual/en/dev/physics/baking.html).

## Retained evidence and checks

Pilot directory: `artifacts/cloth-simulation/20261030T175021Z-e7850657/`.

- `authored.blend`: intact authored fixture before proxy creation.
- `baked-owned.blend`: source objects plus independent proxy/collider copies and embedded bake.
- `cache-receipt.json`: expected sampled coordinates, source snapshots/hashes and collider membership.
- `measurements.json`: measured dynamics and cold verification.

The baked file's SHA-256 is `350f0541de59da9ceffc9735fdce4f295211058296774bef9f97a2877905234e`.

**Six actual cloth/cache tests** and **eight existing secondary-motion tests** pass in Blender 5.2.1 LTS. Logs: `artifacts/cloth-simulation-final.log` and `artifacts/cloth-secondary-regression.log`. The new suite is `scripts/test_cloth_simulation.py`; `--pilot-dir <new-directory>` retains an additional inspectable fixture and refuses an existing directory. Normal test runs use temporary directories. Ruff formatting and lint pass for the changed runtime/tests.

The simulation is synchronous, bounded by this small fixture, and is not a new interruptible cloth service. No game assets, live editor state or existing external physics caches were changed. Artistic acceptance and production garment/hair work remain open.
