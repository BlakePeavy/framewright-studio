"""Explicit binding, cloth setup and authored control-pose adapters."""

from __future__ import annotations

from uuid import uuid4

from .rigging import (
    checked_context,
    discard_derivative,
    finite,
    hidden_derivative,
    integer,
    parameters,
    scene_object,
)


def _names(values, label, maximum=64, allow_empty=False):
    if not isinstance(values, list) or not (0 if allow_empty else 1) <= len(values) <= maximum:
        raise ValueError(f"{label} must be a bounded list of names")
    if any(not isinstance(value, str) or not value or len(value) > 256 for value in values) or len(
        set(values)
    ) != len(values):
        raise ValueError(f"{label} must contain unique nonempty names")
    return values


def _bone(armature, name):
    if not isinstance(name, str) or name not in armature.pose.bones:
        raise ValueError("bone must name an existing authored bone on the armature")
    return armature.pose.bones[name]


def inspect_bindings(params: dict, context=None) -> dict:
    if not isinstance(params, dict) or set(params) != {"object_names"}:
        raise ValueError("Binding inspection requires object_names only")
    names = _names(params["object_names"], "object_names")
    context = checked_context(context)
    objects = []
    complete = True
    for name in names:
        obj = scene_object(context, name)
        rigs = {
            modifier.object
            for modifier in obj.modifiers
            if modifier.type == "ARMATURE" and modifier.object
        }
        deform_names = {bone.name for rig in rigs for bone in rig.data.bones if bone.use_deform}
        counts = {group.index: 0 for group in obj.vertex_groups}
        weight_complete = obj.type != "MESH" or len(obj.data.vertices) <= 200_000
        if obj.type == "MESH" and weight_complete:
            for vertex in obj.data.vertices:
                for group in vertex.groups:
                    if group.weight > 0:
                        counts[group.group] = counts.get(group.group, 0) + 1
        complete = complete and weight_complete
        keys = getattr(obj.data, "shape_keys", None) if obj.data else None
        objects.append(
            {
                "name": obj.name,
                "type": obj.type,
                "parent": obj.parent.name if obj.parent else None,
                "parent_type": obj.parent_type,
                "parent_bone": obj.parent_bone if obj.parent_type == "BONE" else None,
                "armatures": sorted(rig.name for rig in rigs),
                "vertex_groups": [
                    {
                        "name": group.name,
                        "locked": group.lock_weight,
                        "matches_deform_bone": group.name in deform_names,
                        "weighted_vertices": counts[group.index] if weight_complete else None,
                    }
                    for group in obj.vertex_groups
                ],
                "shape_keys": [
                    {"name": key.name, "value": key.value, "mute": key.mute}
                    for key in keys.key_blocks
                ]
                if keys
                else [],
                "modifiers": [modifier.type for modifier in obj.modifiers],
                "weight_coverage": "complete"
                if weight_complete
                else "skipped_over_200000_vertices",
            }
        )
    return {
        "schema_version": "1.0",
        "coverage": "complete" if complete else "partial",
        "objects": objects,
        "limits": [
            "Reports actual bindings only; does not infer anatomy or attachment suitability",
            "Physics modifiers do not establish simulation or engine portability",
        ],
    }


