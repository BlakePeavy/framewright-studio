# Blender knee: consistent local progress

Subsequent work: [witness and backtracking](blender-knee-backtracking.md).

Seven focused tests fix two research-solver issues: squared-error ranking
rejected a candidate with a smaller worst defect, and normalized fold rows
received relaxation inconsistent with that ranking. Worst-defect ranking and
unit-consistent relaxation now pass their retained and mathematical controls.
See the [receipt](../artifacts/verification/blender-knee-progress-20261102.json).

Two numerical continuations reuse the measured Blender models and finish in
66.6 seconds combined. They advance eight steps after the retained alternative.
The worst modeled contact deficit falls from 0.2363 to 0.1138 mm (51.8%), while
the required correction benefit and 8 mm rest-offset cap remain satisfied.
Mean benefit is 93.42%/93.22%; the maximum rest offset is 7.2597 mm.

**The correction remains rejected.** Nineteen contact checks and three fold
checks fail, including two reversed fold orientations. A lower worst-defect
score is not geometry acceptance or evidence of visual improvement. All final
clearance, fold, benefit and preservation checks remain unchanged.

Four components reach the current model boundary. At the terminal point, the
0.1 mm / 90% relaxation proposal has a frozen-system conflict certificate;
the 0.3 mm / 90% attempt reaches its 180-sweep budget without feasibility or
a conflict certificate. Inspect the tight-row witness and boundary/benefit
contributions before choosing additional measurements. These local results
do not establish that nonlinear repair is impossible.

No Blender capture, render, bake, full-suite repetition, Unreal run or Sundown
write occurred. Actual corrected Blender geometry, full 73-pose contact,
stretch, protected-region and influence coverage, cold reopening, visual
review and public implementation remain open. Executed scripts and evidence
are pinned at workspace paths in the receipt. This is an unreleased research
increment; the sealed 0.9 package is unchanged.

Previous evidence: [full-benefit repair](blender-knee-benefit-repair.md).
