"""Bounded evaluated-vertex contacts sampled on isolated local dependency copies."""

from __future__ import annotations

import hashlib
import json
import math
import re
from array import array
from contextlib import contextmanager

from . import contact_analysis

MAX_DEPENDENCIES = 64
MAX_WORK = 200_000_000
MAX_KEY_POINTS = 2_000_000
MODIFIERS = {"ARMATURE", "SUBSURF", "MULTIRES"}
CONSTRAINTS = {
    "ARMATURE",
    "CHILD_OF",
    "COPY_LOCATION",
    "COPY_ROTATION",
    "COPY_SCALE",
    "COPY_TRANSFORMS",
    "DAMPED_TRACK",
    "TRACK_TO",
    "LOCKED_TRACK",
    "IK",
    "LIMIT_DISTANCE",
    "LIMIT_LOCATION",
    "LIMIT_ROTATION",
    "LIMIT_SCALE",
    "MAINTAIN_VOLUME",
    "STRETCH_TO",
    "TRANSFORM",
}


def _request(params):
    if not isinstance(params, dict) or "step" in params:
        raise ValueError(
            "Skin contacts sample every frame; step and non-object requests are unsupported"
        )
    rigid = dict(params)
    maximum = contact_analysis._integer(
        rigid.pop("max_evaluated_vertices", 250000), 1, 1_000_000, "max_evaluated_vertices"
    )
    markers = params.get("markers")
    if not isinstance(markers, list) or not 1 <= len(markers) <= 32:
        raise ValueError("markers must contain 1..32 explicit evaluated-skin points")
    rigid["markers"] = []
    for marker in markers:
        if not isinstance(marker, dict) or set(marker) != {
            "id",
            "object_name",
            "vertex_indices",
            "weights",
        }:
            raise ValueError(
                "Skin marker requires id, object_name, vertex_indices and weights only"
            )
        indices, weights = marker["vertex_indices"], marker["weights"]
        if not isinstance(indices, list) or len(indices) not in (1, 3):
            raise ValueError("vertex_indices must select one vertex or three triangle vertices")
        for value in indices:
            contact_analysis._integer(value, 0, 999999, "vertex index")
        if len(set(indices)) != len(indices):
            raise ValueError("vertex_indices must be unique")
        if not isinstance(weights, list) or len(weights) != len(indices):
            raise ValueError("weights must match the selected one or three vertices")
        for value in weights:
            contact_analysis._number(value, 0, 1, "barycentric weight")
        if abs(sum(weights) - 1) > 1e-9:
            raise ValueError("Barycentric weights must sum to one")
        rigid["markers"].append(
            {"id": marker["id"], "object_name": marker["object_name"], "position": [0, 0, 0]}
        )
    times, _ = contact_analysis._request(rigid)
    return rigid, times, maximum


def _blocks(obj):
    result = [obj]
    if obj.data is not None:
        result.append(obj.data)
        keys = getattr(obj.data, "shape_keys", None)
        if keys is not None:
            result.append(keys)
    return result


def _constraints(obj):
    result = list(obj.constraints)
    if obj.type == "ARMATURE":
        result.extend(constraint for bone in obj.pose.bones for constraint in bone.constraints)
    return result


def _pointers(owner):
    """Only declared RNA ID pointers; never traverse arbitrary custom properties."""
    import bpy

    for prop in owner.bl_rna.properties:
        if prop.type == "POINTER":
            value = getattr(owner, prop.identifier, None)
            if isinstance(value, bpy.types.ID):
                yield owner, prop.identifier, value
    for target in getattr(owner, "targets", ()):
        yield from _pointers(target)


