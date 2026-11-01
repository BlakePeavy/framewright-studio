"""Explicit joint-angle activation of an existing corrective on an owned mesh copy."""

from __future__ import annotations

import math

from .rigging import (
    checked_context,
    discard_derivative,
    finite,
    hidden_derivative,
    parameters,
    preserve_time,
    scene_object,
)


def _curves(action):
    return [
        curve
        for layer in action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        for curve in bag.fcurves
    ]


def _native_dependencies(animation, allowed_ids, rig, *, native_rig_curves=False):
    if not animation:
        return
    if len(animation.drivers) > 2048:
        raise ValueError("Driver count exceeds the supported 2048-curve budget")
    for curve in animation.drivers:
        driver = curve.driver
        native_type = driver.type == "SCRIPTED" and driver.is_simple_expression
        if native_rig_curves and driver.type in {"SUM", "AVERAGE", "MIN", "MAX"}:
            native_type = True
        native_modifiers = not curve.modifiers or (
            native_rig_curves
            and all(
                modifier.type == "GENERATOR"
                and modifier.mode == "POLYNOMIAL"
                and modifier.poly_order <= 10
                and all(math.isfinite(value) for value in modifier.coefficients)
                for modifier in curve.modifiers
            )
        )
        if not native_type or not native_modifiers:
            raise ValueError(
                "Only native simple-expression drivers are supported; existing rig drivers also allow native aggregation and bounded polynomials"
            )
        for variable in driver.variables:
            if variable.type not in {"SINGLE_PROP", "TRANSFORMS", "LOC_DIFF", "ROTATION_DIFF"}:
                raise ValueError("Unsupported driver dependency type")
            for target in variable.targets:
                if target.id not in allowed_ids:
                    raise ValueError(
                        "Driver dependency must refer to the explicit local mesh/key or rig"
                    )
                if variable.type != "SINGLE_PROP" and target.id != rig:
                    raise ValueError("Transform driver dependencies must use the explicit armature")
                if target.bone_target and target.bone_target not in rig.pose.bones:
                    raise ValueError("Driver dependency refers to a missing armature bone")


def _validate_source(source, rig, key_name, bone_names):
    keys = source.data.shape_keys
    if not keys or not keys.use_relative:
        raise ValueError("Source requires relative shape-key data")
    key = keys.key_blocks.get(key_name)
    if (
        key is None
        or key == keys.reference_key
        or key.relative_key != keys.reference_key
        or key.slider_min > 0
        or key.slider_max < 1
        or key.mute
    ):
        raise ValueError(
            "Corrective must be an unmuted Basis-relative key supporting values 0 through 1"
        )
    if any(
        data.library or data.override_library for data in (source, source.data, keys, rig, rig.data)
    ):
        raise ValueError("Corrective activation requires local editable mesh/key and armature data")
    if (
        source.constraints
        or source.animation_data
        or source.data.animation_data
        or (source.parent and (source.parent != rig or source.parent_type != "OBJECT"))
    ):
        raise ValueError(
            "Mesh object/data animation, constraints and non-rig parenting are unsupported"
        )
    if rig.parent:
        raise ValueError("Parented armatures require a separately reviewed dependency workflow")
    modifiers = [modifier for modifier in source.modifiers if modifier.type == "ARMATURE"]
    if (
        len(modifiers) != 1
        or modifiers[0].object != rig
        or any(
            modifier.type not in {"ARMATURE", "SUBSURF", "MULTIRES"}
            for modifier in source.modifiers
        )
    ):
        raise ValueError(
            "Source needs exactly the explicit armature binding; only subdivision may accompany it"
        )
    if (
        not 1 <= len(source.data.vertices) <= 200_000
        or len(keys.key_blocks) > 128
        or len(keys.key_blocks) * len(source.data.vertices) > 2_000_000
    ):
        raise ValueError(
            "Mesh/key data exceeds the fixed 200k-vertex, 128-key, 2m-key-point budget"
        )
    if len(set(bone_names)) != 3 or any(name not in rig.pose.bones for name in bone_names):
        raise ValueError("Three distinct existing armature bones are required")
    heads = [rig.data.bones[name].head_local for name in bone_names]
    if any(not math.isfinite(value) for head in heads for value in head) or any(
        (heads[a] - heads[b]).length <= 1e-8 for a, b in ((0, 1), (1, 2))
    ):
        raise ValueError("Authored joint-head segments must have nonzero lengths")
    for obj in (source, rig):
        if (
            any(not math.isfinite(value) for row in obj.matrix_world for value in row)
            or abs(obj.matrix_world.determinant()) <= 1e-12
        ):
            raise ValueError("Object transforms must be finite and invertible")
    if any(
        not math.isfinite(value) for k in keys.key_blocks for point in k.data for value in point.co
    ):
        raise ValueError("Shape-key coordinates must be finite")
    animation = keys.animation_data
    path = key.path_from_id("value")
    if animation:
        if animation.nla_tracks:
            raise ValueError(
                "Shape-key NLA is unsupported; explicitly prepare a detached active action"
            )
        if any(curve.data_path == path for curve in animation.drivers):
            raise ValueError("The target corrective already has a driver")
        if animation.action:
            if animation.action_slot is None:
                raise ValueError("Existing shape-key action must have an explicit active slot")
            if animation.action.library or animation.action.override_library:
                raise ValueError("Linked shape-key animation is unsupported")
            curves = _curves(animation.action)
            if len(curves) > 2048:
                raise ValueError("Shape-key action exceeds the 2048-curve budget")
            if any(curve.data_path == path for curve in curves):
                raise ValueError("The target corrective already has authored animation")
        _native_dependencies(animation, {source, source.data, keys, rig, rig.data}, rig)
    # The measured rig may not depend back on the source mesh or unrelated targets.
    # Stock Rigify's own-control constraints and simple internal drivers are supported.
    for owner in (rig, rig.data):
        _native_dependencies(owner.animation_data, {rig, rig.data}, rig, native_rig_curves=True)
    for owner in (rig, *rig.pose.bones):
        for constraint in owner.constraints:
            targets = [
                getattr(constraint, prop.identifier)
                for prop in constraint.bl_rna.properties
                if prop.type == "POINTER" and prop.fixed_type.identifier == "Object"
            ]
            targets += [item.target for item in getattr(constraint, "targets", ())]
            if any(target is not None and target != rig for target in targets):
                raise ValueError(
                    "Armature constraints must not depend on meshes or unrelated objects"
                )
    return key


