# Corrective morph animation handoff — 2026-10-30

`animation.bake_shape_keys` now samples authored corrective weights into a hidden
independent mesh/Key/action derivative and explicitly rebinds that skin to an
already baked rig. The original rig, mesh, shape geometry, weights, drivers and
actions remain unchanged. This is a bounded feature verified in version 0.4.

Required parameters are `object_name`, `armature_name`, `baked_armature_name`,
`shape_keys`, `frame_start` and `frame_end`. `shape_keys` must name **all** non-Basis
keys exactly once (1–32). Optional parameters are `dry_run` (default true),
`max_samples` (default 128, maximum 256 integer frames), and
`max_interpolation_error` (default 0.001, range 0–1). No skipped-frame option is
provided. The interpolation tolerance is a scalar shape-weight error in the 0–1
range; it is not a distance, pose tolerance or artistic threshold.

The workflow is explicit:

1. Bake the source rig through `animation.bake` with the chosen full frame range.
2. Pass that returned rig and the original driven skin to
   `animation.bake_shape_keys`. Preview evaluates the complete interval before
   authoring any retained derivative.
3. Apply after inspecting the preview, then export only the returned skin and
   chosen baked rig with `include_animation=true` and the matching scene range.
4. Cold-import and compare the coupled skin/morph motion, not just action names.

Sampling happens in an owned scene with copied local rig/mesh dependencies and
remapped native drivers/constraints. The user's scene is never advanced, avoiding
dirty-value resets on unrelated light/shader RNA. Registered frame-change or
depsgraph handlers are rejected before allocation because even an owned scene
would invoke global callbacks. Sampling copies omit bone display widgets and
their materials; source widget links and animation remain intact. The target's rest hierarchy,
deform flags and integer-frame evaluated poses must match the source; the matrix
component threshold is 1e-4. Midpoint rig deviations are separately reported.
Every requested integer and midpoint is sampled; scalar midpoint error against
linear interpolation gates the bake. The result contains one independent active
layered Key action with linear keys on every integer frame. Parent inverse and
explicit Armature modifier target are retained/rebound deliberately.

The initial supported subset is local, finite, unmuted, unmasked Basis-relative
keys with values in [0,1], an unanimated mesh object, an internal source rig graph,
and a matching baked rig. Skinning must use enabled linear vertex-group deformation.
Other modifiers, envelope/mask/DQ modes, absolute or vertex-masked keys, shape-key
NLA, arbitrary Python/external driver dependencies, B-Bones, parented or
data-animated rigs, and registered frame/depsgraph handlers are
rejected. Budgets are 200k vertices, 2m key points, 32 keys, 256 bones, 2048 inspected
shape curves and 256 integer frames. The derivative starts hidden. Temporary IDs
and newly authored actions are removed on failures, including partial action work.

The pre-0.5 dependency audit also requires action and driver paths to stay within
supported local numeric channels. Source rig, baked rig and Key actions are checked
on each owner's selected slot, so legitimate unrelated slots in a shared action
remain supported. Rig/Key NLA is explicitly refused. Both driver destination paths
and SINGLE_PROP source paths are checked; an external ID hidden in a custom
property cannot extend the sampling scope. FCurve and Driver validity are checked
on the owned and evaluated copies at every sampled time, and invalid evaluated
source constraints are refused.

## Exporter changes and observed cold behavior

The bundled Blender 5.2 GLB exporter evaluates modified meshes into temporary
geometry when `export_apply=true`, which removes shape-key data. Morph scopes now
explicitly use `export_apply=false`; non-Armature modifiers anywhere in that export
scope are rejected rather than silently ignored. FBX uses the corresponding
morph-safe modifier setting. Morph metadata is recorded in the receipt.

GLB also needs `export_anim_scene_split_object=false`: splitting the rig and shape
channels into separate clips caused cold import to retain a shape action without
activating it alongside the rig. The morph scope now emits one combined scene
animation. A Blender-imported GLB may use an Empty wrapper plus the skin mesh and
importer-created bone widgets; tests verify those identities rather than confusing
helpers with additional exported assets.

FBX can represent this subset. Its bundled exporter writes relative shape deltas
and sampled `DeformPercent` curves (weight ×100); the importer converts them back
to shape weights. This conclusion is supported by actual cold playback below,
not just exporter option names.

