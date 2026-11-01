"""Static-mesh derivatives and bounded surface evidence; no automatic acceptance."""

import math
import threading

import bmesh
import bpy
from mathutils.bvhtree import BVHTree


def _context(context=None):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Use Blender main thread")
    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Object Mode is required")
    return context


def _source(name, context, *, repair=False):
    matches = [o for o in context.scene.objects if o.name == name]
    if len(matches) != 1 or matches[0].type != "MESH":
        raise ValueError("Use a unique mesh name in the active scene")
    source = matches[0]
    if repair and (
        source.library
        or source.data.library
        or source.override_library
        or source.data.shape_keys
        or source.vertex_groups
        or source.animation_data
        or source.data.animation_data
    ):
        raise ValueError(
            "Derivative operation requires a local static mesh without weights or shape keys"
        )
    return source


def _params(params, allowed):
    if not isinstance(params, dict) or set(params) - set(allowed):
        raise ValueError("Unknown parameters")
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be boolean")


def _float(value, low, high, label):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"Invalid {label}")


def _evaluated_mesh(source, context):
    evaluated = source.evaluated_get(context.evaluated_depsgraph_get())
    return bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=context.evaluated_depsgraph_get()
    )


def _derivative(source, mesh, name, role, context):
    obj = bpy.data.objects.new(name, mesh)
    try:
        obj.matrix_world = source.matrix_world.copy()
        obj["framewright_source"] = source.name
        obj["framewright_role"] = role
        context.scene.collection.objects.link(obj)
        obj.hide_render = True
        obj.hide_viewport = True
        return obj
    except Exception:
        bpy.data.objects.remove(obj, do_unlink=True)
        raise


