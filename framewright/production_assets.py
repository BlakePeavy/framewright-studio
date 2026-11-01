"""Owned, editable construction tools and isolated look-development scenes.

All dimensions are in metres. No operators, scripts from requests, file writes or
network calls are used by construction. Technical fixtures are not art approval.
"""

from __future__ import annotations

import math
import threading

import bpy
from mathutils import Matrix, Vector

from .static_data import require_static_mesh_material_data

OWNER = "production_assets"
REVIEW_SOURCE_OWNERS = frozenset({OWNER, "material_atlas"})


def _context(context=None):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender access must run on the main thread")
    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before authoring or inspecting assets")
    return context


def _require_no_update_handlers():
    """Do not let global callbacks mutate unrelated data during owned evaluation."""
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
            "Construction/evaluated inspection refuses registered frame/depsgraph handlers; builder previews remain available"
        )


def _params(params, defaults):
    if not isinstance(params, dict) or set(params) - set(defaults):
        raise ValueError("Unknown or invalid parameters")
    result = dict(defaults, **params)
    if "dry_run" in result and type(result["dry_run"]) is not bool:
        raise ValueError("dry_run must be a boolean")
    if "name" in result:
        name = result["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 48 or not name.isprintable():
            raise ValueError("name must contain 1 to 48 printable characters")
    if "location" in result:
        location = result["location"]
        if not isinstance(location, (list, tuple)) or len(location) != 3:
            raise ValueError("location must contain three finite metre coordinates")
        result["location"] = [_number(value, -1e6, 1e6, "location") for value in location]
    return result


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return float(value)


class _Transaction:
    def __init__(self):
        self.created = []
        self.collection = None

    def add(self, kind, item):
        self.created.append((kind, item))
        return item

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            for kind in (
                "objects",
                "scenes",
                "collections",
                "meshes",
                "cameras",
                "lights",
                "worlds",
                "materials",
            ):
                for item_kind, item in reversed(self.created):
                    if item_kind == kind:
                        getattr(bpy.data, kind).remove(item, do_unlink=True)
        return False

    def new_collection(self, name, parent):
        collection = self.add("collections", bpy.data.collections.new(name))
        collection["framewright_owner"] = OWNER
        parent.children.link(collection)
        self.collection = collection
        return collection


def _material(tx, name, color, roughness=0.5, metallic=0.0, *, wood=False, glass=False):
    material = tx.add("materials", bpy.data.materials.new(name))
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    material["framewright_owner"] = OWNER
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if glass:
        shader.inputs["Transmission Weight"].default_value = 0.92
        shader.inputs["IOR"].default_value = 1.45
    if wood:
        nodes, links = material.node_tree.nodes, material.node_tree.links
        coordinates = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (6, 6, 0.65)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 4
        noise.inputs["Detail"].default_value = 3
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*(channel * 0.6 for channel in color), 1)
        ramp.color_ramp.elements[1].color = (*(min(channel * 1.3, 1) for channel in color), 1)
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.0006
        links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    return material


def _uv_atlas(mesh):
    """Deterministic separate planar islands with shared per-object UV scale."""
    layer = mesh.uv_layers.new(name="ConstructionUV")
    charts = []
    for face in mesh.polygons:
        normal = face.normal
        drop = max(range(3), key=lambda axis: abs(normal[axis]))
        axes = [axis for axis in range(3) if axis != drop]
        points = [tuple(mesh.vertices[index].co[axis] for axis in axes) for index in face.vertices]
        lower = tuple(min(point[axis] for point in points) for axis in range(2))
        spans = tuple(max(point[axis] for point in points) - lower[axis] for axis in range(2))
        charts.append((face, points, lower, spans))
    scale = max((max(chart[3]) for chart in charts), default=1)
    scale = max(scale, 1e-9)
    columns = math.ceil(math.sqrt(len(charts)))
    for index, (face, points, lower, spans) in enumerate(charts):
        offset = (index % columns, index // columns)
        for loop, point in zip(face.loop_indices, points, strict=True):
            layer.data[loop].uv = tuple(
                (offset[axis] + 0.5 + (point[axis] - lower[axis] - spans[axis] / 2) / scale * 0.9)
                / columns
                for axis in range(2)
            )


def _mesh_object(tx, name, vertices, faces, location, material, role, bevel):
    mesh = tx.add("meshes", bpy.data.meshes.new(name + "Mesh"))
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    _uv_atlas(mesh)
    obj = tx.add("objects", bpy.data.objects.new(name, mesh))
    tx.collection.objects.link(obj)
    obj.location = location
    obj["framewright_owner"] = OWNER
    obj["framewright_role"] = role
    mesh.materials.append(material)
    for face in mesh.polygons:
        face.use_smooth = True
    modifier = obj.modifiers.new("Construction bevel", "BEVEL")
    modifier.width = bevel
    modifier.segments = 3
    modifier.harden_normals = True
    normals = obj.modifiers.new("Face-weighted normals", "WEIGHTED_NORMAL")
    normals.keep_sharp = True
    return obj


def _box(tx, name, dimensions, location, material, role, bevel):
    x, y, z = (value / 2 for value in dimensions)
    vertices = [
        (-x, -y, -z),
        (x, -y, -z),
        (x, y, -z),
        (-x, y, -z),
        (-x, -y, z),
        (x, -y, z),
        (x, y, z),
        (-x, y, z),
    ]
    faces = [(0, 3, 2, 1), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)]
    return _mesh_object(
        tx, name, vertices, faces, location, material, role, min(bevel, min(dimensions) / 3)
    )


def _cylinder(tx, name, radius, length, location, material, role, bevel, segments=16):
    vertices = [
        (
            radius * math.cos(index * math.tau / segments),
            radius * math.sin(index * math.tau / segments),
            z,
        )
        for z in (-length / 2, length / 2)
        for index in range(segments)
    ]
    faces = [
        (index, (index + 1) % segments, (index + 1) % segments + segments, index + segments)
        for index in range(segments)
    ]
    faces += [tuple(reversed(range(segments))), tuple(range(segments, segments * 2))]
    return _mesh_object(
        tx, name, vertices, faces, location, material, role, min(bevel, radius / 3, length / 3)
    )


