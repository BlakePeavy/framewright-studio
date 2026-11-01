"""Baking must not reevaluate the unchanged source time or run foreign handlers."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import baking  # noqa: E402

KINDS = ("objects", "scenes", "collections", "meshes", "materials", "images", "lights")


def ids():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


class BakePreservationReview(unittest.TestCase):
    def setUp(self):
        self.before = ids()
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("BakePreservationSource")
        bpy.context.window.scene = self.scene
        self.objects = []
        for name, z in (("High", 0.02), ("Low", 0)):
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata([(0, 0, z), (1, 0, z), (1, 1, z), (0, 1, z)], [], [(0, 1, 2, 3)])
            uv = mesh.uv_layers.new(name="UVMap")
            for item, point in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
                item.uv = point
            obj = bpy.data.objects.new(name, mesh)
            self.scene.collection.objects.link(obj)
            self.objects.append(obj)
        self.light = bpy.data.lights.new("UnrelatedAnimatedLight", "AREA")
        obj = bpy.data.objects.new(self.light.name, self.light)
        self.scene.collection.objects.link(obj)
        for frame, energy in ((1, 10), (5, 20)):
            self.light.energy = energy
            self.light.keyframe_insert("energy", frame=frame)
        self.scene.frame_set(2, subframe=0.25)
        self.light.energy = 123.456
        self.params = {
            "high_object": self.objects[0].name,
            "low_object": self.objects[1].name,
            "resolution": 64,
            "dry_run": False,
        }

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def state(self):
        return self.light.energy, self.scene.frame_current, self.scene.frame_subframe

    def test_success_preserves_unkeyed_authored_light_at_unchanged_source_time(self):
        before = self.state()
        baking.bake_normal(self.params)
        self.assertEqual(before, self.state())

    def test_failure_preserves_unkeyed_authored_light_and_cleans_owned_data(self):
        before, data = self.state(), ids()
        with patch.object(baking, "_bake", side_effect=RuntimeError("injected bake failure")):
            with self.assertRaisesRegex(RuntimeError, "injected bake failure"):
                baking.bake_normal(self.params)
        self.assertEqual(before, self.state())
        self.assertEqual(data, ids())

    def test_preview_and_apply_refuse_graph_callbacks_before_evaluation(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                calls = []

                def foreign_handler(scene, graph, observed=calls):
                    if not observed:
                        observed.append(scene.name)
                        self.light.energy = 999

                before, data = self.state(), ids()
                bpy.app.handlers.depsgraph_update_post.append(foreign_handler)
                try:
                    refusal = None
                    try:
                        baking.bake_normal({**self.params, "dry_run": dry_run})
                    except ValueError as error:
                        refusal = error
                    self.assertEqual(before, self.state())
                    self.assertEqual(calls, [])
                    self.assertIsNotNone(refusal)
                    self.assertIn("handler", str(refusal))
                    self.assertEqual(data, ids())
                    self.assertIn(foreign_handler, bpy.app.handlers.depsgraph_update_post)
                finally:
                    bpy.app.handlers.depsgraph_update_post.remove(foreign_handler)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BakePreservationReview)
    )
    if not outcome.wasSuccessful():
        raise SystemExit(1)
