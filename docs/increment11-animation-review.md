# Independent B-Bone and export sampling review — 2026-10-30

The new independent suites use real Blender fixtures and exercise source
preservation, dependency admission and fractional-time staging. Runtime fixes
were made by the implementation owner after reproducible failures were reported;
the review added tests without editing the runtime modules.

## Confirmed failures and corrections

1. **Invalid B-Bone drivers produced success evidence.** A native simple-expression
   driver targeting a missing property returned finite fallback geometry and a
   successful bake preview. A second driver began valid, divided by zero at frame
   two, and still passed a 1 cm sampled surface tolerance when its fallback was
   stable. Both `FCurve.is_valid` and `Driver.is_valid` now participate in admission
   and sampled evaluation. Geometric closeness cannot substitute for a valid
   evaluated driver. These two tests failed before the correction and now pass.
2. **A valid driver could traverse an external ID through a custom property.**
   `target.id` was the selected rig, but the path
   `["external_owner"]["gain"]` reached an unselected Empty. Blender resolved the
   path and considered the driver valid; the copied rig retained that external
   pointer. B-Bone animation/driver paths now use the local numeric-path grammar.
   This refusal test failed before the correction and now passes. A companion
   test verifies that action paths cannot write through the same boundary.
3. **Actual export changed an unselected source object.** An object's action
   curve used `["external_owner"].location`, reaching an unselected Empty through
   a custom-property ID pointer. Actual GLB export at both ordinary and fourfold
   sampling succeeded while changing that original object's dirty X coordinate
   from approximately **0.910000026 to 0.200000003**. Public export now validates
   active object/data/key and applicable NLA action paths before staging. Both
   rates reject the fixture before allocation or file publication and preserve
   the external value.
4. **Initial path hardening resolved unrelated slots against the wrong owner.**
   Valid shared Object actions with owner-specific custom properties, and shared
   Mesh/Key actions, were rejected because every channelbag was resolved on every
   owner. Export and B-Bone path validation now uses the owner's selected action
   slot. The positive shared-slot cases were red during hardening and are green
   after the correction; the cross-ID refusals remain green.

## Passing boundaries

`scripts/test_bbone_review.py`: **six tests pass**. The tests preserve exact
source rig/skin state and datablock inventories around failure and successful
preview. Intentional division-by-zero diagnostics in Blender's output are
negative-control evidence, not successful motion samples.

The sixth test independently verifies that both GLB and FBX refuse raw bound
segmented B-Bone skins, for static and animated requests, before source changes,
retained allocations or files. The implementation owner's separate cold test
reported approximately 0.406 m of lost deformation before that guard; this review
verifies the refusal and does not present that separate measurement as its own.

`scripts/test_export_sampling_review.py`: **six tests pass**. They additionally
verify:

- Negative and fractional effective time, asymmetric free Bezier handles,
  shared action slots, shared source mesh data, and independent copied object,
  Mesh and shape-key actions. Curve values at nine times agree after fourfold
  retiming; the scene's effective FPS preserves physical duration.
- Three repeated staging operations retain original action/slot identities,
  keys and handles, source time, shared-data relationships and allocation counts.
- A 13-sample public preview reports 13; a 12-sample admission bound refuses the
  actual operation before files or retained allocations.
- Each of the four global frame/dependency-graph handler lists is rejected by
  actual public export before a registered callback can change an unrelated
  light from 123 to 999. The light remains 123, no callback runs, and no output
  is published. This verifies the existing public guard; private staging helpers
  are not advertised as an independently guarded public API.

Blender may represent negative fractional time with a negative `frame_subframe`;
the test compares effective time and restores the actual original representation
instead of assuming a particular integer/subframe decomposition. Ruff checks pass
for both new suites. Tests run with factory startup, offline mode and automatic
script execution disabled.

These checks complement the implementation owner's endpoint-skin conversion,
DQ/shear/morph refusal, budget, failure-cleanup and cold GLB/FBX parity suites.
They do not add artist acceptance, continuous-motion error guarantees, arbitrary
dependency support or native-engine verification. No game project was opened or
modified.
