"""Measured B-Bone endpoint skin baking; sampled transport, not an animator rig."""

from __future__ import annotations

import math
from array import array
from contextlib import contextmanager

from .pose_correctives import _curves, _native_dependencies
from .rigging import checked_context, finite, integer, parameters, scene_object
from .shape_baking import _constraint_targets, _constraints, _remap_drivers
from .skin_contacts import _numeric_path

_BUDGETS = {
    "max_key_times": (257, 1, 1025),
    "max_samples": (1025, 1, 4097),
    "max_vertex_samples": (10_000_000, 1, 100_000_000),
    "max_joints": (512, 1, 1024),
    "max_influences": (8, 1, 32),
    "max_refinement_depth": (4, 0, 6),
}
_CACHE_BYTES = 128 * 1024 * 1024
_JOINT_SAMPLES = 262_144


def _options(params):
    required = ("object_name", "armature_name", "frame_start", "frame_end", "max_surface_error_m")
    parameters(params, (*_BUDGETS, "dry_run"), required)
    if not isinstance(params["armature_name"], str) or not 1 <= len(params["armature_name"]) <= 256:
        raise ValueError("armature_name must be an exact nonempty name")
    options = {
        name: integer(params.get(name, default), low, high, name)
        for name, (default, low, high) in _BUDGETS.items()
    }
    start = integer(params["frame_start"], -1_000_000, 1_000_000, "frame_start")
    end = integer(params["frame_end"], -1_000_000, 1_000_000, "frame_end")
    tolerance = finite(params["max_surface_error_m"], "max_surface_error_m", 1e-7)
    if tolerance > 1:
        raise ValueError("max_surface_error_m must be at most one meter")
    if end < start or end - start + 1 > min(options["max_key_times"], options["max_samples"]):
        raise ValueError("Full integer interval must fit the key/sample budgets")
    return {**options, "start": start, "end": end, "tolerance": tolerance}


def _matrix_finite(matrix):
    return (
        all(math.isfinite(v) for row in matrix for v in row) and abs(matrix.determinant()) > 1e-12
    )


