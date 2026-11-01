# Verification and release evidence

Recorded through 2026-11-01 on Windows with Blender **5.2.1 LTS**, build `9e2066aef7ef`.
Validation uses owned fixtures/background processes. It has not changed the shared
Blender session, Sundown assets or the native game runtime. Technical checks, visual
review, native integration and production acceptance are separate outcomes.

The recommended install is the **0.8.0 ZIP identified below**. Its final aggregate
and both Python matrices pass. Earlier packages, source checkpoints and failure
evidence remain retained. No native-engine execution or artistic acceptance is implied.

## Verified engineering preview: 0.8.0

The [final aggregate receipt](../artifacts/verification/release-0.8.0-candidate.json)
and [log](../artifacts/verification/release-0.8.0-candidate.log), recorded at
**16:21:53 UTC on 2026-11-01**, contain **82 passing stages in 398.616 seconds**:
812 Python tests on **3.11.15**, 69 isolated Blender suites, packaging/byte audit,
actual **0.7→0.8→0.7→0.8** installed lifecycle, batch, worker and packaged MCP checks.
All **208 source/config files remained unchanged**. Source snapshot SHA256:
`1b6a087c469c26bd9373ecd4d1fece8a3a4d2afc2babba638390d6b820ce34dc`.
The separate [Python 3.13.11 matrix](../artifacts/verification/python313-0.8-20261101T162125Z-4fe3c56f.json)
and [log](../artifacts/verification/python313-0.8-20261101T162125Z-4fe3c56f.log)
pass **812 tests and 294 subtests**, without skips, on the identical source snapshot.
The shared environment remains Python 3.11.

The [0.8.0 install ZIP](../dist/framewright_studio-0.8.0.zip) is **237,048 bytes**;
all **51 files** match tested runtime bytes in its
[audit receipt](../dist/framewright_studio-0.8.0.receipt.json). SHA256:

```text
107af5e0fe5b64cc15bd118ff82da3b726e797257357f9c238b323c425952f29
```

The [promotion receipt](../artifacts/verification/promotion-0.8.0.json) verifies
370 copied files, retained replacement preimages, unchanged staging index and
unchanged older packages. The [source checkpoint receipt](../artifacts/verification/git-tree-0.8.0.json)
retains tree `0d946dc64a758b940ce9c88c7bc08bdc13cd0adc` under
`refs/framewright/checkpoints/0.8.0`. Its [source archive](../dist/framewright-studio-source-0.8.0.zip)
is **946,592 bytes / 277 files**, SHA256
`bf2f7d6b9605d3b924f928c6d2d86178d0171ef6379f3afe4488d759e4a4da9d`.
Every staged blob matches the Git-normalized promoted bytes, and every archived
file matches its blob. A separate index preserves the user's staging; no author,
commit or remote publication was invented. The archive predates these checkpoint notes.

The first seal attempt refused before publishing: the system Git setting converted
both extensionless license files to CRLF during archive export. The
[independent diagnosis](../artifacts/verification/seal-eol-diagnosis-0.8.json)
records the exact difference and retained attempt. Command-local LF export settings
resolved it; all 277 files pass the unchanged strict byte check in the final archive.

The [material-atlas increment](increment16-material-atlas.md) adds the 59th command,
`surfaces.bake_material_atlas`. Actual 1024 and 8192 cabinet assemblies pass source
preservation, source→atlas and cold Blender/GLB/FBX render comparisons, map-role
audits and negative material-loss controls. The 8K run uses four real 8192² packed
maps; its 1,193.70-second worker peaks at 16.39 GiB working memory and 18.19 GiB
private memory. This single CPU run establishes bounded transport and measured
cost, not an efficiency target or artist-approved source materials.

The [native static adapter](increment15-native-static-adapter.md) has 169 focused
contract/budget tests and admits the actual 325 MB 8K GLB only with explicit higher
budgets. A fresh owned Unreal fixture is prepared. Actual import, native materials,
cold reload, rendered parity and runtime performance remain unverified; launching
the fixture is pending the already requested editor-launch authorization.
The isolated surface and knee studies are outside this package and grant no new
artistic or deformation acceptance. The [roadmap](roadmap.md) retains those gates.

## Verified developer preview: 0.7.0 with resource accounting correction

The [final resource aggregate receipt](../artifacts/verification/release-0.7.0-resource-final.json)
and [log](../artifacts/verification/release-0.7.0-resource-final.log), recorded at
**22:42:50 UTC on 2026-10-30**, contain **77 passing stages in 274.470 seconds**:
582 Python tests on **3.11.15**, 64 isolated Blender suites, packaging/byte audit,
actual **0.6→0.7→0.6→0.7** installed lifecycle, batch and worker checks. All
**188 source/config files remained unchanged**. Source snapshot SHA256:
`77f1b7fc3043e76b7a6b6423a9ba0f4c5fcdf1847707a7a666631123a32fd8c1`.
The separate [Python 3.13.11 matrix](../artifacts/python-0.7-resource-python313.log)
passed **582 tests in 9.57 seconds**.

