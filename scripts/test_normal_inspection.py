"""Exact frozen-oracle and independent golden checks on owned float Blender images."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import math
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests/fixtures")]

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from normal_evidence_v0_5 import _image_evidence as oracle  # noqa: E402

from framewright import baking  # noqa: E402

ARCHIVE_SHA = "87a8d969a3cd0c40c3373b1803da466bd3ea031abb3c57682fc46809ca36aed0"


class NormalInspectionTests(unittest.TestCase):
    def setUp(self):
        self.images = []

    def tearDown(self):
        for image in self.images:
            bpy.data.images.remove(image)

    @staticmethod
    def candidate():
        return importlib.import_module("framewright.normal_inspection")

    def image(self, values, width=None):
        values = np.asarray(values, dtype=np.float32).reshape(-1, 4)
        width = width or len(values)
        image = bpy.data.images.new(
            "OwnedNormalInspection", width, len(values) // width, float_buffer=True
        )
        self.images.append(image)
        image.pixels.foreach_set(values.ravel())
        return image

    @staticmethod
    def pixels(image):
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.tobytes()

    def compare(self, values, width=None):
        image = self.image(values, width)
        before = self.pixels(image)
        expected = oracle(image)
        actual = self.candidate().inspect_normal_image(image)
        self.assertEqual(actual, expected)
        self.assertEqual(self.pixels(image), before)
        return actual

    def test_flat_golden_and_public_baker_wrapper(self):
        image = self.image([[0.5, 0.5, 1, 1]] * 16, 4)
        expected = {
            "valid_normal_pixels": 16,
            "valid_normal_fraction": 1.0,
            "channel_ranges": [0.0, 0.0, 0.0],
            "detail_present": False,
        }
        self.assertEqual(self.candidate().inspect_normal_image(image), expected)
        with patch.object(
            baking, "inspect_normal_image", wraps=self.candidate().inspect_normal_image
        ) as call:
            self.assertEqual(baking._image_evidence(image), expected)
            call.assert_called_once_with(image)

    def test_seeded_mixed_tail_chunk_exact_and_unchanged(self):
        random = np.random.default_rng(78421)
        values = random.uniform(-0.15, 1.15, (257 * 257, 4)).astype(np.float32)
        self.compare(values, 257)

    def test_squared_length_and_blue_threshold_neighbors_match_scalar(self):
        values = []
        for squared in (0.8, 1.2):
            for blue in (0.1, 0.4, 0.9):
                red = np.float32((math.sqrt(max(0, squared - (blue * 2 - 1) ** 2)) + 1) / 2)
                for direction in (-np.inf, np.inf):
                    value = red
                    for _ in range(8):
                        values.append((value, 0.5, blue, 1))
                        value = np.nextafter(value, np.float32(direction))
        for blue in (
            np.nextafter(np.float32(0.1), np.float32(-np.inf)),
            np.float32(0.1),
            np.nextafter(np.float32(0.1), np.float32(np.inf)),
        ):
            values.append((0.8, 0.5, blue, 1))
        values.append((0.5, 0.5, 1, 1))
        self.compare(values)

    def test_detail_threshold_neighbors_keep_strict_comparison(self):
        below = np.float32(0.501)
        above = np.nextafter(below, np.float32(np.inf))
        for red, detail in ((below, False), (above, True)):
            with self.subTest(red=red):
                result = self.compare([(0.5, 0.5, 1, 1), (red, 0.5, 1, 1)])
                self.assertIs(result["detail_present"], detail)

    def test_out_of_range_valid_constant_preserves_legacy_range_initialization(self):
        for rgb, channel, expected in (
            ((1.03, 0.5, 0.5), 0, float(np.float32(1.03)) - 1),
            ((0.5, -0.02, 0.5), 1, -float(np.float32(-0.02))),
        ):
            with self.subTest(rgb=rgb):
                result = self.compare([(*rgb, 1)] * 4, 2)
                self.assertEqual(result["valid_normal_pixels"], 4)
                self.assertEqual(result["channel_ranges"][channel], expected)
                self.assertTrue(result["detail_present"])

    def test_nonfinite_extreme_rgb_and_ignored_alpha_preserve_pixels(self):
        maximum = np.finfo(np.float32).max
        values = [
            (0.5, 0.5, 1, np.nan),
            (0.5, 0.5, 1, np.inf),
            (0.5, 0.5, 1, -maximum),
            (np.nan, 0.5, 1, 1),
            (0.5, np.inf, 1, 1),
            (0.5, 0.5, -np.inf, 1),
            (maximum, -maximum, maximum, 1),
            (0, 0, 0, 1),
        ]
        with np.errstate(all="raise"):
            result = self.compare(values)
        self.assertEqual(result["valid_normal_pixels"], 3)

    def test_all_invalid_preserves_exact_error_and_pixels(self):
        image = self.image([(0, 0, 0, 1), (np.nan, 0.5, 1, 1), (0.5, np.inf, 1, 1)])
        before = self.pixels(image)
        for function in (oracle, self.candidate().inspect_normal_image):
            with self.assertRaisesRegex(RuntimeError, "^Bake produced no valid tangent normals$"):
                function(image)
        self.assertEqual(self.pixels(image), before)

    def test_readback_once_and_float64_work_is_bounded_across_tail(self):
        image = self.image([(0.5, 0.5, 1, 1)] * (257 * 257), 257)
        candidate = self.candidate()
        sizes = []
        original = candidate._chunk_summary

        def chunk(values):
            sizes.append(len(values))
            return original(values)

        calls = []

        class Pixels:
            def __len__(self):
                return len(image.pixels)

            def foreach_get(self, values):
                calls.append((len(values), values.dtype))
                image.pixels.foreach_get(values)

        with patch.object(candidate, "_chunk_summary", side_effect=chunk):
            result = candidate.inspect_normal_image(SimpleNamespace(pixels=Pixels()))
        self.assertEqual(calls, [(257 * 257 * 4, np.dtype(np.float32))])
        self.assertEqual(sizes, [65536, 513])
        self.assertEqual(result["valid_normal_pixels"], 257 * 257)

    def test_tracked_oracle_matches_verified_archive_when_available(self):
        path = ROOT / "dist/framewright_studio-0.5.0.zip"
        if not path.is_file():
            self.skipTest(
                "Retained0.5 ZIP unavailable; independent goldens and tracked historical oracle still run"
            )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ARCHIVE_SHA)
        with zipfile.ZipFile(path) as archive:
            source = archive.read("baking.py").decode()
        function = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "_image_evidence"
        )
        self.assertEqual(ast.dump(function), ast.dump(ast.parse(inspect.getsource(oracle)).body[0]))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NormalInspectionTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
