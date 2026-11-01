"""Real standalone PBR ownership, node and failure checks in background Blender."""

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from test_materials import png  # noqa: E402

from framewright import interchange, materials  # noqa: E402


class PBRMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "source.png"
        self.path.write_bytes(png())
        self.before_ids = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)}
            for kind in ("objects", "meshes", "images", "materials")
        }

    def tearDown(self):
        for kind in ("objects", "meshes", "materials", "images"):
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.before_ids[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)
        self.temp.cleanup()

    def params(self, **changes):
        return {
            "base_color_path": str(self.path),
            "roughness_path": str(self.path),
            "metallic_path": str(self.path),
            "normal_path": str(self.path),
            **changes,
        }

    def test_preview_does_not_allocate_blender_data(self):
        before = (len(bpy.data.images), len(bpy.data.materials))
        result = materials.create_pbr_material(self.params())
        self.assertTrue(result["dry_run"])
        self.assertEqual(before, (len(bpy.data.images), len(bpy.data.materials)))

    def test_applied_material_owns_images_and_preserves_shared_source(self):
        existing = bpy.data.images.load(str(self.path), check_existing=False)
        existing.colorspace_settings.name = "sRGB"
        before_objects = {
            obj.session_uid: [slot.material for slot in obj.material_slots]
            for obj in bpy.data.objects
        }
        result = materials.create_pbr_material(self.params(dry_run=False))
        material = bpy.data.materials[result["material"]]
        self.assertTrue(material.use_fake_user)
        self.assertEqual(existing.colorspace_settings.name, "sRGB")
        nodes = material.node_tree.nodes
        textures = [node for node in nodes if node.type == "TEX_IMAGE"]
        self.assertEqual(len(textures), 4)
        self.assertEqual(len({node.image.session_uid for node in textures}), 4)
        self.assertNotIn(existing.session_uid, {node.image.session_uid for node in textures})
        normal = next(node for node in nodes if node.type == "NORMAL_MAP")
        self.assertEqual(normal.space, "TANGENT")
        shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
        self.assertTrue(shader.inputs["Base Color"].is_linked)
        self.assertTrue(shader.inputs["Roughness"].is_linked)
        self.assertTrue(shader.inputs["Metallic"].is_linked)
        self.assertEqual(shader.inputs["Normal"].links[0].from_node, normal)
        self.assertEqual(
            before_objects,
            {
                obj.session_uid: [slot.material for slot in obj.material_slots]
                for obj in bpy.data.objects
            },
        )
        self.assertEqual(self.path.read_bytes(), png())

    def test_partial_loading_failure_removes_only_owned_data(self):
        existing = bpy.data.images.load(str(self.path), check_existing=False)
        before = (len(bpy.data.images), len(bpy.data.materials))
        original = materials._load_image
        calls = []

        def fail_later(path):
            calls.append(path)
            if len(calls) == 2:
                raise RuntimeError("Injected image decode failure")
            return original(path)

        with patch.object(materials, "_load_image", side_effect=fail_later):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                materials.create_pbr_material(self.params(dry_run=False))
        self.assertEqual(before, (len(bpy.data.images), len(bpy.data.materials)))
        self.assertTrue(any(image == existing for image in bpy.data.images))

    def test_real_jpeg_load_and_unique_material_names(self):
        image = bpy.data.images.new("JPEGFixture", width=2, height=2)
        image.pixels[:] = [1, 0.2, 0.1, 1] * 4
        image.filepath_raw = str(self.root / "source.jpg")
        image.file_format = "JPEG"
        image.save()
        results = [
            materials.create_pbr_material({"base_color_path": image.filepath_raw, "dry_run": False})
            for _ in range(2)
        ]
        self.assertNotEqual(results[0]["material"], results[1]["material"])
        self.assertEqual(results[0]["maps"][0]["format"], "JPEG")

    def test_invalid_full_image_decode_cleans_created_data(self):
        self.path.write_bytes(png(10, 10))  # Valid dimensions, deliberately empty IDAT.
        before = (len(bpy.data.images), len(bpy.data.materials))
        with self.assertRaises((RuntimeError, ValueError)):
            materials.create_pbr_material(self.params(dry_run=False))
        self.assertEqual(before, (len(bpy.data.images), len(bpy.data.materials)))

    def test_changed_file_during_load_is_rejected_and_cleaned(self):
        before = (len(bpy.data.images), len(bpy.data.materials))
        original = materials._load_image

        def replace_after_load(path):
            image = original(path)
            self.path.write_bytes(png(pixel=(255, 0, 0, 255)))
            return image

        with patch.object(materials, "_load_image", side_effect=replace_after_load):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                materials.create_pbr_material(self.params(dry_run=False))
        self.assertEqual(before, (len(bpy.data.images), len(bpy.data.materials)))

    def test_glb_contains_explicit_pbr_texture_bindings(self):
        result = materials.create_pbr_material(self.params(dry_run=False))
        material = bpy.data.materials[result["material"]]
        mesh = bpy.data.meshes.new("PBRExportMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        layer = mesh.uv_layers.new()
        for loop, uv in zip(layer.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
            loop.uv = uv
        mesh.materials.append(material)
        obj = bpy.data.objects.new("PBRExportFixture", mesh)
        bpy.context.scene.collection.objects.link(obj)
        export = interchange.export_asset(
            {"object_names": [obj.name], "directory": str(self.root), "dry_run": False}
        )
        data = Path(export["output_path"]).read_bytes()
        json_length, chunk_type = struct.unpack_from("<II", data, 12)
        self.assertEqual(chunk_type, 0x4E4F534A)
        gltf = json.loads(data[20 : 20 + json_length])
        exported = gltf["materials"][0]
        self.assertIn("baseColorTexture", exported["pbrMetallicRoughness"])
        self.assertIn("metallicRoughnessTexture", exported["pbrMetallicRoughness"])
        self.assertIn("normalTexture", exported)
        for texture in (
            exported["pbrMetallicRoughness"]["baseColorTexture"],
            exported["pbrMetallicRoughness"]["metallicRoughnessTexture"],
            exported["normalTexture"],
        ):
            image = gltf["images"][gltf["textures"][texture["index"]]["source"]]
            self.assertIn("bufferView", image)
            self.assertGreater(gltf["bufferViews"][image["bufferView"]]["byteLength"], 0)
        self.assertEqual(self.path.read_bytes(), png())


def verify_pilot(receipt_path):
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    recipe = receipt["recipe"]
    material = bpy.data.materials[recipe["material"]]
    obj = bpy.data.objects[receipt["object"]]
    assert obj.data.materials[0] == material
    assert material.use_fake_user
    images = []
    for item in recipe["maps"]:
        image = bpy.data.images[item["image"]]
        assert tuple(image.size) == (8192, 8192)
        assert image.colorspace_settings.name == item["color_space"]
        assert image.packed_file is None
        assert materials.inspect_texture_file(item["path"])["sha256"] == item["sha256"]
        images.append(
            {
                "image": image.name,
                "dimensions": list(image.size),
                "color_space": image.colorspace_settings.name,
                "external_file_retained": True,
            }
        )
    result = {
        "passed": True,
        "images": images,
        "source_hashes_preserved": True,
        "artist_approval": "not_evaluated",
    }
    (receipt_path.parent / "cold-verification.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print("FRAMEWRIGHT_PBR_8K_COLD_OK")


def build_pilot(source_directory, output_directory):
    from scripts.benchmark_process_performance import process_memory

    checkpoints = []
    started = time.perf_counter()

    def checkpoint(stage):
        checkpoints.append(
            {
                "stage": stage,
                "elapsed_seconds": time.perf_counter() - started,
                "memory": process_memory(),
            }
        )

    source = Path(source_directory).resolve()
    download = json.loads((source / "download-receipt.json").read_text(encoding="utf-8"))
    maps = {item["role"]: item for item in download["files"]}
    if set(maps) != {"base_color", "roughness", "normal"}:
        raise ValueError("Pilot expects exactly the three downloaded Poly Haven maps")
    params = {"name": "FW_WoodenPlanks8K", "max_memory_mb": 4096, "dry_run": False}
    for role, item in maps.items():
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(source):
            raise ValueError("Pilot source must stay in its specified input directory")
        inspected = materials.inspect_texture_file(str(path))
        if inspected["sha256"] != item["sha256"] or (inspected["width"], inspected["height"]) != (
            8192,
            8192,
        ):
            raise ValueError("Downloaded source hash or 8K dimensions mismatch")
        params[role + "_path"] = str(path)
    output = Path(output_directory).resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    output.mkdir(parents=True, exist_ok=False)
    checkpoint("before_recipe")
    recipe = materials.create_pbr_material(params)
    checkpoint("after_recipe")
    scene = bpy.data.scenes.new("Framewright8KMaterialPilot")
    scene.unit_settings.system = "METRIC"
    mesh = bpy.data.meshes.new("WoodenPlanksPilotPlane")
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new()
    for point, coordinate in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
        point.uv = coordinate
    mesh.materials.append(bpy.data.materials[recipe["material"]])
    obj = bpy.data.objects.new("FW_WoodenPlanks8K_Pilot", mesh)
    scene.collection.objects.link(obj)
    bpy.context.window.scene = scene
    world = bpy.data.worlds.new("PBRPilotNeutralWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.3, 0.3, 0.3, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.2
    scene.world = world
    camera_data = bpy.data.cameras.new("PBRPilotCamera")
    camera = bpy.data.objects.new("PBRPilotCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (2.5, -3.4, 2.8)
    camera.rotation_euler = (
        (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera_data.lens = 50
    scene.camera = camera
    for name, location, energy, size in (
        ("Key", (-3, -4, 5), 1000, 4),
        ("Fill", (4, 1, 3), 600, 3),
    ):
        data = bpy.data.lights.new("PBRPilot" + name, "AREA")
        data.energy, data.shape, data.size = energy, "DISK", size
        light = bpy.data.objects.new("PBRPilot" + name, data)
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.cycles.seed = 0
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 8
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    render = output / "wooden-planks-neutral-512.png"
    scene.render.filepath = str(render)
    assert bpy.ops.render.render(write_still=True) == {"FINISHED"}
    checkpoint("after_render")
    for item in maps.values():
        assert materials.inspect_texture_file(item["path"])["sha256"] == item["sha256"]
    blend = output / "wooden-planks-8k.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False) == {"FINISHED"}
    receipt = {
        "schema_version": "1.0",
        "recipe": recipe,
        "object": obj.name,
        "blend": blend.name,
        "blend_sha256": hashlib.sha256(blend.read_bytes()).hexdigest(),
        "download_receipt": str(source / "download-receipt.json"),
        "source": download["source"],
        "license": download["license"],
        "credit": download["credit"],
        "scope": "Owned standalone material and test plane; source textures remain external and unchanged",
        "artist_approval": "not_evaluated",
        "performance": {
            "checkpoints": checkpoints,
            "source_hashes_preserved": True,
            "gpu_memory": "not_measured",
            "scope": "Whole-process Windows counters; startup precedes baseline, disk cache uncontrolled; no runtime/GPU budget approval",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "materials_module_sha256": hashlib.sha256(
                Path(materials.__file__).read_bytes()
            ).hexdigest(),
        },
        "render": {
            "file": render.name,
            "sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
            "resolution": [512, 512],
            "engine": "CYCLES",
            "device": "CPU",
            "samples": 32,
            "denoising": True,
            "seed": 0,
            "threads": 8,
            "view_transform": "AgX",
            "exposure": 0,
            "gamma": 1,
            "camera_lens_mm": 50,
            "lights": [
                {"type": "AREA", "energy_watts": 1000, "size_m": 4},
                {"type": "AREA", "energy_watts": 600, "size_m": 3},
            ],
            "scale_limit": "The 2m plane is an authoring fixture, not verified physical scan coverage",
        },
    }
    receipt_path = output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    # Release parent-process buffers before the independent cold verification.
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    bpy.data.materials.remove(bpy.data.materials[recipe["material"]], do_unlink=True)
    for item in recipe["maps"]:
        bpy.data.images.remove(bpy.data.images[item["image"]], do_unlink=True)
    process = subprocess.run(
        [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(blend),
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--verify-pilot",
            str(receipt_path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    (output / "cold-process.log").write_text(process.stdout + process.stderr, encoding="utf-8")
    if process.returncode or "FRAMEWRIGHT_PBR_8K_COLD_OK" not in process.stdout:
        raise RuntimeError("8K pilot cold verification failed; inspect owned output log")
    print("FRAMEWRIGHT_PBR_8K_PILOT_OK " + str(output))


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in owned background Blender")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-source")
    parser.add_argument("--pilot-output")
    parser.add_argument("--verify-pilot")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if arguments.verify_pilot:
        verify_pilot(arguments.verify_pilot)
    elif arguments.pilot_source and arguments.pilot_output:
        build_pilot(arguments.pilot_source, arguments.pilot_output)
    elif arguments.pilot_source or arguments.pilot_output:
        parser.error("Both pilot-source and pilot-output are required")
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(PBRMaterialTests)
        )
        if not result.wasSuccessful():
            raise RuntimeError("PBR material acceptance failed")
        print(f"FRAMEWRIGHT_MATERIALS_OK tests={result.testsRun}")
