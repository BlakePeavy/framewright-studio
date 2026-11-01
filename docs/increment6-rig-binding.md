# Provisional automatic heat binding

`rig.bind_mesh` calls `framewright.rig_binding.bind_mesh(params, context=None)`.
It proposes initial weights for an explicitly selected mesh and armature on a
separate hidden mesh derivative. It does not infer skeleton fit or approve
deformation quality.

Required parameters are `object_name` (exact scene mesh) and `armature_name`
(exact scene armature). Optional parameters:

| Parameter | Default | Bounds / effect |
|---|---|---|
| `dry_run` | `true` | Preview performs validation without allocating a derivative |
| `max_vertices` | `100000` | Integer 1–1000000; base mesh budget |
| `max_deform_bones` | `256` | Integer 1–1024 |
| `require_complete_weights` | `true` | Discard the copy if any vertex has no positive deform weight |

Both objects must be local and in the current view layer, with finite invertible
transforms. The source mesh must be unparented and unanimated, have faces, no
vertex groups, constraints or shape keys, and only SUBSURF/MULTIRES modifiers.
The chosen armature's current authored controls and deform bones must match rest.
Object Mode and Blender's main thread are required.

The derivative's subdivision modifiers are temporarily disabled during base-mesh
heat weighting, then retained after its new Armature modifier. Only newly created
deform weights are normalized; their relative ratios are preserved. There is no
envelope fallback. Blender warnings that leave unweighted vertices cannot be
silently treated as complete binding. When the caller explicitly allows partial
weights, the result reports the count and first 64 indexes. Every applied result
is `needs_review`, including complete weights.

The source geometry, source rig pose, selection, active object, frame and rig
visibility are retained. Failures remove only the owned mesh object/data. The
result starts hidden in viewport and render and points to the explicitly chosen
armature; it does not replace the source mesh or generate a new skeleton.

## TDD evidence

`scripts/test_rig_binding.py` runs six actual Blender fixtures. The initial test
run failed because the implementation did not exist. The first implementation
then exposed two real failures: heat weights differed from sum one by 0.021649,
and a hidden rig's cached matrix failed to reveal a moved raw pose channel.
Normalizing only the new weights and checking raw rotation/location/scale
channels corrected those cases without weakening the assertions.

All six tests pass in Blender 5.2.1 LTS. They cover read-only preview, actual
heat-weighted deformation of the copy, exact source/context restoration,
subdivision retention, invalid state/budgets, injected operator failure, and
post-heat incomplete-weight rollback versus explicit partial reporting.

```powershell
& $Blender --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_rig_binding.py
```

Automatic heat is synchronous and may be expensive inside the caller's declared
budget. It is an initial skinning method, not an artist influence-count limit,
protected-region guarantee, anatomical correctness check or animation acceptance.
The human pilot below records authored fit and rendered joint samples; no
character acceptance is inferred from these fixtures.

## Provisional human pilot

`scripts/build_human_rig_pilot.py --source <pinned-bundle-member.blend>` runs in
the same isolated Blender invocation (script arguments follow `--`). It reads
the independently retained Human Base Meshes v1.4.1 member, verifies SHA-256
`3c121505651140ceb4d69fd1d8923f7788ffadd81672f5be14845a5f2c75c137`, and appends
only `Body Male - Realistic` into a new owned scene. Reference provenance and
the bundle's retained license evidence remain in the independent review kit.

The script contains explicit authored joint coordinates in local meters,
based on inspected front/side anatomy views and local mesh coordinates. It
does not derive anatomy from a bounding box. The fit intentionally assumes
bilateral symmetry, preserves stock bone rolls and uses Basic Human without
finger or facial controls. These are provisional authoring choices requiring
review, not approved anatomical landmarks.

The actual chain is `rig.fit_metarig` → `rig.generate` → `rig.bind_mesh`.
The two separate eye derivatives attach explicitly to `DEF-spine.006` and
follow head motion; they have no authored gaze/blink system. The original
body/eye geometry and source bundle hashes remain unchanged. Their appended
objects are hidden for review, and all authoring remains outside the game.