def _validate(context, params, options):
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
        raise ValueError("B-Bone sampling refuses registered frame/depsgraph handlers")
    if context.window is None:
        raise ValueError("B-Bone authoring requires an owned window context")
    skin = scene_object(context, params["object_name"], "MESH")
    rig = scene_object(context, params["armature_name"], "ARMATURE")
    if any(o.name not in context.view_layer.objects for o in (skin, rig)):
        raise ValueError("Explicit objects must belong to the active view layer")
    if any(d.library or d.override_library for d in (skin, skin.data, rig, rig.data)):
        raise ValueError("B-Bone baking requires local editable data")
    if not 1 <= len(skin.data.vertices) <= 200_000 or len(rig.data.bones) > 2048:
        raise ValueError("Mesh/rig exceeds the fixed vertex/bone limit")
    if any(not math.isfinite(v) for p in skin.data.vertices for v in p.co):
        raise ValueError("Mesh coordinates must be finite")
    if any(
        not math.isfinite(g.weight) or not 0 <= g.weight <= 1
        for v in skin.data.vertices
        for g in v.groups
    ):
        raise ValueError("Vertex weights must be finite values in [0,1]")
    if (
        2 * len(skin.data.vertices) * (options["end"] - options["start"] + 1)
        > options["max_vertex_samples"]
    ):
        raise ValueError("Even integer source/target samples exceed the vertex-sample budget")
    keys = skin.data.shape_keys
    if keys and (len(keys.key_blocks) > 1 or keys.animation_data):
        raise ValueError(
            "Any non-Basis shape key or shape animation requires separate mapping verification"
        )
    if (
        skin.animation_data
        or skin.data.animation_data
        or skin.constraints
        or rig.constraints
        or rig.modifiers
        or rig.parent
        or rig.data.animation_data
    ):
        raise ValueError(
            "Object/data animation, object constraints, rig parenting/modifiers are unsupported"
        )
    if skin.parent and (skin.parent != rig or skin.parent_type != "OBJECT"):
        raise ValueError("Skin parenting must use the explicit armature in Object mode")
    if (
        len(skin.modifiers) != 1
        or skin.modifiers[0].type != "ARMATURE"
        or skin.modifiers[0].object != rig
    ):
        raise ValueError(
            "Skin requires exactly one explicit Armature modifier and no other modifiers"
        )
    mod = skin.modifiers[0]
    if (
        mod.use_deform_preserve_volume
        or mod.use_bone_envelopes
        or not mod.use_vertex_groups
        or mod.vertex_group
        or not mod.show_viewport
        or not mod.show_render
        or rig.data.pose_position != "POSE"
    ):
        raise ValueError(
            "Only enabled linear group skinning is supported; DQ/envelope/mask modes are refused"
        )
    if not all(_matrix_finite(o.matrix_world) for o in (skin, rig)):
        raise ValueError("Object transforms must be finite and invertible")
    scale = finite(context.scene.unit_settings.scale_length, "scene unit scale", 1e-12)
    animation = rig.animation_data
    if animation:
        if animation.nla_tracks:
            raise ValueError("Rig NLA must first be prepared as an explicit active action")
        if animation.action:
            action = animation.action
            if action.library or action.override_library or animation.action_slot is None:
                raise ValueError("Rig action requires a local explicit slot")
            curves = [
                curve
                for layer in action.layers
                for strip in layer.strips
                for bag in strip.channelbags
                if bag.slot_handle == animation.action_slot.handle
                for curve in bag.fcurves
            ]
            if len(curves) > 8192 or any(
                not c.data_path.startswith(("pose.bones[", '["')) for c in curves
            ):
                raise ValueError(
                    "Only pose/control-property action curves are supported, at most 8192"
                )
            for curve in curves:
                _numeric_path(rig, curve.data_path)
        if any(not c.data_path.startswith(("pose.bones[", '["')) for c in animation.drivers):
            raise ValueError("Object-transform rig drivers are unsupported")
    _native_dependencies(animation, {rig, rig.data}, rig, native_rig_curves=True)
    _driver_validity(rig)
    for constraint in _constraints(rig):
        if any(
            getattr(owner, name) not in (None, rig)
            for owner, name in _constraint_targets(constraint)
        ):
            raise ValueError("Rig constraints must use only internal armature dependencies")
    deform = {b.name: b for b in rig.data.bones if b.use_deform}
    if not any(b.bbone_segments > 1 for b in deform.values()):
        raise ValueError("An explicit segmented deform B-Bone is required")
    count = sum(b.bbone_segments + 1 if b.bbone_segments > 1 else 1 for b in deform.values())
    if count > options["max_joints"]:
        raise ValueError("Endpoint joint count exceeds max_joints budget")
    if any(b.length < 1e-8 or not _matrix_finite(b.matrix_local) for b in deform.values()):
        raise ValueError("Deform bones require finite nonzero rest lengths")
    return skin, rig, scale, deform


def _driver_validity(rig):
    for owner in (rig, rig.data):
        animation = getattr(owner, "animation_data", None)
        if not animation:
            continue
        for curve in animation.drivers:
            _numeric_path(owner, curve.data_path)
            if not curve.is_valid or not curve.driver.is_valid:
                raise ValueError("Invalid native rig driver cannot supply deformation evidence")
            for variable in curve.driver.variables:
                if variable.type == "SINGLE_PROP":
                    for target in variable.targets:
                        try:
                            _numeric_path(target.id, target.data_path)
                        except (ValueError, KeyError, AttributeError, TypeError) as exc:
                            raise ValueError(
                                "Native rig driver property dependency is missing or invalid"
                            ) from exc


