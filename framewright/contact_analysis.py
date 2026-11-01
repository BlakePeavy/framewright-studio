"""Explicit sole/prop marker contacts on a bounded evaluated mesh surface."""

from __future__ import annotations

import hashlib
import math
import re
from array import array
from contextlib import nullcontext

MAX_GEOMETRY_SAMPLE_ELEMENTS = 200_000_000
MAX_SURFACE_VERTICES = 1_000_000


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def _number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return float(value)


def sample_times(params):
    start = _integer(params.get("frame_start"), -1_000_000, 1_000_000, "frame_start")
    end = _integer(params.get("frame_end"), -1_000_000, 1_000_000, "frame_end")
    if end < start:
        raise ValueError("frame_end must not precede frame_start")
    step = _integer(params.get("step", 1), 1, 1000, "step")
    substeps = _integer(params.get("substeps", 1), 1, 8, "substeps")
    maximum = _integer(params.get("max_samples", 512), 1, 4096, "max_samples")
    first, last = start * substeps, end * substeps
    count = (last - first) // step + 1 + bool((last - first) % step)
    if count > maximum:
        raise ValueError("Requested range/substeps exceeds max_samples; no frames were sampled")
    result = [tick / substeps for tick in range(first, last + 1, step)]
    if result[-1] != end:
        result.append(float(end))
    return result