def _parent_keep_world(obj, parent):
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = matrix


def _scene_metres_per_unit(scene):
    return _number(scene.unit_settings.scale_length, 1e-12, 1e12, "scene unit scale")


def _assign_owned_world_matrices(matrices, view_layer):
    """Assign parents before children so evaluated parent transforms are current."""
    pending = set(matrices)
    while pending:
        ready = sorted(
            (obj for obj in pending if obj.parent not in pending), key=lambda obj: obj.name
        )
        if not ready:
            raise ValueError("Owned object hierarchy contains a parent cycle")
        for obj in ready:
            obj.matrix_world = matrices[obj]
        view_layer.update()
        pending.difference_update(ready)


def _convert_owned_metre_geometry(objects, metres_per_unit, view_layer):
    if metres_per_unit == 1:
        return
    conversion = Matrix.Scale(1 / metres_per_unit, 4)
    matrices = {obj: conversion @ obj.matrix_world.copy() for obj in objects}
    _assign_owned_world_matrices(matrices, view_layer)


def build_prop(params, context=None):
    """Build a timber workshop cabinet with separate door, hinges and hardware."""
    context = _context(context)
    p = _params(
        params,
        {
            "name": "FW_WorkshopCabinet",
            "width": 0.9,
            "depth": 0.5,
            "height": 1.25,
            "board_thickness": 0.024,
            "bevel": 0.003,
            "door_open_degrees": 0,
            "location": [0, 0, 0],
            "dry_run": True,
        },
    )
    for key, lower, upper in (
        ("width", 0.3, 10),
        ("depth", 0.2, 5),
        ("height", 0.4, 10),
        ("board_thickness", 0.005, 0.1),
        ("bevel", 0.0001, 0.03),
        ("door_open_degrees", 0, 160),
    ):
        p[key] = _number(p[key], lower, upper, key)
    w, d, h, t = (p[key] for key in ("width", "depth", "height", "board_thickness"))
    metres_per_unit = _scene_metres_per_unit(context.scene)
    if t * 8 >= min(w, d, h) or p["bevel"] > t / 3:
        raise ValueError("Board thickness/bevel must leave usable cabinet dimensions")
    rail = min(w * 0.085, 0.085)
    door_bottom, door_top = t * 4.2, h - t * 1.8
    door_width = w - 2.5 * t
    rail_centers = (
        door_bottom + rail / 2,
        (door_top + door_bottom) / 2,
        door_top - rail / 2,
    )
    if door_width - 2 * rail <= 1e-6 or any(
        rail_centers[index + 1] - rail_centers[index] - rail <= 1e-6 for index in (0, 1)
    ):
        raise ValueError("Door rails must leave positive panel openings")
    result = {
        "dry_run": p["dry_run"],
        "kind": "workshop_cabinet",
        "parameters": p,
        "units": "metres",
        "unit_conversion": {
            "source_scene_metres_per_unit": metres_per_unit,
            "output_scene_metres_per_unit": metres_per_unit,
            "authored_metres_to_output_world_scale": 1 / metres_per_unit,
        },
        "visual_acceptance": "not_reviewed",
    }
    if p["dry_run"]:
        result["planned_parts"] = [
            "carcass",
            "shelves",
            "plinth",
            "framed_door",
            "hinges",
            "latch",
            "screws",
        ]
        return result
    _require_no_update_handlers()
    with _Transaction() as tx:
        collection = tx.new_collection(p["name"], context.scene.collection)
        wood = _material(tx, p["name"] + "_Walnut", (0.20, 0.105, 0.047), wood=True)
        panel = _material(tx, p["name"] + "_PanelWood", (0.27, 0.15, 0.065), wood=True)
        iron = _material(tx, p["name"] + "_Iron", (0.065, 0.075, 0.085), 0.4, 0.85)
        brass = _material(tx, p["name"] + "_Brass", (0.45, 0.29, 0.11), 0.32, 0.9)
        origin = Vector(p["location"])

        def box(label, size, position, material=wood, role="carcass"):
            return _box(
                tx,
                p["name"] + "_" + label,
                size,
                origin + Vector(position),
                material,
                role,
                p["bevel"],
            )

        for side in (-1, 1):
            box(
                "Side" + str(side),
                (t, d, h - t * 2.5),
                (side * (w - t) / 2, 0, (h - t * 2.5) / 2 + t),
            )
            box("Foot" + str(side), (w * 0.12, d * 0.82, t * 2), (side * w * 0.34, d * 0.04, t))
        box("Bottom", (w - 2 * t, d - t, t), (0, -t / 2, t * 3))
        box("Top", (w + t, d + t, t * 1.5), (0, 0, h - t * 0.75))
        box("Back", (w - 2 * t, t, h - t * 3), (0, (d - t) / 2, h / 2))
        for index in (1, 2):
            box(f"Shelf{index}", (w - 2 * t, d - 3 * t, t), (0, 0, h * index / 3), panel, "shelf")
        box("Plinth", (w - 2 * t, t, t * 2), (0, -d / 2 + t, t * 2), wood, "plinth")
        front_y = -d / 2 - t * 0.55
        hinge_y = front_y - t * 0.6
        pivot = tx.add("objects", bpy.data.objects.new(p["name"] + "_DoorPivot", None))
        collection.objects.link(pivot)
        pivot.location = origin + Vector((-door_width / 2, hinge_y, 0))
        pivot["framewright_owner"] = OWNER
        pivot["framewright_role"] = "door_pivot"
        pivot.empty_display_type = "PLAIN_AXES"
        pivot.empty_display_size = 0.1
        context.view_layer.update()
        door_parts = []
        for side in (-1, 1):
            door_parts.append(
                box(
                    "DoorStile" + str(side),
                    (rail, t, door_top - door_bottom),
                    (side * (door_width - rail) / 2, front_y, (door_top + door_bottom) / 2),
                    wood,
                    "door",
                )
            )
        for index, z in enumerate(rail_centers):
            door_parts.append(
                box(
                    f"DoorRail{index}",
                    (door_width - 2 * rail, t, rail),
                    (0, front_y, z),
                    wood,
                    "door",
                )
            )
        for index in (0, 1):
            opening_bottom = rail_centers[index] + rail / 2
            opening_top = rail_centers[index + 1] - rail / 2
            # Match the existing horizontal seat allowance on all four edges.
            # These remain overlapping rectangular seats, not cut mortises.
            seat = rail * 0.1
            z = (opening_bottom + opening_top) / 2
            door_parts.append(
                box(
                    f"InsetPanel{index}",
                    (
                        door_width - 2 * rail + 2 * seat,
                        t * 0.55,
                        opening_top - opening_bottom + 2 * seat,
                    ),
                    (0, front_y + t * 0.2, z),
                    panel,
                    "door",
                )
            )
        for index, z in enumerate(
            (
                door_bottom + (door_top - door_bottom) * 0.18,
                door_bottom + (door_top - door_bottom) * 0.82,
            )
        ):
            plate = box(
                f"HingePlate{index}",
                # Limit the leaf's overhang behind its pivot so thin-board
                # cabinets retain clearance as the plate swings past the side.
                (rail + 2 * min(rail * 0.3, t * 0.95), t * 0.18, rail * 0.8),
                (-door_width / 2 + rail * 0.5, hinge_y, z),
                iron,
                "hinge",
            )
            door_parts.append(plate)
            _cylinder(
                tx,
                p["name"] + f"_HingePin{index}",
                t * 0.32,
                rail,
                origin + Vector((-door_width / 2, hinge_y, z)),
                iron,
                "hinge",
                p["bevel"],
            )
            for screw_index, offset in enumerate((-rail * 0.35, rail * 0.35)):
                screw = _cylinder(
                    tx,
                    p["name"] + f"_HingeScrew{index}_{screw_index}",
                    t * 0.12,
                    t * 0.09,
                    origin + Vector((-door_width / 2 + rail * 0.5 + offset, front_y - t * 0.72, z)),
                    brass,
                    "fastener",
                    p["bevel"],
                )
                screw.rotation_euler.x = math.pi / 2
                door_parts.append(screw)
        handle_x, handle_z = door_width / 2 - rail * 0.5, (door_top + door_bottom) / 2
        door_parts.append(
            box(
                "LatchBackplate",
                (rail * 0.75, t * 0.2, rail * 1.7),
                (handle_x, front_y - t * 0.6, handle_z),
                iron,
                "latch",
            )
        )
        for index, z in enumerate((handle_z - rail * 0.45, handle_z + rail * 0.45)):
            door_parts.append(
                box(
                    f"HandleMount{index}",
                    (t * 0.4, t * 1.2, t * 0.4),
                    (handle_x, front_y - t, z),
                    brass,
                    "handle",
                )
            )
        door_parts.append(
            box(
                "HandleGrip",
                (t * 0.5, t * 0.5, rail * 1.15),
                (handle_x, front_y - t * 1.65, handle_z),
                brass,
                "handle",
            )
        )
        context.view_layer.update()
        for part in door_parts:
            _parent_keep_world(part, pivot)
        pivot.rotation_euler.z = -math.radians(p["door_open_degrees"])
        context.view_layer.update()
        _convert_owned_metre_geometry(collection.objects, metres_per_unit, context.view_layer)
        result.update(
            collection=collection.name,
            objects=sorted(obj.name for obj in collection.objects),
            controls={"door_pivot": pivot.name},
            materials=[wood.name, panel.name, iron.name, brass.name],
        )
        return result