@contextmanager
def _workspace(context, skin, rig):
    import bpy

    original_scene, original_layer = context.window.scene, context.window.view_layer
    active = context.view_layer.objects.active
    selection = [
        (o, o.select_get(view_layer=context.view_layer)) for o in context.view_layer.objects
    ]
    scene = bpy.data.scenes.new("FW_BBoneSampling")
    state = {"objects": [], "data": [], "target": None, "keep": set(), "scene": scene}
    try:
        scene.render.fps, scene.render.fps_base = (
            context.scene.render.fps,
            context.scene.render.fps_base,
        )
        scene.unit_settings.scale_length = context.scene.unit_settings.scale_length
        copies = {}
        for source in (rig, skin):
            copy = source.copy()
            state["objects"].append(copy)
            copy.data = source.data.copy()
            state["data"].append(
                (bpy.data.armatures if source.type == "ARMATURE" else bpy.data.meshes, copy.data)
            )
            if copy.type == "ARMATURE":
                for bone in copy.pose.bones:
                    bone.custom_shape, bone.custom_shape_transform = None, None
            else:
                copy.data.materials.clear()
            scene.collection.objects.link(copy)
            copy.hide_viewport = copy.hide_render = False
            copy.hide_set(False, view_layer=scene.view_layers[0])
            copies[source] = copy
        copied_rig, copied_skin = copies[rig], copies[skin]
        copied_skin.parent = copied_rig if skin.parent else None
        copied_skin.matrix_parent_inverse = skin.matrix_parent_inverse.copy()
        copied_skin.modifiers[0].object = copied_rig
        remap = {rig: copied_rig, rig.data: copied_rig.data}
        _remap_drivers(copied_rig, remap)
        for constraint in _constraints(copied_rig):
            for owner, name in _constraint_targets(constraint):
                if getattr(owner, name) == rig:
                    setattr(owner, name, copied_rig)
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            yield state, copied_rig, copied_skin
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if context.window.scene != original_scene:
            context.window.scene = original_scene
        if context.window.view_layer != original_layer:
            context.window.view_layer = original_layer
        for obj, selected in selection:
            obj.select_set(selected, view_layer=original_layer)
        original_layer.objects.active = active
        target = state["target"]
        action = target.animation_data.action if target and target.animation_data else None
        for obj in state["objects"]:
            if obj not in state["keep"]:
                bpy.data.objects.remove(obj, do_unlink=True)
        keep_data = {obj.data for obj in state["keep"]}
        for store, data in state["data"]:
            if data not in keep_data:
                store.remove(data, do_unlink=True)
        if action and not action.users:
            bpy.data.actions.remove(action)
        bpy.data.scenes.remove(scene, do_unlink=True)


def _time(scene, value):
    scene.frame_set(math.floor(value), subframe=value % 1)
    scene.view_layers[0].update()


@contextmanager
def _edit_armature(target):
    import bpy

    with bpy.context.temp_override(
        object=target,
        active_object=target,
        selected_objects=[target],
        selected_editable_objects=[target],
    ):
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            if not target.data.is_editmode:
                raise RuntimeError("Owned endpoint armature did not enter Edit Mode")
            yield
        finally:
            if target.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")


