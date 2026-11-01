"""FBX scalar staging budgets, precision, independent IDs and failure cleanup."""

from __future__ import annotations

import math
import struct
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from test_pbr_map_handoff import fixture  # noqa: E402
from test_surface_render_parity import source_hash  # noqa: E402

from framewright import export_materials, interchange  # noqa: E402


def ids():
    return {
        name: set(getattr(bpy.data, name))
        for name in ("objects", "meshes", "materials", "images", "scenes")
    }


class ExportMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.initial = ids()
        self.folder = tempfile.TemporaryDirectory(prefix="framewright-scalar-test-")
        self.path = Path(self.folder.name)
        self.sphere, self.recipe = fixture(self.path)
        self.material = self.sphere.data.materials[0]
        self.params = {
            "object_names": [self.sphere.name],
            "directory": str(self.path),
            "format": "FBX",
            "filename": "test",
            "dry_run": False,
        }

    def tearDown(self):
        for name, previous in self.initial.items():
            store = getattr(bpy.data, name)
            for item in set(store) - previous:
                store.remove(item, do_unlink=True)
        self.folder.cleanup()

    def test_preview_allocates_no_ids_or_files_and_reports_conversion_budget(self):
        before, files, original = ids(), set(self.path.iterdir()), source_hash([self.sphere])
        result = interchange.export_asset(dict(self.params, dry_run=True))
        self.assertEqual(
            result["scalar_texture_staging"]["estimated_temporary_bytes"], 64 * 64 * 64 * 2
        )
        self.assertEqual(len(result["scalar_texture_staging"]["maps"]), 2)
        self.assertEqual(ids(), before)
        self.assertEqual(set(self.path.iterdir()), files)
        self.assertEqual(source_hash([self.sphere]), original)

    def test_budget_rejects_before_staging(self):
        self.material.node_tree.nodes["FW_roughness"].image.scale(256, 256)
        before, files = ids(), set(self.path.iterdir())
        with self.assertRaisesRegex(ValueError, "max_material_memory_mb"):
            interchange.export_asset(dict(self.params, max_material_memory_mb=1))
        self.assertEqual(ids(), before)
        self.assertEqual(set(self.path.iterdir()), files)

    def test_parameter_types_and_limits(self):
        for value in (True, 0, -1, 32769, 1.5, "512"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "max_material_memory_mb"),
            ):
                interchange.export_asset(dict(self.params, max_material_memory_mb=value))

    def test_non_red_or_non_color_graph_rejected_before_allocation(self):
        shader = next(
            node for node in self.material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
        )
        socket = shader.inputs["Roughness"]
        separate = socket.links[0].from_node
        self.material.node_tree.links.new(separate.outputs["Green"], socket)
        before, files = ids(), set(self.path.iterdir())
        with self.assertRaisesRegex(ValueError, "red-channel"):
            interchange.export_asset(self.params)
        self.material.node_tree.links.new(separate.outputs["Red"], socket)
        self.material.node_tree.nodes["FW_roughness"].image.colorspace_settings.name = "sRGB"
        with self.assertRaisesRegex(ValueError, "Non-Color"):
            interchange.export_asset(self.params)
        self.assertEqual(ids(), before)
        self.assertEqual(set(self.path.iterdir()), files)

    def test_explicit_uv_graph_rejected_instead_of_silently_losing_mapping(self):
        uv = self.material.node_tree.nodes.new("ShaderNodeUVMap")
        self.material.node_tree.links.new(
            uv.outputs["UV"], self.material.node_tree.nodes["FW_roughness"].inputs["Vector"]
        )
        before = ids()
        with self.assertRaisesRegex(ValueError, "default UVs"):
            interchange.export_asset(self.params)
        self.assertEqual(ids(), before)

    def test_owned_materials_restore_after_exporter_failure(self):
        before, files, original = ids(), set(self.path.iterdir()), source_hash([self.sphere])

        def fail_export(**kwargs):
            raise RuntimeError("export injected")

        with (
            patch.object(
                interchange.bpy,
                "ops",
                SimpleNamespace(export_scene=SimpleNamespace(fbx=fail_export)),
            ),
            self.assertRaisesRegex(RuntimeError, "export injected"),
        ):
            interchange.export_asset(self.params)
        self.assertEqual(ids(), before)
        self.assertEqual(set(self.path.iterdir()), files)
        self.assertEqual(source_hash([self.sphere]), original)

    def test_partial_scalar_file_failure_cleans_owned_ids_and_temp_files(self):
        before, files, original = ids(), set(self.path.iterdir()), source_hash([self.sphere])

        def fail(image, path):
            path.write_bytes(b"partial")
            raise RuntimeError("scalar injected")

        with (
            patch.object(export_materials, "_write_red_png", side_effect=fail),
            self.assertRaisesRegex(RuntimeError, "scalar injected"),
        ):
            interchange.export_asset(self.params)
        self.assertEqual(ids(), before)
        self.assertEqual(set(self.path.iterdir()), files)
        self.assertEqual(source_hash([self.sphere]), original)

    def test_shared_and_object_linked_slots_get_owned_material_only(self):
        other = self.sphere.copy()
        other.data = self.sphere.data.copy()
        bpy.context.scene.collection.objects.link(other)
        other.material_slots[0].link = "OBJECT"
        other.material_slots[0].material = self.material
        self.params["object_names"].append(other.name)
        before, original = ids(), source_hash([self.sphere, other])
        receipt = interchange.export_asset(self.params)
        self.assertTrue(receipt["status"]["export_generated"])
        self.assertEqual(len(receipt["scalar_texture_staging"]["maps"]), 2)
        self.assertEqual(ids(), before)
        self.assertEqual(source_hash([self.sphere, other]), original)
        self.assertIs(other.material_slots[0].material, self.material)

    def test_streamed_png_retains_orientation_and_sixteen_bit_red_precision(self):
        image = bpy.data.images.new("Precision", 19, 7, alpha=True, float_buffer=True)
        pixels = array("f")
        expected = []
        for y in range(7):
            for x in range(19):
                red = (y * 19 + x + 0.37) / 134
                expected.append(red)
                pixels.extend((red, 0.7, 0.2, 1))
        image.pixels.foreach_set(pixels)
        path = self.path / "precision.png"
        export_materials._write_red_png(image, path)
        data = path.read_bytes()
        self.assertEqual(struct.unpack(">IIBB", data[16:26]), (19, 7, 16, 0))
        decoded = bpy.data.images.load(str(path), check_existing=False)
        decoded.colorspace_settings.name = "Non-Color"
        actual = array("f", [0]) * len(decoded.pixels)
        decoded.pixels.foreach_get(actual)
        self.assertLess(
            max(abs(value - actual[index * 4]) for index, value in enumerate(expected)), 1 / 65535
        )
        self.assertTrue(
            all(
                abs(actual[index] - actual[index + 1]) < 1e-7
                and abs(actual[index] - actual[index + 2]) < 1e-7
                for index in range(0, len(actual), 4)
            )
        )

    def test_out_of_range_scalar_values_are_rejected(self):
        image = bpy.data.images.new("InvalidScalar", 2, 2, alpha=True, float_buffer=True)
        for value in (-0.1, 1.1, math.nan, math.inf):
            with self.subTest(value=value):
                image.pixels.foreach_set([value, 0, 0, 1] * 4)
                path = self.path / "invalid.png"
                with self.assertRaisesRegex(ValueError, "finite red-channel"):
                    export_materials._write_red_png(image, path)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportMaterialsTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
