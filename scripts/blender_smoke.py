"""Run integration tests in an isolated factory-startup Blender process."""

import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

import framewright  # noqa: E402
from framewright import blender_adapter as adapter  # noqa: E402


class BlenderIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Only this isolated factory-startup process owns these fixture scenes.
        self.scene = bpy.data.scenes.new("FramewrightTest")
        self.old_scene = bpy.context.window.scene
        bpy.context.window.scene = self.scene
        self.fixture_ids = []

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.old_scene
        for obj in list(self.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(self.scene)
        for kind, item in reversed(self.fixture_ids):
            if item.name in kind:
                kind.remove(item)

    def mesh(self, name="Prop", loose=True):
        mesh = bpy.data.meshes.new(name)
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        if loose:
            vertices.append((2, 2, 2))
        mesh.from_pydata(vertices, [], [(0, 1, 2)])
        mesh.update()
        self.fixture_ids.append((bpy.data.meshes, mesh))
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        return obj

    def test_capture_base_mesh_and_scene(self):
        obj = self.mesh()
        self.scene.unit_settings.system = "METRIC"
        self.scene.unit_settings.scale_length = 0.01
        self.scene.render.fps = 30
        self.scene.render.fps_base = 1.001
        obj.scale = (2, 1, 1)
        obj.data.uv_layers.new(name="UVMap")
        mat = bpy.data.materials.new("Surface")
        self.fixture_ids.append((bpy.data.materials, mat))
        obj.data.materials.append(mat)
        obj.data.materials.append(None)
        snapshot = adapter.capture_scene()
        item = snapshot.objects[0]
        self.assertEqual(snapshot.name, self.scene.name)
        self.assertAlmostEqual(snapshot.fps, 30 / 1.001, places=4)
        self.assertAlmostEqual(snapshot.unit_scale, 0.01)
        self.assertEqual((item.vertex_count, item.edge_count, item.polygon_count), (4, 3, 1))
        self.assertEqual(
            (item.triangle_count, item.nonmanifold_edges, item.loose_vertices), (1, 3, 1)
        )
        self.assertEqual(
            (item.uv_layer_count, item.material_slot_count, item.missing_material_slots), (1, 2, 1)
        )
        self.assertEqual(item.scale, (2.0, 1.0, 1.0))

    def test_preview_does_not_change_scene(self):
        obj = self.mesh()
        obj.hide_render = True
        before = (len(bpy.data.objects), len(bpy.data.meshes), len(obj.data.vertices))
        result = adapter.preview_remove_loose_vertices(obj.name)
        self.assertEqual(result, {"source": obj.name, "removed_vertices": 1, "dry_run": True})
        self.assertEqual(
            before, (len(bpy.data.objects), len(bpy.data.meshes), len(obj.data.vertices))
        )
        self.assertFalse(obj.hide_viewport)
        self.assertTrue(obj.hide_render)

    def test_repair_preserves_source_and_selection(self):
        obj = self.mesh()
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        original_data = obj.data
        original_coords = [tuple(v.co) for v in obj.data.vertices]
        result = adapter.apply_remove_loose_vertices(obj.name)
        derivative = self.scene.objects[result["derivative"]]
        self.fixture_ids.append((bpy.data.meshes, derivative.data))
        self.assertEqual(result["removed_vertices"], 1)
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["hidden"])
        self.assertEqual(len(derivative.data.vertices), 3)
        self.assertIs(obj.data, original_data)
        self.assertIsNot(derivative.data, original_data)
        self.assertEqual([tuple(v.co) for v in obj.data.vertices], original_coords)
        self.assertEqual(list(bpy.context.selected_objects), [obj])
        self.assertIs(bpy.context.view_layer.objects.active, obj)
        self.assertTrue(derivative.hide_viewport)
        self.assertTrue(derivative.hide_render)
        self.assertFalse(obj.hide_viewport)
        self.assertFalse(obj.hide_render)
        self.assertEqual(adapter.capture_scene().objects[0].loose_vertices, 1)

    def test_loose_edges_are_preserved(self):
        obj = self.mesh()
        obj.data.clear_geometry()
        obj.data.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1)], [])
        result = adapter.apply_remove_loose_vertices(obj.name)
        derivative = self.scene.objects[result["derivative"]]
        self.fixture_ids.append((bpy.data.meshes, derivative.data))
        self.assertEqual((len(derivative.data.vertices), len(derivative.data.edges)), (2, 1))

    def test_repair_rejects_unsupported_sources(self):
        obj = self.mesh()
        obj.modifiers.new("Subdivision", "SUBSURF")
        with self.assertRaisesRegex(ValueError, "modifier"):
            adapter.preview_remove_loose_vertices(obj.name)
        obj.modifiers.clear()
        obj.shape_key_add(name="Basis")
        with self.assertRaisesRegex(ValueError, "shape"):
            adapter.apply_remove_loose_vertices(obj.name)
        obj.shape_key_clear()
        obj.vertex_groups.new(name="RigWeight")
        with self.assertRaisesRegex(ValueError, "group"):
            adapter.apply_remove_loose_vertices(obj.name)

    def test_noop_and_foreign_scene_are_rejected(self):
        obj = self.mesh(loose=False)
        with self.assertRaisesRegex(ValueError, "isolated"):
            adapter.preview_remove_loose_vertices(obj.name)
        other = bpy.data.objects.new("Foreign", None)
        self.old_scene.collection.objects.link(other)
        try:
            with self.assertRaisesRegex(ValueError, "scene"):
                adapter.preview_remove_loose_vertices(other.name)
        finally:
            bpy.data.objects.remove(other, do_unlink=True)

    def test_edit_mode_is_explicitly_rejected(self):
        obj = self.mesh()
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        with self.assertRaisesRegex(ValueError, "Object Mode"):
            adapter.capture_scene()
        with self.assertRaisesRegex(ValueError, "Object Mode"):
            adapter.preview_remove_loose_vertices(obj.name)

    def test_adapter_rejects_worker_threads(self):
        errors = []

        def worker():
            try:
                adapter.capture_scene()
            except RuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertIn("main thread", errors[0])

    def test_only_referenced_missing_images_are_reported(self):
        obj = self.mesh()
        material = bpy.data.materials.new("TextureMaterial")
        material.use_nodes = True
        self.fixture_ids.append((bpy.data.materials, material))
        obj.data.materials.append(material)
        missing = bpy.data.images.new("MissingReferenced", 1, 1)
        missing.source = "FILE"
        missing.filepath = "//nonexistent-framewright-fixture.png"
        self.fixture_ids.append((bpy.data.images, missing))
        unused = bpy.data.images.new("MissingUnused", 1, 1)
        unused.source = "FILE"
        unused.filepath = "//also-missing-framewright.png"
        self.fixture_ids.append((bpy.data.images, unused))
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = missing
        self.assertEqual(adapter.capture_scene().missing_images, ("MissingReferenced",))

    def test_texture_dimensions_and_color_space_are_scene_scoped(self):
        obj = self.mesh()
        material = bpy.data.materials.new("GeneratedMaterial")
        material.use_nodes = True
        self.fixture_ids.append((bpy.data.materials, material))
        obj.data.materials.append(material)
        image = bpy.data.images.new("GeneratedMap", 64, 32)
        self.fixture_ids.append((bpy.data.images, image))
        material.node_tree.nodes.new("ShaderNodeTexImage").image = image
        snapshot = adapter.capture_scene()
        self.assertEqual(snapshot.missing_images, ())
        self.assertEqual(len(snapshot.textures), 1)
        texture = snapshot.textures[0]
        self.assertEqual((texture.name, texture.width, texture.height), ("GeneratedMap", 64, 32))
        self.assertEqual(texture.color_space, image.colorspace_settings.name)
        self.assertEqual(texture.source, "GENERATED")

    def test_animated_and_parented_repair_are_rejected(self):
        obj = self.mesh()
        obj.keyframe_insert("location", frame=1)
        with self.assertRaisesRegex(ValueError, "animated"):
            adapter.apply_remove_loose_vertices(obj.name)
        obj.animation_data_clear()
        parent = bpy.data.objects.new("Parent", None)
        self.scene.collection.objects.link(parent)
        obj.parent = parent
        with self.assertRaisesRegex(ValueError, "parented"):
            adapter.apply_remove_loose_vertices(obj.name)

    def test_rig_weights_count_deforming_bones_only(self):
        obj = self.mesh()
        armature = bpy.data.armatures.new("Rig")
        self.fixture_ids.append((bpy.data.armatures, armature))
        rig = bpy.data.objects.new("Rig", armature)
        self.scene.collection.objects.link(rig)
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        bone = armature.edit_bones.new("Root")
        bone.head = (0, 0, 0)
        bone.tail = (0, 0, 1)
        bpy.ops.object.mode_set(mode="OBJECT")
        modifier = obj.modifiers.new("Skin", "ARMATURE")
        modifier.object = rig
        weights = obj.vertex_groups.new(name="Root")
        weights.add([0, 1], 1.0, "REPLACE")
        mask = obj.vertex_groups.new(name="Mask")
        mask.add([2, 3], 1.0, "REPLACE")
        snapshot = adapter.capture_scene()
        item = next(item for item in snapshot.objects if item.name == obj.name)
        self.assertEqual((item.unweighted_vertices, item.max_vertex_influences), (2, 1))
        self.assertEqual(item.armature_target, rig.name)
        rig_snapshot = next(item for item in snapshot.objects if item.name == rig.name)
        self.assertEqual((rig_snapshot.bone_count, rig_snapshot.root_bone_count), (1, 1))

    def test_registration_and_panel_report(self):
        self.mesh()
        framewright.register()
        try:
            self.scene.framewright_triangle_limit = 200000
            self.scene.framewright_texture_target = 8192
            self.assertEqual(bpy.ops.framewright.validate_scene(), {"FINISHED"})
            result = json.loads(self.scene.framewright_report)
            self.assertEqual(result["schema_version"], "1.0")
            self.assertIn("findings", result)
            self.assertEqual(result["settings"]["max_triangles"], 200000)
            self.assertEqual(result["settings"]["texture_target"], 8192)
            self.scene.framewright_profile = "cinematic_8k"
            self.scene.framewright_texture_target = 0
            self.scene.framewright_texture_max = 32768
            self.assertEqual(bpy.ops.framewright.validate_scene(), {"FINISHED"})
            result = json.loads(self.scene.framewright_report)
            self.assertEqual(result["settings"]["texture_target"], 0)
            self.assertEqual(result["settings"]["max_texture_resolution"], 32768)
        finally:
            framewright.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, "framewright_report"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlenderIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("Blender integration tests failed")
    print(f"FRAMEWRIGHT_BLENDER_TESTS_OK tests={result.testsRun} version={bpy.app.version_string}")
