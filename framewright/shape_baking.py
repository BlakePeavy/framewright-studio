"""Bounded corrective-weight baking in an owned scene, with explicit skin rebinding."""

from __future__ import annotations

import math
from contextlib import contextmanager

from .pose_correctives import _native_dependencies
from .rigging import (
    checked_context,
    discard_derivative,
    finite,
    hidden_derivative,
    integer,
    parameters,
    scene_object,
)
from .skin_contacts import _numeric_path


def _constraints(rig):
    for owner in (rig, *rig.pose.bones):
        yield from owner.constraints


def _constraint_targets(constraint):
    for prop in constraint.bl_rna.properties:
        if prop.type == "POINTER" and prop.fixed_type.identifier == "Object":
            yield constraint, prop.identifier
    for item in getattr(constraint, "targets", ()):
        yield item, "target"


def _driver_scope(owner):
    animation = getattr(owner, "animation_data", None)
    if not animation:
        return
    for curve in animation.drivers:
        _numeric_path(owner, curve.data_path)
        if not curve.is_valid or not curve.driver.is_valid:
            raise ValueError("Invalid native driver cannot supply shape-bake evaluation evidence")
        for variable in curve.driver.variables:
            if variable.type == "SINGLE_PROP":
                for target in variable.targets:
                    _numeric_path(target.id, target.data_path)


def _animation_scope(owner):
    """Resolve only this owner's active slot; unrelated shared slots stay untouched."""
    animation = getattr(owner, "animation_data", None)
    if not animation:
        return []
    if animation.nla_tracks:
        raise ValueError("Shape baking supports explicit active actions, not rig/key NLA")
    curves = list(animation.drivers)
    action = animation.action
    if action:
        if animation.action_slot is None or action.library or action.override_library:
            raise ValueError("Shape-bake actions require local assigned owner slots")
        curves += [
            curve
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            if bag.slot_handle == animation.action_slot.handle
            for curve in bag.fcurves
        ]
    if len(curves) > 8192:
        raise ValueError("Shape-bake animation exceeds the local 8192-curve inspection budget")
    for curve in curves:
        _numeric_path(owner, curve.data_path)
    _driver_scope(owner)
    return curves


