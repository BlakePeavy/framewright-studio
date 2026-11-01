# Explicit evaluated region authoring

`contacts.describe_region` closes the selection-to-inspection gap without requiring
caller Python. It describes finite evaluated topology and explicit membership at
one requested time. It does not infer anatomy, test triangle area or collisions,
or certify artistic, volume, continuous-time or native-engine acceptance.

Supply exact `object_name`, caller `region_id` and finite `sample_time`, plus exactly
one of:

- `vertex_indices`: 3–65,536 distinct **evaluated** vertex identities. Input order
  does not affect the result; duplicate/boolean/out-of-range indices refuse.
- `vertex_group`: exact case-sensitive name. Membership is evaluated deform weight
  strictly greater than zero. Zero weight is excluded; no threshold is guessed.

The result's `region` can be passed unchanged into
`contacts.inspect_regions.params.regions`. Each emitted loop triangle must have
all three evaluated vertices selected. Ordered triples and ascending loop-triangle
indices are retained; no adjacent-face expansion, hole filling, position remapping
or polygon-fan approximation occurs. Complete sorted selected/uncovered vertex
lists, counts and triangle fraction accompany the region. Empty/no-complete-triangle
selections refuse. `geometric_relations_checked` is explicitly false; a finite
degenerate triangle may be described and then refused by the relation inspector's
own epsilon/geometry requirements.

The [two-step public workflow example](../examples/describe-and-check-region.json)
passes the whole result region through `$ref`. Replace its exact Skin, Ground and
AuthoredSole.L names with the intended authored identities. `dry_run: true` previews
the workflow plan only; `false` executes the two **read-only** commands. This example
does not authorize an anatomical selection or make every aggregate response fit
the transport limit.

## Identity, evaluation and preservation

The optional `expected_topology_sha256` pins a previously obtained selection to
the exact existing evaluated digest: vertex/polygon counts and ordered native
triangle, edge and loop arrays. Without that pin, indices deliberately describe
current evaluated topology at the explicit sample; the command cannot recover
stale caller intent. The digest is a Blender/platform identity, not cross-version
or cross-format geometric equivalence. Coordinates and group membership are not
part of topology identity. Rerun description if changed weights should select a
different region; an emitted explicit region retains its original selection.

Groups are read from the actual evaluated mesh with all data layers preserved.
Source/copy/evaluated group names and indices must agree. Generated subdivision
vertices with positive interpolated weights are included. Missing layer/membership,
nonfinite/out-of-range weights or invalid deform indices refuse; there is no
control-cage fallback. The same temporary mesh supplies geometry, digest and group
entries and is cleared in the shared `finally` path.

The existing isolated dependency closure and regional graph admission are reused:
main thread, Object Mode, local independent mesh/armature/empty IDs, selected active
action slots and admitted native drivers/constraints/modifiers. NLA, ambiguous shared
data, global frame/depsgraph handlers, unsafe/external RNA paths and unsupported
topology animation refuse. Only the owned scene advances. The report distinguishes
requested time from Blender's actual frame/subframe/effective time and records
source FPS/base and unit scale. Original time, dirty channels, selection/active
object, UVs, materials, weights/groups, keys and actions remain unchanged; no
persistent Blender IDs or files are retained by the command.

## Resource and transport bounds

Defaults are 250,000 evaluated vertices, 100,000 evaluated triangles, 4,096 selected
triangles and two million group entries. Hard maxima are one million evaluated
vertices, 500,000 evaluated triangles, 16,384 selected triangles, 65,536 selected
vertices and two million group entries. Vertex/triangle/work limits span **all**
copied mesh dependencies; `max_group_entries` counts every examined evaluated
membership entry on the **selected mesh**, including memberships in other groups.
Entries are counted before membership traversal. The inherited closure also keeps
64-object, 4,096-bone, two-million shape-point and 200-million geometry-element
admission limits. Native geometry evaluation itself is not an OS memory/time guarantee.

Known source triangle excess refuses before copying. Remaining evaluated triangle
budget is checked immediately after native triangulation, before coordinate/index
arrays and the group extraction hook. Empty unselected mesh transform dependencies
remain valid; the selected mesh must have triangle geometry. No manifest is truncated
to satisfy a triangle, vertex, membership or output bound.

Final response admission constructs the actual completed-worker poll shape, full
API response and MCP result containing both canonical JSON text and structured
content, plus modern metadata, JSON-RPC and newline encoding. Real MCP server/stdio
tests verify the encoded byte count and complete report round-trip. Raw JSON must
fit 1 MiB, and the complete duplicated poll envelope must independently fit 1 MiB.
Duplication imposes the stricter effective raw limit; no fixed 768 KiB allowance
is used.

This guarantee is scoped to **one completed command** with a UUID job ID, worker
directory up to 32,768 characters, API request ID up to 128 printable Unicode
characters, and RPC string ID up to 128 characters or a signed 64-bit integer.
Conservative escaping placeholders bound serialization and are never used as paths.
Arbitrary larger external metadata or nested/multi-step workflow aggregation is
not covered; the actual MCP transport still enforces its final 1 MiB limit. Numeric
maxima are independent: a valid complete selection can still exceed the transport
budget and refuse.

