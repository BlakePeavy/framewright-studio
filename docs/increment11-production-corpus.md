# Versioned retained-asset technical corpus — 2026-10-30

`scripts/benchmark_production_corpus.py` complements the synthetic grid/rig
[process baseline](increment5-resource-performance.md) and the separate
[actual 8K handoff](8k-handoff.md). It runs public read-only commands on two
retained, explicitly scoped assets. It does not generate artist labels or treat
these assets as approved production art.

## Pinned fixtures and observations

[The versioned manifest](../benchmarks/production-corpus-v1.json) pins each source
file, dependencies and evidence receipts by SHA256 and byte length. Fixture
identity changes require a new fixture version; changing the corpus requires a
new corpus version. Paths resolve inside the explicitly selected repository's
`artifacts` directory, with traversal, prefix confusion and symlink escapes
rejected. The runner performs no downloads.

| Fixture | Source identity | Measured scope |
|---|---|---|
| `cabinet-reference-pbr`, version 1 | Owned recipe/reference `.blend`, SHA256 `d914de2c5b5150b8d811416f411289293f8c66d65da4edb153be257cf9fe1764` | Exact `Cabinet_recipe` scene: 13 objects, six meshes including its review floor; diagnostics explicitly select five cabinet parts |
| `human-evaluated-sole-contacts`, version 2 | Owned contact-pilot `.blend`, SHA256 `c51fc18e3216d3ab92dd3be15651cadfcc6612702b9d34d66a4f63d0d9e3e577` | Exact `FW_HumanContact_Pilot` scene: 19 objects and 14 meshes; contact evaluation selects the authored rig, skin and ground |

The cabinet has four 4096×4096 maps: one JPEG base color and three data EXRs.
Their bytes and actual external image bindings are verified. Its selected scene
has 2,415 evaluated triangles, including the floor. The human scene has 22,856
evaluated triangles, including marker and prop review geometry. These counts are
fixture observations, not target budgets for other assets.

Expected findings are explicit. Cabinet mesh diagnostics retain 17, 0, 24, 41 and
41 boundary edges across the five parts; the bounded intersection scan reports
50 pairs for one door and three for each drawer. These are recorded diagnostic
observations requiring interpretation, not invented artist defects or a clean
geometry claim. The 512-triangle/2,000-pair limits produce partial coverage on
several parts. The manifest pins coverage, topology and findings rather than
discarding warnings to achieve a pass.

The human case requires 121 half-frame samples, ten explicit sole markers,
871 contact observations, no measured penetration/sliding/misses, and the same
marker topology and sampled-work counts as its retained report. It does not
infer anatomy, inspect the whole foot surface, or establish continuous collision.

Quality controls run after timing, on temporary owned copies:

- Remove the first cabinet part's copied UV layers. The surface command must
  report `UV_MISSING`; the original retains its UVs.
- Raise a copied human contact surface 40 mm. The contact command must report
  exactly 902 penetration observations; the original floor remains unchanged.

The harness also checks sample-budget refusal and rejects a deliberately false,
unchanged response to the missing-UV control. Controls are excluded from command
timing and the memory counter taken immediately after that timed command group.

## Measurement protocol and isolation

Every fixture/operation/repetition gets a fresh Blender process, temporary user
config/scripts/extensions/data/resource directories, factory startup, offline
mode and disabled script auto-execution. Three repetitions across five operation
groups produce 15 sequential workers. A cabinet diagnostic group includes all
five named parts; raw per-request timings are also retained. No render or export
is included in this first corpus.

The runner records host wall time, startup to worker-script entry, file-load
time, command-group time, individual requests, current/peak Windows working set
and private commit, Blender version/build, host metadata, and runtime-module
hashes. OS counters reuse `benchmark_process_performance.process_memory`.
Lifetime peaks include startup, file loading and preservation snapshots; they
are not allocations attributable solely to the command. Texture decoding is
lazy: mesh diagnostics do not load the same image buffers as resource/surface
inspection. GPU residency is unmeasured. Hash checks warm filesystem caches, so
fresh processes must not be described as cold-disk measurements.

Each worker and the aggregate verify source/dependency bytes and runtime hashes
before and after. The protected authored-state fingerprint covers subject mesh
geometry, UVs, weights, material graphs, shape-key geometry/values, transforms,
pose channels, actions/drivers, scene time/selection, and datablock identities.
It is a bounded fingerprint, not a complete serialization of arbitrary Blender
RNA. Linked libraries and unpinned external image bindings are rejected.

