# Blender knee: wider response calibration

The [receipt](../artifacts/verification/blender-knee-wide-response-20261101.json)
records the Blender-only follow-up to the [initial all-state refusal](blender-knee-composition.md).
All 25 problem poses now pass sampled prediction controls over ±2.5 mm per rest
coordinate, compared with the earlier ±0.4 mm. The accuracy limit remains 1 µm.
Maximum measured base error is 0.7431 µm; composed-surface error is 0.4404 µm.

## What changed

Subdivision weights are measured from actual single-vertex posed movement. This
avoids amplifying tiny finite-difference errors. A wider linear skin model fails
the deepest bend; quadratic models at 2.5/2.1 mm also fail its accuracy check.
Those results are retained. A 26-probe cubic model passes. The return-motion pose
reuses its already-passing quadratic model through verified zero-padding.

All models use the same measured subdivision weights. Nine mixed controls per
accepted pose check the actual Blender base and composed surfaces. Exterior
movement is exactly zero; source fingerprints, owned inventories and dependency
pins remain unchanged. Five workers used 1,802 captures and 471.4 seconds total.
Twelve focused numerical tests pass. No full suite, bake or render ran.

The [subsequent guarded solve](blender-knee-guarded-solve.md) reuses these maps
and identifies a joint conflict. Its retained witness guides the next correction.

## Clearance and next work

A conservative bound accounts for nonlinear displacement in contact inequalities.
With the unchanged 8 µm clearance, the two previously impossible rows at time 117
are individually achievable in the wider box. The maximum nonlinear guard for
that pair is about 0.0102 µm. This does not prove joint or all-state feasibility.

The [prepared solve plan](../artifacts/blender-knee-wide-response-20261101/wide-solve-plan.json)
pins all 25 maps. Next: combine the guarded constraints, include nonlinear motion
in whole-human contact coverage, and evaluate folds/contacts on polynomial
positions. Reuse the measurements; stored linear Jacobians alone are insufficient.
Then verify an actual Blender candidate through full73 geometry/contact/stretch/
protected checks, fresh influence coverage, cold reopening, matched visual review
and public implementation. These sampled models do not certify every point in
the box or grant artistic acceptance.

No character, public plug-in feature or release was promoted. No Unreal process
or Sundown write occurred. The [research handoff](../artifacts/blender-knee-wide-response-20261101/README.md)
and receipt preserve exact data locations; large measurement files remain outside
the plug-in and install ZIP.