def _numeric_path(owner, path):
    # Prevent a path from crossing to a material, parent, target or other shared ID.
    quoted = r'\["(?:[^"\\]|\\.)+"\]'
    channel = r"[A-Za-z_]\w*(?:\[\d+\])?"
    constraint_channel = rf"(?:{channel}|targets\[\d+\]\.weight)"
    pattern = (
        rf"(?:{quoted}|{channel}|(?:bones|key_blocks|modifiers){quoted}\.{channel}|constraints{quoted}\.{constraint_channel}|"
        rf"pose\.bones{quoted}(?:{quoted}|\.{channel}|\.constraints{quoted}\.{constraint_channel}))"
    )
    if not isinstance(path, str) or len(path) > 2048 or not re.fullmatch(pattern, path):
        raise ValueError(
            f"Animation/driver path must stay within supported local numeric channels: {path!r}"
        )
    try:
        value = owner.path_resolve(path)
        if isinstance(value, str):
            custom = re.fullmatch(r'(.*)\[("(?:[^"\\]|\\.)+")\]', path)
            if custom:
                container = owner.path_resolve(custom[1]) if custom[1] else owner
                value = container[json.loads(custom[2])]
    except (ValueError, TypeError) as error:
        raise ValueError("Animation/driver path does not resolve on its copied owner") from error
    try:
        values = [value] if isinstance(value, (bool, int, float)) else list(value)
    except TypeError:
        values = []
    if not values or any(
        not isinstance(item, (bool, int, float)) or not math.isfinite(item) for item in values
    ):
        raise ValueError("Animation/driver dependencies must resolve to finite numeric channels")


def _animations(block):
    animation = block.animation_data
    if animation is None:
        return []
    if animation.nla_tracks:
        raise ValueError("Skin contact isolation currently supports active actions, not NLA tracks")
    action = animation.action
    if action:
        if action.library or action.override_library or animation.action_slot is None:
            raise ValueError("Contact animation needs a local active action and explicit slot")
        curves = [
            curve
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            if bag.slot_handle == animation.action_slot.handle
            for curve in bag.fcurves
        ]
        if len(curves) > 4096 or sum(len(curve.keyframe_points) for curve in curves) > 500000:
            raise ValueError("Contact action curve/key budget exceeded")
        for curve in curves:
            _numeric_path(block, curve.data_path)
    if len(animation.drivers) > 2048:
        raise ValueError("Contact native driver budget exceeded")
    return animation.drivers


