"""Read-only explicit evaluated membership to a reusable triangle-region manifest."""

from __future__ import annotations

import math

from . import region_authoring as region_selection
from . import region_contacts, skin_contacts


def _group_extractor(source, group_name, maximum):
    group = source.vertex_groups.get(group_name)
    if group is None:
        raise ValueError("Exact case-sensitive vertex group is missing from the source object")
    expected = tuple((item.name, item.index) for item in source.vertex_groups)
    group_index = group.index

    def extract(evaluated, mesh):
        if tuple((item.name, item.index) for item in evaluated.vertex_groups) != expected:
            raise ValueError("Evaluated vertex-group name/index identity is unavailable or changed")
        entries = sum(len(vertex.groups) for vertex in mesh.vertices)
        if entries > maximum:
            raise ValueError(
                "Evaluated deform-group entry budget exceeded before membership traversal"
            )
        if not entries:
            raise ValueError(
                "Evaluated deform-group membership is empty or its layer is unavailable"
            )
        selected = []
        group_count = len(expected)
        for vertex in mesh.vertices:
            found = set()
            for entry in vertex.groups:
                if not 0 <= entry.group < group_count or entry.group in found:
                    raise ValueError("Evaluated deform-group index metadata is invalid")
                found.add(entry.group)
                if not math.isfinite(entry.weight) or not 0 <= entry.weight <= 1:
                    raise ValueError(
                        "Evaluated deform-group weights must be finite and within 0..1"
                    )
                if entry.group == group_index and entry.weight > 0:
                    selected.append(vertex.index)
                    if len(selected) > 65536:
                        raise ValueError(
                            "Evaluated group selection exceeds the 65536-vertex budget"
                        )
        if not selected:
            raise ValueError("Vertex group has no strictly positive evaluated membership")
        return {"vertex_indices": selected, "group_entries_examined": entries}

    return extract


