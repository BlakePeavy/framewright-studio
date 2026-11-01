"""Budgeted embedded cloth bakes on independent objects in owned scenes."""

from __future__ import annotations

import math
from uuid import UUID, uuid4

from .rigging import checked_context, integer, scene_object

MAX_WORK_UNITS = 50_000_000
CACHE_BYTES_PER_VERTEX_FRAME = 128
WORKING_BYTES_PER_GEOMETRY_ELEMENT = 4096


def _parameters(params):
    required = {"object_name", "modifier_name"}
    allowed = required | {"dry_run", "max_frames", "max_vertices", "max_memory_mb"}
    if not isinstance(params, dict) or not required <= params.keys() or params.keys() - allowed:
        raise ValueError(
            "Cloth bake requires object_name and modifier_name; unknown parameters rejected"
        )
    for name in required:
        value = params[name]
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not value.isprintable():
            raise ValueError(f"{name} must be an exact printable name up to 1024 characters")
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be a boolean")
    return {
        "max_frames": integer(params.get("max_frames", 250), 1, 512, "max_frames"),
        "max_vertices": integer(params.get("max_vertices", 20000), 1, 50000, "max_vertices"),
        "max_memory_mb": integer(params.get("max_memory_mb", 512), 1, 4096, "max_memory_mb"),
    }


def _owned_uuid(obj):
    identity = obj.get("framewright_cloth_id")
    try:
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError(
            "Missing or invalid Framewright cloth ownership; recreate pre-metadata proxies"
        ) from None
    return identity


def _static_mesh(obj, role):
    if (
        obj.type != "MESH"
        or obj.library
        or obj.override_library
        or obj.data.library
        or obj.data.override_library
    ):
        raise ValueError(f"{role} must be a local mesh without library overrides")
    if obj.parent is not None:
        raise ValueError(f"{role} parent dependencies are unsupported for isolated cloth baking")
    if obj.animation_data or obj.data.animation_data or obj.data.shape_keys:
        raise ValueError(f"{role} animated or shape-key dependencies are unsupported")
    if obj.constraints or obj.particle_systems or (obj.field and obj.field.type != "NONE"):
        raise ValueError(f"{role} constraints, particles or force fields are unsupported")
    if (
        not all(math.isfinite(value) for row in obj.matrix_basis for value in row)
        or abs(obj.matrix_basis.determinant()) < 1e-12
    ):
        raise ValueError(f"{role} transform must be finite and nonsingular")
    for slot in obj.material_slots:
        material = slot.material
        if material is None:
            continue
        tree = material.node_tree
        if material.animation_data or (tree and tree.animation_data):
            raise ValueError(f"{role} animated material dependencies are unsupported")
        if tree:
            for node in tree.nodes:
                if node.type == "GROUP" or getattr(node, "object", None) is not None:
                    raise ValueError(
                        f"{role} material groups or object dependencies are unsupported"
                    )
                image = getattr(node, "image", None)
                if image and (
                    getattr(image, "animation_data", None)
                    or image.source not in {"FILE", "GENERATED"}
                ):
                    raise ValueError(f"{role} animated image dependencies are unsupported")


def _scalar_settings(owner):
    values = {}
    for prop in owner.bl_rna.properties:
        if prop.is_readonly or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue
        value = getattr(owner, prop.identifier)
        if getattr(prop, "is_array", False):
            value = tuple(value)
        numbers = value if isinstance(value, tuple) else (value,)
        if any(isinstance(item, float) and not math.isfinite(item) for item in numbers):
            raise ValueError("Cloth settings must contain finite values")
        values[prop.identifier] = value
    return values


def _apply_settings(owner, values):
    for name, value in values.items():
        setattr(owner, name, value)


