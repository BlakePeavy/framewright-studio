# Preserve literal material values

The unreleased `surfaces.bake_material_atlas` command accepts
`preserve_material_constants: true`. It keeps unlinked Principled base color,
roughness and metallic values directly in output materials. An unlinked default
normal uses the mesh normal. Linked inputs still use the shared baked maps;
even a linked Value node is baked. Existing opaque/static admission rules apply.

```json
{
  "object_names": ["Body", "Hardware"],
  "resolution": 1024,
  "padding_mip_level": 1,
  "preserve_material_constants": true,
  "dry_run": true
}
```

The default is `false`, retaining one fully baked material. Opting in groups
matching literal values, preserves per-face assignments and may increase material
slots/draw calls. Preview refuses more than 256 candidate groups. All four packed
maps remain available; export can omit unused textures. This does not reduce bake
work yet. It cannot repair insufficient density or mip behavior in linked inputs.

Preview reports `material_policy` and `maximum_material_groups`. Apply reports
`materials` and `material_groups`, including each retained value and normal mode.
The legacy `material` field names the sole output when there is one, and is `null`
when there are several. Callers using this option must consume `materials`.
Source objects remain untouched; partial group creation rolls back owned outputs.

## Bounded cabinet evidence

The public 1K padding-only pilot exposed 16 visible metal pixels whose small UV
triangles missed the bake. Its source comparison failed (mean 0.01920). Increasing
padding does not recover an unsampled chart. That failure and its density diagnosis
are retained, alongside the constant-preserving correction.

The corrected public 1K atlas/export took 47.88 seconds end-to-end, with 509 MiB peak
working set. It produces three material groups, 29 meshes/5,836 triangles and two
exported textures. The 670-pixel source-metal comparison is exact both before export
and after cold GLB import. Object identities, hierarchy and transforms also pass.

The authorized disposable Unreal 5.8.3 import took 16.63 seconds; its separate cold
readback/capture took 15.72 seconds. All 35 saved packages pass native settings and
bounded geometry checks. The cold metallic GBuffer comparison passes unchanged
mean 3/255 and P95 8/255 limits: mean **0.001089**, P95 **0.002051**. A transient
zero-metal control fails (mean 0.85565), and the 0.25 readback calibration is exact.
The maximum pixel error remains 0.21309; this is not a per-pixel equivalence claim.
All saved asset bytes and the earlier fixture's 54 pins remain unchanged.

[Receipt](../artifacts/verification/atlas-constants-20261101.json): eight focused
Python 3.15.2 cases, four Blender cases and Ruff pass. Tests cover opt-in/default
contracts, linked fallback, per-face grouping/deduplication and rollback after
second-group failure. The cleanup fixture mocks the bake; the separate public
cabinet pilot performs the real bake. The new suite is registered for the next
milestone, bringing the configured count to 73; that aggregate has not been run.

The sealed 0.9 ZIP is unchanged. No 8K bake or full suite was repeated. This is one
metallic transport check on the original engineering cabinet, not accepted artwork.
Linked-map minification, normal sensitivity, lighting, full surface geometry,
collision/LOD, production readiness and game runtime acceptance remain open.
No Sundown assets were changed.
