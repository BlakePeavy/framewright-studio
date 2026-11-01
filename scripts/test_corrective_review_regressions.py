"""Independent authored-state regression probes for corrective activation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from test_pose_correctives import PoseCorrectiveTests  # noqa: E402


class CorrectiveReviewTests(unittest.TestCase):
    setUp = PoseCorrectiveTests.setUp
    tearDown = PoseCorrectiveTests.tearDown
    apply = PoseCorrectiveTests.apply

    def test_dirty_animated_internal_rig_constraint_is_preserved(self):
        constraint = self.rig.pose.bones["Middle"].constraints.new("COPY_ROTATION")
        constraint.target = self.rig
        constraint.subtarget = "Proximal"
        for frame, influence in ((1, 0.1), (20, 0.9)):
            constraint.influence = influence
            constraint.keyframe_insert("influence", frame=frame)
        self.scene.frame_set(7, subframe=0.25)
        constraint.influence = 0.4321
        before = constraint.influence
        self.apply()
        self.assertEqual(constraint.influence, before)

    def test_unrelated_authored_animated_light_value_is_preserved(self):
        data = bpy.data.lights.new("UnrelatedAuthoredLight", "AREA")
        light = bpy.data.objects.new("UnrelatedAuthoredLight", data)
        self.scene.collection.objects.link(light)
        try:
            for frame, energy in ((1, 10), (20, 90)):
                data.energy = energy
                data.keyframe_insert("energy", frame=frame)
            self.scene.frame_set(7, subframe=0.25)
            data.energy = 123.456
            before = data.energy
            self.apply()
            self.assertEqual(data.energy, before)
        finally:
            bpy.data.objects.remove(light, do_unlink=True)
            bpy.data.lights.remove(data)


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in owned background Blender")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CorrectiveReviewTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Independent corrective preservation regressions failed")
    print(f"FRAMEWRIGHT_CORRECTIVE_REVIEW_OK tests={result.testsRun}")
