"""Action/NLA metadata, contact measurements and sampled derivative pose baking."""

from __future__ import annotations

import math

from .rigging import (
    checked_context,
    discard_derivative,
    finite,
    hidden_derivative,
    integer,
    parameters,
    preserve_time,
    sample_frames,
    scene_object,
)


def _action_report(action):
    if action is None:
        return None
    layers = []
    curve_count = 0
    key_count = 0
    for layer in action.layers:
        strips = []
        for strip in layer.strips:
            bags = []
            for bag in getattr(strip, "channelbags", ()):
                curves = list(bag.fcurves)
                curve_count += len(curves)
                keys = sum(len(curve.keyframe_points) for curve in curves)
                key_count += keys
                bags.append(
                    {
                        "slot_handle": bag.slot_handle,
                        "curve_count": len(curves),
                        "keyframe_count": keys,
                    }
                )
            strips.append({"type": strip.type, "channelbags": bags})
        layers.append({"name": layer.name, "strips": strips})
    return {
        "name": action.name,
        "frame_range": list(action.frame_range),
        "slots": [
            {
                "identifier": slot.identifier,
                "handle": slot.handle,
                "target_id_type": slot.target_id_type,
            }
            for slot in action.slots
        ],
        "layers": layers,
        "curve_count": curve_count,
        "keyframe_count": key_count,
        "users": action.users,
    }


def inspect_animation(params: dict, context=None) -> dict:
    parameters(params, ())
    context = checked_context(context)
    obj = scene_object(context, params["object_name"])
    data = obj.animation_data
    fps = context.scene.render.fps / context.scene.render.fps_base
    tracks = []
    if data:
        for track in data.nla_tracks:
            strips = [
                {
                    "name": strip.name,
                    "type": strip.type,
                    "frame_start": strip.frame_start,
                    "frame_end": strip.frame_end,
                    "action": strip.action.name if strip.action else None,
                    "action_frame_start": strip.action_frame_start,
                    "action_frame_end": strip.action_frame_end,
                    "scale": strip.scale,
                    "repeat": strip.repeat,
                    "blend_type": strip.blend_type,
                    "influence": strip.influence,
                    "mute": strip.mute,
                    "duration_seconds": (strip.frame_end - strip.frame_start) / fps,
                }
                for strip in track.strips
            ]
            tracks.append(
                {"name": track.name, "mute": track.mute, "is_solo": track.is_solo, "strips": strips}
            )
    return {
        "schema_version": "1.0",
        "object_name": obj.name,
        "fps": fps,
        "action": _action_report(data.action if data else None),
        "active_slot": data.action_slot.identifier if data and data.action_slot else None,
        "nla_tracks": tracks,
        "driver_count": len(data.drivers) if data else 0,
        "limits": [
            "Ownership and timing metadata do not prove motion quality",
            "No automatic root-motion or loop acceptance",
        ],
    }