def create_lod(params, context=None):
    _params(params, {"object_name", "ratio", "level", "dry_run"})
    context = _context(context)
    source = _source(params.get("object_name"), context, repair=True)
    ratio = params.get("ratio", 0.5)
    level = params.get("level", 1)
    _float(ratio, 0.01, 0.99, "ratio")
    if type(level) is not int or not 1 <= level <= 8:
        raise ValueError("level must be 1..8")
    result = {
        "source": source.name,
        "ratio": ratio,
        "level": level,
        "dry_run": params.get("dry_run", True),
        "visual_acceptance": False,
        "limitations": [
            "Static geometry only; inspect silhouette, thin parts, UVs and moving transitions before acceptance"
        ],
    }
    staged = None
    mesh = None
    result_mesh = None
    derivative = None
    try:
        mesh = _evaluated_mesh(source, context)
        if not mesh.polygons:
            raise ValueError("Evaluated source must have surface geometry")
        if result["dry_run"]:
            return result
        staged = bpy.data.objects.new("FW_LOD_Staging", mesh)
        context.scene.collection.objects.link(staged)
        modifier = staged.modifiers.new("Framewright_Decimate", "DECIMATE")
        modifier.ratio = ratio
        modifier.use_collapse_triangulate = True
        context.view_layer.update()
        result_mesh = _evaluated_mesh(staged, context)
        if not result_mesh.polygons:
            raise ValueError("Requested reduction removed all surface geometry")
        derivative = _derivative(source, result_mesh, f"{source.name}_LOD{level}", "lod", context)
        derivative["framewright_lod_level"] = level
        result.update(
            derivative=derivative.name,
            vertices=len(result_mesh.vertices),
            polygons=len(result_mesh.polygons),
            hidden=True,
        )
        return result
    except Exception:
        if derivative:
            bpy.data.objects.remove(derivative, do_unlink=True)
        if result_mesh and result_mesh.users == 0:
            bpy.data.meshes.remove(result_mesh)
        raise
    finally:
        if staged:
            bpy.data.objects.remove(staged, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def create_collision(params, context=None):
    _params(params, {"object_name", "dry_run"})
    context = _context(context)
    source = _source(params.get("object_name"), context, repair=True)
    if len(source.data.vertices) < 4:
        raise ValueError("Convex hull needs at least four non-coplanar points")
    result = {
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "type": "convex_hull",
        "limitations": [
            "Concavity is approximated; native contact and walkability still require review"
        ],
        "visual_acceptance": False,
    }
    if result["dry_run"]:
        return result
    temporary = bmesh.new()
    mesh = None
    derivative = None
    try:
        mesh = _evaluated_mesh(source, context)
        temporary.from_mesh(mesh)
        hull = bmesh.ops.convex_hull(
            temporary, input=list(temporary.verts), use_existing_faces=False
        )
        unused = list(set(hull.get("geom_interior", []) + hull.get("geom_unused", [])))
        if unused:
            bmesh.ops.delete(temporary, geom=unused, context="VERTS")
        if abs(temporary.calc_volume()) < 1e-12:
            raise ValueError("Convex hull has no volume")
        temporary.to_mesh(mesh)
        mesh.update()
        derivative = _derivative(source, mesh, f"UCX_{source.name}_00", "collision", context)
        derivative.display_type = "WIRE"
        result.update(
            derivative=derivative.name,
            vertices=len(mesh.vertices),
            polygons=len(mesh.polygons),
            hidden=True,
        )
        return result
    except Exception:
        if derivative:
            bpy.data.objects.remove(derivative, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        temporary.free()


def _surface_tree(mesh, matrix):
    vertices = [matrix @ vertex.co for vertex in mesh.vertices]
    if not vertices or any(not math.isfinite(value) for vertex in vertices for value in vertex):
        raise ValueError("Both meshes need finite world-space vertices")
    mesh.calc_loop_triangles()
    triangles = []
    degenerate = 0
    for triangle in mesh.loop_triangles:
        indices = tuple(triangle.vertices)
        a, b, c = (vertices[index] for index in indices)
        area_squared = (b - a).cross(c - a).length_squared
        if not math.isfinite(area_squared):
            raise ValueError("Surface triangle area exceeds finite world-space range")
        if area_squared == 0:
            degenerate += 1
        else:
            triangles.append(indices)
    if not triangles:
        raise ValueError("Both meshes need non-degenerate surface geometry")
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    bounds = [
        [function(vertex[axis] for vertex in vertices) for axis in range(3)]
        for function in (min, max)
    ]
    return vertices, tree, bounds, len(triangles), degenerate


def _directional_distance(vertices, target_tree, target_triangles, maximum):
    total = len(vertices)
    count = min(total, maximum)
    indices = [i * total // count for i in range(count)]
    distances, greatest = [], None
    for index in indices:
        location, _normal, _triangle, distance = target_tree.find_nearest(vertices[index])
        if (
            distance is None
            or not math.isfinite(distance)
            or location is None
            or any(not math.isfinite(value) for value in location)
        ):
            raise ValueError("Mesh has no valid surface for distance queries")
        distances.append(distance)
        if greatest is None or distance > greatest["distance"]:
            greatest = {
                "vertex_index": index,
                "world_position": list(vertices[index]),
                "nearest_surface_position": list(location),
                "distance": distance,
            }
    return {
        "samples": count,
        "query_vertices": total,
        "omitted_vertices": total - count,
        "target_triangles": target_triangles,
        "coverage": "sampled_vertices" if count < total else "all_query_vertices",
        "sampling": "vertex indices floor(i * vertex_count / sample_count)",
        "maximum_distance": max(distances),
        "mean_distance": sum(distances) / count,
        "maximum_sample": greatest,
    }


def compare_surface(params, context=None):
    _params(params, {"source_name", "candidate_name", "max_samples"})
    context = _context(context)
    source = _source(params.get("source_name"), context)
    candidate = _source(params.get("candidate_name"), context)
    maximum = params.get("max_samples", 10000)
    if type(maximum) is not int or not 1 <= maximum <= 100000:
        raise ValueError("max_samples must be 1..100000")
    source_mesh = None
    candidate_mesh = None
    try:
        source_mesh = _evaluated_mesh(source, context)
        candidate_mesh = _evaluated_mesh(candidate, context)
        depsgraph = context.evaluated_depsgraph_get()
        source_points, source_tree, source_bounds, source_triangles, source_degenerate = (
            _surface_tree(source_mesh, source.evaluated_get(depsgraph).matrix_world)
        )
        (
            candidate_points,
            candidate_tree,
            candidate_bounds,
            candidate_triangles,
            candidate_degenerate,
        ) = _surface_tree(candidate_mesh, candidate.evaluated_get(depsgraph).matrix_world)
        forward = _directional_distance(candidate_points, source_tree, source_triangles, maximum)
        reverse = _directional_distance(source_points, candidate_tree, candidate_triangles, maximum)
        samples = forward["samples"] + reverse["samples"]
        complete = not (forward["omitted_vertices"] or reverse["omitted_vertices"])
        return {
            "schema_version": "1.1",
            "source": source.name,
            "candidate": candidate.name,
            # Retain the original candidate-to-source fields and meanings.
            "samples": forward["samples"],
            "candidate_vertices": len(candidate_points),
            "coverage": "sampled" if forward["omitted_vertices"] else "all_candidate_vertices",
            "maximum_distance": forward["maximum_distance"],
            "mean_distance": forward["mean_distance"],
            "units": "Blender world units",
            "direction": "candidate vertices to source surface",
            "sample_budget_per_direction": maximum,
            "candidate_to_source": forward,
            "source_to_candidate": reverse,
            "bidirectional": {
                "maximum_distance": max(forward["maximum_distance"], reverse["maximum_distance"]),
                "samples": samples,
                "sample_weighted_mean_distance": (
                    forward["mean_distance"] * forward["samples"]
                    + reverse["mean_distance"] * reverse["samples"]
                )
                / samples,
                "coverage": "all_vertices_both_meshes" if complete else "sampled_vertices",
                "metric": "sampled bidirectional vertex-to-triangulated-surface distance; not Hausdorff",
            },
            "bounds": {
                "source": source_bounds,
                "candidate": candidate_bounds,
                "maximum_component_difference": max(
                    abs(a - b)
                    for source_vector, candidate_vector in zip(
                        source_bounds, candidate_bounds, strict=True
                    )
                    for a, b in zip(source_vector, candidate_vector, strict=True)
                ),
                "kind": "world-space axis-aligned bounds of all evaluated vertices",
            },
            "geometry": {
                "source_valid_triangles": source_triangles,
                "candidate_valid_triangles": candidate_triangles,
                "source_degenerate_triangles_excluded": source_degenerate,
                "candidate_degenerate_triangles_excluded": candidate_degenerate,
            },
            "visual_acceptance": False,
            "limitations": [
                "Both directions query bounded vertex samples against full evaluated triangle surfaces; no face-interior query samples",
                "Even all vertices do not give a continuous Hausdorff bound; thin details between samples can be missed",
                "max_samples is per direction; BVH construction and bounds still use complete evaluated geometry",
                "Means are weighted by sampled vertex count, not surface area; loose vertices may contribute samples",
                "Current frame/view-layer only; silhouette, shadows, topology, UVs and moving transitions need independent review",
                "Legacy top-level distance and coverage fields remain candidate-to-source; use bidirectional for the combined evidence",
            ],
        }
    finally:
        if source_mesh:
            bpy.data.meshes.remove(source_mesh)
        if candidate_mesh:
            bpy.data.meshes.remove(candidate_mesh)
