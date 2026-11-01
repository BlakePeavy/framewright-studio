"""Real Rigify regression tests for explicit anatomical-direction pilot poses."""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import addon_utils  # noqa: E402
import bpy  # noqa: E402
from build_human_rig_pilot import authored_sweep, measure_pose_targets  # noqa: E402
from mathutils import Vector  # noqa: E402

from framewright import rigging  # noqa: E402


class HumanPoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon_utils.enable("rigify", default_set=True)
        bpy.ops.object.armature_basic_human_metarig_add()
        source = bpy.context.active_object
        source.location = (-2.2643, 0.6, 0.2)
        source.rotation_euler.z = 0.23
        bpy.context.view_layer.update()
        result = rigging.generate_rig({"object_name": source.name, "dry_run": False})
        cls.rig = bpy.data.objects[result["derivative"]]
        cls.rig.hide_viewport = False
        cls.poses = authored_sweep(cls.rig)
        cls.measurements = measure_pose_targets(cls.rig, cls.poses)

    def pose(self, label):
        frame = next(frame for frame, pose in self.poses.items() if pose["label"] == label)
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        return self.measurements[str(frame)]

    def direction(self, a, b):
        world = self.rig.matrix_world
        return (
            world @ self.rig.pose.bones[b].head - world @ self.rig.pose.bones[a].head
        ).normalized()

    def test_abduction_is_lateral_not_backward(self):
        measured = self.pose("shoulder_abduction_90")
        for side, sign in (("L", 1), ("R", -1)):
            actual = self.direction("ORG-upper_arm." + side, "ORG-forearm." + side)
            expected = (self.rig.matrix_world.to_3x3() @ Vector((sign, 0, 0))).normalized()
            self.assertLess(actual.angle(expected), math.radians(0.01))
        self.assertLess(measured["maximum_direction_error_degrees"], 0.01)

    def test_flexion_points_forward_and_preserves_shoulder_positions(self):
        self.pose("shoulder_flexion_90")
        for side in ("L", "R"):
            actual = self.direction("ORG-upper_arm." + side, "ORG-forearm." + side)
            expected = (self.rig.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
            self.assertLess(actual.angle(expected), math.radians(0.01))
            org = self.rig.pose.bones["ORG-upper_arm." + side]
            self.assertLess((org.head - org.bone.head_local).length, 1e-5)

    def test_knee_flexion_measures_intended_angle_and_posterior_direction(self):
        row = self.pose("knee_flexion_110")
        for side in ("L", "R"):
            knee = row["joint_angles"]["knee." + side]
            self.assertAlmostEqual(knee["degrees"], 110, places=2)
            self.assertGreater(knee["distal_direction_body"][1], 0.7)

    def test_hip_forward_flexion_and_right_angle_knee(self):
        row = self.pose("hip_flexion_90_knee_90")
        actual = self.direction("ORG-thigh.L", "ORG-shin.L")
        expected = (self.rig.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
        self.assertLess(actual.angle(expected), math.radians(0.01))
        self.assertAlmostEqual(row["joint_angles"]["knee.L"]["degrees"], 90, places=2)

    def test_elbow_angle_and_neutral_are_explicit(self):
        row = self.pose("elbow_flexion_110")
        self.assertAlmostEqual(row["joint_angles"]["elbow.L"]["degrees"], 110, places=2)
        self.pose("neutral")
        for name in ("upper_arm_fk.L", "forearm_fk.L", "thigh_fk.L", "shin_fk.L"):
            self.assertLess(self.rig.pose.bones[name].rotation_quaternion.angle, 1e-5)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(HumanPoseTests)
    )
    if not result.wasSuccessful():
        raise AssertionError("Human anatomical pose target regression failed")
