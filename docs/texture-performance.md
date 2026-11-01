# Actual 8K texture workload

Measured 2026-10-30 in three fresh Windows/Blender 5.2.1 CPU processes. This extends
the geometry/rig/instance baseline with the already retained Poly Haven Wooden
Planks diffuse, roughness and OpenGL-normal maps, each actually 8192×8192.
The [summary and individual receipt hashes](../artifacts/texture-performance/summary-20261030T175345.json)
retain the raw observations. Source texture hashes and independent cold reopen
checks passed for every run. No game or live editor was involved.

The existing material pilot now samples Windows `GetProcessMemoryInfo` immediately
before material creation, after it, and after rendering. The process includes
Blender's native allocations; these are not Python-only `tracemalloc` values.
Peaks are cumulative since process start, including transient allocations released
before the checkpoint. GPU memory is explicitly unmeasured.

| Observation | Median of three runs |
|---|---:|
| Peak process working set | 2,279.05 MiB |
| Peak process private commit | 2,586.07 MiB |
| Final private commit minus pre-recipe baseline | 56.57 MiB |
| PBR recipe creation | 10.753 s |
| Scene construction plus render | 5.155 s |

The modest final commit difference does not describe the transient peak. The API's
conservative three-map RGBA-float estimate remains 3,072 MiB; the pilot explicitly
allows 4,096 MiB. Actual allocations and cache lifetimes depend on Blender.

Rendering uses a 2 m UV plane, 512×512 output, 32 CPU Cycles samples, eight fixed
threads, seed zero, denoising and AgX at exposure zero/gamma one. The
[latest image](../artifacts/texture-performance/20261030T175345Z-3037d633/wooden-planks-neutral-512.png)
was visually inspected: the maps produce readable seams and surface variation.
This is use of full-size inputs, not inspection of every 8K texel or approved art.
The source/credit record remains [the licensed material pilot](increment5-materials.md).

Disk caches and concurrent machine load were uncontrolled. Recipe times ranged
8.570–13.501 seconds. Three observations do not establish universal budgets,
production-frame rates, GPU residency, streaming or native-engine performance.

## Verification and reproduction

Before instrumentation, `scripts/test_texture_memory.py` rejected the earlier
pilot receipt because it contained no process-memory evidence. The three new
receipts pass its actual-counter, process-identity, stage-order, input-size and
source-retention checks. Six pure tests reject estimate labels, mixed processes,
invalid counters, missing checkpoints and failed source retention. This validates
receipt consistency; it does not authenticate arbitrary caller-supplied JSON.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_materials.py -- --pilot-source artifacts/reference-candidates/wooden_planks-8k --pilot-output artifacts/texture-performance
uv run --frozen python scripts/test_texture_memory.py '<new output folder>/receipt.json'
```

Input maps must already be downloaded and match their receipt. Each pilot writes
a new UTC/UUID directory. The memory check currently requires Windows counters;
unavailable counters cannot pass as zero memory. Large external texture files are
not included in the install or source archives.