def build_facade(params, context=None):
    """Construct a period shop bay with real opening recesses and separate parts."""
    context = _context(context)
    metres_per_unit = _scene_metres_per_unit(context.scene)
    p = _params(
        params,
        {
            "name": "FW_FacadeBay",
            "width": 4.0,
            "height": 3.4,
            "depth": 0.25,
            "door_width": 0.95,
            "door_height": 2.15,
            "window_width": 1.5,
            "window_height": 1.35,
            "sill_height": 0.85,
            "bevel": 0.01,
            "location": [0, 0, 0],
            "dry_run": True,
        },
    )
    for key, lower, upper in (
        ("width", 1.5, 20),
        ("height", 2, 10),
        ("depth", 0.12, 1),
        ("door_width", 0.65, 2),
        ("door_height", 1.8, 3),
        ("window_width", 0.4, 8),
        ("window_height", 0.4, 4),
        ("sill_height", 0.25, 2),
        ("bevel", 0.0001, 0.03),
    ):
        p[key] = _number(p[key], lower, upper, key)
    w, h, d, dw, dh, ww, wh, sill = (
        p[key]
        for key in (
            "width",
            "height",
            "depth",
            "door_width",
            "door_height",
            "window_width",
            "window_height",
            "sill_height",
        )
    )
    gap = w * 0.08
    side = (w - dw - ww - gap) / 2
    if side < 0.15 or dh > h - 0.2 or sill + wh > h - 0.2:
        raise ValueError("Openings must leave at least 0.15 m side piers and 0.2 m lintel")
    door_x = -w / 2 + side + dw / 2
    window_x = door_x + dw / 2 + gap + ww / 2
    result = {
        "dry_run": p["dry_run"],
        "kind": "facade_bay",
        "parameters": p,
        "units": "metres",
        "unit_conversion": {
            "source_scene_metres_per_unit": metres_per_unit,
            "output_scene_metres_per_unit": metres_per_unit,
            "authored_metres_to_output_world_scale": 1 / metres_per_unit,
        },
        "visual_acceptance": "not_reviewed",
    }
    if p["dry_run"]:
        result["planned_parts"] = [
            "wall_piers",
            "lintels",
            "recessed_door",
            "window_frame",
            "mullions",
            "glazing",
            "sill",
            "parapet_cap",
        ]
        return result
    _require_no_update_handlers()
    with _Transaction() as tx:
        collection = tx.new_collection(p["name"], context.scene.collection)
        plaster = _material(tx, p["name"] + "_WarmPlaster", (0.52, 0.40, 0.27), 0.82)
        stone = _material(tx, p["name"] + "_Limestone", (0.38, 0.34, 0.28), 0.72)
        timber = _material(tx, p["name"] + "_PaintedTimber", (0.07, 0.16, 0.14), 0.46)
        glass = _material(tx, p["name"] + "_Glass", (0.90, 0.96, 0.98), 0.09, glass=True)
        brass = _material(tx, p["name"] + "_Brass", (0.45, 0.29, 0.11), 0.3, 0.9)
        origin = Vector(p["location"])

        def box(label, size, position, material=plaster, role="wall"):
            return _box(
                tx,
                p["name"] + "_" + label,
                size,
                origin + Vector(position),
                material,
                role,
                p["bevel"],
            )

        box("LeftPier", (side, d, h), (-w / 2 + side / 2, 0, h / 2))
        box("MiddlePier", (gap, d, h), (door_x + dw / 2 + gap / 2, 0, h / 2))
        box("RightPier", (side, d, h), (w / 2 - side / 2, 0, h / 2))
        box("DoorLintel", (dw, d, h - dh), (door_x, 0, (h + dh) / 2))
        box("WindowApron", (ww, d, sill), (window_x, 0, sill / 2))
        box("WindowLintel", (ww, d, h - sill - wh), (window_x, 0, (h + sill + wh) / 2))
        front = -d / 2
        trim = 0.065
        for sign in (-1, 1):
            box(
                "DoorJamb" + str(sign),
                (trim, d * 0.55, dh),
                (door_x + sign * (dw - trim) / 2, front + d * 0.275, dh / 2),
                timber,
                "door_frame",
            )
        box(
            "DoorHead",
            (dw, d * 0.55, trim),
            (door_x, front + d * 0.275, dh - trim / 2),
            timber,
            "door_frame",
        )
        box("Threshold", (dw, d + 0.12, 0.035), (door_x, -0.04, 0.0175), stone, "threshold")
        leaf_width = dw - trim * 2 - 0.008
        leaf_y = front + d * 0.45
        box(
            "DoorLeaf",
            (leaf_width, 0.04, dh - trim - 0.025),
            (door_x, leaf_y, (dh - trim) / 2),
            timber,
            "door",
        )
        for index in (0, 1):
            z = dh * (0.27 + index * 0.46)
            box(
                f"DoorRaisedPanel{index}",
                (leaf_width * 0.72, 0.022, dh * 0.34),
                (door_x, leaf_y - 0.029, z),
                timber,
                "door",
            )
        box(
            "DoorHandlePlate",
            (0.055, 0.008, 0.18),
            (door_x + leaf_width * 0.35, leaf_y - 0.028, dh * 0.48),
            brass,
            "handle",
        )
        box(
            "DoorHandle",
            (0.025, 0.065, 0.1),
            (door_x + leaf_width * 0.35, leaf_y - 0.055, dh * 0.48),
            brass,
            "handle",
        )
        frame_y = front + d * 0.36
        for sign in (-1, 1):
            box(
                "WindowJamb" + str(sign),
                (trim, d * 0.45, wh),
                (window_x + sign * (ww - trim) / 2, frame_y, sill + wh / 2),
                timber,
                "window_frame",
            )
            box(
                "WindowRail" + str(sign),
                (ww, d * 0.45, trim),
                (window_x, frame_y, sill + (wh if sign > 0 else 0) - sign * trim / 2),
                timber,
                "window_frame",
            )
        box(
            "Mullion",
            (0.045, d * 0.42, wh - trim * 2),
            (window_x, frame_y - 0.003, sill + wh / 2),
            timber,
            "window_frame",
        )
        box(
            "Transom",
            (ww - trim * 2, d * 0.42, 0.045),
            (window_x, frame_y - 0.003, sill + wh * 0.65),
            timber,
            "window_frame",
        )
        box(
            "Glazing",
            (ww - trim * 2, 0.008, wh - trim * 2),
            (window_x, frame_y + 0.025, sill + wh / 2),
            glass,
            "glazing",
        )
        box("Sill", (ww + 0.16, d + 0.18, 0.07), (window_x, -0.08, sill - 0.035), stone, "sill")
        box(
            "WindowHeader",
            (ww + 0.15, d * 0.7, 0.11),
            (window_x, front, sill + wh + 0.055),
            stone,
            "trim",
        )
        box("DoorHeader", (dw + 0.15, d * 0.7, 0.11), (door_x, front, dh + 0.055), stone, "trim")
        box("ParapetCap", (w + 0.12, d + 0.16, 0.09), (0, -0.025, h + 0.045), stone, "cap")
        box("Cornice", (w + 0.035, d * 0.7, 0.1), (0, front - 0.015, h - 0.12), stone, "trim")
        context.view_layer.update()
        _convert_owned_metre_geometry(collection.objects, metres_per_unit, context.view_layer)
        result.update(
            collection=collection.name,
            objects=sorted(obj.name for obj in collection.objects),
            openings={"door_center_x": door_x, "window_center_x": window_x},
            materials=[plaster.name, stone.name, timber.name, glass.name, brass.name],
        )
        return result


