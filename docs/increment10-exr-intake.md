# EXR data-map intake and authored cabinet reference

The 0.4 intake adds bounded OpenEXR **data maps** for roughness, metallic and
tangent normals. PNG/JPEG behavior is retained. EXR base color is rejected because
this recipe has no explicit linear-color/chromaticity contract; it must not guess
sRGB from a filename. Source files/pixels are not rewritten, clamped or upsampled.

The parser follows the [OpenEXR file layout](https://openexr.com/en/latest/OpenEXRFileLayout.html)
and [standard attributes](https://openexr.com/en/latest/StandardAttributes.html):
single-part scanline version 2, full-resolution HALF/FLOAT Y, RGB or RGBA channels,
matching zero-origin data/display windows and square pixels. Deep, tiled,
multipart, layered/AOV, subsampled and unsigned-integer channels remain unsupported.
Names, attribute counts and the complete header are bounded; the existing file-size,
path, hash and admission checks still apply. Metadata inspection does not decode
chunks or certify a valid image.

Actual apply first verifies the scanline offset table, row coverage, payload extents
and non-overlapping chunks before allocating Blender data. It then loads fresh
Blender images, retains Non-Color semantics, verifies
dimensions and all decoded RGBA values are finite, and reports the observed RGB
range. Potentially lossy compression modes are explicitly recorded. Finite values
outside [0,1] remain unchanged and are flagged, since source compression/HDR data
can exceed this interval. This does not certify valid normal vectors or scalar
artistic intent. The request estimate is 16 bytes/pixel for PNG/JPEG, **36 for EXR**
(decoded RGBA float buffer, validation copy and finite mask); native decoder,
GPU and other process allocations are additional. This is not a hard memory cap.

## TDD and concrete reference

The initial intake run failed 18 supported-format cases before implementation.
`tests/test_exr_intake.py` has 36 cases, including malformed/truncated/duplicate
headers, flags, windows, channels, compression and budgets. With existing material
metadata tests, 44 tests and 19 subtests pass. Six real Blender tests cover actual
EXR precision/routes, shared-image preservation, a header with missing pixel chunks,
injected nonfinite decoded pixels, retained HDR range and partial-validation cleanup.
Independent review reproduced a truncated payload that Blender silently decoded.
The new container guard closes that failure: 33 additional pure tests and four
independent Blender tests pass. Receipts distinguish container structure, finite
decoded buffers and unverified codec semantics; see the
[independent review](increment10-exr-structure-review.md). The final 0.4 aggregate
also passed; see [verification](verification.md).

The external reference is [Painted Wooden Cabinet](https://polyhaven.com/a/painted_wooden_cabinet),
an authored CC0 asset by Kirill Sannikov from Poly Haven. The published asset files
were downloaded through its API with Framewright's user-agent and retained with
published size/MD5 checks plus local SHA256 hashes. No website preview render was
copied. [Poly Haven's asset license](https://polyhaven.com/license) and
[API terms](https://github.com/Poly-Haven/Public-API/blob/master/ToS.md) are recorded.
Powered by Poly Haven; no endorsement is implied.

The [download receipt](../artifacts/reference-candidates/painted_wooden_cabinet-4k/download-receipt.json)
retains the original 168,349-byte `.blend`, JPEG color and three EXR maps. Source
blend SHA256: `0db52d5cfede78a38aed7316109aad213a63396504326e06a24e4c72b85abc8e`.
It has five separate cabinet/door/drawer meshes and original 4096² maps. These
references remain ignored local artifacts; they are not shipped in the extension.

The [current recipe review](../artifacts/cabinet-reference-pilot/20261030T185917Z-db62bd9f/index.html)
contains eight actual 512px, 64-sample CPU Cycles/AgX images: front, side, back and
three-quarter views of retained authored-material copies versus fresh recipe copies.
The original `.blend`, texture bytes, mesh/UV/material graphs and assignments remain
unchanged. The saved editable derivative passed a disabled-autoexec cold reopen
with all four 4096² maps and shader bindings intact. All three EXR receipts include
128 verified scanline chunks covering 4,096 rows and finite decoded buffers.

Observed full-image RGB MAE is 0.000357 front, 0.000161 side, 0.000340 back and
0.000617 three-quarter; local maximum differences reach 0.251. These are reported
comparisons with render noise and differing shader routes, not an exact-parity claim.
The source and recipe front/three-quarter images were inspected: chipped paint,
panels, hardware and grain remain visibly consistent at this resolution. Bright
paint and modest view resolution limit fine-detail assessment.

The source's HALF DWAA maps actually exceed the unit range: roughness reaches
1.010742 and normal channels 1.030273, with small negative minima. Intake preserves
and reports those values. Default FBX scalar conversion rejects them. The explicit
`clamp_scalar_textures: true` FBX option clips only owned staged scalar images and
reports the changed-pixel count; nonfinite pixels still fail. Four real Blender
regressions verify this behavior and source preservation. Native handoff, geometry refinement
against this reference, final artistic approval and 8K-frequency detail remain open.

## Actual cold cabinet handoff

The [handoff review](../artifacts/cabinet-handoff/20261030T190016Z-be43fd74/index.html)
contains twelve 512px renders: four matched source, cold GLB and cold FBX views.
The pilot explicitly evaluates Geometry Nodes/weighted normals into five owned
static mesh copies. This is a recorded pilot operation, not a general public
modifier-bake API. Original blend/texture bytes and source geometry/material graphs
remain unchanged, and all runtime/helper hashes match before and after the run.

Both fresh imports retain five named parts, world bounds (maximum error 5.97e-8 m
GLB / 1.79e-7 m FBX), UV/slot counts, all four shader bindings and 4096² map sizes.
The 73,026,388-byte GLB and 43,770,924-byte FBX are retained with export receipts.
Default FBX conversion rejects the observed unit-range overshoot. Explicit staging
clips 684 roughness pixels and 26,773 metallic pixels out of 16,777,216 each, then
quantizes the owned images to 16-bit; source EXR samples are preserved.

| View | GLB RGB MAE | FBX RGB MAE |
|---|---:|---:|
| Front | 0.0000112646 | 0.0000008028 |
| Side | 0.0000035105 | 0.0000003690 |
| Back | 0.0000047472 | 0.0000010921 |
| Three-quarter | 0.0000094744 | 0.0000007280 |

The maximum individual RGB difference is 0.12549 GLB / 0.03137 FBX. Source and GLB
three-quarter plus FBX front images were inspected: paint wear, panel boundaries,
grain and hardware remain consistent at this scale. These measured comparisons
do not certify all hidden topology, full 4K spatial detail, native parity or artist
acceptance. No Sundown asset was imported or changed.

Reproduce the development pilot in an owned background Blender process:

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/build_cabinet_reference_pilot.py -- --source-kit artifacts/reference-candidates/painted_wooden_cabinet-4k
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/verify_cabinet_handoff.py -- --source-review artifacts/cabinet-reference-pilot/20261030T185917Z-db62bd9f
```
