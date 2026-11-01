# Rigging and animation workflow increment

Implemented and verified on Blender 5.2.1 LTS, 2026-10-30. These are working bounded workflow slices for FW-030–033 and FW-040–043. They do not complete character anatomy, face/hand authoring, secondary simulation, whole-motion visual review or native playback acceptance.

## Callable workflows

All entry points take a JSON-compatible `params` dictionary and optional Blender `context`. They validate parameters independently, require Object Mode/main-thread access, and reject ambiguous same-name local/linked objects. Mutations default to `dry_run=true`. Object derivatives start disabled in viewports and renders; source selection is retained.

| Function | Required arguments | Optional arguments / outcome |
|---|---|---|
| `rigging.inspect_rig` | `object_name` armature | Rest bones, parent hierarchy, deform flags, rest matrices, constraints, scale and bound meshes |
| `rigging.normalize_weights` | `object_name` mesh with one armature | `dry_run`, `protected_vertices=[]`, `max_influences=4` (1–32), `max_vertices=200000` (up to 1,000,000); creates a hidden weight derivative |
| `rigging.generate_rig` | `object_name` explicit metarig | `dry_run`; requires enabled bundled Rigify, 1–256 bones and only stock Rigify types |
| `rigging.sample_deformation` | `object_name` skinned mesh, `frame_start`, `frame_end` | `step=1`, `max_samples=128` (up to 256), `max_vertices=20000` (up to 200,000) |
| `rigging.corrective_shape` | `object_name` mesh, `name`, `offsets=[{"vertex":0,"offset":[0.1,0,0]}]` | `dry_run`, `protected_vertices=[]`; new basis-relative shape key on an independent hidden mesh |
| `animation.inspect_animation` | `object_name` | Active action/slot, layered channelbags, key counts, NLA ownership/timing and driver count |
| `animation.inspect_contacts` | `object_name` armature, `bones` (1–16 names), `frame_start`, `frame_end` | `root_bone`, `step`, `max_samples`, `ground_height=0`, `contact_tolerance=0.03`, `sliding_speed=0.05`, `penetration_tolerance=0.01` |
| `animation.bake_animation` | `object_name` armature, `frame_start`, `frame_end` | `dry_run`, `step`, `max_samples`; new rig/action with sampled object and bone transforms |
| `animation.retarget_animation` | `object_name` target armature, `source_name`, `bone_map={"SourceBone":"TargetBone"}`, `frame_start`, `frame_end` | `dry_run`, `step`, `max_samples`, `root_bone` (source root), `translation_scale=1` (0–1000); explicit local-axis retarget onto a copied target |
| `animation.cleanup_animation` | `object_name`, `frame_start`, `frame_end` | `dry_run`, `threshold=0.1`, `strength=0.5` (0–1), `max_keys=100000` (up to 1,000,000); detached duplicate action with bounded location-key spike smoothing |

Sampling explicitly includes the requested end frame. Oversized frame ranges are rejected, not silently truncated. Frame values are limited to ±1,000,000, and step to 1–1000. Sampling restores the original frame/subframe and exact raw object/pose transform channels, including rotation modes, all rotation representations, delta transforms and parent inverse. Restoration avoids matrix decomposition, including on errors.

## Preservation and interpretation

**Weights.** Only groups matching actual deform-bone names participate. Locked groups, nondeform mask groups and protected vertices retain their original weights. Remaining weight is redistributed among existing positive unlocked influences, ranked deterministically by weight/index. Locked overweight/conflicts and unweighted regions are reported unresolved; the tool does not guess anatomical influence. No source weights are changed.

**Rigify.** The metarig is copied before generation. Its target-rig, generated-UI, widget-collection and finalize-script references are cleared on the copy, preventing reuse of the source's prior outputs. Custom finalize scripts and external rig types are rejected. Generation failure removes newly created datablocks and restores selection/mode. Rigify must already be enabled; the extension does not persistently alter add-on preferences. Stock Rigify creates its normal generated UI script as part of control generation. Rig generation does not skin a mesh.