The first real pilot revealed a placement defect: stock Rigify created its new
target at identity although the source metarig was translated. Consequently
automatic heat bound the translated body to distant bones. A translated and
rotated metarig regression failed before fixing `generate_rig` to assign the
source world matrix to its newly generated derivative. The same 12-test rig
suite then passed without weakening source or world-head-position assertions.
The initial faulty pilot is retained, superseded by the corrected run below.

Corrected run: `artifacts/human-rig-pilot/20261030T170355Z-f205d2b9/` contains
`provisional-human-rig.blend`, `authored_landmarks.json`, `report.json`, and 18
actual 384-pixel CPU Cycles/AgX PNGs (32 samples): front, side and three-quarter
views of neutral, 110-degree elbows/knees, 90-degree shoulder/hip stresses and
a 45-degree head stress. The shoulder and head cases use explicit local axes;
they are not labelled anatomical abduction/yaw. Feet are intentionally airborne
in the bilateral knee stress; this is not a grounded performance clip.

The 10,582-vertex body bound to 35 deform bones with zero unweighted vertices,
maximum seven influences and maximum normalized sum error 4.48e-8. Viewport
sampling uses the base mesh; render-only multires is one level on the derivative.
Original multires settings are retained. Fifty evaluated frames were measured.
An independent process reopened the saved blend with auto-execution disabled:
all 50 sampled scalar measurements matched exactly, source hashes matched after
evaluating the hidden originals, and each attached eye moved about 0.07068 meters
in the head stress. `cold-verification.json` records that evidence. The generated
Rigify UI script was not executed by the verification process.

| Diagnostic frame | Maximum edge ratio | Minimum edge ratio | Signed volume / neutral |
|---|---:|---:|---:|
| Elbows 110° | 1.961 | 0.285 | 0.9947 |
| Knees 110° | 1.565 | 0.253 | 0.9861 |
| Shoulders 90° local-axis stress | 2.323 | 0.357 | 0.9551 |
| Hip/knee 90° | 2.125 | 0.135 | 0.9526 |
| Head 45° local-axis stress | 2.483 | 0.183 | 0.9999 |

These are warnings for review, not passing deformation thresholds: substantial
local compression/stretch remains despite complete normalized weights. A second
agent inspected ten actual PNGs independently and confirmed full-body framing
without global alignment failure. It identified a shoulder backward-axis stress
failure: upper arms disappear behind/through the torso with conspicuous deltoid
bulges; this is not accepted shoulder abduction. The hip stress has a hard groin
fold and strong hip/buttock compression, and the knee stress shows very tight
pointed creases. Full-body 384-pixel images cannot certify volume or resolve
interpenetration. Joint closeups are required before deformation acceptance.
Eight subsequent 512-pixel, 48-sample closeups are retained in `closeups/` with
camera targets/settings and the unchanged saved-blend hash in `closeups.json`.
Their actual pixels were inspected: the shoulder stress clearly compresses the
upper arm against/through the torso and the knee contains a sharp crease with
a dark fissure. These closeups strengthen the failure evidence; they do not
resolve it or grant acceptance.
The rig needs artist-reviewed fit/rolls, painted weights, finger/face/eye
controls, corrective shapes and ground-contact motion work.
No AAA quality, complete character deformation or native-game acceptance is
claimed. Re-running creates a unique output folder and never overwrites a pilot.

## Anatomical pose and corrective follow-up

The builder now authors explicit body-frame directions (forward −Y, left +X,
up +Z) instead of interpreting arbitrary local Euler axes as anatomical motion.
`scripts/test_human_pose_targets.py` has five real Rigify regressions covering
translated/rotated rigs, shoulder abduction/flexion, measured knee/elbow bend
angles, hip forward flexion and neutral restoration. Actual world joint positions
and direction errors are recorded by the builder. Earlier local-axis stress
images remain historical failure evidence and are not relabelled as abduction.

The independent refinement workflow `scripts/refine_human_rig_pilot.py` retains
the input candidate and creates separate pose/skin derivatives. It also exposed
a second placement defect: reassigning a copied skin's parent reset Blender's
parent-inverse matrix. `apply_pose` now preserves that matrix exactly. Its new
red→green fixture includes translated, rotated and nonuniformly scaled parents,
checks source preservation and compares evaluated world-space skin vertices.
All eight secondary-motion fixtures pass.

