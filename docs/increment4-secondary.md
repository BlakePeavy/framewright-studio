# Secondary bindings and authored pose controls

Implemented on 2026-10-30 as working FW-033 adapters. These operate on explicit existing bones, groups and shape keys; they do not infer eye anatomy, a hand grip, facial expressions or simulation acceptance.

## Functions and contracts

| Function | Parameters | Result |
|---|---|---|
| `inspect_bindings` | `object_names`: 1–64 unique exact scene names | Actual parents/bone parents, armature modifiers, weighted groups/locks, shape controls and simulation modifiers |
| `attach_rigid` | `object_name` mesh, `armature_name`, `bone`, optional `dry_run=true` | Independent hidden mesh parented to the named bone, retaining current world placement |
| `create_cloth_proxy` | `object_name`, `pin_group`, optional `dry_run=true`, `collider_names=[]` (up to 8), `frame_start=1`, `frame_end=250`, `quality=5`, `collision_distance=0.015`, `self_collision=false` | Independent cloth and collider meshes with real Cloth/Collision modifiers and bounded point-cache settings |
| `capture_pose` | `object_name` armature, `bones`: 1–128 existing control names | A versioned JSON pose containing the selected controls' basis matrices |
| `apply_pose` | `object_name` target armature, captured `pose`, explicit `bone_map`, optional `dry_run=true`, `bound_mesh_names=[]` (up to 32) | Duplicate control rig and optional separately copied/rebound skins |
| `apply_shape_values` | `object_name` mesh, `values` mapping existing shape-key names to values, optional `dry_run=true`, `protected_keys=[]` | Independent static expression derivative with protected keys retained |

Every function validates independently, requires main-thread/Object Mode access and rejects missing or ambiguous object identities. Mutations preserve source data and start hidden. The public dispatcher names are registered separately; these are the module-level function contracts.

Rigid attachment refuses already skinned, animated or constrained sources to avoid double deformation. It can use a current parented mesh's world placement without changing that source parent. Cloth setup requires an existing positively weighted pin group, permits at most 200,000 source vertices, and refuses an existing Cloth/Soft Body stack. Quality is 1–20; cache frames are 1–1,000,000; collision distance is 0.0001–1 Blender units. Existing armature modifiers and all vertex weights are copied unchanged. Disk caching is disabled. The proxy and collider derivatives must be revealed together before simulation review; creation does not evaluate or bake cloth.

Pose application accepts bounded affine matrices with representable translation/rotation/scale. It detaches copied action/NLA ownership while retaining rig constraints/drivers, remapping self object/data targets, IK pole targets and Armature-constraint target collections to the derivative. Explicit bound mesh copies point to that new rig. External dependencies remain external and are not automatically rewritten. Failure rolls back newly created rig/skin data.

Shape-value application supports existing relative keys only, refuses Basis/protected/missing keys and enforces authored slider ranges. It clears shape-key animation only on the new static derivative, keeps other captured key values, and verifies independent shape-key storage. It does not create a blink/gaze preset by guessing anatomy.

## Verification

Wrote the six initial Blender tests before the module; the first run failed importing missing `secondary_motion`. Implemented the workflows and obtained six passing tests. Expanded coverage to internal constraint/driver target remapping and injected multi-object pose failure rollback. **Seven real Blender 5.2.1 LTS tests now pass**; Ruff lint and formatting also pass.

Fixtures prove that a separate authored eye/accessory retains its initial placement and follows the named animated bone; cloth pin weights/source modifier stacks remain unchanged; generated proxy/colliders carry real simulation modifiers; pose copies own their rig/skin references; shape values remain isolated and protected; invalid input creates no objects; and partial creation is rolled back. No costly cloth simulation or visual acceptance is claimed.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_secondary_motion.py
```

## Human pilot intake

Read the selected official reference collection from the independent review kit and saved a separate editable intake at `artifacts/secondary-pilot/human-intake/human-binding-intake.blend`. `readiness.json` records the source SHA256 and verifies that it stayed unchanged. The selected collection has three mesh objects: the 10,582-vertex realistic body and two 546-vertex eyes. Actual inspection found **no armature, vertex groups or shape keys**. The body retains its Multires modifier and source transform; eyes retain their original body parenting.

An anatomical fit needs either an authored metarig for this rest pose or explicit pelvis/spine/neck/head and bilateral shoulder/elbow/wrist/hip/knee/ankle/toe landmark coordinates. Hand/eye/face workflows need named authored controls or relative expression keys. These are exact missing source inputs, not an inferred artist approval requirement. The intake does not fit a default rig from a bounding box or pretend an unfitted rig proves deformation quality. Neutral reference renders and the original provenance/license evidence remain in the independent review kit. Full posed human renders and anatomical/physics/native playback acceptance remain outstanding.