The [0.7.0 install ZIP](../dist/framewright_studio-0.7.0.zip) is **204,636 bytes**;
all **47 files** match tested runtime bytes in its
[audit receipt](../dist/framewright_studio-0.7.0.receipt.json). SHA256:

```text
bfbe7056b3a39135f83c1ddd5a320a7b1943432a66aa58902d78bb7f7fe9ff03
```

The [resource accounting correction](increment14-resource-accounting.md) passed
ten new Blender tests and nine independent review tests. Original mesh counts remain
separate from converted-source counts; evaluated mesh components and generated
material references are counted without duplicating implicit projections. Unmeasured
non-mesh components are explicit. The original editable carrier scene now reports
**458,951 triangles** at both frames 1 and 330 without conversion, saving or source
changes. [Region authoring](increment13-region-authoring.md) and its cold human
round-trip also remain covered. The [inventory](tool-inventory.md) lists all 58 API
commands; these checks do not grant artistic, native-engine or production acceptance.

Two earlier resumed attempts failed under managed-sandbox filesystem restrictions:
[temporary-directory receipt](../artifacts/verification/release-0.7.0-resource-sandbox-temp.json)
and [log](../artifacts/verification/release-0.7.0-resource-sandbox-temp.log), followed by
[hard-link receipt](../artifacts/verification/release-0.7.0-resource-sandbox-hardlink.json)
and [log](../artifacts/verification/release-0.7.0-resource-sandbox-hardlink.log).
Both retained unchanged source snapshots and incomplete status. The approved run
outside those restrictions passed the complete suite above; the failed attempts
are retained and are not release receipts.

The [0.7 source archive](../dist/framewright-studio-source-0.7.0.zip) retains Git
tree `bfe87a09da5fde493600aadf76c19d96a3bdc064` under
`refs/framewright/checkpoints/0.7.0`: **849,078 bytes, 255 files**, SHA256
`805b6e6876844e1c77be6b88f17ecd7408d7c43ce3ad17f4919c0f5e7d895378`.
The [checkpoint receipt](../artifacts/verification/git-tree-0.7.0.json) records the
matching tested source snapshot and unchanged canonical staging index. A separate
index was used; no author, commit or remote publication was invented. Text is
Git-normalized; exact runtime bytes remain in the install ZIP. This archive predates
the present self-referential hash/status notes.

The [promotion receipt](../artifacts/verification/resource-promotion.json) verifies
the canonical repository against the tested candidate. The earlier 0.7
[package](../artifacts/verification/0.7-before-resource/framewright_studio-0.7.0.zip)
and [audit](../artifacts/verification/0.7-before-resource/framewright_studio-0.7.0.receipt.json)
remain preserved separately; identify the current build by its exact hash above.

## Earlier 0.7 aggregate before the resource correction

The [final 0.7 aggregate receipt](../artifacts/verification/release-0.7.0-final.json)
and [log](../artifacts/verification/release-0.7.0-final.log), recorded at 21:26 UTC
on 2026-10-30, contain **75 passing stages in 300.019 seconds**: 582 Python tests
on 3.11.15, 62 isolated Blender suites, packaging/byte audit, actual
**0.6→0.7→0.6→0.7** installed lifecycle, batch and worker checks. All **186
source/config files remained unchanged**. Source snapshot SHA256:
`227a863eab0b21d23a719cef1733592c77b2019ae0b1f9cbeb8efab9a77904db`.
This run finished during the Blue Horizon development pause. At that point, a final
secondary-version matrix and sealed 0.7 source checkpoint were not completed, and
0.6 remained the install recommendation. The resource-qualified 0.7 ZIP above now
supersedes that recommendation; this older receipt does not cover the later correction.

[Evaluated region authoring](increment13-region-authoring.md) is implemented,
including exact group/vertex selection, complete bounded output, source preservation
and the retained human's four descriptions and two complete 121-sample inspections
reproduced after cold reopening. This is finite-topology authoring and sampled contact
evidence, not anatomical inference or full-character acceptance.

The first 0.7 aggregate stopped in Python tests: structured workflow bindings
exposed a missing MCP check for an entire material-parameter object supplied by
binding. A fake worker reproduced the policy bypass; no real file operation ran.
The [failed receipt](../artifacts/verification/release-0.7.0-first-failed.json) and
[log](../artifacts/verification/release-0.7.0-first-failed.log) are retained.
An explicit pre-submit filesystem-parameter guard and passing regression controls
cover that case in the successful final aggregate. The installed-package MCP entry
and package-version reporting also have passing regressions. A separate interrupted
environment attempt remains [superseded evidence](../artifacts/verification/release-0.7.0-environment-note.json);
it must not be substituted for the restored-environment final receipt above.

