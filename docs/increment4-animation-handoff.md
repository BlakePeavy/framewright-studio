# Coupled animation handoff verification

This increment tests the actual sequence from explicit retargeting through constraint baking, derivative skin binding, GLB/FBX export and fresh-process reimport. It extends FW-040/FW-070 software evidence; it is not an animation-quality or native Unreal acceptance result.

## Fixture and checks

`scripts/test_animation_handoff.py` builds a three-bone source and a target with different rest lengths and orientations. The source animates root translation and rotations on all three bones over frames 1–25 at 24 fps. An explicit bone map and root translation scale of 1.3 drive the copied target. A 28-vertex asymmetric skin has mixed joint weights, an explicit UV atlas and two Principled materials.

The workflow checks the following together:

1. Retargeted local rotations and scaled root translation match every source frame, while the target retains its own rest skeleton and world placement.
2. An added local rotation constraint changes the derivative skin measurably. The bake creates another independent rig/action, removes constraints and reproduces the constrained skin, joint positions and world skinning matrices at all 25 keyed frames.
3. A separate mesh/data copy is explicitly parented and rebound to the baked rig. A deliberately stale source-armature modifier is refused by the export scope check. Skin copying here is fixture orchestration, not a new automatic anatomical binding API.
4. Only the baked rig and its copied skin are exported. Each format is imported in its own factory-startup Blender process with temporary configuration, scripts, extension and data directories.
5. The one-second imported clip matches 49 normalized-time samples, covering every frame and half frame. Checks include joint hierarchy/origins, world skinning matrices, deformed bounds, a bidirectional KD-tree vertex-cloud distance and world-position/UV/material corner associations. Seams, triangulation and vertex reordering do not require source vertex indices to survive.
6. SHA-256 comparison covers the original source/target rigs and mesh, object transform channels, rest/pose matrices, real action curves/key handles/interpolation, mesh geometry, weights, UVs, material values and modifier targets. Scene, active object, selection and fractional frame are also retained.

Deliberate interior-sample corruption controls alter motion, a joint, a skinning matrix, a UV or a material. Each must fail the parity checker even when clip endpoints remain intact. An additional assertion proves the exported fixture actually moves by more than 10 cm.

## TDD finding and measured results

The first coupled test passed both cold exports but failed exact source preservation. Restoring `matrix_basis` in the shared rigging time guard decomposed the unanimated target's Euler rotation and changed a matrix coefficient from `0.14943814277648926` to `0.14943812787532806`. The change was small, but contradicted source preservation. The rigging adapter now snapshots/restores the exact transform channels, rotation modes, delta transforms and parent inverse instead of decomposing a matrix. A separate focused test covers normal and injected-error restoration.

After the fix, both integration tests pass, including exact original-source hashes and context equality. The unchanged source SHA-256 is `632e5c4075c3483d633696da539b7bfe8b4f272e8ef3265e8180e2621b698c36`. The suite took approximately 4.8 seconds within Blender, including the two independent import processes. Ruff lint and format checks pass. Measured 49-sample comparisons on Blender 5.2.1 LTS (`9e2066aef7ef`) on 2026-10-30:

| Format | Maximum world vertex error | Maximum joint error | Maximum bounds error | Maximum world skin-matrix coefficient error | Maximum UV error |
|---|---:|---:|---:|---:|---:|
| GLB | 0.000000756 m | 0.000000619 m | 0.000000622 m | 0.000000790 | 0.000000030 |
| FBX | 0.000001263 m | 0.000000536 m | 0.000001228 m | 0.000000991 | 0 |

The fixture acceptance threshold is 0.0003 m for world distances and 0.0003 for dimensionless matrix/UV comparisons. This is a test tolerance, not a general production asset budget. Half-frame parity compares the exported result with the baked Blender motion; it does not claim that a sampled bake exactly reproduces every intervening time of its original constrained source.

Run the focused suite:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_animation_handoff.py
```

Temporary exports and preferences are removed after testing. No live Blender scene, editor preferences, Sundown files or native engine state are accessed.

## Flexible 8K configuration

The 13-test production-assets suite was rerun successfully. Its real Blender tests verify an `8192` review-scene request in both dry-run and committed modes, with separate scene/geometry, AgX, named cameras and three lights. The dry run creates no datablocks; constructing the 8192 scene allocates no textures. Requests above the current 8192 limit are refused. This verifies output settings and isolation, not an 8K finished render or visual quality. The persistent review kit contains actual smaller renders for inspection.

## Limits and next acceptance gates

This synthetic three-bone fixture has compatible local-axis conventions, no morph animation, no fingers/face, no NLA blend stack, no changing topology and no external constraints after baking. It is not a motion-capture corpus or a proof of arbitrary retarget compatibility. Real character anatomy, deformation and contact approval, longer clips, engine-native animation import/playback and measured runtime budgets remain separate review gates. AAA quality and the usefulness of 8K depend on the artwork, materials, lighting, camera coverage and target platform; neither these numerical checks nor output resolution certifies them.
