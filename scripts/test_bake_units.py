"""Normal projection distances are physical metres in any authoring scene units."""

import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from test_surface_render_parity import source_hash  # noqa: E402

from framewright import baking  # noqa: E402

KINDS = ("objects", "scenes", "collections", "meshes", "materials", "images")


class BakeUnitTests(unittest.TestCase):
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

    def fixture(self, scale, high_offset=0.01):
        scene = bpy.data.scenes.new("BakeMetreSource")
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = scale
        bpy.context.window.scene = scene
        unit = scene.unit_settings.scale_length
        objects = []
        for name, heights in (
            ("High", (high_offset, high_offset + 0.02, high_offset + 0.02, high_offset)),
            ("Low", (0, 0, 0, 0)),
            ("Cage", (0.04, 0.04, 0.04, 0.04)),
        ):
            mesh = bpy.data.meshes.new(name)
            points = [
                (x / unit, y / unit, z / unit)
                for (x, y), z in zip(((0, 0), (1, 0), (1, 1), (0, 1)), heights, strict=True)
            ]
            mesh.from_pydata(points, [], [(0, 1, 2, 3)])
            uv = mesh.uv_layers.new(name="UV")
            for loop, point in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
                loop.uv = point
            obj = bpy.data.objects.new(name, mesh)
            scene.collection.objects.link(obj)
            obj.location = Vector((1, 2, 0)) / unit
            objects.append(obj)
        bpy.context.view_layer.update()
        return scene, objects

    def test_physical_projection_and_returned_geometry_match_across_units(self):
        for explicit_cage in (False, True):
            reference = None
            for scale in (1, 0.01, 10):
                with self.subTest(scale=scale, cage=explicit_cage):
                    scene, sources = self.fixture(scale)
                    high, low, cage = sources
                    before = source_hash(sources)
                    unit = scene.unit_settings.scale_length
                    result = baking.bake_normal(
                        {
                            "high_object": high.name,
                            "low_object": low.name,
                            "cage_object": cage.name if explicit_cage else "",
                            "ray_distance": 0.05,
                            "resolution": 64,
                            "dry_run": False,
                        }
                    )
                    self.assertEqual(result["projection"]["hit_fraction"], 1)
                    derivative = bpy.data.objects[result["derivative"]]
                    for first, second in zip(
                        low.data.vertices, derivative.data.vertices, strict=True
                    ):
                        self.assertLess(
                            (
                                (low.matrix_world @ first.co - derivative.matrix_world @ second.co)
                                * unit
                            ).length,
                            1e-6,
                        )
                    image = bpy.data.images[result["image"]]
                    values = array("f", [0]) * len(image.pixels)
                    image.pixels.foreach_get(values)
                    if reference is None:
                        reference = values
                    else:
                        self.assertLess(
                            max(abs(a - b) for a, b in zip(reference, values, strict=True)), 2e-5
                        )
                    self.assertEqual(source_hash(sources), before)
                    self.assertEqual(scene.unit_settings.scale_length, unit)
                    self.assertIs(bpy.context.scene, scene)

    def test_distant_physical_surface_refuses_even_in_large_scene_units(self):
        scene, sources = self.fixture(10, high_offset=0.2)
        high, low, _ = sources
        before = source_hash(sources)
        inventory = {
            kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS
        }
        with self.assertRaisesRegex(ValueError, "projection|surface"):
            baking.bake_normal(
                {
                    "high_object": high.name,
                    "low_object": low.name,
                    "ray_distance": 0.05,
                    "resolution": 64,
                    "dry_run": False,
                }
            )
        self.assertEqual(source_hash(sources), before)
        self.assertIs(bpy.context.scene, scene)
        self.assertEqual(
            inventory,
            {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS},
        )

    @staticmethod
    def reexpress(obj, scale):
        points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        matrix = Matrix.Translation(obj.matrix_world.translation) @ Matrix.Diagonal((*scale, 1))
        inverse = matrix.inverted()
        for vertex, point in zip(obj.data.vertices, points, strict=True):
            vertex.co = inverse @ point
        obj.matrix_world = matrix
        obj.data.update()

    def test_implicit_cage_uniform_object_scale_keeps_same_physical_projection(self):
        reference = None
        for scale in (1, 0.2, 3):
            with self.subTest(scale=scale):
                _, sources = self.fixture(1)
                high, low, _ = sources
                self.reexpress(low, (scale, scale, scale))
                bpy.context.view_layer.update()
                before = source_hash(sources)
                result = baking.bake_normal(
                    {
                        "high_object": high.name,
                        "low_object": low.name,
                        "ray_distance": 0.05,
                        "resolution": 64,
                        "dry_run": False,
                    }
                )
                values = array("f", [0]) * len(bpy.data.images[result["image"]].pixels)
                bpy.data.images[result["image"]].pixels.foreach_get(values)
                if reference is None:
                    reference = values
                else:
                    self.assertLess(
                        max(abs(a - b) for a, b in zip(reference, values, strict=True)), 2e-5
                    )
                self.assertEqual(source_hash(sources), before)

    def test_implicit_nonuniform_low_scale_refuses_before_bake_allocation(self):
        _, sources = self.fixture(1)
        high, low, _ = sources
        self.reexpress(low, (2, 3, 4))
        bpy.context.view_layer.update()
        before = source_hash(sources)
        inventory = {
            kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS
        }
        for dry in (True, False):
            with (
                self.subTest(dry=dry),
                self.assertRaisesRegex(ValueError, "uniform|explicit.*cage"),
            ):
                baking.bake_normal(
                    {
                        "high_object": high.name,
                        "low_object": low.name,
                        "ray_distance": 0.05,
                        "resolution": 64,
                        "dry_run": dry,
                    }
                )
        self.assertEqual(source_hash(sources), before)
        self.assertEqual(
            inventory,
            {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS},
        )

    def test_explicit_cage_nonuniform_low_scale_captures_correct_world_normal(self):
        _, sources = self.fixture(0.01)
        high, low, cage = sources
        self.reexpress(low, (2, 3, 4))
        bpy.context.view_layer.update()
        before = source_hash(sources)
        result = baking.bake_normal(
            {
                "high_object": high.name,
                "low_object": low.name,
                "cage_object": cage.name,
                "ray_distance": 0.05,
                "resolution": 64,
                "dry_run": False,
            }
        )
        image = bpy.data.images[result["image"]]
        values = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(values)
        index = (32 * 64 + 32) * 4
        tangent = Vector([values[index + i] * 2 - 1 for i in range(3)])
        world = (low.matrix_world.to_3x3().inverted().transposed() @ tangent).normalized()
        expected = Vector((-0.02, 0, 1)).normalized()
        self.assertLess((world - expected).length, 2e-4)
        self.assertEqual(source_hash(sources), before)

    def test_sheared_parent_worlds_refuse_before_bake_in_preview_and_apply(self):
        for role in (0, 1, 2):
            with self.subTest(role=role):
                scene, sources = self.fixture(1)
                parent = bpy.data.objects.new("ShearingParent", None)
                scene.collection.objects.link(parent)
                parent.scale = (2, 1, 1)
                source = sources[role]
                source.parent = parent
                source.rotation_euler.z = 0.6
                bpy.context.view_layer.update()
                before = source_hash(sources)
                inventory = {
                    kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS
                }
                high, low, cage = sources
                for dry in (True, False):
                    with self.subTest(dry=dry), self.assertRaisesRegex(ValueError, "shear"):
                        baking.bake_normal(
                            {
                                "high_object": high.name,
                                "low_object": low.name,
                                "cage_object": cage.name,
                                "ray_distance": 0.05,
                                "resolution": 64,
                                "dry_run": dry,
                            }
                        )
                self.assertEqual(source_hash(sources), before)
                self.assertEqual(
                    inventory,
                    {
                        kind: {item.as_pointer() for item in getattr(bpy.data, kind)}
                        for kind in KINDS
                    },
                )

    def test_singular_worlds_and_reflected_implicit_low_fail_before_staging(self):
        for role, scale, explicit in (
            (0, (0, 1, 1), True),
            (1, (1, 0, 1), True),
            (2, (1, 1, 0), True),
            (1, (-1, 1, 1), False),
        ):
            with self.subTest(role=role, scale=scale, explicit=explicit):
                _, sources = self.fixture(1)
                high, low, cage = sources
                sources[role].scale = scale
                bpy.context.view_layer.update()
                before = source_hash(sources)
                inventory = {
                    kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS
                }
                for dry in (True, False):
                    with (
                        self.subTest(dry=dry),
                        self.assertRaisesRegex(ValueError, "nonsingular|positive uniform"),
                    ):
                        baking.bake_normal(
                            {
                                "high_object": high.name,
                                "low_object": low.name,
                                "cage_object": cage.name if explicit else "",
                                "ray_distance": 0.05,
                                "resolution": 64,
                                "dry_run": dry,
                            }
                        )
                self.assertEqual(source_hash(sources), before)
                self.assertEqual(
                    inventory,
                    {
                        kind: {item.as_pointer() for item in getattr(bpy.data, kind)}
                        for kind in KINDS
                    },
                )


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BakeUnitTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
