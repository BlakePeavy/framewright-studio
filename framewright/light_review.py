"""Editable interior/glass reference fixture, not automatic user-asset lighting."""

from __future__ import annotations

import bpy
from mathutils import Vector

from .production_assets import _box, _context, _material, _number, _params, _Transaction

OWNER = "light_review"


def create_interior_fixture(params, context=None):
    """Create an independent benchmark scene; rendering and saving are separate actions."""
    _context(context)
    p = _params(
        params,
        {
            "name": "FW_InteriorGlass",
            "dry_run": True,
            "resolution": 512,
            "samples": 64,
            "glass_thickness": 0.08,
            "ior": 1.5,
            "roughness": 0.03,
            "window_power": 1800,
            "fill_power": 60,
            "exposure": 0,
            "max_pixel_samples": 16777216,
            "max_render_memory_mb": 512,
        },
    )
    for key, lower, upper in (
        ("resolution", 64, 8192),
        ("samples", 1, 512),
        ("max_pixel_samples", 4096, 34359738368),
        ("max_render_memory_mb", 16, 16384),
    ):
        if type(p[key]) is not int or not lower <= p[key] <= upper:
            raise ValueError(f"{key} must be an integer from {lower} to {upper}")
    for key, lower, upper in (
        ("glass_thickness", 0.005, 0.25),
        ("ior", 1, 2.5),
        ("roughness", 0, 0.3),
        ("window_power", 0, 20000),
        ("fill_power", 0, 5000),
        ("exposure", -8, 8),
    ):
        p[key] = _number(p[key], lower, upper, key)
    pixels = p["resolution"] ** 2
    budget = {
        "pixel_samples": pixels * p["samples"],
        "max_pixel_samples": p["max_pixel_samples"],
        "estimated_render_buffer_bytes": pixels * 64,
        "max_render_memory_mb": p["max_render_memory_mb"],
        "scope": "Admission estimates, not runtime caps; 64 bytes/pixel buffer allowance excludes geometry, renderer temporaries, devices and later scene edits",
    }
    if (
        budget["pixel_samples"] > p["max_pixel_samples"]
        or budget["estimated_render_buffer_bytes"] > p["max_render_memory_mb"] * 1024**2
    ):
        raise ValueError("Interior fixture exceeds explicit render admission budget")
    result = {
        "schema_version": "1.0",
        "dry_run": p["dry_run"],
        "kind": "interior_glass_reference",
        "parameters": p,
        "budget": budget,
        "units": "metres",
        "visual_acceptance": False,
        "native_glass_parity": False,
        "limitations": [
            "Explicit editable reference fixture only; does not automatically light arbitrary assets",
            "No render or file writes are performed by scene creation",
            "Cycles thick-surface transmission reference, no volume absorption, spectral/caustic or photographic calibration",
            "Admission estimates are not memory/time caps after manual editing",
            "Apply refuses registered frame/depsgraph handlers before allocation; nonmutating preview remains available",
            "Physical display, production lighting, native glass and artistic acceptance remain independent",
        ],
    }
    if p["dry_run"]:
        return result
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
            "Interior fixture creation refuses registered frame/depsgraph handlers; preview remains available"
        )
    with _Transaction() as tx:
        scene = tx.add("scenes", bpy.data.scenes.new(p["name"]))
        collection = tx.new_collection(p["name"] + "_Contents", scene.collection)
        neutral = _material(tx, p["name"] + "_Plaster", (0.55, 0.53, 0.49), 0.8)
        floor_mat = _material(tx, p["name"] + "_Floor", (0.32, 0.32, 0.32), 0.65)
        frame_mat = _material(tx, p["name"] + "_Frame", (0.07, 0.08, 0.09), 0.5)
        glass_mat = _material(tx, p["name"] + "_Glass", (1, 1, 1), p["roughness"])
        shader = glass_mat.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Transmission Weight"].default_value = 1
        shader.inputs["IOR"].default_value = p["ior"]
        blue = _material(tx, p["name"] + "_TargetBlue", (0.02, 0.11, 0.5), 0.75)
        cream = _material(tx, p["name"] + "_TargetCream", (0.8, 0.7, 0.25), 0.75)
        block_mat = _material(tx, p["name"] + "_ContactOchre", (0.45, 0.16, 0.035), 0.6)
        objects = {}

        def box(role, size, position, material, bevel=0.002):
            obj = _box(tx, p["name"] + "_" + role, size, position, material, role, bevel)
            objects[role] = obj.name
            return obj

        box("floor", (6, 5, 0.12), (0, 0, -0.06), floor_mat)
        box("back_wall", (6, 0.15, 3.2), (0, 2.35, 1.6), neutral)
        box("right_wall", (0.15, 5, 3.2), (2.95, 0, 1.6), neutral)
        # Four pieces create an actual opening without boolean/context operators.
        box("window_wall_front", (0.15, 1.2, 3.2), (-2.95, -1.9, 1.6), neutral)
        box("window_wall_back", (0.15, 1.2, 3.2), (-2.95, 1.9, 1.6), neutral)
        box("window_wall_sill", (0.15, 2.6, 0.65), (-2.95, 0, 0.325), neutral)
        box("window_wall_lintel", (0.15, 2.6, 0.65), (-2.95, 0, 2.875), neutral)
        box("ceiling", (6, 5, 0.12), (0, 0, 3.26), neutral)
        for y in (-1.3, 1.3):
            box("window_jamb_" + str(y), (0.20, 0.07, 1.9), (-2.95, y, 1.6), frame_mat)
        glass = box("glass", (1.6, p["glass_thickness"], 1.9), (0, -0.15, 0.95), glass_mat, 0.0005)
        block = box("contact_block", (0.45, 0.45, 0.5), (1.35, -0.65, 0.25), block_mat, 0.015)
        for row in range(8):
            for column in range(8):
                box(
                    f"target_{row}_{column}",
                    (0.22, 0.025, 0.22),
                    (-0.77 + column * 0.22, 0.65, 0.25 + row * 0.22),
                    blue if (row + column) % 2 else cream,
                    0,
                )
        world = tx.add("worlds", bpy.data.worlds.new(p["name"] + "_World"))
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.15, 0.18, 0.24, 1)
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.03
        scene.world = world
        lights = {}
        for name, position, target, power, size, color in (
            (
                "window_key",
                (-3.3, -0.35, 2.2),
                (0, 0.3, 0.8),
                p["window_power"],
                1.8,
                (1, 0.95, 0.87),
            ),
            ("interior_fill", (1.5, -2.2, 2.5), (0, 0.5, 1), p["fill_power"], 2.0, (0.78, 0.87, 1)),
        ):
            data = tx.add("lights", bpy.data.lights.new(p["name"] + "_" + name, "AREA"))
            obj = tx.add("objects", bpy.data.objects.new(data.name, data))
            collection.objects.link(obj)
            obj.location = position
            obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
            data.energy, data.size, data.color = power, size, color
            data.shape = "DISK"
            lights[name] = obj.name
        cameras = {}
        for name, position, target in (
            ("front", (0, -5.2, 1.65), (0, 0.15, 1.05)),
            ("three_quarter", (2.2, -5.2, 1.7), (0.1, 0.2, 1.05)),
        ):
            data = tx.add("cameras", bpy.data.cameras.new(p["name"] + "_" + name))
            obj = tx.add("objects", bpy.data.objects.new(data.name, data))
            collection.objects.link(obj)
            obj.location = position
            obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
            data.lens = 43
            data.clip_start, data.clip_end = 0.01, 100
            cameras[name] = obj.name
        scene.camera = bpy.data.objects[cameras["three_quarter"]]
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = p["samples"]
        scene.cycles.seed = 0
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.use_denoising = False
        scene.cycles.max_bounces = 16
        scene.cycles.transmission_bounces = 12
        scene.cycles.caustics_reflective = False
        scene.cycles.caustics_refractive = False
        scene.render.resolution_x = scene.render.resolution_y = p["resolution"]
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        scene.render.dither_intensity = 0
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = p["exposure"]
        scene.view_settings.gamma = 1
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1
        for _kind, item in tx.created:
            item["framewright_owner"] = OWNER
        for layer in scene.view_layers:
            layer.update()
        result.update(
            scene=scene.name,
            collection=collection.name,
            objects=objects,
            cameras=cameras,
            lights=lights,
            glass_material=glass_mat.name,
            object_count=len(scene.objects),
            contact={
                "glass_bottom_to_floor": min(
                    (glass.matrix_world @ Vector(point)).z for point in glass.bound_box
                ),
                "block_bottom_to_floor": min(
                    (block.matrix_world @ Vector(point)).z for point in block.bound_box
                ),
            },
            renderer="CYCLES",
            transmission_bounces=12,
            color_transform="AgX",
        )
        return result
