# Framewright Studio roadmap

**Retained scope, user decision November 5, 2026:** asset checks; source
protection and isolated jobs; export and baking utilities. Broader modeling,
character and AAA/studio-parity work remains inactive. The board below retains
historical implementation/evidence states; its broader unfinished rows are not
completion requirements for the retained toolkit. No code or release files were
removed by this scope decision. Development remains paused.

Owner: Blake. Started 2026-10-30. **Development is paused at the user's request** while the separate scratch-built Nimitz cinematic is developed; its current visual draft is not accepted as photorealistic. The verified 0.9 engineering preview passes 84 stages, 71 Blender suites and all 830 latest-host Python cases across the initial run and focused setup rechecks. The original target was independently reviewed AAA production quality with configurable cinematic/8K and real-time budgets. Sundown's development art is not the benchmark.

**Scope correction, 2026-11-01:** this project is strictly a Blender plug-in.
Unreal/Sundown work (FW-070–073) is deferred and excluded from completion gates.
Do not resume engine testing using the earlier approval. Preserve historical
experiments; no additional native integration is required for this release.
Historical board: 21 Done, 16 Partial, one Pending; four destination rows Deferred.

**Verified 0.8 increment:** shared procedural-to-PBR atlas baking and cold hidden-object review.
The separate native static adapter has passing offline contracts. The atlas command has 61 pure/schema
checks; review preservation/workflow has nine Blender checks plus 24 existing regressions.
The [1024 cabinet pilot](increment16-material-atlas.md) now passes gated source→atlas
and cold Blender/GLB/FBX comparisons, including the white-loss negative control.
The [actual 8K atlas run](increment16-material-atlas.md) also passes, including four
8192² map-role audits after each cold import; its 19.9-minute worker peaks at 16.39 GiB
working memory. Native admission budgets pass against the 325 MB GLB; PBR metadata/
readback contracts and a disposable engine fixture were prepared at that checkpoint.
All 82 aggregate stages and both 812-test Python matrices pass on the same 208 source/config
files. Subsequent isolated Unreal import and cold settings checks now pass with a
separate repaired adapter; no artistic or Sundown integration acceptance is claimed.
Surface and rejected knee research remain separate from the verified package.

**Verified 0.9 increment:** configurable atlas spatial sampling, bounded FBX object aliases
and cold-hidden static export transforms pass the combined 84-stage aggregate,
71 Blender suites and both 830-test Python matrices. The refined 1K public handoff
also passes. Default-16 8K measurement (41.26 minutes), evidence retention and single
latest-host Python 3.15.2 validation are complete. Promotion and the 281-file source
checkpoint are sealed; these checks do not close the production/artistic rows below.

An artist or AI agent should inspect an asset, identify a concrete defect, propose a bounded change, retain the source, review an editable derivative and deliver reproducible handoff evidence. Technical validity, reference fidelity, deformation/motion, Blender export/reimport parity, rendered appearance and Blender performance are independent gates. Neither a numeric score nor texture resolution grants artistic acceptance.

**Value review, 2026-11-05:** the [usefulness audit](library-value-audit-20261105.md)
records attribution, visual-gate, compatibility and durability findings F24–F28.
It recommends preserving narrow utilities and keeping broader development paused
until an equivalent-task comparison shows benefit. These findings do not open
new implementation tasks or promote any incomplete production row.

## Delivery and status

Delivery proceeds through foundation → diagnostics → bounded repairs → modeling/surfaces → rigging/animation → scene review → AI orchestration → Blender production review → production release. Use small test-first increments and keep at most one writer per shared scene.

**Done** means the stated bounded engineering scope has passing evidence. **Partial** means working code exists but part of the original deliverable or acceptance remains. **Active** means integration or validation is underway. **Pending** means the stated outcome has no completed evidence. **Deferred** means outside the current Blender-only scope and excluded from its completion requirements. These labels do not imply full AAA, character, engine or release acceptance. Current evidence is in [verification](verification.md) and linked increment records.