def attach_rigid(params: dict, context=None) -> dict:
    parameters(params, ("armature_name", "bone", "dry_run"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    if not isinstance(params.get("armature_name"), str):
        raise ValueError("armature_name must identify an armature")
    rig = scene_object(context, params["armature_name"], "ARMATURE")
    bone = _bone(rig, params.get("bone"))
    if (
        source.animation_data
        or source.constraints
        or any(modifier.type == "ARMATURE" for modifier in source.modifiers)
    ):
        raise ValueError(
            "Rigid attachment requires an unanimated mesh without constraints or skin modifiers"
        )
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "armature": rig.name,
        "bone": bone.name,
        "dry_run": params.get("dry_run", True),
        "preserves_world_placement": True,
    }
    if result["dry_run"]:
        return result
    world = source.matrix_world.copy()
    derivative = hidden_derivative(source, context, "Attachment")
    try:
        derivative.parent = rig
        derivative.parent_type = "BONE"
        derivative.parent_bone = bone.name
        context.view_layer.update()
        derivative.matrix_world = world
        result.update(derivative=derivative.name, hidden=True)
        return result
    except Exception:
        discard_derivative(derivative)
        raise


def create_cloth_proxy(params: dict, context=None) -> dict:
    parameters(
        params,
        (
            "pin_group",
            "dry_run",
            "frame_start",
            "frame_end",
            "quality",
            "collision_distance",
            "self_collision",
            "collider_names",
        ),
    )
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    group_name = params.get("pin_group")
    if not isinstance(group_name, str) or group_name not in source.vertex_groups:
        raise ValueError("pin_group must name an existing authored vertex group")
    group = source.vertex_groups[group_name]
    if len(source.data.vertices) > 200_000:
        raise ValueError("Cloth setup is limited to 200000 source vertices")
    pinned = sum(
        any(weight.group == group.index and weight.weight > 0 for weight in vertex.groups)
        for vertex in source.data.vertices
    )
    if not pinned:
        raise ValueError("pin_group must contain positive authored weights")
    if any(modifier.type in {"CLOTH", "SOFT_BODY"} for modifier in source.modifiers):
        raise ValueError(
            "Source already contains cloth/soft-body simulation; choose a clean authored source"
        )
    start = integer(params.get("frame_start", 1), 1, 1_000_000, "frame_start")
    end = integer(params.get("frame_end", 250), start, 1_000_000, "frame_end")
    quality = integer(params.get("quality", 5), 1, 20, "quality")
    distance = finite(params.get("collision_distance", 0.015), "collision_distance", 0.0001)
    if distance > 1:
        raise ValueError("collision_distance must not exceed one Blender unit")
    self_collision = params.get("self_collision", False)
    if type(self_collision) is not bool:
        raise ValueError("self_collision must be a boolean")
    collider_names = _names(params.get("collider_names", []), "collider_names", 8, allow_empty=True)
    if source.name in collider_names:
        raise ValueError("Cloth source cannot be its own collision object")
    colliders = [scene_object(context, name, "MESH") for name in collider_names]
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "pin_group": group_name,
        "pinned_vertices": pinned,
        "dry_run": params.get("dry_run", True),
        "frame_start": start,
        "frame_end": end,
        "simulation_evaluated": False,
        "collision_distance_blender_units": distance,
        "collision_scope": "selected_collider_derivatives_only",
        "limits": [
            "Creates settings and independent collider derivatives; no simulation bake",
            "Only selected collider derivatives participate; an empty selection excludes scene colliders",
            "Reveal proxy and collider derivatives together before simulation review",
            "No automatic physics export or engine collision binding",
        ],
    }
    if result["dry_run"]:
        return result
    import bpy

    created = []
    collision_collection = None
    try:
        proxy = hidden_derivative(source, context, "ClothProxy")
        created.append(proxy)
        cloth_id = str(uuid4())
        proxy["framewright_cloth_id"] = cloth_id
        proxy["framewright_cloth_role"] = "proxy"
        proxy["framewright_cloth_schema"] = "1.0"
        cloth = proxy.modifiers.new("Framewright Cloth", "CLOTH")
        cloth.settings.vertex_group_mass = group_name
        cloth.settings.quality = quality
        cloth.collision_settings.use_collision = True
        cloth.collision_settings.use_self_collision = self_collision
        cloth.collision_settings.distance_min = distance
        cloth.collision_settings.self_distance_min = distance
        collision_collection = bpy.data.collections.new(proxy.name + "_Colliders")
        collision_collection["framewright_owner"] = "secondary_motion"
        collision_collection["framewright_cloth_proxy"] = proxy.name
        collision_collection["framewright_cloth_id"] = cloth_id
        context.scene.collection.children.link(collision_collection)
        cloth.collision_settings.collection = collision_collection
        cloth.point_cache.frame_start = start
        cloth.point_cache.frame_end = end
        cloth.point_cache.use_disk_cache = False
        copies = []
        for source_collider in colliders:
            collider = hidden_derivative(source_collider, context, "ClothCollider")
            created.append(collider)
            collider["framewright_cloth_id"] = cloth_id
            collider["framewright_cloth_role"] = "collider"
            if not any(modifier.type == "COLLISION" for modifier in collider.modifiers):
                collider.modifiers.new("Framewright Collision", "COLLISION")
            collision_collection.objects.link(collider)
            copies.append(collider.name)
        result.update(
            derivative=proxy.name,
            collider_derivatives=copies,
            collision_collection=collision_collection.name,
            cloth_id=cloth_id,
            hidden=True,
        )
        return result
    except Exception:
        for obj in reversed(created):
            discard_derivative(obj)
        if collision_collection is not None:
            bpy.data.collections.remove(collision_collection)
        raise


