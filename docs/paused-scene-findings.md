# Blue Horizon pause findings and resumed work

Plug-in development was explicitly paused on 2026-10-30 for the separate carrier
launch cinematic. It has now resumed at the user's request. The historical findings
below remain retained; the resource-reporting correction now has passing 0.7 evidence.

The pre-existing [final 0.7 aggregate](../artifacts/verification/release-0.7.0-final.json)
finished during the pause: 75 stages, 582 host tests and 62 Blender suites passed;
all 186 source/config files remained unchanged. No 0.7 source checkpoint or final
secondary-version matrix was sealed at that pause point. The resumed
[resource-qualified aggregate](../artifacts/verification/release-0.7.0-resource-final.json)
now passes 77 stages, 582 Python tests and 64 Blender suites with 188 source/config
files unchanged; the separate Python 3.13.11 matrix also passes all 582 tests.
Install the exact **0.7 ZIP in [verification](verification.md)**. Its source checkpoint
is retained; these results do not establish production acceptance.

The carrier scene exercises the checkout's public `scene.inspect`, `scene.validate`
and `scene.resources` commands. Its models, motion and lighting were authored by
ordinary Blender scripts; Framewright did not generate the assets.

Historical FW-053 defect: `scene.resources` included evaluated curve/text instances,
then read their original Curve data as Mesh and accessed `polygons`, raising
`AttributeError`. The original failure is retained in
`artifacts/blue-horizon-20261030/framewright-scene-report.json` and `build-final.log`.
The artwork workflow measured a temporary snapshot with evaluated curves/text
converted to meshes; source curves remained editable. That workaround did not
repair the extension or prove reporting support for the original editable scene.

The [verified correction](increment14-resource-accounting.md) now counts evaluated
mesh components from editable sources and separates their original data types.
Ten new tests and nine independent review tests pass, including shared data,
instances, generated materials and temporary-mesh cleanup. The original carrier
reports **458,951 evaluated triangles** at frames 1 and 330 without a converted
snapshot or saved derivative; source file, IDs, data, actions and state remain
unchanged. Mixed non-mesh outputs remain explicitly unmeasured. The
[tool inventory](tool-inventory.md) distinguishes this reporting capability from
remaining artistic, native and performance work. Sandbox temporary-directory and
hard-link failures remain linked in [verification](verification.md), alongside the
approved complete run that passed.

The scene-specific preflight reports zero errors and 183 warnings: 179 open-boundary
findings on authored surfaces/details and four animated exhaust scales. UV and
texture-target requirements are disabled because the materials are procedural.
These results do not certify watertight export meshes, textured-game readiness,
AAA appearance, or Sundown integration.

Prior knee candidates still fail the no-added-crossing guard. The
[retained study receipt](../artifacts/knee-contour-study/20261030T204835Z-a14df1de/study-receipt.json)
records five new crossing identities across seven of 73 sampled states per finalist,
despite lower total intersection counts. Fixed-boundary triangles are involved.
No candidate was accepted or promoted during the scene task. Region authoring is
separate completed engineering, with [cold human evidence](increment13-region-authoring.md);
it does not resolve the knee or supply artistic approval.
