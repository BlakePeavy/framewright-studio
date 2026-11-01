"""Independent B-Bone dependency/evaluation review on real Blender fixtures."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_bbone_baking import BendyBakeTests, state  # noqa: E402
from test_shape_baking import ids  # noqa: E402

from framewright import bbone_baking, interchange  # noqa: E402


class BendyReviewTests(unittest.TestCase):
    setUp = BendyBakeTests.setUp
    tearDown = BendyBakeTests.tearDown

    def driver(self, path):
        data_path = 'pose.bones["Bendy"].bbone_curveinx'
        for layer in self.rig.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in list(bag.fcurves):
                        if curve.data_path == data_path:
                            bag.fcurves.remove(curve)
        self.rig.pose.bones["Bendy"].bbone_curveinx = 0
        curve = self.rig.driver_add('pose.bones["Bendy"].bbone_curveinx')
        variable = curve.driver.variables.new()
        variable.name = "denominator"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = path
        curve.driver.expression = "0.01 / denominator"
        return curve

    def test_native_driver_failure_mid_interval_rejects_finite_fallback_geometry(self):
        for frame, value in ((1, 1.0), (2, 0.0), (3, 1.0)):
            self.rig["denominator"] = value
            self.rig.keyframe_insert(data_path='["denominator"]', frame=frame)
        curve = self.driver('["denominator"]')
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        self.assertTrue(curve.driver.is_simple_expression)
        before, allocation = state(self.rig, self.skin), ids()
        with self.assertRaisesRegex(ValueError, "driver|evaluation"):
            bbone_baking.bake_bbone_skin(
                {**self.params, "frame_end": 3, "max_surface_error_m": 0.01}
            )
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertEqual(ids(), allocation)

    def test_native_driver_missing_property_rejected_before_success_claim(self):
        curve = self.driver('["missing_property"]')
        self.scene.frame_set(3)
        self.assertFalse(curve.driver.is_valid)
        before, allocation = state(self.rig, self.skin), ids()
        with self.assertRaisesRegex(ValueError, "driver|dependency|property"):
            bbone_baking.bake_bbone_skin(
                {**self.params, "frame_end": 3, "max_surface_error_m": 0.01}
            )
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertEqual(ids(), allocation)

    def test_driver_path_cannot_reach_external_id_through_rig_custom_property(self):
        external = bpy.data.objects.new("ExternalDriverOwner", None)
        self.scene.collection.objects.link(external)
        external["gain"] = 2.0
        self.rig["external_owner"] = external
        curve = self.driver('["external_owner"]["gain"]')
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        before, allocation = state(self.rig, self.skin), ids()
        with self.assertRaisesRegex(ValueError, "external|dependency|local|path"):
            bbone_baking.bake_bbone_skin(
                {**self.params, "frame_end": 3, "max_surface_error_m": 0.01}
            )
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertIs(self.rig["external_owner"], external)
        self.assertEqual(external["gain"], 2.0)
        self.assertEqual(ids(), allocation)

    def test_action_path_cannot_write_external_id_through_rig_custom_property(self):
        external = bpy.data.objects.new("ExternalAnimatedOwner", None)
        self.scene.collection.objects.link(external)
        self.rig["external_owner"] = external
        animation = self.rig.animation_data
        bag = next(
            bag
            for layer in animation.action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            if bag.slot_handle == animation.action_slot.handle
        )
        curve = bag.fcurves.new('["external_owner"].location', index=0)
        curve.keyframe_points.insert(1, 0.1)
        curve.keyframe_points.insert(3, 0.3)
        self.scene.frame_set(3)
        external.location.x = 0.91
        before, allocation, dirty = state(self.rig, self.skin), ids(), tuple(external.location)
        with self.assertRaisesRegex(ValueError, "external|dependency|local|path"):
            bbone_baking.bake_bbone_skin(
                {**self.params, "frame_end": 3, "max_surface_error_m": 0.01}
            )
        self.assertEqual(tuple(external.location), dirty)
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertEqual(ids(), allocation)

    def test_source_action_resolves_only_selected_rig_slot_paths(self):
        sibling = bpy.data.objects.new("UnselectedActionSlotOwner", None)
        self.scene.collection.objects.link(sibling)
        sibling.animation_data_create()
        action = self.rig.animation_data.action
        sibling.animation_data.action = action
        sibling.animation_data.action_slot = action.slots.new("OBJECT", sibling.name)
        for frame, value in ((1, 0.1), (3, 0.3)):
            sibling["only_sibling"] = value
            sibling.keyframe_insert(data_path='["only_sibling"]', frame=frame)
        self.assertNotIn("only_sibling", self.rig)
        before, allocation = state(self.rig, self.skin), ids()
        result = bbone_baking.bake_bbone_skin(
            {**self.params, "frame_end": 3, "max_surface_error_m": 0.01}
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertEqual(ids(), allocation)

    def test_raw_segmented_skin_export_refuses_both_formats_before_side_effects(self):
        before, allocation = state(self.rig, self.skin), ids()
        with tempfile.TemporaryDirectory(prefix="fw-raw-bbone-review-") as directory:
            for format_name in ("GLB", "FBX"):
                for animated in (False, True):
                    with self.subTest(format=format_name, animated=animated):
                        with self.assertRaisesRegex(ValueError, "segment|B-Bone|Bendy|bake"):
                            interchange.export_asset(
                                {
                                    "object_names": [self.rig.name, self.skin.name],
                                    "directory": directory,
                                    "filename": "raw",
                                    "format": format_name,
                                    "include_animation": animated,
                                    "animation_substeps": 4 if animated else 1,
                                    "dry_run": False,
                                }
                            )
                        self.assertEqual(state(self.rig, self.skin), before)
                        self.assertEqual(ids(), allocation)
                        self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BendyReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
