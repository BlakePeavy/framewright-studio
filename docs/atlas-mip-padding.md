# Atlas padding for minification

The unreleased `surfaces.bake_material_atlas` command accepts optional integer
`padding_mip_level`. It budgets padding through that level of a power-of-two
texture. Level 0 is full resolution; level 4 is 1/16 resolution in each dimension.
This plans UV spacing and bake extension; it does not clamp an engine's mip range.

```json
{
  "object_names": ["Body", "Hardware"],
  "resolution": 8192,
  "padding_mip_level": 4,
  "max_memory_mb": 8200,
  "dry_run": true
}
```

This preview chooses a 48px margin. A supplied smaller `margin` is rejected;
a larger one is retained. Without `padding_mip_level`, existing margins/defaults
remain unchanged. More padding leaves less atlas area for surface detail.

The conservative margin budget is `3 × 2^level` base pixels, covering the summed
axis reach of a 2×2 box mip followed by bilinear/trilinear sampling, including
diagonal chart boundaries. The default 8px margin remains when it is sufficient.
The existing 64px margin limit admits levels 0–4; higher requests refuse rather
than silently reducing padding. Non-power-of-two textures cannot request this
model. Existing memory and layout limits still apply.

Preview reports `mip_padding.state = "planned"`. After packing, the command checks
the complete measured chart-gap lower bound against twice the actual margin and
the tile border against the actual margin, with 0.001px numerical tolerance.
An insufficient/nonfinite gap refuses before image allocation or baking and rolls
back owned derivatives. Success reports `"packing_verified"`. An omitted request
reports `"not_requested"`. Every state retains `native_filtering_verified = false`.

This is a padding/layout contract. It does not verify actual baked edge pixels,
compression, anisotropic or sharpening kernels, coarser engine mips, lighting or
art quality. Native comparison remains required. The
[native mip study](native-mip-review.md) explains why resolution alone was insufficient.

[Evidence](../artifacts/verification/atlas-mip-padding-20261101.json): 92 focused
Python 3.15.2 cases, four Blender checks and changed-file Ruff pass. The owned 512px
cube produces four packed maps with exact source preservation. Crowded packing,
injected insufficient gaps and a larger explicit-margin regression refuse cleanly.
The new suite is registered for the next milestone. No full suite or retained 8K
bake/import was repeated; the sealed 0.9 ZIP does not include this increment.

The [1K cabinet follow-up](atlas-material-constants.md) shows why padding alone
cannot fix unsampled tiny triangles. Optional literal material values now
preserve that fixture's metal response through cold GLB and isolated Unreal.
