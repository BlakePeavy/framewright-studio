"""Explicit opt-in scalar clipping on owned FBX staging; original EXR stays exact."""

import math
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_pbr_map_handoff import fixture  # noqa: E402
from test_surface_render_parity import source_hash  # noqa: E402

from framewright import export_materials, interchange  # noqa: E402


class ScalarClampTests(unittest.TestCase):
    def setUp(self):
        self.stores = ("objects", "meshes", "materials", "images", "scenes")
        self.initial = {name: set(getattr(bpy.data, name)) for name in self.stores}
        self.temporary = tempfile.TemporaryDirectory(prefix="fw-explicit-scalar-clamp-")
        self.folder = Path(self.temporary.name)
        self.skin, _ = fixture(self.folder)
        self.image = bpy.data.images.new("Overshoot", 2, 2, alpha=True, float_buffer=True)
        self.image.colorspace_settings.name = "Non-Color"
        self.image.pixels.foreach_set(
            [v for red in (-0.01, 0.2, 1.01, 0.8) for v in (red, 0.1, 0.9, 1)]
        )
        self.image.filepath_raw = str(self.folder / "overshoot.exr")
        self.image.file_format = "OPEN_EXR"
        self.image.save()
        self.image = bpy.data.images.load(self.image.filepath_raw, check_existing=False)
        self.image.colorspace_settings.name = "Non-Color"
        self.skin.data.materials[0].node_tree.nodes["FW_roughness"].image = self.image
        self.params = dict(
            object_names=[self.skin.name],
            directory=str(self.folder),
            format="FBX",
            filename="clamped",
            dry_run=False,
        )

    def tearDown(self):
        for name, previous in self.initial.items():
            store = getattr(bpy.data, name)
            for item in set(store) - previous:
                store.remove(item, do_unlink=True)
        self.temporary.cleanup()

    def test_default_rejects_and_explicit_clamp_reports_ranges_without_source_changes(self):
        before = source_hash([self.skin])
        original = (self.folder / "overshoot.exr").read_bytes()
        with self.assertRaisesRegex(ValueError, "finite red-channel"):
            interchange.export_asset(self.params)
        receipt = interchange.export_asset({**self.params, "clamp_scalar_textures": True})
        evidence = receipt["scalar_texture_staging"]["scalar_images"][self.image.name]
        self.assertLess(evidence["source_red_min"], 0)
        self.assertGreater(evidence["source_red_max"], 1)
        self.assertEqual(evidence["clipped_pixel_count"], 2)
        self.assertEqual(evidence["pixel_count"], 4)
        self.assertTrue(evidence["clamp_requested"])
        self.assertEqual(source_hash([self.skin]), before)
        self.assertEqual((self.folder / "overshoot.exr").read_bytes(), original)

    def test_writer_clips_only_owned_output_red_with_sixteen_bit_precision(self):
        path = self.folder / "clipped.png"
        source = tuple(self.image.pixels)
        evidence = export_materials._write_red_png(self.image, path, clamp=True)
        decoded = bpy.data.images.load(str(path), check_existing=False)
        decoded.colorspace_settings.name = "Non-Color"
        pixels = array("f", [0]) * len(decoded.pixels)
        decoded.pixels.foreach_get(pixels)
        expected = [min(1, max(0, source[i * 4])) for i in range(4)]
        self.assertLess(
            max(abs(pixels[i * 4] - value) for i, value in enumerate(expected)), 1 / 65535
        )
        self.assertEqual(evidence["clipped_pixel_count"], 2)
        self.assertEqual(tuple(self.image.pixels), source)

    def test_nonfinite_values_remain_rejected_with_opt_in(self):
        image = bpy.data.images.new("Nonfinite", 2, 2, alpha=True, float_buffer=True)
        for value in (math.nan, math.inf):
            image.pixels.foreach_set([value, 0, 0, 1] * 4)
            path = self.folder / "invalid.png"
            with self.assertRaisesRegex(ValueError, "finite"):
                export_materials._write_red_png(image, path, clamp=True)
            self.assertFalse(path.exists())

    def test_clamp_flag_requires_bool_and_fbx(self):
        for changes in (
            {"clamp_scalar_textures": 1},
            {"clamp_scalar_textures": True, "format": "GLB"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(ValueError, "clamp_scalar_textures"),
            ):
                interchange.export_asset({**self.params, **changes})


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ScalarClampTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
