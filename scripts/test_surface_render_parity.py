"""Rendered normal-bake and cold GLB/FBX material evidence, with corrupt controls.

Run in isolated factory-startup Blender. The default writes a new artifact run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from framewright import baking, interchange  # noqa: E402

RESOLUTION = 128
SAMPLES = 48


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def clear_factory_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def material(name, color=(0.35, 0.35, 0.35, 1), roughness=0.45, metallic=0.0):
    result = bpy.data.materials.new(name)
    shader = next(node for node in result.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    return result


def wave_fixture():
    mesh = bpy.data.meshes.new("WaveLowMesh")
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name="WaveUV")
    for index, point in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[index].uv = point
    low = bpy.data.objects.new("WaveLow", mesh)
    bpy.context.scene.collection.objects.link(low)
    vertices, faces = [], []
    divisions = 48
    for y in range(divisions + 1):
        for x in range(divisions + 1):
            px, py = -1 + 2 * x / divisions, -1 + 2 * y / divisions
            height = 0.02 + 0.06 * (math.sin(px * 5) * math.cos(py * 4) + 1) / 2
            vertices.append((px, py, height))
    for y in range(divisions):
        for x in range(divisions):
            index = y * (divisions + 1) + x
            faces.append((index, index + 1, index + divisions + 2, index + divisions + 1))
    high_mesh = bpy.data.meshes.new("WaveHighMesh")
    high_mesh.from_pydata(vertices, [], faces)
    high_mesh.update()
    for polygon in high_mesh.polygons:
        polygon.use_smooth = True
    high = bpy.data.objects.new("WaveHigh", high_mesh)
    bpy.context.scene.collection.objects.link(high)
    shared = material("WaveSurface")
    high.data.materials.append(shared)
    low.data.materials.append(shared)
    bpy.context.view_layer.update()
    return high, low


def pbr_fixture(folder):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
    sphere = bpy.context.active_object
    sphere.name = "PortablePBRSphere"
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True
    surface = material("PortablePBR", roughness=0.28, metallic=0.65)
    sphere.data.materials.append(surface)
    image = bpy.data.images.new("PortablePBRColor", 64, 64, alpha=True)
    pixels = []
    for y in range(64):
        for x in range(64):
            color = (0.65, 0.12, 0.04, 1) if (x // 8 + y // 16) % 2 else (0.04, 0.3, 0.65, 1)
            pixels.extend(color)
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(folder / "source_color.png")
    image.file_format = "PNG"
    image.save()
    # Compare a real file-backed portable image, avoiding generated-buffer ambiguity.
    loaded = bpy.data.images.load(image.filepath_raw, check_existing=False)
    loaded.name = "PortablePBRFileColor"
    loaded.pack()
    bpy.data.images.remove(image)
    texture = surface.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = loaded
    shader = next(node for node in surface.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    surface.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    bpy.context.view_layer.update()
    return sphere


def source_hash(objects):
    records = []
    for obj in objects:
        materials = []
        for slot in obj.material_slots:
            surface = slot.material
            nodes = []
            for node in surface.node_tree.nodes:
                inputs = []
                for socket in node.inputs:
                    if not hasattr(socket, "default_value"):
                        continue
                    value = socket.default_value
                    if not isinstance(value, (str, int, float, bool)):
                        try:
                            value = list(value)
                        except TypeError:
                            continue
                    inputs.append((socket.name, value))
                node_data = {"name": node.name, "type": node.type, "inputs": inputs}
                if node.type == "TEX_IMAGE" and node.image:
                    pixels = array("f", [0]) * len(node.image.pixels)
                    node.image.pixels.foreach_get(pixels)
                    node_data["image"] = {
                        "name": node.image.name,
                        "space": node.image.colorspace_settings.name,
                        "pixels": hashlib.sha256(pixels.tobytes()).hexdigest(),
                    }
                nodes.append(node_data)
            materials.append(
                {
                    "name": surface.name,
                    "nodes": nodes,
                    "links": [
                        (
                            link.from_node.name,
                            link.from_socket.name,
                            link.to_node.name,
                            link.to_socket.name,
                        )
                        for link in surface.node_tree.links
                    ],
                }
            )
        records.append(
            {
                "name": obj.name,
                "matrix": [list(row) for row in obj.matrix_world],
                "vertices": [list(vertex.co) for vertex in obj.data.vertices],
                "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
                "smooth": [polygon.use_smooth for polygon in obj.data.polygons],
                "uv": [[list(item.uv) for item in layer.data] for layer in obj.data.uv_layers],
                "materials": materials,
            }
        )
    return hashlib.sha256(json.dumps(records, sort_keys=True, allow_nan=False).encode()).hexdigest()


def png_pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(values)
        return values
    finally:
        bpy.data.images.remove(image)


def render(objects, path, corrupt=None):
    original = bpy.context.window.scene
    stage = bpy.data.scenes.new("RenderParityStage")
    created = []
    try:
        bpy.context.window.scene = stage
        stage.render.engine = "CYCLES"
        stage.cycles.device = "CPU"
        stage.cycles.samples = SAMPLES
        stage.cycles.use_adaptive_sampling = False
        stage.cycles.use_denoising = False
        stage.cycles.seed = 0
        stage.render.resolution_x = stage.render.resolution_y = RESOLUTION
        stage.render.resolution_percentage = 100
        stage.render.image_settings.file_format = "PNG"
        stage.render.image_settings.color_mode = "RGBA"
        stage.render.image_settings.color_depth = "8"
        stage.view_settings.view_transform = "Standard"
        stage.view_settings.look = "None"
        stage.view_settings.exposure = 0
        stage.view_settings.gamma = 1
        stage.render.film_transparent = False
        world = bpy.data.worlds.new("ParityWorld")
        created.append((bpy.data.worlds, world))
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.12, 0.12, 0.12, 1)
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3
        stage.world = world
        for obj in objects:
            copy = obj.copy()
            copy.data = obj.data.copy()
            created.extend(((bpy.data.meshes, copy.data), (bpy.data.objects, copy)))
            copy.parent = None
            copy.matrix_world = obj.matrix_world.copy()
            copy.hide_render = False
            copy.hide_viewport = False
            stage.collection.objects.link(copy)
            for index, slot in enumerate(copy.material_slots):
                surface = slot.material.copy()
                created.append((bpy.data.materials, surface))
                copy.data.materials[index] = surface
                shader = next(
                    node for node in surface.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
                )
                if corrupt == "normal_removed":
                    for link in list(shader.inputs["Normal"].links):
                        surface.node_tree.links.remove(link)
                elif corrupt == "wrong_color":
                    for link in list(shader.inputs["Base Color"].links):
                        surface.node_tree.links.remove(link)
                    shader.inputs["Base Color"].default_value = (0.015, 0.8, 0.01, 1)
            copy.hide_set(False)
        camera_data = bpy.data.cameras.new("ParityCamera")
        camera = bpy.data.objects.new("ParityCamera", camera_data)
        created.extend(((bpy.data.cameras, camera_data), (bpy.data.objects, camera)))
        stage.collection.objects.link(camera)
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = 2.4
        camera.location = (0, 0, 4)
        camera.rotation_euler = (0, 0, 0)
        stage.camera = camera
        light_data = bpy.data.lights.new("ParitySun", "SUN")
        light_data.energy = 2.0
        light_data.angle = 0.05
        light = bpy.data.objects.new("ParitySun", light_data)
        created.extend(((bpy.data.lights, light_data), (bpy.data.objects, light)))
        stage.collection.objects.link(light)
        light.rotation_euler = Vector((-3, 4, -6)).to_track_quat("-Z", "Y").to_euler()
        stage.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        require(path.is_file(), "Render output is missing")
        return png_pixels(path)
    finally:
        bpy.context.window.scene = original
        object_ids = [
            (store, item) for store, item in created if isinstance(item, bpy.types.Object)
        ]
        other_ids = [
            (store, item) for store, item in created if not isinstance(item, bpy.types.Object)
        ]
        for store, item in reversed(object_ids):
            store.remove(item, do_unlink=True)
        bpy.data.scenes.remove(stage)
        for store, item in reversed(other_ids):
            store.remove(item)


def metrics(reference, actual):
    require(
        len(reference) == len(actual) == RESOLUTION * RESOLUTION * 4, "Unexpected image dimensions"
    )
    differences = []
    # Interior ROI avoids pretending the flat low mesh reproduces the high silhouette.
    for y in range(int(RESOLUTION * 0.2), int(RESOLUTION * 0.8)):
        for x in range(int(RESOLUTION * 0.2), int(RESOLUTION * 0.8)):
            offset = (y * RESOLUTION + x) * 4
            differences.extend(abs(reference[offset + c] - actual[offset + c]) for c in range(3))
    ordered = sorted(differences)
    return {
        "mae": sum(differences) / len(differences),
        "p95": ordered[int(len(ordered) * 0.95)],
        "maximum": ordered[-1],
        "rgb_values": len(differences),
        "roi": [0.2, 0.2, 0.8, 0.8],
    }


def material_values(objects):
    result = []
    for obj in objects:
        for slot in obj.material_slots:
            for node in slot.material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    result.append(
                        {
                            "material": slot.material.name,
                            "roughness": node.inputs["Roughness"].default_value,
                            "metallic": node.inputs["Metallic"].default_value,
                            "base_color_linked": bool(node.inputs["Base Color"].links),
                        }
                    )
    return result


def assert_normal_parity(measured, corrupt_control):
    require(
        corrupt_control["mae"] > 0.003,
        "Corrupt normal control did not create a measurable shading difference",
    )
    tolerance = min(0.01, corrupt_control["mae"] * 0.65)
    require(
        measured["mae"] < tolerance,
        f"Baked normal shading exceeded calibrated fixture MAE ceiling {tolerance}: {measured}",
    )
    return tolerance


def assert_material_parity(measured, corrupt_control):
    require(corrupt_control["mae"] > 0.05, "Corrupt color control was not detected")
    tolerance = min(0.03, corrupt_control["mae"] * 0.2)
    require(
        measured["mae"] <= tolerance,
        f"Portable material exceeded calibrated fixture MAE ceiling {tolerance}: {measured}",
    )
    return tolerance


def require_control_rejected(check, measured):
    try:
        check(measured, measured)
    except AssertionError:
        return
    raise AssertionError("Deliberately corrupted control incorrectly passed the parity assertion")


def cold_import(path, folder, format_name):
    clear_factory_scene()
    if format_name == "GLB":
        outcome = bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        outcome = bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    require(outcome == {"FINISHED"}, "Cold import did not finish")
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    require(bool(objects), "Cold import produced no mesh")
    bpy.context.view_layer.update()
    render(objects, folder / f"pbr_{format_name.lower()}_cold.png")
    (folder / f"{format_name.lower()}_material.json").write_text(
        json.dumps(material_values(objects), indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-import", type=Path)
    parser.add_argument("--format", choices=("GLB", "FBX"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--inject-corruption", choices=("normal", "color"), help="Negative test: must exit nonzero"
    )
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    if args.cold_import:
        cold_import(args.cold_import, args.output, args.format)
        return
    folder = args.output or ROOT / "artifacts" / "surface-render-parity" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    clear_factory_scene()
    high, low = wave_fixture()
    before = source_hash([high, low])
    baked = baking.bake_normal(
        {"high_object": high.name, "low_object": low.name, "resolution": 128, "dry_run": False}
    )
    derivative = bpy.data.objects[baked["derivative"]]
    normal_image = bpy.data.images[baked["image"]]
    normal_image.filepath_raw = str(folder / "baked_normal.exr")
    normal_image.save()
    high_pixels = render([high], folder / "wave_high.png")
    low_pixels = render([derivative], folder / "wave_baked_normal.png")
    corrupt_pixels = render(
        [derivative], folder / "wave_corrupt_normal_removed.png", corrupt="normal_removed"
    )
    bake_metrics = metrics(high_pixels, low_pixels)
    bad_normal_metrics = metrics(high_pixels, corrupt_pixels)
    require_control_rejected(assert_normal_parity, bad_normal_metrics)
    normal_tolerance = assert_normal_parity(
        bad_normal_metrics if args.inject_corruption == "normal" else bake_metrics,
        bad_normal_metrics,
    )
    require(
        source_hash([high, low]) == before, "Bake/render modified source geometry, UVs or materials"
    )
    sphere = pbr_fixture(folder)
    sphere_hash = source_hash([sphere])
    source_pixels = render([sphere], folder / "pbr_source.png")
    bad_color = render([sphere], folder / "pbr_corrupt_color.png", corrupt="wrong_color")
    color_control = metrics(source_pixels, bad_color)
    require(color_control["mae"] > 0.05, "Corrupt color control was not detected")
    require_control_rejected(assert_material_parity, color_control)
    material_report = {}
    for format_name in ("GLB", "FBX"):
        receipt = interchange.export_asset(
            {
                "object_names": [sphere.name],
                "directory": str(folder),
                "filename": "portable_" + format_name.lower(),
                "format": format_name,
                "include_animation": False,
                "dry_run": False,
            }
        )
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold-import",
            receipt["output_path"],
            "--format",
            format_name,
            "--output",
            str(folder),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        (folder / f"{format_name.lower()}_cold.log").write_text(
            completed.stdout + "\n" + completed.stderr, encoding="utf-8"
        )
        require(
            completed.returncode == 0,
            f"Cold {format_name} render failed:\n{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}",
        )
        cold_pixels = png_pixels(folder / f"pbr_{format_name.lower()}_cold.png")
        measured = metrics(source_pixels, cold_pixels)
        tolerance = min(0.03, color_control["mae"] * 0.2)
        passes = measured["mae"] <= tolerance
        assert_material_parity(
            color_control if args.inject_corruption == "color" else measured, color_control
        )
        material_report[format_name] = {
            "metrics": measured,
            "mae_tolerance": tolerance,
            "status": "within_fixture_tolerance" if passes else "difference_detected",
            "material_values": json.loads(
                (folder / f"{format_name.lower()}_material.json").read_text(encoding="utf-8")
            ),
        }
    require(source_hash([sphere]) == sphere_hash, "Export/render changed the source PBR fixture")
    report = {
        "schema_version": "1.0",
        "blender": bpy.app.version_string,
        "resolution": RESOLUTION,
        "samples": SAMPLES,
        "renderer": "Cycles CPU; fixed seed 0; adaptive sampling and denoising off",
        "color_management": "Standard view, None look, exposure 0, gamma 1; saved RGBA8 PNG",
        "normal_bake": {
            "metrics": bake_metrics,
            "mae_tolerance": normal_tolerance,
            "corrupt_control": bad_normal_metrics,
            "corrupt_control_rejected": True,
            "high_triangles": 48 * 48 * 2,
            "low_triangles": 2,
            "normal_map": "baked_normal.exr",
            "source_sha256": before,
            "source_preserved": True,
        },
        "material_roundtrip": material_report,
        "corrupt_color_control": color_control,
        "corrupt_color_control_rejected": True,
        "pbr_source_sha256": sphere_hash,
        "pbr_source_preserved": True,
        "measurement": "RGB differences decoded from saved 8-bit PNG files; fixed interior ROI",
        "limits": [
            "Fixture tolerances do not certify arbitrary materials or AAA quality",
            "Normal-map shading does not restore high-mesh silhouette or parallax",
            "Both formats must meet this fixture tolerance; other material graphs remain unverified",
            "No texture compression, mip, temporal or Unreal rendering acceptance",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("FRAMEWRIGHT_SURFACE_RENDER_PARITY_OK " + str(folder))


if __name__ == "__main__":
    main()