def _target(state, rig, skin, original, deform, options):
    import bpy
    from mathutils import Matrix, Vector

    scene = state["scene"]
    _time(scene, options["start"])
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = bpy.data.armatures.new(original.name + "_FW_EndpointRigData")
    state["data"].append((bpy.data.armatures, data))
    target = bpy.data.objects.new(original.name + "_FW_EndpointRig", data)
    state["objects"].append(target)
    state["target"] = target
    scene.collection.objects.link(target)
    target.matrix_world = rig.matrix_world.copy()
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    mapping, rest = {}, {}
    with _edit_armature(target):
        for ordinal, name in enumerate(deform):
            pose = evaluated.pose.bones[name]
            count = pose.bone.bbone_segments + 1 if pose.bone.bbone_segments > 1 else 1
            mapping[name], rest[name] = [], []
            for index in range(count):
                segment = (
                    pose.bbone_segment_matrix(index, rest=True).copy()
                    if count > 1
                    else Matrix.Identity(4)
                )
                rest[name].append(segment)
                matrix = pose.bone.matrix_local @ segment
                location, rotation, _ = matrix.decompose()
                bone = data.edit_bones.new(f"FWB_{ordinal:04d}_{index:02d}")
                bone.head, bone.tail = (0, 0, 0), (0, 0.05, 0)
                bone.matrix = Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
                mapping[name].append(bone.name)
    for pose in target.pose.bones:
        pose.rotation_mode = "QUATERNION"
    candidate = skin.copy()
    state["objects"].append(candidate)
    candidate.data = skin.data.copy()
    state["data"].append((bpy.data.meshes, candidate.data))
    candidate.name = original.name + "_FW_EndpointSkin"
    scene.collection.objects.link(candidate)
    candidate.parent = target
    candidate.matrix_parent_inverse = (
        skin.matrix_parent_inverse.copy() if skin.parent else target.matrix_world.inverted()
    )
    candidate.modifiers[0].object = target
    for name in deform:
        if name in candidate.vertex_groups:
            candidate.vertex_groups.remove(candidate.vertex_groups[name])
    for names in mapping.values():
        for name in names:
            if name in candidate.vertex_groups:
                raise ValueError("Generated endpoint name collides with a protected vertex group")
            candidate.vertex_groups.new(name=name)
    to_rig = rig.matrix_world.inverted() @ skin.matrix_world
    maximum = 0
    source_totals = []
    for vertex in skin.data.vertices:
        original_weights = [
            (skin.vertex_groups[g.group].name, g.weight)
            for g in vertex.groups
            if skin.vertex_groups[g.group].name in deform and g.weight > 0
        ]
        total = sum(weight for _, weight in original_weights)
        if not math.isfinite(total):
            raise ValueError("Deform weights must be finite")
        source_totals.append(total)
        row = []
        for name, weight in original_weights:
            names = mapping[name]
            if len(names) == 1:
                row.append((names[0], weight / total))
            else:
                index, blend = evaluated.pose.bones[name].bbone_segment_index(to_rig @ vertex.co)
                row.extend(
                    (
                        (names[index], weight * (1 - blend) / total),
                        (names[index + 1], weight * blend / total),
                    )
                )
        row = [(name, weight) for name, weight in row if weight > 0]
        maximum = max(maximum, len(row))
        if maximum > options["max_influences"]:
            raise ValueError(
                "Endpoint weights exceed max_influences budget; no influence pruning is performed"
            )
        for name, weight in row:
            candidate.vertex_groups[name].add([vertex.index], weight, "REPLACE")
    return (
        target,
        candidate,
        mapping,
        rest,
        {
            "maximum_influences": maximum,
            "source_deform_weight_total_range": [min(source_totals), max(source_totals)],
            "weight_semantics": "Derivative deform weights normalize original positive deform totals, matching unmasked Blender linear skinning; zero-total vertices stay unweighted; nondeform groups remain exact; no pruning",
        },
    )


def _pose_matrices(rig, target, mapping, rest):
    import bpy
    from mathutils import Matrix

    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    _driver_validity(rig)
    _driver_validity(evaluated)
    if any(not constraint.is_valid for constraint in _constraints(evaluated)):
        raise ValueError("Invalid evaluated rig constraint cannot supply deformation evidence")
    matrices = {}
    maximum = 0.0
    for name, names in mapping.items():
        pose = evaluated.pose.bones[name]
        for index, output in enumerate(names):
            segment_rest = (
                pose.bbone_segment_matrix(index, rest=True)
                if len(names) > 1
                else Matrix.Identity(4)
            )
            if (
                max(
                    abs(a - b)
                    for row, other in zip(segment_rest, rest[name][index], strict=True)
                    for a, b in zip(row, other, strict=True)
                )
                > 1e-6
            ):
                raise ValueError("Animated B-Bone rest mapping is unsupported")
            segment_pose = (
                pose.bbone_segment_matrix(index, rest=False)
                if len(names) > 1
                else Matrix.Identity(4)
            )
            desired = (
                pose.matrix
                @ segment_pose
                @ segment_rest.inverted()
                @ pose.bone.matrix_local.inverted()
                @ target.data.bones[output].matrix_local
            )
            if not _matrix_finite(desired):
                raise ValueError("Endpoint pose is degenerate or nonfinite")
            location, rotation, scale = desired.decompose()
            rebuilt = Matrix.LocRotScale(location, rotation, scale)
            residual = max(
                abs(a - b)
                for row, other in zip(desired, rebuilt, strict=True)
                for a, b in zip(row, other, strict=True)
            )
            if residual > 1e-5:
                raise ValueError("Endpoint pose shear exceeds the supported TRS numerical limit")
            maximum = max(maximum, residual)
            matrices[output] = desired
    return matrices, maximum


