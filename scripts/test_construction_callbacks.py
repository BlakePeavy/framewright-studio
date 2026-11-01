"""Independent callback-boundary regressions for construction and resource reads."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import production_assets as assets  # noqa: E402

KINDS = ("objects", "scenes", "collections", "meshes", "materials", "worlds", "lights", "cameras")


def inventory():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


class ConstructionCallbackTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.before = inventory()
        self.scene = bpy.data.scenes.new("CallbackConstructionSource")
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("CallbackSourceMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
        self.source = bpy.data.objects.new("AuthoredCallbackSource", mesh)
        self.scene.collection.objects.link(self.source)
        self.source["framewright_owner"] = assets.OWNER
        self.source["authored_value"] = 123
        bpy.context.view_layer.update()

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def assert_guard(self, operation):
        calls = []

        def handler(scene, graph):
            if not calls:
                calls.append(scene.name)
                self.source["authored_value"] = -999

        before = inventory()
        bpy.app.handlers.depsgraph_update_post.append(handler)
        try:
            refusal = None
            try:
                operation()
            except ValueError as error:
                refusal = error
            self.assertEqual((self.source["authored_value"], calls), (123, []))
            self.assertIsNotNone(refusal, "Active foreign callbacks require a preflight refusal")
            self.assertIn("handler", str(refusal))
            self.assertEqual(before, inventory())
            self.assertIn(handler, bpy.app.handlers.depsgraph_update_post)
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(handler)

    def test_cabinet_refuses_callbacks_before_allocating_or_updating(self):
        self.assert_guard(lambda: assets.build_prop({"dry_run": False}))

    def test_facade_refuses_callbacks_before_allocating_or_updating(self):
        self.assert_guard(lambda: assets.build_facade({"dry_run": False}))

    def test_review_refuses_callbacks_before_allocating_or_updating(self):
        self.assert_guard(
            lambda: assets.setup_review_scene(
                {"object_names": [self.source.name], "resolution": 64, "dry_run": False}
            )
        )

    def test_resources_refuses_callbacks_before_evaluating_dirty_source(self):
        self.source.location.x = 0.25
        self.assert_guard(lambda: assets.scene_resources({}))

    def test_construction_previews_remain_nonmutating_with_foreign_handlers(self):
        calls = []

        def handler(scene, graph):
            calls.append(scene.name)

        before = inventory()
        bpy.app.handlers.depsgraph_update_post.append(handler)
        try:
            self.assertTrue(assets.build_prop({})["dry_run"])
            self.assertTrue(assets.build_facade({})["dry_run"])
            self.assertTrue(
                assets.setup_review_scene({"object_names": [self.source.name]})["dry_run"]
            )
            self.assertEqual(calls, [])
            self.assertEqual(before, inventory())
            self.assertIn(handler, bpy.app.handlers.depsgraph_update_post)
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(handler)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ConstructionCallbackTests)
    )
    if not outcome.wasSuccessful():
        raise SystemExit(1)