## Test-first evidence

- Root's 34 schema cases started with two missing-command failures; 85 related
  schema/API tests then passed.
- The bpy-free authoring module started missing; 16 pure tests and 38 subtests pass
  for validation, deterministic all-three membership, complete uncovered facts,
  topology pins, input preservation and actual double-encoded transport bounds.
- Fifteen actual Blender tests pass after the missing-implementation red. They cover
  exact reusable manifests, Armature/Subsurf/Multires evaluated group membership,
  generated vertices, actual NaN/invalid-index deform corruption, shape-driven
  triangulation, fractional time, source preservation, complete dependency budgets,
  handler/topology-animation refusal, injected cleanup failures, finite degeneracy,
  actual MCP encoding, cold public response and a real 12,482-triangle oversized
  manifest that refuses without truncation.
- Independent review reproduced two late-admission failures: three base triangles
  with budget two entered copying; 12 evaluated Subsurf triangles with budget three
  reached group extraction. Both now refuse at the first available count. Three
  independent cases pass, including a valid empty unselected mesh dependency.
- Existing regional suites remain green: 17 owned tests plus ten independent tests.

The public workflow test also exposed an existing validator gap: a whole bound
object was replaced with an empty schema placeholder, and a digest string stub was
too short. The parent fix recursively fills required placeholder fields and respects
minimum string length; real bound results still undergo ordinary command validation.
Twelve focused host tests went from 11 failures to all green, including malformed
upstream values and invalid literal siblings refused before target execution.
The first aggregate then caught an MCP pre-submission path-policy regression:
binding a whole filesystem-command parameter object could hide the paths from
that check. The parent corrected the transport guard. Structured region bindings
remain supported; commands with a filesystem path policy must supply explicit
parameters before an MCP job is submitted. The failed aggregate evidence is retained rather
than counted as a successful release.

A separate retained-ZIP probe found the absolute MCP entry only worked when its
enclosing directory was named `framewright`. The installed extension uses manifest
ID `framewright_studio`; the old hardcoded package name failed before discovery.
The parent now derives the package name from the trusted script parent, matching
the existing Blender worker entry. Two new installed-name tests pass without skips,
including an actual owned `scene.inspect` worker, package-version reporting, exact
input hash retention, no derivative save and clean process shutdown. They launch
from an unrelated directory with `PYTHONPATH`/`PYTHONHOME` removed. Probe evidence
is in `artifacts/mcp-package-probe/20261030T210927Z-cf74315c/`; test red/green logs
are `packaged-entry-{red,green}.log` under the authoring-plan evidence directory.

Evidence is under `artifacts/region-authoring-plan/`: schema/pure/workflow red and
green logs, `blender-red.log`, `blender-green.log`,
`independent-admission-{red,final-green}.log` and final regression logs. Schema,
workflow and pure-test counts overlap related runs and are not summed as a new
release total. The final package receipt is recorded separately by the parent.

## Human round trip

The pilot uses the retained input SHA256
`c51fc18e3216d3ab92dd3be15651cadfcc6612702b9d34d66a4f63d0d9e3e577` and its existing
311 explicitly authored candidate indices per foot. Public description reproduces
the earlier region manifest exactly: 484 left triangles covering 309 vertices,
482 right triangles covering 308 vertices, with uncovered IDs `[5720, 6052]` and
`[587, 919, 1249]`. These remain candidate sole patches, not complete anatomical
coverage. The resulting regions reproduce the complete 121-sample inspection.

Equivalent named groups are authored only on a separate independent copy. Their
public descriptions have the same ordered triangle identities/digest and explicit
new object identity. Cold reopening repeats all four public descriptions and both
complete 121-sample inspections with auto-execution disabled. Original input files,
source state and ID inventory are retained.

The final post-review receipt is
`artifacts/region-authoring-pilot/20261030T210025Z-2447864a/receipt.json`.
It pins eight runtime modules with identical entry/exit hashes, including
`region_description.py` SHA256
`82defc8813969632afe47b3ee459f9969191aed91c3d145eac505f5c96b8394c`
and the backward-compatible shared extraction helper SHA256
`5d2296c4d2a8e8f49bbf98d2b7d89fa64801554aa1ed89e12c0086779a37fa94`.
The separate `owned-human-groups.blend` has SHA256
`c9339f54209c509e1e6d2997bbde1a54a7da8df6f59611771fc1f2c39799eb05`.
The retained original, candidate-index file, manifest and earlier complete contact
report all retain their original hashes. The exact 121-sample report remains zero
crossings, 145 touches and 83,926 proximity pairs; authoring does not imply a new
collision result. Earlier pilot folders precede the admission-order fix and are
retained separately. No new visual acceptance is claimed; the existing regional
cutaway overlays describe the same source geometry.