def _write_action(state, rig, target, mapping, rest, times):
    import bpy

    samples = len(target.data.bones) * len(times)
    if state.get("joint_samples", 0) + samples > _JOINT_SAMPLES:
        raise ValueError("Endpoint key authoring exceeds the fixed joint-sample work limit")
    state["joint_samples"] = state.get("joint_samples", 0) + samples
    if target.animation_data:
        old = target.animation_data.action
        target.animation_data_clear()
        if old and not old.users:
            bpy.data.actions.remove(old)
    quaternions = {}
    for time in times:
        _time(state["scene"], time)
        matrices, _ = _pose_matrices(rig, target, mapping, rest)
        for name, matrix in matrices.items():
            pose = target.pose.bones[name]
            pose.matrix = matrix
            previous = quaternions.get(name)
            if previous is not None and pose.rotation_quaternion.dot(previous) < 0:
                pose.rotation_quaternion.negate()
            quaternions[name] = pose.rotation_quaternion.copy()
            for path in ("location", "rotation_quaternion", "scale"):
                pose.keyframe_insert(path, frame=time)
    action = target.animation_data.action
    action.name = target.name + "_Action"
    for curve in _curves(action):
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"


def _points(obj, work, options):
    import bpy

    count = len(obj.data.vertices)
    if work["vertices"] + count > options["max_vertex_samples"]:
        raise ValueError("Evaluated vertex-sample work exceeds max_vertex_samples budget")
    work["vertices"] += count
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != count:
            raise ValueError("Evaluated topology changed during skin sampling")
        values = array("f")
        for vertex in mesh.vertices:
            values.extend(evaluated.matrix_world @ vertex.co)
        if any(not math.isfinite(v) for v in values):
            raise ValueError("Evaluated surface contains nonfinite coordinates")
        return values
    finally:
        evaluated.to_mesh_clear()


