"""Scoped GLB/FBX handoff from a disposable scene into new files only."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import bpy

from . import export_materials
from .skin_contacts import _numeric_path


def _request(params, context):
    defaults = {
        "object_names": [],
        "directory": "",
        "filename": "asset",
        "format": "GLB",
        "include_animation": False,
        "animation_substeps": 1,
        "max_animation_samples": 16384,
        "profile": "generic",
        "max_material_memory_mb": 512,
        "clamp_scalar_textures": False,
        "dry_run": True,
    }
    if not isinstance(params, dict) or set(params) - set(defaults):
        raise ValueError("Unknown or invalid export parameters")
    p = dict(defaults, **params)
    if type(p["dry_run"]) is not bool or type(p["include_animation"]) is not bool:
        raise ValueError("dry_run and include_animation must be booleans")
    if type(p["animation_substeps"]) is not int or not 1 <= p["animation_substeps"] <= 64:
        raise ValueError("animation_substeps must be an integer from 1 to 64")
    if type(p["max_animation_samples"]) is not int or not 1 <= p["max_animation_samples"] <= 65536:
        raise ValueError("max_animation_samples must be an integer from 1 to 65536")
    if p["animation_substeps"] > 1 and not p["include_animation"]:
        raise ValueError("animation_substeps > 1 requires include_animation=true")
    if (
        type(p["max_material_memory_mb"]) is not int
        or not 1 <= p["max_material_memory_mb"] <= 32768
    ):
        raise ValueError("max_material_memory_mb must be an integer from 1 to 32768")
    if not isinstance(p["format"], str) or p["format"] not in {"GLB", "FBX"}:
        raise ValueError("format must be GLB or FBX")
    if type(p["clamp_scalar_textures"]) is not bool or (
        p["clamp_scalar_textures"] and p["format"] != "FBX"
    ):
        raise ValueError(
            "clamp_scalar_textures must be a boolean; true applies only to owned FBX scalar staging"
        )
    if not isinstance(p["profile"], str) or p["profile"] not in {"generic", "sundown"}:
        raise ValueError("profile must be generic or sundown")
    if not isinstance(p["filename"], str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]{0,63}", p["filename"]
    ):
        raise ValueError("filename must be a safe basename without extension")
    if p["filename"].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("filename is a reserved device name")
    if not isinstance(p["directory"], str) or not p["directory"]:
        raise ValueError("directory must be an explicit existing directory")
    directory = Path(p["directory"]).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("Export directory must already exist")
    names = p["object_names"]
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 500
        or not all(isinstance(name, str) and name for name in names)
    ):
        raise ValueError("object_names must contain 1 to 500 exact active-scene names")
    if len(set(names)) != len(names):
        raise ValueError("object_names must not contain duplicates")
    objects = []
    for name in names:
        matches = [obj for obj in context.scene.objects if obj.name == name]
        if len(matches) != 1:
            raise ValueError("Object name is missing or ambiguous in the active scene")
        obj = matches[0]
        if obj.type not in {"MESH", "EMPTY", "ARMATURE"}:
            raise ValueError("Export supports exact active-scene mesh, empty and armature objects")
        objects.append(obj)
    selected = set(objects)
    for obj in objects:
        if obj.parent is not None and obj.parent not in selected:
            raise ValueError(f"Include parent {obj.parent.name!r} explicitly")
        for modifier in obj.modifiers:
            if modifier.type not in {
                "ARMATURE",
                "BEVEL",
                "WEIGHTED_NORMAL",
                "SUBSURF",
                "DECIMATE",
                "TRIANGULATE",
                "SOLIDIFY",
                "SMOOTH",
            }:
                raise ValueError(
                    f"Bake unsupported modifier {modifier.type!r} before scoped export"
                )
            target = getattr(modifier, "object", None)
            if target is not None and target not in selected:
                raise ValueError(f"Include modifier dependency {target.name!r} explicitly")
            if modifier.type == "ARMATURE" and target is not None and obj.parent != target:
                raise ValueError(
                    "Parent skinned meshes to their selected armature before scoped export"
                )
            if (
                modifier.type == "ARMATURE"
                and target is not None
                and any(b.use_deform and b.bbone_segments > 1 for b in target.data.bones)
            ):
                raise ValueError(
                    "Bake segmented B-Bone skin explicitly before scoped export; raw segment deformation is not portable"
                )
        if obj.constraints or (
            obj.type == "ARMATURE" and any(bone.constraints for bone in obj.pose.bones)
        ):
            raise ValueError("Constraint rigs must be baked before this scoped export")
        if obj.animation_data and obj.animation_data.drivers:
            raise ValueError("Driver animation must be baked before this scoped export")
        for datablock in (obj.data, getattr(obj.data, "shape_keys", None)):
            animation = getattr(datablock, "animation_data", None)
            if animation and animation.drivers:
                raise ValueError("Datablock/shape-key drivers must be baked before scoped export")
        if obj.instance_type != "NONE":
            raise ValueError("Realize instances into owned objects before scoped export")
    if not any(obj.type == "MESH" for obj in objects):
        raise ValueError("Export requires at least one mesh")
    path = directory / (p["filename"] + "." + p["format"].lower())
    receipt_path = directory / (p["filename"] + ".receipt.json")
    if path.exists() or receipt_path.exists():
        raise FileExistsError("Output or receipt already exists; choose a new filename")
    p["directory"] = str(directory)
    return p, sorted(objects, key=lambda obj: obj.name), path, receipt_path


def _hash_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _matrix(matrix):
    return [[float(value) for value in row] for row in matrix]


def _animation_owners(obj):
    return (obj, obj.data, getattr(obj.data, "shape_keys", None))


def _action_curves(action, slot_handle=None):
    return [
        curve
        for layer in action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        if slot_handle is None or bag.slot_handle == slot_handle
        for curve in bag.fcurves
    ]


def _animation_plan(objects, context, params):
    if any(
        getattr(bpy.app.handlers, name)
        for name in (
            "frame_change_pre",
            "frame_change_post",
            "depsgraph_update_pre",
            "depsgraph_update_post",
        )
    ):
        raise ValueError("Isolated export refuses registered frame/depsgraph handlers")
    step = params["animation_substeps"]
    scene = context.scene
    samples = (scene.frame_end - scene.frame_start) * step + 1 if params["include_animation"] else 0
    channels = (
        len(objects)
        + sum(len(o.pose.bones) for o in objects if o.type == "ARMATURE")
        + sum(
            len(o.data.shape_keys.key_blocks) - 1
            for o in objects
            if o.type == "MESH" and o.data.shape_keys
        )
    )
    if samples > params["max_animation_samples"]:
        raise ValueError("Export sampling exceeds max_animation_samples budget")
    if samples * channels > 2_000_000:
        raise ValueError("Export exceeds the fixed 2m object/bone/shape channel-sample work limit")
    if params["include_animation"]:
        for obj in objects:
            for owner in _animation_owners(obj):
                animation = getattr(owner, "animation_data", None)
                if not animation:
                    continue
                actions = (
                    [
                        (
                            animation.action,
                            animation.action_slot.handle if animation.action_slot else None,
                        )
                    ]
                    if animation.action
                    else []
                )
                pending = [strip for track in animation.nla_tracks for strip in track.strips]
                inspected = 0
                while pending:
                    strip = pending.pop()
                    inspected += 1
                    if inspected > 2048:
                        raise ValueError("NLA action inspection exceeds its fixed strip budget")
                    if strip.action:
                        slot = getattr(strip, "action_slot", None)
                        actions.append((strip.action, slot.handle if slot else None))
                    pending.extend(getattr(strip, "strips", ()))
                for action, slot_handle in set(actions):
                    curves = _action_curves(action, slot_handle)
                    if len(curves) > 32768:
                        raise ValueError("Active action exceeds the export curve-inspection budget")
                    for curve in curves:
                        _numeric_path(owner, curve.data_path)
    plan = {
        "substeps": step,
        "sample_count": samples,
        "channel_sample_count": samples * channels,
        "sample_budget": params["max_animation_samples"],
        "channel_sample_limit": 2_000_000,
        "source_fps": scene.render.fps / scene.render.fps_base,
        "staged_fps": scene.render.fps * step / scene.render.fps_base,
        "source_frame_range": [scene.frame_start, scene.frame_end],
        "staged_frame_range": [scene.frame_start * step, scene.frame_end * step],
        "semantics": "Owned copied actions and scene timebase scale together; physical duration is preserved; sampled export is not a continuous-error guarantee",
    }
    if step == 1:
        return plan
    fps_property = scene.render.bl_rna.properties["fps"]
    if not fps_property.hard_min <= scene.render.fps * step <= fps_property.hard_max:
        raise ValueError("Scaled export FPS exceeds Blender's representable FPS range")
    for name, value in (
        ("frame_start", scene.frame_start),
        ("frame_end", scene.frame_end),
        ("frame_current", scene.frame_current + scene.frame_subframe),
    ):
        prop = scene.bl_rna.properties[name]
        if not prop.hard_min <= value * step <= prop.hard_max:
            raise ValueError(
                "Scaled export frame timing exceeds Blender's representable frame range"
            )
    if scene.render.frame_map_old != scene.render.frame_map_new:
        raise ValueError("Scene time remapping is unsupported for fractional export sampling")
    for obj in objects:
        for owner in _animation_owners(obj):
            animation = getattr(owner, "animation_data", None)
            if not animation:
                continue
            if animation.nla_tracks:
                raise ValueError("NLA must be baked before fractional export sampling")
            action = animation.action
            if not action:
                continue
            if action.library or action.override_library or animation.action_slot is None:
                raise ValueError("Fractional export requires local actions with explicit slots")
            if (
                len(action.layers) != 1
                or len(action.layers[0].strips) != 1
                or action.layers[0].strips[0].type != "KEYFRAME"
            ):
                raise ValueError("Fractional export supports a single keyframe action layer/strip")
            curves = _action_curves(action)
            if len(curves) > 32768:
                raise ValueError("Action exceeds the fractional-export curve budget")
            for curve in curves:
                if curve.modifiers or curve.sampled_points:
                    raise ValueError(
                        "FCurve modifiers/sampled points require baking before fractional export"
                    )
                for key in curve.keyframe_points:
                    if key.interpolation not in {"CONSTANT", "LINEAR", "BEZIER"}:
                        raise ValueError(
                            "Fractional export supports Constant, Linear and Bezier interpolation"
                        )
                    if any(
                        not math.isfinite(v)
                        for coord in (key.co, key.handle_left, key.handle_right)
                        for v in coord
                    ):
                        raise ValueError("Action keys and handles must be finite")
                    if any(
                        abs(coord.x * step) > 1_048_574
                        for coord in (key.co, key.handle_left, key.handle_right)
                    ):
                        raise ValueError(
                            "Scaled action keys/handles exceed the supported frame range"
                        )
    return plan


def _scale_owned_action(action, substeps):
    if action.use_frame_range:
        start, end = action.frame_start, action.frame_end
        action.frame_start, action.frame_end = start * substeps, end * substeps
    for curve in _action_curves(action):
        coordinates = [
            (tuple(key.co), tuple(key.handle_left), tuple(key.handle_right))
            for key in curve.keyframe_points
        ]
        for key, (co, left, right) in zip(curve.keyframe_points, coordinates, strict=True):
            key.co = (co[0] * substeps, co[1])
            key.handle_left = (left[0] * substeps, left[1])
            key.handle_right = (right[0] * substeps, right[1])
        curve.update()


def _source_record(objects):
    records = []
    for obj in objects:
        record = {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "matrix_world": _matrix(obj.matrix_world),
            "matrix_local": _matrix(obj.matrix_local),
            "materials": [
                slot.material.name if slot.material else None for slot in obj.material_slots
            ],
        }
        if obj.type == "MESH":
            mesh = obj.data
            geometry = {
                "vertices": [list(vertex.co) for vertex in mesh.vertices],
                "faces": [list(face.vertices) for face in mesh.polygons],
                "material_indices": [face.material_index for face in mesh.polygons],
                "uvs": {
                    layer.name: [list(loop.uv) for loop in layer.data] for layer in mesh.uv_layers
                },
                "weights": [
                    [(group.group, group.weight) for group in vertex.groups]
                    for vertex in mesh.vertices
                ],
                "vertex_groups": [group.name for group in obj.vertex_groups],
            }
            record.update(
                vertices=len(mesh.vertices),
                source_triangles=sum(len(face.vertices) - 2 for face in mesh.polygons),
                uv_layers=[layer.name for layer in mesh.uv_layers],
                geometry_sha256=_hash_json(geometry),
                modifiers=[modifier.type for modifier in obj.modifiers],
            )
        elif obj.type == "ARMATURE":
            record["bones"] = [
                {
                    "name": bone.name,
                    "parent": bone.parent.name if bone.parent else None,
                    "matrix_local": _matrix(bone.matrix_local),
                    "deform": bone.use_deform,
                }
                for bone in obj.data.bones
            ]
            record["pose_basis"] = {
                bone.name: _matrix(bone.matrix_basis) for bone in obj.pose.bones
            }
        if obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            record["action"] = {"name": action.name, "frame_range": list(action.frame_range)}
        records.append(record)
    return records


@contextmanager
def _staging(objects, context, include_animation=False, animation_substeps=1):
    original_scene = context.scene
    original_layer = context.view_layer
    original_window = context.window
    original_active = original_layer.objects.active
    original_selection = [
        (obj, obj.select_get(view_layer=original_layer)) for obj in original_layer.objects
    ]
    original_frame = (original_scene.frame_current, original_scene.frame_subframe)
    scene = bpy.data.scenes.new("FW_ExportStage")
    copies = {}
    data_copies = []
    owned_actions = []
    try:
        scene.render.fps = context.scene.render.fps
        scene.render.fps_base = context.scene.render.fps_base
        scene.frame_start, scene.frame_end = context.scene.frame_start, context.scene.frame_end
        scene.unit_settings.system = context.scene.unit_settings.system
        scene.unit_settings.scale_length = context.scene.unit_settings.scale_length
        for source in objects:
            copy = source.copy()
            copies[source] = copy
            copy.name = "FW_Export_" + source.name
            if source.data:
                copy.data = source.data.copy()
                data_copies.append(("meshes" if source.type == "MESH" else "armatures", copy.data))
            if not include_animation:
                # Static handoff freezes the explicitly authored current state,
                # including dirty overrides; clearing only copied animation does
                # not edit or unlink the source's actions/NLA/key data.
                for data in (copy, copy.data, getattr(copy.data, "shape_keys", None)):
                    if data is not None and getattr(data, "animation_data", None) is not None:
                        data.animation_data_clear()
            copy["framewright_source_name"] = source.name
            scene.collection.objects.link(copy)
        if animation_substeps > 1:
            scene.render.fps *= animation_substeps
            scene.frame_start *= animation_substeps
            scene.frame_end *= animation_substeps
            for copy in copies.values():
                for owner in _animation_owners(copy):
                    animation = getattr(owner, "animation_data", None)
                    if animation and animation.action:
                        identifier = animation.action_slot.identifier
                        action = animation.action.copy()
                        owned_actions.append(action)
                        animation.action = action
                        animation.action_slot = next(
                            slot for slot in action.slots if slot.identifier == identifier
                        )
                        _scale_owned_action(action, animation_substeps)
        for source, copy in copies.items():
            copy.parent = copies.get(source.parent)
            copy.matrix_world = source.matrix_world.copy()
            for modifier in copy.modifiers:
                target = getattr(modifier, "object", None)
                if target is not None:
                    modifier.object = copies[target]
            copy.hide_render = False
            copy.hide_viewport = False
            copy.select_set(True, view_layer=scene.view_layers[0])
        scene.view_layers[0].objects.active = next(
            copy for copy in copies.values() if copy.type == "MESH"
        )
        staged_frame = (original_frame[0] + original_frame[1]) * animation_substeps
        scene.frame_set(math.floor(staged_frame), subframe=staged_frame % 1)
        scene.view_layers[0].update()
        yield scene, copies
    finally:
        # Some exporters assign Window.scene internally despite a context
        # override. Restore it before deleting the owned staging scene.
        if original_window is not None:
            if original_window.scene != original_scene:
                original_window.scene = original_scene
            if original_window.view_layer != original_layer:
                original_window.view_layer = original_layer
        # The owned scene is the only animation-evaluation target. Refreshing the
        # unchanged source scene resets authored dirty values on unrelated IDs.
        if (original_scene.frame_current, original_scene.frame_subframe) != original_frame:
            original_scene.frame_set(original_frame[0], subframe=original_frame[1])
        for obj, selected in original_selection:
            obj.select_set(selected, view_layer=original_layer)
        original_layer.objects.active = original_active
        for copy in copies.values():
            bpy.data.objects.remove(copy, do_unlink=True)
        bpy.data.scenes.remove(scene, do_unlink=True)
        for kind, data in data_copies:
            getattr(bpy.data, kind).remove(data, do_unlink=True)
        for action in owned_actions:
            if not action.users:
                bpy.data.actions.remove(action)


def _reference(scene, copies, include_animation):
    normalized = (0, 0.5, 1) if include_animation else (0,)
    bounds = {source.name: [] for source in copies if source.type == "MESH"}
    original_frame = (scene.frame_current, scene.frame_subframe)
    try:
        with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            for time in normalized:
                frame = (
                    scene.frame_start + time * (scene.frame_end - scene.frame_start)
                    if include_animation
                    else original_frame[0] + original_frame[1]
                )
                integer = math.floor(frame)
                scene.frame_set(integer, subframe=frame - integer)
                graph = bpy.context.evaluated_depsgraph_get()
                for source, copy in copies.items():
                    if source.type != "MESH":
                        continue
                    evaluated = copy.evaluated_get(graph)
                    mesh = evaluated.to_mesh()
                    try:
                        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
                        if not points:
                            bounds[source.name].append(None)
                        else:
                            bounds[source.name].append(
                                [
                                    [min(point[axis] for point in points) for axis in range(3)],
                                    [max(point[axis] for point in points) for axis in range(3)],
                                ]
                            )
                    finally:
                        evaluated.to_mesh_clear()
    finally:
        scene.frame_set(original_frame[0], subframe=original_frame[1])
    return {
        "normalized_times": list(normalized),
        "normalized_mesh_bounds": bounds,
        "scope": "Bounds reference only; full surface/UV/material/render comparison remains separate",
    }


def _settings(format_name, include_animation, has_morphs=False):
    if format_name == "GLB":
        return {
            "export_format": "GLB",
            "use_selection": True,
            "use_active_scene": True,
            "export_extras": True,
            "export_yup": True,
            "export_apply": not has_morphs,
            "export_morph": True,
            "export_morph_animation": include_animation,
            "export_anim_scene_split_object": not has_morphs,
            "export_texcoords": True,
            "export_normals": True,
            "export_materials": "EXPORT",
            "export_animations": include_animation,
            "export_frame_range": True,
            "export_force_sampling": True,
            "export_animation_mode": "SCENE",
            "export_optimize_animation_size": False,
            "export_anim_slide_to_zero": False,
            "export_skins": True,
            "export_all_influences": True,
            "export_armature_object_remove": False,
            "export_rest_position_armature": True,
            "will_save_settings": False,
        }
    return {
        "use_selection": True,
        "object_types": {"EMPTY", "MESH", "ARMATURE"},
        "global_scale": 1.0,
        "apply_unit_scale": True,
        "apply_scale_options": "FBX_SCALE_NONE",
        "axis_forward": "-Y",
        "axis_up": "Z",
        "use_mesh_modifiers": not has_morphs,
        "use_custom_props": True,
        "add_leaf_bones": False,
        "use_armature_deform_only": False,
        "bake_anim": include_animation,
        "bake_anim_use_all_bones": True,
        "bake_anim_use_nla_strips": False,
        "bake_anim_use_all_actions": False,
        "bake_anim_force_startend_keying": True,
        "bake_anim_step": 1.0,
        "bake_anim_simplify_factor": 0.0,
        "path_mode": "COPY",
        "embed_textures": True,
    }


def _portable_settings(settings):
    return {
        key: sorted(value) if isinstance(value, set) else value for key, value in settings.items()
    }


def _warnings(objects):
    warnings = []
    materials = {slot.material for obj in objects for slot in obj.material_slots if slot.material}
    for material in materials:
        if material.node_tree and any(
            node.type
            not in {
                "OUTPUT_MATERIAL",
                "BSDF_PRINCIPLED",
                "TEX_IMAGE",
                "NORMAL_MAP",
                "SEPARATE_COLOR",
                "UVMAP",
                "REROUTE",
            }
            for node in material.node_tree.nodes
        ):
            warnings.append(
                f"Material {material.name!r} has procedural/unsupported node constructs; bake and compare exported appearance"
            )
    return sorted(warnings)


def _remove_owned(path, identity, verify):
    """Best-effort cleanup only while file identity and intended bytes still match."""
    if identity is None:
        return
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (
            identity.st_dev,
            identity.st_ino,
        ):
            return
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return
            if not verify(stream):
                return
        after = path.lstat()
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            path.unlink()
    except (OSError, ValueError):
        # Ambiguous/replaced outputs remain for inspection; preserve the original error.
        pass


def _publish_new(path, incoming):
    identity = None
    try:
        with path.open("xb") as output:
            identity = os.fstat(output.fileno())
            shutil.copyfileobj(incoming, output)
        return identity
    except Exception:

        def intended_prefix(actual):
            incoming.seek(0)
            while chunk := actual.read(1024 * 1024):
                if chunk != incoming.read(len(chunk)):
                    return False
            return True

        _remove_owned(path, identity, intended_prefix)
        raise


def _remove_complete(path, identity, size, digest):
    _remove_owned(
        path,
        identity,
        lambda stream: (
            os.fstat(stream.fileno()).st_size == size
            and hashlib.file_digest(stream, "sha256").hexdigest() == digest
        ),
    )


def export_asset(params, context=None):
    """Export explicitly selected dependencies through an owned temporary scene.

    The sundown profile records the intended Unreal handoff; it does not apply a
    legacy Unity axis conversion, import native assets or assert game acceptance.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender access must run on the main thread")
    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before export")
    p, objects, path, receipt_path = _request(params, context)
    animation_plan = _animation_plan(objects, context, p)
    export_materials.validate_material_dependencies(objects)
    morph_meshes = [
        obj
        for obj in objects
        if obj.type == "MESH" and obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1
    ]
    if morph_meshes:
        if any(
            modifier.type != "ARMATURE"
            for obj in objects
            if obj.type == "MESH"
            for modifier in obj.modifiers
        ):
            raise ValueError(
                "Morph/shape handoff requires an Armature-only modifier scope; bake other meshes separately"
            )
        for obj in morph_meshes:
            keys = obj.data.shape_keys
            if not keys.use_relative or any(
                key.relative_key != keys.reference_key or key.mute or key.vertex_group
                for key in keys.key_blocks
                if key != keys.reference_key
            ):
                raise ValueError(
                    "Morph export supports unmuted unmasked Basis-relative shape keys only"
                )
            for modifier in obj.modifiers:
                if (
                    modifier.use_deform_preserve_volume
                    or modifier.use_bone_envelopes
                    or not modifier.use_vertex_groups
                    or modifier.vertex_group
                    or not modifier.show_viewport
                    or not modifier.show_render
                ):
                    raise ValueError(
                        "Morph export requires enabled linear vertex-group skinning without envelope/mask/DQ modes"
                    )
                if modifier.object and any(
                    bone.bbone_segments > 1 for bone in modifier.object.data.bones
                ):
                    raise ValueError(
                        "Morph export with Bendy-bone segments needs a separately verified deformation bake"
                    )
    source = _source_record(objects)
    fingerprint = _hash_json(source)
    settings = _settings(p["format"], p["include_animation"], bool(morph_meshes))
    scalar_plan = (
        export_materials.plan_scalar_maps(
            objects, p["max_material_memory_mb"], p["clamp_scalar_textures"]
        )
        if p["format"] == "FBX"
        else {"maps": []}
    )
    receipt = {
        "schema_version": "1.0",
        "dry_run": p["dry_run"],
        "format": p["format"],
        "profile": p["profile"],
        "target_engine": "Unreal" if p["profile"] == "sundown" else "unspecified",
        "output_path": str(path),
        "receipt_path": str(receipt_path),
        "blender_version": bpy.app.version_string,
        "source_scene": context.scene.name,
        "source_frame": context.scene.frame_current,
        "source_subframe": context.scene.frame_subframe,
        "fps": context.scene.render.fps / context.scene.render.fps_base,
        "frame_range": [context.scene.frame_start, context.scene.frame_end],
        "unit_system": context.scene.unit_settings.system,
        "unit_scale": context.scene.unit_settings.scale_length,
        "source": source,
        "source_fingerprint_before": fingerprint,
        "settings": _portable_settings(settings),
        "animation_sampling": animation_plan,
        "warnings": _warnings(objects),
        "scalar_texture_staging": scalar_plan,
        "morph_targets": {
            obj.name: [
                key.name
                for key in obj.data.shape_keys.key_blocks
                if key != obj.data.shape_keys.reference_key
            ]
            for obj in morph_meshes
        },
        "status": {
            "export_generated": False,
            "cold_reimport_verified": False,
            "native_imported": False,
            "world_placed": False,
            "visually_accepted": False,
        },
        "limitations": [
            "Object names are staged; framewright_source_name custom properties and the receipt preserve source identity",
            "Procedural materials require baking and rendered comparison",
            "Animated material/node/image dependencies are rejected; static exports freeze copied current object/shape state",
            "Sundown profile is a staging contract only; no native Unreal import or runtime acceptance",
            "Cold reimport, full surface/UV/material comparison and artistic review are independent gates",
        ],
    }
    if p["dry_run"]:
        return receipt
    published_output = published_receipt = None
    try:
        with tempfile.TemporaryDirectory(
            prefix=".framewright-export-", dir=p["directory"]
        ) as temporary:
            staged_path = Path(temporary) / path.name
            with _staging(objects, context, p["include_animation"], p["animation_substeps"]) as (
                scene,
                copies,
            ):
                receipt["staged_names"] = {
                    source.name: copy.name for source, copy in copies.items()
                }
                receipt["verification_reference"] = _reference(
                    scene, copies, p["include_animation"]
                )
                with (
                    export_materials.stage_scalar_maps(
                        list(copies.values()), scalar_plan, Path(temporary)
                    ),
                    bpy.context.temp_override(
                        scene=scene,
                        view_layer=scene.view_layers[0],
                        active_object=scene.view_layers[0].objects.active,
                        selected_objects=list(copies.values()),
                        selected_editable_objects=list(copies.values()),
                    ),
                ):
                    exporter = (
                        bpy.ops.export_scene.gltf
                        if p["format"] == "GLB"
                        else bpy.ops.export_scene.fbx
                    )
                    outcome = exporter(filepath=str(staged_path), check_existing=False, **settings)
                    if outcome != {"FINISHED"} or not staged_path.is_file():
                        raise RuntimeError("Exporter did not produce a completed file")
            after = _hash_json(_source_record(objects))
            receipt["source_fingerprint_after"] = after
            if after != fingerprint:
                raise RuntimeError("Source data changed during export; output was not published")
            with staged_path.open("rb") as stream:
                receipt["output_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            receipt["output_bytes"] = staged_path.stat().st_size
            # Exclusive creation plus identity/content checks preserve foreign
            # replacements if publication or the following receipt write fails.
            with staged_path.open("rb") as incoming:
                published_output = _publish_new(path, incoming)
            receipt["status"]["export_generated"] = True
            data = (json.dumps(receipt, indent=2, allow_nan=False) + "\n").encode("utf-8")
            published_receipt = _publish_new(receipt_path, io.BytesIO(data))
        return receipt
    except Exception:
        if published_receipt is not None:
            _remove_complete(
                receipt_path, published_receipt, len(data), hashlib.sha256(data).hexdigest()
            )
        if published_output is not None:
            _remove_complete(
                path, published_output, receipt["output_bytes"], receipt["output_sha256"]
            )
        raise