| ID | State | Implemented and verified scope | Remaining work / acceptance |
|---|---|---|---|
| FW-001 | Done | Repository, extension metadata, development tools and verified 0.9 package | Production acceptance is separate under FW-083 |
| FW-002 | Done | Frozen pure-Python snapshot/report models, independent of Blender | Broader models require new contracts/tests |
| FW-003 | Done | Scene capture and preflight panel; context/source preservation fixtures | Visual panel usability review remains separate |
| FW-004 | Done | Structural mesh/rig/animation/lighting rules with stable findings | Findings do not certify visual quality |
| FW-005 | Done | Versioned commands, discovery, typed validation, explicit effects | Continue command/schema regression coverage |
| FW-006 | Done | Preview and source-preserving loose-vertex derivative | Deliberately restricted static-mesh repair |
| FW-007 | Done | Isolated harness; 71 Blender suites and actual lifecycle passed in the unchanged-source 0.9 aggregate | New changes require relevant checks and a new package receipt |
| FW-008 | Partial | Independent human/material references plus authored CC0 cabinet, provenance, rubric, editable review kits and rendered views | Final reference selection, architecture/character/motion/calibrated-lighting benchmarks and artistic acceptance |
| FW-009 | Done | Six flexible profiles and per-request texture/budget overrides | No upsampling or automatic art approval |
| FW-010 | Done | UUID manifests, hashes, recipes, license/origin metadata, lineage and independent states | Caller evidence is recorded, not certified |
| FW-011 | Done | Evaluated topology, duplicate/degenerate faces and bounded intersection checks | Current-frame/sampled limits are explicit |
| FW-012 | Done | Bounded UV/material diagnostics and world-space, unit-aware texel density for direct supported image mapping | UDIM/sequence/group/mapped-coordinate density remains unknown; no universal density or art pass |
| FW-013 | Done | Plan/apply/cancel/rollback, stale fingerprints, exact owned derivative checks | Tokens and rollback authority are process-local; restart recovery is unsupported |
| FW-014 | Partial | Bounded jobs; geometry/rig/instance timing; actual 8K material memory; 15 fresh retained-cabinet/human workers with timings, OS memory and recorded background load | Broader production workloads, UI responsiveness and Blender performance; synchronous Blender work is not interruptible |
| FW-020 | Partial | Original-path/hash intake, view labels, authored landmarks and general local HTML reference boards | Complete benchmark views, scale/material evidence and approved reference selection |
| FW-021 | Partial | Editable cabinet/facade builders; corrected hinge axis, panel seats and thin-board clearance; physical units and owned review scenes; authored reference and rendered fixtures | Refine joinery/materials and representative asset acceptance |
| FW-022 | Partial | Actual normal baking/cages and shared multipart PBR atlas baking; physical UV guards, exact preservation, normal sampling, six measured 8K normal workers, actual 8K atlas/cold-map evidence and [declared mip-padding/packing checks](atlas-mip-padding.md) plus [literal material preservation](atlas-material-constants.md) | Broader production seams/cages, complete bake efficiency and artist acceptance; CPU atlas bake remains lengthy |
| FW-023 | Partial | Static LOD/collision derivatives with [closed point-only convex hulls](native-derivative-handoff.md); bidirectional bounded distances catch a missing fin despite equal bounds; 13 silhouette/shadow views and exact source preservation | Posed silhouettes, Blender LOD previews, production thin features/shadows and Blender contact review |
| FW-030 | Partial | Explicit landmark metarig fit, stock Rigify and automatic heat binding on copies; provisional human derivative | Artist-reviewed fit/rolls/weights, project skeleton profiles and production rest/units acceptance |
| FW-031 | Done | Scoped deform-weight normalization with locks/protected regions and unresolved conflicts | Production deformation acceptance is FW-032 |
| FW-032 | Partial | Corrective tools and retained source-preserving evidence; [complete buffered folds](blender-knee-backtracking.md): four focused regressions, all 1,336 affected quads retained, 16 actual captures verify 11.9% lower worst contact deficit; 20 contact failures remain (worst deficit 0.1010 mm) | Continue contact repair within the existing measured range, retaining full fold coverage, buffer, correction benefit, movement limits and unchanged final clearance. Full 73-pose/contact/stretch/protected/halo/cold/visual/public-command gates, underarm/hip compression, broader poses, Blender morph handoff and artist acceptance remain |
| FW-033 | Partial | Exact collider scope, actual pinned cloth/collision simulation, public isolated cloth bake and cold embedded-cache playback; stock full Rigify finger/hand/face controls tested | Authored character hands/face/gaze/grips, garment/hair behavior and artistic review |
| FW-040 | Done | Layered actions/slots, NLA timing/ownership and FPS metadata inspection | Supported Blender version only |
| FW-041 | Partial | Rigid/skin markers, sampled triangle-region relations and explicit evaluated vertex/group region authoring; reviewed graph/topology/budget guards; human descriptions/inspection cold round trips and ridge control | Broader motion/grips, full-foot/volume/continuous collision, artistic review and Blender playback; no anatomical inference |
| FW-042 | Partial | Coupled retarget/bake/rebound skin handoff; 97-sample bone-and-shape cold parity; adaptive endpoint B-Bone conversion, explicit export substeps and 361-sample prepared human low-cage transport | Complete human Multires/correctives, authored motion/contact acceptance and Blender clip playback |
| FW-043 | Partial | Basis-relative correctives and detached active-slot location-spike cleanup | Broader mocap corpus, layer workflows and artist-reviewed improvement without regressions |
| FW-050 | Done | Scoped GLB/FBX exports; cold geometry/UV/pivot/skin/motion and bounded rendered material parity in both formats | Broader shader/rig export and Blender reimport cases remain separate gates |
| FW-051 | Partial | Four-camera review scenes; actual decoded 8192² PNG; controlled linear/HDR/Standard/AgX exposure fixture with cold verification | Physical lighting/display calibration, full-resolution visual inspection and accepted lighting/artwork |
| FW-052 | Partial | PBR recipes, actual 8K handoff, bounded EXR data intake/container checks, explicit FBX scalar staging, authored four-map 4K cabinet cold views and controlled interior/glass renders | Complete reference fidelity, broader Blender lighting and accepted art-light targets |
| FW-053 | Partial | Evaluated mesh components from mesh/converted sources, actual instance counts, generated materials/images, explicit unmeasured components and LOD coverage; original carrier scene now passes with source preserved | Blender viewport/render residency, draw calls, CPU/GPU counters and representative budget approval |
| FW-060 | Done | Allowlisted workflows, strict response gates, output bindings, replay/partial-failure receipts and preview | Replay cache is process-local; workflows are not atomic; artistic gates cannot be inferred |
| FW-061 | Done | Owned workers, deadlines/cancel, supplied-plan/replay providers and explicit worker-only stock Rigify opt-in | Explicit retry only; no cloud provider, credentials or automatic model generation |
| FW-062 | Partial | Eight-case structural corpus plus two pinned retained assets/five operation groups, missing-UV/penetration controls, three-repeat timings and source hashes; repair ranking and explicit cost semantics | Broader production/provider corpus and independent artistic labels |
| FW-063 | Done | Strict MCP stdio, bounded responses, scoped absolute paths and file-binding checks | OS-owned pipe trust; no network listener, arbitrary script tool or filesystem sandbox |
| FW-070 | Deferred | Destination contract, hashed GLB/PBR compiler; [native fixes integrated](native-runtime-integration.md) in the unreleased checkout with 204 affected host cases and identical code to the actual isolated UE 5.8.3 warm/cold settings run; [two-view native base-color checks](native-appearance-review.md) pass with loss controls; [surface diagnostics](native-surface-review.md) verify bounded roughness and isolate mip-dependent metal error; [constant-preserving 1K pilot](atlas-material-constants.md) passes cold GLB/native metallic comparison with loss control; [owned texture readiness](native-texture-readiness.md) resolves actual cold placeholders without a global barrier; [six-region normal transport](native-normal-validation.md) passes atlas/direct exports with sensitive controls; [full-precision native import](native-uv-precision.md) preserves all corner attributes/both UVs across 5,836 triangles in fresh/cold readback | Linked-map minification, broader normal corpus, shader/GPU readiness, lighting/fine edges, broader geometry, collision/LOD and destination placement; Sundown unchanged |
| FW-071 | Deferred | Static pilot sequence documented; no game asset changed | Owned static asset, native Journey placement, matched 1/5/25 m day/dusk/contact/access evidence |
| FW-072 | Deferred | Original character intake and provisional Blender rig retained; no native pilot | Accepted static pilot plus reviewed rig/clip, skeleton identity and full native motion review |
| FW-073 | Deferred | Blender timings and whole-process memory baseline available | Pin game build/hardware/resolution and measure native CPU/GPU/memory/streaming/temporal behavior |
| FW-080 | Done | Windows/Blender 5.2.1; latest standalone Python 3.15.2 passes all 830 candidate cases across the initial run and focused rechecks | One standalone host target; the actual bundled Blender runtime remains required. Remote CI remains unverified |
| FW-081 | Done | Transactional registration, saved-state handling and final 0.8→0.9→0.8→0.9 installed lifecycle passed | Cross-process repair authority recovery remains unsupported |
| FW-082 | Done | Verified GPL 0.9 preview: 84 stages on 210 unchanged files, latest-host validation, package byte audit and sealed 281-file Git source archive | Later code changes require a new verified release; production 1.0 is FW-083 |
| FW-083 | Pending | Acceptance rubric and independent gate model | Artist acceptance, Blender performance targets, issue triage and support ownership; production 1.0 is not claimed |