def _static_review_matrices(objects):
    """Read authored static channels, including hidden cold-file parent chains.

    matrix_world is an evaluation cache: hidden objects can retain identity after
    reopening a blend. Reading channels avoids exposing or evaluating originals.
    Constraints/animation and non-object parenting need a different review path.
    """
    matrices = {}
    for source in objects:
        chain = []
        seen = set()
        current = source
        while current is not None and current not in matrices:
            if current in seen or len(chain) + len(matrices) >= 2048:
                raise ValueError("Review parent hierarchy is cyclic or exceeds 2048 objects")
            if current.animation_data or current.constraints:
                raise ValueError("Review requires static object and parent transforms")
            if current.parent is not None and current.parent_type != "OBJECT":
                raise ValueError(
                    "Review requires static object parenting, not bone/vertex parenting"
                )
            seen.add(current)
            chain.append(current)
            current = current.parent
        for obj in reversed(chain):
            matrix = obj.matrix_basis.copy()
            if obj.parent is not None:
                matrix = matrices[obj.parent] @ obj.matrix_parent_inverse @ matrix
            if not all(math.isfinite(value) for row in matrix for value in row):
                raise ValueError("Review requires finite authored world transforms")
            matrices[obj] = matrix
    return {obj: matrices[obj] for obj in objects}


