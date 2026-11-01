"""Isolated Blender tests written before the rig/animation implementation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy  # noqa: E402

from framewright import animation, rigging  # noqa: E402


class RigAnimationTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("RigAnimationTest")
        bpy.context.window.scene = self.scene
        armature = bpy.data.armatures.new("TestSkeleton")
        self.rig = bpy.data.objects.new("TestRig", armature)
        self.scene.collection.objects.link(self.rig)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        root = armature.edit_bones.new("Root")
        root.head, root.tail = (0, 0, 0), (0, 0, 1)
        tip = armature.edit_bones.new("Tip")
        tip.head, tip.tail, tip.parent = (0, 0, 1), (0, 0, 2), root
        bpy.ops.object.mode_set(mode="OBJECT")
        mesh = bpy.data.meshes.new("TestSkin")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)], [], [(0, 1, 3, 2)])
        mesh.update()
        self.skin = bpy.data.objects.new("TestSkin", mesh)
        self.scene.collection.objects.link(self.skin)
        self.skin.modifiers.new("Deform", "ARMATURE").object = self.rig
        self.skin.vertex_groups.new(name="Root").add([0, 1, 2, 3], 0.2, "REPLACE")
        self.skin.vertex_groups.new(name="Tip").add([0, 1, 2, 3], 0.3, "REPLACE")
        self.skin.vertex_groups.new(name="Mask").add([0, 1, 2, 3], 0.7, "REPLACE")
        self.skin.vertex_groups["Root"].lock_weight = True
        pose = self.rig.pose.bones["Tip"]
        pose.location = (0, 0, 0)
        pose.keyframe_insert("location", frame=1)
        pose.location = (1, 0, 0)
        pose.keyframe_insert("location", frame=3)
        self.scene.frame_set(2)

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.old_scene
        for obj in list(self.scene.objects):
            data = obj.data
            kind = (
                bpy.data.meshes
                if obj.type == "MESH"
                else bpy.data.armatures
                if obj.type == "ARMATURE"
                else None
            )
            bpy.data.objects.remove(obj, do_unlink=True)
            if kind is not None and data.users == 0:
                kind.remove(data)
        bpy.data.scenes.remove(self.scene)

    def weights(self, obj):
        return [
            tuple((group.group, group.weight) for group in vertex.groups)
            for vertex in obj.data.vertices
        ]

    def test_time_preservation_restores_exact_transform_channels_and_matrices(self):
        self.rig.location = (1.4, -0.6, 0.2)
        self.rig.rotation_euler = (0.123, 0.234, 0.15)
        self.rig.delta_location = (0.04, 0.05, -0.06)
        self.rig.delta_rotation_euler = (0.01, -0.02, 0.03)
        self.rig.delta_scale = (1.1, 0.95, 1.05)
        root = self.rig.pose.bones["Root"]
        root.rotation_mode = "XYZ"
        root.rotation_euler = (0.07, 0.08, 0.09)
        root.scale = (1.2, 0.8, 1.1)
        tip = self.rig.pose.bones["Tip"]
        tip.rotation_mode = "AXIS_ANGLE"
        tip.rotation_axis_angle = (0.25, 0.70710677, 0.70710677, 0.0)

        def snapshot():
            bpy.context.view_layer.update()
            fields = (
                "location",
                "rotation_euler",
                "rotation_quaternion",
                "rotation_axis_angle",
                "scale",
            )
            delta_fields = (
                "delta_location",
                "delta_rotation_euler",
                "delta_rotation_quaternion",
                "delta_scale",
            )
            return {
                "object_channels": {
                    name: tuple(getattr(self.rig, name)) for name in (*fields, *delta_fields)
                },
                "object_mode": self.rig.rotation_mode,
                "object_world": tuple(tuple(row) for row in self.rig.matrix_world),
                "bones": {
                    bone.name: {
                        "channels": {name: tuple(getattr(bone, name)) for name in fields},
                        "rotation_mode": bone.rotation_mode,
                        "matrix": tuple(tuple(row) for row in bone.matrix),
                    }
                    for bone in self.rig.pose.bones
                },
                "frame": (self.scene.frame_current, self.scene.frame_subframe),
            }

        before = snapshot()
        with rigging.preserve_time(bpy.context, (self.rig,)):
            self.scene.frame_set(3)
        self.assertEqual(snapshot(), before)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with rigging.preserve_time(bpy.context, (self.rig,)):
                self.scene.frame_set(1)
                self.rig.delta_rotation_euler.y = 0.12
                root.rotation_euler.x = 1.5
                raise RuntimeError("injected sampling error")
        self.assertEqual(snapshot(), before)

    def test_skeleton_profile_has_rest_hierarchy_and_bindings(self):
        report = rigging.inspect_rig({"object_name": self.rig.name})
        self.assertEqual(report["root_bones"], ["Root"])
        self.assertEqual([bone["name"] for bone in report["bones"]], ["Root", "Tip"])
        self.assertEqual(report["bones"][1]["parent"], "Root")
        self.assertIn(self.skin.name, report["bound_meshes"])

    def test_normalize_derivative_preserves_locked_non_deform_and_protected_weights(self):
        before = self.weights(self.skin)
        count = len(self.scene.objects)
        params = {"object_name": self.skin.name, "protected_vertices": [3]}
        preview = rigging.normalize_weights(params)
        self.assertEqual(preview["changed_vertices"], 3)
        self.assertEqual(len(self.scene.objects), count)
        report = rigging.normalize_weights({**params, "dry_run": False})
        derived = self.scene.objects[report["derivative"]]
        self.assertEqual(self.weights(self.skin), before)
        self.assertEqual(self.weights(derived)[3], before[3])
        self.assertAlmostEqual(derived.vertex_groups["Root"].weight(0), 0.2)
        self.assertAlmostEqual(derived.vertex_groups["Tip"].weight(0), 0.8)
        self.assertAlmostEqual(derived.vertex_groups["Mask"].weight(0), 0.7)
        self.assertTrue(derived.hide_viewport and derived.hide_render)

    def test_deformation_sampling_restores_frame_pose_and_source(self):
        before = [tuple(vertex.co) for vertex in self.skin.data.vertices]
        pose = tuple(self.rig.pose.bones["Tip"].location)
        report = rigging.sample_deformation(
            {"object_name": self.skin.name, "frame_start": 1, "frame_end": 3}
        )
        self.assertEqual(len(report["samples"]), 3)
        self.assertIsNone(report["samples"][0]["signed_volume"])
        self.assertEqual(report["coverage"], "complete")
        self.assertEqual(self.scene.frame_current, 2)
        penetration = animation.inspect_contacts(
            {
                "object_name": self.rig.name,
                "bones": ["Tip"],
                "frame_start": 1,
                "frame_end": 3,
                "ground_height": 1.2,
            }
        )
        self.assertGreater(penetration["penetration_samples"], 0)
        self.assertEqual(tuple(self.rig.pose.bones["Tip"].location), pose)
        self.assertEqual([tuple(vertex.co) for vertex in self.skin.data.vertices], before)

    def test_action_slots_nla_and_contacts(self):
        data = self.rig.animation_data
        track = data.nla_tracks.new()
        strip = track.strips.new("FixtureNLA", 10, data.action)
        strip.extrapolation = "NOTHING"
        report = animation.inspect_animation({"object_name": self.rig.name})
        self.assertGreaterEqual(report["action"]["curve_count"], 3)
        self.assertTrue(report["action"]["slots"])
        self.assertEqual(report["nla_tracks"][0]["strips"][0]["action"], data.action.name)
        contacts = animation.inspect_contacts(
            {
                "object_name": self.rig.name,
                "bones": ["Tip"],
                "root_bone": "Root",
                "frame_start": 1,
                "frame_end": 3,
                "ground_height": 1.0,
            }
        )
        self.assertGreater(contacts["sliding_segments"], 0)
        self.assertAlmostEqual(contacts["root_displacement"], 0.0)
        self.assertEqual(self.scene.frame_current, 2)

    def test_bake_creates_separate_hidden_rig_action(self):
        original_action = self.rig.animation_data.action
        original_pose = tuple(self.rig.pose.bones["Tip"].location)
        params = {"object_name": self.rig.name, "frame_start": 1, "frame_end": 3}
        preview = animation.bake_animation(params)
        self.assertTrue(preview["dry_run"])
        result = animation.bake_animation({**params, "dry_run": False})
        derived = self.scene.objects[result["derivative"]]
        self.assertIsNot(derived.data, self.rig.data)
        self.assertIsNot(derived.animation_data.action, original_action)
        self.assertIs(self.rig.animation_data.action, original_action)
        self.assertEqual(tuple(self.rig.pose.bones["Tip"].location), original_pose)
        self.assertTrue(derived.hide_viewport and derived.hide_render)
        derived.hide_viewport = False
        for frame in (1, 2, 3):
            self.scene.frame_set(frame)
            expected = self.rig.pose.bones["Tip"].matrix.translation
            actual = derived.pose.bones["Tip"].matrix.translation
            self.assertLess((expected - actual).length, 1e-5)

    def test_corrective_is_basis_relative_on_derivative(self):
        params = {
            "object_name": self.skin.name,
            "name": "ElbowCorrective",
            "offsets": [{"vertex": 0, "offset": [0.1, 0, 0]}],
            "protected_vertices": [1],
        }
        report = rigging.corrective_shape({**params, "dry_run": False})
        derivative = self.scene.objects[report["derivative"]]
        self.assertIsNone(self.skin.data.shape_keys)
        keys = derivative.data.shape_keys.key_blocks
        self.assertAlmostEqual(
            keys["ElbowCorrective"].data[0].co.x - keys["Basis"].data[0].co.x, 0.1
        )
        self.assertEqual(tuple(keys["ElbowCorrective"].data[1].co), tuple(keys["Basis"].data[1].co))
        self.assertEqual(keys["ElbowCorrective"].value, 0.0)
        with self.assertRaisesRegex(ValueError, "protected"):
            rigging.corrective_shape({**params, "protected_vertices": [0]})

    def test_sample_bounds_are_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            rigging.sample_deformation(
                {"object_name": self.skin.name, "frame_start": 1, "frame_end": 1000}
            )
        with self.assertRaises(ValueError):
            animation.inspect_contacts(
                {
                    "object_name": self.rig.name,
                    "bones": ["Missing"],
                    "frame_start": 1,
                    "frame_end": 3,
                }
            )
        self.assertEqual(self.scene.frame_current, 2)

    def test_stock_rigify_keeps_metarig_and_rejects_custom_script(self):
        import addon_utils

        addon_utils.enable("rigify", default_set=True)
        self.rig.pose.bones["Root"].rigify_type = "basic.super_copy"
        self.rig.data.rigify_target_rig = self.rig
        self.rig.location = (-2.2643, 0.6, 0.2)
        self.rig.rotation_euler.z = 0.23
        bpy.context.view_layer.update()
        original_world = self.rig.matrix_world.copy()
        original_root_head = original_world @ self.rig.data.bones["Root"].head_local
        original_bones = list(self.rig.data.bones.keys())
        result = rigging.generate_rig({"object_name": self.rig.name, "dry_run": False})
        generated = self.scene.objects[result["derivative"]]
        self.assertIsNot(generated, self.rig)
        self.assertTrue(generated.hide_viewport and generated.hide_render)
        self.assertEqual(generated.matrix_world, original_world)
        self.assertLess(
            (
                generated.matrix_world @ generated.data.bones["ORG-Root"].head_local
                - original_root_head
            ).length,
            1e-6,
        )
        self.assertEqual(self.rig.matrix_world, original_world)
        self.assertEqual(list(self.rig.data.bones.keys()), original_bones)
        self.assertIs(self.rig.data.rigify_target_rig, self.rig)
        from unittest.mock import patch

        before = {obj.as_pointer() for obj in bpy.data.objects}
        with patch(
            "rigify.generate.generate_rig", side_effect=RuntimeError("injected generation failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                rigging.generate_rig({"object_name": self.rig.name, "dry_run": False})
        self.assertEqual({obj.as_pointer() for obj in bpy.data.objects}, before)
        self.assertIs(bpy.context.active_object, self.rig)
        script = bpy.data.texts.new("ForbiddenRigifyHook")
        try:
            self.rig.data.rigify_finalize_script = script
            with self.assertRaisesRegex(ValueError, "script"):
                rigging.generate_rig({"object_name": self.rig.name})
        finally:
            self.rig.data.rigify_finalize_script = None
            bpy.data.texts.remove(script)

    def test_retarget_explicit_map_preserves_target_rest_and_source(self):
        target = self.rig.copy()
        target.data = self.rig.data.copy()
        target.animation_data_clear()
        target.name = "TargetRig"
        self.scene.collection.objects.link(target)
        target.pose.bones["Tip"].location = (0, 0, 0)
        target.data.bones["Tip"].name = "TargetTip"
        target.data.bones["Root"].name = "TargetRoot"
        source = self.rig.pose.bones["Tip"]
        source.rotation_mode = "QUATERNION"
        from mathutils import Quaternion

        source.rotation_quaternion = Quaternion((1, 0, 0), 0.0)
        source.keyframe_insert("rotation_quaternion", frame=1)
        source.rotation_quaternion = Quaternion((1, 0, 0), 0.5)
        source.keyframe_insert("rotation_quaternion", frame=3)
        self.scene.frame_set(2)
        rest = [list(row) for row in target.data.bones["TargetTip"].matrix_local]
        result = animation.retarget_animation(
            {
                "object_name": target.name,
                "source_name": self.rig.name,
                "bone_map": {"Root": "TargetRoot", "Tip": "TargetTip"},
                "frame_start": 1,
                "frame_end": 3,
                "dry_run": False,
            }
        )
        derivative = self.scene.objects[result["derivative"]]
        derivative.hide_viewport = False
        self.assertEqual(
            [list(row) for row in derivative.data.bones["TargetTip"].matrix_local], rest
        )
        self.assertIsNone(target.animation_data)
        for frame in (1, 2, 3):
            self.scene.frame_set(frame)
            expected = self.rig.pose.bones["Tip"].matrix_basis.to_quaternion()
            actual = derivative.pose.bones["TargetTip"].matrix_basis.to_quaternion()
            self.assertAlmostEqual(abs(expected.dot(actual)), 1.0, places=5)

    def test_cleanup_duplicate_action_reduces_spike_preserves_endpoints(self):
        tip = self.rig.pose.bones["Tip"]
        tip.location = (5, 0, 0)
        tip.keyframe_insert("location", frame=2)
        action = self.rig.animation_data.action
        other_slot = action.slots.new("OBJECT", "OtherOwner")
        other_bag = action.layers[0].strips[0].channelbag(other_slot, ensure=True)
        other_curve = other_bag.fcurves.new(data_path="location", index=0)
        for frame, value in ((1, 0), (2, 100), (3, 0)):
            other_curve.keyframe_points.insert(frame, value)
        curves = [
            curve
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            for curve in bag.fcurves
        ]
        original = [tuple(key.co) for curve in curves for key in curve.keyframe_points]
        result = animation.cleanup_animation(
            {
                "object_name": self.rig.name,
                "frame_start": 1,
                "frame_end": 3,
                "threshold": 1.0,
                "strength": 0.5,
                "dry_run": False,
            }
        )
        cleaned = bpy.data.actions[result["action"]]
        self.assertIs(self.rig.animation_data.action, action)
        self.assertEqual(
            [tuple(key.co) for curve in curves for key in curve.keyframe_points], original
        )
        source_curve = next(curve for curve in curves if curve.array_index == 0)
        cleaned_curves = [
            curve
            for layer in cleaned.layers
            for strip in layer.strips
            for bag in strip.channelbags
            for curve in bag.fcurves
        ]
        clean_curve = next(
            curve
            for curve in cleaned_curves
            if curve.data_path == source_curve.data_path and curve.array_index == 0
        )
        self.assertLess(clean_curve.keyframe_points[1].co.y, source_curve.keyframe_points[1].co.y)
        self.assertEqual(
            tuple(clean_curve.keyframe_points[0].co), tuple(source_curve.keyframe_points[0].co)
        )
        self.assertEqual(
            tuple(clean_curve.keyframe_points[-1].co), tuple(source_curve.keyframe_points[-1].co)
        )
        copied_other = cleaned.layers[0].strips[0].channelbag(cleaned.slots[1]).fcurves[0]
        self.assertEqual(copied_other.keyframe_points[1].co.y, 100)

    def test_normalization_does_not_guess_or_change_locked_conflicts(self):
        self.skin.vertex_groups["Root"].add([0], 1.0, "REPLACE")
        self.skin.vertex_groups["Tip"].lock_weight = True
        self.skin.vertex_groups["Root"].remove([3])
        self.skin.vertex_groups["Tip"].remove([3])
        before = self.weights(self.skin)
        report = rigging.normalize_weights({"object_name": self.skin.name, "dry_run": False})
        self.assertGreaterEqual(report["unresolved_count"], 2)
        self.assertEqual(self.weights(self.skin), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RigAnimationTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Rig/animation tests failed")
    print(f"FRAMEWRIGHT_RIG_ANIMATION_OK tests={result.testsRun} version={bpy.app.version_string}")