def _preflight(params, context, limits):
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
            "Custom frame/depsgraph handlers are unsupported; use an owned clean background job"
        )
    proxy = scene_object(context, params["object_name"], "MESH")
    identity = _owned_uuid(proxy)
    if (
        proxy.get("framewright_cloth_role") not in {"proxy", "baked_proxy"}
        or proxy.get("framewright_cloth_schema") != "1.0"
    ):
        raise ValueError("Unsupported Framewright cloth ownership metadata")
    _static_mesh(proxy, "Cloth proxy")
    modifiers = [
        modifier for modifier in proxy.modifiers if modifier.name == params["modifier_name"]
    ]
    if len(modifiers) != 1 or modifiers[0].type != "CLOTH" or len(proxy.modifiers) != 1:
        raise ValueError("Select the one cloth modifier; other proxy modifiers are unsupported")
    cloth = modifiers[0]
    cache = cloth.point_cache
    if not cloth.show_viewport or not cloth.show_render:
        raise ValueError("Selected cloth modifier must be enabled for viewport and render")
    if cache.use_disk_cache or cache.use_external:
        raise ValueError("Only embedded caches are supported; disk/external caches are refused")
    if len(cache.point_caches) != 1:
        raise ValueError("Exactly one selected cloth cache is supported")
    if cache.is_baked:
        raise ValueError("Selected cloth cache is already baked; existing bakes are never replaced")
    if cloth.settings.rest_shape_key or cloth.settings.effector_weights.collection:
        raise ValueError("External rest-shape or effector collection dependencies are unsupported")
    group_name = cloth.settings.vertex_group_mass
    if group_name not in proxy.vertex_groups:
        raise ValueError("Owned cloth proxy must retain its authored pin group")
    group = proxy.vertex_groups[group_name]
    if not any(
        any(weight.group == group.index and weight.weight > 0 for weight in vertex.groups)
        for vertex in proxy.data.vertices
    ):
        raise ValueError("Owned cloth proxy must retain positive authored pin weights")
    collection = cloth.collision_settings.collection
    if (
        collection is None
        or collection.library
        or collection.override_library
        or collection.get("framewright_owner") != "secondary_motion"
        or collection.get("framewright_cloth_id") != identity
    ):
        raise ValueError("Missing or foreign collider collection ownership metadata")
    colliders = sorted(collection.all_objects, key=lambda obj: obj.name)
    if len(colliders) > 8 or collection.children:
        raise ValueError("Owned collider collection supports at most eight direct collider copies")
    for collider in colliders:
        if (
            collider.get("framewright_cloth_id") != identity
            or collider.get("framewright_cloth_role") != "collider"
        ):
            raise ValueError("Missing or foreign collider ownership metadata")
        _static_mesh(collider, "Collider")
        if len(collider.modifiers) != 1 or collider.modifiers[0].type != "COLLISION":
            raise ValueError(
                "Collider requires exactly one collision modifier; other dependencies are unsupported"
            )
        if not collider.collision or not collider.collision.use:
            raise ValueError("Selected collider collision settings must be enabled")
    start = integer(cache.frame_start, 1, 1_000_000, "cache frame_start")
    end = integer(cache.frame_end, start, 1_000_000, "cache frame_end")
    frame_count = end - start + 1
    objects = [proxy, *colliders]
    vertices = sum(len(obj.data.vertices) for obj in objects)
    if frame_count > limits["max_frames"]:
        raise ValueError("Cloth frame budget exceeded; no truncation or bake performed")
    if vertices > limits["max_vertices"] or not proxy.data.vertices or not proxy.data.polygons:
        raise ValueError("Cloth/copied-collider geometry budget exceeded or cloth surface is empty")
    if sum(len(obj.data.loops) for obj in objects) > limits["max_vertices"] * 12:
        raise ValueError("Cloth/copied-collider topology budget exceeded")
    triangles = sum(max(len(poly.vertices) - 2, 0) for obj in objects for poly in obj.data.polygons)
    if triangles > limits["max_vertices"] * 4:
        raise ValueError("Cloth/copied-collider triangle budget exceeded")
    if not all(
        math.isfinite(value)
        for obj in objects
        for vertex in obj.data.vertices
        for value in vertex.co
    ):
        raise ValueError("Cloth and collider coordinates must be finite")
    quality = integer(cloth.settings.quality, 1, 20, "cloth quality")
    collision_quality = integer(
        cloth.collision_settings.collision_quality, 1, 20, "collision quality"
    )
    collider_triangles = sum(
        max(len(poly.vertices) - 2, 0) for obj in colliders for poly in obj.data.polygons
    )
    work = frame_count * (
        len(proxy.data.vertices) * quality + collider_triangles * collision_quality
    )
    memory = (
        len(proxy.data.vertices) * frame_count * CACHE_BYTES_PER_VERTEX_FRAME
        + (vertices + triangles) * WORKING_BYTES_PER_GEOMETRY_ELEMENT
    )
    if memory > limits["max_memory_mb"] * 1024 * 1024:
        raise ValueError("Estimated cloth memory budget exceeded")
    if work > MAX_WORK_UNITS:
        raise ValueError("Estimated cloth simulation work budget exceeded")
    scene = context.scene
    if (
        not all(
            math.isfinite(value)
            for value in (*scene.gravity, scene.unit_settings.scale_length, scene.render.fps_base)
        )
        or scene.unit_settings.scale_length <= 0
        or scene.render.fps_base <= 0
    ):
        raise ValueError("Source scene gravity, units and FPS must be finite and valid")
    settings = (
        _scalar_settings(cloth.settings),
        _scalar_settings(cloth.collision_settings),
        _scalar_settings(cloth.settings.effector_weights),
    )
    report = {
        "schema_version": "1.0",
        "dry_run": params.get("dry_run", True),
        "source": proxy.name,
        "source_cloth_id": identity,
        "source_modifier": cloth.name,
        "frame_start": start,
        "frame_end": end,
        "frame_count": frame_count,
        "cloth_vertices": len(proxy.data.vertices),
        "copied_vertices": vertices,
        "copied_triangles": triangles,
        "estimated_memory_bytes": memory,
        "estimated_work_units": work,
        "budgets": limits,
        "memory_estimate_model": {
            "cache_bytes_per_vertex_frame": CACHE_BYTES_PER_VERTEX_FRAME,
            "working_bytes_per_vertex_or_triangle": WORKING_BYTES_PER_GEOMETRY_ELEMENT,
        },
        "is_baked": False,
        "simulation_evaluated": False,
        "visual_acceptance": False,
        "limits": [
            "Static unparented local cloth/colliders only; rig, shape, animated, foreign handler and unsupported modifier dependencies are refused",
            "Memory/work estimates are admission checks, not OS memory limits or execution-time guarantees",
            "Creates a separate owned simulation scene; original proxy geometry, settings and cache are retained",
            "Ownership UUID metadata is evidence for scope, not an authenticity or security guarantee",
            "Synchronous selected embedded-cache bake; no file writes, external .bphys, global bake or production garment acceptance",
        ],
    }
    return proxy, cloth, colliders, settings, report


