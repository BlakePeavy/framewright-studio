# Spatial PBR map handoff — 2026-10-30

The 0.3 FBX staging adapter fixes a reproduced data-loss defect: Blender's FBX
Principled wrapper sees direct image links but ignores the Separate Color node
used by Framewright's red-channel roughness and metallic recipes. The original
cold import retained base color and normal but silently lost both scalar maps.
GLB retained all four maps. The failing execution is retained in
`artifacts/pbr-map-handoff-red.log`.

`asset.export` now stages independent materials and exact red-channel images for
this supported FBX graph. A streamed **16-bit grayscale PNG** preserves scalar
values without applying a color transform. Direct image links let FBX embed the
maps. The source material, images, files and scene objects remain unchanged; all
staged materials/images/files are discarded after export or failure. Blender's
bundled NumPy processes scanlines; no runtime installation is needed.

The supported adapter requires file images in Non-Color, RGB Separate Color's
red output, default UV coordinates, and flat/repeat/linear sampling. Other
Separate Color scalar graphs are rejected before staging instead of silently
changing channel or mapping semantics. This is not a procedural shader baker.
Existing unrelated unsupported node graphs still require the export warning and
independent review.

The [independent preservation review](export-material-review.md) then reproduced
muted-node semantic loss and authored-value resets. Muted scalar paths and animated
material/group/image dependencies now reject before staging in the relevant
scope. Static export freezes animation only on its owned copies, retaining the
authored current pose and subframe; unchanged source scenes are not reevaluated.
Eight additional Blender regressions cover these fixes, including failure cleanup.
This does not promise arbitrary scene-property rollback during time traversal.

The optional integer `max_material_memory_mb` defaults to **512**, range 1–32768.
Preview reports the conversion plan and a conservative **64 bytes per unique
image pixel** estimate. One 8192² scalar map requires an explicit 4096 MiB budget;
two require 8192 MiB. This estimates temporary CPU work, not total process memory,
a hard allocation cap or GPU residency. GLB needs no such conversion. Material
intake has its own separate decoded-image budget. No textures are downsampled.

## Verification

- `scripts/test_export_materials.py`: ten real Blender tests cover preview without
  allocations, budgets/types, unsupported graph rejection, 16-bit precision and
  orientation, invalid scalar values, shared/object-linked slots, exporter failure
  and partial-file cleanup with exact retained source hashes/IDs.
- `tests/test_export_material_schema.py`: ten pure contract cases check explicit
  AI-request budgets and invalid types/limits.
- `scripts/test_pbr_map_handoff.py`: actual four-map sphere, two independent cold
  imports, all bindings required, fixed CPU Cycles renders and independent
  missing-roughness/metallic/normal controls. Non-gray G/B data deliberately tests
  preservation of **R**, rather than accidental luminance conversion.

The [initial passing report](../artifacts/pbr-map-handoff/20261030T180850Z-0677d4de/report.json)
measured RGB mean absolute errors of **0.000001102 for GLB** and **0.000003969 for
FBX**, against a fixture-specific ceiling of 0.008528. Missing roughness, metallic
and normal respectively produced 0.033274, 0.047089 and 0.024367. An actual
`--inject-missing metallic` invocation exited 1; its log is
`artifacts/pbr-map-handoff-control.log`. Input file hashes and source geometry,
UVs, shader graphs and pixel data were retained.

The [source image](../artifacts/pbr-map-handoff/20261030T180850Z-0677d4de/source.png)
and [cold FBX image](../artifacts/pbr-map-handoff/20261030T180850Z-0677d4de/fbx-cold.png)
were visually inspected. They are controlled 128px renders of spatial 64px maps,
not production artwork. The metric uses a fixed central crop of saved RGBA8 PNG;
it is not radiometric equivalence or a universal artistic tolerance. Native Unreal,
compression/mips, temporal behavior, glass/interior lighting and artistic approval
remain separate acceptance gates. The larger external-reference pilot is recorded
separately from this normal test fixture.
