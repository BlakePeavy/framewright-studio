# Sampled regional triangle geometry

`region_geometry.py` is the pure-Python geometry half of FW-041 regional contact
inspection. The [Blender adapter and human evidence](increment12-regional-contacts.md)
define source selection, topology identity, isolated evaluation and sampling.
This module receives explicit world-metre triangle coordinates. It neither infers
anatomical regions nor touches Blender, a source file or a game project.

## API and geometric meaning

`triangle_relation(first, second, distance_epsilon_m=1e-6,
proximity_distance_m=0.005)` returns a relation, distance in metres and two closest
world points. A triangle consists of three finite numeric 3D points. The minimum
altitude must be strictly greater than the requested distance epsilon; unresolved
or degenerate geometry refuses instead of appearing clear. Length epsilon accepts
1e-9–1e-3 metres, and the proximity radius accepts epsilon–1 metre.

Coordinates are translated to a pair-local origin and scaled for narrow-phase
calculations. Length and area tolerances have dimensional meaning; the
near-parallel normal threshold is separately dimensionless, `ANGULAR_EPSILON=1e-12`.
That shortcut also requires plane-offset variation across each whole triangle to
stay within the metric epsilon. A tiny angle over a long span can otherwise be a
well-resolved crossing. A computed normal whose vertex-plane residual exceeds
epsilon/4 explicitly refuses numerical conditioning rather than supplying a
possibly false distance. Closest-face calculations use projection and boundary
checks; closest edges use cross-product line parameters, avoiding subtraction of
nearly equal squared-length products for long, thin geometry.
Results distinguish:

- `crossing`: a noncoplanar intersection segment longer than epsilon, with each
  triangle straddling the other's plane beyond epsilon.
- `coplanar_overlap`: near-parallel planes within epsilon and positive projected
  overlap area greater than epsilon squared. This is tolerance-coplanar overlap;
  an actual small plane separation is still reported as a nonzero distance.
- `touch`: point, edge, or another boundary relation within distance epsilon.
- `proximity`: separated boundaries within the requested local radius.
- `separated`: boundaries beyond that local radius.

The radius comparison includes eight representational ULPs of the requested
radius, exposed as `proximity_cutoff_m` by the regional result. Broad-phase event
endpoints round outward and use that same cutoff. This avoids direct-vs-sweep
disagreement at floating-point cutoff boundaries. It is not a physical tolerance
increase or an invitation to tune a candidate into a pass.

These are floating-point boundary predicates, not an exact-real arithmetic proof,
signed penetration depth or a quality score. A closed object wholly inside
another may have no intersecting boundaries; `containment_checked` remains false.
No conclusion about unsampled times, unselected body regions, physical balance,
anatomical correctness or artistic/native acceptance follows from the result.

## Bounded interval traversal

`compare_regions(region_triangles, surface_triangles, budget=PairBudget(...), ...)`
validates all supplied geometry before pair traversal. The input hard bounds are
16,384 regional and 500,000 surface triangles. A sweep over X intervals retains
active triangles and expiration heaps; it does not allocate a cartesian product
or an unbounded BVH-overlap result. Conservative bounding-box distances reject
pairs beyond the local radius before narrow-phase work.

Every X-overlapping candidate visit is charged, including pairs subsequently
rejected on Y/Z. Every narrow triangle query is charged separately. One
`PairBudget` must be shared across every region and sample in the requested
interval. Its defaults are 2,000,000 candidate visits and 200,000 narrow checks;
hard maxima are 50,000,000 and 10,000,000 respectively. Exhaustion raises
`RegionBudgetExceeded`, a `ValueError`, and the whole request fails. No partial
zero-intersection success is returned. Counters record consumed work and must not
be reset inside an interval to evade the declared admission bound.

The result contains counts for every pair, including conservative broad-phase
separation. Only pairs within the local cutoff contribute to
`minimum_distance_within_radius_m`; null means no pair was found within the local
cutoff. It does not supply a global minimum distance. Pair examples retain caller array indices and world points, with
an explicit truncation flag and a 0–1,000 example bound. The Blender adapter also
enforces the global example bound across regions and times. Memory/work bounds
are admission policies, not execution-time or OS-memory caps.

## Test-first status

The first pure run failed to import the not-yet-written module. Initial coverage
then passed 20 test methods and 27 parameterized observations, including the thin
ridge missed by sparse markers, coplanar/edge/vertex cases, AABB false positives,
interior edge-to-edge proximity, permutations, translated metre/mm fixtures,
degenerate/nonfinite refusal, shared cumulative budgets, bounded examples and an
explicit containment nonclaim.

A subsequent genuine red exposed tolerance-expanded triangle half-planes
inventing a crossing or zero-distance touch at a nearby corner. Actual triangle
membership now establishes intersections; closest-feature distances handle
tolerance-near points separately. Independent review additionally reproduced the
cutoff mismatch described above and an extreme-aspect-ratio parallel-triangle
distance error. A proven 1-micrometre separation was originally measured as
1.1053 micrometres, incorrectly exceeding a 1.05-micrometre query radius. The
corrected edge/face calculations return the proven minimum. A second independent
case has a 1e-13-radian angle across a 2,000 km span: its vertex offsets are 100
times the requested epsilon, so the old angular-only shortcut falsely returned
touch. It now reports the resolved crossing.

Final focused evidence is **21 owned tests plus eight independent review cases,
with 28 parameterized observations**, all passing. Thirty-six permutations of the
thin parallel triangles retain the proven distance. Rotated extreme-aspect cases
either compute the reference distance or explicitly refuse unresolved numerical
conditioning; they never produce a false-clearance result. Huge numeric input
also refuses cleanly, and returned distances/world points must remain finite.
Ruff formatting and checks pass. The independent red records are
`artifacts/region-contact-study/geometry-review-red.log` and
`geometry-review-expanded-red.log`; the combined focused green is
`artifacts/region-contact-study/geometry-final-green.log`.

Existing mesh diagnostic predicates remain unchanged. Their documented
within-mesh/self-intersection and point-contact behavior are not silently reused
as a full regional clearance test. Actual human performance and selected artifact
evidence belong to the adapter record and the complete release verification.
Focused test success is not a final package receipt or artistic/native acceptance.