The [pause findings](paused-scene-findings.md) retain the actual `scene.resources`
curve/text crash and the cinematic's temporary converted-scene workaround. The
reporting defect is closed by the resumed evidence above. The separate knee-contour
study remains rejected: both finalists introduce new crossing identities despite
reducing total intersection counts. The resource correction does not resolve that
asset-quality finding.

## Verified developer preview: 0.6.0

The [final aggregate receipt](../artifacts/verification/release-0.6.0-final.json)
and [log](../artifacts/verification/release-0.6.0-final.log), recorded at 20:45 UTC,
show **73 stages passing in 271.097 seconds**, with all **177 source/config files
unchanged**. This includes 515 Python tests on 3.11.15 (7.55 seconds), 11 host tests,
60 isolated Blender suites (434 unittest cases and three render-fixture drivers),
manifest/build/ZIP validation, byte audit, installed lifecycle, eight batch checks
and six worker checks across three jobs. A separate
[Python 3.13 run](../artifacts/python-0.6-python313.log) passed all **515 tests and
252 subtests in 5.51 seconds**, including its real owned-worker smoke.

The [0.6.0 install ZIP](../dist/framewright_studio-0.6.0.zip) is **195,710 bytes**;
all 45 files match runtime bytes in the
[audit receipt](../dist/framewright_studio-0.6.0.receipt.json). SHA256:

```text
ab457792d2a7c5e45b9d327ef63f5fc22bd118841e1a93200a5f3aac7ffd09dc
```

Tested source/config snapshot SHA256:
`4705703d9ab74706a50504fae27f0c7ba566c305517c78e36990d34e687415f6`.
Actual isolated **0.5→0.6→0.5→0.6** installation, persisted enablement, installed
API/operator/workflow checks and disable/re-enable passed. Disposable Blender user
directories were used; the shared editor and Sundown remain untouched.

The [0.6 source archive](../dist/framewright-studio-source-0.6.0.zip) retains Git
tree `6e56cf468c0bbf33d18516e2da7572d20359863a` under
`refs/framewright/checkpoints/0.6.0`. Its SHA256 is
`e6a26e6eca5d3b5a2f6d55fecf6e405032916b91bd35ae8fcff7d1ffd6e704ca`
(799,949 bytes). Text is Git-normalized; the install ZIP preserves tested runtime
bytes. The archive predates this self-referential hash note. No author identity,
commit or remote publication was invented.

New evidence covers [regional contacts](increment12-regional-contacts.md),
[independently reviewed geometry predicates](increment12-region-geometry.md), and
[bounded normal-image inspection](increment12-normal-inspection.md). The retained
human's 966 declared sole triangles reproduce both full 121-sample reports after
cold reopening: zero baseline crossings and 363 ridge-control crossings missed by
the old ten markers. Invalid constraint/bone targets and animated subdivision
now refuse before unsafe evaluation. Floating-point, regional and sampled limits
remain explicit; this does not establish whole-body or continuous clearance.

Six actual 8K workers measured median readback/inspection time of 55.0871 → 3.37715
seconds with exact output fields and unchanged pixels. Their receipt retains its
historical runtime hashes; the measured normal helper is unchanged. This is a
synthetic inspection-only observation, not a complete bake speed or memory-cap claim.
The final aggregate's curved fixture is retained at
`artifacts/curved-bake/20261030T204221Z-29e1f32d/`; cold pixels and negative controls
pass. Artistic, full-character, native and production acceptance remain open.

## Verified developer preview: 0.5.0

The first 0.5 aggregate was stopped after independent review reproduced lost
material assignments and detached-parent shear in successful derivatives. Follow-up
checks also exposed animation paths reaching unrelated IDs in bake dependencies.
Those fixes and regressions passed together in the final 0.5 aggregate below;
the [interrupted-run record](../artifacts/verification/release-0.5.0-interrupted.json)
is retained and does not constitute a release receipt.

The [final aggregate receipt](../artifacts/verification/release-0.5.0-final.json)
and [log](../artifacts/verification/release-0.5.0-final.log), recorded at 20:05 UTC,
show **70 stages passing in 255.467 seconds**, with all **165 source/config files
unchanged**. This includes 442 Python tests on 3.11.15 (6.86 seconds), 11 host tests,
57 isolated Blender suites (398 unittest cases and three render-fixture drivers),
manifest/build/ZIP validation, byte audit, installed lifecycle, eight batch checks
and six worker checks across three jobs. A separate
[Python 3.13 run](../artifacts/python-0.5-python313.log) passed all **442 tests in
5.93 seconds**, including its real owned-worker smoke.

The [0.5.0 install ZIP](../dist/framewright_studio-0.5.0.zip) is **183,940 bytes**;
all 42 files match runtime bytes in the
[audit receipt](../dist/framewright_studio-0.5.0.receipt.json). SHA256:

```text
87a8d969a3cd0c40c3373b1803da466bd3ea031abb3c57682fc46809ca36aed0
```

