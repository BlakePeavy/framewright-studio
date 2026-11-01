"""Bounded mesh diagnostics and pure triangle-intersection algorithms."""

from __future__ import annotations

import math
import threading
from contextlib import contextmanager

EPSILON = 1e-8
DEFAULT_MAX_TRIANGLES = 20_000
DEFAULT_MAX_PAIRS = 100_000
MAX_TRIANGLES = 200_000
MAX_PAIRS = 2_000_000
SAMPLE_LIMIT = 100


def _triangle(points, dimensions):
    if len(points) != 3 or any(len(point) != dimensions for point in points):
        raise ValueError(f"Expected three {dimensions}D points")
    if any(not math.isfinite(value) for point in points for value in point):
        raise ValueError("Triangle coordinates must be finite")
    return tuple(tuple(float(value) for value in point) for point in points)


def _cross2(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _area2(points):
    if len(points) < 3:
        return 0.0
    origin = points[0]
    return (
        abs(sum(_cross2(origin, points[i], points[i + 1]) for i in range(1, len(points) - 1))) * 0.5
    )


def triangle_overlap_2d(first, second, epsilon=EPSILON):
    """Positive-area convex overlap; touching vertices or edges are not overlap."""
    first = _triangle(first, 2)
    second = _triangle(second, 2)
    if _area2(first) <= epsilon * epsilon or _area2(second) <= epsilon * epsilon:
        return False
    clip = second if _cross2(*second) > 0 else tuple(reversed(second))
    output = list(first)
    for a, b in zip(clip, clip[1:] + clip[:1], strict=True):
        previous_output = output
        output = []
        if not previous_output:
            return False
        previous = previous_output[-1]
        previous_distance = _cross2(a, b, previous)
        for current in previous_output:
            current_distance = _cross2(a, b, current)
            previous_inside = previous_distance >= 0.0
            current_inside = current_distance >= 0.0
            if current_inside != previous_inside:
                fraction = previous_distance / (previous_distance - current_distance)
                output.append(
                    tuple(previous[i] + fraction * (current[i] - previous[i]) for i in range(2))
                )
            if current_inside:
                output.append(current)
            previous, previous_distance = current, current_distance
    return len(output) >= 3 and _area2(output) > epsilon * epsilon


def _subtract(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normal(triangle):
    normal = _cross(_subtract(triangle[1], triangle[0]), _subtract(triangle[2], triangle[0]))
    length = math.sqrt(_dot(normal, normal))
    return tuple(value / length for value in normal) if length > EPSILON * EPSILON else None


def _coplanar(first, second, epsilon=EPSILON):
    normal = _normal(first)
    return normal is not None and all(
        abs(_dot(normal, _subtract(p, first[0]))) <= epsilon for p in second
    )


def _plane_slice(triangle, origin, normal, epsilon):
    distances = [_dot(normal, _subtract(point, origin)) for point in triangle]
    points = [triangle[i] for i, distance in enumerate(distances) if abs(distance) <= epsilon]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if (distances[i] < -epsilon and distances[j] > epsilon) or (
            distances[j] < -epsilon and distances[i] > epsilon
        ):
            fraction = distances[i] / (distances[i] - distances[j])
            points.append(
                tuple(
                    triangle[i][axis] + fraction * (triangle[j][axis] - triangle[i][axis])
                    for axis in range(3)
                )
            )
    return points


def triangles_intersect_3d(first, second, epsilon=EPSILON):
    """Coplanar area overlap or noncoplanar segment overlap, ignoring point contact."""
    first = _triangle(first, 3)
    second = _triangle(second, 3)
    first_normal, second_normal = _normal(first), _normal(second)
    if first_normal is None or second_normal is None:
        return False
    direction = _cross(first_normal, second_normal)
    length = math.sqrt(_dot(direction, direction))
    if length <= epsilon:
        if not _coplanar(first, second, epsilon):
            return False
        drop = max(range(3), key=lambda i: abs(first_normal[i]))
        return triangle_overlap_2d(
            [tuple(value for i, value in enumerate(p) if i != drop) for p in first],
            [tuple(value for i, value in enumerate(p) if i != drop) for p in second],
            epsilon,
        )
    direction = tuple(value / length for value in direction)
    first_slice = _plane_slice(first, second[0], second_normal, epsilon)
    second_slice = _plane_slice(second, first[0], first_normal, epsilon)
    if len(first_slice) < 2 or len(second_slice) < 2:
        return False
    first_values = [_dot(point, direction) for point in first_slice]
    second_values = [_dot(point, direction) for point in second_slice]
    return (
        min(max(first_values), max(second_values)) - max(min(first_values), min(second_values))
        > epsilon
    )


def _positive_limit(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def scan_intersections(
    triangles,
    *,
    vertex_ids=None,
    face_ids=None,
    dimensions=3,
    max_triangles=DEFAULT_MAX_TRIANGLES,
    max_pairs=DEFAULT_MAX_PAIRS,
):
    """Sweep the X axis, bound candidate visits, and retain at most 100 pair samples."""
    _positive_limit(max_triangles, MAX_TRIANGLES, "max_triangles")
    _positive_limit(max_pairs, MAX_PAIRS, "max_pairs")
    if dimensions not in {2, 3}:
        raise ValueError("dimensions must be 2 or 3")
    selected = [_triangle(triangle, dimensions) for triangle in triangles[:max_triangles]]
    boxes = [
        tuple(
            (min(p[axis] for p in triangle), max(p[axis] for p in triangle))
            for axis in range(dimensions)
        )
        for triangle in selected
    ]
    ordered = sorted(range(len(selected)), key=lambda i: (boxes[i][0][0], i))
    considered = 0
    found = 0
    samples = []
    capped = False
    for position, first_id in enumerate(ordered):
        for next_position in range(position + 1, len(ordered)):
            second_id = ordered[next_position]
            if boxes[second_id][0][0] > boxes[first_id][0][1] + EPSILON:
                break
            if considered >= max_pairs:
                capped = True
                break
            considered += 1
            if face_ids is not None and face_ids[first_id] == face_ids[second_id]:
                continue
            if any(
                boxes[first_id][axis][1] < boxes[second_id][axis][0] - EPSILON
                or boxes[second_id][axis][1] < boxes[first_id][axis][0] - EPSILON
                for axis in range(dimensions)
            ):
                continue
            first, second = selected[first_id], selected[second_id]
            if dimensions == 3 and vertex_ids is not None:
                shared = set(vertex_ids[first_id]) & set(vertex_ids[second_id])
                if len(shared) == 2 and not _coplanar(first, second):
                    continue
            intersects = (
                triangle_overlap_2d(first, second)
                if dimensions == 2
                else triangles_intersect_3d(first, second)
            )
            if intersects:
                found += 1
                if len(samples) < SAMPLE_LIMIT:
                    samples.append(sorted((first_id, second_id)))
        if capped:
            break
    omitted = max(0, len(triangles) - len(selected))
    return {
        "coverage": "partial" if omitted or capped else "complete",
        "triangles_total": len(triangles),
        "triangles_tested": len(selected),
        "triangles_omitted": omitted,
        "pairs_considered": considered,
        "pair_limit_reached": capped,
        "intersection_count": found,
        "pairs": sorted(samples),
        "pair_samples_truncated": found > len(samples),
        "epsilon": EPSILON,
    }


def validate_params(params, extra=()):
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    allowed = {"object_name", "evaluated", "max_triangles", "max_pairs", *extra}
    if set(params) - allowed:
        raise ValueError("Unknown diagnostic parameter")
    name = params.get("object_name")
    if not isinstance(name, str) or not name or len(name) > 256:
        raise ValueError("object_name must be a nonempty exact scene object name")
    for field in ("evaluated", "open_boundary_allowed", "allow_stacked_uvs"):
        if field in params and type(params[field]) is not bool:
            raise ValueError(f"{field} must be a boolean")
    _positive_limit(
        params.get("max_triangles", DEFAULT_MAX_TRIANGLES), MAX_TRIANGLES, "max_triangles"
    )
    _positive_limit(params.get("max_pairs", DEFAULT_MAX_PAIRS), MAX_PAIRS, "max_pairs")


@contextmanager
def inspected_mesh(params, context=None):
    """Temporary evaluated/source mesh, always cleared even if a diagnostic fails."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender diagnostics must run on the main thread")
    import bpy

    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before inspecting a mesh")
    matches = [obj for obj in context.scene.objects if obj.name == params["object_name"]]
    if len(matches) > 1:
        raise ValueError("object_name is ambiguous across local or linked assets; use unique names")
    obj = matches[0] if matches else None
    if obj is None or obj.type != "MESH":
        raise ValueError("object_name must identify a mesh in the active scene")
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = params.get("evaluated", True)
    owner = obj.evaluated_get(depsgraph) if evaluated else obj
    try:
        mesh = owner.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        if mesh is None:
            raise ValueError("Object could not produce an inspectable mesh")
        mesh.calc_loop_triangles()
        yield obj, mesh
    finally:
        owner.to_mesh_clear()


def finding(rule_id, severity, message, count=1, samples=()):
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "count": count,
        "samples": list(samples)[:SAMPLE_LIMIT],
    }


def _inspect_mesh_data(obj, mesh, params):
    vertices = [tuple(vertex.co) for vertex in mesh.vertices]
    incidence = {tuple(sorted(edge.vertices)): 0 for edge in mesh.edges}
    seen = {}
    duplicate_count = 0
    duplicates = []
    zero_area = []
    for polygon in mesh.polygons:
        key = tuple(sorted(vertices[index] for index in polygon.vertices))
        if key in seen:
            duplicate_count += 1
            if len(duplicates) < SAMPLE_LIMIT:
                duplicates.append([seen[key], polygon.index])
        else:
            seen[key] = polygon.index
        if polygon.area <= EPSILON * EPSILON:
            zero_area.append(polygon.index)
        for edge in polygon.edge_keys:
            key = tuple(sorted(edge))
            incidence[key] = incidence.get(key, 0) + 1
    boundary = sum(count == 1 for count in incidence.values())
    wire = sum(count == 0 for count in incidence.values())
    branching = sum(count > 2 for count in incidence.values())
    triangle_total = len(mesh.loop_triangles)
    selected = [
        mesh.loop_triangles[i]
        for i in range(min(triangle_total, params.get("max_triangles", DEFAULT_MAX_TRIANGLES)))
    ]
    triangles = [tuple(vertices[index] for index in tri.vertices) for tri in selected]
    scan = scan_intersections(
        triangles,
        vertex_ids=[tuple(tri.vertices) for tri in selected],
        face_ids=[tri.polygon_index for tri in selected],
        max_triangles=params.get("max_triangles", DEFAULT_MAX_TRIANGLES),
        max_pairs=params.get("max_pairs", DEFAULT_MAX_PAIRS),
    )
    scan["triangles_total"] = triangle_total
    scan["triangles_omitted"] = triangle_total - len(selected)
    if scan["triangles_omitted"]:
        scan["coverage"] = "partial"
    scan["polygon_pairs"] = [
        [selected[first].polygon_index, selected[second].polygon_index]
        for first, second in scan["pairs"]
    ]
    findings = []
    if duplicate_count:
        findings.append(
            finding(
                "DUPLICATE_FACES",
                "ERROR",
                "Faces share the same exact vertex positions",
                duplicate_count,
                duplicates,
            )
        )
    if zero_area:
        findings.append(
            finding(
                "ZERO_AREA_FACES",
                "ERROR",
                "Faces have zero or near-zero local area",
                len(zero_area),
                zero_area,
            )
        )
    if boundary and not params.get("open_boundary_allowed", False):
        findings.append(
            finding(
                "OPEN_BOUNDARY",
                "WARNING",
                "Boundary edges need an explicit open-surface policy",
                boundary,
            )
        )
    if wire or branching:
        findings.append(
            finding(
                "NONMANIFOLD_EDGES",
                "WARNING",
                "Wire edges or edges shared by more than two faces",
                wire + branching,
            )
        )
    if scan["intersection_count"]:
        findings.append(
            finding(
                "SELF_INTERSECTION",
                "WARNING",
                "Nonadjacent triangles overlap or meet along a segment; inspect the sampled pairs",
                scan["intersection_count"],
                scan["pairs"],
            )
        )
    if scan["coverage"] != "complete":
        findings.append(
            finding(
                "PARTIAL_INTERSECTION_CHECK",
                "INFO",
                "Analysis budget omitted triangles or candidate pairs; absence of findings is not a clean result",
            )
        )
    return {
        "schema_version": "1.0",
        "object_name": obj.name,
        "evaluated": params.get("evaluated", True),
        "linked_source": bool(obj.library or obj.data.library),
        "coordinate_space": "object_local",
        "coverage": scan["coverage"],
        "open_boundary_allowed": params.get("open_boundary_allowed", False),
        "topology": {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "triangles": triangle_total,
            "boundary_edges": boundary,
            "wire_edges": wire,
            "branching_edges": branching,
            "duplicate_faces": duplicate_count,
            "zero_area_faces": len(zero_area),
        },
        "intersections": scan,
        "findings": findings,
        "limits": [
            "Current frame and viewport modifier evaluation only",
            "Geometry evaluation itself is not interruptible",
            "No visual or export acceptance",
            "Point contacts below local tolerance are not intersection findings",
        ],
    }


def inspect_mesh(params: dict, context=None) -> dict:
    """Inspect exact active-scene mesh identity without changing the original."""
    validate_params(params, ("open_boundary_allowed",))
    with inspected_mesh(params, context) as (obj, mesh):
        return _inspect_mesh_data(obj, mesh, params)
