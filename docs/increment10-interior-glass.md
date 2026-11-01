# FW-052: interior thick-glass lighting fixture

This increment adds `lighting.create_interior_fixture`, an explicit editable benchmark scene. It does **not** automatically light arbitrary user assets. The scene contains a real window opening, area key and interior fill, floor and room surfaces, a closed solid glass slab, a colored geometric checker target, a contact block, and front/three-quarter cameras. Scene creation performs no rendering or file writes and leaves the current authoring scene, selection, active object, frame, existing geometry and settings unchanged.

The implementation is separate from `production_assets.setup_review_scene`; its neutral/day/dusk asset-review behavior is unchanged. `light_review.create_interior_fixture` uses the existing owned-data transaction helpers, creates independent data, and removes only its own partial data on failure. The public command has a scene-mutation effect and defaults to `dry_run: true`.

Apply refuses registered `frame_change_pre/post` or `depsgraph_update_pre/post`
handlers before allocating any fixture data. Preview remains available and invokes
none of those callbacks. This supported-context boundary prevents a global callback
from modifying unrelated authoring data when the new scene's dependency graph is
updated; callbacks are neither disabled nor removed by the command.

## Parameters and admission budgets

| Parameter | Default | Supported range |
| --- | ---: | --- |
| `name` | `FW_InteriorGlass` | 1–48 printable characters |
| `resolution` | 512 | Integer 64–8192, square output |
| `samples` | 64 | Integer 1–512 |
| `glass_thickness` | 0.08 m | 0.005–0.25 m |
| `ior` | 1.5 | 1–2.5 |
| `roughness` | 0.03 | 0–0.3 |
| `window_power` | 1800 | 0–20000, Blender area-light power |
| `fill_power` | 60 | 0–5000, Blender area-light power |
| `exposure` | 0 | −8–8 stops |
| `max_pixel_samples` | 16777216 | Integer 4096–34359738368 |
| `max_render_memory_mb` | 512 | Integer 16–16384, interpreted as MiB |

Preview and apply both reject `resolution² × samples > max_pixel_samples` or a `resolution² × 64` byte buffer allowance above the stated memory budget. These are admission estimates, **not runtime memory/time caps**, and do not constrain later manual scene edits. Geometry, renderer temporaries, devices and other allocations are additional. An explicit 8192-square, one-sample preview with 4096 MiB allowance is tested without allocating an image or rendering.

The fixture deliberately supports thick slabs: the default 80 mm and rendered 200 mm stress case make optical displacement measurable at a small output size. They are not recommendations for ordinary architectural window thickness. A 5 mm control is rendered separately.

## Actual Blender APIs and checks

The installed Blender 5.2.1 LTS (`9e2066aef7ef`) was queried before implementation. The material uses its actual Principled `Transmission Weight`, `IOR` and `Roughness` sockets. Transmission is 1 on the reference slab; alpha blending is not substituted for transmission. The closed box has eight vertices, twelve edges and six outward faces before the small bevel modifier. Cycles uses twelve transmission bounces, sixteen total bounces, CPU rendering, fixed seed, no adaptive sampling or denoising, and disabled reflective/refractive caustics. The fixture selects AgX/None, explicit exposure and gamma 1.

The test suite was written before the module existed and failed on the missing module. After implementation, eight real-Blender scene/API tests pass: preview allocation, malformed requests, budgets including an explicit 8K preview, editable geometry and shader settings, floor contact, exact source-context preservation, failure rollback, repeated-name safety, main-thread refusal, and public preview/apply dispatch. No external files or arbitrary shader graphs are accepted by this command.

An independent review added four real-Blender regressions in
`scripts/test_light_review_independent.py`. A genuine red showed a registered
dependency-graph callback changing an unrelated authored property from `123` to
`-999` while creation returned success. The new preflight makes that case green
without invoking the callback or allocating data. All four callback categories
reject apply while retaining nonmutating preview. Dirty animated light energy,
material roughness and constraint influence remain exact during supported
creation; an injected failure after allocating the second camera removes every
owned datablock. The original eight tests and these four tests pass. Evidence is
retained in `artifacts/light-review-independent-red.log`,
`light-review-independent-green.log` and `light-review-suite-green.log`.

