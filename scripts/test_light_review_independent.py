"""Independent source-preservation and late-failure review of the lighting fixture."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from test_light_review import ids  # noqa: E402

from framewright import light_review  # noqa: E402


class IndependentLightingTests(unittest.TestCase):
    def setUp(self):
        self.before = ids()
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("IndependentLightingSource")
        bpy.context.window.scene = self.scene
        self.source = bpy.data.objects.new("AuthoredSource", None)
        self.scene.collection.objects.link(self.source)

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in (
            "objects",
            "scenes",
            "collections",
            "meshes",
            "materials",
            "worlds",
            "cameras",
            "lights",
            "images",
        ):
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def test_dirty_light_material_constraint_channels_survive_scene_creation(self):
        light = bpy.data.lights.new("AuthoredDirtyLight", "AREA")
        light_obj = bpy.data.objects.new("AuthoredDirtyLight", light)
        self.scene.collection.objects.link(light_obj)
        material = bpy.data.materials.new("AuthoredDirtyMaterial")
        material.use_nodes = True
        socket = material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"]
        constraint = self.source.constraints.new("LIMIT_LOCATION")
        for frame, amount in ((1, 0.1), (3, 0.9)):
            light.energy = amount * 100
            light.keyframe_insert("energy", frame=frame)
            socket.default_value = amount
            socket.keyframe_insert("default_value", frame=frame)
            constraint.influence = amount
            constraint.keyframe_insert("influence", frame=frame)
        self.scene.frame_set(2, subframe=0.25)
        light.energy = 123.456
        socket.default_value = 0.1234
        constraint.influence = 0.4321
        before = (
            light.energy,
            socket.default_value,
            constraint.influence,
            self.scene.frame_current,
            self.scene.frame_subframe,
        )
        light_review.create_interior_fixture({"resolution": 64, "samples": 1, "dry_run": False})
        self.assertEqual(
            (
                light.energy,
                socket.default_value,
                constraint.influence,
                self.scene.frame_current,
                self.scene.frame_subframe,
            ),
            before,
        )

    def test_global_depsgraph_handler_refused_before_source_mutation_or_allocation(self):
        self.source["authored_value"] = 123
        called = []

        def foreign_handler(scene, graph):
            if not called:
                called.append(scene.name)
                self.source["authored_value"] = -999

        before = ids()
        bpy.app.handlers.depsgraph_update_post.append(foreign_handler)
        try:
            refusal = None
            try:
                light_review.create_interior_fixture(
                    {"resolution": 64, "samples": 1, "dry_run": False}
                )
            except ValueError as error:
                refusal = error
            self.assertEqual((self.source["authored_value"], called), (123, []))
            self.assertIsNotNone(
                refusal, "Foreign callbacks must be refused before fixture updates"
            )
            self.assertIn("handler", str(refusal))
            self.assertEqual(ids(), before)
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(foreign_handler)

    def test_late_camera_failure_removes_every_owned_datablock(self):
        before = ids()
        add = light_review._Transaction.add
        camera_count = []

        def fail_late(transaction, kind, item):
            value = add(transaction, kind, item)
            if kind == "cameras":
                camera_count.append(1)
                if len(camera_count) == 2:
                    raise RuntimeError("injected late camera failure")
            return value

        with patch.object(light_review._Transaction, "add", fail_late):
            with self.assertRaisesRegex(RuntimeError, "late camera"):
                light_review.create_interior_fixture(
                    {"resolution": 64, "samples": 1, "dry_run": False}
                )
        self.assertEqual(ids(), before)

    def test_all_four_callback_categories_allow_preview_but_refuse_apply(self):
        before = ids()
        calls = []

        def foreign_handler(*args):
            calls.append(args)

        for name in (
            "frame_change_pre",
            "frame_change_post",
            "depsgraph_update_pre",
            "depsgraph_update_post",
        ):
            with self.subTest(handler=name):
                callbacks = getattr(bpy.app.handlers, name)
                callbacks.append(foreign_handler)
                try:
                    report = light_review.create_interior_fixture({})
                    self.assertTrue(report["dry_run"])
                    with self.assertRaisesRegex(ValueError, "handler"):
                        light_review.create_interior_fixture({"dry_run": False})
                    self.assertEqual(ids(), before)
                    self.assertEqual(calls, [])
                finally:
                    callbacks.remove(foreign_handler)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(IndependentLightingTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Independent lighting review failed")
    print(f"FRAMEWRIGHT_LIGHT_REVIEW_INDEPENDENT_OK tests={result.testsRun}")