## Historical followups (inactive)

These earlier priorities are retained for context, not queued for execution.

| Priority / dependency | Next bounded outcome | Required evidence |
|---|---|---|
| 1 — FW-021/022/050/052; bounded atlas transport correction complete | Refine source material fidelity and baking efficiency while retaining the verified 1K/8K transport behavior | Matched source/reference views, material-scale/UV/source preservation, measured performance and unchanged cold handoff gates; visual acceptance remains separate |
| 2 — FW-030/032/043; retained failed knee studies | The old candidate remains rejected. Opposing constraints on the connected near-contact patch dominate the witness; repair or consistently constrain that patch, reusing the measured maps and exact row identities | Pin actual pair identities and 73 samples; a lower crossing count must still fail if new crossing identities appear. Preserve support/halo, disabled-key control, cold reproduction and matched visual evidence |
| 3 — FW-041; region authoring and human round trips implemented | Extend declared motion/grip coverage using the existing describe→inspect workflow | Author explicit intended regions/interactions, retain uncovered facts and topology pins, include missing-contact/penetration controls and sampled/cold evidence; no full-foot or continuous clearance claim |
| 4 — FW-008/020/021/022/052; reference selection first | Refine one cabinet/facade and production surface against approved references | Complete views/scale/provenance, editable details, seam/curvature/material comparisons and artist review; retain current fixtures |
| 5 — FW-030–033/042/043; after corrected body fit | Add authored hand/face/eye controls, protected corrective shapes and representative motion | Named intended behaviors, joint/contact failure controls, reversible derivatives, cold handoff and artist-reviewed improvement |
| 6 — FW-014/062; representative assets from preceding rows | Expand technical corpus and performance evidence | Versioned cases, preserved-source hashes, expected failures, repeated timings, actual cost or unknown, texture/rig/instance workload coverage |

