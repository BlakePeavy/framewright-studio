# Explicit landmark metarig fitting

`rig_fit.fit_metarig(params)` implements the reusable `rig.fit_metarig` operation. It consumes authored landmarks and never infers body proportions from a bounding box or assigns anatomical meaning to vertex positions.

Required arguments are `object_name` (an existing stock Rigify metarig), `landmarks` mapping names to three coordinates, and `bone_map` mapping existing bone names to `{"head":"landmark_name","tail":"landmark_name"}`. A mapping may include an explicit `roll` in radians. Optional arguments are `dry_run=true`, `units="meters"` (`centimeters` and `blender_units` also supported), `coordinate_space="world"` (`armature_local` also supported), and `protected_bones=[]`.

World points are converted using the scene's unit scale and the metarig's inverse world transform. Armature-local values use the same declared unit conversion before any object transform; non-unit object scale therefore remains meaningful. Bounds are 512 bones/mappings, 1,024 landmarks, 512 protected names, converted coordinates within ±1,000,000 units and explicit roll within ±2π. Rigify must already be enabled and the source must contain stock Rigify types; no external feature types are invoked.

Preview returns planned local endpoints, explicitly fitted bones, preserved unmapped bones and any numerical connected-endpoint snapping. Connected parent tails and child heads must agree within `1e-6` armature-local units. Inconsistency requires explicit additional landmarks; the tool does not reposition an unmapped child anatomically. Numerical snapping is reported and validated again for zero-length collapse. Explicit protected bones cannot move or receive a roll edit. Unmapped hand/face controls remain at their authored positions unless explicitly mapped; anatomical names are not guessed.

Apply creates a separate hidden metarig and clears only its copied animation and previous Rigify target/UI/widget/finalize references. The source is never put into Edit Mode. Existing hierarchy, connection flags and authored rolls are retained unless a mapped roll is explicitly supplied. Failed edits remove the new derivative and restore Object Mode, selection and active object. The fitted result can then use the separate stock generation adapter; fitting does not skin a body or pass deformation review.

## Verification

Five real Blender 5.2.1 tests were written before implementation; the first run failed importing the missing module. Implemented and verified:

- World-space centimeter landmarks on a translated/rotated source, preserving exact source channels/rest matrices/action identity.
- Connected-chain validity, source selection and hidden independent output.
- Zero-length and mismatched connection rejection before creating data.
- Protected/unmapped control endpoints and injected failure rollback.
- The installed bundled **Basic Human** metarig, explicitly mapped from its authored rest endpoints, still generates successfully through stock Rigify.

A follow-up regression showed that a tiny valid proposed segment could collapse after numerical connection snapping. It first failed with “ValueError not raised”; a post-normalization length guard now rejects that case before mutation. **Five fixture tests pass**, and Ruff lint/format checks pass.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_rig_fit.py
```

The Basic Human test proves adapter compatibility, not an anatomical fit to the independent realistic body reference. That source still needs its own authored landmark/metarig input and reviewed posed renders. No default rig was fitted to it by guessing proportions, and no game asset was modified.

Follow-up, 2026-10-30: [the later human binding pilot](increment6-rig-binding.md) supplies explicit authored landmarks, a fitted/heat-bound derivative and actual joint renders. It remains provisional: inspected shoulder/hip/knee defects require correction. The paragraph above records the original adapter-only test scope, not the current pilot's existence or acceptance.
