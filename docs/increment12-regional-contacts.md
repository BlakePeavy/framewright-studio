# Sampled regional triangle contacts

`contacts.inspect_regions` is a read-only Blender command for explicit evaluated
triangle regions against an explicit evaluated mesh surface. The old point-marker
command remains unchanged. This increment closes a demonstrated sampling blind
spot; it does not certify full-foot volume clearance, continuous collision, balance,
artist acceptance or native-engine motion.

## Request and evidence boundary

Supply exact scene object names, a topology SHA256, and ordered loop-triangle
indices/vertex triples for each of 1–8 regions. The digest uses evaluated vertex
and polygon counts plus the ordered triangle, edge and loop arrays. Every copied
dependency mesh must retain that topology throughout the requested interval.
Duplicate or overlapping selections on one object refuse. Region selection is
caller-authored; the API does not infer anatomy or repair stale identities.

Every integer frame and requested subdivision is sampled, including both endpoints.
The report retains source FPS, FPS base, effective FPS and physical interval duration;
frame-based inputs are not retimed. A fractional-FPS regression preserves the exact
source frame/subframe and timing settings.
World coordinates use the scene metre scale and evaluated object transforms.
Results distinguish crossing, tolerance-coplanar overlap, edge/point touch,
radius-limited proximity and separation. Counts are triangle pairs per sample,
not counts of anatomical defects. Coplanar overlap is not automatically a defect.
Volume containment is explicitly unchecked.

The command uses the existing isolated dependency-copy closure: native local
actions/drivers and supported modifiers/constraints, with global-handler, foreign
dependency and unsafe RNA-path refusal. Both driver and FCurve validity are checked
at each sample. Original scene time, dirty channels and data remain untouched;
temporary scene/object/mesh/key/armature IDs are removed on success and failure.
The closure is limited to 64 local mesh/armature/empty objects in the active scene,
with independent data blocks. NLA, shared data between dependency objects, simulations,
instances and foreign references refuse. Mesh modifiers are limited to Armature,
Subsurf and Multires; supported local constraints follow the existing contact
sampler's allowlist. The selected active action slot is preserved even when its
action also contains unrelated owners' slots.
Active constraint targets, target bones/vertex groups and bone-parent identities
must exist; native `is_valid` alone is insufficient. Copied/evaluated active
constraints are checked at every sample. Dormant muted/zero-influence constraints
are allowed, but invalid activation refuses. Animated/driven Subsurf or Multires
viewport levels are refused **before copying or sampling**, because post-evaluation
limits cannot prevent an oversized subdivision evaluation. Static admitted levels
0–3 remain supported. The old marker command's scope is unchanged.

Defaults are 512 samples, 250,000 evaluated vertices, 100,000 surface triangles,
4,096 selected triangles, two million broad-phase candidate visits, 200,000 narrow
checks and 100 retained examples. The shared pair budgets span every frame and
region. Exhaustion fails the whole request; no partial result can claim clearance.
Substeps accept 1–8 subdivisions per frame; the sample cap may be explicitly raised
to 4,096. Hard maxima are one million evaluated vertices per sample, 500,000
surface triangles, 16,384 selected triangles total, 50 million candidate visits,
10 million narrow checks and 1,000 examples. Requests must satisfy both their
declared bounds and the shared geometry-work admission limit.
Examples follow sample, region and spatial-sweep order; they are **not severity
ranked**. The cap applies globally. Clients must inspect complete relation counts
and each `examples_truncated` flag, then narrow the query for additional examples.
The retained ridge report has 363 crossings but its first 100 examples contain
95 proximity pairs and five touches, with no crossing example. Absence from the
example list therefore does not establish absence of that relation.
The hard 200-million geometry-work limit counts vertices, three indices per triangle,
two indices per edge, and loops for **every** copied mesh, including the surface and
unselected constraint/driver mesh dependencies. These limits are admission/work
bounds, not a memory or execution-time guarantee.

Distance epsilon defaults to 1 micrometre and proximity radius to 5 mm; both are
explicit engineering settings. The pure predicate also reports its dimensionless
angular threshold, effective radius cutoff and exclusive minimum triangle altitude.
Finite floating-point geometry cannot establish exact-real predicates. A triangle
whose minimum altitude does not exceed the epsilon refuses rather than appearing
clear. The sampler provides no between-sample collision guarantee.

## Test-first evidence

`scripts/test_region_contacts.py` first ran red with the missing implementation.
The existing marker API already passed the fixture's three corner markers over a
ground plane while a narrow vertical ridge crossed the triangle interior. The new
command reports three crossings over its three samples; moving the ridge away
removes them. This is a meaningful negative geometry control.

Seventeen actual Blender tests then pass, including:

- Distinct overlap/touch/proximity/separation and explicit unchecked containment.
- Metre/millimetre and nonuniform transforms on a rotated, translated moving platform.
- Actual shape-key changes to triangulation with unchanged vertex/polygon counts.
- Complete dependency accounting, exact ordered identities, bounds and global example limits.
- Dirty unrelated light/object preservation and injected mid-interval failure cleanup.
- External-ID action/driver path and mid-interval invalid-driver refusal.
- Global-handler refusal before invocation, singular/degenerate refusal, public dispatch,
  negative frames/subframes, fractional FPS and exact cold report reproduction with
  auto-execution disabled.

