# Actual 8K texture handoff pilot

`scripts/pbr_8k_handoff.py` exercises one verified three-map material through GLB and FBX, using fresh isolated Blender processes. It is optional evidence outside normal CI because it depends on approximately 302 MB of external reference textures. The host-only safety checks need no reference downloads or Blender process.

The input is the editable [wooden-planks material pilot](../artifacts/texture-performance/20261030T175345Z-3037d633/receipt.json). Its base-color, roughness and OpenGL tangent-normal images are each 8192 × 8192. Their source is the [Poly Haven wooden_planks asset](https://polyhaven.com/a/wooden_planks), recorded as CC0-1.0; the original receipt includes the source file hashes and attribution. The pilot verifies those current texture bytes and the original `.blend` hash before and after execution. The original source files remain untouched.

## What the script checks

Five sequential workers perform the source render, GLB export, GLB cold import/render, FBX export, and FBX cold import/render. Each starts with factory settings, offline mode and automatic script execution disabled. Config, scripts, extension and data directories are temporary and separate for each process. Cold workers open only their exported asset, without loading the source `.blend`, materials or textures through that source file.

Each cold import must contain one mesh, four vertices, one UV layer and one material slot. The active Principled shader must retain three image routes: base color in sRGB, roughness in Non-Color, and tangent-space normal in Non-Color. Every bound image must be 8192 × 8192. Reports preserve the actual route, including glTF's packed roughness green channel and FBX's staged scalar image. Removing the roughness connection is an intentional negative control and must be rejected.

Exports use an explicit `max_material_memory_mb: 4096` for the single 8K roughness staging image. This is the exporter's conservative staging estimate, **not** a process or GPU memory cap. Each worker records Windows `GetProcessMemoryInfo` counters at timed checkpoints, including whole-process working set, lifetime peak working set and private commit. Startup precedes some checkpoints, OS disk caching is uncontrolled, and no GPU memory or native-engine residency is measured.

The source and imported materials are rendered using the existing surface-parity stage: 512 × 512, Cycles CPU, 32 samples, fixed seed, orthographic camera, fixed sun/world, Standard/None, exposure 0 and gamma 1. Full-image and central-region RGB differences use Blender's PNG `Image.pixels` readback; the comparator adds no color conversion. A 0.01 full-image mean absolute difference is this fixture's engineering ceiling, not an artistic threshold. These are **8K texture inputs with 512-pixel comparison renders**, not an 8K output render.

The input receipt, source `.blend`, source textures, export receipts, exported bytes, logs and rendered PNGs have recorded hashes. Every worker also checks all Framewright Python runtime files and the pilot/helper scripts before imports and afterward; the host checks the same code set across the complete run. Any changed code prevents a successful final report. Existing outputs are not overwritten: each invocation creates a unique artifact directory, and JSON files use exclusive creation.

## Reproduction and evidence status

Host safety checks (three test methods covering missing inputs, stale source hashes, duplicate map roles and output overwrite refusal):

```powershell
uv run --frozen python scripts/pbr_8k_handoff.py --self-test
```

The complete optional run:

```powershell
uv run --frozen python scripts/pbr_8k_handoff.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --source-kit artifacts/texture-performance/20261030T175345Z-3037d633
```

`--output-dir` selects the parent for a new unique run. There are no network downloads, game writes, native-editor launches or package changes. Each worker has a 900-second timeout; its log and the execution receipt remain available on failure.

The first integration run, `20261030T181525Z-b793084a`, stopped at cold GLB because the new pilot read `sha256` instead of the export receipt's `output_sha256`. This was a pilot-script bug, fixed without changing runtime code. The next run, `20261030T181601Z-488046cc`, completed all five workers and its three comparison images were inspected. It predates the added whole-run runtime-hash guard and remains provisional history.

The selected final run is [20261030T182035Z-7f0e7928](../artifacts/pbr-8k-handoff/20261030T182035Z-7f0e7928/index.html), with its [measured report](../artifacts/pbr-8k-handoff/20261030T182035Z-7f0e7928/report.json), [input hashes](../artifacts/pbr-8k-handoff/20261030T182035Z-7f0e7928/inputs.json), and [execution receipt](../artifacts/pbr-8k-handoff/20261030T182035Z-7f0e7928/execution.json). All five worker exit codes are zero in Blender 5.2.1 LTS (`9e2066aef7ef`). All 37 runtime/helper/script hashes match before imports, after each worker and at the host's final check. Source `.blend`, texture bytes and source geometry/material-graph fingerprints are unchanged.

Both cold imports contain the three distinct 8192-square image bindings in their required color spaces. GLB roughness reads the packed green channel; FBX roughness reads the generated 16-bit grayscale scalar map. Both disconnected-roughness controls are rejected. The exported GLB is 189,839,820 bytes; the FBX is 268,636,412 bytes. Their hashes, import routes and output-receipt hashes are retained alongside the source hashes.

| Format | Full-image RGB mean absolute difference | Central-region RGB mean absolute difference |
| --- | ---: | ---: |
| GLB | 0.00000655230 | 0.00000897053 |
| FBX | 0.000000902562 | 0.00000115749 |

The three final PNGs were inspected directly. Plank placement, grain, seams and overall shading appear consistent at the recorded 512-pixel resolution. This inspection does not assess original 8K-frequency detail or approve the material for a production shot.

| Fresh worker | Observed wall time | Peak working set | Peak private commit |
| --- | ---: | ---: | ---: |
| Source open / render | 12.76 s | 2,888,478,720 bytes | 3,172,700,160 bytes |
| GLB export | 10.68 s | 4,995,297,280 bytes | 5,655,654,400 bytes |
| GLB cold import / render | 7.20 s | 3,688,177,664 bytes | 4,301,746,176 bytes |
| FBX export | 15.34 s | 3,808,862,208 bytes | 4,307,083,264 bytes |
| FBX cold import / render | 8.92 s | 5,382,324,224 bytes | 6,204,645,376 bytes |

These are single-run observations, including startup in wall time; other verification work was active on the host and caching was uncontrolled. The cold FBX process reached about 5.01 GiB working set and 5.78 GiB private commit, illustrating why the 4,096 MiB scalar staging allowance must not be treated as a total-process cap.

This bounded plane/material case cannot establish native Unreal import, arbitrary shader portability, compressed texture quality, mipmapping, moving shots, an approved art target, or production performance budgets. The script always leaves artist and native-engine acceptance false.