def _validate(params, context):
    import bpy

    if any(
        getattr(bpy.app.handlers, name)
        for name in (
            "frame_change_pre",
            "frame_change_post",
            "depsgraph_update_pre",
            "depsgraph_update_post",
        )
    ):
        raise ValueError(
            "Isolated morph sampling refuses registered frame/depsgraph handlers; use a clean background job"
        )
    required = (
        "object_name",
        "armature_name",
        "baked_armature_name",
        "shape_keys",
        "frame_start",
        "frame_end",
    )
    parameters(params, ("max_samples", "max_interpolation_error", "dry_run"), required)
    for field in ("object_name", "armature_name", "baked_armature_name"):
        if not isinstance(params[field], str) or not 1 <= len(params[field]) <= 256:
            raise ValueError(f"{field} must be an exact nonempty name")
    source = scene_object(context, params["object_name"], "MESH")
    rig = scene_object(context, params["armature_name"], "ARMATURE")
    target = scene_object(context, params["baked_armature_name"], "ARMATURE")
    if rig == target:
        raise ValueError("A separate explicitly baked armature is required")
    keys = source.data.shape_keys
    names = params["shape_keys"]
    if (
        not keys
        or not keys.use_relative
        or not isinstance(names, list)
        or not 1 <= len(names) <= 32
        or not all(isinstance(n, str) and n for n in names)
        or len(set(names)) != len(names)
        or set(names) != {key.name for key in keys.key_blocks if key != keys.reference_key}
    ):
        raise ValueError(
            "shape_keys must explicitly list every non-Basis relative key exactly once"
        )
    if any(
        key.relative_key != keys.reference_key or key.mute or key.vertex_group
        for key in keys.key_blocks
        if key != keys.reference_key
    ):
        raise ValueError("Only unmuted unmasked Basis-relative keys are portable in this workflow")
    if (
        len(source.data.vertices) > 200_000
        or len(source.data.vertices) * len(keys.key_blocks) > 2_000_000
    ):
        raise ValueError("Source exceeds the 200k vertex or 2m key-point budget")
    if any(not math.isfinite(v) for key in keys.key_blocks for point in key.data for v in point.co):
        raise ValueError("Shape coordinates must be finite")
    if any(
        data.library or data.override_library
        for data in (source, source.data, keys, rig, rig.data, target, target.data)
    ):
        raise ValueError("Baking requires local editable mesh, key and armature data")
    if any(obj.name not in context.view_layer.objects for obj in (source, rig, target)):
        raise ValueError("All explicit objects must belong to the active view layer")
    if (
        source.parent != rig
        or source.parent_type != "OBJECT"
        or source.constraints
        or source.animation_data
        or source.data.animation_data
        or len(source.modifiers) != 1
        or source.modifiers[0].type != "ARMATURE"
        or source.modifiers[0].object != rig
    ):
        raise ValueError(
            "Source must be statically object-parented to its only Armature modifier, without other modifiers or object/data animation"
        )
    if rig.parent or target.parent or rig.data.animation_data or target.data.animation_data:
        raise ValueError("Parented or data-animated rigs require a separate workflow")
    modifier = source.modifiers[0]
    if (
        modifier.use_deform_preserve_volume
        or modifier.use_bone_envelopes
        or not modifier.use_vertex_groups
        or modifier.vertex_group
        or not modifier.show_viewport
        or not modifier.show_render
        or rig.data.pose_position != "POSE"
        or target.data.pose_position != "POSE"
    ):
        raise ValueError(
            "Portable morph handoff requires enabled linear vertex-group skinning without envelope/mask/DQ modes"
        )
    if any(b.bbone_segments > 1 for obj in (rig, target) for b in obj.data.bones):
        raise ValueError("Bendy-bone segments need a separately verified deformation bake")
    if len(rig.data.bones) > 256 or set(rig.data.bones.keys()) != set(target.data.bones.keys()):
        raise ValueError("Source and baked rest hierarchy must match and contain at most 256 bones")
    for bone in rig.data.bones:
        other = target.data.bones[bone.name]
        if (
            bone.matrix_local != other.matrix_local
            or bone.length != other.length
            or bone.use_deform != other.use_deform
            or bone.use_connect != other.use_connect
            or (bone.parent.name if bone.parent else None)
            != (other.parent.name if other.parent else None)
        ):
            raise ValueError("Baked rest hierarchy and deform flags must match the source exactly")
    if list(_constraints(target)) or (target.animation_data and target.animation_data.drivers):
        raise ValueError("Target rig must already be baked without constraints/drivers")
    for constraint in _constraints(rig):
        if any(
            getattr(owner, field) not in (None, rig)
            for owner, field in _constraint_targets(constraint)
        ):
            raise ValueError("Source rig constraints must use only internal armature targets")
    _native_dependencies(rig.animation_data, {rig, rig.data}, rig, native_rig_curves=True)
    _native_dependencies(keys.animation_data, {source, source.data, keys, rig, rig.data}, rig)
    _animation_scope(rig)
    _animation_scope(target)
    curves = _animation_scope(keys)
    paths = {keys.key_blocks[name].path_from_id("value") for name in names}
    if len(curves) > 2048 or any(c.data_path not in paths for c in curves):
        raise ValueError(
            "Shape animation must affect only the explicit key values, at most 2048 curves"
        )
    start = integer(params["frame_start"], -1_000_000, 1_000_000, "frame_start")
    end = integer(params["frame_end"], -1_000_000, 1_000_000, "frame_end")
    maximum = integer(params.get("max_samples", 128), 1, 256, "max_samples")
    if end < start or end - start + 1 > maximum:
        raise ValueError(
            "Full integer-frame interval must fit max_samples; skipped frames are unsupported"
        )
    tolerance = finite(params.get("max_interpolation_error", 0.001), "max_interpolation_error", 0)
    if tolerance > 1:
        raise ValueError("max_interpolation_error must be at most 1 in scalar shape-weight units")
    return source, rig, target, names, list(range(start, end + 1)), tolerance