Logs are retained under `artifacts/region-contact-study/`: `blender-red.log`,
`blender-first-green-attempt.log` and `blender-green.log`. The first integrated
attempt's sole remaining failure was an error-message regex; the geometric refusal
already occurred. No predicate was relaxed to pass it.
The FPS addition has its own `time-basis-red.log` (missing result field) and
`time-basis-green.log`; `final-synthetic-green.log` repeats all 17 against the
numerically reviewed geometry implementation.

Independent `scripts/test_region_contacts_review.py` added four genuine red cases:
missing constraint target, missing target bone, missing bone parent, and an animated
level-4 subdivision hidden by the source's current level 0. Regional-only guards
fix these; ten independent methods now pass. They also verify dormant/activated
constraints, static levels 0–3, frame-driven level refusal before allocation,
selected shared-action slots, degenerate far surfaces and nonfinite unselected
mesh dependencies. Evidence is in `artifacts/region-contact-review/red-final.log`
and `independent-green.log`. No shared marker-helper runtime was changed.

## Retained human candidate

The input remains
`artifacts/human-contact-pilot/20261030T190254Z-94a0cdfa/authored-human-contact.blend`,
SHA256 `c51fc18e3216d3ab92dd3be15651cadfcc6612702b9d34d66a4f63d0d9e3e577`.
Root authored a query from the previously retained 311 candidate vertices per foot:
only triangles whose three vertices belonged to that explicit candidate set were
selected. No new bounding-box/anatomical selection occurs inside the API.

The manifest is retained at
`artifacts/region-contact-study/20261030T201508Z-human-regions-767d7233/`.
It selects 484 left triangles covering 309 vertices and 482 right triangles covering
308 vertices. Five candidate vertices lack a fully selected triangle and remain
explicitly uncovered. These are candidate surface regions, not full-foot coverage.

The first complete owned pilot is
`artifacts/region-contact-study/20261030T201847Z-human-pilot-bd99a089/`.
Across all 121 times, the 966 selected triangles produced zero crossings, 145 touch
pairs and 83,926 proximity pairs at the explicitly inherited 12 mm radius. The
baseline used 233,772 candidate visits and 168,142 narrow checks.

A separate ridge-control surface crosses declared right-region triangle 1476.
Its centre is 58.25 mm in XY from the nearest old right sole marker. It produces
363 crossing pairs, while the ten old markers still report zero penetrations.
Both complete regional reports reproduce exactly after cold reopening the new
candidate with script execution disabled. The original file SHA256 is unchanged.
The saved candidate/report is technical evidence. Three visible 512-pixel Cycles
CPU overlays are retained in `overlays-20261030T202822Z-ff737d2a/` beneath that pilot:
declared soles at frames 1 and 30, and a close-up of ridge/triangle 1476. Blue/green
patches show selected triangles; gray toe/side areas remain visibly excluded;
gold marks triangle 1476 and orange marks the ridge. Ground and geometry above
24 cm are explicitly omitted for the cutaway. Subject alpha coverage is 8.69%,
7.85% and 60.49%; rendered pixels were inspected by the author and independently
by root. This is coverage illustration, not anatomical or artistic approval.
The editable overlay scenes and HTML index are retained, and the candidate file
SHA256 remains unchanged.

The final admission-fixed verification is
`verification-20261030T203844Z-a90b9864/verification.json` beneath the same pilot.
It pins entry/exit hashes for the regional adapter, pure geometry and three shared
dependencies; the regional adapter SHA256 is
`6040b2add0005ca6910973312f5812da71a504b8b3d3761eff467cbe20e8f6c5`.
Both full reports, including 24 FPS and the 2.5-second interval, reproduce exactly
in the fresh disabled-autoexec process. The source state and ID inventory are exact;
the original SHA256 remains `c51fc18…e577`, and the owned candidate remains
`48ddc416a454d33baee69a743b9df18866b95e3968b46ea5bff869f18a98e4e2`.

One instrumented actual-human run per surface observed:

| Work | Baseline | Ridge control |
|---|---:|---:|
| Total command time | 19.9475 s | 20.3785 s |
| Pure pair comparisons, 242 calls | 16.6580 s | 17.0723 s |
| Geometry/driver/constraint/topology capture, 121 calls | 2.8839 s | 2.8887 s |
| Candidate visits | 233,772 | 262,812 |
| Narrow checks | 168,142 | 173,224 |
| Geometry work elements | 19,210,928 | 19,212,743 |

Copy setup/cleanup totalled under 7 ms per command. Frame advancement, admission
and report construction account for the remaining time. These are observations
on the current host with instrumentation, not universal performance guarantees.
Earlier retained verification folders precede the final graph-admission fixes;
the final receipt above identifies the bytes used for the current evidence.

## Remaining authoring interface

The query requires an existing explicit triangle manifest. Current root authoring
uses a retained, inspectable helper outside the shipped runtime. A useful next
read-only command would accept an exact object and caller-supplied vertex indices
or named vertex group at an explicit sample time, then return a bounded ordered
triangle manifest, topology digest, membership policy and uncovered-vertex facts.
That can make the workflow accessible to AI clients without arbitrary Python;
anatomical labeling and artistic region acceptance remain independent.