def capture_pose(params: dict, context=None) -> dict:
    parameters(params, ("bones",))
    context = checked_context(context)
    rig = scene_object(context, params["object_name"], "ARMATURE")
    names = _names(params.get("bones"), "bones", 128)
    poses = {name: [list(row) for row in _bone(rig, name).matrix_basis] for name in names}
    return {
        "schema_version": "1.0",
        "source": rig.name,
        "pose": {"schema_version": "1.0", "bones": poses},
        "limits": [
            "Captures authored control basis transforms, not anatomical grip/blink/gaze correctness"
        ],
    }


def _remap_internal_targets(derivative, source):
    constraints = list(derivative.constraints)
    constraints.extend(
        constraint for bone in derivative.pose.bones for constraint in bone.constraints
    )
    for constraint in constraints:
        for field in ("target", "pole_target"):
            if hasattr(constraint, field) and getattr(constraint, field) == source:
                setattr(constraint, field, derivative)
        for target in getattr(constraint, "targets", ()):
            if getattr(target, "target", None) == source:
                target.target = derivative
    for block in (derivative, derivative.data):
        data = block.animation_data
        if data is None:
            continue
        data.action = None
        for track in list(data.nla_tracks):
            data.nla_tracks.remove(track)
        for curve in data.drivers:
            for variable in curve.driver.variables:
                for target in variable.targets:
                    if target.id == source:
                        target.id = derivative
                    elif target.id == source.data:
                        target.id = derivative.data


def _remap_bound_drivers(pairs):
    """Remap copied object/data/key driver IDs without touching shared actions."""
    mapping = {}
    blocks = []
    for source, derivative in pairs:
        mapping[source] = derivative
        mapping[source.data] = derivative.data
        blocks.extend((derivative, derivative.data))
        source_keys = getattr(source.data, "shape_keys", None)
        if source_keys is not None:
            mapping[source_keys] = derivative.data.shape_keys
            blocks.append(derivative.data.shape_keys)
    for block in blocks:
        data = block.animation_data
        if data is not None:
            for curve in data.drivers:
                for variable in curve.driver.variables:
                    for target in variable.targets:
                        if target.id in mapping:
                            target.id = mapping[target.id]