def _dependencies(roots, context, maximum, sample_count):
    import bpy

    for name in (
        "frame_change_pre",
        "frame_change_post",
        "depsgraph_update_pre",
        "depsgraph_update_post",
    ):
        if getattr(bpy.app.handlers, name):
            raise ValueError(
                "Isolated contact sampling refuses registered frame/depsgraph handlers"
            )
    scene_objects = set(context.scene.objects)
    pending, result = list(roots), []
    while pending:
        obj = pending.pop()
        if obj in result:
            continue
        if (
            obj not in scene_objects
            or obj.library
            or obj.override_library
            or obj.type not in {"MESH", "ARMATURE", "EMPTY"}
        ):
            raise ValueError(
                "Contact dependencies must be explicit local mesh/armature/empty objects in the active scene"
            )
        result.append(obj)
        if len(result) > MAX_DEPENDENCIES:
            raise ValueError("Contact dependency budget exceeds 64 objects")
        if obj.instance_type != "NONE" or obj.particle_systems:
            raise ValueError(
                "Instances and particle simulations are unsupported contact dependencies"
            )
        if obj.parent:
            if obj.parent_type not in {"OBJECT", "BONE"}:
                raise ValueError("Only object/bone parenting is supported for contact dependencies")
            pending.append(obj.parent)
        for modifier in obj.modifiers:
            if modifier.type not in MODIFIERS or getattr(modifier, "is_external", False):
                raise ValueError(
                    "Unsupported modifier/cache/external multires dependency for skin contacts"
                )
            if modifier.type == "ARMATURE":
                if modifier.object is None:
                    raise ValueError("Contact armature modifier has no target")
                pending.append(modifier.object)
            elif modifier.levels > 3:
                raise ValueError("Contact subdivision level exceeds the bounded level-3 budget")
        for constraint in _constraints(obj):
            if constraint.type not in CONSTRAINTS:
                raise ValueError("Unsupported contact constraint dependency")
            for _, _, target in _pointers(constraint):
                if not isinstance(target, bpy.types.Object):
                    raise ValueError("Constraint dependency must be a local object")
                pending.append(target)
        for block in _blocks(obj):
            if block.library or block.override_library:
                raise ValueError("Linked/override contact data is unsupported")
            for curve in _animations(block):
                driver = curve.driver
                if not (
                    driver.type == "SCRIPTED"
                    and driver.is_simple_expression
                    or driver.type in {"SUM", "AVERAGE", "MIN", "MAX"}
                ) or any(
                    modifier.type != "GENERATOR"
                    or modifier.mode != "POLYNOMIAL"
                    or modifier.poly_order > 10
                    or any(not math.isfinite(value) for value in modifier.coefficients)
                    for modifier in curve.modifiers
                ):
                    raise ValueError(
                        "Only native simple-expression/aggregation drivers and bounded polynomials are supported"
                    )
                _numeric_path(block, curve.data_path)
                for variable in driver.variables:
                    if variable.type not in {
                        "SINGLE_PROP",
                        "TRANSFORMS",
                        "LOC_DIFF",
                        "ROTATION_DIFF",
                    }:
                        raise ValueError("Unsupported native contact driver variable")
                    for target in variable.targets:
                        if target.id is None:
                            raise ValueError("Missing native driver dependency")
                        if variable.type == "SINGLE_PROP":
                            _numeric_path(target.id, target.data_path)
                        elif not isinstance(target.id, bpy.types.Object):
                            raise ValueError("Transform driver dependency must be a local object")
                        if target.bone_target and (
                            not isinstance(target.id, bpy.types.Object)
                            or target.id.type != "ARMATURE"
                            or target.bone_target not in target.id.pose.bones
                        ):
                            raise ValueError("Driver bone dependency is missing")
                        owners = (
                            [target.id]
                            if isinstance(target.id, bpy.types.Object)
                            else [
                                candidate
                                for candidate in scene_objects
                                if target.id in _blocks(candidate)
                            ]
                        )
                        if len(owners) != 1:
                            raise ValueError(
                                "Driver data dependency is foreign or has ambiguous object ownership"
                            )
                        pending.append(owners[0])
    meshes = [obj for obj in result if obj.type == "MESH"]
    data = [obj.data for obj in result if obj.data is not None]
    if len(set(data)) != len(data):
        raise ValueError(
            "Shared data between contact dependencies needs explicit independent authoring"
        )
    if sum(len(obj.data.vertices) for obj in meshes) > maximum:
        raise ValueError("Contact source vertex budget exceeded before copying")
    loops = sum(len(obj.data.loops) for obj in meshes)
    triangles = sum(max(len(poly.vertices) - 2, 0) for obj in meshes for poly in obj.data.polygons)
    elements = (
        sum(len(obj.data.vertices) + 2 * len(obj.data.edges) for obj in meshes)
        + loops
        + 3 * triangles
    )
    if loops > 12 * maximum or triangles > 4 * maximum or elements * sample_count > MAX_WORK:
        raise ValueError("Contact source topology/sample work budget exceeded before copying")
    if any(len(obj.data.shape_keys.key_blocks) > 128 for obj in meshes if obj.data.shape_keys):
        raise ValueError("Contact shape-key count exceeds the 128-key budget")
    if (
        sum(
            len(obj.data.vertices) * len(obj.data.shape_keys.key_blocks)
            for obj in meshes
            if obj.data.shape_keys
        )
        > MAX_KEY_POINTS
    ):
        raise ValueError("Contact shape-key point budget exceeded before copying")
    if sum(len(obj.data.bones) for obj in result if obj.type == "ARMATURE") > 4096:
        raise ValueError("Contact bone budget exceeded before copying")
    return sorted(result, key=lambda obj: obj.name)


