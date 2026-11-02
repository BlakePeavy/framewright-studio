# Native mip-level evidence

The [retained study](../artifacts/verification/atlas-mip-padding-20261101.json)
continues the [surface investigation](native-surface-review.md) on the original
0.8 cabinet. All source/saved native files remain unchanged. The original scalar
limits (mean 3/255, P95 8/255) and 670-pixel metal region remain unchanged.

CPU sampling reconstructs perspective UVs from all 5,836 saved RenderData triangles,
with the saved camera and source metallic image. Five focused tests cover perspective
interpolation, texel centers/wrapping, mip averaging, derivative-based level selection
and invalid inputs. No-mipmap native/CPU error is 0.00123 mean / 0.00595 P95.
The computed median metal mip is 3.81; the original atlas used a four-pixel margin.

Transient native materials then sample the original packed texture at fixed levels:

| Mip | Native vs source mean / P95 | Native vs CPU box-mip mean / P95 |
|---|---:|---:|
| 0 | 0.00154 / 0.00595 | 0.00123 / 0.00595 |
| 3 | 0.02112 / 0.12635 | 0.00562 / 0.02260 |
| 4 | 0.06790 / 0.30863 | 0.00858 / 0.02864 |
| 5 | 0.12189 / 0.37994 | 0.01734 / 0.05880 |

Mip levels 3/4 agree with the box-mip reference within the existing limits, but
their source comparisons fail. Level 5 also fails the native/reference comparison.
This supports addressing atlas edge filtering; it is not full mip/decoder parity.

The replacement automatic shader agrees with the CPU reference (0.00950 mean /
0.03051 P95), but differs from the original imported material (0.02872 mean /
0.14111 P95). Imported material sampler behavior therefore remains unresolved.
The texture asset itself reports trilinear filtering, zero LOD bias and the World
group. Texture settings alone do not prove shader sampling equivalence.

The first native run retained its automatic capture before a pin-name failure:
MaterialEditingLibrary expects the shortened `Level` name for the expression's
`MipLevel` input. The focused retry captures only the missing levels in 36.94s.
It restores materials and Initial, and preserves all 54 pinned fixture files.
CPU comparisons reuse pixels; no retained atlas rebake or import occurred.

The new [padding option](atlas-mip-padding.md) lets callers budget and verify chart
spacing for a declared mip range. Next validate a small cabinet derivative through
the public handoff and native comparison, and resolve the imported sampler difference.
Do not repeat the 8K bake until that pilot passes. Normal sensitivity, lighting,
full geometry, runtime and independent artistic acceptance remain open.
