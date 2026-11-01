# Physical normal-bake projection distances

Normal baking now treats `ray_distance` as metres independently of the authoring
scene's unit scale. High, low and optional cage copies enter an isolated one-metre
staging scene; the retained low derivative returns to the source's original world
placement and mesh coordinates. Source objects, scene units and authored controls
remain unchanged. The request schema and image-memory admission budget are unchanged.

## Reproduction and correction

The initial independent unit tests found a distant high surface falsely passing a
5 cm projection request in a scene with 10 metres per Blender unit. Converting the
staging world matrices fixed that distance error and explicit cages, but implicit
cages still produced flat normals at scene scales 0.01 and 10. The same physical
tilted plane failed with low-object uniform scales 0.2 and 3: its normal map differed
from the reference by 0.009988 in a channel.

Actual Cycles tests confirmed that cage extrusion uses the low object's **local**
coordinates. The implicit extrusion is now the requested metre distance divided
by the product of source scene scale and uniform low-world scale. Maximum ray
length remains twice the requested distance in the metre staging scene. Explicit
cages supply their own origins and do not use implicit extrusion.

Returned `unit_conversion` metadata records source/staging units, the physical
projection/ray lengths and the local implicit extrusion, or `null` for an explicit
cage. Flat valid maps remain possible for truly flat surfaces; the existing
`detail_present` observation is separate from normal-vector validity.

## Supported transform boundary

- Implicit cages require positive, uniform low-object world scale. A single local
  extrusion cannot represent one physical distance under arbitrary nonuniform scale.
- An explicit topology-matched cage supports nonuniform scale. The test uses a
  nonuniform low transform in a 0.01-unit scene and reconstructs the expected world
  normal from the actual baked tangent pixel.
- All bake sources must have finite, nonsingular world transforms without shear.
  Detaching a sheared parent hierarchy into ordinary location/rotation/scale copies
  would change geometry. Preview and apply therefore refuse it before staging,
  with an instruction to apply transforms on a separate derivative.
- Blender's local extrusion limit is checked before allocating the bake stage.

These checks do not establish every texel's correspondence, arbitrary cage quality,
native shader parity or artistic acceptance. The existing at-most-256 centroid ray
check, UV checks, memory scope and other limits remain explicit.

## Evidence

The expanded red run had 13 failures in six test methods, covering uniform object
scale, scene units, unsupported implicit nonuniform scale and sheared worlds.
The final unit suite has **seven passing tests**, including singular/reflected
implicit boundaries, exact source preservation and failure cleanup. Nine existing
bake tests and three independent preservation tests also pass. Tests use owned
background Blender 5.2.1 LTS processes with autoexec disabled.

Logs: [initial unit red](../artifacts/bake-units-red.log),
[partial staging fix](../artifacts/bake-units-green.log),
[scale/shear red](../artifacts/bake-units-scale-red.log),
[final unit green](../artifacts/bake-units-final-green.log),
[existing nine tests](../artifacts/bake-units-existing-green.log),
[preservation three tests](../artifacts/bake-units-preservation-green.log).

The [curved bake regression](../artifacts/curved-bake/20261030T194054Z-b3924af8/index.html)
also passes against the final baker. All five actual images were inspected.
The healthy interior RGB MAE is 0.00191530 and seam-strip MAE is 0.000493827;
removed-normal and deliberately damaged-seam controls fail the same fixture gates.
The cold reopened packed map reproduces the central rendered pixels exactly
(MAE and maximum difference zero), with an unchanged source fingerprint.
See the [receipt](../artifacts/curved-bake/20261030T194054Z-b3924af8/report.json)
and [curved fixture limits](increment11-curved-bake.md).

The unit-fix baker SHA256 was
`0fa9bfc1747702b80adc021613378c0793a7c488cf2c0615073ba2c6c35a5cd1`.
The saved curved `.blend` SHA256 is
`67206d450c16aec32199a132b14be614cd91f4381cafbc0805b7497b4f2b2d9f`.
This is 20 relevant passing test methods in four suites, including the rendered
curved/cold test. It is bounded technical evidence, not production asset approval.

## Subsequent material-assignment audit

The combined unit-boundary audit reproduced two output defects on a low mesh with
two surface slots. Clearing the copied mesh's slots reset face material indices
from `[0, 1]` to `[0, 0]`. Reading only its data slots also replaced an effective
green `OBJECT`-linked material with the red data-slot material underneath it. Both
operations reported success while changing the returned derivative's appearance.
The authored source mesh and its existing image stayed unchanged in the probe.

The baker now captures effective slot materials, `OBJECT`/`DATA` link modes and
face indices before rebuilding its owned slots. It uses independent materials and
restores the face assignments before baking. Source image pixels, material
identities and source face indices remain unchanged. This concerns effective
surface assignments; it does not promise to preserve unused data-slot fallback
materials underneath object overrides.

The three-test independent suite also catches the omitted-parent shear defect
described in the [construction record](increment11-cabinet-construction.md).
It failed all three tests before these fixes, then passed. All 65 related prior
unit/construction/material/preservation tests passed against the updated modules.
Logs: [independent red](../artifacts/final-unit-review-red.log),
[independent green](../artifacts/final-unit-review-first-green.log),
[bake units](../artifacts/final-review-bake-units.log),
[bake preservation](../artifacts/final-review-bake-preservation.log),
and [existing bake suite](../artifacts/final-review-baking.log).

The post-audit baker SHA256 is
`53592331c2449b9c76c23ad1db5c4fec29705c3a4890a94254aec1f8098323a3`.

## Native data-driver dependency boundary

A further independent probe confirmed that an FCurve stored on a source Mesh,
Material or ShaderNodeTree can traverse an ID-valued custom property and write an
unrelated object's location. Native drivers performed that write during both
preview and real baking with script autoexec disabled and no registered callbacks.
The same material-driver effect occurred during review-scene creation.

The shared `static_data.py` preflight now checks source mesh/shape-key data,
effective and underlying material slots, node trees and nested shader groups
before evaluated UV inspection or review allocation. Any animation data, including
ordinary actions and native drivers, is refused. The traversal is cycle-safe and
bounded to 4,096 distinct datablocks and 65,536 shader nodes. It reads the source;
it does not remove or disable actions/drivers. Static nested shader groups remain
supported. This is a declared dependency-admission policy, not an arbitrary-code
or whole-filesystem sandbox.

`test_bake_dependency_review.py` initially recorded 14 failing observations, then
passed all nine methods: six direct driver preview/apply cases, nested group
refusal, ordinary animated high/low/cage Mesh refusal, and a real static-group bake.
Exact external/source state and allocation inventories remain unchanged on refusal.
The final unit-review suite now has four passing methods, including the same
external-writing material driver on review preview/apply. All 65 relevant prior
tests pass again against these final modules.

Evidence: [independent dependency red](../artifacts/production-corpus-study/bake-dependency-review-red.log),
[independent green](../artifacts/production-corpus-study/bake-dependency-review-green.log),
[review dependency red](../artifacts/final-unit-review-dependency-red.log),
[review dependency green](../artifacts/final-unit-review-dependency-green.log).
The final targeted regression logs use the `artifacts/final-static-` prefix.

Final baker SHA256:
`bb05b90f210a689bd1a64524fb3d96dc3c6270a085eb7e42bf5f30b72d928fb5`.
Shared admission helper SHA256:
`643ddf290bd7462edf1b2a7a0464a5a86ede3fe4c0c84ac073741fb527b6d58b`.
The complete release aggregate remains the authority for selected final package
and rendered artifact receipts; earlier render runs above retain their exact hashes.