## TDD and verification

- `scripts/test_shape_baking.py`: **11/11** real Blender tests. Preview samples the
  full interval, copied actions/keys/weights are independent, dirty animated
  constraint/light values survive, partial and completed-action failures clean
  up, and invalid key scope/modifiers/B-Bones/target motion are rejected. Public
  preview/apply reject all four frame/depsgraph handler lists without invoking
  callbacks or retaining IDs. Both source and baked armature data animation are
  rejected; temporary rigs exclude custom-shape display/material dependencies
  while preserving their original links and dirty animated values.
- `tests/test_shape_bake_schema.py`: **3/3** Python tests, including rejection before
  Blender import and dispatch only through the registered handler.
- `scripts/test_morph_handoff.py`: **1 coupled test with both formats**. An authored
  three-bone clip, continuous corrective driver and independent second morph are
  baked, rebound and exported. Independent disabled-autoexec processes verify the
  entire two-second clip at **97 integer/midpoint times**, joint identities,
  animated weights and world-space skin geometry. Missing and one-frame-offset
  morph animation are rejected by independent negative controls.

| Comparison | Observed maximum error |
|---|---:|
| Original nonlinear driver/action → linear bake, world-space surface | 0.000362579 m |
| Baked reference → cold GLB, surface | 5.45e-7 m |
| Baked reference → cold GLB, shape weights | 0 |
| Baked reference → cold FBX, surface | 7.94e-7 m |
| Baked reference → cold FBX, shape weights | 5.96e-8 |

The fixture explicitly requests scalar tolerance 0.003 and checks its separate
source-to-bake surface error below 0.0005 m. The cold-format threshold is 3e-5 m;
these are fixture engineering limits, not universal asset acceptance. Source action
curves, raw transforms/poses, key geometry/values/drivers, weights, selection and
frame remain exact. Existing five scoped-export tests and two 49-sample animation
handoff tests still pass. Ruff checks pass for the changed files.

Initial red evidence is `artifacts/shape-bake-red.log`,
`shape-bake-skinning-red.log` and `morph-handoff-red.log`; final outputs are
`artifacts/final-test_shape_baking.log` and `final-test_morph_handoff.log`.

The subsequent global-handler review reproduced **97 callback invocations** per
frame-change handler in the owned sampling scene and an unrelated light mutation.
`artifacts/shape-bake-handler-review-red.log` retains that failure and the original
display-widget dependency leak. The preflight guard and removal of cosmetic links
on sampling copies pass in `shape-bake-handler-review-green.log`; both cold formats
still pass all 97 times and negative controls in
`morph-handoff-handler-review-green.log`. This rejects unclean callback contexts;
it does not claim rollback of arbitrary third-party handlers or arbitrary RNA.

The subsequent source-scope review reproduced an active rig action changing an
unrelated object's X coordinate from **0.91 to 0.30** during a successful preview.
Both source and baked rig paths were affected, including apply. Native driver
destination/source paths could also cross the declared scope, and missing-property
or mid-clip division-by-zero drivers returned finite fallback values as success.
`scripts/test_shape_scope_review.py` adds **9 real Blender tests** covering these
failures, exact source/external-state and ID preservation, explicit rig NLA refusal,
and positive shared Object/Key slot compatibility. Red/green evidence is retained
in `artifacts/shape-scope-review-{red,green}.log`; the original 11 shape tests and
both default/high-rate coupled GLB/FBX fixtures are rerun after the fix.

## Explicit next issue: human B-Bone parity

Follow-up in 0.5: [explicit human low-cage transport](increment9-bbone-handoff.md#explicit-human-low-cage-transport-result)
now has 361-sample preparation/bake and cold-format evidence. The original finding
below explains the boundary: full Multires and corrective parity remain open.

The existing provisional human has 222 bones and 22 segmented deform B-Bones
(8 or 10 segments each), plus subdivision in its review body. It remains outside
this transform/shape-only handoff. Turning off B-Bone segments or subdivision would
change its deformation and is not a parity solution. The next engineering task is
an explicit segment-preserving target skeleton/weight conversion (or a separately
accepted vertex-cache route), measured against evaluated original geometry across
the whole clip before any native handoff claim. Remaining knee/underarm/hip defects
and artistic approval are unchanged by morph transport.