def _review_sources(p, context):
    names, collection_name = p["object_names"], p["collection_name"]
    if bool(names) == bool(collection_name):
        raise ValueError("Specify exactly one nonempty object_names or collection_name")
    if collection_name:
        if not isinstance(collection_name, str):
            raise ValueError("collection_name must be a name")
        collection = bpy.data.collections.get(collection_name)
        if collection is None or collection.get("framewright_owner") not in REVIEW_SOURCE_OWNERS:
            raise ValueError("Review collection must be owned by supported Framewright tools")
        objects = list(collection.all_objects)
    else:
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("object_names must contain exact object names")
        objects = [context.scene.objects.get(name) for name in names]
    if not objects or len(objects) > 500:
        raise ValueError("Review requires between 1 and 500 owned objects")
    if any(
        obj is None or obj.get("framewright_owner") not in REVIEW_SOURCE_OWNERS for obj in objects
    ):
        raise ValueError("Review sources must be owned Framewright objects")
    active_objects = set(context.scene.objects)
    if any(obj not in active_objects for obj in objects):
        raise ValueError(
            "Review sources must belong to the active scene to establish source scene units"
        )
    if any(
        obj.type not in {"MESH", "EMPTY"} or obj.animation_data or obj.constraints
        for obj in objects
    ):
        raise ValueError("Review currently supports static owned mesh/empty objects only")
    if not any(obj.type == "MESH" for obj in objects):
        raise ValueError("Review requires at least one mesh")
    require_static_mesh_material_data(objects)
    included = set(objects)
    matrices = _static_review_matrices(included)
    for obj in included:
        if obj.parent is not None and obj.parent not in included:
            columns = [matrices[obj].to_3x3().col[index].copy() for index in range(3)]
            if any(
                abs(columns[first].dot(columns[second]))
                > 1e-6 * columns[first].length * columns[second].length
                for first, second in ((0, 1), (0, 2), (1, 2))
            ):
                raise ValueError(
                    "Review cannot detach a sheared parent transform; include the complete owned parent hierarchy or apply transforms on a separate derivative first"
                )
    return sorted(set(objects), key=lambda obj: obj.name)


def _point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_review_scene(params, context=None):
    """Copy an owned asset into a separate scene with four cameras and three lights."""
    context = _context(context)
    p = _params(
        params,
        {
            "name": "FW_Review",
            "object_names": [],
            "collection_name": "",
            "lighting": "neutral",
            "resolution": 1024,
            "dry_run": True,
        },
    )
    if not isinstance(p["lighting"], str) or p["lighting"] not in {"neutral", "day", "dusk"}:
        raise ValueError("lighting must be neutral, day or dusk")
    if type(p["resolution"]) is not int or not 64 <= p["resolution"] <= 8192:
        raise ValueError("resolution must be an integer from 64 to 8192")
    sources = _review_sources(p, context)
    metres_per_unit = _scene_metres_per_unit(context.scene)
    result = {
        "dry_run": p["dry_run"],
        "parameters": p,
        "source_objects": [obj.name for obj in sources],
        "units": "metres",
        "unit_conversion": {
            "source_scene_metres_per_unit": metres_per_unit,
            "output_scene_metres_per_unit": 1.0,
            "source_world_to_output_world_scale": metres_per_unit,
        },
        "visual_acceptance": "not_reviewed",
    }
    if p["dry_run"]:
        return result
    _require_no_update_handlers()
    source_matrices = _static_review_matrices(sources)
    with _Transaction() as tx:
        scene = tx.add("scenes", bpy.data.scenes.new(p["name"]))
        scene["framewright_owner"] = OWNER
        collection = tx.new_collection(p["name"] + "_Contents", scene.collection)
        copies = {}
        for source in sources:
            duplicate = tx.add("objects", source.copy())
            duplicate.name = p["name"] + "_" + source.name
            # Sources/derivatives may deliberately be hidden in the authoring
            # scene. Explicit review copies must be visible in their own scene.
            duplicate.hide_viewport = False
            duplicate.hide_render = False
            if source.data is not None:
                duplicate.data = tx.add("meshes", source.data.copy())
            collection.objects.link(duplicate)
            copies[source] = duplicate
        # Disconnect original parents before the first derivative graph update;
        # otherwise Blender evaluates hidden originals through copied links.
        for source, duplicate in copies.items():
            duplicate.parent = copies.get(source.parent)
        for layer in scene.view_layers:
            layer.update()
            for duplicate in copies.values():
                duplicate.hide_set(False, view_layer=layer)
        converted_world_matrices = {}
        conversion = Matrix.Scale(metres_per_unit, 4)
        for source, duplicate in copies.items():
            converted_world_matrices[duplicate] = conversion @ source_matrices[source]
        _assign_owned_world_matrices(converted_world_matrices, scene.view_layers[0])
        # Evaluate only the visible copies; cold hidden originals also have stale
        # bounding-box caches. Include the copied modifiers when framing the view.
        graph = scene.view_layers[0].depsgraph
        evaluated_meshes = [
            obj.evaluated_get(graph) for obj in copies.values() if obj.type == "MESH"
        ]
        points = [
            obj.matrix_world @ Vector(corner)
            for obj in evaluated_meshes
            for corner in obj.bound_box
        ]
        lower = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
        upper = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
        center = (lower + upper) / 2
        span = max(max(upper - lower), 0.1)
        floor = _material(tx, p["name"] + "_NeutralFloor", (0.18, 0.18, 0.18), 0.72)
        _box(
            tx,
            p["name"] + "_Floor",
            (span * 12, span * 12, 0.04),
            (center.x, center.y, lower.z - 0.025),
            floor,
            "review_floor",
            0.005,
        )
        scene.world = tx.add("worlds", bpy.data.worlds.new(p["name"] + "_World"))
        scene.world.use_nodes = True
        scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = {
            "neutral": 0.12,
            "day": 0.35,
            "dusk": 0.035,
        }[p["lighting"]]
        scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (
            (0.34, 0.40, 0.5, 1) if p["lighting"] != "neutral" else (0.5, 0.5, 0.5, 1)
        )
        cameras = {}
        for label, direction in {
            "front": (0, -1, 0.08),
            "side": (1, 0, 0.08),
            "back": (0, 1, 0.08),
            "three_quarter": (0.75, -1, 0.55),
        }.items():
            data = tx.add("cameras", bpy.data.cameras.new(p["name"] + "_" + label))
            camera = tx.add("objects", bpy.data.objects.new(data.name, data))
            collection.objects.link(camera)
            camera.location = center + Vector(direction).normalized() * span * 2.8
            data.lens = 50
            data.clip_start = 0.01
            data.clip_end = max(span * 30, 100)
            _point_at(camera, center)
            cameras[label] = camera.name
        scene.camera = bpy.data.objects[cameras["three_quarter"]]
        light_recipe = {
            "neutral": ((1, 0.97, 0.92), (0.84, 0.9, 1), (1, 1, 1), (650, 350, 500)),
            "day": ((1, 0.88, 0.68), (0.65, 0.8, 1), (1, 0.95, 0.82), (1000, 300, 650)),
            "dusk": ((1, 0.57, 0.27), (0.34, 0.5, 1), (0.8, 0.87, 1), (420, 160, 350)),
        }[p["lighting"]]
        for index, (label, offset) in enumerate(
            (("Key", (-1.4, -1.8, 2.1)), ("Fill", (1.7, -1, 1)), ("Rim", (0.3, 1.5, 1.8)))
        ):
            data = tx.add("lights", bpy.data.lights.new(p["name"] + "_" + label, "AREA"))
            obj = tx.add("objects", bpy.data.objects.new(data.name, data))
            collection.objects.link(obj)
            obj.location = center + Vector(offset) * span
            data.energy = light_recipe[3][index] * span * span
            data.color = light_recipe[index]
            data.shape = "DISK"
            data.size = span * 1.3
            _point_at(obj, center)
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.exposure = 0
        scene.view_settings.gamma = 1
        scene.render.resolution_x = p["resolution"]
        scene.render.resolution_y = p["resolution"]
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1
        result.update(
            scene=scene.name,
            collection=collection.name,
            cameras=cameras,
            copies={source.name: copy.name for source, copy in copies.items()},
            renderer="CYCLES",
            samples=64,
            resolution=[p["resolution"], p["resolution"]],
            color_transform="AgX",
        )
        return result


