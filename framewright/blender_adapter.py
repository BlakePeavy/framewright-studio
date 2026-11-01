"""Main-thread Blender boundary; snapshots inspect source meshes, not modifiers."""

import threading
from pathlib import Path

import bmesh
import bpy

from .core import ObjectSnapshot, SceneSnapshot, TextureSnapshot


def _context(context=None):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender access must run on the main thread")
    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before inspecting or repairing a scene")
    return context


def _mesh_stats(mesh):
    """Inspect a temporary BMesh; do not tessellate or change the source datablock."""
    temporary = bmesh.new()
    try:
        temporary.from_mesh(mesh)
        return {
            "vertex_count": len(temporary.verts),
            "edge_count": len(temporary.edges),
            "polygon_count": len(temporary.faces),
            "triangle_count": sum(max(0, len(face.verts) - 2) for face in temporary.faces),
            "nonmanifold_edges": sum(not edge.is_manifold for edge in temporary.edges),
            "loose_vertices": sum(not vert.link_edges for vert in temporary.verts),
            "degenerate_faces": sum(face.calc_area() <= 1e-12 for face in temporary.faces),
            "uv_layer_count": len(mesh.uv_layers),
        }
    finally:
        temporary.free()


def _animation(obj):
    data = obj.animation_data
    if not data:
        return False, None
    ranges = []
    if data.action:
        ranges.append(tuple(data.action.frame_range))
    for track in data.nla_tracks:
        for strip in track.strips:
            ranges.append((strip.frame_start, strip.frame_end))
    frame_range = None
    if ranges:
        frame_range = (min(start for start, _ in ranges), max(end for _, end in ranges))
    return bool(data.action or data.drivers or ranges), frame_range


def _deform_stats(obj):
    target = next(
        (
            modifier.object
            for modifier in obj.modifiers
            if modifier.type == "ARMATURE" and modifier.object is not None
        ),
        None,
    )
    if target is None or target.type != "ARMATURE":
        return {}
    deform_names = {bone.name for bone in target.data.bones if bone.use_deform}
    indices = {group.index for group in obj.vertex_groups if group.name in deform_names}
    influences = [
        sum(group.group in indices and group.weight > 0.0 for group in vertex.groups)
        for vertex in obj.data.vertices
    ]
    return {
        "armature_target": target.name,
        "unweighted_vertices": sum(count == 0 for count in influences),
        "max_vertex_influences": max(influences, default=0),
    }


def _scene_images(scene):
    """Traverse referenced material/world node groups once, including cycles."""
    trees = []
    for obj in scene.objects:
        for slot in obj.material_slots:
            if slot.material and slot.material.node_tree:
                trees.append(slot.material.node_tree)
    if scene.world and scene.world.node_tree:
        trees.append(scene.world.node_tree)
    seen = set()
    images = {}
    while trees:
        tree = trees.pop()
        key = tree.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        for node in tree.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                images[image.as_pointer()] = image
            nested_tree = getattr(node, "node_tree", None)
            if nested_tree is not None:
                trees.append(nested_tree)
    return sorted(images.values(), key=lambda image: image.name)


def _image_missing(image):
    if image.source not in {"FILE", "TILED", "SEQUENCE", "MOVIE"}:
        return False
    if image.packed_file or image.packed_files:
        return False
    path = bpy.path.abspath(image.filepath, library=image.library)
    if not path:
        return True
    if image.source == "TILED":
        for tile in image.tiles:
            u = (tile.number - 1001) % 10 + 1
            v = (tile.number - 1001) // 10 + 1
            tile_path = path.replace("<UDIM>", str(tile.number)).replace("<UVTILE>", f"u{u}_v{v}")
            if not Path(tile_path).is_file():
                return True
        return False
    return not Path(path).is_file()


