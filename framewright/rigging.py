"""Bounded rig inspection and conservative source-preserving deformation tools."""

from __future__ import annotations

import math
import threading
from contextlib import contextmanager


def checked_context(context=None):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender rig workflows must run on the main thread")
    import bpy

    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before running a rig workflow")
    return context


def parameters(params, allowed, required=("object_name",)):
    if (
        not isinstance(params, dict)
        or set(params) - set(allowed) - set(required)
        or not set(required) <= set(params)
    ):
        raise ValueError("Missing or unknown workflow parameters")
    if (
        not isinstance(params.get("object_name"), str)
        or not params["object_name"]
        or len(params["object_name"]) > 256
    ):
        raise ValueError("object_name must be a nonempty exact name")
    if "dry_run" in params and type(params["dry_run"]) is not bool:
        raise ValueError("dry_run must be a boolean")


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def finite(value, label, minimum=None):
    if (
        type(value) not in {int, float}
        or not math.isfinite(value)
        or (minimum is not None and value < minimum)
    ):
        raise ValueError(
            f"{label} must be finite" + (f" and at least {minimum}" if minimum is not None else "")
        )
    return float(value)


def scene_object(context, name, expected=None):
    matches = [obj for obj in context.scene.objects if obj.name == name]
    if len(matches) != 1:
        raise ValueError("Object name is missing or ambiguous in the active scene")
    obj = matches[0]
    if expected and obj.type != expected:
        raise ValueError(f"Object must be an {expected}")
    return obj


def sample_frames(params):
    start = integer(params.get("frame_start"), -1_000_000, 1_000_000, "frame_start")
    end = integer(params.get("frame_end"), -1_000_000, 1_000_000, "frame_end")
    step = integer(params.get("step", 1), 1, 1000, "step")
    maximum = integer(params.get("max_samples", 128), 1, 256, "max_samples")
    if end < start:
        raise ValueError("frame_end must not precede frame_start")
    count = (end - start) // step + 1
    if count > maximum:
        raise ValueError(
            "Frame range exceeds max_samples; shorten range or increase step explicitly"
        )
    frames = list(range(start, end + 1, step))
    if frames[-1] != end:
        if len(frames) == maximum:
            raise ValueError("Including the end frame exceeds max_samples")
        frames.append(end)
    return frames


@contextmanager
def preserve_time(context, rigs=()):
    """Restore selected transforms and local character channels, not arbitrary RNA."""
    scene = context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    character_channels = _character_channels(context)
    poses = [
        (
            rig,
            _transform_channels(rig),
            [(bone.name, _transform_channels(bone)) for bone in rig.pose.bones]
            if rig.type == "ARMATURE"
            else [],
        )
        for rig in rigs
    ]
    try:
        yield
    finally:
        # A same-frame update re-evaluates animated RNA outside this bounded
        # character snapshot and can erase unrelated authored dirty values.
        if scene.frame_current != frame or scene.frame_subframe != subframe:
            scene.frame_set(frame, subframe=subframe)
        _restore_character_channels(character_channels)
        for rig, channels, bones in poses:
            _restore_transform_channels(rig, channels)
            for name, channels in bones:
                _restore_transform_channels(rig.pose.bones[name], channels)
        context.view_layer.update()
        # An update may evaluate drivers. Retain manually overridden authored
        # character values as they were before sampling, including dirty values.
        _restore_character_channels(character_channels)


def _numeric_custom_channels(owner):
    result = []
    for name, value in owner.items():
        if isinstance(value, (bool, int, float)):
            result.append((owner, name, value, False))
        elif hasattr(value, "to_list"):
            values = tuple(value.to_list())
            if all(isinstance(item, (bool, int, float)) for item in values):
                result.append((owner, name, values, True))
    return result


