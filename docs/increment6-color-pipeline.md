# Controlled color-pipeline evidence

Implemented on 2026-10-30 for FW-051. `scripts/test_color_pipeline.py` adds a bounded
render/file-pipeline fixture without changing the extension API or live scenes.
It is a software color/exposure reference, not physical monitor, camera, material
reflectance or photographic-light calibration. It grants no AAA or native-game
artistic acceptance.

## Explicit source and transforms

Eighteen flat emission patches use specified **Linear Rec.709** RGB values. Eleven
neutral patches range through 0, 0.003, 0.018, 0.036, 0.18, 0.36, 0.5, 1, 2, 4 and 8.
Additional patches contain single-channel 0.18 primaries and paired warm/cool colors
whose scene-linear values differ by exactly two. A black zero-strength world,
orthographic camera and emission strength one remove incident-light/material
ambiguity. Interior samples exclude labels and antialiased boundaries.

The fixture renders once in CPU Cycles at 768×432, four samples, seed zero, four
threads, no adaptive sampling or denoising. It saves Standard and AgX outputs at
exposure zero and +1 with sRGB display, look None, gamma one, curves/white balance
disabled and zero dithering. PNGs are 8-bit RGBA. EXRs are 32-bit float RGBA with
lossless ZIP compression, saved at both exposure settings.

Blender documents scene-linear rendering/storage separately from display encoding,
and recommends high-precision scene-linear OpenEXR for intermediate files.
See [Color Spaces](https://docs.blender.org/manual/en/5.1/render/color_management/color_spaces.html).
Exposure multiplies the linear input by `2^exposure` before the display transform;
gamma is a separate post-transform adjustment. See
[Displays and Views](https://docs.blender.org/manual/en/5.0/render/color_management/displays_views.html).
The tests below measure the installed 5.2.1 implementation rather than assuming
those documents alone prove its behavior.

## Independent process checks

A fresh Blender process with temporary user directories and automatic execution
disabled checks every saved image hash, then decodes central 5×5 pixel means.
EXRs must be detected as Linear Rec.709 and match the specified emission values
within absolute error `0.00002`. This includes values above one; clipping them
fails. PNGs are explicitly read as Non-Color to measure stored display-encoded
bytes without applying a second transfer function.

Standard has an independent analytic target: clamp the piecewise sRGB encoding
of `linear_RGB × 2^exposure`. Display tolerance is `1/255 + 0.00001`, allowing
8-bit quantization. Both views must retain neutral channel balance and monotonic
grayscale; AgX must distinguish the sampled HDR steps instead of clipping them
like Standard. For eight scalar/color pairs both views must satisfy
`display(2×input, exposure=0) == display(input, exposure=1)` within that tolerance.
This relation does not assert that encoded pixels double, or invent a closed-form
AgX tone curve.

Six test-first validator cases initially failed against unimplemented checks.
They now pass, including clipped-HDR, non-finite/missing samples, wrong exposure
and treating linear values as display encoding. The actual-render negative
control saves +1-stop pixels, then deliberately asks the Standard validator to
interpret them at zero. Ordinary runs verify that this control is rejected;
`--inject-corruption exposure` propagates it as a failing CLI result.

## Recorded results

The selected [review sheet](../artifacts/color-pipeline/20261030T173514Z-a2493eca/index.html),
[inputs/settings/hashes](../artifacts/color-pipeline/20261030T173514Z-a2493eca/inputs.json)
and [cold measurements](../artifacts/color-pipeline/20261030T173514Z-a2493eca/cold-verification.json)
are retained locally. They use Blender 5.2.1 LTS build `9e2066aef7ef`, OpenColorIO
2.5.0 and OpenImageIO 3.1.13. The active OCIO config hash is
`df5714c85d5afb5e9762281503a0c48a9f65dadb22d32a3aee50c454a0821f62`;
all 23 files in its installed configuration directory are also hashed.

| Measurement | Observed result |
|---|---:|
| EXR maximum absolute error, exposure 0 and +1 | 0.00000002861 |
| Largest retained EXR value | 8.0 |
| Standard sRGB maximum error, exposure 0 / +1 | 0.00189793 / 0.00162471 |
| Neutral RGB channel spread, both views | 0 |
| One-stop versus doubled-input error, both views | 0 |
| Intentional wrong-exposure maximum error | 0.26464302, rejected |

The two EXRs are byte-identical: the display exposure did not bake into their
scene-linear values. For linear gray 0.18, Standard PNG measures 0.462745 at zero
and 0.635294 at +1; AgX measures 0.462745 and 0.603922. Actual inspected chart
pixels show readable labels, neutral ramps, Standard's clipped HDR patches and
AgX's preserved HDR gradation. Antialiasing at patch/label edges is outside the
central measurement region. The chart geometry and emission fingerprint remained
`185bdf4f1e400a221234a110821109b4c3b60414809fa0c480d6ef58ad47aff8`.

The [execution receipt](../artifacts/color-pipeline/verification-20261030T173511Z-8d9bfd12/execution.json)
and adjacent logs record six unit checks exiting **0**, the healthy render/cold
decode exiting **0**, and the intentional corruption invocation exiting **1**.
Its failed run is retained at `artifacts/color-pipeline/20261030T173519Z-aed300bb`.

## Reproduce and remaining scope

```powershell
uv run --frozen python scripts/test_color_pipeline.py --self-test
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_color_pipeline.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_color_pipeline.py -- --inject-corruption exposure
```

The final command is expected to fail. Each render creates a unique folder under
`artifacts/color-pipeline`; `--output-dir` chooses another parent. No network,
provider credit, user preferences or game files are used. The cold child has a
60-second timeout. Only this installed OCIO/Blender/CPU path is measured; the
independent process uses the same Blender decoder, not an independent EXR library.
GPU/viewport/OS display management, wide-gamut/HDR monitor delivery, compositing,
camera response, photographic reference exposure, real material reflectance,
native Unreal parity and artist-approved lighting remain separate work.