def _adaptive(state, rig, skin, target, candidate, mapping, rest, options, unit_scale):
    times = list(range(options["start"], options["end"] + 1))
    cache, work = {}, {"vertices": 0}
    rounds = 0
    max_trs = 0.0
    while True:
        if len(times) > options["max_key_times"]:
            raise ValueError("Adaptive key-time budget exhausted before tolerance passed")
        _write_action(state, rig, target, mapping, rest, times)
        rounds += 1
        intervals = list(zip(times, times[1:], strict=False))
        checks = sorted(
            {float(t) for t in times}
            | {
                start + (end - start) * fraction
                for start, end in intervals
                for fraction in (0.25, 0.5, 0.75)
            }
        )
        errors = {}
        worst_vertex = {}
        for time in checks:
            _time(state["scene"], time)
            if time not in cache:
                if len(cache) >= options["max_samples"]:
                    raise ValueError(
                        "Adaptive source-sample budget exhausted before tolerance passed"
                    )
                if (len(cache) + 1) * len(skin.data.vertices) * 12 > _CACHE_BYTES:
                    raise ValueError("Source surface cache exceeds the fixed 128 MiB limit")
                _, residual = _pose_matrices(rig, target, mapping, rest)
                max_trs = max(max_trs, residual)
                cache[time] = _points(skin, work, options)
            actual = _points(candidate, work, options)
            expected = cache[time]
            distances = [
                math.sqrt(sum((expected[i + axis] - actual[i + axis]) ** 2 for axis in (0, 1, 2)))
                * unit_scale
                for i in range(0, len(actual), 3)
            ]
            errors[time] = max(distances)
            worst_vertex[time] = distances.index(errors[time])
        if any(errors[t] > options["tolerance"] for t in times):
            raise ValueError(
                "Exact endpoint key poses exceed the requested surface tolerance; refinement cannot repair the conversion"
            )
        splits = []
        for start, end in intervals:
            if (
                max(errors[start + (end - start) * f] for f in (0.25, 0.5, 0.75))
                > options["tolerance"]
            ):
                if end - start <= 2 ** -options["max_refinement_depth"]:
                    raise ValueError(
                        "Refinement depth limit exhausted before surface tolerance passed"
                    )
                splits.append((start + end) / 2)
        if not splits:
            worst = max(errors, key=errors.get)
            return {
                "key_times": times,
                "validation_times": checks,
                "maximum_surface_error_m": errors[worst],
                "worst_time": worst,
                "worst_vertex": worst_vertex[worst],
                "refinement_rounds": rounds,
                "source_sample_count": len(cache),
                "vertex_samples": work["vertices"],
                "cached_coordinate_bytes": sum(
                    len(values) * values.itemsize for values in cache.values()
                ),
                "maximum_trs_residual": max_trs,
                "joint_pose_samples": state["joint_samples"],
                "joint_pose_sample_limit": _JOINT_SAMPLES,
                "recommended_export_animation_substeps": round(
                    1 / min((end - start for start, end in intervals), default=1)
                ),
            }
        times = sorted(set(times + splits))


def bake_bbone_skin(params: dict, context=None) -> dict:
    """Preview or create a hidden endpoint rig/skin after bounded sampled surface validation."""
    context = checked_context(context)
    options = _options(params)
    skin, rig, unit_scale, deform = _validate(context, params, options)
    original_scene = context.scene
    with _workspace(context, skin, rig) as (state, copied_rig, copied_skin):
        target, candidate, mapping, rest, weights = _target(
            state, copied_rig, copied_skin, skin, deform, options
        )
        evidence = _adaptive(
            state, copied_rig, copied_skin, target, candidate, mapping, rest, options, unit_scale
        )
        result = {
            "schema_version": "1.0",
            "source": skin.name,
            "armature": rig.name,
            "dry_run": params.get("dry_run", True),
            "source_preserved": True,
            "art_accepted": False,
            "frame_start": options["start"],
            "frame_end": options["end"],
            "requested_surface_error_m": options["tolerance"],
            "unit_scale_m": unit_scale,
            "joint_count": len(target.data.bones),
            "endpoint_mapping": mapping,
            "budgets": {name: options[name] for name in _BUDGETS},
            **weights,
            **evidence,
            "limits": [
                "Sampled endpoint/quarter/midpoint checks do not bound arbitrary between-sample extrema",
                "Export skeleton is independent of the original animator/control hierarchy",
                "No DQ, non-Basis morph, shear, topology-modifier or native-engine parity claim",
                "Source-to-bake surface evidence is separate from export/cold-import geometry validation",
            ],
        }
        if not result["dry_run"]:
            for material in skin.data.materials:
                candidate.data.materials.append(material)
            # Clearing sampling materials resets face indices and object slot links.
            # Restore both from the untouched source only after geometry validation.
            for polygon, source_polygon in zip(
                candidate.data.polygons, skin.data.polygons, strict=True
            ):
                polygon.material_index = source_polygon.material_index
            for slot, source_slot in zip(
                candidate.material_slots, skin.material_slots, strict=True
            ):
                slot.link = source_slot.link
                if source_slot.link == "OBJECT":
                    slot.material = source_slot.material
            for obj in (target, candidate):
                obj.hide_viewport = obj.hide_render = True
                original_scene.collection.objects.link(obj)
            state["keep"].update((target, candidate))
            result.update(
                derivative=candidate.name,
                armature_derivative=target.name,
                action=target.animation_data.action.name,
                hidden=True,
            )
        return result
