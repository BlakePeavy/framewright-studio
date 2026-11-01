"""Isolated Cycles normal-bake acceptance tests using generated geometry."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import baking  # noqa: E402


def counts():
    return tuple(
        len(getattr(bpy.data, kind))
        for kind in ("scenes", "objects", "meshes", "images", "materials", "collections")
    )


def fixture():
    scene = bpy.context.scene
    low_mesh = bpy.data.meshes.new("BakeLowMesh")
    low_mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    low_mesh.update()
    uv = low_mesh.uv_layers.new(name="BakeUV")
    for index, coord in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[index].uv = coord
    low = bpy.data.objects.new("BakeLow", low_mesh)
    scene.collection.objects.link(low)
    vertices, faces = [], []
    divisions = 24
    for y in range(divisions + 1):
        for x in range(divisions + 1):
            px, py = -1 + 2 * x / divisions, -1 + 2 * y / divisions
            height = 0.02 + 0.045 * (math.sin(px * 5) * math.cos(py * 4) + 1) / 2
            vertices.append((px, py, height))
    for y in range(divisions):
        for x in range(divisions):
            index = y * (divisions + 1) + x
            faces.append((index, index + 1, index + divisions + 2, index + divisions + 1))
    high_mesh = bpy.data.meshes.new("BakeHighMesh")
    high_mesh.from_pydata(vertices, [], faces)
    high_mesh.update()
    high = bpy.data.objects.new("BakeHigh", high_mesh)
    scene.collection.objects.link(high)
    bpy.context.view_layer.update()
    return high, low


class BakingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.high, cls.low = fixture()

    def params(self, **extra):
        return {
            "high_object": self.high.name,
            "low_object": self.low.name,
            "resolution": 64,
            **extra,
        }

    def test_01_dry_run_does_not_allocate(self):
        before = counts()
        result = baking.bake_normal(self.params())
        self.assertTrue(result["dry_run"])
        self.assertGreater(result["estimated_image_working_bytes"], 0)
        self.assertEqual(counts(), before)

    def test_02_large_allocation_requires_explicit_budget(self):
        before = counts()
        with self.assertRaisesRegex(ValueError, "budget"):
            baking.bake_normal(self.params(resolution=8192, dry_run=False))
        self.assertEqual(counts(), before)

    def test_03_missing_uv_same_source_and_bad_params_rejected(self):
        for params in (
            self.params(low_object=self.high.name),
            self.params(high_object=self.low.name),
            self.params(ray_distance=-1),
            self.params(dry_run=0),
        ):
            with self.assertRaises(ValueError):
                baking.bake_normal(params)

    def test_04_actual_normal_bake_has_detail_and_preserves_sources(self):
        old_scene = bpy.context.scene
        old_active = bpy.context.view_layer.objects.active
        old_selection = tuple(bpy.context.selected_objects)
        old_uv = [tuple(item.uv) for item in self.low.data.uv_layers[0].data]
        old_materials = list(self.low.data.materials)
        old_vertices = [tuple(vertex.co) for vertex in self.high.data.vertices]
        result = baking.bake_normal(self.params(dry_run=False))
        image = bpy.data.images[result["image"]]
        derivative = bpy.data.objects[result["derivative"]]
        self.assertIsNot(derivative.data, self.low.data)
        self.assertEqual(image.colorspace_settings.name, "Non-Color")
        self.assertTrue(image.packed_file)
        self.assertTrue(result["detail_present"])
        self.assertGreater(result["valid_normal_pixels"], 64 * 64 * 0.9)
        self.assertGreater(max(result["channel_ranges"][:2]), 0.05)
        self.assertEqual([tuple(item.uv) for item in self.low.data.uv_layers[0].data], old_uv)
        self.assertEqual(list(self.low.data.materials), old_materials)
        self.assertEqual([tuple(vertex.co) for vertex in self.high.data.vertices], old_vertices)
        self.assertIs(bpy.context.scene, old_scene)
        self.assertIs(bpy.context.view_layer.objects.active, old_active)
        self.assertEqual(tuple(bpy.context.selected_objects), old_selection)
        self.assertTrue(derivative.hide_render)

    def test_05_failed_bake_cleans_created_data(self):
        before = counts()
        with patch.object(baking, "_bake", side_effect=RuntimeError("Injected bake failure")):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                baking.bake_normal(self.params(dry_run=False))
        self.assertEqual(counts(), before)

    def test_06_missing_projection_surface_is_rejected(self):
        old_location = self.high.location.copy()
        before = counts()
        try:
            self.high.location.z = 4
            bpy.context.view_layer.update()
            with self.assertRaisesRegex(ValueError, "projection"):
                baking.bake_normal(self.params(dry_run=False))
        finally:
            self.high.location = old_location
            bpy.context.view_layer.update()
        self.assertEqual(counts(), before)

    def test_07_blank_bake_never_publishes_a_derivative(self):
        before = counts()

        def blank_result(stage, high, low, params):
            image = low.data.materials[0].node_tree.nodes.active.image
            image.pixels.foreach_set([0.0] * len(image.pixels))

        with patch.object(baking, "_bake", side_effect=blank_result):
            with self.assertRaisesRegex(RuntimeError, "no valid tangent normals"):
                baking.bake_normal(self.params(dry_run=False))
        self.assertEqual(counts(), before)

    def test_08_ambiguous_or_outside_single_tile_uvs_rejected_before_allocation(self):
        for mode in ("overlap", "collapsed", "outside"):
            mesh = bpy.data.meshes.new("UnsafeUV")
            mesh.from_pydata(
                [
                    (-1, -1, 0),
                    (1, -1, 0),
                    (1, 1, 0),
                    (-1, 1, 0),
                    (2, -1, 0),
                    (4, -1, 0),
                    (4, 1, 0),
                    (2, 1, 0),
                ],
                [],
                [(0, 1, 2, 3), (4, 5, 6, 7)],
            )
            mesh.update()
            uv = mesh.uv_layers.new()
            for index in range(8):
                coordinate = ((0, 0), (1, 0), (1, 1), (0, 1))[index % 4]
                if mode == "collapsed" and index >= 4:
                    coordinate = (0, 0)
                if mode == "outside":
                    coordinate = (coordinate[0] + 1, coordinate[1])
                uv.data[index].uv = coordinate
            obj = bpy.data.objects.new("UnsafeUV", mesh)
            bpy.context.scene.collection.objects.link(obj)
            bpy.context.view_layer.update()
            before = counts()
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "UV"):
                baking.bake_normal(self.params(low_object=obj.name))
            self.assertEqual(counts(), before)

    def test_09_explicit_cage_bake_preserves_source_and_refuses_wrong_topology(self):
        cage = self.low.copy()
        cage.data = self.low.data.copy()
        cage.name = "AuthoredCage"
        for vertex in cage.data.vertices:
            vertex.co.z = 0.12
        bpy.context.scene.collection.objects.link(cage)
        bpy.context.view_layer.update()
        original = [tuple(v.co) for v in cage.data.vertices]
        result = baking.bake_normal(self.params(cage_object=cage.name, dry_run=False))
        self.assertTrue(result["detail_present"])
        self.assertEqual(result["cage"], cage.name)
        self.assertEqual([tuple(v.co) for v in cage.data.vertices], original)
        wrong = cage.copy()
        wrong.data = self.high.data.copy()
        bpy.context.scene.collection.objects.link(wrong)
        with self.assertRaisesRegex(ValueError, "topology"):
            baking.bake_normal(self.params(cage_object=wrong.name))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BakingTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Baking acceptance tests failed")
