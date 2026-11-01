# Shared material atlas — verified engineering preview 0.8

`surfaces.bake_material_atlas` converts supported static opaque Principled appearance
into four packed PBR maps on owned multipart derivatives. It addresses a measured
export defect: the cabinet's procedural wood previously became white in cold GLB
imports because its shader graph had no portable image maps. Artistic quality,
native engine rendering and production acceptance remain separate open gates.
The [0.8 aggregate and Python matrices](verification.md) pass on unchanged source.

## Contract

```json
{"schema_version":"1.0","request_id":"cabinet-atlas-preview","command":"surfaces.bake_material_atlas","params":{"object_names":["Cabinet","Door","DoorPivot"],"resolution":1024,"margin":8,"dry_run":true}}
```

Names must identify a complete explicit hierarchy of 1–64 local Mesh/Empty objects.
Inspect the preview before applying the same scope with `dry_run:false`. No source
mesh, material, image, hierarchy, transform or visibility is edited. The result
returns `objects` for workflow bindings, a source-to-derivative map, hidden collection,
shared material, atlas UV name, packed-image records and geometry/memory/UV evidence.
Export is a separate `asset.export` action; the baker creates no external files.

The four maps are base color (sRGB), roughness and metallic (Non-Color), and OpenGL
tangent-space normal (Non-Color). Explicit 16-bit RGB PNG encoding preserves row
orientation and scalar values. Normal components within `1e-4` of the encoding range
are clamped as measured bake roundoff; other maps use `1e-6`. Larger excursions and
nonfinite pixels fail with cleanup. Records disclose ranges and clamped components.

The adapter copies evaluated Bevel/Weighted Normal/Triangulate geometry while retaining
separate logical parts, ordinary parent pivots and original named UV coordinates/pins.
Source render-UV references are pinned while baking. Smart Project charts are globally
area-scaled and packed against an explicitly square temporary target, so non-square
source images cannot distort atlas allocation. Complete bounded overlap and chart-gap
checks report actual coverage and padding; they do not certify mipmap behavior.
The owned atlas becomes the first/render UV layer after baking because Blender's FBX
exporter does not emit texture UVSet names. Original source layers remain named on the
derivative; originals are unchanged.

Unsupported material semantics fail explicitly: animation, external/instancer or
view-dependent coordinates, non-opaque/volume/displacement shaders, nondefault
Principled distribution, transmission/SSS/coat/sheen/anisotropy, modified IOR/specular
semantics, unavailable images or missing UV dependencies. Source image nodes must use
local decoded FILE/GENERATED data with flat linear/closest sampling. Main-thread Object
mode and a context without global update/bake/render callbacks are required.

## Budgets and verification boundary

Resolution accepts 64–8192; the default is 1024. The owned image estimate is
`128 × resolution² + 8 MiB`, plus decoded input image buffers. Thus 8K requires at
least 8200 MiB of explicit image budget before source images. This is not an OS/GPU
memory cap: geometry, renderer and driver allocations are additional. Default evaluated
budgets are 250,000 vertices and 100,000 triangles. UV inspection refuses more than
two million candidate visits per overlap/padding pass instead of claiming partial
inspection complete.

Tests include actual packed map sampling, parent/source preservation, failure cleanup,
FBX default-UV transport, existing/default/named UV dependency admission, image-byte
preservation, object material overrides, nonuniform parent transforms, physically
rotated/mirrored tangent normals, asymmetric PNG rows, nonfinite values, known chart
gaps, and non-square source-image aspect. The cabinet handoff harness additionally
checks all 30 logical identities/parents/transforms, 29 meshes/one pivot, triangle
counts/bounds, cold packed native/GLB/FBX rendering and a white-material-loss negative
control. Its image thresholds apply only to this measured 384px neutral fixture.

The earlier `20261030T231938Z-b4e51f33` run recorded images without acceptance assertions;
it is retained as failed evidence. Native cold renders had stale hidden-object matrices
and FBX sampled the wrong UV layer. The fixes have test-first regressions; those earlier
measurements must not be reported as passed parity. Broader production surfaces and
moving/mipmapped views remain outside the bounded cabinet fixtures below.

## Retained passing cabinet run

[The gated report](../artifacts/material-atlas/20261101T152904Z-c07ed2f0/report.json)
passed on unchanged runtime bytes. It retains 1024² maps, the editable packed
`atlas.blend`, both exports, matched 384²/48-sample renders and subprocess logs.
All 30 logical objects, the door hierarchy, world transforms, 5836 triangles and
bounds survived cold reopen/import. The report checks the export receipt's explicit
staging-name mapping rather than guessing names. Original sources remained exact.

| Comparison | Three-quarter RGB MAE | Grain-detail RGB MAE |
|---|---:|---:|
| Procedural source → atlas | 0.00020628 | 0.00102330 |
| Atlas → cold packed Blender | 0 | 0 |
| Atlas → cold GLB | 0.00003492 | 0.00017997 |
| Atlas → cold FBX | 0.00000019 | 0.00000019 |
| Source → deliberate white-material loss (rejected) | 0.04258494 | 0.17245854 |

