"""Actual sole-marker / uneven-surface contact fixtures in isolated Blender."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import contact_analysis  # noqa: E402


class SurfaceContactTests(unittest.TestCase):
    def setUp(self):
        self.previous_scene = bpy.context.window.scene
        self.before = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)}
            for kind in ("objects", "meshes", "armatures", "actions", "scenes")
        }
        self.scene = bpy.data.scenes.new("ContactFixture")
        bpy.context.window.scene = self.scene
        self.scene.unit_settings.system = "METRIC"
        self.scene.unit_settings.scale_length = 1
        self.scene.render.fps = 24
        mesh = bpy.data.meshes.new("ContactSurfaceMesh")
        mesh.from_pydata(
            [(-4, -4, 0), (4, -4, 0), (4, 4, 0), (-4, 4, 0)], [], [(0, 1, 2), (0, 2, 3)]
        )
        self.surface = bpy.data.objects.new("Ground", mesh)
        self.scene.collection.objects.link(self.surface)
        self.marker = bpy.data.objects.new("Sole", None)
        self.scene.collection.objects.link(self.marker)

    def tearDown(self):
        bpy.context.window.scene = self.previous_scene
        for kind in ("objects", "scenes", "meshes", "armatures", "actions"):
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def params(self, **changes):
        return {
            "surface_name": self.surface.name,
            "markers": [{"id": "heel", "object_name": self.marker.name, "position": [0, 0, 0]}],
            "frame_start": 1,
            "frame_end": 3,
            **changes,
        }

    def animate(self, obj, points):
        for frame, position in points:
            obj.location = position
            obj.keyframe_insert("location", frame=frame)
        for layer in obj.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = "LINEAR"
        self.scene.frame_set(2, subframe=0.25)

    def test_local_sole_offset_detects_contact_below_object_origin(self):
        self.marker.location.z = 0.2
        report = contact_analysis.inspect_surface_contacts(
            self.params(
                markers=[{"id": "heel", "object_name": self.marker.name, "position": [0, 0, -0.2]}]
            )
        )
        self.assertEqual(report["contact_samples"], 3)
        self.assertEqual(report["penetration_samples"], 0)
        self.assertEqual(report["coverage"], "complete_at_samples")
        self.assertFalse(report["temporal_coverage"]["between_samples_verified"])

    def test_sloped_nonuniform_surface_and_scene_units(self):
        for vertex in self.surface.data.vertices:
            vertex.co.z = vertex.co.x * 0.5
        self.surface.scale = (2, 1, 0.5)
        self.scene.unit_settings.scale_length = 0.01
        self.marker.location = (2, 0, 0.25 - 0.2)
        report = contact_analysis.inspect_surface_contacts(
            self.params(penetration_tolerance=0.001, contact_tolerance=0.003)
        )
        sample = report["samples"][0]["markers"][0]
        self.assertEqual(sample["projection_status"], "hit")
        self.assertTrue(sample["penetrating"])
        self.assertAlmostEqual(
            sample["normal_distance_meters"], -0.002 / (1 + 0.125**2) ** 0.5, places=6
        )

    def test_platform_motion_is_compensated_and_relative_sliding_is_measured(self):
        self.animate(self.surface, [(1, (0, 0, 0)), (3, (1, 0, 0))])
        self.animate(self.marker, [(1, (0, 0, 0)), (3, (1, 0, 0))])
        stable = contact_analysis.inspect_surface_contacts(self.params())
        self.assertEqual(stable["sliding_segments"], 0)
        self.assertAlmostEqual(
            stable["samples"][1]["markers"][0]["relative_tangent_speed_mps"], 0, places=6
        )
        self.marker.animation_data_clear()
        self.marker.location = (0, 0, 0)
        slides = contact_analysis.inspect_surface_contacts(self.params())
        self.assertEqual(slides["sliding_segments"], 2)
        self.assertAlmostEqual(
            slides["samples"][1]["markers"][0]["relative_tangent_speed_mps"], 12, places=5
        )

    def test_projection_miss_is_unknown_contact_and_partial_coverage(self):
        self.marker.location = (10, 0, 0)
        report = contact_analysis.inspect_surface_contacts(self.params())
        self.assertEqual(report["coverage"], "partial")
        self.assertEqual(report["projection_misses"], 3)
        sample = report["samples"][0]["markers"][0]
        self.assertIsNone(sample["contact"])
        self.assertIsNone(sample["penetrating"])

    def test_steep_projection_is_unknown_instead_of_falsely_clear(self):
        for vertex in self.surface.data.vertices:
            vertex.co.z = vertex.co.x
        report = contact_analysis.inspect_surface_contacts(self.params(minimum_up_dot=0.9))
        self.assertEqual(report["steep_surface_samples"], 3)
        self.assertEqual(report["coverage"], "partial")
        self.assertIsNone(report["samples"][0]["markers"][0]["contact"])

    def test_bone_local_sole_points_dispatch_through_public_command(self):
        from framewright.api import dispatch

        data = bpy.data.armatures.new("ContactRigData")
        rig = bpy.data.objects.new("ContactRig", data)
        self.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("heel.L")
        bone.head = (0, 0, 0.2)
        bone.tail = (0, 0.3, 0.2)
        bpy.ops.object.mode_set(mode="OBJECT")
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "bone-sole",
                "command": "animation.surface_contacts",
                "params": self.params(
                    markers=[
                        {
                            "id": "heel",
                            "object_name": rig.name,
                            "bone": "heel.L",
                            "position": [0, 0, -0.2],
                        }
                    ]
                ),
            }
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["contact_samples"], 3)
        self.assertAlmostEqual(
            response["result"]["samples"][0]["markers"][0]["normal_distance_meters"], 0, places=6
        )

    def test_geometry_budget_rejects_and_restores_time(self):
        self.scene.frame_set(2, subframe=0.25)
        with self.assertRaisesRegex(ValueError, "geometry budget"):
            contact_analysis.inspect_surface_contacts(self.params(max_surface_triangles=1))
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))

    def test_scene_scale_and_fractional_fps_apply_to_sliding_speed(self):
        self.scene.unit_settings.scale_length = 0.01
        self.scene.render.fps = 30
        self.scene.render.fps_base = 1.001
        self.animate(self.marker, [(1, (0, 0, 0)), (3, (1, 0, 0))])
        report = contact_analysis.inspect_surface_contacts(self.params())
        self.assertAlmostEqual(
            report["samples"][1]["markers"][0]["relative_tangent_speed_mps"],
            0.005 * 30 / 1.001,
            places=6,
        )

    def test_subframe_sampling_reports_skipped_integer_frames_honestly(self):
        report = contact_analysis.inspect_surface_contacts(self.params(frame_end=4, step=2))
        self.assertFalse(report["temporal_coverage"]["every_integer_frame"])
        full = contact_analysis.inspect_surface_contacts(self.params(substeps=2))
        self.assertEqual(len(full["samples"]), 5)
        self.assertTrue(full["temporal_coverage"]["every_integer_frame"])

    def test_whole_requested_interval_distinguishes_contact_from_known_clearance(self):
        self.animate(
            self.marker, [(1, (0, 0, 0)), (12, (0, 0, 0)), (13, (0, 0, 0.2)), (24, (0, 0, 0.2))]
        )
        report = contact_analysis.inspect_surface_contacts(self.params(frame_end=24))
        states = [sample["markers"][0] for sample in report["samples"]]
        self.assertEqual(len(states), 24)
        self.assertTrue(all(sample["contact"] is True for sample in states[:12]))
        self.assertTrue(all(sample["contact"] is False for sample in states[12:]))
        self.assertTrue(all(sample["projection_status"] == "hit" for sample in states))
        self.assertEqual(report["projection_misses"], 0)
        self.assertEqual(report["contact_samples"], 12)
        self.assertTrue(report["temporal_coverage"]["every_integer_frame"])
        self.assertFalse(report["visual_acceptance"])
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))

    def test_animated_surface_geometry_rejected_with_context_restored(self):
        self.surface.shape_key_add(name="Basis")
        key = self.surface.shape_key_add(name="Raise")
        for vertex in key.data:
            vertex.co.z += 0.2
        key.value = 0
        key.keyframe_insert("value", frame=1)
        key.value = 1
        key.keyframe_insert("value", frame=3)
        self.scene.frame_set(2, subframe=0.25)
        with self.assertRaisesRegex(ValueError, "surface geometry"):
            contact_analysis.inspect_surface_contacts(self.params())
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))

    def test_failure_restores_exact_source_channels_and_allocations(self):
        self.animate(self.marker, [(1, (0, 0, 0)), (3, (1, 0, 0))])
        self.marker.rotation_mode = "QUATERNION"
        self.marker.rotation_quaternion = (1, 0.001, 0.003, 0.002)
        self.marker.delta_location = (0.01, 0, 0)
        before = (
            tuple(self.marker.rotation_quaternion),
            tuple(self.marker.location),
            tuple(self.marker.delta_location),
            self.scene.frame_current,
            self.scene.frame_subframe,
            len(bpy.data.meshes),
            len(bpy.data.objects),
        )
        with patch.object(
            contact_analysis, "_project", side_effect=RuntimeError("Fixture projection failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "Fixture"):
                contact_analysis.inspect_surface_contacts(self.params())
        after = (
            tuple(self.marker.rotation_quaternion),
            tuple(self.marker.location),
            tuple(self.marker.delta_location),
            self.scene.frame_current,
            self.scene.frame_subframe,
            len(bpy.data.meshes),
            len(bpy.data.objects),
        )
        self.assertEqual(before, after)

    def test_unrelated_authored_shape_and_rig_properties_restore_on_success_and_failure(self):
        unrelated = bpy.data.objects.new("UnrelatedAnimatedCharacter", self.surface.data.copy())
        self.scene.collection.objects.link(unrelated)
        unrelated.shape_key_add(name="Basis")
        shape = unrelated.shape_key_add(name="Corrective")
        driven_shape = unrelated.shape_key_add(name="DrivenCorrective")
        driven_shape.driver_add("value").driver.expression = "0.5"
        for frame, value in ((1, 0.0), (3, 1.0)):
            shape.value = value
            shape.keyframe_insert("value", frame=frame)
        data = bpy.data.armatures.new("UnrelatedRigData")
        rig = bpy.data.objects.new("UnrelatedRig", data)
        self.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("control")
        bone.head = (0, 0, 0)
        bone.tail = (0, 1, 0)
        bpy.ops.object.mode_set(mode="OBJECT")
        control = rig.pose.bones["control"]
        for frame, value in ((1, 0.0), (3, 1.0)):
            control["IK_FK"] = value
            control.keyframe_insert('["IK_FK"]', frame=frame)
            rig["blend"] = value
            rig.keyframe_insert('["blend"]', frame=frame)
            rig["blend_array"] = [value, value]
            rig.keyframe_insert('["blend_array"]', frame=frame)
        for failure in (False, True):
            with self.subTest(failure=failure):
                self.scene.frame_set(2, subframe=0.25)
                shape.value = 0.123
                driven_shape.value = 0.432
                control["IK_FK"] = 0.234
                rig["blend"] = 0.345
                rig["blend_array"][:] = [0.456, 0.567]
                before = (
                    shape.value,
                    driven_shape.value,
                    control["IK_FK"],
                    rig["blend"],
                    tuple(rig["blend_array"]),
                )
                if failure:
                    with patch.object(
                        contact_analysis, "_project", side_effect=RuntimeError("Fixture failure")
                    ):
                        with self.assertRaisesRegex(RuntimeError, "Fixture"):
                            contact_analysis.inspect_surface_contacts(self.params())
                else:
                    contact_analysis.inspect_surface_contacts(self.params())
                self.assertEqual(
                    (
                        shape.value,
                        driven_shape.value,
                        control["IK_FK"],
                        rig["blend"],
                        tuple(rig["blend_array"]),
                    ),
                    before,
                )
                self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an owned background Blender process")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SurfaceContactTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Surface contact acceptance failed")
    print(f"FRAMEWRIGHT_SURFACE_CONTACTS_OK tests={result.testsRun}")
