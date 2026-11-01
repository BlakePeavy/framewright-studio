"""Cold binding audit for a retained material-atlas handoff, or small observer tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from benchmark_process_performance import process_memory  # noqa: E402

ROLES = {
    "base_color": "Base Color",
    "roughness": "Roughness",
    "metallic": "Metallic",
    "normal": "Normal",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bindings(material, resolution):
    assert material and material.node_tree, "Missing material graph"
    tree = material.node_tree
    outputs = [
        node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output
    ]
    assert len(outputs) == 1 and outputs[0].inputs["Surface"].is_linked, (
        "Missing active material surface"
    )
    shader = outputs[0].inputs["Surface"].links[0].from_node
    assert shader.type == "BSDF_PRINCIPLED", "Expected direct Principled surface"
    result = {}
    for role, socket_name in ROLES.items():
        socket = shader.inputs[socket_name]
        route = []
        for _ in range(4):
            assert socket.is_linked, f"Missing {role} image binding"
            link = socket.links[0]
            node = link.from_node
            assert not node.mute, f"Muted {role} dependency"
            route.append({"node": node.type, "output": link.from_socket.name})
            if node.type == "TEX_IMAGE":
                image = node.image
                assert image, f"Missing {role} image"
                pixel_count = len(image.pixels)
                assert image.has_data and pixel_count == resolution * resolution * 4, (
                    f"Missing decoded {role} image or wrong dimensions"
                )
                assert tuple(image.size) == (resolution, resolution), f"Wrong {role} dimensions"
                assert link.from_socket.name == "Color", f"Wrong {role} image output"
                expected = "sRGB" if role == "base_color" else "Non-Color"
                assert image.colorspace_settings.name == expected, f"Wrong {role} color space"
                assert node.projection == "FLAT", f"Wrong {role} projection"
                result[role] = {
                    "image": image.name,
                    "dimensions": list(image.size),
                    "color_space": expected,
                    "packed": bool(image.packed_file),
                    "route": route,
                }
                break
            if role == "normal" and node.type == "NORMAL_MAP":
                assert link.from_socket.name == "Normal" and node.space == "TANGENT", (
                    "Wrong normal semantic"
                )
                assert (
                    not node.inputs["Strength"].is_linked
                    and abs(node.inputs["Strength"].default_value - 1) < 1e-7
                ), "Changed normal strength"
                socket = node.inputs["Color"]
            elif role in {"roughness", "metallic"} and node.type in {"SEPARATE_COLOR", "SEPRGB"}:
                expected = {"roughness": "Green", "metallic": "Blue"}[role]
                assert link.from_socket.name in {expected, "Red"}, f"Wrong {role} packed channel"
                socket = node.inputs[0]
            else:
                raise AssertionError(f"Unsupported {role} binding route {node.type}")
        else:
            raise AssertionError(f"No {role} image found")
    # Shared ORM images require distinct G/B routes, not an arbitrary same-R route.
    if result["roughness"]["image"] == result["metallic"]["image"]:
        assert result["roughness"]["route"][0]["output"] == "Green", (
            "Shared ORM roughness must use G"
        )
        assert result["metallic"]["route"][0]["output"] == "Blue", "Shared ORM metallic must use B"
    return result, shader


def negative_controls(material, resolution):
    _, shader = bindings(material, resolution)
    rejected = []
    for role, name in ROLES.items():
        socket = shader.inputs[name]
        original = socket.links[0].from_socket
        material.node_tree.links.remove(socket.links[0])
        try:
            try:
                bindings(material, resolution)
            except AssertionError as error:
                assert role in str(error), (role, error)
                rejected.append(role)
            else:
                raise AssertionError(f"Disconnected {role} was not rejected")
        finally:
            material.node_tree.links.new(original, socket)
    try:
        bindings(material, resolution + 1)
    except AssertionError as error:
        assert "dimensions" in str(error)
    else:
        raise AssertionError("Wrong dimensions were not rejected")
    return {"disconnected_roles_rejected": rejected, "wrong_dimensions_rejected": True}


class BindingObserverTests(unittest.TestCase):
    def fixture(self, packed):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        material = bpy.data.materials.new("AtlasBindingFixture")
        tree = material.node_tree
        shader = tree.nodes.get("Principled BSDF")
        images = {}
        for role in ROLES:
            if packed and role == "metallic":
                continue
            image = bpy.data.images.new(role, width=4, height=4)
            image.colorspace_settings.name = "sRGB" if role == "base_color" else "Non-Color"
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            images[role] = texture
            if role == "normal":
                normal = tree.nodes.new("ShaderNodeNormalMap")
                tree.links.new(texture.outputs["Color"], normal.inputs["Color"])
                tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
            else:
                tree.links.new(texture.outputs["Color"], shader.inputs[ROLES[role]])
        if packed:
            split = tree.nodes.new("ShaderNodeSeparateColor")
            tree.links.new(images["roughness"].outputs["Color"], split.inputs["Color"])
            tree.links.new(split.outputs["Green"], shader.inputs["Roughness"])
            tree.links.new(split.outputs["Blue"], shader.inputs["Metallic"])
        return material

    def test_direct_roles_and_missing_dimensions_connections(self):
        material = self.fixture(False)
        observed, _ = bindings(material, 4)
        self.assertEqual(len({row["image"] for row in observed.values()}), 4)
        self.assertEqual(negative_controls(material, 4)["disconnected_roles_rejected"], list(ROLES))

    def test_orm_channels_colorspace_and_tangent_semantics(self):
        material = self.fixture(True)
        observed, shader = bindings(material, 4)
        self.assertEqual(len({row["image"] for row in observed.values()}), 3)
        self.assertTrue(negative_controls(material, 4)["wrong_dimensions_rejected"])
        split = shader.inputs["Roughness"].links[0].from_node
        material.node_tree.links.new(split.outputs["Blue"], shader.inputs["Roughness"])
        with self.assertRaisesRegex(AssertionError, "channel"):
            bindings(material, 4)
        material.node_tree.links.new(split.outputs["Green"], shader.inputs["Roughness"])
        normal = shader.inputs["Normal"].links[0].from_node
        normal.space = "OBJECT"
        with self.assertRaisesRegex(AssertionError, "normal"):
            bindings(material, 4)
        normal.space = "TANGENT"
        image = bpy.data.images[observed["base_color"]["image"]]
        image.colorspace_settings.name = "Non-Color"
        with self.assertRaisesRegex(AssertionError, "color space"):
            bindings(material, 4)


def audit(args):
    folder = args.folder.resolve(strict=True)
    record_path = folder / "report.json"
    record = json.loads(record_path.read_text())
    assert record["status"] == "passed", "Retained handoff did not pass"
    expected_resolution = record["atlas"]["resolution"]
    assert expected_resolution == args.resolution, (
        "Explicit audit resolution differs from retained bake"
    )
    filename = (
        "atlas.blend"
        if args.format == "native"
        else "Cabinet" + args.format + "." + args.format.lower()
    )
    path = folder / filename
    expected_sha = (
        record["blend_sha256"]
        if args.format == "native"
        else record["exports"][args.format]["output_sha256"]
    )
    assert sha(path) == expected_sha, "Stale retained asset"
    output = folder / ("map-audit-" + args.format.lower() + ".json")
    started = time.perf_counter()
    report = {
        "status": "failed",
        "format": args.format,
        "input": path.name,
        "input_sha256": expected_sha,
        "report_sha256": sha(record_path),
        "script_sha256": sha(__file__),
        "memory_before": process_memory(),
    }
    with output.open("x", encoding="utf-8") as stream:
        try:
            if args.format == "native":
                bpy.ops.wm.open_mainfile(filepath=str(path))
                objects = [bpy.data.objects[name] for name in record["atlas"]["objects"]]
            else:
                bpy.ops.wm.read_factory_settings(use_empty=True)
                if args.format == "GLB":
                    bpy.ops.import_scene.gltf(filepath=str(path))
                else:
                    bpy.ops.import_scene.fbx(filepath=str(path))
                objects = list(bpy.context.scene.objects)
            meshes = [obj for obj in objects if obj.type == "MESH"]
            assert len(meshes) == 29 and len(objects) == 30, "Assembly scope differs"
            assert all(len(obj.material_slots) == 1 for obj in meshes), "Changed material slots"
            materials = {obj.material_slots[0].material for obj in meshes}
            assert len(materials) == 1, "Expected one shared atlas material"
            material = next(iter(materials))
            report["bindings"], _ = bindings(material, args.resolution)
            report["negative_controls"] = negative_controls(material, args.resolution)
            assert sha(path) == expected_sha and sha(record_path) == report["report_sha256"], (
                "Inputs changed during audit"
            )
            report["status"] = "passed"
        except BaseException as error:
            report["error"] = str(error)
            raise
        finally:
            report["memory_after"] = process_memory()
            report["elapsed_seconds"] = time.perf_counter() - started
            json.dump(report, stream, indent=2)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--format", choices=("native", "GLB", "FBX"))
    parser.add_argument("--resolution", type=int)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.self_test or args.folder is None:
        outcome = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(BindingObserverTests)
        )
        if not outcome.wasSuccessful():
            raise RuntimeError("Atlas binding observer tests failed")
    else:
        assert args.format and args.resolution, "Audit requires explicit --format and --resolution"
        audit(args)