Team coordination is separate from system exclusivity. The team paused its
Blender/heavy jobs and runtime edits. An existing user Blender session remained
open and untouched. `--allow-idle-pid` explicitly admits that PID only while its
process creation identity and executable path remain stable. Read-only Windows
`GetProcessTimes` counters enforce `--max-idle-cpu-seconds` cumulatively across
the whole run and around each worker. New unlisted Blender processes, PID reuse,
an exited allowed process, or excess CPU activity reject the run. No process is
suspended or closed. Other system and GPU activity remain unknown.

## Retained measurements

Successful [aggregate receipt](../artifacts/production-corpus/20261030T192324Z-5037f8c1/report.json):
all 15 workers passed expected observations, controls, exact protected-state
checks and final file/runtime identity checks. The manifest SHA256 is
`7db6eb2142f1d2fe5d3c7057ac5ede6dd45bca4ca9ae416d0ee50cf9501ff3a3`;
runtime identity SHA256 is
`57983303be9892e2ccd78502773801f58ac0434f9f7dcb8cda77f331f77fc7c3`.

Blender 5.2.1 LTS, Windows, four requested Blender threads. Command groups were
measured once per fresh worker, without a discarded warm-up. The table gives the
median of three observations and the largest process peak in each group.

| Fixture / operation | Median command group | Range | Peak working set | Peak private commit |
|---|---:|---:|---:|---:|
| Cabinet resources | 445.02 ms | 437.99–445.19 ms | 1,059.75 MiB | 1,204.70 MiB |
| Cabinet five-part mesh diagnostics | 65.05 ms | 63.56–78.55 ms | 208.87 MiB | 256.21 MiB |
| Cabinet five-part surface diagnostics | 500.99 ms | 491.46–510.98 ms | 1,050.44 MiB | 1,210.46 MiB |
| Human scene resources | 5.24 ms | 4.77–5.31 ms | 887.57 MiB | 717.19 MiB |
| Human 121-sample skin contacts | 2,487.63 ms | 2,485.02–2,538.17 ms | 887.55 MiB | 718.44 MiB |

Startup to worker entry ranged from 1.450 to 1.506 seconds. Median file loads
were approximately 0.012 seconds for the small cabinet `.blend` and 2.37–2.39
seconds for the 240 MB human file. Cabinet textures are external and decode
during commands that request their dimensions/buffers, so the short `.blend`
load does not imply all material resources are resident.

The initial [0.25 CPU-second allowance run](../artifacts/production-corpus/20261030T192227Z-3756996d/failure.json)
was rejected after six workers and is retained as partial evidence, not a valid
baseline. The fresh successful run used an explicit **2.0 CPU-second** allowance.
User Blender PID 22672 retained its creation/executable identity and consumed
**0.90625 CPU seconds**. The sum of sequential worker wall times was **121.845
seconds**, making that background load at most **0.744% of one core's time**
over the encompassing CPU-counter interval. File creation/write timestamps span
approximately 125.517 seconds; they are a full-window proxy, not synchronized
monotonic CPU snapshots. The [timing context](../artifacts/production-corpus/20261030T192324Z-5037f8c1/timing-context.json)
records this distinction. This is an observed GUI-background-load allowance,
not proof of an idle or exclusive machine.

The runner makes zero provider/network calls, so its provider request count and
provider charge are zero. Upstream asset creation, electricity, machine cost and
any future provider work remain unknown, not zero.

## Tests and repetition

**25 host tests** pass, including initial missing-module failures before
implementation, hash/path/identity admission, finite strict JSON, scope and
command guards, false observations, no overwrite, and real Windows process
identity/CPU counters. **Eight Blender tests** pass for the owned-copy quality
controls, negative false-response and source-mutation injections, cleanup,
scope rejection, native memory, and a separate cold worker with isolated user
directories. Both retained asset workers were separately validated before
collecting the 15 timing samples. Ruff checks pass.

```powershell
uv run --frozen pytest tests/test_production_corpus.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_production_corpus.py
uv run --frozen python scripts/benchmark_production_corpus.py --blender '<Blender executable>' --repeats 3 --threads 4 --confirm-idle
```

If a known user Blender session is open, append an explicitly checked
`--allow-idle-pid <PID> --max-idle-cpu-seconds 2.0`; the PID above is historical and
must not be blindly reused. Coordinate heavy jobs first. The CPU threshold is a
declared measurement-admission choice, not a universal definition of idle.
Output uses new UTC/UUID directories under `artifacts/production-corpus`, with
per-worker logs and JSON. Missing retained fixtures fail; the runner does not
fetch substitutes. Performance acceptance, broader production coverage and
artist/native acceptance remain separate tasks. Sundown was not opened or changed.