def _character_channels(context):
    """Numeric ID properties and local shape channels affected by frame_set."""
    properties, shapes, seen_data, seen_keys = [], [], set(), set()
    for obj in context.scene.objects:
        if obj.library:
            continue
        properties.extend(_numeric_custom_channels(obj))
        if obj.type == "ARMATURE":
            for bone in obj.pose.bones:
                properties.extend(_numeric_custom_channels(bone))
        data = obj.data
        if data is None or data.library or data.as_pointer() in seen_data:
            continue
        seen_data.add(data.as_pointer())
        properties.extend(_numeric_custom_channels(data))
        keys = getattr(data, "shape_keys", None)
        if keys is not None and not keys.library and keys.as_pointer() not in seen_keys:
            seen_keys.add(keys.as_pointer())
            properties.extend(_numeric_custom_channels(keys))
            shapes.append(
                (keys, keys.eval_time, [(key, key.value, key.mute) for key in keys.key_blocks])
            )
    return properties, shapes


def _restore_character_channels(state):
    properties, shapes = state
    for owner, name, value, is_array in properties:
        if is_array:
            if tuple(owner[name]) != value:
                owner[name][:] = value
        elif owner[name] != value:
            owner[name] = value
    for keys, eval_time, blocks in shapes:
        if keys.eval_time != eval_time:
            keys.eval_time = eval_time
        for key, value, mute in blocks:
            if key.value != value:
                key.value = value
            if key.mute != mute:
                key.mute = mute


def _transform_channels(owner):
    fields = (
        "location",
        "rotation_euler",
        "rotation_quaternion",
        "rotation_axis_angle",
        "scale",
        "delta_location",
        "delta_rotation_euler",
        "delta_rotation_quaternion",
        "delta_scale",
    )
    state = {name: tuple(getattr(owner, name)) for name in fields if hasattr(owner, name)}
    state["rotation_mode"] = owner.rotation_mode
    if hasattr(owner, "matrix_parent_inverse"):
        state["matrix_parent_inverse"] = tuple(tuple(row) for row in owner.matrix_parent_inverse)
    return state


def _restore_transform_channels(owner, state):
    if owner.rotation_mode != state["rotation_mode"]:
        owner.rotation_mode = state["rotation_mode"]
    for name, values in state.items():
        if name == "rotation_mode":
            continue
        current = getattr(owner, name)
        current = (
            tuple(tuple(row) for row in current)
            if name == "matrix_parent_inverse"
            else tuple(current)
        )
        if current != values:
            setattr(owner, name, values)


def hidden_derivative(obj, context, suffix):
    derivative = obj.copy()
    try:
        derivative.data = obj.data.copy()
        derivative.name = f"{obj.name}_FW_{suffix}"
        context.scene.collection.objects.link(derivative)
        derivative.select_set(False)
        derivative.hide_viewport = True
        derivative.hide_render = True
        return derivative
    except Exception:
        discard_derivative(derivative)
        raise


def discard_derivative(obj):
    import bpy

    data = obj.data
    kind = (
        bpy.data.meshes
        if obj.type == "MESH"
        else bpy.data.armatures
        if obj.type == "ARMATURE"
        else None
    )
    bpy.data.objects.remove(obj, do_unlink=True)
    if kind is not None and data.users == 0:
        kind.remove(data)


def _bound_armature(obj):
    targets = {
        modifier.object
        for modifier in obj.modifiers
        if modifier.type == "ARMATURE" and modifier.object
    }
    if len(targets) != 1:
        raise ValueError("Mesh must have exactly one bound armature")
    return targets.pop()


def _protected(params, count):
    values = params.get("protected_vertices", [])
    if not isinstance(values, list) or len(values) > count:
        raise ValueError("protected_vertices must be a bounded list of vertex indexes")
    for index in values:
        integer(index, 0, count - 1, "protected vertex")
    if len(set(values)) != len(values):
        raise ValueError("protected_vertices must be unique")
    return set(values)