def _lod_resources(objects, occurrences):
    """Resolve only explicit derivative metadata; names never imply LOD levels."""
    objects = sorted(objects, key=lambda obj: obj.name)
    by_name = {}
    for obj in objects:
        by_name.setdefault(obj.name, []).append(obj)
    groups, unresolved, grouped = {}, [], set()
    unsupported = []
    unknown_levels = 0
    for obj in objects:
        if obj.get("framewright_role") != "lod":
            continue
        if obj.type != "MESH":
            unsupported.append(
                {"object": obj.name, "source_type": obj.type, "reason": "derivative_not_mesh"}
            )
            continue
        raw_level = obj.get("framewright_lod_level")
        level = raw_level if type(raw_level) is int and 1 <= raw_level <= 8 else None
        unknown_levels += level is None
        source_name = obj.get("framewright_source")
        source_name = source_name if isinstance(source_name, str) and source_name else None
        observed = occurrences.get(obj.as_pointer(), {})
        row = {
            "object": obj.name,
            "level": level,
            "level_status": "declared" if level is not None else "missing_or_invalid_metadata",
            "source_triangles": sum(max(len(face.vertices) - 2, 0) for face in obj.data.polygons),
            "evaluated_occurrences": observed.get("occurrences", 0),
            "instance_occurrences": observed.get("instances", 0),
            "evaluated_triangles_total": observed.get("triangles", 0),
            "hidden_viewport": obj.hide_viewport,
            "hidden_render": obj.hide_render,
        }
        matches = by_name.get(source_name, [])
        if not source_name or len(matches) != 1 or matches[0] == obj or matches[0].type != "MESH":
            row.update(
                source=source_name,
                reason=(
                    "missing_or_invalid_source_metadata"
                    if not source_name
                    else "source_not_referenced"
                    if not matches
                    else "ambiguous_source"
                    if len(matches) != 1
                    else "self_reference"
                    if matches[0] == obj
                    else "source_not_mesh"
                ),
            )
            unresolved.append(row)
            continue
        source = matches[0]
        grouped.update((obj.as_pointer(), source.as_pointer()))
        group = groups.setdefault(
            source_name,
            {
                "source": source_name,
                "source_triangles": sum(
                    max(len(face.vertices) - 2, 0) for face in source.data.polygons
                ),
                "source_evaluated_occurrences": occurrences.get(source.as_pointer(), {}).get(
                    "occurrences", 0
                ),
                "derivatives": [],
            },
        )
        group["derivatives"].append(row)
    for group in groups.values():
        levels = [row["level"] for row in group["derivatives"] if row["level"] is not None]
        group["levels"] = sorted(set(levels))
        group["duplicate_levels"] = sorted(
            level for level in set(levels) if levels.count(level) > 1
        )
        group["metadata_coverage"] = (
            "complete_for_declared_derivatives"
            if len(levels) == len(group["derivatives"]) and not group["duplicate_levels"]
            else "incomplete_or_conflicting"
        )
    return {
        "metadata_fields": ["framewright_role", "framewright_source", "framewright_lod_level"],
        "groups": [groups[name] for name in sorted(groups)],
        "unresolved_derivatives": unresolved,
        "unsupported_derivatives": unsupported,
        "unknown_level_count": unknown_levels,
        "ungrouped_mesh_objects": [
            obj.name for obj in objects if obj.type == "MESH" and obj.as_pointer() not in grouped
        ],
        "limitations": [
            "Groups are explicit source-name associations, not inferred assets or runtime LOD switches",
            "Renamed/missing source names and legacy derivatives without level metadata need explicit repair",
            "No required level set or screen-size thresholds are assumed; metadata coverage is not visual or budget acceptance",
            "Hidden derivatives retain source counts but may have no evaluated occurrence in this view layer",
        ],
    }


