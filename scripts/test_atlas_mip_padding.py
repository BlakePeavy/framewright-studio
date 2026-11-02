"""Actual packed-layout gate and source preservation for requested mip padding."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import bpy  # noqa: E402
from test_material_atlas import cube, handler, inventory, material, source_state  # noqa: E402


class MipPaddingTests(unittest.TestCase):
    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        self.obj = cube("MipSource", material("MipMetal", (0.2, 0.1, 0.05), metal=0.9))
        bpy.context.view_layer.update()
        self.request = {
            "object_names": [self.obj.name],
            "resolution": 512,
            "padding_mip_level": 3,
            "bake_samples": 1,
            "dry_run": False,
        }

    def test_real_bake_uses_requested_padding_and_preserves_source(self):
        before = source_state([self.obj])
        result = handler().bake_material_atlas(self.request)
        self.assertEqual(result["margin"], 24)
        self.assertEqual(result["mip_padding"]["state"], "packing_verified")
        self.assertFalse(result["mip_padding"]["native_filtering_verified"])
        self.assertGreaterEqual(
            result["uv_evidence"]["minimum_chart_gap_px_lower_bound"], 48 - 0.001
        )
        self.assertGreaterEqual(result["uv_evidence"]["minimum_tile_border_px"], 24 - 0.001)
        self.assertEqual(len(result["maps"]), 4)
        self.assertEqual(source_state([self.obj]), before)

    def test_insufficient_packed_gap_rolls_back_before_baking(self):
        module = handler()
        before, state = inventory(), source_state([self.obj])
        original = module._uv_evidence

        def bad_gap(*args):
            row = original(*args)
            row["minimum_chart_gap_px_lower_bound"] = 47
            return row

        with (
            patch.object(module, "_uv_evidence", bad_gap),
            patch.object(module, "_bake_pass") as bake,
        ):
            with self.assertRaisesRegex(ValueError, "mip padding"):
                module.bake_material_atlas(self.request)
            bake.assert_not_called()
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state([self.obj]), state)

    def test_crowded_256_layout_refuses_and_preserves_source(self):
        module = handler()
        before, state = inventory(), source_state([self.obj])
        with patch.object(module, "_bake_pass") as bake:
            with self.assertRaisesRegex(ValueError, "UV packing"):
                module.bake_material_atlas({**self.request, "resolution": 256})
            bake.assert_not_called()
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state([self.obj]), state)

    def test_larger_explicit_margin_requires_its_full_gap_before_baking(self):
        module = handler()
        before, state = inventory(), source_state([self.obj])
        original = module._uv_evidence

        def insufficient_for_requested_margin(*args):
            row = original(*args)
            row["minimum_chart_gap_px_lower_bound"] = 60
            return row

        with (
            patch.object(module, "_uv_evidence", insufficient_for_requested_margin),
            patch.object(module, "_bake_pass") as bake,
        ):
            with self.assertRaisesRegex(ValueError, "mip padding"):
                module.bake_material_atlas({**self.request, "margin": 32})
            bake.assert_not_called()
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state([self.obj]), state)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(MipPaddingTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Mip padding checks failed")
