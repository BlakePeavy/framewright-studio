# Full stock human Rigify coverage

Added `scripts/test_full_human_rigify.py` on 2026-10-30 for bounded FW-030/033
coverage. It exercises the installed **full human** metarig, including fingers
and the bundled `faces.super_face` implementation. Earlier fixtures primarily
covered Basic Human or small synthetic rigs. No runtime module change was needed.

## Actual template and preservation

The fixture imports the installed `rigify.metarigs.human.create` into a new owned
scene with metric units and scale length one. The source is translated/rotated,
has an authored action, and deliberately references an existing target rig,
UI text, widget collection and custom shape. Its prior UI text would raise if
executed. Full generation must create separate rig/metarig/widget data, retain
world placement, begin hidden and leave the existing source/targets unchanged.

Before/after snapshots compare exact rest bones/hierarchy, raw transform channels,
action identity/keyframes, Rigify parameters, custom properties, target/script/
widget/custom-shape references, selection and frame. The resulting fingerprint
includes process-local ID identities; it demonstrates equality within that run,
not a portable asset-file hash. Custom finalize scripts are refused in both
preview and apply modes without execution. An injected generation failure creates
partial widget/text data; rollback removes that owned data and copied metarig
while retaining every pre-existing datablock.

The source template is the installed `rigify/metarigs/human.py`, SHA256
`5a73068517140a179750be019b2821e6570d98daa0a1409584cacda012ad1958`.
On Blender 5.2.1 LTS (`9e2066aef7ef`), its **159 metarig bones** produce
**706 generated bones**, including **160 deform bones** and **114 object drivers**.
Tests verify identifiable hand IK/FK, finger-master, jaw, eye, upper-eyelid and
tongue controls with widget references. Control presence alone is not the response
test described below.

## Measured responses

| Action on the generated stock rig | Observed response |
|---|---|
| Scale each of ten finger/thumb master controls on local Y to 0.65 | Corresponding deform-tip movement 0.04712–0.06999 m; wrist movement below 0.000001 m |
| Translate each hand IK control 0.03 m on local X, explicit `IK_FK=0` | Hand/finger-tip movement approximately 0.02990 m left and 0.02998 m right; opposite hand retained |
| Rotate `jaw_master` 0.25 rad on local X | `DEF-jaw` tail moves approximately 0.04029 m |
| Translate the shared `eyes` control 0.025 m on local X | Left/right eye-chain tails each move approximately 0.001949 m |
| Translate each upper-lid control −0.008 m on local Z | Corresponding upper-lid deform tail moves approximately 0.003389 m |
| Capture index/jaw/eyes controls and apply with Framewright to an independent pose derivative | All three evaluated tail positions match the authored pose with measured error zero; generated source remains unchanged |

The stock face implementation intentionally excludes eye bones from its `DEF-`
generation. Its original `ORG-eye.L/R` bones follow the eye mechanism; those
actual chains are measured for gaze response. This is not a claim of eyeball
skin weights or blink closure. The tests also verify that face adjustments leave
the unrelated right hand stationary. Framewright's pose-copy test exercises
constraint/driver remapping on this full rig rather than only storing matrices.

## Test-first evidence and repeatability

Eight actual Blender tests pass. The first run exposed a harness requirement:
stock Rigify's registration reads an in-memory preferences entry, so enabling it
in this factory-startup process uses `default_set=True`; no preferences-save
operation is called. A second test assumption incorrectly expected `DEF-eye`
names; inspection of the installed implementation established the correct eye
mechanism above. No production implementation defect was found or patched.

The selected [passing report](../artifacts/full-human-rigify/20261030T175501Z-271a5639/report.json)
retains template/script hashes and measurements. The
[execution receipt](../artifacts/full-human-rigify/verification-20261030T175442Z-86a2d5d9/execution.json)
and adjacent logs record the eight-test healthy run exiting **0**. A targeted
`--inject-disable-fingers` run leaves the finger master at rest; its movement is
zero and the required 0.005 m response assertion fails, exiting **1**. That
[failed-control report](../artifacts/full-human-rigify/20261030T175507Z-7e78f839/report.json)
is retained. It runs only the relevant finger test to avoid regenerating unrelated
rigs during a deliberate failure check. Ruff lint/format checks pass.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_full_human_rigify.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_full_human_rigify.py -- --inject-disable-fingers
```

The second command should fail. Each run writes a fresh report folder under
`artifacts/full-human-rigify`; `--output-dir` selects another parent. Existing
0.2 release receipts, reference assets, the human art candidate and game files
are not changed.

This closes a stock-template compatibility/pose-response coverage gap. It does
not fit hands or facial landmarks to the reference character, create production
weights or expression keys, certify hand grips/blinks/gaze/phonemes, inspect
rendered face deformation, validate the newer modular face upgrade, cold-execute
generated Rigify UI scripts, transfer full rigs to Unreal, or grant artistic
acceptance. Those original production requirements remain open.