def _remap_drivers(data, mapping):
    animation = getattr(data, "animation_data", None)
    if animation:
        for curve in animation.drivers:
            for variable in curve.driver.variables:
                for target in variable.targets:
                    if target.id in mapping:
                        target.id = mapping[target.id]


@contextmanager
def _sampling_scene(context, source, rig, target):
    """Evaluate owned local dependencies without advancing the user's scene."""
    import bpy

    scene = bpy.data.scenes.new("FW_MorphSample")
    copies = {}
    owned_data = []
    try:
        scene.render.fps = context.scene.render.fps
        scene.render.fps_base = context.scene.render.fps_base
        scene.unit_settings.scale_length = context.scene.unit_settings.scale_length
        for original in (rig, target, source):
            copy = original.copy()
            copies[original] = copy
            copy.data = original.data.copy()
            owned_data.append(
                (bpy.data.meshes if original.type == "MESH" else bpy.data.armatures, copy.data)
            )
            if copy.type == "ARMATURE":
                for bone in copy.pose.bones:
                    # Viewport widgets and their materials do not contribute to skin deformation.
                    bone.custom_shape = None
                    bone.custom_shape_transform = None
            scene.collection.objects.link(copy)
            copy.hide_viewport = False
            copy.hide_render = False
            copy.hide_set(False, view_layer=scene.view_layers[0])
        skin, driver_rig, baked_rig = copies[source], copies[rig], copies[target]
        skin.parent = driver_rig
        skin.matrix_parent_inverse = source.matrix_parent_inverse.copy()
        skin.modifiers[0].object = driver_rig
        skin.data.materials.clear()  # Shader/image animation is irrelevant and stays outside this graph.
        mapping = {original: copy for original, copy in copies.items()}
        mapping.update({original.data: copy.data for original, copy in copies.items()})
        mapping[source.data.shape_keys] = skin.data.shape_keys
        for copy in copies.values():
            _remap_drivers(copy, mapping)
            _remap_drivers(copy.data, mapping)
            if copy.type == "ARMATURE":
                for constraint in _constraints(copy):
                    for owner, field in _constraint_targets(constraint):
                        value = getattr(owner, field)
                        if value in mapping:
                            setattr(owner, field, mapping[value])
        _remap_drivers(skin.data.shape_keys, mapping)
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            yield scene, skin, driver_rig, baked_rig
    finally:
        for copy in copies.values():
            bpy.data.objects.remove(copy, do_unlink=True)
        bpy.data.scenes.remove(scene, do_unlink=True)
        for store, data in owned_data:
            store.remove(data, do_unlink=True)