def _bake_selected(scene, proxy, cache):
    import bpy

    with bpy.context.temp_override(
        scene=scene,
        view_layer=scene.view_layers[0],
        object=proxy,
        active_object=proxy,
        point_cache=cache,
    ):
        if bpy.ops.ptcache.bake(bake=True) != {"FINISHED"}:
            raise RuntimeError("Selected cloth bake did not finish")
    if not cache.is_baked:
        raise RuntimeError("Selected cloth bake did not produce a baked cache")


def _verify_frames(scene, proxy, start, end):
    import bpy

    bounds = []
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        evaluated = proxy.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            if len(mesh.vertices) != len(proxy.data.vertices) or not all(
                math.isfinite(value) for vertex in mesh.vertices for value in vertex.co
            ):
                raise RuntimeError("Baked cloth has changed topology or non-finite coordinates")
            if frame in {start, end}:
                points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
                bounds.append(
                    {
                        "frame": frame,
                        "minimum": [min(point[axis] for point in points) for axis in range(3)],
                        "maximum": [max(point[axis] for point in points) for axis in range(3)],
                    }
                )
        finally:
            evaluated.to_mesh_clear()
    return bounds


def bake_cloth(params, context=None):
    limits = _parameters(params)
    context = checked_context(context)
    if context.window is None:
        raise ValueError("An owned Blender window context is required for isolated scene baking")
    source, source_cloth, colliders, settings, result = _preflight(params, context, limits)
    if result["dry_run"]:
        return result
    import bpy

    source_scene = context.scene
    created_objects, created_meshes, created_collections = [], [], []
    scene = None
    success = False
    try:
        identity = str(uuid4())
        scene = bpy.data.scenes.new("FW_ClothBake")
        scene["framewright_owner"] = "cloth_baking"
        scene["framewright_cloth_id"] = identity
        scene.frame_start, scene.frame_end = result["frame_start"], result["frame_end"]
        scene.render.fps, scene.render.fps_base = (
            source_scene.render.fps,
            source_scene.render.fps_base,
        )
        scene.unit_settings.system = source_scene.unit_settings.system
        scene.unit_settings.scale_length = source_scene.unit_settings.scale_length
        scene.gravity, scene.use_gravity = source_scene.gravity, source_scene.use_gravity

        def copy_object(original, suffix, role):
            copied = original.copy()
            created_objects.append(copied)
            copied_mesh = original.data.copy()
            created_meshes.append(copied_mesh)
            copied.data = copied_mesh
            copied.name = original.name + suffix
            copied.hide_viewport = False
            copied.hide_render = False
            copied["framewright_cloth_id"] = identity
            copied["framewright_cloth_schema"] = "1.0"
            copied["framewright_cloth_role"] = role
            scene.collection.objects.link(copied)
            return copied

        proxy = copy_object(source, "_Baked", "baked_proxy")
        proxy["framewright_cloth_bake_source_id"] = result["source_cloth_id"]
        # A copied configured proxy can carry an unbaked playback cache. Replace
        # that copied modifier with a genuinely fresh selected cache.
        proxy.modifiers.remove(proxy.modifiers[source_cloth.name])
        cloth = proxy.modifiers.new(source_cloth.name, "CLOTH")
        _apply_settings(cloth.settings, settings[0])
        _apply_settings(cloth.collision_settings, settings[1])
        _apply_settings(cloth.settings.effector_weights, settings[2])
        collision_collection = bpy.data.collections.new(proxy.name + "_Colliders")
        created_collections.append(collision_collection)
        collision_collection["framewright_owner"] = "secondary_motion"
        collision_collection["framewright_cloth_id"] = identity
        scene.collection.children.link(collision_collection)
        cloth.collision_settings.collection = collision_collection
        copied_colliders = []
        for collider in colliders:
            copied = copy_object(collider, "_BakeCollider", "collider")
            collision_collection.objects.link(copied)
            copied_colliders.append(copied)
        cache = cloth.point_cache
        cache.name = "FW_" + identity.replace("-", "")
        cache.frame_start, cache.frame_end = result["frame_start"], result["frame_end"]
        cache.use_disk_cache = False
        cache.use_external = False
        # Never activate another window scene: restoring the original window
        # scene can re-evaluate unrelated authored animation overrides.
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            scene.view_layers[0].objects.active = proxy
            proxy.select_set(True, view_layer=scene.view_layers[0])
            scene.frame_set(result["frame_start"])
            _bake_selected(scene, proxy, cache)
            if not cache.is_baked or cache.use_disk_cache or cache.use_external:
                raise RuntimeError("Selected cache did not remain a valid embedded bake")
            bounds = _verify_frames(scene, proxy, result["frame_start"], result["frame_end"])
            for obj in [proxy, *copied_colliders]:
                obj.hide_viewport = True
                obj.hide_render = True
                obj.select_set(False, view_layer=scene.view_layers[0])
        result.update(
            scene=scene.name,
            derivative=proxy.name,
            modifier=cloth.name,
            cloth_id=identity,
            collision_collection=collision_collection.name,
            collider_derivatives=[obj.name for obj in copied_colliders],
            is_baked=cache.is_baked,
            simulation_evaluated=True,
            evaluated_frames=result["frame_count"],
            cache_name=cache.name,
            cache_info=cache.info,
            cache_embedded=True,
            sampled_bounds=bounds,
            hidden=True,
            source_preserved=True,
        )
        success = True
        return result
    finally:
        if not success:
            for obj in reversed(created_objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            for mesh in reversed(created_meshes):
                bpy.data.meshes.remove(mesh)
            for collection in reversed(created_collections):
                bpy.data.collections.remove(collection)
            if scene is not None:
                bpy.data.scenes.remove(scene)