If development is resumed, choose a bounded defect within the retained Blender
utility scope, write its failing check, fix it and inspect the result.
Reuse existing exports and renders; do not rerun full suites or 8K bakes without a
milestone or concrete regression. Earlier engine findings remain historical under
FW-070–073 and do not block Blender delivery. The native derivative assignment
candidate remains unpromoted in the task workspace after the scope correction.

The install recommendation is the verified 0.9 engineering preview. Its final
84-stage aggregate and latest-host validation pass; earlier releases remain
historical evidence. The resource-reporting and bounded atlas transport corrections are complete. Later rows
retain production acceptance; completing a small fixture does not close their full scope.
Material assignment, marker contacts, controlled color calibration,
coupled animation, rendered parity, LOD accounting, process memory, reference boards
and the 0.2 release have passed their recorded checks and should not be reimplemented.
New 0.3 evidence: [cloth command](increment9-cloth-bake-command.md),
[continuous correctives](increment7-corrective-activation.md),
[full stock Rigify](increment7-full-human-rigify.md),
[bidirectional LOD](increment7-bidirectional-lod.md),
[spatial PBR handoff](increment9-material-handoff.md) and
[8K process memory](texture-performance.md) and [actual 8K handoff](8k-handoff.md).

The [WorkshopCabinet offline handoff](../artifacts/sundown-handoff/WorkshopCabinet-reviewed-inputs.json) is prepared from the actual review kit. Its 22 test-first Python checks reject stale/mixed evidence, paths outside the kit, source/target writes and output replacement. It records a proposed new owned package identity, not a reserved/imported asset. Earlier cold-check reports are hashed and retained as claims, not reexecuted or promoted to art/native approval.

