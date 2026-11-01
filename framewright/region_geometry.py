"""Bounded world-metre triangle boundary relations; no volume containment claim."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

RELATIONS = ("crossing", "coplanar_overlap", "touch", "proximity", "separated")
MAX_REGION_TRIANGLES = 16_384
MAX_SURFACE_TRIANGLES = 500_000
ANGULAR_EPSILON = 1e-12


class RegionBudgetExceeded(ValueError):
    """The complete requested relation cannot be established within its work limit."""


def _integer(value, maximum, name, minimum=1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _settings(epsilon, radius):
    if not _finite_number(epsilon) or not 1e-9 <= epsilon <= 1e-3:
        raise ValueError("distance_epsilon_m must be finite from 1e-9 to 1e-3 metres")
    if not _finite_number(radius) or not epsilon <= radius <= 1:
        raise ValueError("proximity_distance_m must be finite between epsilon and 1 metre")
    return float(epsilon), float(radius)


def _radius_cutoff(radius):
    """Shared representational slack for narrow and conservative broad phases."""
    return radius + 8 * math.ulp(radius)


@dataclass
class PairBudget:
    """Cumulative interval counters; charge before visiting/checking each pair."""

    max_candidate_visits: int = 2_000_000
    max_narrow_checks: int = 200_000
    candidate_visits: int = 0
    narrow_checks: int = 0

    def __post_init__(self):
        _integer(self.max_candidate_visits, 50_000_000, "max_candidate_visits")
        _integer(self.max_narrow_checks, 10_000_000, "max_narrow_checks")
        _integer(self.candidate_visits, self.max_candidate_visits, "candidate_visits", 0)
        _integer(self.narrow_checks, self.max_narrow_checks, "narrow_checks", 0)

    def visit(self):
        if self.candidate_visits >= self.max_candidate_visits:
            raise RegionBudgetExceeded(
                "Regional candidate-visit budget exhausted; no complete result"
            )
        self.candidate_visits += 1

    def check(self):
        if self.narrow_checks >= self.max_narrow_checks:
            raise RegionBudgetExceeded("Regional narrow-check budget exhausted; no complete result")
        self.narrow_checks += 1


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _mix(a, b, factor):
    return tuple(a[i] + (b[i] - a[i]) * factor for i in range(3))


def _length(vector):
    return math.hypot(*vector)


def _clamp(value):
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class _Triangle:
    points: tuple
    normal: tuple
    longest: float
    bounds: tuple


def _prepare(triangle, epsilon):
    if not isinstance(triangle, (list, tuple)) or len(triangle) != 3:
        raise ValueError("A regional triangle must contain exactly three 3D points")
    for point in triangle:
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or any(not _finite_number(value) for value in point)
        ):
            raise ValueError("Regional coordinates must be finite numeric 3D points")
    points = tuple(tuple(float(value) for value in point) for point in triangle)
    edges = [_sub(points[b], points[a]) for a, b in ((0, 1), (0, 2), (1, 2))]
    longest = max(_length(edge) for edge in edges)
    if not math.isfinite(longest) or longest <= epsilon:
        raise ValueError("Regional triangle is degenerate or outside finite numeric range")
    normal = _cross(tuple(v / longest for v in edges[0]), tuple(v / longest for v in edges[1]))
    area = _length(normal)
    if area * longest <= epsilon:
        raise ValueError(
            "Degenerate regional triangle: minimum altitude must exceed distance epsilon"
        )
    unit_normal = tuple(v / area for v in normal)
    if any(abs(_dot(unit_normal, edge)) > epsilon * 0.25 for edge in edges):
        raise ValueError(
            "Triangle plane is numerically unresolved at the requested distance epsilon"
        )
    return _Triangle(
        points,
        unit_normal,
        longest,
        tuple((min(p[i] for p in points), max(p[i] for p in points)) for i in range(3)),
    )


def _closest_point(point, triangle, normal):
    """Project to the face, then edges; avoid skinny barycentric determinants."""
    offset = _dot(_sub(point, triangle[0]), normal)
    projected = tuple(point[i] - offset * normal[i] for i in range(3))
    if _inside(projected, triangle, normal, 0):
        return projected
    best_distance, closest = math.inf, None
    for i, first in enumerate(triangle):
        second = triangle[(i + 1) % 3]
        edge = _sub(second, first)
        denominator = _dot(edge, edge)
        if denominator == 0:
            raise ValueError("Triangle edge is numerically unresolved in pair-local coordinates")
        candidate = _mix(first, second, _clamp(_dot(_sub(point, first), edge) / denominator))
        distance = _length(_sub(candidate, point))
        if distance < best_distance:
            best_distance, closest = distance, candidate
    return closest


def _closest_segments(a, b, c, d):
    first, second, offset = _sub(b, a), _sub(d, c), _sub(a, c)
    aa, ee, ff = _dot(first, first), _dot(second, second), _dot(second, offset)
    if aa == 0 or ee == 0:
        raise ValueError("Segment is numerically unresolved in pair-local coordinates")
    cc, bb = _dot(first, offset), _dot(first, second)
    cross = _cross(first, second)
    cross_length = _length(cross)
    # aa*ee-bb*bb cancels for valid near-parallel edges. Cross-product line
    # parameters preserve their interior minimum without an angular shortcut.
    s = (
        _clamp(
            _dot(_cross(tuple(-v for v in offset), second), tuple(v / cross_length for v in cross))
            / cross_length
        )
        if cross_length
        else 0.0
    )
    t = (bb * s + ff) / ee
    if t < 0:
        t, s = 0.0, _clamp(-cc / aa)
    elif t > 1:
        t, s = 1.0, _clamp((bb - cc) / aa)
    return _mix(a, b, s), _mix(c, d, t)


def _closest_features(first, second, first_normal, second_normal):
    best = (math.inf, None, None)
    pairs = [(point, _closest_point(point, second, second_normal)) for point in first]
    pairs.extend((_closest_point(point, first, first_normal), point) for point in second)
    pairs.extend(
        _closest_segments(first[i], first[(i + 1) % 3], second[j], second[(j + 1) % 3])
        for i in range(3)
        for j in range(3)
    )
    for a, b in pairs:
        distance = _length(_sub(a, b))
        if distance < best[0]:
            best = distance, a, b
    return best


def _inside(point, triangle, normal, epsilon):
    for i in range(3):
        edge = _sub(triangle[(i + 1) % 3], triangle[i])
        if _dot(_cross(edge, _sub(point, triangle[i])), normal) < -epsilon * _length(edge):
            return False
    return True


def _plane_hits(first, second, normal, epsilon):
    hits = []
    distances = [_dot(_sub(point, second[0]), normal) for point in first]
    for i, a in enumerate(first):
        j, d0, d1 = (i + 1) % 3, distances[i], distances[(i + 1) % 3]
        if d0 == 0 and _inside(a, second, normal, 0):
            hits.append(a)
        if (d0 < 0 < d1) or (d1 < 0 < d0):
            point = _mix(a, first[j], d0 / (d0 - d1))
            # Tolerance-expanded half-planes can invent a crossing outside a
            # triangle corner. Only actual inside hits establish intersection;
            # the separate closest-feature distance handles epsilon-near cases.
            if _inside(point, second, normal, 0):
                hits.append(point)
    return hits


def _coplanar_area(first, second, normal):
    drop = max(range(3), key=lambda i: abs(normal[i]))
    first = [tuple(value for i, value in enumerate(point) if i != drop) for point in first]
    second = [tuple(value for i, value in enumerate(point) if i != drop) for point in second]

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    if cross(*second) < 0:
        second.reverse()
    polygon = first
    for a, b in zip(second, second[1:] + second[:1], strict=True):
        source, polygon = polygon, []
        if not source:
            return 0.0
        previous, previous_distance = source[-1], cross(a, b, source[-1])
        for current in source:
            distance = cross(a, b, current)
            if (distance >= 0) != (previous_distance >= 0):
                factor = previous_distance / (previous_distance - distance)
                polygon.append(
                    tuple(previous[i] + (current[i] - previous[i]) * factor for i in range(2))
                )
            if distance >= 0:
                polygon.append(current)
            previous, previous_distance = current, distance
    if len(polygon) < 3:
        return 0.0
    projected_area = (
        abs(sum(cross(polygon[0], polygon[i], polygon[i + 1]) for i in range(1, len(polygon) - 1)))
        / 2
    )
    return projected_area / abs(normal[drop])


def _relation(first, second, epsilon, radius):
    origin = first.points[0]
    local = [tuple(_sub(point, origin)) for point in (*first.points, *second.points)]
    scale = max(first.longest, second.longest, *(abs(value) for point in local for value in point))
    if not math.isfinite(scale):
        raise ValueError("Pair-local coordinate range is not finite")
    points = [tuple(value / scale for value in point) for point in local]
    a, b, tolerance = points[:3], points[3:], epsilon / scale
    da = [_dot(_sub(point, b[0]), second.normal) for point in a]
    db = [_dot(_sub(point, a[0]), first.normal) for point in b]
    # A tiny angle across a long span can still cross by many metre epsilons.
    # Only take the near-parallel shortcut when its plane variation is also
    # unresolved at the requested dimensional tolerance.
    parallel = (
        _length(_cross(first.normal, second.normal)) <= ANGULAR_EPSILON
        and max(da) - min(da) <= tolerance
        and max(db) - min(db) <= tolerance
    )
    coplanar = parallel and max(map(abs, (*da, *db))) <= tolerance
    relation = None
    if coplanar and _coplanar_area(a, b, first.normal) > tolerance * tolerance:
        relation = "coplanar_overlap"
    if not parallel:
        hits = _plane_hits(a, b, second.normal, tolerance) + _plane_hits(
            b, a, first.normal, tolerance
        )
        if hits:
            extent = max(_length(_sub(p, q)) for p in hits for q in hits)
            crosses = (
                min(da) < -tolerance
                and max(da) > tolerance
                and min(db) < -tolerance
                and max(db) > tolerance
            )
            relation = "crossing" if crosses and extent > tolerance else "touch"
            distance, closest_a, closest_b = 0.0, hits[0], hits[0]
        else:
            distance, closest_a, closest_b = _closest_features(a, b, first.normal, second.normal)
    else:
        distance, closest_a, closest_b = _closest_features(a, b, first.normal, second.normal)
    metres = distance * scale
    if not math.isfinite(metres):
        raise ValueError("Regional distance is outside finite numeric range")
    if relation is None:
        relation = (
            "touch"
            if metres <= epsilon
            else "proximity"
            if metres <= _radius_cutoff(radius)
            else "separated"
        )
    world_first = [origin[i] + closest_a[i] * scale for i in range(3)]
    world_second = [origin[i] + closest_b[i] * scale for i in range(3)]
    if not all(math.isfinite(value) for value in (*world_first, *world_second)):
        raise ValueError("Regional closest points are outside finite numeric range")
    return {
        "relation": relation,
        "distance_m": metres,
        "closest_first": world_first,
        "closest_second": world_second,
    }


def triangle_relation(first, second, *, distance_epsilon_m=1e-6, proximity_distance_m=0.005):
    """Triangle boundary relation with metre thresholds and pair-local arithmetic.

    Coplanar overlap means plane separation within epsilon plus positive projected
    area. Crossing means a noncoplanar segment with both triangles straddling the
    other's plane; edge/point contact is distinct. Floating-point, not exact-real,
    predicates are used. Full volume containment is deliberately not checked.
    """
    epsilon, radius = _settings(distance_epsilon_m, proximity_distance_m)
    return _relation(_prepare(first, epsilon), _prepare(second, epsilon), epsilon, radius)


def compare_regions(
    region_triangles,
    surface_triangles,
    *,
    budget,
    distance_epsilon_m=1e-6,
    proximity_distance_m=0.005,
    max_examples=100,
):
    """Sweep bounded triangle inputs without constructing an overlap-pair list.

    All pairs contribute to counts. Broad-phase pruning proves only separation
    beyond the local radius, so the reported minimum is restricted to that radius.
    Shared budget counters accumulate across calls/samples; exhaustion raises.
    """
    epsilon, radius = _settings(distance_epsilon_m, proximity_distance_m)
    cutoff = _radius_cutoff(radius)
    _integer(max_examples, 1000, "max_examples", 0)
    if not isinstance(budget, PairBudget):
        raise ValueError("A shared PairBudget is required")
    for triangles, maximum, name in (
        (region_triangles, MAX_REGION_TRIANGLES, "region"),
        (surface_triangles, MAX_SURFACE_TRIANGLES, "surface"),
    ):
        if not isinstance(triangles, (list, tuple)) or not 1 <= len(triangles) <= maximum:
            raise ValueError(f"{name} triangles require 1..{maximum} explicit triangles")
    collections = [
        [_prepare(triangle, epsilon) for triangle in triangles]
        for triangles in (region_triangles, surface_triangles)
    ]
    events = sorted(
        (
            math.nextafter(triangle.bounds[0][0] - cutoff, -math.inf)
            if kind == 0
            else triangle.bounds[0][0],
            kind,
            index,
        )
        for kind, collection in enumerate(collections)
        for index, triangle in enumerate(collection)
    )
    active, expiry = [{}, {}], [[], []]
    counts = dict.fromkeys(RELATIONS, 0)
    counts["separated"] = len(region_triangles) * len(surface_triangles)
    examples, minimum = [], None
    before_visits, before_checks = budget.candidate_visits, budget.narrow_checks
    for position, kind, index in events:
        other = 1 - kind
        for group in (0, 1):
            while expiry[group] and expiry[group][0][0] < position:
                _, expired = heapq.heappop(expiry[group])
                del active[group][expired]
        triangle = collections[kind][index]
        for other_index, other_triangle in active[other].items():
            budget.visit()
            a, b = (triangle, other_triangle) if kind == 0 else (other_triangle, triangle)
            gaps = [
                max(0, a.bounds[axis][0] - b.bounds[axis][1], b.bounds[axis][0] - a.bounds[axis][1])
                for axis in range(3)
            ]
            if _length(gaps) > cutoff:
                continue
            budget.check()
            result = _relation(a, b, epsilon, radius)
            relation = result["relation"]
            if relation != "separated":
                counts["separated"] -= 1
                counts[relation] += 1
                minimum = (
                    result["distance_m"] if minimum is None else min(minimum, result["distance_m"])
                )
                if len(examples) < max_examples:
                    first_index, second_index = (
                        (index, other_index) if kind == 0 else (other_index, index)
                    )
                    examples.append(
                        {"first_index": first_index, "second_index": second_index, **result}
                    )
        active[kind][index] = triangle
        heapq.heappush(
            expiry[kind],
            (
                math.nextafter(triangle.bounds[0][1] + cutoff, math.inf)
                if kind == 0
                else triangle.bounds[0][1],
                index,
            ),
        )
    return {
        "counts": counts,
        "tested_region_triangles": len(region_triangles),
        "tested_surface_triangles": len(surface_triangles),
        "examples": examples,
        "examples_truncated": sum(counts[name] for name in RELATIONS if name != "separated")
        > len(examples),
        "minimum_distance_within_radius_m": minimum,
        "containment_checked": False,
        "distance_epsilon_m": epsilon,
        "proximity_distance_m": radius,
        "proximity_cutoff_m": cutoff,
        "angular_epsilon": ANGULAR_EPSILON,
        "minimum_altitude_m_exclusive": epsilon,
        "work": {
            "candidate_visits": budget.candidate_visits - before_visits,
            "narrow_checks": budget.narrow_checks - before_checks,
            "cumulative_candidate_visits": budget.candidate_visits,
            "cumulative_narrow_checks": budget.narrow_checks,
        },
    }