Source-to-atlas P95 absolute error is 0 / 0.00392157; all cold comparisons have P95
zero. Errors are measured over the full images, not a selected passing crop. The
white-loss control must exceed both fixed defect thresholds and 10× the actual bake
error. GLB/FBX differences remain below recorded fixture limits; no universal visual
equivalence or AAA approval follows from these values.

Report SHA256: `7cd4bb8bd670d3c311ddf5a9efdaf73e2ce7e1bf3e360afe95de33a7d98c4541`.
Editable blend SHA256: `8c377affc1f80260c291ad3d57957d8dc508be63de4cebc237c552635c17554e`.
Runtime/image/export hashes and exact threshold values are in the report. Historical
failed attempts and corrected harness errors remain alongside the passing run.

Separate fresh-process `map-audit-native.json`, `map-audit-glb.json` and
`map-audit-fbx.json` in that run verify all four decoded image roles, exact dimensions,
color spaces and tangent normal semantics. GLB roughness uses the shared ORM green
channel and metallic uses blue; native/FBX retain four direct map routes. Disconnecting
each of the four roles and requesting the wrong dimensions are rejected controls.
The inspector is `scripts/inspect_material_atlas_maps.py`: no arguments or
`--self-test` run two small Blender observer tests; `--folder <run> --format GLB
--resolution 1024` audits a passed retained handoff to a new exclusive JSON report.

## Actual 8K bake and cold transport

[The 8K report](../artifacts/material-atlas/20261101T153315Z-bb69144b/report.json)
passed the same assembly, source-preservation, render and negative-control gates on
the same four pinned runtime files. Four true 8192² maps were baked from procedural
source appearance, without upscaling the 1024 maps. The explicit image budget was
16384 MiB. Separate fresh native/GLB/FBX binding audits confirm every image role still
decodes to 8192² with the correct color space, channels and tangent normal connection;
all four disconnection controls and the wrong-dimension control reject in each format.

| Comparison | Three-quarter RGB MAE | Grain-detail RGB MAE |
|---|---:|---:|
| Procedural source → 8K atlas | 0.00004968 | 0.00013687 |
| 8K atlas → cold packed Blender | 0 | 0 |
| 8K atlas → cold GLB | 0.00003698 | 0.00018439 |
| 8K atlas → cold FBX | 0.00000023 | 0.00000025 |
| Source → deliberate white-material loss (rejected) | 0.04257981 | 0.17245702 |

All of these comparisons have P95 error zero except the deliberately bad control.
The 384² comparison images were inspected: cabinet placement, grain, rail seam and
hardware survive transport. This does not assess every 8K-frequency texel or approve
the source cabinet's art. Soft/blotchy source grain remains a separate refinement.

Windows whole-process counters show the cost: bake/packing took **1109.80 seconds**
between measured checkpoints; the full worker including three cold subprocesses took
**1193.70 seconds**, excluding its own startup/shutdown. Its lifetime peak working set
was **17,599,356,928 bytes (16.39 GiB)** and peak private commit was **19,529,736,192
bytes (18.19 GiB)**. Four CPU bake threads were used; no GPU memory or runtime residency
was measured. Efficiency remains open: functional 8K support does not make this long
synchronous bake responsive. The 8200 MiB owned-image estimate remains explicitly
separate from whole-process use.

| Cold render worker | Script time | Peak working set | Peak private commit |
|---|---:|---:|---:|
| Packed Blender | 14.20 s | 6,084,034,560 B | 8,276,148,224 B |
| GLB | 11.50 s | 4,432,601,088 B | 5,168,009,216 B |
| FBX | 12.07 s | 7,470,178,304 B | 9,355,657,216 B |

These are single-run observations with uncontrolled system caching/background load;
OS peaks cover each process lifetime, not an isolated allocation or GPU estimate.
The final GLB is 325,497,744 bytes and FBX is 325,822,860 bytes. Their larger file and
decoded-image budgets must be evaluated separately by native-engine admission.

The [offline GLB admission receipt](../artifacts/native-adapter/budget-8k-admission-final.json)
now passes with explicit 512 MiB / 201,326,592 aggregate-pixel allowances in 2.76 seconds.
The conservative default byte limit and default pixel limit each correctly refuse this
file. [Independent review](../artifacts/native-adapter/independent-budget-final-review.json)
passes 169 native parser/contract cases on the same pinned runtime, including bounded
reads, changing-input controls and container allocation limits. This is offline
admission only; no Unreal import or rendering was executed.

Report SHA256: `653413773fcf26bfde811a7c8116f270e03b39477ceb99a0ca2f2fa4b2b3ffb0`.
Editable blend SHA256: `eca282b47f191e8548db8f981c170c9c4ce12dd5449a981647a0e24942366186`.
`performance.json`, `cold_*.json`, `map-audit-*.json` and logs retain actual counters,
bindings and hashes. No native Unreal import, artistic approval or release-wide
acceptance follows from these Blender-side results.
