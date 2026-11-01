# Cabinet hinge and panel construction

This bounded 0.5 change corrects the existing single-door cabinet builder without
adding a new layout or changing its request fields. It remains an editable technical
fixture; the procedural wood, hardware and simplified joinery do not establish
reference fidelity, fabrication readiness or artistic acceptance.

The [read-only study](../artifacts/cabinet-modeling-study/probe-68754758/report.json)
compared the generated geometry with the separately retained, authored
[Poly Haven cabinet](increment10-exr-intake.md). That reference informed the gap
review, not a pass/fail art standard. Its five separate cabinet/door/drawer parts,
original materials and source bytes were retained. No external texture is shipped.

## Reproduced defects and bounded changes

At default dimensions, the old rotation origin was 14.4 mm behind the visible hinge
pin axis. A point on the moving hinge line drifted 20.36 mm from the pin at 90 degrees
and 28.36 mm at 160 degrees. The pivot now shares the fixed pins' axis. Their fixed
world transforms remain unchanged while the door rotates.

The inset panels were placed by quarter-height fractions instead of the actual
openings between three rails. Each left a 3.825 mm through-gap beside the middle
rail and overlapped an outer rail by 34.425 mm. The panels now use the actual opening
bounds and the existing horizontal seat allowance on all four edges. Default seat
overlap is 7.65 mm. Requests whose rails leave no positive panel opening are refused
before allocation in both preview and apply.

The corrected pivot exposed a second collision in the existing broad hinge plate on
5 mm boards: evaluated triangles intersected the carcass at 45 degrees. The part's
overhang behind its pivot is now capped by board thickness. This preserves the
current simplified hardware while clearing the sampled door motion.

The shared construction/evaluated-resource path also refuses registered
`frame_change_pre`, `frame_change_post`, `depsgraph_update_pre` or
`depsgraph_update_post` callbacks before it allocates or evaluates. Independent red
tests observed a callback changing unrelated authored data during cabinet/facade
construction and resource inspection. Review creation uses the same conservative
policy. Handlers are never removed or disabled; builder/review previews remain
available and nonmutating.

Independent review also reproduced metre dimensions changing physically at scene
unit scales 0.01 and 10. Builders now convert only their new objects' world matrices
from authored metres to the active scene's units. Mesh coordinates and bevel widths
stay in metres, with uniform object scaling applying the conversion. Parent worlds
are assigned and evaluated before children, retaining articulated door motion.
Source objects, materials and scene settings remain unchanged.

Review bounds and copied worlds convert the active scene's unit scale into a new
one-metre-unit review scene. Cameras, lights and their framing use those physical
bounds. Returned `unit_conversion` metadata records source/output metres per
Blender unit and the world-coordinate factor. Review collections must belong to the
active source scene, so a collection from a different scene cannot silently borrow
the wrong unit scale. Parameters and requested locations continue to mean metres.

## TDD evidence

The first construction run had **19 failing assertions in eight tests**. It caught
hinge-axis disagreement, middle-rail ray gaps, asymmetric seats, impossible
openings and actual evaluated door/body intersections. The first fix still failed
the thin-board collision case, which prompted the bounded plate correction.

The first eight construction tests cover eight dimension combinations, including
the exact width/depth/height minimum and maximum, thin/thick boards, translated
origins, 33 door angles at five-degree intervals, evaluated ray coverage beside the
middle rail, finite closed mesh parts, UV data, unchanged authored geometry/shape
value/action/context, and injected failure after the second panel allocation.
The final suite has **12 tests**: four additional cases verify articulated units,
rotated/nonuniform nested parent placement with parent inverses, evaluated bevels
and camera/light physical scale, and rejection of ambiguous cross-scene units.
Three independent unit tests, all 16 existing production tests, all 10 material
assignment/review tests and the five callback tests also pass.
Tests ran in owned background Blender 5.2.1 LTS processes with disabled autoexec.

Logs: [initial red](../artifacts/cabinet-modeling-study/probe-68754758/construction-red.log),
[thin-board residual](../artifacts/cabinet-modeling-study/probe-68754758/construction-first.log),
[boundary green](../artifacts/cabinet-modeling-study/probe-68754758/construction-boundaries.log),
[final all-size ray check](../artifacts/cabinet-modeling-study/probe-68754758/construction-final.log),
[existing production tests](../artifacts/cabinet-modeling-study/probe-68754758/production-regression.log),
[callback red](../artifacts/construction-callbacks-red.log),
[callback green](../artifacts/construction-callbacks-green.log).
The independent unit red run had six failing subcases; the nested/door red run
had eleven failing assertions. See [independent unit red](../artifacts/construction-units-red.log),
[nested unit red](../artifacts/cabinet-modeling-study/probe-68754758/construction-units-nested-red.log),
[final 12-test green](../artifacts/cabinet-modeling-study/probe-68754758/construction-final-units-green.log),
[independent unit green](../artifacts/construction-units-green.log),
[final callback green](../artifacts/construction-callbacks-final-green.log),
[production regression](../artifacts/cabinet-modeling-study/probe-68754758/production-units-regression.log)
and [material-review regression](../artifacts/cabinet-modeling-study/probe-68754758/material-review-units-regression.log).