Tested source/config snapshot SHA256:
`a838e67ca1ce584271e3db2649aca2aefe1077b355de132e11dcf2d88c52ed65`.
Actual isolated **0.4→0.5→0.4→0.5** installation, persisted enablement, installed
API/operator/workflow checks and disable/re-enable passed. Disposable Blender user
directories were used; the shared editor and Sundown remain untouched.

The [0.5 source archive](../dist/framewright-studio-source-0.5.0.zip) retains Git
tree `9a62f44fe2dbbae572ddfdfa3805d2c3e82a65e0` under
`refs/framewright/checkpoints/0.5.0`. Its SHA256 is
`25bffb59742d461ad53e94a1047cdd6d2b116af7c8ebfb299b748da6c05dd656`
(752,016 bytes). Text is Git-normalized; the install ZIP preserves tested runtime
bytes. The archive predates this self-referential hash note. No author identity,
commit or remote publication was invented.

New evidence covers [cabinet construction and units](increment11-cabinet-construction.md),
[bake units/materials/static dependencies](increment11-bake-units.md),
[curved normal/seam rendering](increment11-curved-bake.md),
[B-Bone endpoint transport](increment9-bbone-handoff.md),
[independent animation/export review](increment11-animation-review.md), and
[shape-bake dependency preservation](increment8-morph-handoff.md).
The final curved fixture reproduces its cold central pixels exactly and rejects
removed-normal/damaged-seam controls. A separate 361-sample prepared human low-cage
pilot retains under 1 mm bake error and micrometre-scale cold transport error;
it does not cover Multires or corrective geometry. The
[15-worker retained-asset measurements](increment11-production-corpus.md) retain
their earlier exact runtime hashes; they are historical measurements, not a new
performance run against every final 0.5 byte. Artistic, full-character, native and
production acceptance remain open on the roadmap.

## Verified developer preview: 0.4.0

The [final aggregate receipt](../artifacts/verification/release-0.4.0-final.json)
and [log](../artifacts/verification/release-0.4.0-final.log), recorded at 19:06 UTC,
show **56 stages passing in 226.742 seconds**, with all **143 source/config files
unchanged**. This includes 383 Python tests on 3.11.15 (7.12 seconds), 11 host tests,
43 isolated Blender suites (307 unittest cases and three render-fixture drivers),
manifest/build/ZIP validation, exact byte audit, installed lifecycle, eight batch
checks and six worker checks across three jobs. A separate
[Python 3.13.11 run](../artifacts/python-0.4-python313.log) passed **383 tests and
221 subtests in 5.72 seconds**, including its real owned-worker smoke.

The [0.4.0 install ZIP](../dist/framewright_studio-0.4.0.zip) is **170,006 bytes**;
all 40 files match runtime bytes in the
[audit receipt](../dist/framewright_studio-0.4.0.receipt.json). SHA256:

```text
bec958e746a0c9c47076c183051a5869e529f8305fe38558f73183932a8fa634
```

Tested source/config snapshot SHA256:
`3f551231abbe510b761a1d31b024d513e0c15ba5c89bdc1099cb9ce95fe1eebe`.
Actual isolated **0.3→0.4→0.3→0.4** installation, persisted enablement, installed
API/operator/workflow checks and disable/re-enable passed. Only disposable Blender
user directories were used; earlier archives remain available.

The [0.4 source archive](../dist/framewright-studio-source-0.4.0.zip) retains Git
tree `7c117c1837fee7f915681ebd82fcadbbe80c7339` under
`refs/framewright/checkpoints/0.4.0`. Its SHA256 is
`39d28bbd4aa4969606aa05870201e09940210700c85df8fc7993ab8fa639bbf1`
(649,324 bytes). Source text is Git-normalized; the install ZIP preserves the
tested runtime bytes. No author identity or remote publication was invented.

New evidence covers [coupled morph handoff](increment8-morph-handoff.md),
[skin contacts](increment10-skin-contacts.md) and their
[independent dependency/driver fixes](increment10-contact-review.md),
[interior/glass render controls](increment10-interior-glass.md),
[EXR data-map intake and actual cabinet handoff](increment10-exr-intake.md), and
[truncated EXR container rejection](increment10-exr-structure-review.md).
The selected human pilot again matches both 121-sample reports exactly after cold
reopening. The authored cabinet retains five parts and four 4K material bindings
through both cold formats. These are bounded technical/visual observations, not
studio, final-character or native-engine acceptance. Existing character defects,
segmented B-Bone handoff and newly identified builder hinge/panel issues remain on
the active roadmap.

## Verified developer preview: 0.3.0

The [final aggregate receipt](../artifacts/verification/release-0.3.0-final.json)
and [log](../artifacts/verification/release-0.3.0-final.log), recorded at 18:23 UTC,
show **46 command stages passing in 167.243 seconds**, with all 121 source/config
files unchanged. This includes Ruff, **301 Python tests**, 11 host tests,
**33 isolated Blender suites** (247 unittest cases and three render-fixture
drivers), manifest/build/ZIP validation, exact byte audit, installed lifecycle,
eight batch checks and six worker checks across three jobs. Python 3.11.15 passed
301 tests in 6.40 seconds; a separate [Python 3.13.11 run](../artifacts/python-0.3-python313.log)
passed 301 tests and 184 subtests in 5.58 seconds. Blender child execution is not
merged into Python coverage; no whole-product coverage percentage is claimed.