The rendered test first failed while its implementation was missing. It then produced actual 256 × 256, 64-sample Cycles images for nine variants: thick reference, transmission zero, slab removed, IOR 1, 5 mm thin slab, contact block removed, block raised 20 cm, unchanged repeat, and front view. The comparison region is computed from the projected glass bounds. Horizontal checker-edge correlation distinguishes displacement from a simple missing-image test. Floor samples are ray-checked to hit visible floor outside directly occluded block pixels; their change is evidence of the block's lighting influence, with indirect reflection also possible. Tests restore the original raw block location rather than adding/subtracting offsets, avoiding floating-point transform drift in the owned fixture.

An intentional `--inject-opaque-glass` run changes the reference slab's transmission to zero. It must fail because the supposed transparent baseline becomes identical to its opaque control. This is a negative regression control, not a second accepted scene.

## Recorded rendered evidence

The selected post-review run is [the comparison sheet](../artifacts/interior-glass/20261030T185949Z-c9620296/index.html), with [measurements and hashes](../artifacts/interior-glass/20261030T185949Z-c9620296/report.json), [the passing test result](../artifacts/interior-glass/20261030T185949Z-c9620296/test-result.json), and [the editable scene](../artifacts/interior-glass/20261030T185949Z-c9620296/interior-glass-reference.blend). The default rendered test passed in about 27.8 seconds while the independent negative-control process ran concurrently. The eight scene/API tests, four independent preservation tests and Ruff checks also passed.

| Measurement | Recorded value |
| --- | ---: |
| Opaque versus thick-glass RGB mean absolute difference | 0.084898 |
| IOR 1 versus thick-glass difference | 0.042829 |
| 5 mm versus 200 mm slab difference | 0.037548 |
| Thick glass versus removed slab difference | 0.055669 |
| Opaque versus removed slab difference | 0.073717 |
| Best horizontal checker-edge shift, within ±6 pixels | −1 pixel |
| Edge correlation at that shift / at zero shift | 0.613935 / 0.137393 |
| Visible floor samples outside primary block occlusion | 255 |
| Mean floor RGB increase with contact block removed | 0.050340 |
| Maximum unchanged-repeat pixel difference | 0 |

Direct inspection of the final pixels confirms that the thick slab transmits the checker, the opaque control obscures it, the thin/IOR controls alter its apparent position, and raising the contact block creates a visible gap. Removing the block also removes its visible floor shadow. These observations accompany the bounded measurements; they do not establish calibrated optical correctness or production lighting quality.

Source-context fingerprints match exactly before and after the render experiment, and the owned glass/block controls are restored exactly before saving. All nine final PNG hashes and the current module/script hashes were verified. The saved `.blend` SHA-256 is `6f1fc3abf5b3646af1b1fdb684c9bb449795d2aa0f27b5442f4103ba3af86ced`.

The [intentional opaque-baseline run](../artifacts/interior-glass/20261030T185949Z-27adda48/test-result.json), using the same script and module hashes, exits **1** with one assertion failure: opaque-versus-baseline difference is 0 instead of greater than 0.015. Its failed artifacts are retained separately. Earlier successful development images remain historical evidence; they are not substituted for this selected run.

## Reproduce

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_light_review.py
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_interior_render.py
```

Append `-- --inject-opaque-glass` to the second command for the expected failure. Render tests require background Blender and create a unique `artifacts/interior-glass/<run>/` folder containing PNGs, an editable `.blend`, source/module/script hashes, measurements, an HTML comparison sheet and `test-result.json`. The API itself does none of these file operations.

## Limits

This is a synthetic fixture with nominal Blender light powers and explicit geometry. Pixel thresholds and correlation offsets are specific regression evidence, not universal lighting quality criteria. The renders are visibly noisy at the bounded sample count. Disabled caustics, absent volume absorption and RGB material evaluation do not validate physical spectral or caustic behavior. No photographic exposure, lux, display calibration, architectural glazing specification, arbitrary-material baking, native Unreal glass parity or artist approval is claimed. Existing production-art and native-engine gates remain open.