@contextmanager
def _isolated_scene(objects, context):
    import bpy

    scene, created, data_blocks, mapping = None, [], [], {}
    try:
        scene = bpy.data.scenes.new("Framewright_ContactSampling")
        scene.unit_settings.scale_length = context.scene.unit_settings.scale_length
        scene.render.fps = context.scene.render.fps
        scene.render.fps_base = context.scene.render.fps_base
        for source in objects:
            copy = source.copy()
            created.append(copy)
            if source.data is not None:
                copy.data = source.data.copy()
                data_blocks.append(copy.data)
                mapping[source.data] = copy.data
                if source.type == "MESH":
                    copy.data.materials.clear()
                    if source.data.shape_keys:
                        mapping[source.data.shape_keys] = copy.data.shape_keys
            copy.name = source.name + "_FW_ContactSample"
            mapping[source] = copy
            scene.collection.objects.link(copy)
            copy.hide_viewport = False
            copy.hide_render = False
            if copy.type == "ARMATURE":
                for bone in copy.pose.bones:
                    bone.custom_shape = None
        for source in objects:
            copy = mapping[source]
            if source.parent:
                copy.parent = mapping[source.parent]
                copy.matrix_parent_inverse = source.matrix_parent_inverse.copy()
            for owner in [*copy.modifiers, *_constraints(copy)]:
                for pointer_owner, field, target in _pointers(owner):
                    if target not in mapping:
                        if target not in mapping.values():
                            raise ValueError(
                                f"Unmapped dependency in isolated contact copy: {field} -> {target.name}"
                            )
                    else:
                        setattr(pointer_owner, field, mapping[target])
            for block in _blocks(copy):
                animation = block.animation_data
                if animation:
                    for curve in animation.drivers:
                        for variable in curve.driver.variables:
                            for target in variable.targets:
                                if target.id in mapping:
                                    target.id = mapping[target.id]
                                elif target.id not in mapping.values():
                                    raise ValueError(
                                        "Unmapped native driver in isolated contact copy"
                                    )
            copy.update_tag()
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            yield context, mapping
    finally:
        for copy in reversed(created):
            bpy.data.objects.remove(copy, do_unlink=True)
        if scene is not None:
            bpy.data.scenes.remove(scene)
        for data in reversed(data_blocks):
            if data.users == 0:
                (
                    bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.armatures
                ).remove(data)


class _EvaluatedMarkers:
    def __init__(self, definitions, maximum, sample_count, dependencies=(), surface=None):
        self.definitions = {item["id"]: item for item in definitions}
        self.maximum, self.sample_count = maximum, sample_count
        self.topology = {}
        self.max_work = 0
        self.dependencies = tuple(dependencies)
        self.surface = surface

    def __call__(self, markers, graph, surface_vertices, surface_triangles):
        from mathutils import Vector

        result, grouped = {}, {}
        for obj in self.dependencies:
            for block in _blocks(obj):
                animation = block.animation_data
                if animation is not None:
                    for curve in animation.drivers:
                        if not curve.is_valid or not curve.driver.is_valid:
                            raise ValueError(
                                "Native driver evaluation failed in copied contact dependencies"
                            )
            if obj.type == "MESH" and obj != self.surface:
                grouped[obj] = []
        for definition, obj in markers:
            grouped.setdefault(obj, []).append(self.definitions[definition["id"]])
        vertices_total, elements = surface_vertices, surface_vertices + surface_triangles * 3
        for obj, definitions in grouped.items():
            evaluated, mesh = obj.evaluated_get(graph), None
            try:
                mesh = evaluated.to_mesh()
                mesh.calc_loop_triangles()
                count, triangle_count = len(mesh.vertices), len(mesh.loop_triangles)
                vertices_total += count
                elements += count + triangle_count * 3 + len(mesh.edges) * 2 + len(mesh.loops)
                if vertices_total > self.maximum or elements * self.sample_count > MAX_WORK:
                    raise ValueError("Evaluated contact geometry/sample work budget exceeded")
                coordinates = array("f", [0]) * (count * 3)
                triangles = array("i", [0]) * (triangle_count * 3)
                edges = array("i", [0]) * (len(mesh.edges) * 2)
                loops = array("i", [0]) * len(mesh.loops)
                mesh.vertices.foreach_get("co", coordinates)
                mesh.loop_triangles.foreach_get("vertices", triangles)
                mesh.edges.foreach_get("vertices", edges)
                mesh.loops.foreach_get("vertex_index", loops)
                if not all(math.isfinite(value) for value in coordinates) or not all(
                    math.isfinite(value) for row in evaluated.matrix_world for value in row
                ):
                    raise ValueError("Evaluated skin coordinates and transforms must be finite")
                topology = hashlib.sha256(
                    str((count, len(mesh.polygons))).encode()
                    + triangles.tobytes()
                    + edges.tobytes()
                    + loops.tobytes()
                ).hexdigest()
                previous = self.topology.setdefault(
                    obj.name,
                    {
                        "topology_sha256": topology,
                        "evaluated_vertices": count,
                        "evaluated_triangles": triangle_count,
                    },
                )
                if topology != previous["topology_sha256"]:
                    raise ValueError(
                        "Evaluated dependency mesh topology changed; vertex/triangle identity is no longer verified"
                    )
                actual_triangles = {
                    tuple(sorted(triangles[index : index + 3]))
                    for index in range(0, len(triangles), 3)
                }
                for definition in definitions:
                    indices, weights = definition["vertex_indices"], definition["weights"]
                    if any(index >= count for index in indices):
                        raise ValueError("Marker vertex index is outside evaluated geometry")
                    if len(indices) == 3 and tuple(sorted(indices)) not in actual_triangles:
                        raise ValueError(
                            "Barycentric marker does not identify an actual evaluated triangle"
                        )
                    position = sum(
                        (
                            Vector(coordinates[index * 3 : index * 3 + 3]) * weight
                            for index, weight in zip(indices, weights, strict=True)
                        ),
                        Vector(),
                    )
                    result[definition["id"]] = evaluated.matrix_world @ position
            finally:
                if mesh is not None:
                    evaluated.to_mesh_clear()
        self.max_work = max(self.max_work, elements * self.sample_count)
        return result


