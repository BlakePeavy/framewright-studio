"""Independent evaluated-dependency budget and pose-driver ownership regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_skin_contacts import SkinContactTests  # noqa: E402

from framewright import secondary_motion, skin_contacts  # noqa: E402


class SkinContactReviewTests(unittest.TestCase):
    setUp = SkinContactTests.setUp
    tearDown = SkinContactTests.tearDown
    inventory = staticmethod(SkinContactTests.inventory)
    mesh = SkinContactTests.mesh
    params = SkinContactTests.params
    animate = SkinContactTests.animate

    def target(self):
        target = self.mesh("ConstraintDependency", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        constraint = self.skin.constraints.new("COPY_LOCATION")
        constraint.target = target
        return target

    def test_evaluated_constraint_dependency_counts_against_total_vertex_budget(self):
        target = self.target()
        modifier = target.modifiers.new("ExtraEvaluatedGeometry", "SUBSURF")
        modifier.levels = 2
        self.scene.frame_set(2, subframe=0.25)
        before = (
            self.inventory(),
            self.scene.frame_current,
            self.scene.frame_subframe,
            modifier.levels,
        )
        with self.assertRaisesRegex(ValueError, "budget"):
            skin_contacts.inspect_skin_contacts(self.params(max_evaluated_vertices=10))
        self.assertEqual(
            (
                self.inventory(),
                self.scene.frame_current,
                self.scene.frame_subframe,
                modifier.levels,
            ),
            before,
        )

    def test_extra_mesh_dependency_topology_changes_are_not_silently_omitted(self):
        target = self.target()
        modifier = target.modifiers.new("ChangingDependencyTopology", "SUBSURF")
        self.animate(modifier, "levels", [(1, 0), (2, 2), (3, 0)])
        self.scene.frame_set(3)
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "topology"):
            skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(self.inventory(), before)

    def test_negative_frames_and_subframes_cover_every_requested_tick(self):
        self.animate(self.skin, "location", [(-2, (0, 0, -0.1)), (1, (0, 0, 0.2))])
        self.scene.frame_set(0, subframe=0.125)
        before = (
            self.inventory(),
            tuple(self.skin.location),
            self.scene.frame_current,
            self.scene.frame_subframe,
        )
        result = skin_contacts.inspect_skin_contacts(
            self.params(frame_start=-2, frame_end=1, substeps=4, max_samples=13)
        )
        self.assertEqual(
            [sample["frame"] + sample["subframe"] for sample in result["samples"]],
            [-2 + i * 0.25 for i in range(13)],
        )
        for i, sample in enumerate(result["samples"]):
            self.assertAlmostEqual(
                sample["markers"][0]["normal_distance_meters"], -0.1 + i * 0.025, places=6
            )
        self.assertEqual(
            (
                self.inventory(),
                tuple(self.skin.location),
                self.scene.frame_current,
                self.scene.frame_subframe,
            ),
            before,
        )
        with self.assertRaisesRegex(ValueError, "max_samples"):
            skin_contacts.inspect_skin_contacts(
                self.params(frame_start=-2, frame_end=1, substeps=4, max_samples=12)
            )
        self.assertEqual(
            (
                self.inventory(),
                tuple(self.skin.location),
                self.scene.frame_current,
                self.scene.frame_subframe,
            ),
            before,
        )

    def test_constraint_dependency_from_other_scene_is_refused_without_cleanup_damage(self):
        foreign = bpy.data.scenes.new("ForeignContactScene")
        target = bpy.data.objects.new("ForeignTarget", None)
        foreign.collection.objects.link(target)
        self.skin.constraints.new("COPY_LOCATION").target = target
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "active scene"):
            skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(self.inventory(), before)

    def test_mid_interval_native_driver_failure_does_not_report_valid_contact_samples(self):
        self.assert_driver_failure_preserves_source(self.skin, "location", 2)

    def assert_driver_failure_preserves_source(self, owner, path, index=-1):
        control = bpy.data.objects.new("NativeDriverControl", None)
        self.scene.collection.objects.link(control)
        for frame, value in ((1, 1.0), (2, 0.0), (3, 1.0)):
            control["denominator"] = value
            control.keyframe_insert(data_path='["denominator"]', frame=frame)
        curve = owner.driver_add(path, index) if index >= 0 else owner.driver_add(path)
        curve.driver.type = "SCRIPTED"
        variable = curve.driver.variables.new()
        variable.name = "denominator"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = control
        variable.targets[0].data_path = '["denominator"]'
        curve.driver.expression = "1.0 / denominator"
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_simple_expression)
        self.assertTrue(curve.driver.is_valid)
        before = (
            self.inventory(),
            tuple(self.skin.location),
            control["denominator"],
            self.scene.frame_current,
        )
        with self.assertRaisesRegex(ValueError, "driver|evaluation"):
            skin_contacts.inspect_skin_contacts(self.params(search_distance=2))
        self.assertEqual(
            (
                self.inventory(),
                tuple(self.skin.location),
                control["denominator"],
                self.scene.frame_current,
            ),
            before,
        )

    def test_mesh_data_driver_failure_is_checked_at_each_sample(self):
        self.skin.data["driven"] = 1.0
        self.assert_driver_failure_preserves_source(self.skin.data, '["driven"]')

    def test_shape_key_driver_failure_is_checked_at_each_sample(self):
        self.skin.shape_key_add(name="Basis")
        self.skin.shape_key_add(name="DrivenShape")
        self.assert_driver_failure_preserves_source(
            self.skin.data.shape_keys, 'key_blocks["DrivenShape"].value'
        )

    def test_non_marker_dependency_driver_failure_is_checked_at_each_sample(self):
        target = self.target()
        self.assert_driver_failure_preserves_source(target, "location", 2)

    def rig(self):
        data = bpy.data.armatures.new("DriverRigData")
        rig = bpy.data.objects.new("DriverRig", data)
        self.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("Foot")
        bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
        bpy.ops.object.mode_set(mode="OBJECT")
        return rig

    def test_pose_shared_mesh_data_driver_dependency_requires_unambiguous_ownership(self):
        rig = self.rig()
        other = self.skin.copy()
        other.name = "SharedSkinObject"
        self.scene.collection.objects.link(other)
        for obj in (self.skin, other):
            obj.modifiers.new("BoundSkin", "ARMATURE").object = rig
        self.skin.data["gain"] = 1.0
        driver = rig.driver_add('pose.bones["Foot"].scale', 0).driver
        driver.type = "AVERAGE"
        variable = driver.variables.new()
        variable.type = "SINGLE_PROP"
        variable.targets[0].id_type = "MESH"
        variable.targets[0].id = self.skin.data
        variable.targets[0].data_path = '["gain"]'
        pose = secondary_motion.capture_pose({"object_name": rig.name, "bones": ["Foot"]})["pose"]
        before = (self.inventory(), variable.targets[0].id, self.skin.data, other.data)
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                with self.assertRaisesRegex(ValueError, "shared|Shared|ambiguous"):
                    secondary_motion.apply_pose(
                        {
                            "object_name": rig.name,
                            "pose": pose,
                            "bone_map": {"Foot": "Foot"},
                            "bound_mesh_names": [self.skin.name, other.name],
                            "dry_run": dry_run,
                        }
                    )
        self.assertEqual(
            (self.inventory(), variable.targets[0].id, self.skin.data, other.data), before
        )


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SkinContactReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
