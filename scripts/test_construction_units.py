"""Metre-authored geometry and review scenes retain physical scale across scene units."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from framewright import production_assets as assets  # noqa: E402

KINDS = ("objects", "scenes", "collections", "meshes", "materials", "worlds", "lights", "cameras")


class ConstructionUnitsTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.before = {
            kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS
        }

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def scene(self, scale):
        scene = bpy.data.scenes.new("MetreContract")
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = scale
        bpy.context.window.scene = scene
        return scene

    def assert_builder_scale(self, function, parameters):
        expected = None
        for scale in (1, 0.01, 10):
            with self.subTest(scale=scale):
                scene = self.scene(scale)
                source_scale = scene.unit_settings.scale_length
                result = function({"location": [1.25, -2.75, 0.5], "dry_run": False, **parameters})
                self.assertEqual(scene.unit_settings.scale_length, source_scale)
                self.assertEqual(result["units"], "metres")
                actual = [
                    tuple((obj.matrix_world @ vertex.co) * source_scale)
                    for obj in sorted(
                        bpy.data.collections[result["collection"]].objects,
                        key=lambda item: item.name.rsplit(".", 1)[0],
                    )
                    if obj.type == "MESH"
                    for vertex in obj.data.vertices
                ]
                if expected is None:
                    expected = actual
                else:
                    self.assertEqual(len(expected), len(actual))
                    maximum = max(
                        abs(a - b)
                        for first, second in zip(expected, actual, strict=True)
                        for a, b in zip(first, second, strict=True)
                    )
                    self.assertLess(
                        maximum, 5e-5, "Metre geometry changed with the authoring scene unit scale"
                    )

    def test_cabinet_dimensions_location_and_open_door_are_metres(self):
        self.assert_builder_scale(assets.build_prop, {"door_open_degrees": 65})

    def test_facade_dimensions_and_location_are_metres(self):
        self.assert_builder_scale(assets.build_facade, {})

    def test_review_copies_preserve_physical_world_positions_and_source_units(self):
        for scale in (0.01, 10):
            with self.subTest(scale=scale):
                scene = self.scene(scale)
                source_scale = scene.unit_settings.scale_length
                mesh = bpy.data.meshes.new("PhysicalSourceMesh")
                mesh.from_pydata(
                    [(0, 0, 0), (1 / scale, 0, 0), (0, 1 / scale, 0), (0, 0, 1 / scale)],
                    [],
                    [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
                )
                source = bpy.data.objects.new("PhysicalSource", mesh)
                scene.collection.objects.link(source)
                source.location = Vector((1, 2, 3)) / scale
                source["framewright_owner"] = assets.OWNER
                bpy.context.view_layer.update()
                raw = source.matrix_world.copy()
                expected = [
                    source.matrix_world @ vertex.co * source_scale for vertex in mesh.vertices
                ]
                result = assets.setup_review_scene(
                    {"object_names": [source.name], "resolution": 64, "dry_run": False}
                )
                review = bpy.data.scenes[result["scene"]]
                copy = bpy.data.objects[result["copies"][source.name]]
                review.view_layers[0].update()
                actual = [
                    copy.matrix_world @ vertex.co * review.unit_settings.scale_length
                    for vertex in copy.data.vertices
                ]
                self.assertLess(
                    max((a - b).length for a, b in zip(expected, actual, strict=True)), 5e-5
                )
                self.assertEqual(source.matrix_world, raw)
                self.assertEqual(scene.unit_settings.scale_length, source_scale)
                self.assertIs(bpy.context.scene, scene)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ConstructionUnitsTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