_RESOURCE_CONVERTIBLE_TYPES = frozenset({"MESH", "CURVE", "SURFACE", "FONT", "META"})
_RESOURCE_GEOMETRY_TYPES = _RESOURCE_CONVERTIBLE_TYPES | {
    "CURVES",
    "POINTCLOUD",
    "VOLUME",
    "GREASEPENCIL",
}


def _resource_mesh_statistics(mesh):
    """Read only the temporary evaluated mesh; retain no evaluated geometry IDs."""
    mesh.calc_loop_triangles()
    return {
        "triangles": len(mesh.loop_triangles),
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "materials": tuple(material.original for material in mesh.materials if material),
    }


def _resource_evaluated_mesh(obj):
    # Cleanup also covers failed conversion/counting, not only successful reports.
    try:
        mesh = obj.to_mesh()
        return _resource_mesh_statistics(mesh) if mesh is not None else None
    finally:
        obj.to_mesh_clear()


def _resource_instance_path(instance):
    if not instance.is_instance:
        return ()
    path = tuple(instance.persistent_id)
    return path[: path.index(2147483647)] if 2147483647 in path else path


def _resource_component_key(instance, path=None):
    original = instance.object.original
    parent = instance.parent.original if instance.parent else original
    return (
        original.as_pointer(),
        parent.as_pointer(),
        _resource_instance_path(instance) if path is None else path,
    )


def _resource_conversion_occurrences(graph):
    """Map non-mesh geometry's implicit mesh projection to its authored occurrence.

    Blender emits a non-mesh geometry object and its evaluated MESH
    component separately. The component has an extra leading zero persistent-ID
    level. Only an exact source/parent/component-path match is collapsed; real
    Geometry Nodes or collection instances retain their independent occurrences.
    No transient depsgraph instance or evaluated geometry wrapper is retained.
    """
    converted = {}
    for instance in graph.object_instances:
        obj = instance.object
        if obj.type == "MESH" or obj.type not in _RESOURCE_GEOMETRY_TYPES:
            continue
        geometry = obj.evaluated_geometry()
        component = geometry.mesh
        if component is not None:
            key = _resource_component_key(instance, (0,) + _resource_instance_path(instance))
            converted[key] = bool(instance.is_instance)
    return converted


