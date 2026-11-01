# Allowlisted isolated cloth bake

`secondary.bake_cloth` invokes the tested cloth solver/cache workflow through the strict JSON API. It bakes a new independent copy in a new owned scene and retains the configured proxy, its mesh, authored state and existing unbaked cache. It never calls a global bake, replaces an existing bake, or enables external physics cache files.

Required parameters are exact `object_name` and `modifier_name`. Optional `dry_run` defaults to `true`; the remaining options are:

| Option | Default | Allowed range |
|---|---:|---:|
| `max_frames` | 250 | 1–512 |
| `max_vertices` | 20,000 | 1–50,000 |
| `max_memory_mb` | 512 | 1–4096 |

The configured cache's complete frame interval is used. Oversized intervals reject; the command does not silently truncate them. `max_vertices` includes the cloth and all copied colliders. Topology is additionally bounded to twelve loops and four triangles per allowed vertex. The admission estimate uses 128 bytes per cloth vertex/frame plus 4096 working bytes per copied vertex/triangle. Work units are frames × (cloth vertices × solver quality + collider triangles × collision quality), capped at 50 million. These are explicit conservative estimates, **not OS memory limits or guaranteed execution times**. Blender simulation remains synchronous; background-job cancellation can terminate an owned worker.

## Supported state and ownership

Current `secondary.create_cloth_proxy` assigns stable UUID metadata to the proxy, selected collider collection and collider copies. Names may change while IDs continue to match. Missing metadata, mismatched members and pre-metadata proxies reject; recreate an older proxy rather than silently adopting it. UUIDs describe ownership scope and lineage, not security or authenticity.

The first bake implementation supports local, unparented, static meshes. It rejects rig/shape/action/constraint/particle dependencies, foreign handlers, unsupported modifiers, library data/overrides and nontrivial animated/material-group dependencies before allocating anything. The proxy must have exactly its one enabled cloth modifier and one embedded, unbaked cache, a valid positive-weight pin group and its owned collider collection. Colliders require exactly their collision modifier. Already-baked, external and disk-cache inputs are refused. This deliberately excludes animated garments and character-bound cloth until those dependencies have separate preservation and simulation evidence.

The new scene copies the source scene's gravity, units and effective FPS. It contains only independent cloth/collider object and mesh copies; static materials remain referenced without editing. A fresh cloth modifier receives the supported scalar settings, and a new cache is baked with an explicit object/cache context. Every requested frame is then evaluated to check finite coordinates and unchanged topology. The result reports actual `is_baked`, `simulation_evaluated`, `evaluated_frames`, cache info, first/last bounds in world-space Blender units, the output `scene` and `derivative`, and budgets/limits. Cloth and collider outputs finish hidden in their owned scene. Select that returned scene for review; the original scene remains active.

The implementation uses a scene/view-layer context override without activating another window scene. An initial version switched window scenes and reset an unrelated light's manually overridden value from 123.456 to its keyed 10.3702. The failing preservation fixture and corrected override path are retained in the test evidence. Failures remove only newly tracked objects, meshes, collections and scene; an unsuccessful operator or missing baked cache cannot return success.

The command itself performs no file writes. Its scene effect requires saved derivative output in batch/worker execution. A caller can put `secondary.create_cloth_proxy` and `secondary.bake_cloth` in one workflow, bind `proxy.result.derivative` into `object_name`, and require `result.is_baked == true`. Saving the resulting `.blend` retains the embedded bake; cold playback is separately tested.

## Test-first evidence

- Missing command and missing runtime-module failures were recorded before implementation: `artifacts/cloth-bake-python-red.log` and `cloth-bake-blender-red.log`.
- Static image-material validation exposed Blender Image's absent `animation_data` property; the guard was corrected. The unrelated authored-light regression then failed before switching to context overrides. Logs: `cloth-bake-state-check.log`, `cloth-bake-green.log` (the latter contains that intermediate failure), and `cloth-bake-override-check.log` (green).
- **15 new command/schema tests** pass. With affected API/registry/workflow regressions, **41 Python tests and 32 subtests** pass (`cloth-bake-python-green.log`).
- **11 actual Blender tests** pass: budget rejection before allocation, missing/foreign/renamed identity, pre-metadata refusal, multiple/external/already-baked caches, unsupported static dependencies/handlers, original cache validity retention, partial-bake cleanup, fail-closed operator completion, static image material preservation, unrelated authored-light preservation and the real public create→bake workflow with cold reopening. Final log: `artifacts/cloth-bake-final.log`.
- Final affected Blender regression run passed **11 bake-command + 6 cloth-simulation + 8 secondary-motion tests** after the ownership metadata and allocation-cleanup changes. Logs are `artifacts/cloth-bake-regression-test_cloth_baking.log`, `cloth-bake-regression-test_cloth_simulation.log`, and `cloth-bake-regression-test_secondary_motion.log`. Ruff formatting/lint also pass.

Retained public-command pilot: `artifacts/cloth-bake-command/20261030T181029Z-5b3c7df3/`. It contains `authored.blend`, `command-baked.blend`, expected frame coordinates in `command-receipt.json`, and `command-evidence.json`. The 81-vertex fixture produced a 61-frame embedded cache, reported by Blender as 180 KiB; the admission estimate was 1,513,088 bytes. Cold nonsequential playback had **zero maximum vertex error**, no external `.bphys` files appeared in the owned directory, and the original authored-file SHA-256 remained unchanged. The saved baked file hash is `f17ae20d3272742ab4adfe645d09ce0871a93ff9a70c037e297463059d2ecc7b`.

This is a technical sheet/floor fixture, not garment, hair, artist or native-engine acceptance. The verified 0.2 archive and receipts remain unchanged.