## Matched visual and cold-reopen evidence

The [local comparison](../artifacts/cabinet-modeling-study/20261030T193340Z-e6bd98b1/index.html)
contains ten actual 512px CPU Cycles/64-sample AgX renders: closed front, middle-rail
detail, open 65-degree three-quarter/hinge detail, and full open 160-degree views.
The retained 0.4 builder was loaded from its unchanged verified ZIP into a disposable
process. Both versions use matching cameras and neutral review lighting; the two
160-degree views use a wider 42 mm lens to include the complete door. Other
perspective views use 50 mm. All ten final images were inspected.

The rendered rail detail exposes the original through-gaps and shows them closed
in the corrected model. The hinge view shows rotation around the pin after the
fix, while also exposing the still-simplified mounting hardware. Default-size
metrics recorded 21 intersecting samples out of 33 for the retained builder
(up to 148 overlapping triangle pairs), versus zero for the corrected builder.
The corrected sampled moving-vertex/body distance minimum is 6.19 mm; this is
not a global minimum-clearance claim.

The [receipt](../artifacts/cabinet-modeling-study/20261030T193340Z-e6bd98b1/receipt.json)
pins module, retained ZIP, original reference, script, image and saved `.blend`
hashes. The [cold check](../artifacts/cabinet-modeling-study/20261030T193340Z-e6bd98b1/cold-reopen.json)
reproduced both authored-source fingerprints and all 33-angle measurements exactly
with autoexec disabled. The reference was only hashed in this render run; its
bytes and the verified 0.4 ZIP remained unchanged. All outputs are ignored local
artifacts, outside the extension package.

## Subsequent omitted-parent audit

Independent review found that selecting a child without its nonuniform/rotated
parent could flatten a sheared world transform into ordinary location/rotation/scale.
A successful review moved the test vertices by up to 4.791 mm in a 0.01-unit scene.
The source stayed unchanged, but the copied geometry did not match it physically.

Review creation now refuses this case before allocation. Include the complete
owned parent hierarchy, or apply transforms on a separate derivative first.
The existing nested-parent test verifies that included hierarchies still preserve
world placement. Omitted nonshearing parents remain supported. The guard does not
change the builder's generated cabinet geometry or the retained visual evidence.

The [independent red](../artifacts/final-unit-review-red.log) and
[green](../artifacts/final-unit-review-first-green.log) runs include this regression
alongside two bake material-assignment defects. The 12 construction, three unit,
five callback, 16 production and 10 material-assignment tests pass again; logs use
the `artifacts/final-review-` prefix. The post-audit construction module SHA256 is
`06acfb2ea837bda8a14e6a61fb64f3b96728b9d12a164f17b7217e57b64caef0`.

A later native-driver probe reproduced an unrelated object's location changing
during a successful review because a source Material FCurve traversed an ID-valued
property. Review now shares the baker's bounded static-data preflight before any
evaluation/allocation, including nested shader groups and shape-key data. Source
actions/drivers are retained and unsupported inputs receive a refusal. The same
review test covers preview and apply; all existing construction and material-review
tests remain green. See the [dependency evidence](increment11-bake-units.md#native-data-driver-dependency-boundary).
Final construction module SHA256:
`7eb06bd11b2801558c3496dae2df1d82a5a6cfbf418b7706b066e004d8724639`.

## Limits and next modeling work

The motion check measures evaluated triangle intersections and moving-vertex
distance to the stationary carcass/shelves/plinth at sampled angles. It excludes
intentional hinge-pin contact and does not prove continuous collision freedom,
global minimum clearance or every possible valid parameter combination.

Panel seats still use overlapping rectangular solids: cut grooves, mortises,
rabbets and actual assembly tolerances are absent. Hinge knuckles/mounts, screw
slots, hollow drawers/runners and paired-door layouts need separate bounded work.
UVs are deterministic per-object islands; physical texel density, grain direction
and material regions across parts remain provisional. The reference has different
proportions, paint and layout, so matching it requires explicit design choices and
independent review. Neither render resolution nor these structural checks grants
an AAA or native-engine acceptance result.