The verified [0.3.0 install ZIP](../dist/framewright_studio-0.3.0.zip) is
**149,689 bytes**, with 36 files matching runtime bytes in its
[audit receipt](../dist/framewright_studio-0.3.0.receipt.json). SHA256:

```text
842bed9333727889aac88a71c1c9dd4a16673c9b40d5dedd9215e8822f722016
```

Tested source/config snapshot SHA256:
`80012fa457c80922496fb7f9ee386f50e17a59fbec186090ad6326b47099af6a`.
Actual isolated **0.2→0.3→0.2→0.3** installation, persisted enablement,
installed API/workflow/operator checks and disable/re-enable passed. Only
disposable Blender user directories were used. The earlier 0.2 archives remain.

The [0.3 Git source archive](../dist/framewright-studio-source-0.3.0.zip) retains
tree `cffe23719dfd84c105d00e095271e091790ae31f`; its SHA256 is
`b0e8dabafbd155662832927af5bd464f8c18cc3c9e6c64400e06429750dc9236`.
Local refs retain the 0.2 and 0.3 trees under `refs/framewright/checkpoints/`.
Git-normalized text lives in the source archive; exact runtime bytes live in the
install ZIP. No author identity, commit or remote publication was invented.

Scoped checks now cover the [public cloth-bake command](increment9-cloth-bake-command.md)
with 11 Blender tests and exact 61-frame embedded-cache cold playback; the separate
physics suite has six tests. [Continuous corrective activation](increment7-corrective-activation.md)
has 11 Blender tests and exact reproduction of 39 actual human-pilot samples after
a disabled-autoexec cold reopen. [Stock full-human Rigify](increment7-full-human-rigify.md)
has eight tests for all fingers, hand IK, jaw, gaze, lids and pose preservation.
These do not resolve the retained human knee/underarm defects or approve garments,
face weights, hand grips or final character quality.

[Bidirectional LOD](increment7-bidirectional-lod.md) has 12 tests and an inspected
13-image silhouette/shadow fixture; it catches a missing thin fin that the prior
one-way metric and equal bounding boxes missed. [Spatial PBR handoff](increment9-material-handoff.md)
reproduced and fixed FBX's loss of red-channel roughness/metallic maps. Both cold
four-map renders now pass with individual missing-map controls. Independent
[export preservation review](export-material-review.md) adds eight regressions for
muted/animated shader dependencies, static pose/subframe retention and unrelated
authored state. Two further corrective regressions fix unnecessary reevaluation of
an unchanged source frame, preserving dirty rig-constraint and light values.

[Three actual 8K material runs](texture-performance.md) measure median whole-process
peak working set **2279.05 MiB**, peak private commit **2586.07 MiB**, and recipe
time **10.75 seconds**. These are Windows OS counters, not estimates or GPU residency.
Input hashes and cold-loaded maps remain exact. The separate [actual 8K handoff](8k-handoff.md)
passed five isolated workers with all 37 runtime/helper/script hashes unchanged.
Three 8192² image bindings survived both formats; fixed 512px render MAE was
0.00000655230 for GLB and 0.000000902562 for FBX. Cold FBX peak working set was
5.01 GiB and peak private commit 5.78 GiB. These single-run measurements are not
total-memory caps, GPU residency or native performance. No artist/native acceptance
or remote CI result is claimed.

## Verified developer preview: 0.2.0

The [final aggregate receipt](../artifacts/verification/release-0.2.0-final.json)
and [log](../artifacts/verification/release-0.2.0-final.log), recorded at 17:40 UTC,
show **all 36 command stages passing** in 126.506 seconds, with source bytes unchanged.
This includes Ruff, **270 Python tests** on 3.11.15, two OS-memory and six color-oracle
host tests, **24 isolated Blender suites** (180 unittest cases plus the rendered
surface-parity and color-pipeline fixtures), manifest/build/ZIP validation, byte
audit, installed lifecycle, eight batch checks and six worker checks across three
actual jobs. Blender child coverage is not merged into pytest coverage; no
whole-product coverage percentage is claimed.

A separate [Python 3.13.11 run](../artifacts/final-python313-v2.log) passed **270 tests
and 184 subtests** in 5.83 seconds, with the actual Blender-backed MCP check enabled.
The tested source/config snapshot contains 102 files, with digest
`045b69c5545313bec0589beb37c0b4e0150ea0df4b500ed3c56bba5dd2083364`.

The verified [0.2.0 ZIP](../dist/framewright_studio-0.2.0.zip) is **134,936 bytes**.
Its [byte-audit receipt](../dist/framewright_studio-0.2.0.receipt.json) matches all
33 packaged files to runtime sources; generated/reference assets are excluded.
SHA256:

```text
a04a7a4f4ff358c534c2411180507d71e72ff714755adec34e5658c4021002de
```

Actual isolated **0.1→0.2→0.1→0.2** installation, persisted enablement, installed
API/workflow/operator checks and disable/re-enable passed. Only disposable user
directories were used. An [earlier run](../artifacts/verification/release-0.2.0.json)
caught an overlong manifest permission description; the final run verifies its fix.
This release is a tested developer preview, not production/AAA acceptance.

A [Git source archive](../dist/framewright-studio-source-0.2.0.zip) retains tree
`0a106f8119d34ea1a0b55d1782496898802990e0` with repository-normalized text line endings.
Its SHA256 is `d9ffafc640f9661d57c8c80cc061ec0f5d4a4972a8c74119d69acbc243c05a6e`.
The initial tree is staged locally; no author identity was invented and no remote
publication was performed. Exact packaged runtime bytes remain in the install ZIP.

Recorded aggregate scope, with additional evidence linked below:

| Area | Observed checks and supported scope | Evidence |
|---|---|---|
| Core/API/jobs/provenance | Python contracts, malformed requests, hashes/lineage, independent acceptance states and owned paths | [Core](core-tdd.md), [API/jobs](api-tdd.md), [Provenance](increment2-provenance.md) |
| Adapter and repair transactions | 13 base and 17 transaction Blender tests; snapshots, stale plans, exact source/owned-output checks, rollback and cleanup | [Transactions](increment2-provenance.md) |
| Evaluated surfaces | 16 Blender tests; geometry/UV/channel coverage and actual world-space texel density with explicit unknowns | [Diagnostics](increment2-diagnostics.md), [Density](increment5-texel-density.md) |
| Construction/resources | 16 asset tests, 5 LOD tests, 2 workload-fixture tests; editable builders, collection instances and explicit LOD source/level coverage | [Assets](increment2-assets.md), [Resources](increment5-resource-performance.md) |
| Editable resource geometry | 10 reporting tests plus 9 independent review tests; converted sources, mixed components, nested instances, generated materials and cleanup | [Evaluated accounting](increment14-resource-accounting.md) |
| Rig/animation tools | 12 tests for Rigify, protected weights, sampled bake/retarget, corrective isolation, NLA/action slots and exact transform preservation | [Rigging](increment3-rigging.md) |
| Fit/binding/secondary | 5 landmark-fit, 6 heat-binding, 5 anatomical-pose and 8 secondary-adapter tests; copied skin parent inverses preserved | [Fit](increment5-rig-fit.md), [Binding](increment6-rig-binding.md), [Secondary](increment4-secondary.md) |
| Surface contacts | 13 Blender tests for authored sole/prop points, uneven/moving surfaces, units, FPS, bounded coverage and exact character-channel restoration | [Contacts](increment6-contacts.md) |
| Materials and baking | 7 PBR-recipe and 9 normal-bake tests; actual pixels, file/color-space/memory guards, explicit cages and UV/projection checks | [Materials](increment5-materials.md), [Baking](increment3-baking.md), [Cage corrections](increment5-board-gates-release.md) |
| Scoped interchange | 5 tests with cold GLB/FBX scope, asymmetric bounds, pivots, UVs, slots, weights and normalized motion | [Interchange](increment3-interchange.md) |
| Combined animation handoff | 2 tests; retarget→bake→explicit skin rebinding→both cold imports, 49 samples across the clip | [Animation handoff](increment4-animation-handoff.md) |
| Material assignment | 10 Blender tests; preserved slot links, geometry, shared peers, parent/skin/shape state and visible PBR workflow review copies | [Assignment](increment7-material-assignment.md) |
| API/UI/integration review | 4 feature-API, 6 UI, 8 integration-review and 8 final-regression tests; gates/JSON, export/HTML ownership cleanup and transactional registration | [Integration](increment2-integration.md), [Gates/release](increment5-board-gates-release.md), `scripts/test_final_regressions.py` |
| Evaluation and local AI boundary | Versioned eight-case corpus; 28 provider tests and 3 Blender evaluation tests; ranking, source/regression guards, actual outcomes and unknown costs; MCP process/path/response tests | [Evaluation](increment4-evaluation.md), [AI/MCP](increment3-ai.md) |
| Rendered parity | Separate real Cycles fixture driver requires source/bake and both GLB/FBX comparisons to pass; corrupted-normal/color controls fail | [Rendered parity](increment5-render-parity.md) |
| Controlled color pipeline | 18 analytical linear patches, saved HDR EXR/Standard/AgX output, exposure and independent cold-decode checks | [Color pipeline](increment6-color-pipeline.md) |

The combined animation fixture uses three joints, a 28-vertex explicitly bound skin,
different source/target rest proportions and one second of motion. Independent
imports retain UV/material evidence, compare normalized time, world-space vertices,
joints, bounds and deformation matrices, and preserve all source fingerprints.
Maximum sampled surface error was **0.0000007563 m for GLB** and
**0.0000012630 m for FBX**. This proves the fixture's coupling, not arbitrary rigs,
all interpolation modes or native game playback.

