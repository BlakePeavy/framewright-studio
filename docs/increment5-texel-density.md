# Bounded real-world texel density

`surfaces.inspect` now includes `texel_density`, a read-only measurement for a conservative shader subset. It uses the selected object's evaluated mesh by default, its evaluated world transform, scene unit scale, actual image dimensions and effective material slots, including object-linked material overrides. Source-mode inspection remains available with `evaluated=false`.

For each measured triangle:

`world_area_m2 = area(world_matrix × triangle_vertices) × scene_unit_scale²`

`texel_area = UV_triangle_area × image_width × image_height`

`texels_per_meter = sqrt(texel_area / world_area_m2)`

Per-material totals report `sqrt(sum(texel_area) / sum(world_area_m2))`, with the minimum and maximum individual triangle measurements. This weights actual areas rather than averaging densities. It is an area-equivalent measurement: a strongly stretched UV triangle can have the same value as an evenly sampled triangle. It does not report the least-resolved direction, anisotropy, rendered sharpness or an acceptable production budget.

## Supported mapping and explicit unknowns

The active material output must connect directly to a Principled BSDF, whose Base Color is connected directly to an Image Texture's Color output. Supported images are ordinary file or generated image datablocks with actual positive dimensions; missing files remain unknown. This does not support generated coordinates. The image must use flat projection and unchanged internal mapping. Its vector input may be unconnected, a direct UV Map node or a Texture Coordinate node's UV output, with instancer coordinates disabled.

Default coordinates use the Active Render UV layer. A UV Map node can select another named layer; an empty UV Map selection also uses Active Render UV. The command's `uv_layer` parameter still selects the separate UV diagnostic layer and does not rewrite the shader mapping. This distinction follows Blender's [UV Map node documentation](https://docs.blender.org/manual/en/5.0/render/shader_nodes/input/uv_map.html) and [Active Render UV documentation](https://docs.staging.blender.org/manual/en/latest/modeling/meshes/uv/uv_texture_spaces.html).

Mapping nodes, transformed internal mappings, generated/object/instancer coordinates, muted or indirect shader paths, non-flat projections, node groups, tiled/UDIM images and animated image sequences/movies remain unknown. UV triangles outside one 0–1 tile also remain unknown; wrapping or tile resolution is not guessed. Non-finite or degenerate sampled geometry/UVs are rejected by the existing UV checks or explicitly reported unknown by the density check. All returned numeric measurements are finite; unavailable density values are `null`.

## Coverage and interpretation

The existing `max_triangles` limit bounds density sampling independently of the UV intersection pair limit. Reports expose total, sampled, measured and omitted triangle counts. Each material includes slot indices, selected image/dimensions/UV source, sampled/measured counts, finite sampled world area, measured world/UV/texel areas, density/range, unknown reasons with counts, and coverage. A material with no sampled triangles is marked `not_sampled`.

`coverage="complete"` means every triangle in this inspected object had a supported measurement. It does not mean its UVs, material or artwork passed quality review. If the global sample budget omits triangles, measured statistics apply only to the samples and material coverage stays partial. Reused UV area is counted per triangle; the totals do not measure unique texture occupancy. The inspected world placement is used; differently scaled instances need their own measurement. Shader displacement, camera coverage, mip selection, streaming, compression, filtering and native GPU residency are outside this metric.

## TDD and verification

Four initial real-Blender tests were added first and failed because `texel_density` did not exist. The implementation and additional controls now pass in the **16-test diagnostic suite** on Blender 5.2.1 LTS (`9e2066aef7ef`). The density cases cover:

- A 1 m² world triangle, 0.5 UV area and 256×128 image produce exactly 128 texels/m; geometry, UVs, shader links, source transform and source mesh count are retained.
- Nonuniform object scale and a 0.01 scene unit scale change the measurement correctly. Active editing UV and Active Render UV differ, and a named UV Map node selects its explicit layer.
- Evaluated array geometry and an object-linked replacement material use the actual replacement image and both triangles; a one-triangle budget reports partial coverage and one omission.
- World areas 1 and 4 m² with identical texture areas produce a weighted result of about 80.954 texels/m, with a 64–128 range; the arithmetic mean of 96 is intentionally not used.
- Mapping/generated/object coordinate paths and a sequence image remain unknown; direct Texture Coordinate UV remains measurable.
- Degenerate world area, degenerate UVs, outside-tile UVs and non-finite shader UVs remain unknown without non-finite JSON.

The bake-specific `_uv_diagnostics` function was not changed; all **9 normal-bake tests pass** after the density increment. Ruff lint and format checks pass for the changed implementation and tests.

## Actual 8K material pilot

An additional read-only background process opened the existing [wooden-planks pilot](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/receipt.json) and inspected `FW_WoodenPlanks8K_Pilot`. It measured both triangles, 4.0 m² world area, 1.0 UV area and the actual 8192×8192 base-color image. Weighted, minimum and maximum density were all **4096 texels/m**, or 40.96 texels/cm.

The `.blend` SHA-256 remained `e5852146037f3cc970153bc6b9c93beba6692975e4e26e6f00f01297cb17ccc5`, and an in-memory source geometry/material/UV fingerprint was unchanged. The process did not render or save. This verifies the authored 2 m × 2 m pilot and its existing 8K image; it does not independently calibrate the photographed material's physical coverage or certify the artwork.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_diagnostics.py
```
