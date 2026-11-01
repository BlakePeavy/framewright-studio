# Blender extraction and diagnostic baseline

Measured 2026-10-30 in an owned background Blender 5.2.1 LTS process (`9e2066aef7ef`, bundled Python 3.13.13), Windows 11 build 26200. Machine: Intel Core i9-12900KF, 16 physical/24 logical cores; Windows reported 68,501,528,576 physical memory bytes. GPU/runtime performance was not measured.

Full raw results and source-file hashes: [baseline.json](../artifacts/performance/20261030T162124Z-a475e4c1/baseline.json). This is an initial engineering observation, not a performance promise or universal production budget.

| Fixture | Snapshot extraction median | Pure snapshot rules median | Bounded evaluated-mesh diagnostics median | Diagnostic peak traced Python allocations |
|---|---:|---:|---:|---:|
| 10,000 triangles; 5,166 vertices; one mesh object | 3.130 ms | 0.032 ms | 118.654 ms | 4.77 MiB |
| 100,000 triangles; 50,451 vertices; one mesh object | 31.928 ms | 0.031 ms | 424.610 ms | 32.91 MiB |

Each stage received one warm-up, three independently timed repetitions, then a separate `tracemalloc` invocation for Python allocation evidence. Garbage collection ran before each timed call. **Traced Python memory excludes Blender's native BMesh/mesh buffers, process RSS, Cycles, GPU and driver memory.** In particular, the snapshot stage's approximately 3.7 KB Python trace does not mean a 100k-triangle extraction uses only 3.7 KB overall.

The diagnostic fixtures are gently curved open grids with UVs. Intersection work was limited to 2,000 triangles and 10,000 candidate pairs, while full mesh topology extraction still occurred. Both results correctly reported partial coverage: 8,000/98,000 triangles were omitted from intersection analysis and the pair budget was reached. Zero sampled intersections therefore does not establish a globally clean mesh.

## Interpretation and next measurements

Snapshot extraction grew approximately with triangle count in these two fixtures. Pure preflight rules operate on the already-extracted one-object snapshot, so their near-constant time is expected. Evaluated mesh analysis costs substantially more and should remain an explicit bounded/background job for large assets. The existing worker cancellation/timeouts are process-control features; this benchmark does not claim Blender geometry evaluation itself is interruptible.

This run followed completion of this task's render jobs, but unrelated machine activity was not controlled. One-object grids do not model large scene hierarchies, linked libraries, modifiers, rigs, textures, instances or engine resource residency. Future baseline fixtures should add those workloads, report native process memory, and repeat on supported target hardware. Presented frame rate, native CPU/GPU time, texture streaming, runtime LODs and 4K/8K playback remain unverified.

Follow-up, 2026-10-30: [the expanded baseline](increment5-resource-performance.md) adds a 16-joint/100-instance workload and actual Windows process working-set/private-commit counters in fresh Blender children. This earlier run remains Python-only evidence. Texture-heavy production workloads, other hardware and native runtime/GPU measurements are still open.

Further evidence: [three actual 8K texture runs](texture-performance.md) measure
whole-process memory and material/render timing. The [versioned retained-asset
corpus](increment11-production-corpus.md) adds 15 fresh workers across authored
cabinet diagnostics and human sole contacts. Broader production scenes, other
hardware and native runtime/GPU measurements remain separate work.

## Reproduce

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/benchmark_performance.py -- --output-dir artifacts/performance --repeats 3
```

The script refuses interactive Blender, creates only owned fixture scenes, checks exact triangle totals and partial-analysis reporting, restores the original factory scene, and writes a fresh UTC/UUID run folder. Output contains raw samples, separate memory measurements, environment metadata and hashes of the measured implementation. No game tests, live scenes or native engine measurements are involved.
