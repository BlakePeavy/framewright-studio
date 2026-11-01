# Source-preserving tangent-normal bake

`framewright/baking.py` adds `bake_normal(params, context=None)` as a bounded FW-022 foundation. It performs an actual Cycles selected-to-active normal bake in a disposable scene, then retains a hidden low-mesh derivative, copied materials and a packed float image. It does not save the current file or write image files automatically.

```json
{"high_object":"HighDetail","low_object":"LowTopology","resolution":1024,"ray_distance":0.1,"max_memory_mb":512,"margin":8,"dry_run":true}
```

High/low names are required exact names in the active scene. Other values above are defaults. Resolution accepts 64–8192; 8K requires an explicit larger memory budget. The estimate includes three RGBA float image buffers (48 bytes/pixel), before any allocation. Geometry, BVHs, Cycles and driver memory are additional; the budget is not a guarantee of peak process/GPU memory. `ray_distance` sets the cage extrusion; the ray search is twice that distance. Margin is 0–64 pixels. Unknown/malformed parameters fail before mutation.

Supported sources are distinct local static meshes without rig weights, shape keys, animation or constraints. Supported modifiers are Bevel, Weighted Normal, Subdivision Surface, Triangulate, Solidify and Smooth. The low source needs a finite, nonzero-area active UV map. Each existing low material must have one Principled BSDF; a new Principled material is supplied when no slot exists. Original high/low meshes, UVs, materials, transforms, selection, frame and active scene are preserved.

The [0.5 unit and dependency corrections](increment11-bake-units.md) make
`ray_distance` a physical metre distance, convert implicit extrusion into low-object
local units, preserve effective material/face assignments, and reject animated
mesh/material/node-group dependencies before evaluation. Explicit cages and
[curved seam/cold render evidence](increment11-curved-bake.md) extend this initial record.

The bake uses tangent +X/+Y/+Z (OpenGL convention), Non-Color image interpretation, and an explicit Normal Map node. Generated image data is packed for later `.blend` saving. New materials preserve source material contents before adding the normal-map connection. The retained derivative starts hidden so it cannot overlap the original in the working scene.

Before baking, up to 256 low-triangle centroid rays check for high-surface projection hits. A completely missed surface is rejected. Afterwards, decoded pixel vectors must include valid tangent normals. The result records sampled coverage, valid-pixel count/fraction, channel ranges and `detail_present`; flat valid maps remain distinguishable from blank/missing results. Sampling and valid pixels do not certify every texel's projection, UV non-overlap, texel density, seams or artistic quality.

## TDD and evidence

- Red: initial tests failed because the module did not exist.
- Final: **7 tests pass** on Blender 5.2.1 LTS/Windows, covering read-only preview, 8K budget refusal before allocation, missing UV/same-source/input rejection, real Cycles baking, source/context preservation, rollback after an injected bake failure, all-missed projection and blank-image refusal.
- A 64×64 normal bake from a 24×24 relief grid onto a UV-mapped plane produced 4,096 valid normal pixels (100% of the fixture image), with R/G variation of approximately 0.1104/0.0886. The map was inspected at `artifacts/baking/normal-fixture.png` (ignored local evidence).
- Lint/format checks pass. No 8K image was allocated in tests. No native engine import, surface render comparison or AAA benchmark acceptance is claimed.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_baking.py
```

Future work: explicit cages, multi-tile/UDIM workflows, overlap/seam guards, per-texel miss evidence, other bake channels, high-detail production examples, rendered source/result comparisons and export/native normal-convention checks. These remain separate from the verified single-image static normal-bake path.

Follow-up, 2026-10-30: [the cage/UV increment](increment5-board-gates-release.md) adds explicit cages, overlap/degeneracy/tile guards and corrected projection-distance preflight; the bake suite now has nine tests. [Rendered source/bake parity](increment5-render-parity.md) passes on a bounded shallow-surface fixture with a failing removed-normal control. The seven-test results above remain the original run history. Production seams, UDIMs, per-texel miss coverage, other channels and native normal-convention acceptance are still open.