The refinement compares linear skinning, preserve-volume skinning, bounded
joint-patch weight smoothing and explicit basis-relative pose correctives.
The corrective proposal searches bounded authored displacement fields, records
every trial and rejects excessive stretch growth. Original weights and vertices
outside each corrective patch are retained. These are provisional candidate
experiments; a lower intersection count alone is not artistic acceptance.
Early refinement runs `171805Z-2d1e82ff` and `171846Z-650d2624` contain invalid
placement/blank-render reproductions and are marked explicitly invalid. Selected
render runs now reject images with insufficient subject pixel coverage and check
that eye attachments remain near the authored head. Final matched-render and
cold-reopen evidence is recorded with each generated artifact before selection.

### Verified provisional corrective checkpoint

The selected **technical-improvement candidate** is
`artifacts/human-rig-refinement/20261030T173751Z-1625c77f/`, with an `index.html`
comparison page, `refined-human-rig.blend`, full trial/measurement `report.json`,
38 matched before/after PNGs and `cold-corrective-regression.json`. It retains
the original candidate and comparison alternatives. It is not an artist-approved
character or a declaration that its remaining deformation defects are resolved.

The actual intended poses are neutral, shoulder abduction 90°, shoulder forward
flexion 90°, elbows 110°, knees 110°, left hip forward flexion 90° with knee 90°,
and head yaw 45°. Direction targets are in the authored body frame; actual world
joint positions are measured. The corrected abduction is a lateral T-pose.

Four editable basis-relative corrective keys use bounded authored separation
fields on shoulder, elbow, knee and hip patches. The comparison preserves the
original weights. Trials that exceeded the configured stretch-growth guard were
rejected. Preserve-volume skinning and weight-smoothing alternatives were retained
for comparison rather than silently selected: they had mixed results, including
worse hip intersections/compression. Remaining geometric problems are explicit.

| Same intended pose | Before L / R intersection pairs | Corrective L / R pairs |
|---|---:|---:|
| Shoulder forward flexion 90° | 38 / 40 | 12 / 13 |
| Elbow flexion 110° | 42 / 36 | 37 / 29 |
| Knee flexion 110° | 31 / 30 | 28 / 27 |
| Left hip 90° / knee 90° | 15 / 0 | 12 / 0 |

These counts cover nonadjacent triangles fully within the explicitly authored
joint patches; shared-vertex pairs and patch-crossing triangles are excluded.
They are comparative measurements, not whole-character collision clearance.

An independent factory-startup process reopened the saved candidate with script
auto-execution disabled. It reproduced all recorded endpoint measurements exactly
(maximum scalar difference zero), rejected the disabled-corrective control,
passed the bounded improvement/volume assertions, verified 41,007 protected
shape-key vertex comparisons, and retained the original weights and input file
hash. Both eye centroids remained near the authored head and moved approximately
0.07852 m during the head-turn sample. All 38 saved PNGs passed subject-coverage
checks; the final actual pixels were also inspected.

Independent root review found a visible shoulder improvement: the angular
upper-deltoid notch becomes rounder. Underarm compression/bulging remains. The
knee before/after looks nearly unchanged at the displayed scale and retains a
sharp crease/pinch; it is **not resolved**. Elbow and hip corrections have smaller
quantitative changes and retain visible shape/compression concerns. No blank or
measurement-only run is counted as visual acceptance.

The current keys are sampled-pose authoring, not a validated continuous pose-driver
system. Full-range activation, interpolation between samples, protected-region
appearance, remaining intersections, natural contact motion and native skeletal/
morph export still need work. Finger/face/gaze/blink controls remain unauthored.
Further bounded authoring and testing can proceed without treating the need for
eventual independent artistic approval as a blocker to engineering progress.

Follow-up, 2026-10-30: [continuous corrective activation](increment7-corrective-activation.md)
now has independent left/right joint-angle drivers, 39 fractional/reversing/asymmetric
human samples, disabled-autoexec cold reproduction, and a bounded public command.
This closes the activation gap for that explicit pilot scope; the knee crease and
the deformation/artistic limits above remain open.