def capture_scene(context=None):
    """Return source-geometry facts without switching modes or modifying data.

    Triangle counts assume ordinary n-gon tessellation; modifiers, render output,
    full sequence coverage, texture channels and visual quality need later gates.
    """
    context = _context(context)
    scene = context.scene
    objects = []
    meshes = {}
    for obj in sorted(scene.objects, key=lambda item: item.name):
        has_animation, animation_range = _animation(obj)
        fields = {
            "name": obj.name,
            "type": obj.type,
            "scale": tuple(obj.scale),
            "modifier_types": tuple(modifier.type for modifier in obj.modifiers),
            "has_animation": has_animation,
            "animation_range": animation_range,
        }
        if obj.type == "MESH":
            key = obj.data.as_pointer()
            if key not in meshes:
                meshes[key] = _mesh_stats(obj.data)
            fields.update(meshes[key])
            fields.update(
                material_slot_count=len(obj.material_slots),
                missing_material_slots=sum(slot.material is None for slot in obj.material_slots),
                vertex_group_count=len(obj.vertex_groups),
            )
            fields.update(_deform_stats(obj))
        elif obj.type == "ARMATURE":
            fields.update(
                bone_count=len(obj.data.bones),
                root_bone_count=sum(bone.parent is None for bone in obj.data.bones),
            )
        objects.append(ObjectSnapshot(**fields))
    images = _scene_images(scene)
    textures = tuple(
        TextureSnapshot(
            name=image.name,
            width=image.size[0],
            height=image.size[1],
            source=image.source,
            color_space=image.colorspace_settings.name,
        )
        for image in images
    )
    return SceneSnapshot(
        name=scene.name,
        objects=tuple(objects),
        unit_system=scene.unit_settings.system,
        unit_scale=scene.unit_settings.scale_length,
        fps=scene.render.fps / scene.render.fps_base,
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        camera_name=scene.camera.name if scene.camera else None,
        light_count=sum(obj.type == "LIGHT" for obj in scene.objects),
        world_present=scene.world is not None,
        missing_images=tuple(image.name for image in images if _image_missing(image)),
        textures=textures,
    )


def _repair_source(object_name, context=None):
    context = _context(context)
    matches = [obj for obj in context.scene.objects if obj.name == object_name]
    if len(matches) != 1:
        raise ValueError("Object name is missing or ambiguous in the active scene")
    source = matches[0]
    if source.type != "MESH":
        raise ValueError("Repair supports mesh objects only")
    if (
        source.library
        or source.data.library
        or source.override_library
        or source.data.override_library
    ):
        raise ValueError("Linked or library override objects are not supported")
    if source.data.shape_keys:
        raise ValueError("Repair does not support shape keys")
    if source.animation_data or source.data.animation_data:
        raise ValueError("Repair does not support animated objects")
    if source.modifiers:
        raise ValueError("Repair does not support objects with modifiers")
    if source.parent:
        raise ValueError("Repair does not support parented objects")
    if source.vertex_groups:
        raise ValueError("Repair does not support vertex groups")
    if source.constraints:
        raise ValueError("Repair does not support constrained objects")
    # Count edge participation directly: previews need no temporary BMesh.
    connected = bytearray(len(source.data.vertices))
    for edge in source.data.edges:
        connected[edge.vertices[0]] = 1
        connected[edge.vertices[1]] = 1
    loose_count = len(connected) - sum(connected)
    if not loose_count:
        raise ValueError("Mesh has no isolated loose vertices to remove")
    return context, source, loose_count


def preview_remove_loose_vertices(object_name, context=None):
    """Read-only plan for removing vertices that belong to no edges or faces."""
    _, source, loose_count = _repair_source(object_name, context)
    return {
        "source": source.name,
        "removed_vertices": loose_count,
        "dry_run": True,
    }


def apply_remove_loose_vertices(object_name, context=None):
    """Create a repaired derivative; never alter the source or current selection."""
    context, source, _ = _repair_source(object_name, context)
    derivative = None
    derivative_mesh = None
    temporary = bmesh.new()
    try:
        temporary.from_mesh(source.data)
        loose = [vert for vert in temporary.verts if not vert.link_edges]
        removed = len(loose)
        bmesh.ops.delete(temporary, geom=loose, context="VERTS")
        derivative_mesh = source.data.copy()
        derivative_mesh.name = f"{source.data.name}_FW_Clean"
        temporary.to_mesh(derivative_mesh)
        derivative_mesh.update()
        derivative = source.copy()
        derivative.name = f"{source.name}_FW_Clean"
        derivative.data = derivative_mesh
        context.scene.collection.objects.link(derivative)
        derivative.select_set(False)
        derivative.hide_viewport = True
        derivative.hide_render = True
        return {
            "source": source.name,
            "derivative": derivative.name,
            "removed_vertices": removed,
            "dry_run": False,
            "hidden": True,
        }
    except Exception:
        if derivative is not None:
            bpy.data.objects.remove(derivative, do_unlink=True)
        if derivative_mesh is not None and derivative_mesh.users == 0:
            bpy.data.meshes.remove(derivative_mesh)
        raise
    finally:
        temporary.free()