def apply_pose(params: dict, context=None) -> dict:
    parameters(params, ("pose", "bone_map", "dry_run", "bound_mesh_names"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "ARMATURE")
    pose = params.get("pose")
    if (
        not isinstance(pose, dict)
        or set(pose) != {"schema_version", "bones"}
        or pose["schema_version"] != "1.0"
        or not isinstance(pose["bones"], dict)
    ):
        raise ValueError("pose must be a version 1.0 captured control-pose object")
    mapping = params.get("bone_map")
    if (
        not isinstance(mapping, dict)
        or not 1 <= len(mapping) <= 128
        or any(
            not isinstance(a, str)
            or not isinstance(b, str)
            or a not in pose["bones"]
            or b not in source.pose.bones
            for a, b in mapping.items()
        )
        or len(set(mapping.values())) != len(mapping)
    ):
        raise ValueError("bone_map must map captured controls to unique existing target bones")
    from mathutils import Matrix

    matrices = {}
    for captured, target in mapping.items():
        rows = pose["bones"][captured]
        if (
            not isinstance(rows, list)
            or len(rows) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in rows)
        ):
            raise ValueError("Each captured control needs a 4x4 basis matrix")
        values = [[finite(value, "pose matrix coordinate") for value in row] for row in rows]
        if any(abs(value) > 1_000_000 for row in values for value in row) or values[3] != [
            0.0,
            0.0,
            0.0,
            1.0,
        ]:
            raise ValueError("Pose matrix must be bounded and affine")
        matrix = Matrix(values)
        rebuilt = Matrix.LocRotScale(*matrix.decompose())
        if max(abs(matrix[i][j] - rebuilt[i][j]) for i in range(4) for j in range(4)) > 1e-5:
            raise ValueError("Pose matrix shear cannot be represented by control channels")
        matrices[target] = matrix
    mesh_names = _names(
        params.get("bound_mesh_names", []), "bound_mesh_names", 32, allow_empty=True
    )
    meshes = [scene_object(context, name, "MESH") for name in mesh_names]
    if len({mesh.data for mesh in meshes}) != len(meshes):
        raise ValueError("Shared bound mesh data has ambiguous derivative driver ownership")
    if any(
        not any(
            modifier.type == "ARMATURE" and modifier.object == source for modifier in mesh.modifiers
        )
        for mesh in meshes
    ):
        raise ValueError("Every bound mesh must already reference the source rig")
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "control_count": len(matrices),
        "bone_map": mapping,
        "limits": [
            "User-authored controls only; anatomical correctness is not inferred",
            "Pose candidate removes copied action/NLA but retains and remaps existing rig drivers/constraints",
            "External constraints remain external dependencies",
        ],
    }
    if result["dry_run"]:
        return result
    created = []
    try:
        derivative = hidden_derivative(source, context, "Pose")
        created.append(derivative)
        _remap_internal_targets(derivative, source)
        for name, matrix in matrices.items():
            derivative.pose.bones[name].matrix_basis = matrix
        bound = []
        pairs = [(source, derivative)]
        for mesh in meshes:
            copy = hidden_derivative(mesh, context, "PoseSkin")
            created.append(copy)
            for modifier in copy.modifiers:
                if modifier.type == "ARMATURE" and modifier.object == source:
                    modifier.object = derivative
            if copy.parent == source:
                copy.parent = derivative
                # Assigning parent resets this inverse in Blender. Preserve the
                # authored bind transform instead of decomposing matrix_world.
                copy.matrix_parent_inverse = mesh.matrix_parent_inverse.copy()
            bound.append(copy.name)
            pairs.append((mesh, copy))
        _remap_bound_drivers(pairs)
        result.update(derivative=derivative.name, bound_derivatives=bound, hidden=True)
        return result
    except Exception:
        for obj in reversed(created):
            discard_derivative(obj)
        raise


def apply_shape_values(params: dict, context=None) -> dict:
    parameters(params, ("values", "protected_keys", "dry_run"))
    context = checked_context(context)
    source = scene_object(context, params["object_name"], "MESH")
    keys = source.data.shape_keys
    if keys is None or not keys.use_relative:
        raise ValueError("Object must already contain authored relative shape keys")
    protected = _names(params.get("protected_keys", []), "protected_keys", 128, allow_empty=True)
    if any(name not in keys.key_blocks for name in protected):
        raise ValueError("protected_keys must identify existing authored keys")
    values = params.get("values")
    if not isinstance(values, dict) or not 1 <= len(values) <= 128:
        raise ValueError("values must contain 1-128 authored shape-key values")
    for name, value in values.items():
        if (
            not isinstance(name, str)
            or name not in keys.key_blocks
            or name == keys.key_blocks[0].name
            or name in protected
        ):
            raise ValueError("Shape values cannot target missing, Basis or protected keys")
        value = finite(value, "shape value")
        key = keys.key_blocks[name]
        if not key.slider_min <= value <= key.slider_max:
            raise ValueError("Shape value exceeds its authored slider range")
    result = {
        "schema_version": "1.0",
        "source": source.name,
        "dry_run": params.get("dry_run", True),
        "values": values,
        "protected_keys": protected,
        "limits": [
            "Existing authored expressions only; no generated blink/gaze anatomy",
            "Shape-key animation is detached on the static derivative only",
        ],
    }
    if result["dry_run"]:
        return result
    derivative = hidden_derivative(source, context, "Expression")
    try:
        if derivative.data.shape_keys is keys:
            raise RuntimeError("Copied mesh unexpectedly shares shape-key data")
        derivative.data.shape_keys.animation_data_clear()
        for name, value in values.items():
            derivative.data.shape_keys.key_blocks[name].value = value
        result.update(derivative=derivative.name, hidden=True)
        return result
    except Exception:
        discard_derivative(derivative)
        raise
