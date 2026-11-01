"""Shape sampling dependency scope, selected slots and native-driver failures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_shape_baking import ShapeBakeTests, ids, source_state  # noqa: E402

from framewright import shape_baking  # noqa: E402


def active_bag(owner):
    animation = owner.animation_data
    return next(
        bag
        for layer in animation.action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        if bag.slot_handle == animation.action_slot.handle
    )


class ShapeScopeReviewTests(unittest.TestCase):
    setUp = ShapeBakeTests.setUp
    tearDown = ShapeBakeTests.tearDown

    def refusal(self, params=None, external=None):
        before, allocation = source_state(self.rig, self.host, self.baked), ids()
        external_before = tuple(external.location) if external else None
        caught = None
        try:
            shape_baking.bake_shape_keys(params or self.params)
        except ValueError as error:
            caught = error
        if external:
            self.assertEqual(
                tuple(external.location),
                external_before,
                "Original external object changed while sampling copied dependencies",
            )
        self.assertEqual(source_state(self.rig, self.host, self.baked), before)
        self.assertEqual(ids(), allocation)
        self.assertIsNotNone(caught, "Unsupported dependency incorrectly returned success")
        self.assertRegex(str(caught), "local|path|driver|NLA|dependency|invalid")

    def test_active_action_paths_cannot_write_external_ids_from_either_rig(self):
        for owner in (self.rig, self.baked):
            for dry_run in (True, False):
                with self.subTest(owner=owner.name, dry_run=dry_run):
                    external = bpy.data.objects.new("OutsideShapeActionScope", None)
                    self.scene.collection.objects.link(external)
                    owner["external_owner"] = external
                    bag = active_bag(owner)
                    curve = bag.fcurves.new('["external_owner"].location', index=0)
                    curve.keyframe_points.insert(1, 0.1)
                    curve.keyframe_points.insert(49, 0.3)
                    self.scene.frame_set(25)
                    external.location.x = 0.91
                    try:
                        self.refusal({**self.params, "dry_run": dry_run}, external)
                    finally:
                        bag.fcurves.remove(curve)
                        del owner["external_owner"]
                        bpy.data.objects.remove(external, do_unlink=True)

    def test_driver_destination_cannot_write_through_custom_id_pointer(self):
        external = bpy.data.objects.new("OutsideShapeDriverDestination", None)
        self.scene.collection.objects.link(external)
        self.rig["external_owner"] = external
        self.rig.animation_data_create()
        curve = self.rig.animation_data.drivers.new('["external_owner"].location', index=0)
        curve.driver.expression = "0.2"
        self.rig.update_tag()
        self.scene.frame_set(25)
        self.assertTrue(curve.driver.is_valid)
        external.location.x = 0.91
        self.refusal(external=external)

    def key_driver(self, path):
        keys = self.host.data.shape_keys
        key = keys.key_blocks["JointBulge"]
        keys.driver_remove(key.path_from_id("value"))
        key.value = 0.01
        curve = key.driver_add("value")
        variable = curve.driver.variables.new()
        variable.name = "denominator"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = path
        curve.driver.expression = "0.01 / denominator"
        self.rig.update_tag()
        keys.update_tag()
        return curve

    def test_single_property_driver_source_cannot_traverse_external_id(self):
        external = bpy.data.objects.new("OutsideShapeDriverInput", None)
        self.scene.collection.objects.link(external)
        external["gain"] = 2.0
        self.rig["external_owner"] = external
        curve = self.key_driver('["external_owner"]["gain"]')
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        self.refusal({**self.params, "frame_end": 3, "max_interpolation_error": 0.01})
        self.assertEqual(external["gain"], 2.0)

    def test_missing_driver_property_does_not_become_finite_fallback_success(self):
        curve = self.key_driver('["missing_property"]')
        self.scene.frame_set(3)
        self.assertFalse(curve.driver.is_valid)
        self.refusal({**self.params, "frame_end": 3, "max_interpolation_error": 0.01})

    def test_midclip_invalid_key_driver_is_rejected_with_exact_source_preservation(self):
        for frame, value in ((1, 1.0), (2, 0.0), (3, 1.0)):
            self.rig["denominator"] = value
            self.rig.keyframe_insert('["denominator"]', frame=frame)
        curve = self.key_driver('["denominator"]')
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        self.refusal({**self.params, "frame_end": 3, "max_interpolation_error": 0.01})

    def test_midclip_invalid_rig_driver_is_rejected_even_when_pose_stays_finite(self):
        for frame, value in ((1, 1.0), (2, 0.0), (3, 1.0)):
            self.rig["denominator"] = value
            self.rig.keyframe_insert('["denominator"]', frame=frame)
        self.rig["review_value"] = 0.01
        curve = self.rig.driver_add('["review_value"]')
        variable = curve.driver.variables.new()
        variable.name = "denominator"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = '["denominator"]'
        curve.driver.expression = "0.01 / denominator"
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        self.refusal({**self.params, "frame_end": 3, "max_interpolation_error": 0.01})

    def test_rig_nla_is_explicitly_refused_on_both_source_and_baked_target(self):
        for owner in (self.rig, self.baked):
            with self.subTest(owner=owner.name):
                track = owner.animation_data.nla_tracks.new()
                try:
                    self.refusal()
                finally:
                    owner.animation_data.nla_tracks.remove(track)

    def test_shared_object_action_slots_keep_other_owner_channels_out_of_scope(self):
        for owner in (self.rig, self.baked):
            with self.subTest(owner=owner.name):
                sibling = bpy.data.objects.new("UnselectedShapeActionSibling", None)
                self.scene.collection.objects.link(sibling)
                sibling.animation_data_create()
                action = owner.animation_data.action
                sibling.animation_data.action = action
                sibling.animation_data.action_slot = action.slots.new("OBJECT", sibling.name)
                for frame, value in ((1, 0.1), (49, 0.3)):
                    sibling["only_sibling"] = value
                    sibling.keyframe_insert('["only_sibling"]', frame=frame)
                sibling["only_sibling"] = 0.456
                before, allocation = source_state(self.rig, self.host, self.baked), ids()
                result = shape_baking.bake_shape_keys(self.params)
                self.assertTrue(result["dry_run"])
                self.assertEqual(sibling["only_sibling"], 0.456)
                self.assertEqual(source_state(self.rig, self.host, self.baked), before)
                self.assertEqual(ids(), allocation)

    def test_shared_key_action_slot_preserves_unselected_key_channels(self):
        mesh = bpy.data.meshes.new("UnselectedKeyMesh")
        mesh.from_pydata([(0, 0, 0)], [], [])
        sibling = bpy.data.objects.new("UnselectedKeyOwner", mesh)
        self.scene.collection.objects.link(sibling)
        sibling.shape_key_add(name="Basis")
        other = sibling.shape_key_add(name="NotRequested")
        data = sibling.data.shape_keys
        data.animation_data_create()
        action = self.host.data.shape_keys.animation_data.action
        data.animation_data.action = action
        data.animation_data.action_slot = action.slots.new("KEY", data.name)
        for frame, value in ((1, 0.1), (49, 0.3)):
            other.value = value
            other.keyframe_insert("value", frame=frame)
        other.value = 0.456
        exact = other.value
        before, allocation = source_state(self.rig, self.host, self.baked), ids()
        result = shape_baking.bake_shape_keys(self.params)
        self.assertTrue(result["dry_run"])
        self.assertEqual(other.value, exact)
        self.assertEqual(source_state(self.rig, self.host, self.baked), before)
        self.assertEqual(ids(), allocation)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ShapeScopeReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
