"""Explicit automatic-heat binding on an independent, hidden mesh derivative."""

from __future__ import annotations

import math

from .rigging import (
    checked_context,
    discard_derivative,
    hidden_derivative,
    integer,
    parameters,
    scene_object,
)


def _auto_weight(derivative, rig, context):
    import bpy

    with context.temp_override(
        object=rig,
        active_object=rig,
        selected_objects=[derivative, rig],
        selected_editable_objects=[derivative, rig],
    ):
        outcome = bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
    if outcome != {"FINISHED"}:
        raise RuntimeError("Blender automatic heat binding did not finish")


def _weight_evidence(derivative, deform_names):
    indexes = {group.index for group in derivative.vertex_groups if group.name in deform_names}
    unweighted, max_error, max_influences = [], 0.0, 0
    for vertex in derivative.data.vertices:
        weights = [group.weight for group in vertex.groups if group.group in indexes]
        if any(not math.isfinite(weight) or weight < 0 or weight > 1 for weight in weights):
            raise ValueError("Automatic heat produced invalid deform weights")
        total = sum(weights)
        if total <= 1e-8:
            unweighted.append(vertex.index)
        else:
            max_error = max(max_error, abs(total - 1.0))
        max_influences = max(max_influences, sum(weight > 1e-8 for weight in weights))
    return {
        "unweighted_vertices": len(unweighted),
        "unweighted_vertex_sample": unweighted[:64],
        "unweighted_sample_truncated": len(unweighted) > 64,
        "max_weight_sum_error": max_error,
        "max_influences": max_influences,
    }


def _normalize_new_weights(derivative, deform_names):
    groups = {
        group.index: group for group in derivative.vertex_groups if group.name in deform_names
    }
    for vertex in derivative.data.vertices:
        weights = [(group.group, group.weight) for group in vertex.groups if group.group in groups]
        if any(not math.isfinite(weight) or weight < 0 or weight > 1 for _, weight in weights):
            raise ValueError("Automatic heat produced invalid deform weights")
        total = sum(weight for _, weight in weights)
        if total > 1e-8:
            for index, weight in weights:
                groups[index].add([vertex.index], weight / total, "REPLACE")


