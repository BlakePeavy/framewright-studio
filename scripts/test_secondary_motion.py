"""Secondary binding and authored pose-control tests in isolated Blender."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import bpy  # noqa: E402
from test_rigging_animation import RigAnimationTests  # noqa: E402

from framewright import secondary_motion  # noqa: E402


class SecondaryMotionTests(unittest.TestCase):
    weights = RigAnimationTests.weights

    def setUp(self):
        self.original_collections = {collection.session_uid for collection in bpy.data.collections}
        RigAnimationTests.setUp(self)

    def tearDown(self):
        try:
            RigAnimationTests.tearDown(self)
        finally:
            for collection in list(bpy.data.collections):
                if collection.session_uid not in self.original_collections:
                    bpy.data.collections.remove(collection)

    def accessory(self):
        mesh = bpy.data.meshes.new("AccessoryMesh")
        mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new("AuthoredEyeAccessory", mesh)
        self.scene.collection.objects.link(obj)
        obj.location = (3, 0, 2)
        bpy.context.view_layer.update()
        return obj

    def test_binding_inventory_reports_actual_rig_groups_and_keys(self):
        self.skin.shape_key_add(name="Basis")
        self.skin.shape_key_add(name="AuthoredBlink")
        report = secondary_motion.inspect_bindings({"object_names": [self.skin.name]})
        item = report["objects"][0]
        self.assertEqual(item["armatures"], [self.rig.name])
        self.assertIn("Mask", [group["name"] for group in item["vertex_groups"]])
        self.assertIn("AuthoredBlink", [key["name"] for key in item["shape_keys"]])

    def test_rigid_derivative_preserves_placement_then_follows_bone(self):
        source = self.accessory()
        original = source.matrix_world.copy()
        params = {"object_name": source.name, "armature_name": self.rig.name, "bone": "Tip"}
        before = len(self.scene.objects)
        self.assertTrue(secondary_motion.attach_rigid(params)["dry_run"])
        self.assertEqual(len(self.scene.objects), before)
        result = secondary_motion.attach_rigid({**params, "dry_run": False})
        derivative = self.scene.objects[result["derivative"]]
        derivative.hide_viewport = False
        bpy.context.view_layer.update()
        self.assertLess((derivative.matrix_world.translation - original.translation).length, 1e-5)
        self.assertIsNone(source.parent)
        self.assertEqual(source.matrix_world, original)
        self.assertEqual(derivative.parent_type, "BONE")
        self.assertEqual(derivative.parent_bone, "Tip")
        self.scene.frame_set(1)
        start = derivative.matrix_world.translation.copy()
        self.scene.frame_set(3)
        self.assertAlmostEqual(derivative.matrix_world.translation.x - start.x, 1.0, places=5)

    def test_cloth_proxy_sets_real_pin_collision_and_cache_without_editing_source(self):
        collider = self.accessory()
        weights = self.weights(self.skin)
        source_modifiers = [modifier.type for modifier in self.skin.modifiers]
        result = secondary_motion.create_cloth_proxy(
            {
                "object_name": self.skin.name,
                "pin_group": "Root",
                "collider_names": [collider.name],
                "frame_start": 1,
                "frame_end": 10,
                "dry_run": False,
            }
        )
        proxy = self.scene.objects[result["derivative"]]
        cloth = next(modifier for modifier in proxy.modifiers if modifier.type == "CLOTH")
        self.assertEqual(cloth.settings.vertex_group_mass, "Root")
        self.assertTrue(cloth.collision_settings.use_collision)
        self.assertEqual((cloth.point_cache.frame_start, cloth.point_cache.frame_end), (1, 10))
        self.assertFalse(cloth.point_cache.use_disk_cache)
        self.assertEqual(cloth.collision_settings.collection.name, result["collision_collection"])
        self.assertEqual(
            [obj.name for obj in cloth.collision_settings.collection.objects],
            result["collider_derivatives"],
        )
        self.assertEqual(self.weights(proxy), weights)
        self.assertEqual([modifier.type for modifier in self.skin.modifiers], source_modifiers)
        copy = self.scene.objects[result["collider_derivatives"][0]]
        self.assertIn("COLLISION", [modifier.type for modifier in copy.modifiers])
        self.assertEqual(len(collider.modifiers), 0)

    def test_captured_authored_control_pose_applies_to_independent_rig_and_skin(self):
        constraint = self.rig.pose.bones["Tip"].constraints.new("COPY_LOCATION")
        constraint.target = self.rig
        constraint.subtarget = "Root"
        self.rig.pose.bones["Root"]["authored_scale"] = 1.0
        curve = self.rig.driver_add('pose.bones["Tip"].scale', 0)
        curve.driver.type = "AVERAGE"
        variable = curve.driver.variables.new()
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = 'pose.bones["Root"]["authored_scale"]'
        captured = secondary_motion.capture_pose({"object_name": self.rig.name, "bones": ["Tip"]})
        captured["pose"]["bones"]["Tip"][0][3] = 0.25
        original = self.rig.pose.bones["Tip"].matrix_basis.copy()
        result = secondary_motion.apply_pose(
            {
                "object_name": self.rig.name,
                "pose": captured["pose"],
                "bone_map": {"Tip": "Tip"},
                "bound_mesh_names": [self.skin.name],
                "dry_run": False,
            }
        )
        derivative = self.scene.objects[result["derivative"]]
        self.assertAlmostEqual(derivative.pose.bones["Tip"].location.x, 0.25)
        self.assertEqual(self.rig.pose.bones["Tip"].matrix_basis, original)
        skin = self.scene.objects[result["bound_derivatives"][0]]
        self.assertIs(
            next(modifier.object for modifier in skin.modifiers if modifier.type == "ARMATURE"),
            derivative,
        )
        self.assertIsNot(skin.data, self.skin.data)
        self.assertIsNone(derivative.animation_data.action)
        self.assertIs(derivative.pose.bones["Tip"].constraints[0].target, derivative)
        self.assertIs(
            derivative.animation_data.drivers[0].driver.variables[0].targets[0].id, derivative
        )
        self.assertIs(constraint.target, self.rig)
        self.assertIs(variable.targets[0].id, self.rig)

    def test_existing_shape_controls_are_isolated_and_protected(self):
        self.skin.shape_key_add(name="Basis")
        blink = self.skin.shape_key_add(name="AuthoredBlink")
        blink.value = 0.1
        protected = self.skin.shape_key_add(name="ProtectedSmile")
        protected.value = 0.2
        result = secondary_motion.apply_shape_values(
            {
                "object_name": self.skin.name,
                "values": {"AuthoredBlink": 0.75},
                "protected_keys": ["ProtectedSmile"],
                "dry_run": False,
            }
        )
        derivative = self.scene.objects[result["derivative"]]
        self.assertAlmostEqual(derivative.data.shape_keys.key_blocks["AuthoredBlink"].value, 0.75)
        self.assertAlmostEqual(derivative.data.shape_keys.key_blocks["ProtectedSmile"].value, 0.2)
        self.assertAlmostEqual(blink.value, 0.1)
        with self.assertRaisesRegex(ValueError, "protected"):
            secondary_motion.apply_shape_values(
                {
                    "object_name": self.skin.name,
                    "values": {"ProtectedSmile": 0.8},
                    "protected_keys": ["ProtectedSmile"],
                }
            )

    def test_pose_copy_remaps_skin_corrective_and_self_driver_ids(self):
        self.skin.shape_key_add(name="Basis")
        corrective = self.skin.shape_key_add(name="RigDrivenCorrective")
        corrective.data[0].co.z += 0.2
        self.rig["corrective_amount"] = 0.2
        curve = corrective.driver_add("value")
        curve.driver.type = "AVERAGE"
        variable = curve.driver.variables.new()
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = '["corrective_amount"]'
        self.skin["own_amount"] = 0.3
        own = self.skin.shape_key_add(name="SelfDrivenCorrective")
        own_curve = own.driver_add("value")
        own_curve.driver.type = "AVERAGE"
        own_variable = own_curve.driver.variables.new()
        own_variable.type = "SINGLE_PROP"
        own_variable.targets[0].id = self.skin
        own_variable.targets[0].data_path = '["own_amount"]'
        self.skin.data.shape_keys["authored_amount"] = 0.4
        key_owned = self.skin.shape_key_add(name="KeyOwnedCorrective")
        key_curve = key_owned.driver_add("value")
        key_curve.driver.type = "AVERAGE"
        key_variable = key_curve.driver.variables.new()
        key_variable.type = "SINGLE_PROP"
        key_variable.targets[0].id_type = "KEY"
        key_variable.targets[0].id = self.skin.data.shape_keys
        key_variable.targets[0].data_path = '["authored_amount"]'
        self.rig.update_tag()
        self.skin.update_tag()
        self.skin.data.shape_keys.update_tag()
        bpy.context.view_layer.update()
        source_values = (corrective.value, own.value, key_owned.value)
        source_targets = [self.rig, self.skin, self.skin.data.shape_keys]
        weights = self.weights(self.skin)
        action = self.rig.animation_data.action
        captured = secondary_motion.capture_pose({"object_name": self.rig.name, "bones": ["Tip"]})
        result = secondary_motion.apply_pose(
            {
                "object_name": self.rig.name,
                "pose": captured["pose"],
                "bone_map": {"Tip": "Tip"},
                "bound_mesh_names": [self.skin.name],
                "dry_run": False,
            }
        )
        rig = self.scene.objects[result["derivative"]]
        skin = self.scene.objects[result["bound_derivatives"][0]]
        self.assertEqual(
            [
                c.driver.variables[0].targets[0].id
                for c in skin.data.shape_keys.animation_data.drivers
            ],
            [rig, skin, skin.data.shape_keys],
        )
        self.assertEqual(
            [
                c.driver.variables[0].targets[0].id
                for c in self.skin.data.shape_keys.animation_data.drivers
            ],
            source_targets,
        )
        rig.hide_viewport = skin.hide_viewport = False
        rig["corrective_amount"] = 0.8
        skin["own_amount"] = 0.7
        skin.data.shape_keys["authored_amount"] = 0.6
        rig.update_tag()
        skin.update_tag()
        skin.data.shape_keys.update_tag()
        bpy.context.view_layer.update()
        self.assertAlmostEqual(skin.data.shape_keys.key_blocks[corrective.name].value, 0.8)
        self.assertAlmostEqual(skin.data.shape_keys.key_blocks[own.name].value, 0.7)
        self.assertAlmostEqual(skin.data.shape_keys.key_blocks[key_owned.name].value, 0.6)
        self.assertEqual((corrective.value, own.value, key_owned.value), source_values)
        self.assertEqual(self.weights(self.skin), weights)
        self.assertIs(self.rig.animation_data.action, action)

    def test_parented_pose_skin_retains_rotated_scaled_parent_inverse_and_world_placement(self):
        self.rig.location = (-2.2643, 0.6, 0.2)
        self.rig.rotation_euler = (0.12, -0.2, 0.23)
        self.rig.scale = (1.2, 0.8, 1.1)
        bpy.context.view_layer.update()
        self.skin.parent = self.rig
        self.skin.matrix_parent_inverse = self.rig.matrix_world.inverted()
        self.skin.location = (0.3, 0.4, 0.5)
        bpy.context.view_layer.update()
        world = self.skin.matrix_world.copy()
        inverse = self.skin.matrix_parent_inverse.copy()
        weights = self.weights(self.skin)
        pose = secondary_motion.capture_pose({"object_name": self.rig.name, "bones": ["Tip"]})[
            "pose"
        ]
        result = secondary_motion.apply_pose(
            {
                "object_name": self.rig.name,
                "pose": pose,
                "bone_map": {"Tip": "Tip"},
                "bound_mesh_names": [self.skin.name],
                "dry_run": False,
            }
        )
        copy = self.scene.objects[result["bound_derivatives"][0]]
        rig = self.scene.objects[result["derivative"]]
        copy.hide_viewport = rig.hide_viewport = False
        bpy.context.view_layer.update()
        self.assertEqual(copy.matrix_parent_inverse, inverse)
        self.assertLess(
            max(abs(copy.matrix_world[i][j] - world[i][j]) for i in range(4) for j in range(4)),
            2e-6,
        )
        self.assertEqual(self.skin.matrix_world, world)
        self.assertEqual(self.skin.matrix_parent_inverse, inverse)
        self.assertEqual(self.weights(self.skin), weights)

        def evaluated_points(obj):
            owner = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = owner.to_mesh()
            try:
                return [owner.matrix_world @ vertex.co for vertex in mesh.vertices]
            finally:
                owner.to_mesh_clear()

        self.assertLess(
            max(
                (a - b).length
                for a, b in zip(evaluated_points(copy), evaluated_points(self.skin), strict=True)
            ),
            2e-6,
        )

    def test_invalid_bindings_fail_before_creating_objects(self):
        count = len(self.scene.objects)
        with self.assertRaises(ValueError):
            secondary_motion.attach_rigid(
                {
                    "object_name": self.skin.name,
                    "armature_name": self.rig.name,
                    "bone": "Tip",
                    "dry_run": False,
                }
            )
        with self.assertRaises(ValueError):
            secondary_motion.create_cloth_proxy(
                {"object_name": self.skin.name, "pin_group": "Missing", "dry_run": False}
            )
        with self.assertRaises(ValueError):
            secondary_motion.create_cloth_proxy(
                {
                    "object_name": self.skin.name,
                    "pin_group": "Root",
                    "collider_names": ["Missing"],
                    "dry_run": False,
                }
            )
        self.assertEqual(len(self.scene.objects), count)

    def test_pose_failure_rolls_back_created_derivatives(self):
        from unittest.mock import patch

        original = secondary_motion.hidden_derivative
        calls = []

        def fail_second(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("injected bound-mesh failure")
            return original(*args)

        pose = secondary_motion.capture_pose({"object_name": self.rig.name, "bones": ["Tip"]})[
            "pose"
        ]
        before = (len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.meshes))
        with patch.object(secondary_motion, "hidden_derivative", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                secondary_motion.apply_pose(
                    {
                        "object_name": self.rig.name,
                        "pose": pose,
                        "bone_map": {"Tip": "Tip"},
                        "bound_mesh_names": [self.skin.name],
                        "dry_run": False,
                    }
                )
        self.assertEqual(
            (len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.meshes)), before
        )


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SecondaryMotionTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Secondary-motion fixture tests failed")
    print(f"FRAMEWRIGHT_SECONDARY_OK tests={result.testsRun} version={bpy.app.version_string}")
