# Explicit LOD resources and whole-process performance evidence

Implemented and verified on Windows with Blender 5.2.1 LTS (`9e2066aef7ef`), 2026-10-30. These changes extend engineering resource accounting and bounded performance evidence. They do not establish target-device frame rate, GPU residency or native-engine budgets.

## LOD and instance resource accounting

`production_assets.scene_resources` now includes a `lod` report. Groups use the actual derivative properties `framewright_role="lod"`, `framewright_source` and `framewright_lod_level`. New `lod.create_lod` results persist the requested level (1–8). A derivative can be renamed without losing its declared level. Legacy objects without the new property retain an unknown level; names such as `_LOD7` never supply missing data.

Each resolved group reports its explicit source, source triangles, evaluated source occurrences, declared levels, duplicate levels and derivative rows. Derivative rows include source triangles, evaluated triangle/instance occurrences, viewport/render visibility and level status. Hidden derivatives therefore remain visible in the metadata report even when they contribute no evaluated geometry.

`metadata_coverage="complete_for_declared_derivatives"` means only that the existing declared derivatives have valid, unique level metadata. It does not assert that the asset has enough LODs. No required level count, distance threshold or runtime switching rule is invented. Missing/invalid levels, ambiguous or absent source names, self references and duplicate levels remain explicit. `ungrouped_mesh_objects` identifies meshes without a resolved association. Renaming the source invalidates an old name reference until explicitly repaired.

The report also fixes collection-only instance accounting. Unique source meshes/materials now include originals referenced solely through dependency-graph instances. `mesh_objects` still counts direct scene mesh objects; `referenced_mesh_objects` includes instance sources. Evaluated totals count each occurrence, while unique source geometry counts shared mesh data once. `material_slots_evaluated_occurrences` is an occurrence count, not a draw-call estimate. First-view-layer/current-frame and visibility limitations remain explicit.

The new tests first failed because LOD and referenced-instance reporting were absent. They now verify a renamed real LOD derivative at level 3, a hidden derivative's zero evaluated occurrences, unknown legacy levels, duplicate level declarations, an orphaned source, and an untagged name that resembles an LOD. A collection-only tetrahedron instantiated three times correctly reports zero direct meshes, one unique source mesh, four unique triangles and twelve evaluated triangles. The resource report remains read-only.

## Native process memory and bounded workload

`scripts/benchmark_process_performance.py` launches one fresh factory-startup Blender child per fixture, using temporary config/scripts/extensions/data/resource directories and no live session. Each child runs the expanded `benchmark_performance.py`. Windows memory is read through the standard-library `ctypes` binding to `GetProcessMemoryInfo` and `PROCESS_MEMORY_COUNTERS_EX`. Current working set measures resident process memory, including shared pages; peak working set and peak private commit are lifetime high-water marks. Private commit is separate from residency. These meanings follow the [Microsoft structure documentation](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex).

OS counters cover the entire Blender child, including native mesh buffers, startup, fixture construction and the Python tracing pass. They are not measurements of GPU memory. Each stage records OS counters before work, after timing and after its separate Python allocation trace. A stage's OS peak may come from earlier work in that process and must not be interpreted as the stage's allocation alone. Fresh children prevent one fixture's peak contaminating another's. Unsupported platforms report memory as unavailable instead of inventing zero values.

Each stage uses one warm-up, three timed repetitions without `tracemalloc`, then a separate Python-traced invocation. The original 10k/100k curved-grid fixtures remain. A third workload adds a 16-joint animated armature, a fully weighted 5,166-vertex/10,000-triangle skin and 100 collection instances of one shared 1,000-triangle source. The scene has 102 direct objects, two unique mesh datablocks, 11,000 unique source triangles and 110,000 evaluated triangles. Five sampled poses exercise real deformation. This is a bounded rig/instance workload, not an anatomically approved character or a complete production scene.

## Recorded baseline

Raw samples, OS counters, source hashes and per-child logs are retained in [process-baseline.json](../artifacts/process-performance/20261030T164143Z-a22679c4/process-baseline.json). The machine is the same Windows 11/i9-12900KF workstation as the [initial baseline](performance-baseline.md). Values below are observations on that machine; unrelated machine activity was not controlled.

| Workload | Snapshot median | Resource accounting median | Diagnostic/deformation median | Peak working set | Peak private commit | Traced Python peak for diagnostic/deformation |
|---|---:|---:|---:|---:|---:|---:|
| 10k grid | 3.092 ms | 1.587 ms | 115.398 ms mesh diagnostics | 228.10 MiB | 272.55 MiB | 4.77 MiB |
| 100k grid | 39.358 ms | 14.646 ms | 421.787 ms mesh diagnostics | 340.76 MiB | 402.84 MiB | 32.91 MiB |
| 16 joints + 100 instances | 11.267 ms | 2.170 ms | 106.340 ms for five deformation samples | 241.02 MiB | 306.72 MiB | 6.02 MiB |

Pure snapshot-rule medians were 0.029, 0.032 and 0.052 ms respectively. The rig snapshot describes its direct 10k skin; the separate resource report accounts for all 110k evaluated triangles. The two grid intersection checks retain the explicit 2,000-triangle/10,000-pair caps and partial coverage. Neither their timings nor sampled zero intersections imply exhaustive geometry validation. No renderer, native editor or engine workload was measured.

## Verification and repeatability

The resource suite has **16 passing Blender tests**, the LOD suite has **5**, and the new benchmark-fixture suite has **2**. The latter checks exact rig/instance workload counts, normalized weights, actual animated deformation, frame restoration and owned-datablock cleanup. It also verifies distinct OS/Python reports around a real 2 MiB allocation. **Two Python memory tests pass**: a touched 32 MiB native allocation increases measured private commit and the recorded peak survives release; an unsupported platform reports unavailable. These memory tests were written before their measurement module and initially failed importing it. Ruff lint and formatting pass for the changed files.

```powershell
uv run --frozen python scripts/test_process_performance.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_benchmark_fixtures.py
uv run --frozen python scripts/benchmark_process_performance.py --blender '<Blender executable>' --repeats 3
```

Benchmark output defaults to a new UTC/UUID folder under `artifacts/process-performance`; `--output-dir` chooses another parent directory. No existing report is overwritten. Each child has a 240-second timeout. `benchmark_performance.py --fixture grid_10k|grid_100k|rig_instances` is also available when explicitly running a single background process. Running its default `all` mode shares one process-lifetime peak across fixtures, so the fresh-child orchestrator is preferred for comparison.
