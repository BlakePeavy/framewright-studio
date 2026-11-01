# Continuous corrective activation — 2026-10-30

`rig.activate_corrective` creates a hidden, independent mesh/key-data derivative
with a native joint-angle driver on an **existing authored corrective**. It does
not generate anatomical shapes or approve deformation quality. Preview is the
default. This is 0.3 development after the verified 0.2 checkpoint.

```json
{
  "schema_version": "1.0",
  "request_id": "left-knee-preview",
  "command": "rig.activate_corrective",
  "params": {
    "object_name": "BodyWithAuthoredCorrective",
    "shape_key": "KneeCorrective.L",
    "armature_name": "CharacterRig",
    "proximal_bone": "ORG-thigh.L",
    "joint_bone": "ORG-shin.L",
    "distal_bone": "ORG-foot.L",
    "onset_degrees": 20,
    "full_degrees": 110,
    "dry_run": true
  }
}
```

Set `dry_run` to false only when an owned derivative is wanted. All identities
are exact names in the active scene/view layer; all three named bones must exist
and have distinct heads at the two segments. No anatomical name mapping occurs.
The measured points are the **world-space heads** of the named proximal, middle,
and distal bones. Zero degrees means straight at the middle joint. There is no
inferred rest-pose offset. The unsigned bend cannot distinguish forward/backward
flexion or axial twist; nonuniform world scaling can alter the measured angle.

With `t = clamp((angle - onset) / (full - onset), 0, 1)`, activation is
`(1 - cos(pi*t)) / 2`. The half-cosine is continuous with zero slope at its two
activation boundaries. Bounds require `0 <= onset < full <= 170`; defaults are
20 and 110 degrees. Three native LOC_DIFF variables and a fixed simple expression
perform evaluation without Python auto-execution or a user-supplied expression.
Collapsed segments at or below 1e-8 Blender units, nonfinite distances, and
distances at or above 1e20 produce zero activation instead of an invented angle.

The target must be an unmuted Basis-relative key supporting values 0–1, without
an existing driver or animation channel. Other key geometry, weights, supported
drivers and active layered animation are copied; the copied action is independent
and copied self-driver targets are remapped to the derivative. The original keys,
actions, driver relationships, transforms, selection, visibility and dirty
character-channel values are retained. Failure removes the owned derivative and
actions, including failures while restoring context.

The bounded implementation accepts local mesh/rig data, exactly the named armature
modifier and optional Subsurf/Multires. Mesh object/data animation, mesh constraints,
shape-key NLA, external rig targets, parented rigs and arbitrary scripted drivers
are rejected before copying. Existing internal rig drivers may use native
aggregation and polynomial generators of degree at most 10, as stock Rigify does.
Limits are 200k base vertices, 128 keys, 2m key points and 2048 curves per inspected
animation owner. Drivers are evaluated when their mesh/rig dependencies are enabled;
the resulting mesh starts hidden to avoid overlapping the retained source.

## TDD and real Blender evidence

`scripts/test_pose_correctives.py`: **11/11** tests passed on Blender 5.2.1 LTS.
The initial missing-module red is retained at
`artifacts/knee-refinement/public-corrective-red.log`. Subsequent genuine red
regressions exposed a denominator clamp activating a tiny straight joint, missed
IK pole dependencies, stock Rigify native SUM/polynomial compatibility, and an
owned-data leak when context restoration raised. The corrected tests pass; final
output is `public-corrective-green.log` in the same folder.

The tests include real evaluated geometry at 13 increasing/reversing angles,
collapsed segments, very small valid world distances, preview through public
dispatch, independent layered actions and self-driver remapping, exact source
state, rejection before allocation, two rollback paths, and exact geometry after
an independent factory-startup cold reopen with auto-execution disabled.
The earlier pilot helper has a separate **4/4** test suite in
`scripts/test_knee_corrective_activation.py` covering 19 angles and cold reopening.

## Human pilot: activation verified, knee shape still provisional

Selected continuous-activation evidence is under
`artifacts/knee-refinement/20261030T175350Z-d566f95d/`:

- `continuous-knee-candidate.blend`, `report.json`, `cold-verification.json`.
- Ten actual 512px CPU Cycles PNGs compare baseline/activation at 60°, 90°, 110°,
  130°, and left-110°/right-neutral; all pass subject-coverage checks.
- 39 fractional, reversing and asymmetric samples reproduced exactly in a cold
  process with auto-execution disabled. Maximum activation error was 2.38e-7;
  outside-patch displacement was zero. All 20,889 protected key-vertex comparisons,
  original weights and source hashes were preserved. Forced cross-side activation
  was rejected by the negative control.
- `public-api-candidate.blend` and `public-command-verification.json` independently
  exercise the public command against the actual stock Rigify pilot. Preparation
  clears experimental drivers only on a new owned copy; the API itself refuses
  replacement. Both left/right commands reproduce all 39 measurements exactly,
  including a second disabled-autoexec cold process. Original pilot key coordinates,
  values and driver identities plus input-file hashes remain unchanged.

The retained corrective shapes make only a modest measured change. Actual 110°
before/after images look nearly unchanged; a conspicuous knee crease remains and
deepens at 130°. Earlier DQ and Corrective Smooth alternatives in
`artifacts/knee-refinement/20261030T174604Z-9c2efd43/` were rendered and inspected;
they accentuated the fissure/dimple or changed volume elsewhere and were not
selected as a global improvement. The first continuous candidate
`20261030T175245Z-836faa4f` used the corrected mesh's tessellation for baseline
metrics and is superseded by the selected run, which measures each independently.

This increment verifies activation engineering, preservation and repeatability.
It does **not** resolve the knee crease, underarm/hip compression, remaining
intersections, production pose coverage, native morph export or artist approval.
Earlier shoulder/elbow/hip evidence remains in
[the binding/refinement record](increment6-rig-binding.md).
