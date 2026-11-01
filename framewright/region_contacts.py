"""Sample explicit evaluated triangle regions against an owned surface copy."""

from __future__ import annotations

import hashlib
import math
import re
from array import array

from . import contact_analysis, region_geometry, skin_contacts

RELATIONS = ("crossing", "coplanar_overlap", "touch", "proximity", "separated")
INTEGER_SETTINGS = {
    "max_evaluated_vertices": (250000, 1, 1000000),
    "max_surface_triangles": (100000, 1, 500000),
    "max_region_triangles": (4096, 1, 16384),
    "max_candidate_visits": (2000000, 1, 50000000),
    "max_pair_checks": (200000, 1, 10000000),
    "max_examples": (100, 0, 1000),
}


def _name(value, label, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not value.isprintable():
        raise ValueError(f"{label} must be a printable exact identity up to {maximum} characters")


def _request(params):
    required = {"surface_name", "regions", "frame_start", "frame_end"}
    allowed = (
        required
        | set(INTEGER_SETTINGS)
        | {"substeps", "max_samples", "distance_epsilon_m", "proximity_distance_m"}
    )
    if not isinstance(params, dict) or not required <= params.keys() or params.keys() - allowed:
        raise ValueError(
            "Regional contacts require explicit surface, regions and frame bounds only"
        )
    times = contact_analysis.sample_times(params)
    _name(params["surface_name"], "surface_name", 256)
    settings = {
        name: contact_analysis._integer(params.get(name, default), low, high, name)
        for name, (default, low, high) in INTEGER_SETTINGS.items()
    }
    for name, default, low, high in (
        ("distance_epsilon_m", 1e-6, 1e-9, 1e-3),
        ("proximity_distance_m", 0.005, 1e-9, 1),
    ):
        settings[name] = contact_analysis._number(params.get(name, default), low, high, name)
    if settings["proximity_distance_m"] < settings["distance_epsilon_m"]:
        raise ValueError("proximity_distance_m must be at least distance_epsilon_m")
    regions = params["regions"]
    if not isinstance(regions, list) or not 1 <= len(regions) <= 8:
        raise ValueError("regions must contain 1..8 explicit triangle regions")
    identities, selected, total = set(), set(), 0
    for region in regions:
        if not isinstance(region, dict) or set(region) != {
            "id",
            "object_name",
            "topology_sha256",
            "triangles",
        }:
            raise ValueError("Region requires id, object_name, topology_sha256 and triangles")
        _name(region["id"], "region id", 64)
        _name(region["object_name"], "object_name", 256)
        if region["id"] in identities:
            raise ValueError("Region ids must be unique")
        identities.add(region["id"])
        if not isinstance(region["topology_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", region["topology_sha256"]
        ):
            raise ValueError("topology_sha256 must be a 64-character lowercase hexadecimal digest")
        triangles = region["triangles"]
        if not isinstance(triangles, list) or not 1 <= len(triangles) <= 16384:
            raise ValueError("Each region requires 1..16384 explicit triangles")
        total += len(triangles)
        if total > settings["max_region_triangles"]:
            raise ValueError("Selected region triangle budget exceeded")
        for triangle in triangles:
            if not isinstance(triangle, dict) or set(triangle) != {"index", "vertices"}:
                raise ValueError("Each triangle requires its index and ordered vertices")
            index = contact_analysis._integer(triangle["index"], 0, 9999999, "triangle index")
            vertices = triangle["vertices"]
            if not isinstance(vertices, list) or len(vertices) != 3:
                raise ValueError("Triangle vertices must contain exactly three indices")
            for vertex in vertices:
                contact_analysis._integer(vertex, 0, 999999, "triangle vertex")
            if len(set(vertices)) != 3:
                raise ValueError("Triangle vertices must be distinct")
            identity = (region["object_name"], index)
            if identity in selected:
                raise ValueError("Duplicate/overlapping region triangle identities are unsupported")
            selected.add(identity)
    return times, settings


def _bone_or_group(target, name, label):
    if target is None or not (
        target.type == "ARMATURE"
        and name in target.data.bones
        or target.type == "MESH"
        and name in target.vertex_groups
    ):
        raise ValueError(f"Regional {label} bone/vertex-group target is missing")


def _constraint_references(constraint):
    if not math.isfinite(constraint.influence):
        raise ValueError("Regional constraint influence must be finite")
    if constraint.mute or constraint.influence == 0:
        return False
    required = {
        "CHILD_OF",
        "COPY_LOCATION",
        "COPY_ROTATION",
        "COPY_SCALE",
        "COPY_TRANSFORMS",
        "DAMPED_TRACK",
        "TRACK_TO",
        "LOCKED_TRACK",
        "LIMIT_DISTANCE",
        "STRETCH_TO",
        "TRANSFORM",
    }
    if constraint.type in required and constraint.target is None:
        raise ValueError("Active regional constraint is missing its required target")
    for target_field, bone_field in (
        ("target", "subtarget"),
        ("pole_target", "pole_subtarget"),
        ("space_object", "space_subtarget"),
    ):
        name = getattr(constraint, bone_field, "")
        if name:
            _bone_or_group(getattr(constraint, target_field, None), name, "constraint")
    if constraint.type == "ARMATURE":
        if not constraint.targets:
            raise ValueError("Active regional armature constraint requires target bones")
        for target in constraint.targets:
            if not math.isfinite(target.weight):
                raise ValueError("Regional armature constraint weight must be finite")
            if target.weight:
                if target.target is None or target.target.type != "ARMATURE":
                    raise ValueError("Regional armature constraint target must be an armature")
                _bone_or_group(target.target, target.subtarget, "armature constraint")
    return True


def _admit_graph(objects):
    for obj in objects:
        if obj.parent_type == "BONE":
            if obj.parent is None or obj.parent.type != "ARMATURE":
                raise ValueError("Regional bone parent must be an existing armature")
            _bone_or_group(obj.parent, obj.parent_bone, "parent")
        for constraint in skin_contacts._constraints(obj):
            _constraint_references(constraint)
        paths = {
            modifier.path_from_id("levels")
            for modifier in obj.modifiers
            if modifier.type in {"SUBSURF", "MULTIRES"}
        }
        animation = obj.animation_data
        if not paths or animation is None:
            continue
        curves = list(animation.drivers)
        if animation.action is not None:
            curves.extend(
                curve
                for layer in animation.action.layers
                for strip in layer.strips
                for bag in strip.channelbags
                if bag.slot_handle == animation.action_slot.handle
                for curve in bag.fcurves
            )
        if any(curve.data_path in paths for curve in curves):
            raise ValueError(
                "Animated subdivision topology levels are unsupported before geometry evaluation"
            )


def _validate_dependencies(objects, graph):
    for obj in objects:
        for owner in (obj, obj.evaluated_get(graph)):
            for constraint in skin_contacts._constraints(owner):
                if _constraint_references(constraint) and not constraint.is_valid:
                    raise ValueError("Active regional constraint evaluation failed")
            for block in skin_contacts._blocks(owner):
                animation = block.animation_data
                if animation is not None:
                    for curve in animation.drivers:
                        if not curve.is_valid or not curve.driver.is_valid:
                            raise ValueError(
                                "Native driver evaluation failed in regional dependencies"
                            )


def _geometry(
    obj,
    graph,
    unit,
    remaining_vertices,
    remaining_work,
    surface_limit=None,
    *,
    extractor=None,
    triangle_limit=None,
):
    evaluated, mesh = obj.evaluated_get(graph), None
    try:
        mesh = (
            evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
            if extractor is not None
            else evaluated.to_mesh()
        )
        mesh.calc_loop_triangles()
        count, triangle_count = len(mesh.vertices), len(mesh.loop_triangles)
        elements = count + 3 * triangle_count + 2 * len(mesh.edges) + len(mesh.loops)
        if triangle_limit is not None and triangle_count > triangle_limit:
            raise ValueError("Evaluated regional triangle budget exceeded before extraction")
        if count > remaining_vertices or elements > remaining_work:
            raise ValueError("Evaluated regional geometry/sample work budget exceeded")
        if surface_limit is not None and (not triangle_count or triangle_count > surface_limit):
            raise ValueError("Surface triangle geometry is empty or exceeds the configured budget")
        coordinates = array("f", [0]) * (count * 3)
        triangles = array("i", [0]) * (triangle_count * 3)
        edges = array("i", [0]) * (len(mesh.edges) * 2)
        loops = array("i", [0]) * len(mesh.loops)
        mesh.vertices.foreach_get("co", coordinates)
        mesh.loop_triangles.foreach_get("vertices", triangles)
        mesh.edges.foreach_get("vertices", edges)
        mesh.loops.foreach_get("vertex_index", loops)
        matrix = evaluated.matrix_world
        if not all(math.isfinite(value) for row in matrix for value in row):
            raise ValueError("Regional dependency transform must be finite")
        try:
            matrix.inverted()
        except ValueError as error:
            raise ValueError("Regional dependency transform must be nonsingular") from error
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Regional dependency coordinates must be finite")
        from mathutils import Vector

        world = [
            tuple((matrix @ Vector(coordinates[i : i + 3])) * unit)
            for i in range(0, len(coordinates), 3)
        ]
        if not all(math.isfinite(value) for point in world for value in point):
            raise ValueError("Regional world-metre coordinates must be finite")
        topology = hashlib.sha256(
            str((count, len(mesh.polygons))).encode()
            + triangles.tobytes()
            + edges.tobytes()
            + loops.tobytes()
        ).hexdigest()
        result = {
            "topology_sha256": topology,
            "evaluated_vertices": count,
            "evaluated_triangles": triangle_count,
            "evaluated_polygons": len(mesh.polygons),
            "evaluated_edges": len(mesh.edges),
            "evaluated_loops": len(mesh.loops),
            "work_elements": elements,
            "indices": [tuple(triangles[i : i + 3]) for i in range(0, len(triangles), 3)],
            "world_vertices": world,
        }
        if extractor is not None:
            result["extracted"] = extractor(evaluated, mesh)
        return result
    finally:
        if mesh is not None:
            evaluated.to_mesh_clear()


def _sample_geometry(objects, surface, context, unit, settings, topology, work):
    graph = context.evaluated_depsgraph_get()
    _validate_dependencies(objects, graph)
    result, vertices = {}, 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        geometry = _geometry(
            obj,
            graph,
            unit,
            settings["max_evaluated_vertices"] - vertices,
            skin_contacts.MAX_WORK - work,
            settings["max_surface_triangles"] if obj == surface else None,
        )
        vertices += geometry["evaluated_vertices"]
        work += geometry["work_elements"]
        digest = geometry["topology_sha256"]
        previous = topology.setdefault(
            obj.name,
            {
                key: value
                for key, value in geometry.items()
                if key not in {"indices", "world_vertices"}
            },
        )
        if digest != previous["topology_sha256"]:
            raise ValueError("Evaluated dependency topology changed; triangle identity is invalid")
        result[obj] = geometry
    return result, work


def _triangles(geometry, identities=None):
    vertices, indices = geometry["world_vertices"], geometry["indices"]
    if identities is None:
        identities = range(len(indices))
    return [tuple(vertices[index] for index in indices[identity]) for identity in identities]


def inspect_regions(params, context=None):
    """Return sampled surface relations; exhaustions refuse without a partial clear result."""
    times, settings = _request(params)
    from .rigging import checked_context, scene_object

    context = checked_context(context)
    unit = float(context.scene.unit_settings.scale_length)
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError("Scene unit scale must be finite and positive")
    fps, fps_base = context.scene.render.fps, float(context.scene.render.fps_base)
    if not math.isfinite(fps_base) or fps_base <= 0 or fps <= 0:
        raise ValueError("Source frame rate and fps_base must be finite and positive")
    effective_fps = fps / fps_base
    time_basis = {
        "fps": fps,
        "fps_base": fps_base,
        "effective_fps": effective_fps,
        "interval_duration_seconds": (times[-1] - times[0]) / effective_fps,
    }
    source_surface = scene_object(context, params["surface_name"], "MESH")
    sources = {
        region["object_name"]: scene_object(context, region["object_name"], "MESH")
        for region in params["regions"]
    }
    if source_surface in sources.values():
        raise ValueError("Regions must be distinct from the contact surface")
    objects = skin_contacts._dependencies(
        [source_surface, *sources.values()], context, settings["max_evaluated_vertices"], len(times)
    )
    _admit_graph(objects)
    budget = region_geometry.PairBudget(
        settings["max_candidate_visits"], settings["max_pair_checks"]
    )
    samples, topology, coverage = [], {}, []
    work, example_count = 0, 0
    totals = dict.fromkeys(RELATIONS, 0)
    with skin_contacts._isolated_scene(objects, context) as (isolated, mapping):
        surface = mapping[source_surface]
        copied = [mapping[obj] for obj in objects]
        for time in times:
            frame = math.floor(time)
            isolated.scene.frame_set(frame, subframe=time - frame)
            geometry, work = _sample_geometry(
                copied, surface, isolated, unit, settings, topology, work
            )
            surface_triangles = _triangles(geometry[surface])
            entries = []
            for region in params["regions"]:
                obj = mapping[sources[region["object_name"]]]
                mesh = geometry[obj]
                if mesh["topology_sha256"] != region["topology_sha256"]:
                    raise ValueError(
                        "Caller topology_sha256 does not match evaluated region topology"
                    )
                indices = []
                for triangle in region["triangles"]:
                    index = triangle["index"]
                    if (
                        index >= len(mesh["indices"])
                        or tuple(triangle["vertices"]) != mesh["indices"][index]
                    ):
                        raise ValueError(
                            "Explicit ordered triangle identity does not match evaluated geometry"
                        )
                    indices.append(index)
                if not samples:
                    coverage.append(
                        {
                            "id": region["id"],
                            "object_name": region["object_name"],
                            "requested_topology_sha256": region["topology_sha256"],
                            "evaluated_topology_sha256": mesh["topology_sha256"],
                            "selected_triangles": len(indices),
                            "evaluated_object_triangles": mesh["evaluated_triangles"],
                            "triangle_fraction": len(indices) / mesh["evaluated_triangles"],
                            "triangle_indices": indices,
                        }
                    )
                result = region_geometry.compare_regions(
                    _triangles(mesh, indices),
                    surface_triangles,
                    budget=budget,
                    distance_epsilon_m=settings["distance_epsilon_m"],
                    proximity_distance_m=settings["proximity_distance_m"],
                    max_examples=settings["max_examples"] - example_count,
                )
                for example in result["examples"]:
                    example["region_triangle_index"] = indices[example["first_index"]]
                    example["surface_triangle_index"] = example["second_index"]
                example_count += len(result["examples"])
                for relation in RELATIONS:
                    totals[relation] += result["counts"][relation]
                entries.append({"id": region["id"], **result})
            samples.append({"frame": frame, "subframe": time - frame, "regions": entries})
        dependencies = [
            {"object_name": obj.name, **topology[mapping[obj].name]}
            for obj in objects
            if obj.type == "MESH"
        ]
    return {
        "schema_version": "1.0",
        "command": "contacts.inspect_regions",
        "surface_name": params["surface_name"],
        "regions": coverage,
        "region_definitions": params["regions"],
        "sample_times": times,
        "samples": samples,
        "coverage": "complete_at_samples",
        "containment_checked": False,
        "temporal_coverage": {
            "every_integer_frame": True,
            "substeps": params.get("substeps", 1),
            "continuous_between_samples": False,
        },
        "unit_scale_meters": unit,
        "time_basis": time_basis,
        "settings": settings,
        "counts": totals,
        "dependency_names": [obj.name for obj in objects],
        "dependency_topology": dependencies,
        "sampled_geometry_work_elements": work,
        "pair_work": {
            "candidate_visits": budget.candidate_visits,
            "narrow_checks": budget.narrow_checks,
        },
        "preservation": {
            "strategy": "isolated_owned_scene",
            "source_scene_time_changed": False,
            "cleanup": "temporary scene and object/mesh/key/armature IDs disposed on success or failure",
        },
        "limits": [
            "Relations concern explicitly selected evaluated triangles at requested times, not anatomical coverage or artistic acceptance",
            "Crossing is a boundary intersection; no signed penetration depth, volume containment or balance is inferred",
            "Coplanar overlap is tolerance-coplanar contact and is not automatically a defect",
            "Closest distance is radius-limited, not an unrestricted global clearance distance",
            "No continuous collision guarantee applies between the full requested integer/subframe samples",
            "All copied mesh dependency topology is checked and counted; unsupported graph/handlers or exhausted budgets fail the entire request",
            "Coordinate precision remains bounded by Blender mesh and transform precision; synchronous work limits are not OS memory or time guarantees",
        ],
    }
