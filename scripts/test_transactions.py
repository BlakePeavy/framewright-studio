"""Run with isolated Blender --background --factory-startup --disable-autoexec."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy  # noqa: E402

from framewright import blender_transactions as tx  # noqa: E402


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.scene = bpy.data.scenes.new("TransactionFixture")
        self.previous = bpy.context.window.scene
        bpy.context.window.scene = self.scene
        self.mesh = bpy.data.meshes.new("TransactionMesh")
        self.mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 2, 2)], [], [(0, 1, 2)])
        self.mesh.uv_layers.new(name="UVMap")
        self.obj = bpy.data.objects.new("TransactionSource", self.mesh)
        self.scene.collection.objects.link(self.obj)
        self.obj.select_set(True)
        bpy.context.view_layer.objects.active = self.obj
        self.old_meshes = {mesh.as_pointer() for mesh in bpy.data.meshes}
        self.materials = []

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for obj in list(self.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(self.scene)
        for mesh in list(bpy.data.meshes):
            if mesh == self.mesh or mesh.as_pointer() not in self.old_meshes:
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
        for material in self.materials:
            bpy.data.materials.remove(material)

    def plan(self):
        return tx.plan_remove_loose({"object_name": self.obj.name})

    def apply(self, plan=None):
        plan = plan or self.plan()
        return tx.apply_plan(
            {
                "plan_token": plan["plan_token"],
                "source_fingerprint": plan["source_fingerprint"],
                "dry_run": False,
            }
        )

    def test_plan_is_deterministic_and_read_only(self):
        before = tx.source_fingerprint(self.obj)
        plan = self.plan()
        self.assertEqual(plan, self.plan())
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["preview"]["removed_vertices"], 1)
        self.assertEqual(len(self.scene.objects), 1)
        self.assertEqual(tx.source_fingerprint(self.obj), before)
        self.assertEqual(list(self.obj.keys()), [])

    def test_apply_requires_explicit_false_and_matching_fingerprint(self):
        plan = self.plan()
        for params in [
            {"plan_token": plan["plan_token"], "source_fingerprint": plan["source_fingerprint"]},
            {"plan_token": plan["plan_token"], "source_fingerprint": "0" * 64, "dry_run": False},
            {
                "plan_token": plan["plan_token"],
                "source_fingerprint": plan["source_fingerprint"],
                "dry_run": True,
            },
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                tx.apply_plan(params)
        self.assertEqual(len(self.scene.objects), 1)

    def test_apply_preserves_source_and_creates_hidden_owned_derivative(self):
        before = tx.source_fingerprint(self.obj)
        result = self.apply()
        derivative = self.scene.objects[result["derivative"]]
        self.assertEqual(tx.source_fingerprint(self.obj), before)
        self.assertEqual(len(derivative.data.vertices), 3)
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        self.assertEqual(derivative["framewright_transaction_id"], result["transaction_id"])
        self.assertEqual(bpy.context.view_layer.objects.active, self.obj)
        self.assertTrue(self.obj.select_get())

    def test_stale_coordinates_and_topology_are_rejected(self):
        plan = self.plan()
        self.obj.data.vertices[0].co.x = 3
        with self.assertRaisesRegex(ValueError, "changed|stale"):
            self.apply(plan)
        plan = self.plan()
        self.obj.data.vertices.add(1)
        with self.assertRaisesRegex(ValueError, "changed|stale"):
            self.apply(plan)
        self.assertEqual(len(self.scene.objects), 1)

    def test_stale_transforms_material_identity_and_uvs_are_rejected(self):
        plan = self.plan()
        self.obj.location.x = 2
        with self.assertRaises(ValueError):
            self.apply(plan)
        plan = self.plan()
        material = bpy.data.materials.new("TransactionMaterial")
        self.materials.append(material)
        self.obj.data.materials.append(material)
        with self.assertRaises(ValueError):
            self.apply(plan)
        plan = self.plan()
        self.obj.data.uv_layers[0].data[0].uv = (0.7, 0.3)
        with self.assertRaises(ValueError):
            self.apply(plan)

    def test_plan_cannot_be_replayed(self):
        plan = self.plan()
        self.apply(plan)
        with self.assertRaisesRegex(ValueError, "consumed|applied"):
            self.apply(plan)
        self.assertEqual(len(self.scene.objects), 2)

    def test_dependency_refresh_does_not_make_unchanged_transforms_stale(self):
        self.obj.location = (2, 3, 4)
        plan = self.plan()
        bpy.context.view_layer.update()
        result = self.apply(plan)
        self.assertEqual(result["state"], "applied")

    def test_cancel_preserves_source_and_prevents_apply(self):
        before = tx.source_fingerprint(self.obj)
        plan = self.plan()
        result = tx.cancel_plan({"plan_token": plan["plan_token"]})
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(tx.source_fingerprint(self.obj), before)
        self.assertEqual(len(self.scene.objects), 1)
        with self.assertRaises(ValueError):
            self.apply(plan)
        self.assertNotEqual(self.plan()["plan_token"], plan["plan_token"])

    def test_custom_attribute_changes_make_plan_stale(self):
        attribute = self.mesh.attributes.new("DetailMask", "FLOAT", "POINT")
        plan = self.plan()
        attribute.data[0].value = 0.75
        with self.assertRaisesRegex(ValueError, "changed|stale"):
            self.apply(plan)

    def test_rollback_refuses_changes_to_custom_properties(self):
        result = self.apply()
        derivative = self.scene.objects[result["derivative"]]
        derivative["artist_note"] = "Keep this new work"
        with self.assertRaisesRegex(ValueError, "changed"):
            tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})
        self.assertIn(derivative.name, self.scene.objects)

    def test_apply_rejects_foreign_scene(self):
        plan = self.plan()
        bpy.context.window.scene = self.previous
        try:
            with self.assertRaisesRegex(ValueError, "scene"):
                self.apply(plan)
        finally:
            bpy.context.window.scene = self.scene

    def test_failed_post_create_check_cleans_derivative_only(self):
        plan = self.plan()
        original_fingerprint = tx.source_fingerprint
        before = original_fingerprint(self.obj)
        counts = (len(bpy.data.objects), len(bpy.data.meshes))

        def fail_derivative(obj, context=None):
            if obj != self.obj:
                raise RuntimeError("Fixture fingerprint failure")
            return original_fingerprint(obj, context)

        with (
            patch.object(tx, "source_fingerprint", fail_derivative),
            self.assertRaises(RuntimeError),
        ):
            self.apply(plan)
        self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), counts)
        self.assertEqual(original_fingerprint(self.obj), before)

    def test_rollback_removes_only_owned_unchanged_derivative(self):
        before = tx.source_fingerprint(self.obj)
        result = self.apply()
        derivative_name = result["derivative"]
        rollback = tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})
        self.assertEqual(rollback["state"], "rolled_back")
        self.assertNotIn(derivative_name, self.scene.objects)
        self.assertEqual(len(self.scene.objects), 1)
        self.assertEqual(tx.source_fingerprint(self.obj), before)
        with self.assertRaises(ValueError):
            tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})

    def test_rollback_requires_explicit_false(self):
        result = self.apply()
        with self.assertRaises(ValueError):
            tx.rollback_plan({"transaction_id": result["transaction_id"]})
        self.assertIn(result["derivative"], self.scene.objects)

    def test_rollback_refuses_changed_derivative(self):
        result = self.apply()
        derivative = self.scene.objects[result["derivative"]]
        derivative.data.vertices[0].co.z = 1
        with self.assertRaisesRegex(ValueError, "changed"):
            tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})
        self.assertIn(derivative.name, self.scene.objects)

    def test_rollback_refuses_replacement_with_forged_name_and_tag(self):
        result = self.apply()
        derivative = self.scene.objects[result["derivative"]]
        name = derivative.name
        bpy.data.objects.remove(derivative, do_unlink=True)
        foreign = bpy.data.objects.new(name, self.mesh)
        self.scene.collection.objects.link(foreign)
        foreign["framewright_transaction_id"] = result["transaction_id"]
        with self.assertRaisesRegex(ValueError, "owned|identity|replaced"):
            tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})
        self.assertIn(foreign.name, self.scene.objects)

    def test_rollback_refuses_shared_derivative_mesh(self):
        result = self.apply()
        derivative = self.scene.objects[result["derivative"]]
        foreign = bpy.data.objects.new("SharedDerivativeUser", derivative.data)
        self.scene.collection.objects.link(foreign)
        with self.assertRaisesRegex(ValueError, "shared"):
            tx.rollback_plan({"transaction_id": result["transaction_id"], "dry_run": False})
        self.assertIn(derivative.name, self.scene.objects)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TransactionTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Transaction tests failed")
    print(
        f"FRAMEWRIGHT_TRANSACTION_TESTS_OK tests={result.testsRun} version={bpy.app.version_string}"
    )
