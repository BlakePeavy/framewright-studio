# Bounded normal-image inspection

The 0.6 baker replaces its per-pixel Python inspection loop with NumPy operations
over fixed 65,536-pixel chunks. NumPy is bundled with the supported Blender runtime;
no dependency is installed at runtime. The public bake request and result fields
are unchanged.

There is one full RGBA float32 readback buffer, as in the scalar implementation.
RGB conversion, normal-length arithmetic and accepted-pixel copies use float64
within each chunk. They do not allocate a second full-image float64 array. The
existing three-RGBA-buffer image estimate remains unchanged; it is not a total
process, geometry, Cycles or GPU memory cap.

## Exact behavior and TDD

The test-only scalar oracle was copied from the verified 0.5 ZIP, whose SHA256 is
`87a8d969a3cd0c40c3373b1803da466bd3ea031abb3c57682fc46809ca36aed0`.
Its function AST matches the retained archive. Independent goldens also check flat
maps, strict detail thresholds and the historical min/max initialization behavior
for accepted components slightly outside [0,1]. That behavior is intentionally
retained rather than silently redefining the evidence fields.

Nine Blender tests were written before the new helper. They cover mixed data across
a partial final chunk; neighbors of normal-length and blue-channel thresholds;
NaN, infinity and extreme finite RGB; ignored alpha; exact all-invalid errors;
single-readback/chunk bounds; public baker routing; and unchanged pixel bytes.
All nine pass. The initial missing-helper run is retained in
[red evidence](../artifacts/normal-inspection-red.log), with the
[green run](../artifacts/normal-inspection-first-green.log).

Six host tests reject changed pixels/results/runtime, wrong sizes, missing repeats,
reused process IDs, invalid timing, unavailable memory and mixed memory owners.
The [receipt validator run](../artifacts/normal-inspection-benchmark-first-green.log)
passes. Existing unit, bake, preservation, dependency, final-review and curved/cold
regressions also pass: 42 Blender test methods including the new nine. The retained
0.5 archive and source assets are not overwritten.

## Measurement contract

`scripts/benchmark_normal_inspection.py` compares the function extracted directly
from the SHA-pinned 0.5 ZIP with the current public baker wrapper. Each observation
uses a fresh background Blender process, temporary user directories, disabled
autoexec, offline mode and one configured thread. A synthetic, actually allocated
RGBA float image alternates two valid tangent normals; its exact result has an
independent golden. Pixel SHA256 hashes before/after and runtime hashes must match.

The timed region includes full pixel readback and inspection. Image setup, hashing,
baking and rendering are outside that region. Windows `GetProcessMemoryInfo`
counters describe the whole process, including native allocations. Lifetime peaks
also include startup, image setup and preservation readbacks; they are not isolated
algorithm allocation peaks. GPU memory is not measured.

Three observations per implementation use alternating pair order. Existing idle
Blender process identities and CPU counters are checked without suspending or
terminating them. Other operating-system activity remains an uncontrolled factor.
Only observed resolutions and timings may be reported; no 8K extrapolation or
whole-bake speed claim follows from smaller images.

```powershell
uv run --frozen python scripts/benchmark_normal_inspection.py --blender '<Blender executable>' --resolution 8192 --repeats 3
```

The command requires a coordinated quiet window. An already-open idle Blender
session must be listed explicitly with `--allow-idle-pid`; its default CPU allowance
is two seconds across the complete run. Each run writes a new ignored artifact
directory and fails closed on source, process, output or memory-evidence mismatch.

## Actual 8K observations

The [six-worker receipt](../artifacts/normal-inspection-performance/20261030T202125Z-8699bf0b/report.json)
passed on 2026-10-30 with actual **8192×8192** float images in fresh Windows 11 /
Blender 5.2.1 LTS processes, Blender-bundled NumPy 2.3.4 and one configured thread.
The host reports 24 logical CPUs. Runtime and retained-archive hashes, exact output
fields, complete before/after pixel SHA256 hashes, cleanup and memory ownership
checks passed for every observation.

| Observation | Retained 0.5 scalar | Chunked implementation |
|---|---:|---:|
| Inspection seconds, three runs | 55.0871 / 55.6627 / 54.3342 | 3.48288 / 3.27696 / 3.37715 |
| Median inspection time | 55.0871 s | 3.37715 s |
| Median peak process working set | 2,253.79 MiB | 2,256.58 MiB |
| Median peak process private commit | 2,564.77 MiB | 2,564.73 MiB |

The observed median ratio is **16.31×** for readback plus inspection of this
synthetic alternating-normal image. It is not a whole-bake or representative
production-map speed claim. The whole-process memory peaks are similar and include
the identical image/hash setup; the chunk bound is separately tested. These
observations do not establish isolated allocator peaks or a universal memory cap.

The existing user Blender process retained its identity and consumed 1.640625 CPU
seconds across the complete coordinated window, within the predeclared two-second
allowance. It was never suspended, closed or edited. Team runtime edits and heavy
jobs were held during measurement. General OS activity was not fully controlled.
The [host log](../artifacts/normal-inspection-8k-run.log) preserves each start and
completion. No result was extrapolated from a smaller image.

The [curved/cold regression](../artifacts/curved-bake/20261030T201819Z-837394ce/report.json)
also passed with the new implementation, including unchanged sources, exact cold
central pixels and rejected removed-normal/damaged-seam controls.