def scene_resources(params, context=None):
    """Report source/evaluated counts and documented estimates, without mutations."""
    context = _context(context)
    p = _params(params, {"scene_name": ""})
    if not isinstance(p["scene_name"], str):
        raise ValueError("scene_name must be a string")
    scene = bpy.data.scenes.get(p["scene_name"]) if p["scene_name"] else context.scene
    if scene is None:
        raise ValueError("Scene does not exist")
    _require_no_update_handlers()
    referenced = {
        obj.as_pointer(): obj for obj in scene.objects if obj.type in _RESOURCE_GEOMETRY_TYPES
    }
    converted = {
        key: obj
        for key, obj in referenced.items()
        if obj.type in _RESOURCE_CONVERTIBLE_TYPES and obj.type != "MESH"
    }
    evaluated_base, evaluated_total, instances, instance_slots = 0, 0, 0, 0
    cache, occurrences, unsupported, materials = {}, {}, {}, {}

    def add_materials(items):
        for material in items:
            if material:
                material = material.original
                materials[material.as_pointer()] = material

    def unsupported_component(original, obj, component, is_instance, reason):
        key = (original.as_pointer(), obj.type, component, reason)
        row = unsupported.setdefault(
            key,
            {
                "object": original.name,
                "source_type": original.type,
                "evaluated_type": obj.type,
                "component": component,
                "evaluated_occurrences": 0,
                "instance_occurrences": 0,
                "reason": reason,
            },
        )
        row["evaluated_occurrences"] += 1
        row["instance_occurrences"] += bool(is_instance)

    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        graph = bpy.context.evaluated_depsgraph_get()
        converted_occurrences = _resource_conversion_occurrences(graph)
        for instance in graph.object_instances:
            obj = instance.object
            original = obj.original
            if (
                obj.type not in _RESOURCE_GEOMETRY_TYPES
                and original.type not in _RESOURCE_GEOMETRY_TYPES
            ):
                continue
            referenced[original.as_pointer()] = original
            add_materials(slot.material for slot in obj.material_slots)
            geometry = obj.evaluated_geometry()
            for component in ("curves", "pointcloud", "volume", "grease_pencil"):
                data = getattr(geometry, component)
                if data is not None:
                    add_materials(getattr(data, "materials", ()))
                    unsupported_component(
                        original,
                        obj,
                        component,
                        instance.is_instance,
                        "non_mesh_component_not_measured",
                    )
            # Count mesh components once, not both a legacy source occurrence
            # and its synthetic MESH projection in this same depsgraph stream.
            if obj.type != "MESH":
                if geometry.mesh is None and obj.type in _RESOURCE_CONVERTIBLE_TYPES:
                    unsupported_component(
                        original,
                        obj,
                        obj.type.lower(),
                        instance.is_instance,
                        "no_evaluated_mesh_component",
                    )
                continue
            key = (original.as_pointer(), obj.type, obj.data.as_pointer() if obj.data else 0)
            if key not in cache:
                cache[key] = _resource_evaluated_mesh(obj)
            statistics = cache[key]
            if statistics is None:
                unsupported_component(
                    original, obj, obj.type, instance.is_instance, "no_evaluated_mesh_conversion"
                )
                continue
            if original.type != "MESH":
                converted[original.as_pointer()] = original
            add_materials(statistics["materials"])
            triangles = statistics["triangles"]
            is_instance = converted_occurrences.get(
                _resource_component_key(instance),
                bool(instance.is_instance),
            )
            observed = occurrences.setdefault(
                original.as_pointer(),
                {
                    "occurrences": 0,
                    "instances": 0,
                    "triangles": 0,
                    "base_triangles": 0,
                    "vertices": 0,
                    "edges": 0,
                },
            )
            observed["occurrences"] += 1
            observed["triangles"] += triangles
            observed["vertices"] += statistics["vertices"]
            observed["edges"] += statistics["edges"]
            evaluated_total += triangles
            instance_slots += len(obj.material_slots)
            if is_instance:
                instances += 1
                observed["instances"] += 1
            else:
                evaluated_base += triangles
                observed["base_triangles"] += triangles
    mesh_objects = [obj for obj in referenced.values() if obj.type == "MESH"]
    meshes = {obj.data.as_pointer(): obj.data for obj in mesh_objects}
    add_materials(
        slot.material
        for obj in (*scene.objects, *referenced.values())
        for slot in obj.material_slots
    )
    breakdown = {}
    for kind in sorted({obj.type for obj in referenced.values()}):
        sources = [obj for obj in referenced.values() if obj.type == kind]
        observed = [occurrences.get(obj.as_pointer(), {}) for obj in sources]
        pointers = {obj.as_pointer() for obj in sources}
        breakdown[kind] = {
            "referenced_objects": len(sources),
            "unique_source_datablocks": len({obj.data.as_pointer() for obj in sources if obj.data}),
            "evaluated_unique_geometry": sum(
                key[0] in pointers and value is not None for key, value in cache.items()
            ),
            "evaluated_occurrences": sum(row.get("occurrences", 0) for row in observed),
            "instance_occurrences": sum(row.get("instances", 0) for row in observed),
            "evaluated_triangles_objects": sum(row.get("base_triangles", 0) for row in observed),
            "evaluated_triangles_with_instances": sum(row.get("triangles", 0) for row in observed),
            "evaluated_vertices_with_instances": sum(row.get("vertices", 0) for row in observed),
            "evaluated_edges_with_instances": sum(row.get("edges", 0) for row in observed),
        }
    trees = [material.node_tree for material in materials.values() if material.node_tree]
    if scene.world and scene.world.node_tree:
        trees.append(scene.world.node_tree)
    images, visited = {}, set()
    while trees:
        tree = trees.pop()
        if tree.as_pointer() in visited:
            continue
        visited.add(tree.as_pointer())
        for node in tree.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                images[image.as_pointer()] = image
            nested = getattr(node, "node_tree", None)
            if nested is not None:
                trees.append(nested)
    texture_bytes = sum(
        image.size[0] * image.size[1] * max(image.channels, 1) * (4 if image.is_float else 1)
        for image in images.values()
    )
    return {
        "scene": scene.name,
        "objects": len(scene.objects),
        "mesh_objects": sum(obj.type == "MESH" for obj in scene.objects),
        "referenced_mesh_objects": len(mesh_objects),
        "unique_mesh_datablocks": len(meshes),
        "referenced_converted_source_objects": len(converted),
        "unique_converted_source_datablocks": len(
            {obj.data.as_pointer() for obj in converted.values() if obj.data}
        ),
        "converted_source_objects": [
            {
                "object": obj.name,
                "source_type": obj.type,
                "source_datablock": obj.data.name if obj.data else None,
            }
            for obj in sorted(converted.values(), key=lambda obj: obj.name)
        ],
        "source_triangles_unique": sum(
            max(len(face.vertices) - 2, 0) for mesh in meshes.values() for face in mesh.polygons
        ),
        "evaluated_unique_geometry": sum(value is not None for value in cache.values()),
        "evaluated_triangles_objects": evaluated_base,
        "evaluated_triangles_with_instances": evaluated_total,
        "instance_occurrences": instances,
        "material_slots": sum(len(obj.material_slots) for obj in scene.objects),
        "material_slots_evaluated_occurrences": instance_slots,
        "unique_materials": len(materials),
        "textures": len(images),
        "texture_decoded_bytes_estimate": texture_bytes,
        "texture_with_mips_bytes_estimate": math.ceil(texture_bytes * 4 / 3),
        "geometry_by_source_type": breakdown,
        "unsupported_geometry_outputs": sorted(
            unsupported.values(),
            key=lambda row: (row["object"], row["evaluated_type"], row["component"], row["reason"]),
        ),
        "geometry_accounting_scope": "evaluated_mesh_components",
        "lod": _lod_resources(referenced.values(), occurrences),
        "limitations": [
            "Evaluated triangle totals include generated meshes from curves, text, surfaces, metaballs and mesh instances",
            "Non-mesh geometry's implicit mesh projection is counted once and classified by its source occurrence; real collection/Geometry Nodes instances remain separate",
            "Original mesh-source counts and LOD metadata stay mesh-only; converted-source counts also retain hidden supported sources",
            "Non-mesh GeometrySet components are explicitly unmeasured; unsupported rows are observations, not additive unique geometry",
            "A mixed non-mesh component can also appear as a separate evaluated instance; do not sum unsupported observations as physical geometry",
            "Empty meshes and wire-only converted geometry can have zero triangles; per-source-type vertices/edges count evaluated occurrences",
            "Evaluated unique geometry counts source-object/evaluated-data pairs, not deduplicated GPU allocations",
            "Material/image counts cover referenced original/evaluated slots and nodes; unused references can be included",
            "Evaluated geometry uses the first view layer and current frame; hidden/excluded content may differ",
            "Source triangle count assumes ordinary n-gon triangulation",
            "Unique source meshes/materials include collection-instance references; direct scene mesh-object count stays separate",
            "Texture memory is a decoded base-image estimate, not GPU residency; tiled/sequence/multiview data and compression are not fully accounted",
            "Material slots are not native engine draw calls",
            "These counts do not establish performance or visual acceptance",
        ],
    }
