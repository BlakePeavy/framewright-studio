"""Fit only explicitly authored landmark positions onto a copied stock metarig."""

from __future__ import annotations

import math

from .rigging import (
    checked_context,
    discard_derivative,
    finite,
    hidden_derivative,
    parameters,
    scene_object,
)

CONNECT_TOLERANCE = 1e-6


def _apply_fit(derivative, proposed, mapping):
    bones = derivative.data.edit_bones
    connectivity = {bone.name: bone.use_connect for bone in bones}
    rolls = {bone.name: bone.roll for bone in bones}
    for bone in bones:
        bone.use_connect = False
    for name, (head, tail) in proposed.items():
        # Explicit positions include unchanged original positions for unmapped bones.
        bones[name].head = head
        bones[name].tail = tail
        bones[name].roll = mapping.get(name, {}).get("roll", rolls[name])
    for bone in bones:
        bone.use_connect = connectivity[bone.name]


def fit_metarig(params: dict, context=None) -> dict:
    parameters(
        params, ("landmarks", "bone_map", "units", "coordinate_space", "protected_bones", "dry_run")
    )
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "ARMATURE")
    import addon_utils
    import bpy
    from mathutils import Vector

    if not addon_utils.check("rigify")[1]:
        raise ValueError("Enable Blender's bundled Rigify add-on before fitting a metarig")
    from rigify import feature_set_list, rig_lists

    if not 1 <= len(source.data.bones) <= 512:
        raise ValueError("Metarig must contain 1-512 authored bones")
    stock_types = []
    for bone in source.pose.bones:
        if bone.rigify_type:
            entry = rig_lists.rigs.get(bone.rigify_type)
            if entry is None or entry["feature_set"] != feature_set_list.DEFAULT_NAME:
                raise ValueError("Only bundled stock Rigify types are supported")
            stock_types.append(bone.rigify_type)
    if not stock_types:
        raise ValueError("Source must be an authored metarig with stock Rigify bone types")
    units = params.get("units", "meters")
    coordinate_space = params.get("coordinate_space", "world")
    if not isinstance(units, str) or units not in {"meters", "centimeters", "blender_units"}:
        raise ValueError("units must be meters, centimeters or blender_units")
    if not isinstance(coordinate_space, str) or coordinate_space not in {"world", "armature_local"}:
        raise ValueError("coordinate_space must be world or armature_local")
    unit_scale = context.scene.unit_settings.scale_length
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("Scene unit scale must be positive and finite")
    factor = {"meters": 1.0 / unit_scale, "centimeters": 0.01 / unit_scale, "blender_units": 1.0}[
        units
    ]
    if coordinate_space == "world" and abs(source.matrix_world.determinant()) < 1e-12:
        raise ValueError("World-space fitting requires an invertible source transform")
    inverse = source.matrix_world.inverted() if coordinate_space == "world" else None
    landmarks = params.get("landmarks")
    if not isinstance(landmarks, dict) or not 1 <= len(landmarks) <= 1024:
        raise ValueError("landmarks must contain 1-1024 explicitly named positions")
    points = {}
    for name, values in landmarks.items():
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or not isinstance(values, list)
            or len(values) != 3
        ):
            raise ValueError("Every landmark needs a nonempty name and three coordinates")
        scaled = tuple(finite(value, "landmark coordinate") * factor for value in values)
        if any(not math.isfinite(value) or abs(value) > 1_000_000 for value in scaled):
            raise ValueError("Converted landmark coordinates exceed supported bounds")
        vector = Vector(scaled)
        local = inverse @ vector if inverse is not None else vector
        if any(not math.isfinite(value) or abs(value) > 1_000_000 for value in local):
            raise ValueError("Armature-local landmark coordinates exceed supported bounds")
        points[name] = local
    mapping = params.get("bone_map")
    if not isinstance(mapping, dict) or not 1 <= len(mapping) <= 512:
        raise ValueError("bone_map must contain 1-512 explicit authored bone mappings")
    protected = params.get("protected_bones", [])
    if (
        not isinstance(protected, list)
        or len(protected) > 512
        or any(not isinstance(name, str) or name not in source.data.bones for name in protected)
        or len(set(protected)) != len(protected)
    ):
        raise ValueError("protected_bones must be unique existing authored bone names")
    originals = {
        bone.name: (bone.head_local.copy(), bone.tail_local.copy()) for bone in source.data.bones
    }
    proposed = {name: (head.copy(), tail.copy()) for name, (head, tail) in originals.items()}
    for name, specification in mapping.items():
        if (
            not isinstance(name, str)
            or name not in source.data.bones
            or not isinstance(specification, dict)
            or not {"head", "tail"} <= set(specification)
            or set(specification) - {"head", "tail", "roll"}
        ):
            raise ValueError(
                "Bone mappings must identify existing bones and head/tail landmark names"
            )
        if any(
            not isinstance(specification[key], str) or specification[key] not in points
            for key in ("head", "tail")
        ):
            raise ValueError("Bone head/tail must reference declared landmarks")
        if (
            "roll" in specification
            and abs(finite(specification["roll"], "bone roll")) > 2 * math.pi
        ):
            raise ValueError("Explicit roll must be between -2pi and 2pi radians")
        head, tail = points[specification["head"]].copy(), points[specification["tail"]].copy()
        if (tail - head).length <= 1e-8:
            raise ValueError(f"Bone {name} would have zero or unsupported tiny length")
        if name in protected and (
            tuple(head) != tuple(originals[name][0])
            or tuple(tail) != tuple(originals[name][1])
            or "roll" in specification
        ):
            raise ValueError(f"Explicit fit would change protected bone {name}")
        proposed[name] = (head, tail)
    snaps = []
    for bone in source.data.bones:
        if not bone.parent or not bone.use_connect:
            continue
        head = proposed[bone.name][0]
        tail = proposed[bone.parent.name][1]
        if (head - tail).length > CONNECT_TOLERANCE:
            raise ValueError(
                f"Explicit positions break connected chain at {bone.name}; provide matching parent-tail/child-head landmarks"
            )
        if tuple(head) != tuple(tail):
            if bone.name not in mapping or bone.name in protected:
                proposed[bone.parent.name] = (proposed[bone.parent.name][0], head.copy())
            else:
                proposed[bone.name] = (tail.copy(), proposed[bone.name][1])
            snaps.append(bone.name)
    for name, (head, tail) in proposed.items():
        if (tail - head).length <= 1e-8:
            raise ValueError(
                f"Connected endpoint normalization would produce zero length for {name}"
            )
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "units": units,
        "coordinate_space": coordinate_space,
        "fitted_bones": sorted(mapping),
        "preserved_unmapped_bones": sorted(set(originals) - set(mapping)),
        "protected_bones": protected,
        "connectivity_roundoff_snaps": snaps,
        "local_positions": {
            name: {
                "head": list(proposed[name][0]),
                "tail": list(proposed[name][1]),
                "roll": mapping[name].get("roll", "preserve_authored"),
            }
            for name in sorted(mapping)
        },
        "limits": [
            "Landmarks and anatomical meaning are explicitly authored inputs",
            "No bounding-box fit, inferred proportions, skinning or visual acceptance",
            "Unmapped bone positions and authored rolls are retained; connected endpoints must agree",
            "Numerical connected-endpoint snapping is limited to 1e-6 armature-local units",
        ],
    }
    if result["dry_run"]:
        return result
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    derivative = None
    try:
        derivative = hidden_derivative(source, context, "FittedMetarig")
        derivative.animation_data_clear()
        derivative.data.animation_data_clear()
        for name in (
            "rigify_target_rig",
            "rigify_rig_ui",
            "rigify_widgets_collection",
            "rigify_finalize_script",
        ):
            setattr(derivative.data, name, None)
        derivative.hide_viewport = False
        for obj in selected:
            obj.select_set(False)
        derivative.select_set(True)
        context.view_layer.objects.active = derivative
        context.view_layer.update()
        bpy.ops.object.mode_set(mode="EDIT")
        _apply_fit(derivative, proposed, mapping)
        bpy.ops.object.mode_set(mode="OBJECT")
        for name in protected:
            bone = derivative.data.bones[name]
            if tuple(bone.head_local) != tuple(originals[name][0]) or tuple(
                bone.tail_local
            ) != tuple(originals[name][1]):
                raise RuntimeError(
                    "Protected bone positions changed during Blender's edit-mode roundtrip"
                )
        derivative.hide_viewport = True
        result.update(derivative=derivative.name, hidden=True)
        return result
    except Exception:
        if context.mode != "OBJECT" and context.view_layer.objects.active:
            bpy.ops.object.mode_set(mode="OBJECT")
        if derivative is not None:
            discard_derivative(derivative)
        raise
    finally:
        for obj in list(context.selected_objects):
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