def inspect_rig(params: dict, context=None) -> dict:
    parameters(params, ())
    context = checked_context(context)
    obj = scene_object(context, params["object_name"], "ARMATURE")
    bones = [
        {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "use_deform": bone.use_deform,
            "connected": bone.use_connect,
            "head": list(bone.head_local),
            "tail": list(bone.tail_local),
            "length": bone.length,
            "rest_matrix": [list(row) for row in bone.matrix_local],
            "constraints": [
                constraint.type for constraint in obj.pose.bones[bone.name].constraints
            ],
        }
        for bone in sorted(obj.data.bones, key=lambda bone: bone.name)
    ]
    return {
        "schema_version": "1.0",
        "object_name": obj.name,
        "bones": bones,
        "root_bones": [bone["name"] for bone in bones if bone["parent"] is None],
        "bound_meshes": sorted(
            mesh.name
            for mesh in context.scene.objects
            if mesh.type == "MESH"
            and any(mod.type == "ARMATURE" and mod.object == obj for mod in mesh.modifiers)
        ),
        "scale": list(obj.scale),
        "unit_scale": context.scene.unit_settings.scale_length,
        "linked_source": bool(obj.library or obj.data.library),
        "coverage": "complete",
        "limits": [
            "Rest hierarchy and constraints are metadata, not deformation acceptance",
            "No automatic humanoid bone-name mapping",
        ],
    }