The latest recorded [render-parity report](../artifacts/surface-render-parity/20261030T170852Z-ade70a1b/report.json)
uses 128px, 48-sample CPU Cycles renders. In a fixed central crop, normal-bake
RGB mean absolute error was about **0.000300**; removing the normal produced
**0.015364** and failed. Portable base-color/scalar-roughness/scalar-metallic
parity was **0.000000441 for GLB** and **0.000004850 for FBX**; corrupt color
produced **0.200419** and failed. Both formats are mandatory. These are encoded
PNG comparisons for bounded opaque fixtures, not radiance/colorimetry, arbitrary
shader equivalence or native Unreal parity.

## Inspectable art and 8K evidence

The [review kit](benchmark-review.md) contains an editable 25 MB `.blend`, cabinet
and facade GLB/FBX exports, cold checks of all four exports, matched neutral/day/dusk
views and four anatomy-reference views. The cabinet/facade are construction
fixtures awaiting reference-driven refinement and artistic acceptance.

A real **8192×8192 cabinet PNG** was rendered and saved: 67,108,864 pixels,
61,819,181 bytes, CPU Cycles, 16 samples, denoising, AgX, 447.577 seconds.
The [resolution receipt](../artifacts/resolution-probe/20261030T164444Z-2bb30280/receipt.json)
records unchanged source bytes and image SHA256
`a0cfe1d4da44272fab9b422978ee90adaf9596a9570a6438705fdd06fbf45cdc`.
The full image exceeded the image-display transport limit; its full-resolution
pixels have not received visual acceptance. This is actual output-dimension
evidence, not proof of 8K detail or final lighting/art quality.

The separate [8K material pilot](increment5-materials.md) uses actual 8192×8192
Poly Haven wooden-planks color, roughness and OpenGL tangent-normal maps. Its
[cold verification](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/cold-verification.json)
confirms all dimensions, sRGB/Non-Color assignments, external paths and unchanged
source hashes. A saved editable scene and 512px Cycles review image exist. The
source page publishes a 2 m width and rounded 41 px/cm at 8K; the authored 2 m × 2 m
plane measures exactly **4096 texels/m** under the new read-only
[density diagnostic](increment5-texel-density.md). This verifies the authored
geometry/image mapping, not independent calibration of the photographed surface.
The later [8K handoff pilot](8k-handoff.md) closes bounded three-map cold export
parity. Native rendering, an 8K baked image and artist acceptance remain open.

The [human pilot](increment6-rig-binding.md) preserves the external CC0 authored
base mesh and creates a separate provisional fitted Rigify/heat-bound derivative.
The original intake still has no rig, weights or expression keys; the derivative
has 10,582 body vertices, 35 deform bones, zero unweighted vertices and a maximum
of seven influences. Eighteen 384px body renders and eight 512px joint closeups are
retained in [the candidate folder](../artifacts/human-rig-pilot/20261030T170355Z-f205d2b9/index.html).
An independent reopen reproduced 50 sampled scalar measurements exactly, preserved
source hashes and verified that two explicitly attached eyes follow the head.

**That human candidate is not accepted.** Actual inspected pixels show shoulder
compression/intersection, hard hip folds and sharp knee creases. The shoulder test
was a backward local-axis stress, not anatomical abduction. Pose-axis corrections,
weight/corrective refinement and further review are active on a new derivative;
the old evidence is retained. Complete normalized weights and matching cold
measurements do not establish acceptable deformation, face/finger controls,
eye gaze/blink or full-motion contacts.

## Performance and resource evidence

The [process-memory baseline](increment5-resource-performance.md) extends the
[initial Python-only baseline](performance-baseline.md) with three fresh Blender
children. Windows `GetProcessMemoryInfo` measures whole-process working set and
private commit separately from `tracemalloc` Python allocations.
These historical timings predate the 0.7 resource correction; they are not fresh
performance measurements of the [corrected implementation](increment14-resource-accounting.md).

| Fixture | Snapshot median | Resource median | Diagnostic/deformation median | Peak working set | Peak private commit |
|---|---:|---:|---:|---:|---:|
| 10k triangles | 3.092 ms | 1.587 ms | 115.398 ms | 228.10 MiB | 272.55 MiB |
| 100k triangles | 39.358 ms | 14.646 ms | 421.787 ms | 340.76 MiB | 402.84 MiB |
| 16 joints + 100 shared-mesh instances | 11.267 ms | 2.170 ms | 106.340 ms / five poses | 241.02 MiB | 306.72 MiB |

The rig/instance fixture has 11k unique source and 110k evaluated triangles.
Intersection sampling caps remain explicit. OS peaks include process startup,
fixture construction and traced work; they are not per-stage allocations or GPU
memory. These observations on the recorded Windows workstation are not universal
budgets, native engine frame rates, residency or streaming measurements. LOD
coverage uses declared source/level properties only; absent legacy metadata is
unknown, never inferred from object names.