def inspect_contacts(params: dict, context=None) -> dict:
    parameters(
        params,
        (
            "bones",
            "root_bone",
            "frame_start",
            "frame_end",
            "step",
            "max_samples",
            "ground_height",
            "contact_tolerance",
            "sliding_speed",
            "penetration_tolerance",
        ),
    )
    context = checked_context(context)
    obj = scene_object(context, params["object_name"], "ARMATURE")
    bones = params.get("bones")
    if (
        not isinstance(bones, list)
        or not 1 <= len(bones) <= 16
        or any(not isinstance(name, str) or name not in obj.pose.bones for name in bones)
        or len(set(bones)) != len(bones)
    ):
        raise ValueError("bones must name 1-16 distinct bones on the armature")
    root = params.get("root_bone")
    if root is not None and (not isinstance(root, str) or root not in obj.pose.bones):
        raise ValueError("root_bone must identify a bone on the armature")
    frames = sample_frames(params)
    ground = finite(params.get("ground_height", 0.0), "ground_height")
    contact = finite(params.get("contact_tolerance", 0.03), "contact_tolerance", 0.0)
    speed_limit = finite(params.get("sliding_speed", 0.05), "sliding_speed", 0.0)
    penetration = finite(params.get("penetration_tolerance", 0.01), "penetration_tolerance", 0.0)
    unit = context.scene.unit_settings.scale_length
    fps = context.scene.render.fps / context.scene.render.fps_base
    samples = []
    previous = None
    sliding = 0
    penetrating = 0
    root_start = root_end = None
    with preserve_time(context, (obj,)):
        for frame in frames:
            context.scene.frame_set(frame)
            evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
            positions = {
                name: list(evaluated.matrix_world @ evaluated.pose.bones[name].head * unit)
                for name in bones
            }
            if root:
                position = evaluated.matrix_world @ evaluated.pose.bones[root].head * unit
                root_start = position.copy() if root_start is None else root_start
                root_end = position.copy()
            measures = []
            for name, position in positions.items():
                distance = position[2] - ground
                is_contact = abs(distance) <= contact
                speed = None
                slides = False
                if previous:
                    old = previous["positions"][name]
                    duration = (frame - previous["frame"]) / fps
                    speed = math.hypot(position[0] - old[0], position[1] - old[1]) / duration
                    slides = is_contact and abs(old[2] - ground) <= contact and speed > speed_limit
                penetrates = distance < -penetration
                sliding += slides
                penetrating += penetrates
                measures.append(
                    {
                        "bone": name,
                        "position": position,
                        "ground_distance": distance,
                        "contact": is_contact,
                        "horizontal_speed": speed,
                        "sliding": slides,
                        "penetrating": penetrates,
                    }
                )
            samples.append({"frame": frame, "bones": measures})
            previous = {"frame": frame, "positions": positions}
    return {
        "schema_version": "1.0",
        "object_name": obj.name,
        "samples": samples,
        "coverage": "complete",
        "sliding_segments": sliding,
        "penetration_samples": penetrating,
        "root_displacement": (root_end - root_start).length if root else None,
        "settings": {
            "ground_height": ground,
            "contact_tolerance": contact,
            "sliding_speed": speed_limit,
            "penetration_tolerance": penetration,
        },
        "units": "meters_and_seconds_using_scene_scale",
        "limits": [
            "Bone heads compared against a horizontal plane",
            "No automatic foot identity, terrain collision or between-sample guarantee",
        ],
    }


def bake_animation(params: dict, context=None) -> dict:
    parameters(params, ("dry_run", "frame_start", "frame_end", "step", "max_samples"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "ARMATURE")
    frames = sample_frames(params)
    if len(source.data.bones) > 256:
        raise ValueError("Bake is limited to 256 bones")
    if any(bone.bbone_segments > 1 for bone in source.data.bones):
        raise ValueError("Bendy-bone segment deformation requires a separate export bake")
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "frame_count": len(frames),
        "bone_count": len(source.data.bones),
        "limits": [
            "Samples object/bone transforms; no retargeting or morph animation",
            "Exact sampled poses do not guarantee interpolation between samples",
        ],
    }
    if result["dry_run"]:
        return result
    import bpy
    from mathutils import Matrix

    derivative = None
    new_action = None
    try:
        with preserve_time(context, (source,)):
            captures = []
            for frame in frames:
                context.scene.frame_set(frame)
                evaluated = source.evaluated_get(context.evaluated_depsgraph_get())
                captures.append(
                    (
                        frame,
                        evaluated.matrix_world.copy(),
                        {bone.name: bone.matrix.copy() for bone in evaluated.pose.bones},
                    )
                )
            derivative = hidden_derivative(source, context, "Baked")
            derivative.animation_data_clear()
            derivative.data.animation_data_clear()
            derivative.parent = None
            derivative.constraints.clear()
            derivative.rotation_mode = "QUATERNION"
            for bone in derivative.pose.bones:
                for constraint in list(bone.constraints):
                    bone.constraints.remove(constraint)
                bone.rotation_mode = "QUATERNION"
            for frame, matrix_world, poses in captures:
                decomposed = Matrix.LocRotScale(*matrix_world.decompose())
                if (
                    max(
                        abs(matrix_world[i][j] - decomposed[i][j])
                        for i in range(3)
                        for j in range(3)
                    )
                    > 1e-5
                ):
                    raise ValueError("Object shear cannot be represented by this transform bake")
                derivative.matrix_world = matrix_world
                for path in ("location", "rotation_quaternion", "scale"):
                    derivative.keyframe_insert(path, frame=frame)
                new_action = derivative.animation_data.action
                for bone in derivative.pose.bones:
                    data = bone.bone
                    kwargs = {"invert": True}
                    if data.parent:
                        kwargs.update(
                            parent_matrix=poses[data.parent.name],
                            parent_matrix_local=data.parent.matrix_local,
                        )
                    basis = data.convert_local_to_pose(
                        poses[bone.name], data.matrix_local, **kwargs
                    )
                    reconstructed = Matrix.LocRotScale(*basis.decompose())
                    if (
                        max(
                            abs(basis[i][j] - reconstructed[i][j])
                            for i in range(3)
                            for j in range(3)
                        )
                        > 1e-5
                    ):
                        raise ValueError("Bone shear cannot be represented by this transform bake")
                    bone.matrix_basis = basis
                    for path in ("location", "rotation_quaternion", "scale"):
                        bone.keyframe_insert(path, frame=frame)
            new_action.name = f"{source.name}_FW_Baked"
            for layer in new_action.layers:
                for strip in layer.strips:
                    for bag in getattr(strip, "channelbags", ()):
                        for curve in bag.fcurves:
                            for key in curve.keyframe_points:
                                key.interpolation = "LINEAR"
            result.update(derivative=derivative.name, action=new_action.name, hidden=True)
        return result
    except Exception:
        if derivative is not None:
            discard_derivative(derivative)
        if new_action is not None and new_action.users == 0:
            bpy.data.actions.remove(new_action)
        raise