def _name(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not value.isprintable():
        raise ValueError(f"{name} must be an exact nonempty scene name up to 1024 characters")


def _request(params):
    allowed = {
        "surface_name",
        "markers",
        "frame_start",
        "frame_end",
        "step",
        "substeps",
        "max_samples",
        "max_surface_triangles",
        "search_distance",
        "contact_tolerance",
        "penetration_tolerance",
        "sliding_speed",
        "minimum_up_dot",
    }
    if (
        not isinstance(params, dict)
        or params.keys() - allowed
        or not {"surface_name", "markers", "frame_start", "frame_end"} <= params.keys()
    ):
        raise ValueError(
            "Surface contacts require surface_name, markers and frame bounds; unknown parameters rejected"
        )
    times = sample_times(params)
    _name(params["surface_name"], "surface_name")
    markers = params["markers"]
    if not isinstance(markers, list) or not 1 <= len(markers) <= 32:
        raise ValueError("markers must contain 1..32 explicit sole or prop points")
    identities = set()
    for marker in markers:
        if (
            not isinstance(marker, dict)
            or not {"id", "object_name", "position"} <= marker.keys()
            or marker.keys() - {"id", "object_name", "position", "bone"}
        ):
            raise ValueError("Marker requires id, object_name and position; optional bone")
        if (
            not isinstance(marker["id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", marker["id"])
            or marker["id"] in identities
        ):
            raise ValueError("Marker ids must be unique 1..128 letters/digits/hyphens/underscores")
        identities.add(marker["id"])
        _name(marker["object_name"], "object_name")
        if "bone" in marker:
            _name(marker["bone"], "bone")
        if not isinstance(marker["position"], list) or len(marker["position"]) != 3:
            raise ValueError("Marker position requires three local coordinates")
        for value in marker["position"]:
            _number(value, -1_000_000, 1_000_000, "marker position")
    settings = {
        "max_surface_triangles": _integer(
            params.get("max_surface_triangles", 100000), 1, 500000, "max_surface_triangles"
        )
    }
    for name, default, low, high in (
        ("search_distance", 0.5, 0.000001, 1000000),
        ("contact_tolerance", 0.03, 0, 1000000),
        ("penetration_tolerance", 0.01, 0, 1000000),
        ("sliding_speed", 0.05, 0, 1000000),
        ("minimum_up_dot", 0.5, 0, 1),
    ):
        settings[name] = _number(params.get(name, default), low, high, name)
    if (
        max(settings["contact_tolerance"], settings["penetration_tolerance"])
        > settings["search_distance"]
    ):
        raise ValueError("Contact and penetration tolerances must fit search_distance")
    return times, settings


def _geometry(surface, context, maximum, sample_count, build_tree):
    from mathutils.bvhtree import BVHTree

    evaluated = surface.evaluated_get(context.evaluated_depsgraph_get())
    mesh = None
    try:
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        vertices, triangles = len(mesh.vertices), len(mesh.loop_triangles)
        if not triangles or not vertices:
            raise ValueError("Contact surface needs evaluated triangle geometry")
        if triangles > maximum or vertices > MAX_SURFACE_VERTICES:
            raise ValueError("Contact surface exceeds the configured geometry budget")
        if sample_count * (vertices + triangles * 3) > MAX_GEOMETRY_SAMPLE_ELEMENTS:
            raise ValueError("Surface/frame combination exceeds the geometry sampling work budget")
        coordinates = array("f", [0]) * (vertices * 3)
        indices = array("i", [0]) * (triangles * 3)
        mesh.vertices.foreach_get("co", coordinates)
        mesh.loop_triangles.foreach_get("vertices", indices)
        fingerprint = hashlib.sha256(coordinates.tobytes() + indices.tobytes()).hexdigest()
        tree = None
        if build_tree:
            if not all(math.isfinite(value) for value in coordinates):
                raise ValueError("Surface coordinates must be finite")
            tree = BVHTree.FromPolygons(
                [tuple(coordinates[i : i + 3]) for i in range(0, len(coordinates), 3)],
                [tuple(indices[i : i + 3]) for i in range(0, len(indices), 3)],
                all_triangles=True,
            )
        matrix = evaluated.matrix_world.copy()
        if (
            not all(math.isfinite(value) for row in matrix for value in row)
            or abs(matrix.determinant()) <= 1e-12
        ):
            raise ValueError("Surface transform must be finite and invertible")
        return fingerprint, tree, matrix, vertices, triangles
    finally:
        if mesh is not None:
            evaluated.to_mesh_clear()


def _project(tree, matrix, position, search_distance, unit, minimum_up_dot):
    from mathutils import Vector

    up = Vector((0, 0, search_distance / unit))
    inverse = matrix.inverted()
    origin = inverse @ (position + up)
    ray = (inverse @ (position - up)) - origin
    hit, normal, _, _ = tree.ray_cast(origin, ray.normalized(), ray.length)
    if hit is None:
        return {"status": "miss", "point": None, "normal": None, "distance": None}
    point = matrix @ hit
    world_normal = inverse.transposed().to_3x3() @ normal
    if matrix.determinant() < 0:
        world_normal.negate()
    world_normal.normalize()
    status = "hit" if world_normal.z >= minimum_up_dot else "steep_surface"
    return {
        "status": status,
        "point": point,
        "normal": world_normal,
        "distance": (position - point).dot(world_normal) * unit,
    }


def inspect_surface_contacts(params, context=None):
    """Measure authored marker points, never guess foot geometry or approve motion."""
    return _sample_surface_contacts(params, context)


def _sample_surface_contacts(params, context=None, *, position_sampler=None, isolated=False):
    """Shared projection mechanics; only internal isolated callers supply evaluated points."""
    times, settings = _request(params)
    from mathutils import Vector

    from .rigging import checked_context, preserve_time, scene_object

    context = checked_context(context)
    surface = scene_object(context, params["surface_name"], "MESH")
    markers = []
    for marker in params["markers"]:
        obj = scene_object(context, marker["object_name"])
        if obj == surface:
            raise ValueError("Marker objects must be distinct from the contact surface")
        if obj.library or surface.library:
            raise ValueError("Surface contact sampling currently requires local objects")
        if "bone" in marker and (obj.type != "ARMATURE" or marker["bone"] not in obj.pose.bones):
            raise ValueError("Marker bone must exist on its explicit armature object")
        markers.append((marker, obj))
    unit = context.scene.unit_settings.scale_length
    fps_base = context.scene.render.fps_base
    fps = context.scene.render.fps / fps_base if fps_base else 0
    if not math.isfinite(unit) or unit <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Scene unit scale and effective FPS must be positive and finite")
    samples, previous = [], {}
    counts = {
        "contact_samples": 0,
        "penetration_samples": 0,
        "sliding_segments": 0,
        "projection_misses": 0,
        "steep_surface_samples": 0,
    }
    fingerprint, tree = None, None
    # Frame changes affect unrelated animated objects too; restore exact local
    # transform/pose channels as well as the original frame and subframe.
    local_objects = tuple(obj for obj in context.scene.objects if not obj.library)
    with nullcontext() if isolated else preserve_time(context, local_objects):
        for time in times:
            frame = math.floor(time)
            context.scene.frame_set(frame, subframe=time - frame)
            state, new_tree, matrix, vertices, triangles = _geometry(
                surface, context, settings["max_surface_triangles"], len(times), tree is None
            )
            if fingerprint is None:
                fingerprint, tree = state, new_tree
            elif state != fingerprint:
                raise ValueError(
                    "Animated local surface geometry is unsupported; use a rigid contact surface or inspect separate intervals"
                )
            inverse = matrix.inverted()
            measured = []
            graph = context.evaluated_depsgraph_get()
            positions = (
                position_sampler(markers, graph, vertices, triangles)
                if position_sampler is not None
                else None
            )
            for definition, obj in markers:
                if positions is not None:
                    position = positions[definition["id"]]
                else:
                    evaluated = obj.evaluated_get(graph)
                    position = Vector(definition["position"])
                    if "bone" in definition:
                        position = evaluated.pose.bones[definition["bone"]].matrix @ position
                    position = evaluated.matrix_world @ position
                if not all(math.isfinite(value) for value in position):
                    raise ValueError("Evaluated marker position must be finite")
                projection = _project(
                    tree,
                    matrix,
                    position,
                    settings["search_distance"],
                    unit,
                    settings["minimum_up_dot"],
                )
                valid = projection["status"] == "hit"
                contact = (
                    abs(projection["distance"]) <= settings["contact_tolerance"] if valid else None
                )
                penetrating = (
                    projection["distance"] < -settings["penetration_tolerance"] if valid else None
                )
                speed, sliding = None, None
                old = previous.get(definition["id"])
                if valid and old is not None and old["valid"]:
                    duration = (time - old["time"]) / fps
                    displacement = (position - matrix @ old["surface_local_position"]) * unit
                    normal = projection["normal"]
                    speed = (displacement - normal * displacement.dot(normal)).length / duration
                    sliding = bool(contact and old["contact"] and speed > settings["sliding_speed"])
                counts["contact_samples"] += contact is True
                counts["penetration_samples"] += penetrating is True
                counts["sliding_segments"] += sliding is True
                counts["projection_misses"] += projection["status"] == "miss"
                counts["steep_surface_samples"] += projection["status"] == "steep_surface"
                measured.append(
                    {
                        "id": definition["id"],
                        "position_meters": list(position * unit),
                        "projection_status": projection["status"],
                        "surface_point_meters": list(projection["point"] * unit)
                        if projection["point"] is not None
                        else None,
                        "surface_normal": list(projection["normal"])
                        if projection["normal"] is not None
                        else None,
                        "normal_distance_meters": projection["distance"],
                        "contact": contact,
                        "penetrating": penetrating,
                        "relative_tangent_speed_mps": speed,
                        "sliding": sliding,
                    }
                )
                previous[definition["id"]] = {
                    "time": time,
                    "surface_local_position": inverse @ position,
                    "contact": contact,
                    "valid": valid,
                }
            samples.append(
                {
                    "frame": frame,
                    "subframe": time - frame,
                    "seconds_from_start": (time - times[0]) / fps,
                    "markers": measured,
                }
            )
    return {
        "schema_version": "1.0",
        "surface_name": surface.name,
        "samples": samples,
        **counts,
        "coverage": "partial"
        if counts["projection_misses"] or counts["steep_surface_samples"]
        else "complete_at_samples",
        "temporal_coverage": {
            "requested_frames": [params["frame_start"], params["frame_end"]],
            "sample_count": len(times),
            "every_integer_frame": sum(time.is_integer() for time in times)
            == params["frame_end"] - params["frame_start"] + 1,
            "between_samples_verified": False,
        },
        "surface_vertices": vertices,
        "surface_triangles": triangles,
        "surface_geometry_sha256": fingerprint,
        "settings": settings,
        "scene_unit_scale": unit,
        "effective_fps": fps,
        "visual_acceptance": False,
        "preservation": {
            "restored": [
                "frame/subframe",
                "local object/pose transforms",
                "local numeric character custom properties",
                "local shape-key value/mute/eval_time",
            ],
            "outside_scope": [
                "arbitrary animated light/material/node/constraint RNA",
                "custom frame handlers and external side effects",
            ],
        },
        "limits": [
            "Explicit object/bone-local marker points are authored approximations of soles or props, not full skin collision",
            "Downward rays use world +Z, chosen mesh winding and the first hit in a bounded interval; misses are unknown contact, not proof of clearance",
            "Choose the intended contact layer explicitly; overlapping layers can obscure the intended floor, and signed normal distance is not full collision distance",
            "Object-transform platform motion is compensated; animated local surface geometry is rejected",
            "Every requested sample is evaluated, but between-sample motion and full-clip visual/native acceptance remain unverified",
            "Geometry evaluation itself is not interruptible; limits apply after Blender produces evaluated geometry",
        ],
    }