## Offline Sundown handoff preparation

`scripts/prepare_sundown_pilot.py` now validates one explicitly selected static
review-kit asset without Blender or native-editor execution. Its 22 Python tests
were written first and passed after implementation. They cover current source/export
hashes, embedded/external receipt equality, source before/after JSON fingerprints,
object/material scope, static GLB/FBX coordinate/unit/FPS consistency, mismatched
cold rows, duplicate JSON keys, path boundaries, output refusal and owned partial
write cleanup. Identical path prefixes are not mistaken for directory containment.

The actual [WorkshopCabinet plan](../artifacts/sundown-handoff/WorkshopCabinet-reviewed-inputs.json)
verifies the 25 MB editable kit and both export files against their receipts, and
records each input receipt's own hash. It reads only the explicitly configured
target's literal `Source/SundownRunUnreal/SundownRun.uproject` file; that file reports
engine association `5.8`, not a queried editor build. Input bytes were rechecked
before publishing the new JSON. No game file was written or editor launched.

The proposed package root is `/Game/FramewrightPilots/WorkshopCabinet_7c303d740ed4`.
It is neither reserved nor created. Cold import results remain attributed to the
hashed prior report and are explicitly not reexecuted by this script. Blender
geometry is not re-extracted; source-record integrity does not authenticate its
claims. Procedural wood material warnings remain open. Native import, placement,
cold native verification and runtime binding stay `not_run`; art stays
`not_reviewed`. All 22 tests are included in the final aggregate above.

## Historical package: 0.1.0

Historical 0.1 evidence: 65 Python tests on 3.11.15 and 3.13.11; 13 Blender
adapter/UI tests; manifest/ZIP validation, clean import, persisted enablement,
disable/re-enable and eight actual batch checks, including cold save/reopen and
unchanged source bytes. That package contains the earlier preflight/repair scope.

`dist/framewright_studio-0.1.0.zip` was 25,812 bytes with SHA256:

```text
0b8eab0209d6a5074af252dbf437f4a287e741ccb1e4261d967e62ab50b8b278
```

The historical 95% coverage applied only to that earlier configured subset. Only
Windows/Blender 5.2.1 execution is established here. Current Linux/macOS, additional
Blender versions and remote CI execution remain unclaimed. The expanded 0.2
preview is separately verified above; this older archive remains for lifecycle tests.

## Preservation and acceptance limits

- Mutations require explicit apply and preserve source assets; derivative commands use owned data. Export/report commands create explicit owned files. Failure cleanup checks identity/content so it does not delete unrelated replacements.
- Registration preflights foreign operator/property collisions and rolls back only owned partial registration. UI failures and workflow gate failures are reported as failures.
- Repair tokens and workflow replay caches are process-local. Restart does not restore deletion authority. Earlier successful workflow steps remain after later failure; workflows and `.blend`/JSON pairs are not atomic.
- Worker deadlines require polling; synchronous Blender work cannot be interrupted internally. Rigify is an explicit worker-only opt-in, with no persistent live-user preference change.
- MCP is an OS-owned local stdio boundary with scoped absolute paths and bounded responses. Dynamic file-bearing workflow bindings are refused there. The in-process workflow API supports its separately tested explicit bindings. Neither is an OS filesystem sandbox or arbitrary-code service.
- Sampling, supported shader/mapping subsets and unknown coverage remain explicit. Production seams, complex shaders/UDIM/sequence/group graphs, rig/morph/NLA cases, complete contacts and native runtime behavior need their own evidence.
- Frame sampling restores the documented transform, numeric custom-property and local shape channels; arbitrary animated scene RNA and custom handlers are outside that snapshot. Use owned jobs for unfamiliar production files.
- Hashes, file dimensions, density, render comparisons and structural pass states never grant license ownership, reference fidelity, artist approval, native import/placement or runtime performance acceptance.

The [roadmap](roadmap.md) retains production-character refinement, final benchmark
comparisons, native Sundown pilots, pinned runtime measurements and production
1.0 acceptance. Native-editor authorization is still pending. No full visual
sidebar-layout review has been performed. Blender's `use_nodes` deprecation
warnings concern a future unsupported major version, not a verified 6.0 migration.

## Reproduce

```powershell
uv sync --frozen --python 3.11
uv run --frozen python scripts/check.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --previous-zip dist/framewright_studio-0.6.0.zip --receipt artifacts/verification/new-run.json
```

The runner includes Python checks, memory/color host tests, every Blender suite listed
in `scripts/check.py`, manifest
and ZIP validation/build, source-byte audit, isolated installation/lifecycle and
batch/worker checks. Its receipt records executed commands and exit status even
when a later check fails, and refuses completion if tested source/config changes.
The expensive review-kit/full-8K/pilot generation is
separate; exact scripts and retained settings are linked in the evidence records.
