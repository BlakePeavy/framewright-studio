"""Independent conversion-boundary review: omitted parents and bake assignments."""

import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import baking, production_assets  # noqa: E402

KINDS = (
    "objects",
    "scenes",
    "collections",
    "meshes",
    "materials",
    "images",
    "cameras",
    "lights",
    "worlds",
)


def inventory():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


class FinalUnitReview(unittest.TestCase):
    def setUp(self):
        self.before = inventory()
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("FinalUnitReview")
        bpy.context.window.scene = self.scene

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def object(self, name, points, faces):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(points, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        obj["framewright_owner"] = production_assets.OWNER
        return obj

    def test_review_omitted_shearing_parent_preserves_world_geometry_or_refuses(self):
        self.scene.unit_settings.scale_length = 0.01
        source = self.object(
            "Authored",
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
            [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
        )
        parent = bpy.data.objects.new("OmittedParent", None)
        self.scene.collection.objects.link(parent)
        parent.scale = (2, 1, 1)
        parent.rotation_euler = (0.3, -0.4, 0.5)
        source.parent = parent
        source.rotation_euler.z = 0.6
        bpy.context.view_layer.update()
        before = inventory()
        matrix = source.matrix_world.copy()
        expected = [
            source.matrix_world @ vertex.co * self.scene.unit_settings.scale_length
            for vertex in source.data.vertices
        ]
        try:
            result = production_assets.setup_review_scene(
                {"object_names": [source.name], "resolution": 64, "dry_run": False}
            )
        except ValueError as error:
            self.assertRegex(str(error), "parent|shear")
            self.assertEqual(inventory(), before)
            return
        review = bpy.data.scenes[result["scene"]]
        review.view_layers[0].update()
        copy = bpy.data.objects[result["copies"][source.name]]
        actual = [copy.matrix_world @ vertex.co for vertex in copy.data.vertices]
        self.assertLess(max((a - b).length for a, b in zip(expected, actual, strict=True)), 1e-6)
        self.assertEqual(source.matrix_world, matrix)

    def bake_fixture(self):
        points = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
        faces = [(0, 1, 4, 3), (1, 2, 5, 4)]
        low = self.object("Low", points, faces)
        high = self.object("High", [(x, y, 0.02 + 0.01 * x) for x, y, z in points], faces)
        uv = low.data.uv_layers.new(name="Atlas")
        for poly in low.data.polygons:
            for index in poly.loop_indices:
                point = low.data.vertices[low.data.loops[index].vertex_index].co
                uv.data[index].uv = (point.x / 2, point.y)
        for index, color in enumerate(((0.8, 0.1, 0.1, 1), (0.1, 0.1, 0.8, 1))):
            material = bpy.data.materials.new(f"Surface{index}")
            material.diffuse_color = color
            material.node_tree.nodes.get("Principled BSDF").inputs[
                "Base Color"
            ].default_value = color
            low.data.materials.append(material)
            low.data.polygons[index].material_index = index
        bpy.context.view_layer.update()
        return high, low

    def bake(self, high, low):
        return baking.bake_normal(
            {
                "high_object": high.name,
                "low_object": low.name,
                "ray_distance": 0.1,
                "resolution": 64,
                "dry_run": False,
            }
        )

    def test_bake_retains_multiple_polygon_material_assignments(self):
        high, low = self.bake_fixture()
        original = [face.material_index for face in low.data.polygons]
        result = self.bake(high, low)
        copy = bpy.data.objects[result["derivative"]]
        self.assertEqual([face.material_index for face in low.data.polygons], original)
        self.assertEqual([face.material_index for face in copy.data.polygons], original)

    def test_bake_uses_object_slot_surface_without_editing_shared_authored_image(self):
        high, low = self.bake_fixture()
        authored = bpy.data.materials.new("AuthoredObjectOverride")
        authored.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
            0.1,
            0.8,
            0.1,
            1,
        )
        image = bpy.data.images.new("AuthoredExistingImage", 64, 64, alpha=True, float_buffer=True)
        initial = array("f", [0.2, 0.3, 0.4, 1]) * (64 * 64)
        image.pixels.foreach_set(initial)
        texture = authored.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        authored.node_tree.nodes.active = texture
        low.material_slots[0].link = "OBJECT"
        low.material_slots[0].material = authored
        before = [
            tuple(
                slot.material.node_tree.nodes.get("Principled BSDF")
                .inputs["Base Color"]
                .default_value
            )
            for slot in low.material_slots
        ]
        result = self.bake(high, low)
        observed = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(observed)
        self.assertEqual(observed, initial, "Baking changed a shared source image")
        copy = bpy.data.objects[result["derivative"]]
        actual = [
            tuple(
                slot.material.node_tree.nodes.get("Principled BSDF")
                .inputs["Base Color"]
                .default_value
            )
            for slot in copy.material_slots
        ]
        self.assertEqual(
            actual, before, "Returned derivative lost the effective OBJECT-linked surface"
        )
        self.assertEqual(
            [slot.link for slot in copy.material_slots], [slot.link for slot in low.material_slots]
        )
        self.assertTrue(
            all(
                derived.material is not source.material
                for derived, source in zip(copy.material_slots, low.material_slots, strict=True)
            )
        )
        self.assertIs(low.material_slots[0].material, authored)

    def test_review_rejects_material_driver_that_writes_an_external_id_before_evaluation(self):
        source = self.object("DrivenReviewSource", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        external = bpy.data.objects.new("UnrelatedAuthoredObject", None)
        self.scene.collection.objects.link(external)
        material = bpy.data.materials.new("NativeDriverMaterial")
        source.data.materials.append(material)
        material["external_owner"] = external
        curve = material.driver_add("diffuse_color", 0)
        curve.data_path = '["external_owner"].location'
        curve.driver.expression = "0.7"
        self.scene.frame_set(2)
        self.assertAlmostEqual(external.location.x, 0.7, places=6)
        for dry in (True, False):
            with self.subTest(dry=dry):
                external.location.x = 0.91
                material.update_tag()
                before = tuple(external.location)
                identities = inventory()
                with self.assertRaisesRegex(ValueError, "static|animation|driver"):
                    production_assets.setup_review_scene(
                        {"object_names": [source.name], "resolution": 64, "dry_run": dry}
                    )
                self.assertEqual(tuple(external.location), before)
                self.assertEqual(inventory(), identities)
                self.assertIs(source.data.materials[0], material)
                self.assertEqual(curve.data_path, '["external_owner"].location')


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FinalUnitReview)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