def retarget_animation(params: dict, context=None) -> dict:
    """Map sampled local rest-relative rotations onto a copied target skeleton."""
    parameters(
        params,
        (
            "source_name",
            "bone_map",
            "frame_start",
            "frame_end",
            "step",
            "max_samples",
            "dry_run",
            "root_bone",
            "translation_scale",
        ),
    )
    context = checked_context(context)
    target = scene_object(context, params["object_name"], "ARMATURE")
    if not isinstance(params.get("source_name"), str):
        raise ValueError("source_name must identify a source armature")
    source = scene_object(context, params["source_name"], "ARMATURE")
    mapping = params.get("bone_map")
    if not isinstance(mapping, dict) or not 1 <= len(mapping) <= 256:
        raise ValueError("bone_map must contain 1-256 explicit source-to-target bone names")
    if any(
        not isinstance(a, str)
        or not isinstance(b, str)
        or a not in source.data.bones
        or b not in target.data.bones
        for a, b in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Bone map names must exist and target bones must be unique")
    root = params.get("root_bone")
    if root is not None and (
        not isinstance(root, str)
        or root not in mapping
        or source.data.bones[root].parent
        or target.data.bones[mapping[root]].parent
    ):
        raise ValueError("root_bone must map a source root to a target root")
    translation_scale = finite(params.get("translation_scale", 1.0), "translation_scale", 0.0)
    if translation_scale > 1000:
        raise ValueError("translation_scale must not exceed 1000")
    frames = sample_frames(params)
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "target": target.name,
        "dry_run": params.get("dry_run", True),
        "bone_map": mapping,
        "frame_count": len(frames),
        "limits": [
            "Rest-relative local rotations require compatible bone-axis conventions",
            "No automatic proportion, foot-contact, object-root-motion or finger adaptation",
            "Unmapped bones retain their target rest pose",
        ],
    }
    if result["dry_run"]:
        return result
    import bpy
    from mathutils import Matrix

    derivative = None
    action = None
    target_world = target.matrix_world.copy()
    try:
        with preserve_time(context, (source, target)):
            captures = []
            for frame in frames:
                context.scene.frame_set(frame)
                evaluated = source.evaluated_get(context.evaluated_depsgraph_get())
                bases = {}
                for name in mapping:
                    bone = evaluated.pose.bones[name]
                    data = source.data.bones[name]
                    kwargs = {"invert": True}
                    if data.parent:
                        kwargs.update(
                            parent_matrix=evaluated.pose.bones[data.parent.name].matrix,
                            parent_matrix_local=data.parent.matrix_local,
                        )
                    basis = data.convert_local_to_pose(bone.matrix, data.matrix_local, **kwargs)
                    translation = (
                        basis.to_translation() * translation_scale if name == root else (0, 0, 0)
                    )
                    bases[mapping[name]] = Matrix.LocRotScale(
                        translation, basis.to_quaternion(), (1, 1, 1)
                    )
                captures.append((frame, bases))
            derivative = hidden_derivative(target, context, "Retarget")
            derivative.animation_data_clear()
            derivative.data.animation_data_clear()
            derivative.parent = None
            derivative.matrix_world = target_world
            derivative.constraints.clear()
            for bone in derivative.pose.bones:
                for constraint in list(bone.constraints):
                    bone.constraints.remove(constraint)
                bone.matrix_basis = Matrix.Identity(4)
                bone.rotation_mode = "QUATERNION"
            for frame, bases in captures:
                for name, basis in bases.items():
                    bone = derivative.pose.bones[name]
                    bone.matrix_basis = basis
                    for path in ("location", "rotation_quaternion", "scale"):
                        bone.keyframe_insert(path, frame=frame)
                action = derivative.animation_data.action
            action.name = f"{target.name}_FW_Retarget"
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for curve in bag.fcurves:
                            for key in curve.keyframe_points:
                                key.interpolation = "LINEAR"
            result.update(derivative=derivative.name, action=action.name, hidden=True)
        return result
    except Exception:
        if derivative is not None:
            discard_derivative(derivative)
        if action is not None and action.users == 0:
            bpy.data.actions.remove(action)
        raise