def normalize_weights(params: dict, context=None) -> dict:
    parameters(params, ("dry_run", "protected_vertices", "max_influences", "max_vertices"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    maximum = integer(params.get("max_vertices", 200_000), 1, 1_000_000, "max_vertices")
    if len(source.data.vertices) > maximum:
        raise ValueError("Mesh exceeds max_vertices; explicit scope or budget increase is required")
    influences = integer(params.get("max_influences", 4), 1, 32, "max_influences")
    protected = _protected(params, len(source.data.vertices))
    rig = _bound_armature(source)
    deform_names = {bone.name for bone in rig.data.bones if bone.use_deform}
    deform = {group.index: group for group in source.vertex_groups if group.name in deform_names}
    if not deform:
        raise ValueError("Mesh has no vertex groups matching deform bones")
    changes = {}
    unresolved = []
    for vertex in source.data.vertices:
        if vertex.index in protected:
            continue
        weights = {
            group.group: group.weight
            for group in vertex.groups
            if group.group in deform and group.weight > 0
        }
        locked = {index: weight for index, weight in weights.items() if deform[index].lock_weight}
        free = {index: weight for index, weight in weights.items() if not deform[index].lock_weight}
        locked_total = sum(locked.values())
        slots = influences - len(locked)
        if locked_total > 1 + 1e-6 or slots < 0:
            unresolved.append(
                {
                    "vertex": vertex.index,
                    "reason": "locked weights exceed normalization or influence budget",
                }
            )
            continue
        keep = dict(sorted(free.items(), key=lambda item: (-item[1], item[0]))[: max(0, slots)])
        remainder = max(0.0, 1.0 - locked_total)
        if remainder > 1e-6 and not keep:
            unresolved.append(
                {
                    "vertex": vertex.index,
                    "reason": "no unlocked weighted deform group can receive remainder",
                }
            )
            continue
        total = sum(keep.values())
        updates = {
            index: keep.get(index, 0.0) / total * remainder if total else 0.0 for index in free
        }
        if any(abs(updates[index] - free[index]) > 1e-6 for index in updates):
            changes[vertex.index] = updates
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "changed_vertices": len(changes),
        "protected_vertices": len(protected),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved[:100],
        "max_influences": influences,
        "armature": rig.name,
        "limits": [
            "Locked, protected and nondeform weights are retained",
            "Unweighted regions are not guessed; artist deformation review remains required",
        ],
    }
    if result["dry_run"] or not changes:
        return result
    derivative = hidden_derivative(source, context, "Weights")
    try:
        for vertex_index, updates in changes.items():
            for group_index, weight in updates.items():
                if weight > 0:
                    derivative.vertex_groups[group_index].add([vertex_index], weight, "REPLACE")
                else:
                    derivative.vertex_groups[group_index].remove([vertex_index])
        result.update(derivative=derivative.name, hidden=True)
        return result
    except Exception:
        discard_derivative(derivative)
        raise


def sample_deformation(params: dict, context=None) -> dict:
    parameters(params, ("frame_start", "frame_end", "step", "max_samples", "max_vertices"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    rig = _bound_armature(source)
    frames = sample_frames(params)
    maximum = integer(params.get("max_vertices", 20_000), 1, 200_000, "max_vertices")
    samples = []
    reference_edges = None
    reference_lengths = None
    reference_vertex_count = None
    unit_scale = context.scene.unit_settings.scale_length
    with preserve_time(context, (rig, source)):
        for frame in frames:
            context.scene.frame_set(frame)
            depsgraph = context.evaluated_depsgraph_get()
            evaluated = source.evaluated_get(depsgraph)
            try:
                mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                if len(mesh.vertices) > maximum:
                    raise ValueError("Evaluated mesh exceeds max_vertices")
                coords = [
                    evaluated.matrix_world @ vertex.co * unit_scale for vertex in mesh.vertices
                ]
                edges = [tuple(edge.vertices) for edge in mesh.edges]
                lengths = [(coords[a] - coords[b]).length for a, b in edges]
                if reference_edges is None:
                    reference_edges, reference_lengths = edges, lengths
                    reference_vertex_count = len(coords)
                elif edges != reference_edges or len(coords) != reference_vertex_count:
                    raise ValueError(
                        "Topology changes across frames; index-correspondence comparison is unsupported"
                    )
                ratios = [
                    value / baseline
                    for value, baseline in zip(lengths, reference_lengths, strict=True)
                    if baseline > 1e-12
                ]
                incidence = {tuple(sorted(edge)): 0 for edge in edges}
                for polygon in mesh.polygons:
                    for edge in polygon.edge_keys:
                        key = tuple(sorted(edge))
                        incidence[key] = incidence.get(key, 0) + 1
                closed = bool(incidence) and all(count == 2 for count in incidence.values())
                volume = None
                if closed:
                    mesh.calc_loop_triangles()
                    volume = sum(
                        coords[tri.vertices[0]].dot(
                            coords[tri.vertices[1]].cross(coords[tri.vertices[2]])
                        )
                        / 6
                        for tri in mesh.loop_triangles
                    )
                samples.append(
                    {
                        "frame": frame,
                        "vertex_count": len(coords),
                        "max_edge_ratio": max(ratios, default=None),
                        "min_edge_ratio": min(ratios, default=None),
                        "closed_surface": closed,
                        "signed_volume": volume,
                        "minimum_world_z": min((co.z for co in coords), default=None),
                    }
                )
            finally:
                evaluated.to_mesh_clear()
    return {
        "schema_version": "1.0",
        "object_name": source.name,
        "armature": rig.name,
        "coverage": "complete",
        "reference_frame": frames[0],
        "samples": samples,
        "unit": "meters_using_scene_unit_scale",
        "limits": [
            "Samples existing animation only; no artist pose approval",
            "Edge ratios compare the first sampled frame, not an anatomical ideal",
            "Closed-mesh signed volume may cancel for inconsistent winding",
            "No between-sample motion guarantee",
        ],
    }


def corrective_shape(params: dict, context=None) -> dict:
    parameters(params, ("name", "offsets", "protected_vertices", "dry_run"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    name = params.get("name")
    if not isinstance(name, str) or not name or len(name) > 63 or name == "Basis":
        raise ValueError("Corrective name must be 1-63 characters and cannot be Basis")
    existing = source.data.shape_keys
    if existing and (not existing.use_relative or name in existing.key_blocks):
        raise ValueError("Requires relative shape keys and a new corrective name")
    protected = _protected(params, len(source.data.vertices))
    offsets = params.get("offsets")
    if not isinstance(offsets, list) or not 1 <= len(offsets) <= 10_000:
        raise ValueError("offsets must contain 1-10000 explicit vertex offsets")
    validated = {}
    for item in offsets:
        if not isinstance(item, dict) or set(item) != {"vertex", "offset"}:
            raise ValueError("Each offset needs vertex and offset")
        vertex = integer(item["vertex"], 0, len(source.data.vertices) - 1, "vertex")
        if vertex in protected or vertex in validated:
            raise ValueError("Offsets cannot target protected or duplicate vertices")
        values = item["offset"]
        if not isinstance(values, list) or len(values) != 3:
            raise ValueError("offset must contain three coordinates")
        validated[vertex] = tuple(finite(value, "offset coordinate") for value in values)
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "name": name,
        "dry_run": params.get("dry_run", True),
        "affected_vertices": len(validated),
        "protected_vertices": len(protected),
        "basis_relative": True,
    }
    if result["dry_run"]:
        return result
    from mathutils import Vector

    derivative = hidden_derivative(source, context, "Corrective")
    try:
        if existing and derivative.data.shape_keys is existing:
            raise RuntimeError("Copied mesh unexpectedly shares shape-key data")
        basis = (
            derivative.data.shape_keys.key_blocks[0]
            if derivative.data.shape_keys
            else derivative.shape_key_add(name="Basis", from_mix=False)
        )
        key = derivative.shape_key_add(name=name, from_mix=False)
        key.relative_key = basis
        for vertex, values in validated.items():
            key.data[vertex].co = basis.data[vertex].co + Vector(values)
        key.value = 0.0
        result.update(derivative=derivative.name, hidden=True)
        return result
    except Exception:
        discard_derivative(derivative)
        raise


def generate_rig(params: dict, context=None) -> dict:
    """Generate a fresh rig from a copied metarig using enabled stock Rigify types."""
    parameters(params, ("dry_run",))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "ARMATURE")
    import addon_utils
    import bpy

    if not addon_utils.check("rigify")[1]:
        raise ValueError("Enable Blender's bundled Rigify add-on before generating a rig")
    from rigify import feature_set_list, rig_lists
    from rigify.generate import generate_rig as stock_generate

    if source.data.rigify_finalize_script is not None:
        raise ValueError("Custom Rigify finalize scripts are not allowed by this command")
    if not 1 <= len(source.data.bones) <= 256:
        raise ValueError("Metarig must contain 1-256 bones")
    types = []
    for bone in source.pose.bones:
        rig_type = bone.rigify_type
        if rig_type:
            entry = rig_lists.rigs.get(rig_type)
            if not entry or entry["feature_set"] != feature_set_list.DEFAULT_NAME:
                raise ValueError("Only bundled stock Rigify bone types are supported")
            types.append(rig_type)
    if not types:
        raise ValueError("Metarig has no stock Rigify bone types")
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "rig_types": sorted(set(types)),
        "limits": [
            "Control generation does not skin or visually validate a character",
            "Custom scripts and external Rigify feature sets are refused",
        ],
    }
    if result["dry_run"]:
        return result
    stores = (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.armatures,
        bpy.data.collections,
        bpy.data.texts,
        bpy.data.actions,
    )
    before = [{item.as_pointer() for item in store} for store in stores]
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    try:
        derivative = hidden_derivative(source, context, "Metarig")
        derivative.animation_data_clear()
        derivative.data.animation_data_clear()
        for name in (
            "rigify_target_rig",
            "rigify_rig_ui",
            "rigify_widgets_collection",
            "rigify_finalize_script",
        ):
            setattr(derivative.data, name, None)
        derivative.data.rigify_rig_basename = f"{source.name}_FW_Rig"
        for bone in derivative.pose.bones:
            bone.custom_shape = None
        derivative.hide_viewport = False
        for obj in selected:
            obj.select_set(False)
        derivative.select_set(True)
        context.view_layer.objects.active = derivative
        context.view_layer.update()
        stock_generate(context, derivative)
        generated = derivative.data.rigify_target_rig
        if generated is None or generated.as_pointer() in before[0]:
            raise RuntimeError("Rigify did not create a fresh rig")
        # Stock Rigify initializes a new target at identity while retaining local
        # metarig bone coordinates. Keep the explicitly chosen source placement.
        generated.matrix_world = source.matrix_world.copy()
        context.view_layer.update()
        new_objects = [obj for obj in bpy.data.objects if obj.as_pointer() not in before[0]]
        for obj in new_objects:
            obj.hide_viewport = True
            obj.hide_render = True
        result.update(
            derivative=generated.name,
            metarig_derivative=derivative.name,
            created_objects=sorted(obj.name for obj in new_objects),
            hidden=True,
        )
        return result
    except Exception:
        if context.mode != "OBJECT" and context.view_layer.objects.active:
            bpy.ops.object.mode_set(mode="OBJECT")
        for store, retained in zip(stores, before, strict=True):
            for item in list(store):
                if item.as_pointer() not in retained:
                    store.remove(item, do_unlink=True)
        raise
    finally:
        if context.mode != "OBJECT" and context.view_layer.objects.active:
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
