# Blender knee: connected contact diagnosis

Subsequent work: [fresh calibration and local correction](blender-knee-local-correction.md).

The [receipt](../artifacts/verification/blender-knee-contact-anchors-20261101.json)
records nine focused tests and a concrete continuation from the
[guarded solve](blender-knee-guarded-solve.md). No corrected character or public
plug-in behavior is accepted.

## Exact constraints and attempted corrections

All 517,335 saved inequalities were reconstructed bit-for-bit. Their compressed
index now preserves every pose, triangle pair, vertex pair, axis and fold identity.
The original witness is 96.2% concentrated in one triangle pair at time117, yet
that pair is feasible alone. Removing fold tangents still leaves a checked conflict.

Updating separating planes retained all pairs, fold rows, the ±2.5mm coordinate
box and 8µm clearance. A fixed-row admission error in the first attempt was fixed
with two targeted tests; all six corrected plane-revision passes still produced
checked conflicts. The failed first attempt is retained. No threshold was relaxed.

Continuous pose corrections then used convex smoothstep weights from actual knee
angles. Four focused tests cover the calibrated bounds, C1 transitions and the
equivalence to a shared correction when all anchors agree. Both the three-anchor
and eleven-anchor systems have checked conflicts. Some independent seed solves
hit their iteration limits; those limits are not infeasibility proofs.

## Dominant connected patch

The eleven-anchor witness concentrates about99.45% of its weight at times9.5
and122, both approximately105degrees. Its dominant rows38538/311814 constrain
the same vertex pair15100/40750 along almost opposite axes (dot≈-0.999999991).
Triangles35099 and35797 share vertex15100 and meet triangle35974.

The [source audit](../artifacts/blender-knee-contact-anchors-20261101/anchors/opposed-contact-audit.json)
measures at most3.983µm difference in those source vertices. Baseline allowed
contact identities swap between the poses. The relation classifier reports
proximity/crossing in one and touch/touch in the other; the legacy classifier
contributes to the allowed-identity sets. This evidence does not establish a
classifier bug or make new intersections acceptable.

Next: inspect and repair or consistently constrain this connected patch across
both poses. Avoid separate opposing per-triangle decisions and reuse the saved
maps/row identities. Do not add more anchors blindly. A revised passing solve
still requires actual Blender geometry, full73 contact/stretch/protected checks,
fresh influence coverage, cold reopening, matched visual review and public tools.

## Preservation and verification limits

All six owned numeric workers exited; the expected first-attempt failure is
recorded. Input/source hashes, character assets, runtime code, sealed releases
and Git state remain unchanged. No new Blender capture, full suite, bake, render,
Unreal process or Sundown write ran. Current authored helpers pass focused lint;
the immutable executed trace harness retains three unused-name findings and is
research evidence, not installable runtime. Large matrices and complete execution
files stay in the task workspace at paths pinned by the receipt.
