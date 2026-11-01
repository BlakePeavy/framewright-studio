"""Real EXR data-map decoding, precision, ownership and failure checks."""

from __future__ import annotations

import hashlib
import math
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import bpy  # noqa: E402
from test_materials import png  # noqa: E402

from framewright import materials  # noqa: E402


class EXRMaterialTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            name: set(getattr(bpy.data, name)) for name in ("images", "materials", "scenes")
        }
        self.temp = tempfile.TemporaryDirectory(prefix="framewright-exr-")
        self.root = Path(self.temp.name)
        self.color = self.root / "base.png"
        self.color.write_bytes(png())
        self.path = self.root / "data.exr"
        self.image = bpy.data.images.new("AuthoredEXR", 8, 4, alpha=True, float_buffer=True)
        self.image.colorspace_settings.name = "Non-Color"
        self.pixels = array(
            "f",
            [value for index in range(32) for value in (index / 32 + 0.000123, 0.375, 0.9234, 1)],
        )
        self.image.pixels.foreach_set(self.pixels)
        self.image.filepath_raw = str(self.path)
        self.image.file_format = "OPEN_EXR"
        self.image.save()
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        for name in ("materials", "images", "scenes"):
            store = getattr(bpy.data, name)
            for item in set(store) - self.before[name]:
                store.remove(item, do_unlink=True)
        self.temp.cleanup()

    def request(self, **changes):
        return {
            "base_color_path": str(self.color),
            "roughness_path": str(self.path),
            "metallic_path": str(self.path),
            "normal_path": str(self.path),
            **changes,
        }

    def test_real_exr_header_preview_and_all_three_data_routes(self):
        before = (set(bpy.data.images), set(bpy.data.materials))
        preview = materials.create_pbr_material(self.request())
        self.assertEqual(before, (set(bpy.data.images), set(bpy.data.materials)))
        self.assertEqual(preview["maps"][1]["format"], "EXR")
        self.assertFalse(preview["maps"][1]["exr"]["finite_decoded_buffer_verified"])
        self.assertFalse(preview["maps"][1]["exr"]["container_structure_verified"])
        self.assertFalse(preview["maps"][1]["exr"]["codec_semantics_verified"])
        result = materials.create_pbr_material(self.request(dry_run=False))
        self.assertEqual(len({item["image"] for item in result["maps"]}), 4)
        for item in result["maps"][1:]:
            image = bpy.data.images[item["image"]]
            self.assertEqual(tuple(image.size), (8, 4))
            self.assertEqual(image.colorspace_settings.name, "Non-Color")
            self.assertTrue(item["exr"]["finite_decoded_buffer_verified"])
            self.assertTrue(item["exr"]["container_structure_verified"])
            self.assertFalse(item["exr"]["codec_semantics_verified"])
            actual = array("f", [0]) * len(image.pixels)
            image.pixels.foreach_get(actual)
            self.assertLess(
                max(abs(a - b) for a, b in zip(actual, self.pixels, strict=True)), 0.0005
            )
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.digest)

    def test_shared_source_image_colorspace_and_pixels_remain_unchanged(self):
        original = bpy.data.images.load(str(self.path), check_existing=False)
        original.colorspace_settings.name = "Linear Rec.709"
        before = list(original.pixels)
        result = materials.create_pbr_material(self.request(dry_run=False))
        self.assertNotIn(original.name, [item["image"] for item in result["maps"]])
        self.assertEqual(original.colorspace_settings.name, "Linear Rec.709")
        self.assertEqual(list(original.pixels), before)

    def test_header_without_chunks_fails_real_decode_and_cleans_allocations(self):
        header_bytes = materials.inspect_texture_file(str(self.path))["exr"]["header_bytes"]
        self.path.write_bytes(self.path.read_bytes()[:header_bytes])
        before = (set(bpy.data.images), set(bpy.data.materials))
        with self.assertRaises((ValueError, RuntimeError)):
            materials.create_pbr_material(self.request(dry_run=False))
        self.assertEqual(before, (set(bpy.data.images), set(bpy.data.materials)))

    def test_nonfinite_decoded_values_reject_without_leaking_material_or_images(self):
        validator = materials._verify_exr_pixels
        before = (set(bpy.data.images), set(bpy.data.materials))

        def corrupt(image, item):
            image.pixels[0] = math.nan
            self.assertTrue(math.isnan(image.pixels[0]))
            return validator(image, item)

        with (
            patch.object(materials, "_verify_exr_pixels", side_effect=corrupt),
            self.assertRaisesRegex(ValueError, "finite"),
        ):
            materials.create_pbr_material(self.request(dry_run=False))
        self.assertEqual(before, (set(bpy.data.images), set(bpy.data.materials)))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.digest)

    def test_hdr_data_is_reported_without_silent_clamping_or_color_conversion(self):
        self.image.pixels.foreach_set([-0.125, 2.5, 0.5, 1] * 32)
        self.image.save()
        result = materials.create_pbr_material(self.request(dry_run=False))
        for item in result["maps"][1:]:
            self.assertTrue(item["exr"]["outside_unit_range"])
            self.assertAlmostEqual(item["exr"]["decoded_minimum"], -0.125)
            self.assertAlmostEqual(item["exr"]["decoded_maximum"], 2.5)

    def test_validation_failure_after_multiple_loads_removes_only_owned_ids(self):
        original = bpy.data.images.load(str(self.path), check_existing=False)
        before = (set(bpy.data.images), set(bpy.data.materials))
        validator = materials._verify_exr_pixels
        calls = []

        def later(image, item):
            calls.append(item["role"])
            if len(calls) == 2:
                raise RuntimeError("validation injected")
            return validator(image, item)

        with (
            patch.object(materials, "_verify_exr_pixels", side_effect=later),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            materials.create_pbr_material(self.request(dry_run=False))
        self.assertEqual(before, (set(bpy.data.images), set(bpy.data.materials)))
        self.assertIn(original, set(bpy.data.images))


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an owned background Blender process")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EXRMaterialTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