def _detach_animation(source, derivative, actions):
    old_keys, keys = source.data.shape_keys, derivative.data.shape_keys
    animation = keys.animation_data
    if not animation:
        return
    if animation.action:
        slot_identifier = animation.action_slot.identifier if animation.action_slot else None
        action = animation.action.copy()
        actions.append(action)
        animation.action = action
        if slot_identifier:
            animation.action_slot = next(
                slot for slot in action.slots if slot.identifier == slot_identifier
            )
    remap = {source: derivative, source.data: derivative.data, old_keys: keys}
    for curve in animation.drivers:
        for variable in curve.driver.variables:
            for target in variable.targets:
                if target.id in remap:
                    target.id = remap[target.id]


def _install_driver(key, rig, bone_names, onset, full):
    curve = key.driver_add("value")
    driver = curve.driver
    driver.type = "SCRIPTED"
    for name, first, second in (("d", 0, 2), ("h", 0, 1), ("s", 1, 2)):
        variable = driver.variables.new()
        variable.name = name
        variable.type = "LOC_DIFF"
        for target, index in zip(variable.targets, (first, second), strict=True):
            target.id = rig
            target.bone_target = bone_names[index]
            target.transform_space = "WORLD_SPACE"
    angle = "acos(min(1,max(-1,(d*d-h*h-s*s)/max(2*h*s,1e-20))))"
    fraction = (
        f"min(1,max(0,({angle}-{math.radians(onset):.17g})/{math.radians(full - onset):.17g}))"
    )
    # Conditional is part of Blender's native expression subset. Collapsed
    # segments cannot define an angle, so they deactivate rather than guess it.
    driver.expression = (
        f"(1-cos(pi*({fraction})))/2 if 1e-8<h<1e20 and 1e-8<s<1e20 and 0<=d<1e20 else 0"
    )
    if not driver.is_simple_expression:
        raise RuntimeError("Corrective expression did not compile to the native driver subset")


def activate_corrective(params: dict, context=None) -> dict:
    """Preview or create a hidden derivative with fixed native joint-angle activation."""
    required = (
        "object_name",
        "shape_key",
        "armature_name",
        "proximal_bone",
        "joint_bone",
        "distal_bone",
    )
    parameters(params, ("onset_degrees", "full_degrees", "dry_run"), required)
    context = checked_context(context)
    for name in required:
        if not isinstance(params[name], str) or not 1 <= len(params[name]) <= 256:
            raise ValueError(f"{name} must be an exact nonempty name of at most 256 characters")
    onset = finite(params.get("onset_degrees", 20), "onset_degrees")
    full = finite(params.get("full_degrees", 110), "full_degrees")
    if not 0 <= onset < full <= 170:
        raise ValueError("Activation requires 0 <= onset_degrees < full_degrees <= 170")
    source = scene_object(context, params["object_name"], "MESH")
    rig = scene_object(context, params["armature_name"], "ARMATURE")
    if source.name not in context.view_layer.objects or rig.name not in context.view_layer.objects:
        raise ValueError("Source and armature must belong to the active view layer")
    bone_names = tuple(params[name] for name in ("proximal_bone", "joint_bone", "distal_bone"))
    _validate_source(source, rig, params["shape_key"], bone_names)
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "armature": rig.name,
        "shape_key": params["shape_key"],
        "bones": dict(zip(("proximal", "joint", "distal"), bone_names, strict=True)),
        "dry_run": params.get("dry_run", True),
        "onset_degrees": onset,
        "full_degrees": full,
        "angle_zero": "straight_at_middle_joint",
        "measurement": "unsigned_world_joint_head_angle_no_rest_offset",
        "interpolation": "clamped_half_cosine_zero_endpoint_slope",
        "degenerate_segments": "activation_zero_when_segment_le_1e-8_or_nonfinite_or_distance_ge_1e20",
        "native_simple_expression": True,
        "autoexecution_required": False,
        "art_accepted": False,
        "limits": [
            "Existing corrective geometry is retained; no anatomical shape or bone mapping is inferred",
            "Unsigned bend does not distinguish forward/backward flexion or axial twist",
            "Nonuniform rig scaling can change the measured world-space angle",
            "World distances require evaluated rig dependencies; reveal the derivative to evaluate its drivers",
            "No rest offset, pose-space multi-axis solver, export portability or visual acceptance is inferred",
        ],
    }
    if result["dry_run"]:
        return result
    import bpy

    derivative, actions = None, []
    try:
        with preserve_time(context, (source, rig)):
            derivative = hidden_derivative(source, context, "AngleCorrective")
            _detach_animation(source, derivative, actions)
            _install_driver(
                derivative.data.shape_keys.key_blocks[params["shape_key"]],
                rig,
                bone_names,
                onset,
                full,
            )
            result.update(
                derivative=derivative.name,
                hidden=True,
                copied_actions=[action.name for action in actions],
            )
    except Exception:
        if derivative is not None:
            discard_derivative(derivative)
        for action in actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        raise
    return result