def bind_mesh(params: dict, context=None) -> dict:
    parameters(
        params,
        (
            "armature_name",
            "dry_run",
            "max_vertices",
            "max_deform_bones",
            "require_complete_weights",
        ),
    )
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    name = params.get("armature_name")
    if not isinstance(name, str) or not name or len(name) > 256:
        raise ValueError("armature_name must be a nonempty exact object name")
    rig = scene_object(context, name, "ARMATURE")
    if source.name not in context.view_layer.objects or rig.name not in context.view_layer.objects:
        raise ValueError("Source and armature must belong to the active view layer")
    maximum = integer(params.get("max_vertices", 100_000), 1, 1_000_000, "max_vertices")
    max_bones = integer(params.get("max_deform_bones", 256), 1, 1024, "max_deform_bones")
    require_complete = params.get("require_complete_weights", True)
    if type(require_complete) is not bool:
        raise ValueError("require_complete_weights must be a boolean")
    if not 1 <= len(source.data.vertices) <= maximum or not source.data.polygons:
        raise ValueError("Source must have faces and fit the max_vertices base-mesh budget")
    if any(
        obj.library or obj.data.library or obj.override_library or obj.data.override_library
        for obj in (source, rig)
    ):
        raise ValueError("Binding requires local mesh and armature data")
    if (
        source.vertex_groups
        or source.parent
        or source.constraints
        or source.animation_data
        or source.data.animation_data
        or source.data.shape_keys
        or any(modifier.type not in {"SUBSURF", "MULTIRES"} for modifier in source.modifiers)
    ):
        raise ValueError(
            "Source must be unskinned, unparented and unanimated without constraints or shape keys; only SUBSURF/MULTIRES are supported"
        )
    for obj in (source, rig):
        if (
            any(not math.isfinite(value) for row in obj.matrix_world for value in row)
            or abs(obj.matrix_world.determinant()) <= 1e-12
        ):
            raise ValueError("Binding requires finite invertible object transforms")
    if any(not math.isfinite(value) for vertex in source.data.vertices for value in vertex.co):
        raise ValueError("Source vertex coordinates must be finite")
    deform_names = {bone.name for bone in rig.data.bones if bone.use_deform}
    if not 1 <= len(deform_names) <= max_bones:
        raise ValueError("Armature deform bones must fit the max_deform_bones budget")
    for bone in rig.pose.bones:
        # RNA channels remain current even while a hidden rig has stale evaluated matrices.
        rotation = (
            bone.rotation_quaternion.to_matrix()
            if bone.rotation_mode == "QUATERNION"
            else bone.rotation_euler.to_matrix()
            if bone.rotation_mode != "AXIS_ANGLE"
            else None
        )
        if rotation is None:
            from mathutils import Quaternion

            rotation = Quaternion(
                bone.rotation_axis_angle[1:], bone.rotation_axis_angle[0]
            ).to_matrix()
        raw = (*bone.location, *bone.scale, *(value for row in rotation for value in row))
        if (
            any(not math.isfinite(value) for value in raw)
            or bone.location.length > 1e-5
            or any(abs(value - 1.0) > 1e-5 for value in bone.scale)
            or any(
                abs(rotation[row][column] - (1.0 if row == column else 0.0)) > 1e-5
                for row in range(3)
                for column in range(3)
            )
        ):
            raise ValueError(
                "Binding requires the authored rest pose; reset all pose controls first"
            )
        if any(
            abs(bone.matrix_basis[row][column] - (1.0 if row == column else 0.0)) > 1e-5
            for row in range(4)
            for column in range(4)
        ):
            raise ValueError(
                "Binding requires the authored rest pose; reset all pose controls first"
            )
        if bone.name in deform_names and any(
            abs(bone.matrix[row][column] - bone.bone.matrix_local[row][column]) > 1e-4
            for row in range(4)
            for column in range(4)
        ):
            raise ValueError("Binding requires the evaluated deform bones to match their rest pose")
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "armature": rig.name,
        "dry_run": params.get("dry_run", True),
        "method": "AUTOMATIC_HEAT",
        "bind_geometry": "base_mesh",
        "vertices": len(source.data.vertices),
        "deform_bones": len(deform_names),
        "require_complete_weights": require_complete,
        "normalizes_new_weights": True,
        "limits": [
            "Automatic heat is a provisional weight proposal, not deformation acceptance",
            "No envelope fallback or inferred skeleton fitting",
            "Existing subdivision is retained after base-mesh heat binding",
            "No artist influence limit or protected-region acceptance is inferred",
        ],
    }
    if result["dry_run"]:
        return result
    selected = tuple(context.selected_objects)
    active = context.view_layer.objects.active
    rig_visibility = (rig.hide_viewport, rig.hide_render, rig.hide_get())
    derivative = hidden_derivative(source, context, "Bound")
    try:
        for obj in tuple(context.selected_objects):
            obj.select_set(False)
        rig.hide_viewport = False
        rig.hide_set(False)
        derivative.hide_viewport = False
        derivative.hide_set(False)
        modifier_visibility = [
            (modifier, modifier.show_viewport) for modifier in derivative.modifiers
        ]
        for modifier, _ in modifier_visibility:
            modifier.show_viewport = False
        rig.select_set(True)
        derivative.select_set(True)
        context.view_layer.objects.active = rig
        context.view_layer.update()
        _auto_weight(derivative, rig, context)
        modifiers = [modifier for modifier in derivative.modifiers if modifier.type == "ARMATURE"]
        if len(modifiers) != 1 or modifiers[0].object != rig or derivative.parent != rig:
            raise RuntimeError("Automatic heat did not create the requested armature binding")
        modifier = modifiers[0]
        derivative.modifiers.move(list(derivative.modifiers).index(modifier), 0)
        for modifier, visibility in modifier_visibility:
            modifier.show_viewport = visibility
        _normalize_new_weights(derivative, deform_names)
        evidence = _weight_evidence(derivative, deform_names)
        if require_complete and evidence["unweighted_vertices"]:
            raise ValueError(
                f"Automatic heat left {evidence['unweighted_vertices']} unweighted vertices; derivative discarded"
            )
        derivative.select_set(False)
        derivative.hide_viewport = True
        derivative.hide_render = True
        result.update(
            derivative=derivative.name,
            hidden=True,
            status="needs_review",
            **evidence,
        )
        return result
    except Exception:
        discard_derivative(derivative)
        raise
    finally:
        for obj in tuple(context.selected_objects):
            obj.select_set(False)
        rig.hide_viewport, rig.hide_render = rig_visibility[:2]
        rig.hide_set(rig_visibility[2])
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        context.view_layer.update()
