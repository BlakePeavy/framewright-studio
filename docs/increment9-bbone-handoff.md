# B-Bone endpoint transport and fractional export sampling — 2026-10-30

This 0.5 development increment adds `animation.bake_bbone_skin` and explicit
`asset.export` animation substeps. It creates a separate export skeleton and skin;
it does not replace the animator rig, lower original B-Bone segment counts, or
claim general human/corrective/native-engine parity.

## Bounded endpoint bake

Blender's [official B-Bone matrix example](https://github.com/blender/blender/blob/main/doc/python_api/examples/bpy.types.PoseBone.bbone_segment_matrix.0.py)
and [linear deformation implementation](https://github.com/blender/blender/blob/main/source/blender/blenkernel/intern/armature_deform.cc)
describe the adjacent endpoint interpolation used here. An N-segment B-Bone becomes
N+1 ordinary endpoint joints. Its original vertex weight is split using Blender's
rest segment index/blend. Each endpoint's animated transform reproduces the
original pose/rest segment matrix relationship. Ordinary deform-bone influences
are retained. Original rigs, data, actions, weights and segment counts remain intact.

Required command parameters are `object_name`, `armature_name`, `frame_start`,
`frame_end`, and `max_surface_error_m` (1e-7–1 meter). The tolerance is an explicit
engineering surface-distance limit, converted using the scene's unit scale, not an
artistic threshold. `dry_run` defaults true. Budgets are:

| Parameter | Default | Allowed range |
|---|---:|---:|
| `max_key_times` | 257 | 1–1025 |
| `max_samples` | 1025 | 1–4097 |
| `max_vertex_samples` | 10,000,000 | 1–100,000,000 |
| `max_joints` | 512 | 1–1024 |
| `max_influences` | 8 | 1–32 |
| `max_refinement_depth` | 4 | 0–6 |

Additional fixed limits are 200k mesh vertices, 2048 source rig bones, 128 MiB of
cached source coordinates and 262,144 cumulative joint/key-time authoring samples.
Deform weights on the derivative normalize each positive source deform total to
match Blender's unmasked linear skinning. Zero-total vertices remain unweighted;
nondeform groups stay exact. The receipt reports source totals and resulting maximum
influences. Exceeding the influence budget refuses the bake; weights are never pruned.

Apply restores the original polygon material indices, data material slots and
effective OBJECT slot overrides after geometry-only sampling. A regression caught
Blender resetting face indices when temporary material slots were cleared; the
fix restores these only on the derivative and keeps the source unchanged.

The complete integer interval seeds the action. Every interval's endpoints,
quarters, midpoint and three-quarter time are compared using evaluated source and
candidate skin geometry. Failed intervals insert midpoint keys, within explicit
budgets. Linear location/scale keys and hemisphere-consistent quaternion keys are
authored on a new action. Receipts include key/check times, worst vertex/time/error,
TRS residual, work consumption, endpoint mapping and a recommended export substep
rate. These sampled checks cannot bound arbitrary extrema between tested times.

Evaluation uses local copies in a separate scene. Explicit Object/Edit Mode context
overrides avoid switching or advancing the source scene, which otherwise reset
dirty animated B-Bone values. Display widgets/materials are excluded from the
sampling dependency graph. Preview removes its temporary IDs; apply retains only a
hidden independent rig, mesh and action after the surface gate. Failure cleanup is
tested after action creation and on budget exhaustion.

First scope rejects DQ/preserve-volume, envelopes, masked or disabled skinning,
other modifiers, non-Basis shape keys, animated rig data, NLA, rig parenting,
external constraints/drivers, invalid drivers/constraints, nonrepresentable shear,
registered global frame/depsgraph handlers and changing rest segment maps. Native
driver source paths must stay within the supported local numeric-channel grammar;
an ID pointer hidden inside a custom property cannot extend the dependency scope.
Both FCurve and Driver validity are checked during sampling. Source mesh binding
transforms, parent inverse, unparented sources and scene units have actual fixtures.

## Explicit fractional export rate

`asset.export` now accepts `animation_substeps` (integer 1–64, default 1) and
`max_animation_samples` (1–65536, default 16384). Substeps above one require
`include_animation=true`. The full range must fit the sample budget and a fixed
2,000,000 object/bone/shape channel-sample work ceiling. Scaled frames and FPS must
fit Blender's actual RNA bounds.

For higher rates, only staged copied actions are retimed: key and handle X
coordinates, explicit action ranges, scene frame range/current time and FPS scale
together. FPS base and physical duration stay unchanged. Object, bone and shape
actions use the same clock. Export retains its existing integer sampler on that
denser owned clock; neither source actions nor the user's FPS/frame are edited.
Default substeps=1 retains the prior sampling rate. Registered frame/depsgraph
callbacks are now refused for all scoped exports before staging to prevent global
callbacks from changing source data.

Raw skin bound to segmented deform B-Bones is now refused for both static and
animated GLB/FBX export. A direct cold probe lost about **0.406 m** even at four
substeps, so a higher export rate alone cannot replace the explicit endpoint bake.
Original segment counts are retained. Active action paths are also checked for
external-ID traversal before staging at both default and higher rates. Validation
uses each object/data/Key owner's selected action slot (and NLA strip slot), so
legitimate shared actions do not resolve another owner's channels on the wrong ID.
See the [independent animation review](increment11-animation-review.md) for source
mutation regressions, selected-slot coverage and refusal checks.

The higher-rate subset refuses NLA, multiple action layers/strips, sampled FCurves,
FCurve modifiers, scene time remapping, and key interpolation outside Constant,
Linear and Bezier. Action copies and partial output are removed on failure.
Export receipts report both source/staged timing and work bounds. A receipt does
not substitute for full cold-import geometry comparison.

## Measured evidence

The deliberately incorrect rigid-motion prototype missed authored B-Bone curvature
by about 0.43 m. Correct endpoint transforms matched 8-segment straight and
10-segment curved-rest fixtures within 7.96e-7 m across 33 integer/midpoint samples.
The runtime fixture uses a transformed rig, multiple deform influences with source
weight totals of 0.6, and an independent protected vertex group.

| Comparison | Maximum observed error |
|---|---:|
| Source → adaptive endpoint bake, requested 0.5 mm | 0.308 mm |
| Baked reference → cold GLB at default whole-frame export, failing control | 3.414 mm |
| Baked reference → cold FBX at default whole-frame export, failing control | 3.415 mm |
| Baked reference → cold GLB at substeps=4 | 1.85 micrometers |
| Baked reference → cold FBX at substeps=4 | 1.91 micrometers |

The endpoint cold check covers 129 times across the whole clip and verifies its
physical duration and joint identities. Removing an endpoint influence produces
about 70 mm error; offsetting the action produces about 189 mm, so both independent
negative controls fail clearly. The separate coupled morph/skin fixture still
passes both formats at substeps=4 across 97 times, with missing/offset-morph
controls. Its cold error is below 0.81 micrometers. Imported FPS is used when
verifying the same physical two-second duration; FBX preserves the staged rate.

Current evidence is in `artifacts/bbone-probe/`: `red.log`, `runtime-red.log`,
`cold-red.log`, `export-substeps-red.log`, `runtime-green.log`,
`export-substeps-green.log` and `review-green.log`. Research stress controls expose
unsupported DQ (25.7 mm), morph-dependent segment mapping (99.2 mm) and shear
(11.9 mm); these are limits, not accepted approximations.

The human contains 35 deform bones, including 22 segmented bones; endpoint
replacement would produce 243 joints. Its displayed baseline also has Multires,
and its corrective body has driven keys. Only a separately named, explicitly
prepared low-cage baseline can enter this first scope. Human preparation and
acceptance remain recorded separately; no complete human handoff is inferred from
the small fixture. Original Multires, corrective drivers and segment counts must
remain available for later parity work.

## Explicit human low-cage transport result

The retained provisional baseline passed a separate geometric transport pilot in
`artifacts/bbone-probe/20261030T193829Z-human-ad7f6875/` with detailed results under
`verification-20261030T194834Z-20d2e896/verification.json`.

Preparation made a separate low-cage mesh containing only its Armature stage; the
original Multires body and corrective body remain intact. A separate rig/data copy
froze only Rigify rest-ease SUM drivers whose exact `rubber_tweak` inputs were
verified unanimated and undriven. The original drivers were retained. This was an
explicit pilot preparation, not a relaxation of the public command's rig-data
animation refusal.

Across all **361** requested adaptive validation times, original low-cage and
prepared low-cage geometry matched exactly (maximum error **0**). The 243-joint
endpoint bake differed by at most **0.9518 mm**, within its explicitly requested
1 mm tolerance. It uses up to **9 influences per vertex**, with no pruning; this is
not a claim that a target engine accepts that influence budget.

Both cold formats were then compared against the baked geometry at the same 361
times using explicit `animation_substeps=16`: GLB maximum error **1.01 micrometers**,
FBX **0.534 micrometers**. Joint identities and the physical 19/24-second interval
were checked. Input files' hashes remained unchanged. The preparation and bake
errors are separate from these cold-format errors. No full Multires/corrective,
rendered appearance, native engine or artistic acceptance is claimed.
