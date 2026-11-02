# Native base-color review

The original 0.8 cabinet now has a bounded native pixel check in isolated Unreal
5.8.3. The [receipt](../artifacts/verification/native-appearance-20261101.json)
retains the captures, comparison scripts, failures, controls and source hashes.
This is evidence work; no public command or packaged runtime changed.

Two 512px native GBuffer base-color views are compared with Blender emission
renders using the same cameras, atlas image and UVs. Comparisons use stored RGB
codes, a two-pixel eroded common foreground, and an independent foreground overlap
check. Native GBuffer alpha is zero by design; the capture writes its RGB samples
to opaque PNG without compositing or contrast changes.

| View | Mean RGB error (limit 3/255) | P95 error (limit 8/255) | Foreground IoU (minimum 98%) |
|---|---:|---:|---:|
| Three-quarter | 0.005635 / 1.44 codes | 4 codes | 98.90% |
| Grain detail | 0.003250 / 0.83 codes | 2 codes | 100% |

Both material-loss controls reject: substituting the engine's basic material
raises mean interior error to 0.267 / 0.291. The native texture pattern, hardware
colors and camera framing correspond. Maximum local errors reach 95 / 13 codes;
thin boundaries alias and this is not pixel-exact geometry or full appearance parity.

![Native base color](../artifacts/native-appearance-20261101/three_quarter_base_color.png)

![Matched Blender base color](../artifacts/native-appearance-20261101/three_quarter_blender_base_color_v2.png)

The seven camera contract tests pass after the initial missing-module failure.
One native process took 19.06 seconds. The first two-view source comparison took
12.18 seconds and caught a gray World-node background that broke the silhouette
mask. A 9.87-second correction rerendered only the affected view, retaining the
original failure and reusing the detail pixels. Gates were unchanged.

All saved native asset bytes and the source blend are preserved. Temporary review
lights/camera/material overrides were restored without saving; Initial was restored.
Texture streaming was disabled only in the disposable process, and compilation
finished before readback. No import, bake or full suite was repeated.

The [lit native view](../artifacts/native-appearance-20261101/three_quarter_lit.png)
is dark and uses uncalibrated diagnostic lights. It is not a lighting comparison.
Normals, roughness/metal response, fine edges, full-resolution texture equivalence,
full geometry, collision/LOD, runtime and artistic approval remain open. This is
the original 0.8 cabinet, not the refined 0.9 source. Sundown remains unchanged.

[Follow-up surface diagnostics](native-surface-review.md) retain roughness results,
normal-control limits and a mip-dependent metallic mismatch. Full appearance stays open.
