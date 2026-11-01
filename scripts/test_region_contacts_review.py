"""Independent regional graph-admission and pruned-geometry regressions."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_region_contacts import RegionContactTests, inspect  # noqa: E402


class RegionContactReviewTests(unittest.TestCase):
    setUp = RegionContactTests.setUp
    tearDown = RegionContactTests.tearDown
    inventory = staticmethod(RegionContactTests.inventory)
    mesh = RegionContactTests.mesh
    animate = RegionContactTests.animate
    params = RegionContactTests.params

    def assert_refused_preserving_sources(self, request, expression):
        before = self.inventory()
        state = (
            self.scene.frame_current,
            self.scene.frame_subframe,
            tuple(self.skin.location),
            tuple(self.surface.location),
            self.skin.data.session_uid,
            self.surface.data.session_uid,
        )
        with self.assertRaisesRegex(ValueError, expression):
            inspect(request)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(
            (
                self.scene.frame_current,
                self.scene.frame_subframe,
                tuple(self.skin.location),
                tuple(self.surface.location),
                self.skin.data.session_uid,
                self.surface.data.session_uid,
            ),
            state,
        )

    def rig(self):
        data = bpy.data.armatures.new("ReviewArmature")
        obj = bpy.data.objects.new("ReviewRig", data)
        self.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("ExistingBone")
        bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
        bpy.ops.object.mode_set(mode="OBJECT")
        return obj

    def test_active_constraint_with_missing_target_never_claims_complete(self):
        request = self.params(frame_end=1)
        self.skin.constraints.new("COPY_LOCATION")
        self.assert_refused_preserving_sources(request, "constraint|target")

    def test_missing_bone_subtarget_refuses_despite_native_is_valid_flag(self):
        request = self.params(frame_end=1)
        constraint = self.skin.constraints.new("COPY_LOCATION")
        constraint.target = self.rig()
        constraint.subtarget = "MissingBone"
        # Blender may report is_valid=True while logging a missing BONE_DONE
        # dependency. Explicit identity admission must not depend on that flag.
        self.assert_refused_preserving_sources(request, "constraint|bone|target")

    def test_missing_bone_parent_never_claims_complete(self):
        request = self.params(frame_end=1)
        self.skin.parent = self.rig()
        self.skin.parent_type = "BONE"
        self.skin.parent_bone = "MissingBone"
        self.assert_refused_preserving_sources(request, "parent|bone")

    def test_requested_animation_cannot_bypass_subdivision_level_admission(self):
        modifier = self.skin.modifiers.new("AnimatedSubdivision", "SUBSURF")
        self.animate(modifier, "levels", [(1, 4), (3, 4), (10, 0)])
        self.scene.frame_set(1)
        request = self.params(frame_end=3)
        self.assertGreater(len(request["regions"][0]["triangles"]), 1)
        self.scene.frame_set(10)
        self.assertEqual(modifier.levels, 0)
        from framewright import skin_contacts

        with patch.object(
            skin_contacts, "_isolated_scene", wraps=skin_contacts._isolated_scene
        ) as stage:
            self.assert_refused_preserving_sources(request, "subdivision|level|budget")
            stage.assert_not_called()
        self.assertEqual(modifier.levels, 0)

    def test_native_subdivision_level_driver_refuses_before_sampling_allocation(self):
        modifier = self.skin.modifiers.new("DrivenSubdivision", "SUBSURF")
        curve = modifier.driver_add("levels")
        curve.driver.expression = "4 if frame <= 3 else 0"
        self.scene.frame_set(1)
        request = self.params(frame_end=3)
        self.scene.frame_set(10)
        self.assertEqual(modifier.levels, 0)
        from framewright import skin_contacts

        with patch.object(
            skin_contacts, "_isolated_scene", wraps=skin_contacts._isolated_scene
        ) as stage:
            self.assert_refused_preserving_sources(request, "subdivision|level|budget")
            stage.assert_not_called()
        self.assertEqual(modifier.levels, 0)

    def test_dormant_constraint_templates_allow_but_invalid_activation_refuses(self):
        constraint = self.skin.constraints.new("COPY_LOCATION")
        request = self.params(frame_end=3)
        for muted, influence in ((False, 0), (True, 1)):
            with self.subTest(muted=muted, influence=influence):
                constraint.mute, constraint.influence = muted, influence
                before = self.inventory()
                report = inspect(request)
                self.assertEqual(report["coverage"], "complete_at_samples")
                self.assertEqual(self.inventory(), before)
        constraint.mute = False
        self.animate(constraint, "influence", [(1, 0), (2, 1), (3, 0)])
        self.scene.frame_set(3)
        self.assertEqual(constraint.influence, 0)
        self.assert_refused_preserving_sources(request, "constraint|target")
        self.assertEqual(constraint.influence, 0)

    def test_static_subdivision_levels_zero_through_three_remain_supported(self):
        modifier = self.skin.modifiers.new("StaticSubdivision", "SUBSURF")
        previous_triangles = 0
        for level in range(4):
            with self.subTest(level=level):
                modifier.levels = level
                self.skin.update_tag()
                request = self.params(frame_end=1)
                before = self.inventory()
                result = inspect(request)
                triangles = result["regions"][0]["evaluated_object_triangles"]
                self.assertGreater(triangles, previous_triangles)
                previous_triangles = triangles
                self.assertEqual(result["coverage"], "complete_at_samples")
                self.assertEqual(modifier.levels, level)
                self.assertEqual(self.inventory(), before)

    def test_shared_action_slots_stay_on_selected_owners_and_preserve_dirty_sibling(self):
        self.animate(self.skin, "location", [(1, (0, 0, 0)), (3, (0, 0, 0.02))])
        sibling = bpy.data.objects.new("UnrelatedActionSibling", None)
        self.scene.collection.objects.link(sibling)
        sibling.animation_data_create()
        action = self.skin.animation_data.action
        sibling.animation_data.action = action
        sibling.animation_data.action_slot = action.slots.new("OBJECT", sibling.name)
        sibling["sibling_only"] = 1.0
        sibling.keyframe_insert('["sibling_only"]', frame=1)
        sibling["sibling_only"] = 3.0
        sibling.keyframe_insert('["sibling_only"]', frame=3)
        self.scene.frame_set(2, subframe=0.25)
        request = self.params()
        sibling["sibling_only"] = 9.25
        before = self.inventory()
        source_slot = self.skin.animation_data.action_slot.handle
        sibling_slot = sibling.animation_data.action_slot.handle
        result = inspect(request)
        self.assertEqual(result["sample_times"], [1, 2, 3])
        self.assertGreater(result["samples"][0]["regions"][0]["counts"]["coplanar_overlap"], 0)
        self.assertGreater(result["samples"][-1]["regions"][0]["counts"]["separated"], 0)
        self.assertEqual(sibling["sibling_only"], 9.25)
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))
        self.assertEqual(self.skin.animation_data.action, action)
        self.assertEqual(self.skin.animation_data.action_slot.handle, source_slot)
        self.assertEqual(sibling.animation_data.action_slot.handle, sibling_slot)
        self.assertEqual(self.inventory(), before)

    def test_degenerate_surface_triangle_is_refused_even_outside_broad_phase(self):
        self.surface.data.clear_geometry()
        self.surface.data.from_pydata(
            [(-4, -4, 0), (4, -4, 0), (0, 4, 0), (100, 0, 0), (101, 0, 0), (102, 0, 0)],
            [],
            [(0, 1, 2), (3, 4, 5)],
        )
        self.surface.data.update()
        self.assert_refused_preserving_sources(self.params(frame_end=1), "degenerate|altitude")

    def test_unselected_dependency_nonfinite_geometry_is_not_pruned(self):
        dependency = self.mesh(
            "UnselectedConstraintDependency", [(50, 0, 0), (51, 0, 0), (50, 1, 0)], [(0, 1, 2)]
        )
        self.skin.constraints.new("COPY_LOCATION").target = dependency
        request = self.params(frame_end=1)
        dependency.data.vertices[0].co.x = math.nan
        self.assert_refused_preserving_sources(request, "finite")
        self.assertTrue(math.isnan(dependency.data.vertices[0].co.x))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RegionContactReviewTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Independent regional review regressions failed")
    print(f"FRAMEWRIGHT_REGION_CONTACTS_REVIEW_OK tests={result.testsRun}")