def cleanup_animation(params: dict, context=None) -> dict:
    """Smooth only interior location-key spikes on an unassigned duplicate Action."""
    parameters(params, ("frame_start", "frame_end", "dry_run", "threshold", "strength", "max_keys"))
    context = checked_context(context)
    obj = scene_object(context, params["object_name"])
    source = obj.animation_data.action if obj.animation_data else None
    if source is None:
        raise ValueError("Object must have an active action to duplicate")
    start = integer(params.get("frame_start"), -1_000_000, 1_000_000, "frame_start")
    end = integer(params.get("frame_end"), -1_000_000, 1_000_000, "frame_end")
    if end <= start:
        raise ValueError("Cleanup needs a nonempty frame interval")
    threshold = finite(params.get("threshold", 0.1), "threshold", 0.0)
    strength = finite(params.get("strength", 0.5), "strength", 0.0)
    if strength > 1:
        raise ValueError("strength must not exceed 1")
    maximum = integer(params.get("max_keys", 100_000), 1, 1_000_000, "max_keys")
    slot = obj.animation_data.action_slot
    if slot is None:
        raise ValueError("Cleanup requires an explicitly assigned active action slot")
    slot_handle = slot.handle
    curves = [
        curve
        for layer in source.layers
        for strip in layer.strips
        for bag in strip.channelbags
        if bag.slot_handle == slot_handle
        for curve in bag.fcurves
    ]
    if sum(len(curve.keyframe_points) for curve in curves) > maximum:
        raise ValueError("Action exceeds max_keys")
    changes = []
    for curve_index, curve in enumerate(curves):
        if curve.data_path != "location" and not curve.data_path.endswith(".location"):
            continue
        points = [tuple(key.co) for key in curve.keyframe_points]
        for index in range(1, len(points) - 1):
            previous, current, following = points[index - 1 : index + 2]
            if (
                not start < current[0] < end
                or previous[0] < start
                or following[0] > end
                or following[0] <= previous[0]
            ):
                continue
            expected = previous[1] + (following[1] - previous[1]) * (current[0] - previous[0]) / (
                following[0] - previous[0]
            )
            if abs(current[1] - expected) > threshold and strength > 0:
                changes.append(
                    (curve_index, index, current[1] + strength * (expected - current[1]))
                )
    result = {
        "schema_version": "1.0",
        "source_action": source.name,
        "dry_run": params.get("dry_run", True),
        "changed_keys": len(changes),
        "assigned": False,
        "slot_handle": slot_handle,
        "settings": {
            "threshold": threshold,
            "strength": strength,
            "frame_start": start,
            "frame_end": end,
        },
        "limits": [
            "Location keys only; purposeful accents can resemble spikes and require artist review",
            "Interval/end keys and all rotation/scale channels are preserved",
            "Duplicate action is retained with a fake user and is not assigned automatically",
        ],
    }
    if result["dry_run"] or not changes:
        return result
    import bpy

    action = source.copy()
    try:
        action.name = f"{source.name}_FW_Clean"
        action.use_fake_user = True
        copied_curves = [
            curve
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            if bag.slot_handle == slot_handle
            for curve in bag.fcurves
        ]
        for curve_index, index, value in changes:
            key = copied_curves[curve_index].keyframe_points[index]
            delta = value - key.co.y
            key.co.y = value
            key.handle_left.y += delta
            key.handle_right.y += delta
        result["action"] = action.name
        return result
    except Exception:
        bpy.data.actions.remove(action)
        raise
