# Blender knee: calibrated local correction

Subsequent work: [retain meaningful correction](blender-knee-benefit-repair.md).

The [verification receipt](../artifacts/verification/blender-knee-local-correction-20261101.json)
records eight focused tests and a fresh two-pose Blender calibration. The
correction remains rejected; no public tool or character asset was promoted.

## Calibration and coverage

Renormalizing the previous fit failed at 3 mm. A fresh fit now passes the unchanged
1 micrometer limit at poses 9.5 and 122: maximum independent base/high errors are
0.5257/0.3178 micrometers. The worker used 52 fresh fit probes and reused 18
independent captures with identical cold centers. All 66 new captures preserve
source assets and exterior vertices; the worker exited after 32.60 seconds.
The other 23 calibrated poses remain at 2.5 mm.

Whole-human broadphase and nonlinear bounds were rebuilt for both poses, yielding
51,020 constraints. The common patch plane still has a rechecked conflict. A
receipt-name error in the first solver launch was repaired without rebuilding
the system; both attempts are retained.

## Correction outcome

Exact polynomial recentering and batched separating axes pass their focused
checks. Local steps reduce the initial patch distortion but eventually stall:
38 pairs remain below clearance and fold gates fail. Intermediate linear
relaxations never count as acceptance; final geometry is checked separately.

Starting at the unchanged source exposes only four pairs below the solver's
8 micrometer buffer, all on the previously diagnosed connected patch. The largest
deficit is 7.4763 micrometers and there are no fold failures. Small local steps
do not improve it. Existing source proximity is not itself a new crossing, and
these results do not prove that all possible geometric repairs are impossible.

Next, inspect intended corrective activation and visible onset before another
solve. Meaningful improvement at 110/130 degrees remains required. Exact source
preservation elsewhere must be demonstrated; changing onset is not permission to
skip contact checks or claim visual acceptance. Full 73-pose geometry, stretch,
benefit, protected regions, fresh halo, cold reopening, visual review and public
implementation remain open.

All six workers are terminal. No runtime/release change, full-suite repeat,
render, bake, Unreal run or Sundown write occurred. Executed scripts, matrices,
failures and source captures remain at the workspace paths pinned by the receipt.
The [preceding diagnosis](blender-knee-contact-anchors.md) remains historical.