Cross-process repair recovery, full UDIM/sequence/group-graph support, arbitrary generated models and broad cloud providers are unsupported extensions, not implied by the current bounded features. They need separate scope and acceptance before being advertised.

The 0.4 increment adds [coupled morph handoff](increment8-morph-handoff.md),
[evaluated skin contacts](increment10-skin-contacts.md),
[interior/glass fixtures](increment10-interior-glass.md), and
[EXR intake with actual cabinet handoff](increment10-exr-intake.md).
Independent regressions cover truncated EXR payloads, global callbacks, invalid
sampled drivers, dependency topology/budget escape and shared-data remapping.
Its final package aggregate passed on unchanged sources and is retained as history.
The newer 0.5 checkpoint below extends B-Bone transport and editable construction.

The verified 0.5 slices cover the cabinet's measured hinge/panel
construction defects, B-Bone endpoint baking and fractional export sampling,
representative production-corpus measurements, and
[curved bake/source-preservation review](increment11-curved-bake.md).
The [retained-asset corpus](increment11-production-corpus.md) has 25 host and
eight Blender tests plus 15 passing measured workers. The
[cabinet construction study](increment11-cabinet-construction.md) fixes the measured
hinge/panel/clearance defects and preserves physical dimensions across scene units.
The [bake unit review](increment11-bake-units.md) also corrects physical projection
distances and refuses transforms that cannot preserve the requested cage distance.
The original source assets and earlier packages remain retained. Every slice has
passing failure controls and the combined 70-stage release receipt.
The first aggregate was interrupted for material-assignment and detached-shear
regressions. Follow-up dependency checks found unrelated-ID writes in normal and
shape baking; the final aggregate includes their passing corrections.
The verified 0.6 checkpoint adds [regional-contact tests and human evidence](increment12-regional-contacts.md)
and [chunked normal inspection](increment12-normal-inspection.md). Six actual 8K
workers measured median inspection time of 55.09 → 3.38 seconds with exact results
and unchanged pixels; this is not a whole-bake speed claim. Independent regional
precision/source reviews and the combined 73-stage release passed. Its following
region-authoring and knee-contour slices are recorded below; the existing
marker/ridge and failed deformation controls remain retained.

The 0.7 preview implements [`contacts.describe_region`](increment13-region-authoring.md):
explicit evaluated indices or named groups, deterministic all-three membership,
topology pins, complete uncovered facts, admission/transport limits and isolated
source preservation. Four public human descriptions and two complete 121-sample
inspections reproduce after cold reopening. The earlier aggregate passed 75 stages,
582 host tests and 62 Blender suites with 186 unchanged source/config files. The
final resource increment adds 19 Blender cases and passes 77 stages with 188
unchanged files; see [verification](verification.md). Neither grants art/native acceptance.