def _sample_contacts(params, context, sampler):
    return contact_analysis._sample_surface_contacts(
        params, context, position_sampler=sampler, isolated=True
    )


def inspect_skin_contacts(params, context=None):
    """Evaluate explicit skin points on owned copies; never traverse source scene time."""
    rigid, times, maximum = _request(params)
    from .rigging import checked_context, scene_object

    context = checked_context(context)
    source_surface = scene_object(context, params["surface_name"], "MESH")
    sources = {
        marker["object_name"]: scene_object(context, marker["object_name"], "MESH")
        for marker in params["markers"]
    }
    if source_surface in sources.values():
        raise ValueError("Marker mesh must be distinct from the contact surface")
    objects = _dependencies([source_surface, *sources.values()], context, maximum, len(times))
    with _isolated_scene(objects, context) as (isolated, mapping):
        sampler = _EvaluatedMarkers(
            params["markers"],
            maximum,
            len(times),
            (mapping[obj] for obj in objects),
            mapping[source_surface],
        )
        rigid["surface_name"] = mapping[source_surface].name
        for marker in rigid["markers"]:
            marker["object_name"] = mapping[sources[marker["object_name"]]].name
        report = _sample_contacts(rigid, isolated, sampler)
        report["marker_meshes"] = [
            {"object_name": name, **sampler.topology[mapping[obj].name]}
            for name, obj in sorted(sources.items())
        ]
    report.update(
        surface_name=params["surface_name"],
        marker_definitions=params["markers"],
        dependency_names=[obj.name for obj in objects],
        sampled_geometry_work_elements=sampler.max_work,
        max_evaluated_vertices=maximum,
        preservation={
            "strategy": "isolated_owned_scene",
            "source_scene_time_changed": False,
            "copied": "local mesh/armature/empty dependency closure; materials removed on copies",
            "cleanup": "temporary objects, mesh/key/armature data and scene disposed on success or failure",
        },
    )
    report["limits"] = [
        "Explicit evaluated vertex/triangle points sample selected sole/prop locations, not full-body collision or artistic acceptance",
        "Evaluated triangle connectivity and vertex indexing must remain identical for the entire requested interval",
        "All copied mesh dependencies enter evaluated geometry budgets and topology checks; every sampled native driver must remain valid",
        "All integer frames and requested subframes are evaluated; continuous between-sample collision is not verified",
        "Isolated local dependency copies preserve source scene time and dirty RNA; active actions/native drivers only, no NLA/simulations/foreign handlers",
        "Projection follows world +Z and first supported surface hit; ray misses and steep hits remain unknown, not proof of clearance",
        "Rigid platform transforms are compensated; changing local surface geometry is rejected",
        "Geometry evaluation is synchronous; vertex/work admission checks are not OS memory or execution-time guarantees",
    ]
    return report