def _sample(context, source, rig, target, names, frames, tolerance):
    values = {}
    max_rig_integer = 0.0
    max_rig_midpoint = 0.0
    with _sampling_scene(context, source, rig, target) as (scene, skin, driver_rig, baked_rig):
        for half in range(frames[0] * 2, frames[-1] * 2 + 1):
            time = half / 2
            frame = math.floor(time)
            scene.frame_set(frame, subframe=time - frame)
            scene.view_layers[0].update()
            graph = context.evaluated_depsgraph_get()
            evaluated_source = driver_rig.evaluated_get(graph)
            evaluated_target = baked_rig.evaluated_get(graph)
            evaluated_keys = skin.evaluated_get(graph).data.shape_keys
            for owner in (
                driver_rig,
                baked_rig,
                skin.data.shape_keys,
                evaluated_source,
                evaluated_target,
                evaluated_keys,
            ):
                _driver_scope(owner)
            if any(not constraint.is_valid for constraint in _constraints(evaluated_source)):
                raise ValueError(
                    "Invalid evaluated source rig constraint cannot supply shape-bake evidence"
                )
            measured = {name: float(evaluated_keys.key_blocks[name].value) for name in names}
            if any(not math.isfinite(value) or not 0 <= value <= 1 for value in measured.values()):
                raise ValueError(
                    "Evaluated corrective values must remain finite in [0,1] throughout samples"
                )
            values[time] = measured
            matrices = [(evaluated_source.matrix_world, evaluated_target.matrix_world)]
            matrices += [
                (
                    evaluated_source.matrix_world @ b.matrix,
                    evaluated_target.matrix_world @ evaluated_target.pose.bones[b.name].matrix,
                )
                for b in evaluated_source.pose.bones
            ]
            error = max(
                abs(a[i][j] - b[i][j]) for a, b in matrices for i in range(4) for j in range(4)
            )
            if half % 2:
                max_rig_midpoint = max(max_rig_midpoint, error)
            else:
                max_rig_integer = max(max_rig_integer, error)
        if max_rig_integer > 1e-4:
            raise ValueError(
                f"Baked armature does not match source sampled poses within 1e-4 matrix-component tolerance (actual {max_rig_integer})"
            )
    per_key = {name: 0.0 for name in names}
    for frame in frames[:-1]:
        for name in names:
            expected = (values[frame][name] + values[frame + 1][name]) / 2
            per_key[name] = max(per_key[name], abs(values[frame + 0.5][name] - expected))
    if max(per_key.values()) > tolerance:
        raise ValueError(
            f"Scalar shape-weight midpoint interpolation error {max(per_key.values()):.9g} exceeds max_interpolation_error"
        )
    return values, per_key, max_rig_integer, max_rig_midpoint


def _write_action(derivative, names, frames, values):
    keys = derivative.data.shape_keys
    for frame in frames:
        for name in names:
            key = keys.key_blocks[name]
            key.value = values[frame][name]
            key.keyframe_insert("value", frame=frame)
    action = keys.animation_data.action
    action.name = derivative.name + "_ShapeBake"
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"
    return action


def bake_shape_keys(params: dict, context=None) -> dict:
    context = checked_context(context)
    source, rig, target, names, frames, tolerance = _validate(params, context)
    values, errors, rig_error, rig_midpoint = _sample(
        context, source, rig, target, names, frames, tolerance
    )
    result = dict(
        schema_version="1.0",
        source=source.name,
        armature=rig.name,
        baked_armature=target.name,
        shape_keys=names,
        dry_run=params.get("dry_run", True),
        frame_count=len(frames),
        frame_start=frames[0],
        frame_end=frames[-1],
        validation_sample_count=2 * len(frames) - 1,
        interpolation="LINEAR",
        max_interpolation_error=tolerance,
        interpolation_error_units="scalar_shape_weight_0_to_1",
        midpoint_errors=errors,
        maximum_rig_integer_matrix_error=rig_error,
        maximum_rig_midpoint_matrix_error=rig_midpoint,
        source_preserved=True,
        art_accepted=False,
        limits=[
            "Integer frames and midpoints cover the full requested interval, not unsampled extrema",
            "Shape-weight tolerance is an engineering approximation bound, not a pose/skin artistic tolerance",
            "Baked rig integer poses must match; midpoint rig deviations are reported and require coupled geometry validation",
            "No B-Bone, topology modifier, masked/absolute key or arbitrary Python dependency portability",
        ],
    )
    if result["dry_run"]:
        return result
    import bpy

    derivative = None
    try:
        derivative = hidden_derivative(source, context, "ShapeBake")
        derivative.parent = target
        derivative.matrix_parent_inverse = source.matrix_parent_inverse.copy()
        derivative.modifiers[0].object = target
        derivative.data.shape_keys.animation_data_clear()
        action = _write_action(derivative, names, frames, values)
        result.update(derivative=derivative.name, action=action.name, hidden=True)
        return result
    except Exception:
        if derivative is not None:
            animation = derivative.data.shape_keys.animation_data
            action = animation.action if animation else None
            discard_derivative(derivative)
            if action is not None and action.users == 0:
                bpy.data.actions.remove(action)
        raise