**Deformation/contact.** Samples inspect existing animation at bounded frames. Edge-length ratios compare the first sampled frame, and signed volume is only emitted for topologically closed surfaces. Evaluated meshes are always cleared. Contacts compare explicit bone heads against a configurable horizontal plane; speed and height are converted using scene unit scale and fractional FPS. Root displacement is a measurement, not an automatic root-motion acceptance. Uneven ground, actual foot soles, topology changes and motion between samples require separate review.

**Bake/retarget.** Baking samples final evaluated source object/bone matrices into independent data/action, removes derivative constraints/drivers and uses linear interpolation between keyed samples. Bendy-bone segment deformation, morph animation and nonrepresentable shear are refused or outside this transform bake. Retargeting maps rest-relative local rotations with explicit compatible bone-axis assumptions; optional root translation is scaled explicitly. Target rest matrices and starting world placement are retained. It does not infer proportions, object root motion, ground contacts or finger orientation. Sample equality does not prove interpolation or exported playback.

**Correctives/cleanup.** Corrective offsets are relative to Basis, start at value zero and cannot address protected vertices. Existing relative keys are copied independently; absolute-key sources and name collisions are refused. Cleanup modifies only the active object's action slot and only interior location keys; interval boundary keys, other slots and all rotation/scale channels remain unchanged. It averages a flagged interior key toward time-interpolated neighbors, retaining a detached fake-user action. Intentional accents may resemble spikes, so the action is never assigned automatically.

## TDD evidence

The initial seven real-Blender tests were written before the modules and failed importing the missing implementation. The first implementation exposed a real Blender API difference: pose-bone constraints support item removal but no `clear()` method. Corrected the adapter and obtained seven passing tests.

Added stock Rigify, explicit-map retarget and duplicate-action cleanup tests before those functions existed; all three initially failed. Implemented and verified the workflows. A further multi-slot regression showed cleanup incorrectly touched another owner's copied action slot (`50.0 != 100`); constrained filtering and copied-curve lookup to the active slot. Added NLA metadata, locked conflict/unweighted behavior, penetration measurement and injected Rigify generation-failure rollback checks.

**12 real Blender tests now pass**, including sampled pose equality for baked and retargeted fixtures, source action/rest/pose preservation, locked/nondeform/protected weights, independent corrective data, duplicate-action endpoints and unrelated-slot retention, stock generation with a source target-rig pointer, custom-script refusal and rollback. The synthetic test suite took approximately 0.5 seconds inside Blender; this is not a production-character performance result. Ruff lint/format checks pass.

Combined cold-export testing exposed a further preservation defect: restoring `matrix_basis` decomposed a source Euler rotation and changed its derived sine by approximately `1.49e-8`. A focused red regression compared raw channels and derived object/bone matrices exactly, including delta transforms and exception restoration. Replaced decomposition with exact channel snapshots/restoration; the regression, 12 rigging tests and seven secondary tests pass. The combined GLB/FBX handoff suite then passed both 49-sample cold comparisons with its exact comprehensive source hash unchanged. No source-hash tolerance was relaxed.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_rigging_animation.py
```

Tests use a synthetic two-bone mesh/clip in isolated factory-startup scenes. They enable Rigify only in that process and never save preferences. No Sundown scene, user live Blender session or human-reference asset was modified. Full human deformation renders, face/hand presets, secondary motion, motion-capture corpus, cold export of these new workflows and native Unreal animation remain outstanding acceptance gates.

## Reference basis

Consulted bundled official Blender 5.2 API/manual entries for layered Action slots/channelbags, NLA baking, Rigify stock generation and custom finalize hooks. Installed source confirmed bundled `rigify` and the properties cleared before generation. See [Action keyframe strips](https://docs.blender.org/api/5.2/bpy.types.ActionKeyframeStrip.html), [NLA operators](https://docs.blender.org/api/5.2/bpy.ops.nla.html), [Rigify basics](https://docs.blender.org/manual/en/5.2/addons/rigging/rigify/basics.html) and [Rigify introduction](https://docs.blender.org/manual/en/5.2/addons/rigging/rigify/introduction.html).
