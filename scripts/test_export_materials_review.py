"""Independent source/material-semantics regressions discovered in export review."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_pbr_map_handoff import fixture  # noqa: E402
from test_surface_render_parity import source_hash  # noqa: E402

from framewright import interchange  # noqa: E402


class ExportMaterialReviewTests(unittest.TestCase):
    def setUp(self):
        self.stores = (
            "objects",
            "meshes",
            "materials",
            "images",
            "scenes",
            "actions",
            "lights",
            "node_groups",
        )
        self.initial = {name: set(getattr(bpy.data, name)) for name in self.stores}
        self.folder = tempfile.TemporaryDirectory(prefix="fw-export-material-review-")
        self.path = Path(self.folder.name)
        self.host, self.recipe = fixture(self.path)
        self.material = self.host.data.materials[0]
        self.shader = next(
            node for node in self.material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
        )
        self.params = dict(
            object_names=[self.host.name],
            directory=str(self.path),
            filename="review",
            format="FBX",
            dry_run=False,
        )

    def tearDown(self):
        for name, previous in self.initial.items():
            store = getattr(bpy.data, name)
            for item in set(store) - previous:
                store.remove(item, do_unlink=True)
        self.folder.cleanup()

    def test_animated_material_is_rejected_before_any_source_change(self):
        socket = self.shader.inputs["IOR"]
        socket.default_value = 1.1
        socket.keyframe_insert("default_value", frame=1)
        socket.default_value = 2.1
        socket.keyframe_insert("default_value", frame=10)
        bpy.context.scene.frame_set(7, subframe=0.25)
        socket.default_value = 1.375
        before = source_hash([self.host])
        allocations = {name: set(getattr(bpy.data, name)) for name in self.stores}
        files = set(self.path.iterdir())
        with self.assertRaisesRegex(ValueError, "(?i)animated|animation"):
            interchange.export_asset(self.params)
        self.assertEqual(socket.default_value, 1.375)
        self.assertEqual(source_hash([self.host]), before)
        self.assertEqual(allocations, {name: set(getattr(bpy.data, name)) for name in self.stores})
        self.assertEqual(files, set(self.path.iterdir()))

    def test_muted_scalar_separation_is_rejected_before_export(self):
        separate = self.shader.inputs["Roughness"].links[0].from_node
        separate.mute = True
        before = set(self.path.iterdir())
        with self.assertRaisesRegex(ValueError, "muted|mute"):
            interchange.export_asset(self.params)
        self.assertEqual(set(self.path.iterdir()), before)

    def test_muted_image_or_shader_is_rejected_before_export(self):
        for node in (self.material.node_tree.nodes["FW_roughness"], self.shader):
            with self.subTest(node=node.name):
                node.mute = True
                before = set(self.path.iterdir())
                with self.assertRaisesRegex(ValueError, "muted"):
                    interchange.export_asset(self.params)
                self.assertEqual(set(self.path.iterdir()), before)
                node.mute = False

    def test_nested_shader_animation_is_rejected_for_both_formats(self):
        group = bpy.data.node_groups.new("AnimatedNestedGroup", "ShaderNodeTree")
        value = group.nodes.new("ShaderNodeValue")
        value.outputs[0].default_value = 0.7
        value.outputs[0].keyframe_insert("default_value", frame=1)
        self.material.node_tree.nodes.new("ShaderNodeGroup").node_tree = group
        for format_name in ("GLB", "FBX"):
            with self.subTest(format=format_name), self.assertRaisesRegex(ValueError, "Animated"):
                interchange.export_asset({**self.params, "format": format_name})

    def test_image_sequence_is_rejected_for_both_formats(self):
        image = self.material.node_tree.nodes["FW_base_color"].image
        image.source = "SEQUENCE"
        before = set(self.path.iterdir())
        for format_name in ("GLB", "FBX"):
            with (
                self.subTest(format=format_name),
                self.assertRaisesRegex(ValueError, "Animated image"),
            ):
                interchange.export_asset({**self.params, "format": format_name})
        self.assertEqual(set(self.path.iterdir()), before)

    def test_unrelated_animated_light_dirty_value_survives_success_and_failure(self):
        light = bpy.data.lights.new("UnrelatedAnimatedLight", "POINT")
        obj = bpy.data.objects.new("UnrelatedAnimatedLight", light)
        bpy.context.scene.collection.objects.link(obj)
        light.energy = 100
        light.keyframe_insert("energy", frame=1)
        light.energy = 1000
        light.keyframe_insert("energy", frame=10)
        bpy.context.scene.frame_set(7, subframe=0.25)
        light.energy = 375
        result = interchange.export_asset(self.params)
        self.assertTrue(result["status"]["export_generated"])
        self.assertEqual(light.energy, 375)
        self.params["filename"] = "failure"
        with patch.object(
            interchange.bpy,
            "ops",
            SimpleNamespace(
                export_scene=SimpleNamespace(
                    fbx=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected"))
                )
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                interchange.export_asset(self.params)
        self.assertEqual(light.energy, 375)

    def test_source_animated_object_dirty_transform_is_preserved(self):
        self.host.location.x = 0
        self.host.keyframe_insert("location", frame=1)
        self.host.location.x = 5
        self.host.keyframe_insert("location", frame=10)
        bpy.context.scene.frame_set(7, subframe=0.25)
        self.host.location.x = 9.25
        bpy.context.view_layer.update()
        before = source_hash([self.host])
        result = interchange.export_asset(self.params)
        self.assertTrue(result["status"]["export_generated"])
        self.assertEqual(self.host.location.x, 9.25)
        self.assertEqual(source_hash([self.host]), before)
        self.assertEqual(
            (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe), (7, 0.25)
        )
        bounds = result["verification_reference"]["normalized_mesh_bounds"][self.host.name][0]
        self.assertAlmostEqual((bounds[0][0] + bounds[1][0]) / 2, 9.25, places=5)

    def test_static_shape_key_dirty_value_is_frozen_only_on_owned_copy(self):
        self.host.shape_key_add(name="Basis")
        key = self.host.shape_key_add(name="Offset")
        for point in key.data:
            point.co.z += 2
        key.value = 0
        key.keyframe_insert("value", frame=1)
        key.value = 1
        key.keyframe_insert("value", frame=10)
        bpy.context.scene.frame_set(7, subframe=0.25)
        key.value = 0.25
        before_action = self.host.data.shape_keys.animation_data.action
        bpy.context.view_layer.update()
        result = interchange.export_asset(self.params)
        bounds = result["verification_reference"]["normalized_mesh_bounds"][self.host.name][0]
        self.assertAlmostEqual((bounds[0][2] + bounds[1][2]) / 2, 0.5, places=5)
        self.assertEqual(key.value, 0.25)
        self.assertEqual(self.host.data.shape_keys.animation_data.action, before_action)
        self.assertEqual(result["source_subframe"], 0.25)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportMaterialReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
