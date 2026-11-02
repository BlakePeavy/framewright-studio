# Native surface diagnostics

The original 0.8 cabinet has matched 512px world-normal, roughness and metallic
readback in disposable Unreal 5.8.3. The [receipt](../artifacts/verification/native-surface-20261101.json)
retains inputs, captures, failures and comparisons. This follows the passing
[base-color study](native-appearance-review.md). No runtime code, public command,
source asset or saved engine asset changed. Full appearance remains unaccepted.

Scalar error limits remain mean ≤3/255 and P95 ≤8/255. Normal limits remain
mean ≤1° and P95 ≤3°. The two-pixel common-foreground mask is unchanged; metallic
uses its own source-metal region so the large wood surface cannot dilute failures.

| Three-quarter check | Mean error | P95 error | Result |
|---|---:|---:|---|
| World normals, matched point sampling | 0.191° | 0.730° | Within limits; control insufficient |
| Roughness, original native settings | 0.00449 | 0.00976 | Pass; zero-roughness control rejects |
| Metallic, original native settings | 0.03676 | 0.21123 | Fail |
| Metallic, full-precision UV diagnostic | 0.03732 | 0.19657 | Fail |
| Metallic, no-mipmap diagnostic | 0.00154 | 0.00595 | Within limits; zero-metal control rejects |

The no-mipmap trial changes only the packed roughness/metallic texture in memory,
then restores its setting without saving. Its improvement implicates mip-dependent
filtering. It does **not** distinguish atlas-island bleed from filter-footprint or
mip-selection differences. Disabling mips is not adopted as a production remedy.
The close view contains no metal and supplies no metallic acceptance evidence.

The initial source renders used a 1.5px Blackman-Harris filter against point-sampled
native GBuffer fields. Every normal error over 3° was near attribute boundaries.
Rerendering just the two affected source fields with a 0.01px Gaussian filter
resolves that measurement mismatch. Both EXRs survived a subsequent analysis
variable error; analysis resumed from those files without rendering again.
The normal corruption control (`NormalScale=-8`) still falls within the angular
limits in both views. The cabinet alone therefore cannot prove sensitivity.
The later [strong normal fixture](native-normal-validation.md) passes two
public export paths and rejects disabled/inverted controls in every region.

Imported SourceModel→RenderData comparison covers all 29 meshes / 5,836 triangles:
positions match, normal quantization reaches 0.338°, and half-precision UVs shift
by up to two texels at 8K. Full-precision UVs remove the shift but do not fix metal
error. Rebuilding also changes nine bounding coordinates by up to 0.00403 cm,
which fails the existing geometry gate. This is not an independent source-GLB→
native geometry proof, and no import precision policy has been promoted.

Nine focused metric tests pass after their initial missing-module failure.
Transient postprocess shaders must be primed before the isolated compilation
barrier; scalar calibration then reads exactly 0.25 in every pixel/channel.
All saved fixture files and the source blend remain byte-identical. Full suites,
imports and bakes were not repeated. Earlier failed attempts remain in the receipt.

Next: establish a matched mip/filter reference and a mip-safe atlas/material
correction. The stronger normal fixture is now complete; keep the
original limits and retained failures. Lighting, fine-edge behavior, full geometry,
collision/LOD, runtime and independent artistic acceptance remain open. The refined
0.9 cabinet and Sundown have not been validated by this study.

The [fixed-mip follow-up](native-mip-review.md) now isolates level-dependent errors
and motivates [declared padding](atlas-mip-padding.md). The original appearance
failure remains retained; the new layout control has separate focused evidence.
