# Blender knee: witness and backtracking

## Latest: complete fold coverage and actual contact improvement

The [contact continuation receipt](../artifacts/verification/blender-knee-buffered-contact-20261102.json)
records four focused failing-then-passing checks. The evaluator retains all 1,336
affected quads, including 482 omitted from the old linear rows because their
derivatives were zero. A zero derivative does not establish a permanent lack of
response. Evidence contracts reject mismatched rows; ranking and backtracking
reject absent or spent fold buffers.

One bounded 170.76-second search accepts 13 steps. Sixteen actual Blender
captures verify 11.88% lower worst contact deficit: 0.1146352 to
0.1010204 mm. Twenty contacts still fail. All 1,336 actual fold
checks pass, with no degenerate triangles. Minimum original fold slack is
0.0043418; maximum prediction error is 0.126597 micrometers.
Source/exterior/inventory preservation, full correction benefit and the 8 mm
movement cap pass. Actual final 8 micrometer clearance remains unchanged.

The verified point remains inside the existing measured 0.35 mm models; no
calibration was repeated. Continue from this nonzero point with complete coverage
and buffered ranking. Small late-step gains warrant improving numerical
efficiency before a longer continuation. Full-pose, cold, visual and public
implementation gates remain; no character or production release is accepted.

No full suite, render, bake, Unreal run or Sundown write occurred.

## Earlier: actual fold clearance verified

The [buffered-fold receipt](../artifacts/verification/blender-knee-fold-buffer-20261102.json)
records three test-first regressions and successful actual Blender fold checks.
A conditional coherence-error bound accounts for the existing 1 micrometer
position-error budget. It guides proposals; it does not replace actual validation
or claim a guaranteed error bound for every unmeasured prediction.

One restoration step and 16 center-only Blender captures produce zero failed
folds and zero degenerate triangles across 1336 affected quads,
including all prior fold identities. Minimum original fold-margin slack is
0.0034004; source and exterior geometry are unchanged.
The actual fold threshold was not reduced or rounded. No calibration was repeated.

Twenty contact failures remain, with worst deficit
0.1146 mm. The 2 micrometer allowance used to restore
folds is an intermediate-step limit; final 8 micrometer clearance remains unchanged.
Continue contact repair from the verified point while retaining buffered folds,
full correction benefit and the 8 mm movement cap. Include an unrelaxed contact
proposal and retain all actual, full-pose, cold, visual and public-command gates.
The character and production release remain unapproved.

No full suite, render, bake, Unreal run or Sundown write occurred.

## Earlier: fold-preserving branch

The [fold-preserving receipt](../artifacts/verification/blender-knee-fold-preserving-20261102.json)
records two test-first regressions and a branch that keeps every modeled fold
clear throughout accepted steps. Correction benefit and movement caps remain
hard. The first 11 steps reduce worst contact deficit to
0.1309 mm. A verified 5-micrometer step
shows that smaller moves can improve after the old search stalls; finer search
adds 24 steps, reaching 0.1129 mm.

The search ended with `time_budget` and four parameters at the
measured boundary. Blender then verifies the center within
0.1602 micrometers of prediction and measures a fresh
0.35 mm range in 126 captures. Independent controls pass the
unchanged 1 micrometer prediction gate; source and exterior geometry are preserved.

Fresh triangulation/whole-human checks still fail 20 contacts and
1 fold margin. High-surface polygon 35296 at time 12 has positive
coherence 0.01999684 against the required 0.02. It remains failed, despite its
small deficit. Worst actual contact deficit is 0.1129 mm.
No character or artistic acceptance follows. Add a regression for the model-to-Blender fold-margin loss; restore a buffered fold-clear point using the fresh 0.35 mm models, then verify it in Blender before further contact repair. Do not round away the failed margin.

No render, bake, full-suite rerun, Unreal run or Sundown write occurred. Full
73-pose, source, stretch/protected/halo, cold, visual and public-command gates remain.

## Preceding diagnosis

Five focused regressions pass for source-oriented proposal planes and guarded
backtracking. The [receipt](../artifacts/verification/blender-knee-backtracking-20261102.json)
retains the diagnosis, rejected attempts, accepted intermediate point and hashes.
This is research; no public tool, corrected asset or release was promoted.

## What the stalled point revealed

Contacts account for 91.27% of the frozen conflict witness. Removing the model
boundary in a diagnostic still produces a conflict certificate, so expanding
the measurement cube alone is not an established fix. Two neighboring contact
pairs, carrying 45.74% of witness weight together, chose nearly opposite escape
directions although their source directions agree. These are local linear
findings, not proof that nonlinear repair is impossible.

Source-oriented proposals pass three controls, including the actual patch and
reversed triangle winding. Broad and witness-only orientation attempts still
fail to improve at their full step. Final contact detection remains independent.

An audit then finds useful partial moves in 24 of 180 evaluations of retained
directions. Two failing-then-passing regressions add backtracking without trading
hard benefit, movement or projection constraints for progress. The best audited
fraction and one subsequent step reduce worst modeled contact deficit from
0.1138 to 0.1117 mm. The later step's improvement is smaller than model prediction
uncertainty and is not claimed as a measurable Blender or visual improvement.

## Still rejected and next work

Nineteen contacts and three folds still fail, including one reversed orientation.
Mean correction benefit remains 93.32%/93.12%; maximum rest offset is 7.2516 mm.
No component exactly reaches the measured boundary. All acceptance gates remain.

Next, test preserving fold clearance throughout repair from the retained
fold-clear, full-benefit seed. Peak-error improvement has allowed inverted folds
in intermediate points; keeping folds hard may avoid that path. Reuse the
existing models and guarded backtracking. Do not repeat the stalled directions.

Actual Blender geometry, full 73-pose contact/stretch/protected/halo checks,
cold reopening, visual review and public implementation remain open. Four owned
numerical workers exited; no Blender capture, render, bake, aggregate rerun,
Unreal run or Sundown write occurred. The sealed 0.9 package is unchanged.

Previous evidence: [consistent local progress](blender-knee-progress.md).