def describe_region(params, context=None):
    """Describe finite topology at one explicit time; geometric relations remain unchecked."""
    request = region_selection.validate_request(params)
    from .rigging import checked_context, scene_object

    context = checked_context(context)
    source = scene_object(context, request["object_name"], "MESH")
    unit = float(context.scene.unit_settings.scale_length)
    fps, fps_base = context.scene.render.fps, float(context.scene.render.fps_base)
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError("Scene unit scale must be finite and positive")
    if not math.isfinite(fps_base) or fps_base <= 0 or fps <= 0:
        raise ValueError("Source frame rate and FPS base must be finite and positive")
    objects = skin_contacts._dependencies(
        [source], context, request["max_evaluated_vertices"], sample_count=1
    )
    region_contacts._admit_graph(objects)
    source_triangles = sum(
        max(len(polygon.vertices) - 2, 0)
        for obj in objects
        if obj.type == "MESH"
        for polygon in obj.data.polygons
    )
    if source_triangles > request["max_evaluated_triangles"]:
        raise ValueError("All-dependency source triangle budget exceeded before copying")
    extractor = (
        _group_extractor(source, request["vertex_group"], request["max_group_entries"])
        if "vertex_group" in request
        else None
    )
    work, vertices, triangles = 0, 0, 0
    dependency_geometry = []
    source_geometry = None
    with skin_contacts._isolated_scene(objects, context) as (isolated, mapping):
        copied = [mapping[obj] for obj in objects]
        if extractor is not None and tuple(
            (g.name, g.index) for g in mapping[source].vertex_groups
        ) != tuple((g.name, g.index) for g in source.vertex_groups):
            raise ValueError("Copied vertex-group name/index identity changed")
        time = request["sample_time"]
        frame = math.floor(time)
        isolated.scene.frame_set(frame, subframe=time - frame)
        graph = isolated.evaluated_depsgraph_get()
        region_contacts._validate_dependencies(copied, graph)
        sample = {
            "requested_time": time,
            "frame": isolated.scene.frame_current,
            "subframe": float(isolated.scene.frame_subframe),
            "effective_time": isolated.scene.frame_current + float(isolated.scene.frame_subframe),
        }
        for original in objects:
            if original.type != "MESH":
                continue
            geometry = region_contacts._geometry(
                mapping[original],
                graph,
                unit,
                request["max_evaluated_vertices"] - vertices,
                skin_contacts.MAX_WORK - work,
                extractor=extractor if original == source else None,
                triangle_limit=request["max_evaluated_triangles"] - triangles,
            )
            vertices += geometry["evaluated_vertices"]
            triangles += geometry["evaluated_triangles"]
            work += geometry["work_elements"]
            if triangles > request["max_evaluated_triangles"]:
                raise ValueError("All-dependency evaluated triangle budget exceeded")
            dependency_geometry.append(
                {
                    "object_name": original.name,
                    **{
                        key: value
                        for key, value in geometry.items()
                        if key not in {"indices", "world_vertices", "extracted"}
                    },
                }
            )
            if original == source:
                source_geometry = geometry
        if (
            source_geometry is None
            or not source_geometry["evaluated_vertices"]
            or not source_geometry["evaluated_triangles"]
        ):
            raise ValueError("Selected object has empty evaluated triangle geometry")
        selection = (
            source_geometry["extracted"]["vertex_indices"]
            if extractor is not None
            else request["vertex_indices"]
        )
        result = region_selection.select_region(
            object_name=source.name,
            region_id=request["region_id"],
            topology_sha256=source_geometry["topology_sha256"],
            vertex_count=source_geometry["evaluated_vertices"],
            triangles=source_geometry["indices"],
            vertex_indices=selection,
            max_region_triangles=request["max_region_triangles"],
            expected_topology_sha256=request.get("expected_topology_sha256"),
        )
        group_entries = source_geometry.get("extracted", {}).get("group_entries_examined", 0)
    result.update(
        {
            "schema_version": "1.0",
            "command": "contacts.describe_region",
            "selector": {
                "mode": "vertex_group" if extractor is not None else "vertex_indices",
                "membership_policy": "evaluated_weight_strictly_positive"
                if extractor is not None
                else "explicit_evaluated_vertex_indices",
                **({"vertex_group": request["vertex_group"]} if extractor is not None else {}),
            },
            "sample": sample,
            "time_basis": {"fps": fps, "fps_base": fps_base, "effective_fps": fps / fps_base},
            "unit_scale_meters": unit,
            "dependency_names": [obj.name for obj in objects],
            "dependency_geometry": dependency_geometry,
            "evaluated_vertices_all_dependencies": vertices,
            "evaluated_triangles_all_dependencies": triangles,
            "geometry_work_elements": work,
            "group_entries_examined": group_entries,
            "settings": {
                key: request[key]
                for key in (
                    "max_evaluated_vertices",
                    "max_evaluated_triangles",
                    "max_region_triangles",
                    "max_group_entries",
                )
            },
            "preservation": {
                "strategy": "isolated_owned_scene",
                "source_scene_time_changed": False,
                "cleanup": "temporary scene and object/mesh/key/armature IDs disposed on success or failure",
            },
            "limits": [
                "Explicit evaluated membership describes topology; it does not infer anatomy or test geometric relations, area, volume containment or artistic acceptance",
                "Every returned triangle requires all three selected evaluated vertices; selected vertices without complete triangles are reported uncovered",
                "Without expected_topology_sha256, indices deliberately describe current evaluated topology at the explicit sample and cannot detect stale caller intent",
                "Topology identity is Blender/platform-specific and excludes positions and group membership; changed weights require a new description to select the new group",
                "Group membership uses strictly positive evaluated weights, including interpolated subdivision vertices; no source-index fallback",
                "Only the admitted independent local active-action/native-driver dependency closure is copied; unsupported graphs, topology animation or exhausted budgets refuse",
                "The full manifest refuses if output transport bounds are exceeded; no selection is truncated",
            ],
        }
    )
    region_selection.enforce_response_budget(result)
    return result
