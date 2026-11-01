"""Exercise new-file-only GLB/FBX handoff and independent-process reimport."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import interchange  # noqa: E402


def fixture():
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 25
    scene.render.fps = 24
    parent = bpy.data.objects.new("FixturePivot", None)
    scene.collection.objects.link(parent)
    parent.location = (1.3, -0.7, 0.45)
    mesh = bpy.data.meshes.new("AsymmetricSurface")
    mesh.from_pydata(
        [(0, 0, 0), (1.7, 0, 0), (1.7, 0.6, 0), (0, 0.6, 0), (0.2, 0.1, 1.2)],
        [],
        [(0, 1, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)],
    )
    mesh.update()
    uv = mesh.uv_layers.new(name="FixtureUV")
    for loop in mesh.loops:
        vertex = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (vertex.x / 1.7, vertex.y / 0.6)
    obj = bpy.data.objects.new("FixtureMesh", mesh)
    scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = (0.2, 0.3, 0.1)
    for index, color in enumerate(((0.2, 0.05, 0.03, 1), (0.03, 0.1, 0.3, 1))):
        material = bpy.data.materials.new(f"FixtureMaterial{index}")
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
        mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = polygon.index % 2
    # A simple explicit hierarchy and an animated root bone exercise skinning.
    rig_data = bpy.data.armatures.new("FixtureSkeleton")
    rig = bpy.data.objects.new("FixtureRig", rig_data)
    scene.collection.objects.link(rig)
    rig.parent = parent
    obj.parent = rig
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    bone = rig_data.edit_bones.new("Root")
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
    child = rig_data.edit_bones.new("Tip")
    child.head, child.tail = (0, 0, 1), (0.25, 0, 1.5)
    child.parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    group = obj.vertex_groups.new(name="Root")
    group.add(list(range(len(mesh.vertices))), 1, "REPLACE")
    modifier = obj.modifiers.new("FixtureSkin", "ARMATURE")
    modifier.object = rig
    for frame, x in ((1, 0), (13, 0.4), (25, 0)):
        rig.pose.bones["Root"].location = (x, 0, 0)
        rig.pose.bones["Root"].keyframe_insert("location", frame=frame)
    scene.frame_set(1)
    bpy.context.view_layer.update()
    other_scene = bpy.data.scenes.new("OtherSceneMustNotLeak")
    other_mesh = bpy.data.meshes.new("OtherSceneMesh")
    other_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    other = bpy.data.objects.new("OtherSceneSelectedObject", other_mesh)
    other["framewright_source_name"] = "LEAK"
    other_scene.collection.objects.link(other)
    other.select_set(True, view_layer=other_scene.view_layers[0])
    return [parent.name, obj.name, rig.name]


class InterchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = fixture()

    def test_01_preview_does_not_write_or_change_scene(self):
        with tempfile.TemporaryDirectory(prefix="framewright-preview-") as temporary:
            before = (
                bpy.context.scene,
                bpy.context.view_layer.objects.active,
                tuple(bpy.context.selected_objects),
                len(bpy.data.scenes),
                len(bpy.data.objects),
            )
            result = interchange.export_asset({"object_names": self.names, "directory": temporary})
            self.assertTrue(result["dry_run"])
            self.assertEqual(list(Path(temporary).iterdir()), [])
            after = (
                bpy.context.scene,
                bpy.context.view_layer.objects.active,
                tuple(bpy.context.selected_objects),
                len(bpy.data.scenes),
                len(bpy.data.objects),
            )
            self.assertEqual(after, before)

    def test_02_scope_and_path_validation(self):
        with tempfile.TemporaryDirectory(prefix="framewright-invalid-") as temporary:
            base = {"object_names": self.names, "directory": temporary}
            for override in (
                {"filename": "../unsafe"},
                {"format": "OBJ"},
                {"dry_run": 0},
                {"object_names": [self.names[1]]},
                {"object_names": ["Unknown"]},
                {"profile": []},
            ):
                with self.assertRaises(ValueError):
                    interchange.export_asset(dict(base, **override))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_03_glb_and_fbx_cold_roundtrip(self):
        for format_name in ("GLB", "FBX"):
            with (
                self.subTest(format=format_name),
                tempfile.TemporaryDirectory(prefix="framewright-roundtrip-") as temporary,
            ):
                base = {
                    "object_names": self.names,
                    "directory": temporary,
                    "filename": "fixture",
                    "format": format_name,
                    "include_animation": True,
                    "dry_run": False,
                }
                source_state = (
                    bpy.context.scene,
                    bpy.context.scene.frame_current,
                    bpy.context.view_layer.objects.active,
                    tuple(bpy.context.selected_objects),
                    len(bpy.data.scenes),
                    len(bpy.data.objects),
                    len(bpy.data.meshes),
                    len(bpy.data.armatures),
                )
                receipt = interchange.export_asset(base)
                self.assertTrue(Path(receipt["output_path"]).is_file())
                self.assertEqual(
                    source_state,
                    (
                        bpy.context.scene,
                        bpy.context.scene.frame_current,
                        bpy.context.view_layer.objects.active,
                        tuple(bpy.context.selected_objects),
                        len(bpy.data.scenes),
                        len(bpy.data.objects),
                        len(bpy.data.meshes),
                        len(bpy.data.armatures),
                    ),
                )
                self.assertEqual(
                    receipt["source_fingerprint_before"], receipt["source_fingerprint_after"]
                )
                self.assertFalse(receipt["status"]["visually_accepted"])
                with self.assertRaises(FileExistsError):
                    interchange.export_asset(base)
                environment = os.environ.copy()
                for variable in (
                    "BLENDER_USER_CONFIG",
                    "BLENDER_USER_SCRIPTS",
                    "BLENDER_USER_EXTENSIONS",
                    "BLENDER_USER_DATAFILES",
                ):
                    directory = Path(temporary) / variable.lower()
                    directory.mkdir()
                    environment[variable] = str(directory)
                child = subprocess.run(
                    [
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
                        "--verify",
                        receipt["receipt_path"],
                    ],
                    cwd=temporary,
                    env=environment,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=120,
                )
                print(child.stdout)
                print(child.stderr)
                self.assertEqual(child.returncode, 0)
                self.assertIn("FRAMEWRIGHT_COLD_ROUNDTRIP_OK", child.stdout)

    def test_04_failed_staging_leaves_no_files_or_datablocks(self):
        with tempfile.TemporaryDirectory(prefix="framewright-failure-") as temporary:
            before = tuple(
                len(getattr(bpy.data, kind))
                for kind in ("objects", "meshes", "armatures", "scenes")
            )
            with patch.object(
                interchange, "_reference", side_effect=RuntimeError("Injected export failure")
            ):
                with self.assertRaisesRegex(RuntimeError, "Injected"):
                    interchange.export_asset(
                        {"object_names": self.names, "directory": temporary, "dry_run": False}
                    )
            after = tuple(
                len(getattr(bpy.data, kind))
                for kind in ("objects", "meshes", "armatures", "scenes")
            )
            self.assertEqual(after, before)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_05_existing_receipt_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="framewright-existing-") as temporary:
            receipt = Path(temporary) / "asset.receipt.json"
            receipt.write_text("retained original", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                interchange.export_asset(
                    {"object_names": self.names, "directory": temporary, "dry_run": False}
                )
            self.assertEqual(receipt.read_text(encoding="utf-8"), "retained original")


def verify(receipt_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    # Factory scene has unrelated objects; clear only this disposable process.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if receipt["format"] == "GLB":
        bpy.ops.import_scene.gltf(filepath=receipt["output_path"])
    else:
        bpy.ops.import_scene.fbx(filepath=receipt["output_path"], use_anim=True)
    objects = {
        obj.get("framewright_source_name"): obj
        for obj in bpy.context.scene.objects
        if obj.get("framewright_source_name")
    }
    assert set(objects) == {"FixturePivot", "FixtureMesh", "FixtureRig"}, list(objects)
    helpers = {
        bone.custom_shape
        for obj in bpy.context.scene.objects
        if obj.type == "ARMATURE"
        for bone in obj.pose.bones
        if bone.custom_shape
    }
    assert len([obj for obj in bpy.context.scene.objects if obj not in helpers]) == 3, [
        (obj.name, obj.type) for obj in bpy.context.scene.objects
    ]
    mesh = objects["FixtureMesh"]
    rig = objects["FixtureRig"]
    assert len(rig.data.bones) == 2
    assert rig.data.bones["Tip"].parent.name == "Root"
    source_pivot = next(item for item in receipt["source"] if item["name"] == "FixturePivot")
    for actual_row, expected_row in zip(
        objects["FixturePivot"].matrix_world, source_pivot["matrix_world"], strict=True
    ):
        assert (
            max(
                abs(actual - expected)
                for actual, expected in zip(actual_row, expected_row, strict=True)
            )
            < 2e-4
        )
    assert len(mesh.data.uv_layers) == 1
    assert {material.name.split(".")[0] for material in mesh.data.materials} == {
        "FixtureMaterial0",
        "FixtureMaterial1",
    }
    mesh.data.calc_loop_triangles()
    assert len(mesh.data.loop_triangles) == 6
    assert mesh.vertex_groups.get("Root") is not None
    for loop in mesh.data.loops:
        vertex = mesh.data.vertices[loop.vertex_index]
        uv = mesh.data.uv_layers[0].data[loop.index].uv
        world = mesh.matrix_world @ vertex.co
        assert abs(uv.x - (world.x - 1.5) / 1.7) < 2e-4, (list(uv), list(world))
        assert abs(uv.y - (world.y + 0.4) / 0.6) < 2e-4, (list(uv), list(world))
        assert abs(sum(group.weight for group in vertex.groups) - 1) < 2e-4
    assert len({face.material_index for face in mesh.data.polygons}) == 2
    assert rig.animation_data and rig.animation_data.action
    action = rig.animation_data.action
    start, end = action.frame_range
    assert abs((end - start) / bpy.context.scene.render.fps - 1) < 1e-4, (
        start,
        end,
        bpy.context.scene.render.fps,
    )
    samples = []
    for normalized in (0, 0.5, 1):
        bpy.context.scene.frame_set(round(start + normalized * (end - start)))
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(graph)
        data = evaluated.to_mesh()
        try:
            vertices = [evaluated.matrix_world @ vertex.co for vertex in data.vertices]
            bounds = [
                [min(vertex[axis] for vertex in vertices) for axis in range(3)],
                [max(vertex[axis] for vertex in vertices) for axis in range(3)],
            ]
            samples.append(bounds)
        finally:
            evaluated.to_mesh_clear()
    expected = receipt["verification_reference"]["normalized_mesh_bounds"]["FixtureMesh"]
    for actual, reference in zip(samples, expected, strict=True):
        for actual_vector, reference_vector in zip(actual, reference, strict=True):
            assert (
                max(abs(a - b) for a, b in zip(actual_vector, reference_vector, strict=True)) < 2e-4
            ), (receipt["format"], actual, reference)
    print(
        "FRAMEWRIGHT_COLD_ROUNDTRIP_OK "
        + json.dumps(
            {
                "format": receipt["format"],
                "checks": [
                    "scope",
                    "asymmetric_bounds",
                    "parent_pivots",
                    "uv_layer",
                    "material_slots",
                    "bone_count",
                    "weights",
                    "normalized_animation",
                ],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if arguments.verify:
        verify(arguments.verify)
    else:
        outcome = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(InterchangeTests)
        )
        if not outcome.wasSuccessful():
            raise RuntimeError("Interchange acceptance tests failed")
