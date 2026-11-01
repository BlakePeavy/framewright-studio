"""Isolated Blender TDD fixtures for source-preserving automatic heat binding."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

from framewright import rig_binding  # noqa: E402


class RigBindingTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("BindingTest")
        bpy.context.window.scene = self.scene
        data = bpy.data.armatures.new("HeatArmature")
        self.rig = bpy.data.objects.new("HeatRig", data)
        self.scene.collection.objects.link(self.rig)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        root = data.edit_bones.new("Root")
        root.head, root.tail = (0, 0, 0), (0, 0, 0.9)
        tip = data.edit_bones.new("Tip")
        tip.head, tip.tail, tip.parent = (0, 0, 0.9), (0, 0, 1.8), root
        tip.use_connect = True
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12)
        self.skin = bpy.context.active_object
        self.skin.name = "UnboundSkin"
        self.skin.data.transform(Matrix.Diagonal((0.3, 0.3, 1.0, 1.0)))
        self.skin.location.z = 0.9
        self.rig.hide_viewport = True
        self.rig.hide_render = True
        self.scene.frame_set(7, subframe=0.25)
        bpy.context.view_layer.update()

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.old_scene
        for obj in list(self.scene.objects):
            data = obj.data
            store = bpy.data.armatures if obj.type == "ARMATURE" else bpy.data.meshes
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                store.remove(data)
        bpy.data.scenes.remove(self.scene)

    def snapshot(self):
        bpy.context.view_layer.update()
        return {
            "vertices": [tuple(vertex.co) for vertex in self.skin.data.vertices],
            "world": tuple(tuple(row) for row in self.skin.matrix_world),
            "groups": [group.name for group in self.skin.vertex_groups],
            "parent": self.skin.parent,
            "modifiers": [(mod.name, mod.type, mod.show_viewport) for mod in self.skin.modifiers],
            "pose": [
                tuple(tuple(row) for row in bone.matrix_basis) for bone in self.rig.pose.bones
            ],
            "rig_visibility": (self.rig.hide_viewport, self.rig.hide_render, self.rig.hide_get()),
            "source_visibility": (
                self.skin.hide_viewport,
                self.skin.hide_render,
                self.skin.hide_get(),
            ),
            "selected": [obj.name for obj in bpy.context.selected_objects],
            "active": bpy.context.view_layer.objects.active.name,
            "frame": (self.scene.frame_current, self.scene.frame_subframe),
        }

    def params(self, **values):
        return {"object_name": self.skin.name, "armature_name": self.rig.name, **values}

    def test_preview_is_read_only_and_reports_base_mesh_scope(self):
        before, objects = self.snapshot(), len(bpy.data.objects)
        result = rig_binding.bind_mesh(self.params())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["bind_geometry"], "base_mesh")
        self.assertEqual(result["deform_bones"], 2)
        self.assertEqual(len(bpy.data.objects), objects)
        self.assertEqual(self.snapshot(), before)

    def test_actual_heat_binding_preserves_source_and_deforms_copy(self):
        before = self.snapshot()
        result = rig_binding.bind_mesh(self.params(dry_run=False))
        derivative = bpy.data.objects[result["derivative"]]
        self.assertEqual(self.snapshot(), before)
        self.assertIsNot(derivative.data, self.skin.data)
        self.assertEqual(result["unweighted_vertices"], 0)
        self.assertTrue(result["hidden"])
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        self.assertEqual(derivative.parent, self.rig)
        modifier = next(mod for mod in derivative.modifiers if mod.type == "ARMATURE")
        self.assertEqual(modifier.object, self.rig)
        self.assertTrue(all(vertex.groups for vertex in derivative.data.vertices))
        self.assertLess(result["max_weight_sum_error"], 1e-5)
        self.rig.hide_viewport = derivative.hide_viewport = False
        self.rig.pose.bones["Tip"].rotation_mode = "XYZ"
        self.rig.pose.bones["Tip"].rotation_euler.y = 0.6
        bpy.context.view_layer.update()
        evaluated = derivative.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            self.assertGreater(
                max(
                    (vertex.co - derivative.data.vertices[vertex.index].co).length
                    for vertex in mesh.vertices
                ),
                0.1,
            )
        finally:
            evaluated.to_mesh_clear()
        self.assertEqual(
            [tuple(vertex.co) for vertex in self.skin.data.vertices], before["vertices"]
        )

    def test_subdivision_is_retained_after_base_mesh_binding(self):
        modifier = self.skin.modifiers.new("SurfaceSubdivision", "SUBSURF")
        modifier.levels = 2
        before = self.snapshot()
        result = rig_binding.bind_mesh(self.params(dry_run=False))
        derivative = bpy.data.objects[result["derivative"]]
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(derivative.modifiers[0].type, "ARMATURE")
        self.assertTrue(derivative.modifiers[1].show_viewport)
        self.assertEqual(derivative.modifiers[1].levels, 2)

    def test_invalid_existing_groups_pose_or_budget_rejected(self):
        for values in ({"max_vertices": 1}, {"max_deform_bones": 1}, {"dry_run": "false"}):
            with self.assertRaises(ValueError):
                rig_binding.bind_mesh(self.params(**values))
        self.skin.vertex_groups.new(name="KeepMe")
        with self.assertRaisesRegex(ValueError, "unskinned"):
            rig_binding.bind_mesh(self.params(dry_run=False))
        self.skin.vertex_groups.clear()
        self.rig.pose.bones["Tip"].location.x = 0.2
        bpy.context.view_layer.update()
        with self.assertRaisesRegex(ValueError, "rest pose"):
            rig_binding.bind_mesh(self.params(dry_run=False))

    def test_operator_failure_rolls_back_only_owned_copy_and_restores_context(self):
        before = self.snapshot()
        counts = (len(bpy.data.objects), len(bpy.data.meshes))
        with patch.object(
            rig_binding, "_auto_weight", side_effect=RuntimeError("injected failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                rig_binding.bind_mesh(self.params(dry_run=False))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), counts)

    def test_incomplete_heat_rejected_or_explicitly_reported(self):
        real_auto_weight = rig_binding._auto_weight

        def omit_vertex(derivative, rig, context):
            real_auto_weight(derivative, rig, context)
            for group in derivative.vertex_groups:
                group.remove([0])

        before, count = self.snapshot(), len(bpy.data.objects)
        with patch.object(rig_binding, "_auto_weight", side_effect=omit_vertex):
            with self.assertRaisesRegex(ValueError, "unweighted"):
                rig_binding.bind_mesh(self.params(dry_run=False))
            self.assertEqual(len(bpy.data.objects), count)
            result = rig_binding.bind_mesh(
                self.params(dry_run=False, require_complete_weights=False)
            )
        self.assertEqual(result["unweighted_vertices"], 1)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RigBindingTests)
    )
    if not result.wasSuccessful():
        raise AssertionError("Rig binding fixtures failed")
