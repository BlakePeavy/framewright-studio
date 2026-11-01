"""Independent fractional-time, shared-slot and data/key action staging checks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_export_substeps import snapshot  # noqa: E402
from test_shape_baking import ids  # noqa: E402

from framewright import interchange  # noqa: E402


def active_curves(owner):
    animation = owner.animation_data
    return [
        curve
        for layer in animation.action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        if bag.slot_handle == animation.action_slot.handle
        for curve in bag.fcurves
    ]


class ExportSamplingReviewTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.before = ids()
        self.scene = bpy.data.scenes.new("ExportSamplingReview")
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("SharedData")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        self.a = bpy.data.objects.new("SlotA", mesh)
        self.b = bpy.data.objects.new("SlotB", mesh)
        for obj in (self.a, self.b):
            self.scene.collection.objects.link(obj)
        self.objects = [self.a, self.b]
        for frame, value in ((-1.5, -2.0), (0.25, 3.0), (2.75, 1.0)):
            self.a.location.x = value
            self.a.keyframe_insert("location", index=0, frame=frame)
        action = self.a.animation_data.action
        self.b.animation_data_create()
        self.b.animation_data.action = action
        self.b.animation_data.action_slot = action.slots.new("OBJECT", "SlotB")
        for frame, value in ((-1.5, 1.0), (0.25, -2.0), (2.75, 5.0)):
            self.b.location.y = value
            self.b.keyframe_insert("location", index=1, frame=frame)
            mesh["bias"] = value * 0.1
            mesh.keyframe_insert(data_path='["bias"]', frame=frame)
        self.a.shape_key_add(name="Basis")
        shape = self.a.shape_key_add(name="Bend")
        shape.data[0].co.z = 0.1
        for frame, value in ((-1.5, 0.0), (0.25, 0.8), (2.75, 0.2)):
            shape.value = value
            shape.keyframe_insert("value", frame=frame)
        for owner in (self.a, self.b, mesh, mesh.shape_keys):
            for curve in active_curves(owner):
                for key in curve.keyframe_points:
                    key.interpolation = "BEZIER"
                    key.handle_left_type = key.handle_right_type = "FREE"
                    key.handle_left = (key.co.x - 0.2, key.co.y - 0.13)
                    key.handle_right = (key.co.x + 0.45, key.co.y + 0.2)
        self.scene.render.fps = 30
        self.scene.render.fps_base = 1.001
        self.scene.frame_start, self.scene.frame_end = 0, 3
        self.scene.frame_set(-1, subframe=0.625)
        self.source_time = (self.scene.frame_current, self.scene.frame_subframe)

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in ("objects", "meshes", "armatures", "actions", "scenes"):
            for item in set(getattr(bpy.data, kind)) - self.before[kind]:
                getattr(bpy.data, kind).remove(item, do_unlink=True)

    def test_fractional_negative_time_bezier_and_shared_action_slots_preserve_values(self):
        original = snapshot(self.objects)
        allocation = ids()
        with interchange._staging(self.objects, bpy.context, True, animation_substeps=4) as (
            scene,
            copies,
        ):
            self.assertAlmostEqual(scene.frame_current + scene.frame_subframe, -1.5)
            self.assertEqual(scene.render.fps, 120)
            self.assertEqual(scene.render.fps_base, self.scene.render.fps_base)
            self.assertAlmostEqual(
                (scene.frame_end - scene.frame_start) / (scene.render.fps / scene.render.fps_base),
                (self.scene.frame_end - self.scene.frame_start)
                / (self.scene.render.fps / self.scene.render.fps_base),
                places=10,
            )
            owners = [
                (self.a, copies[self.a]),
                (self.b, copies[self.b]),
                (self.a.data, copies[self.a].data),
                (self.a.data.shape_keys, copies[self.a].data.shape_keys),
                (self.b.data, copies[self.b].data),
                (self.b.data.shape_keys, copies[self.b].data.shape_keys),
            ]
            for source, derivative in owners:
                self.assertEqual(
                    source.animation_data.action_slot.identifier,
                    derivative.animation_data.action_slot.identifier,
                )
                self.assertIsNot(source.animation_data.action, derivative.animation_data.action)
                for old, new in zip(active_curves(source), active_curves(derivative), strict=True):
                    self.assertEqual(
                        (old.data_path, old.array_index), (new.data_path, new.array_index)
                    )
                    for time in (-1.5, -1.125, -0.375, 0, 0.25, 0.625, 1.125, 2.375, 2.75):
                        self.assertAlmostEqual(old.evaluate(time), new.evaluate(time * 4), places=5)
        self.assertEqual(snapshot(self.objects), original)
        self.assertEqual(ids(), allocation)
        self.assertIs(self.a.data, self.b.data)
        self.assertIs(self.a.animation_data.action, self.b.animation_data.action)

    def test_repeated_fractional_stages_preserve_all_source_slots_and_cleanup(self):
        before, allocation = snapshot(self.objects), ids()
        for attempt in range(3):
            with interchange._staging(self.objects, bpy.context, True, animation_substeps=4):
                pass
            self.assertEqual(snapshot(self.objects), before, attempt)
            self.assertEqual(ids(), allocation, attempt)
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), self.source_time)

    def test_public_preview_counts_fractional_samples_and_refuses_tighter_bound(self):
        with tempfile.TemporaryDirectory(prefix="fw-sampling-review-") as directory:
            params = {
                "object_names": [obj.name for obj in self.objects],
                "directory": directory,
                "filename": "scope",
                "include_animation": True,
                "animation_substeps": 4,
            }
            preview = interchange.export_asset(params)
            self.assertEqual(preview["animation_sampling"]["sample_count"], 13)
            before = ids()
            with self.assertRaisesRegex(ValueError, "sample"):
                interchange.export_asset({**params, "max_animation_samples": 12, "dry_run": False})
            self.assertEqual(ids(), before)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_shared_action_slots_resolve_numeric_paths_on_their_selected_owner(self):
        for obj, property_name in ((self.a, "only_a"), (self.b, "only_b")):
            for frame, value in ((0, 0.1), (3, 0.9)):
                obj[property_name] = value
                obj.keyframe_insert(data_path=f'["{property_name}"]', frame=frame)
        self.assertNotIn("only_b", self.a)
        self.assertNotIn("only_a", self.b)
        before, allocation = snapshot(self.objects), ids()
        with tempfile.TemporaryDirectory(prefix="fw-slot-owner-review-") as directory:
            preview = interchange.export_asset(
                {
                    "object_names": [obj.name for obj in self.objects],
                    "directory": directory,
                    "filename": "slots",
                    "include_animation": True,
                    "animation_substeps": 4,
                }
            )
            self.assertTrue(preview["dry_run"])
        self.assertEqual(snapshot(self.objects), before)
        self.assertEqual(ids(), allocation)

    def test_actual_export_refuses_handlers_before_unrelated_light_or_file_changes(self):
        light = bpy.data.lights.new("UnrelatedReviewLight", "POINT")
        light.energy = 123
        light_object = bpy.data.objects.new("UnrelatedReviewLight", light)
        self.scene.collection.objects.link(light_object)
        calls = []

        def callback(*args):
            calls.append(True)
            light.energy = 999

        try:
            with tempfile.TemporaryDirectory(prefix="fw-callback-review-") as directory:
                before, allocation = snapshot(self.objects), ids()
                for name in (
                    "frame_change_pre",
                    "frame_change_post",
                    "depsgraph_update_pre",
                    "depsgraph_update_post",
                ):
                    handlers = getattr(bpy.app.handlers, name)
                    handlers.append(callback)
                    try:
                        with self.subTest(handler=name):
                            with self.assertRaisesRegex(ValueError, "handler"):
                                interchange.export_asset(
                                    {
                                        "object_names": [obj.name for obj in self.objects],
                                        "directory": directory,
                                        "filename": "guarded",
                                        "format": "GLB",
                                        "include_animation": True,
                                        "animation_substeps": 4,
                                        "dry_run": False,
                                    }
                                )
                            self.assertEqual(light.energy, 123)
                            self.assertEqual(calls, [])
                            self.assertEqual(snapshot(self.objects), before)
                            self.assertEqual(ids(), allocation)
                            self.assertEqual(list(Path(directory).iterdir()), [])
                    finally:
                        handlers.remove(callback)
        finally:
            bpy.data.objects.remove(light_object, do_unlink=True)
            bpy.data.lights.remove(light)

    def test_fractional_export_rejects_action_path_into_unselected_external_id(self):
        external = bpy.data.objects.new("UnselectedAnimatedOwner", None)
        self.scene.collection.objects.link(external)
        self.a["external_owner"] = external
        animation = self.a.animation_data
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
        for substeps in (1, 4):
            with (
                self.subTest(substeps=substeps),
                tempfile.TemporaryDirectory(prefix="fw-external-action-review-") as directory,
            ):
                self.scene.frame_set(2)
                external.location.x = 0.91
                before, allocation, dirty = snapshot(self.objects), ids(), tuple(external.location)
                with self.assertRaisesRegex(ValueError, "external|dependency|local|path"):
                    interchange.export_asset(
                        {
                            "object_names": [obj.name for obj in self.objects],
                            "directory": directory,
                            "filename": "external",
                            "format": "GLB",
                            "include_animation": True,
                            "animation_substeps": substeps,
                            "dry_run": False,
                        }
                    )
                    print("EXTERNAL_ACTION_SOURCE_STATE", substeps, dirty, tuple(external.location))
                self.assertEqual(tuple(external.location), dirty)
                self.assertEqual(snapshot(self.objects), before)
                self.assertEqual(ids(), allocation)
                self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportSamplingReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