The separate [left-knee study](../artifacts/knee-contour-study/20261030T204835Z-a14df1de/readme.md)
retains six variants and two finalists at 110°/130°. Both finalists fail the intended
no-added-crossing guard: lower totals conceal five new pair identities across seven
of 73 sampled states per finalist, involving fixed-boundary triangles. Some matched
views improve the terminal puncture, but the raised lip and genuine new crossings
prevent geometry acceptance. Source/protected-region/cold evidence does not erase
that failure. No knee candidate was promoted.

The [causal diagnosis](../artifacts/knee-boundary-causality-20261030/README.md)
reproduces every new crossing identity and confirms a fixed-pose activation failure.
The [constrained support study](../artifacts/knee-constrained-support-20261030/README.md)
passes nine host tests and 32 native map controls (maximum 0.725 micrometres), but
its single bounded solve fails. Thirteen affine constraints cannot fit the chosen
trust box; this is not a proof that native geometry cannot be corrected. No new
asset or render was accepted. Source files, protected geometry and pinned runtime
remain unchanged; subsequent studies retain the full existing gates.

The [direct-native trial](../artifacts/knee-native-correction-20261030/README.md)
tested 32 vectors/140 captures and retained four new crossing occurrences. The
[expanded-support trial](../artifacts/knee-support-band-20261030/README.md) tested
64 vectors/268 captures, expanding the movable band from 23 to 36 vertices with
a new fixed outer ring. Its best result clears the 95°/110°/120° new crossings but
retains three at 130°. Both failed their first geometry gate; no new asset,
73-state acceptance, cold validation or rendered approval followed. The source
files remained unchanged. Copies and original hashes are retained in the
[0.8 evidence receipt](../artifacts/evidence-retention-0.8.json).

At that checkpoint, development resumed after Blue Horizon with FW-053. The
[pause findings](paused-scene-findings.md) preserve the curve/text reporting failure
and the artwork's temporary converted-mesh workaround. The
[resource correction](increment14-resource-accounting.md) passes on the unchanged
editable scene at two frames, reporting 458,951 evaluated triangles without conversion.

## External acceptance and conditional integration

Independent artistic approval cannot be manufactured by tests. A complete benchmark suite still needs accepted final surfaces, motion and lighting; the available anatomy reference alone is insufficient. License/source evidence is retained, including the reference bundle's inconsistent embedded license texts.

The selected human corrective study is a provisional technical improvement, with
corrected anatomical pose targets and fewer sampled intersections. Underarm/hip
compression and knee pinching remain visible; the knee is not resolved. A full 8K
output and real 8K maps exist, but resolution, density, complete weights and technical
parity do not establish final art quality.

Sundown/Unreal adoption is deferred. The task has not imported or placed assets
in the game. Existing destination contracts and engine evidence are retained for
a possible separately requested project; they impose no active Blender release
requirements. Other OS/Blender support requires execution in those environments.

## Agile working agreement

- Ready: name the source/owned output, failing behavior, supported subset, budgets, dependencies and measurable acceptance; secure any required external approval before the dependent action.
- Done for an increment: relevant tests and preservation/failure controls pass, actual outputs are inspectable, limits and receipts are recorded, and README/task status reflect the bounded result. Artistic acceptance stays open until that specific evidence exists; deferred engine gates do not block this scope.
- Select a bounded failure/outcome with clear ownership and acceptance; write the failing test first, implement, then refactor and run relevant checks.
- Use pure Python for contracts, isolated Blender for data/API semantics, rendered review for visual outcomes and measured Blender workloads for performance claims.
- Include malformed/unsupported/linked/shared inputs, stale plans, failure cleanup and exact source preservation. Passing sampled work must retain its omissions.
- Demo each slice with a fixture and representative owned asset where available. Update README briefly, this task board and the relevant evidence record.
- Keep original sources and earlier evidence. Do not silently treat newer generated output as the accepted production asset.
- Measure before optimizing. Separate extraction, rule evaluation, I/O, Python allocations, native memory and GPU/runtime counters; avoid universal triangle/texture/FPS thresholds.

The verified 0.9 release is an engineering preview. It does not replace artists, certify studio parity or imply that all roadmap acceptance is complete.
