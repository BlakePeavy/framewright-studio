"""Bounded image metadata and standalone PBR request contracts."""

import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from framewright import materials


def png(width=2, height=2, pixel=(128, 128, 255, 255)):
    def chunk(name, data):
        return (
            struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    body = zlib.compress((b"\0" + bytes(pixel) * width) * height) if width * height < 100 else b""
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")
    )


def jpeg(width=320, height=240, marker=0xC0):
    body = (
        bytes([8])
        + struct.pack(">HHB", height, width, 3)
        + bytes([1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1])
    )
    return (
        b"\xff\xd8\xff\xe0\x00\x04xx\xff"
        + bytes([marker])
        + struct.pack(">H", len(body) + 2)
        + body
        + b"\xff\xd9"
    )


class MaterialMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "map.png"
        self.path.write_bytes(png())

    def test_png_metadata_hash_and_request_color_semantics(self):
        result = materials.create_pbr_material(
            {
                "base_color_path": str(self.path),
                "roughness_path": str(self.path),
                "normal_path": str(self.path),
            }
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["estimated_decoded_bytes"], 3 * 2 * 2 * 16)
        self.assertEqual(
            [item["color_space"] for item in result["maps"]], ["sRGB", "Non-Color", "Non-Color"]
        )
        self.assertTrue(
            all(
                item["sha256"] == hashlib.sha256(self.path.read_bytes()).hexdigest()
                for item in result["maps"]
            )
        )
        self.assertTrue(
            all(
                (item["width"], item["height"], item["format"]) == (2, 2, "PNG")
                for item in result["maps"]
            )
        )

    def test_baseline_and_progressive_jpeg_headers(self):
        path = self.root / "map.jpg"
        for marker in (0xC0, 0xC2):
            with self.subTest(marker=marker):
                path.write_bytes(jpeg(marker=marker))
                result = materials.inspect_texture_file(str(path))
                self.assertEqual(
                    (result["width"], result["height"], result["format"]), (320, 240, "JPEG")
                )

    def test_8k_requires_explicit_budget_before_loading(self):
        self.path.write_bytes(png(8192, 8192))
        with self.assertRaisesRegex(ValueError, "budget"):
            materials.create_pbr_material({"base_color_path": str(self.path)})
        result = materials.create_pbr_material(
            {"base_color_path": str(self.path), "max_memory_mb": 1024}
        )
        self.assertEqual(result["estimated_decoded_bytes"], 1024**3)
        self.assertTrue(result["dry_run"])

    def test_malformed_png_crc_dimensions_and_truncated_data_rejected(self):
        malformed = [b"not an image", png()[:20], png(0, 1)]
        damaged = bytearray(png())
        damaged[29] ^= 1
        malformed.append(damaged)
        for data in malformed:
            with self.subTest(data=data[:16]):
                self.path.write_bytes(data)
                with self.assertRaises(ValueError):
                    materials.inspect_texture_file(str(self.path))

    def test_jpeg_dimensions_must_be_in_bounded_header(self):
        path = self.root / "map.jpg"
        data = b"\xff\xd8" + (b"\xff\xe1\xff\xff" + b"x" * 65533) * 17 + jpeg()[2:]
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "header"):
            materials.inspect_texture_file(str(path))

    def test_truncated_jpeg_segments_and_zero_dimensions_rejected(self):
        path = self.root / "map.jpg"
        for data in (jpeg()[:8], jpeg(width=0), b"\xff\xd8\xff\xda\x00\x02"):
            with self.subTest(data=data[:10]):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    materials.inspect_texture_file(str(path))

    def test_path_type_and_source_format_restrictions(self):
        for value in (
            "relative.png",
            "https://example.com/map.png",
            "\\\\server\\share\\map.png",
            str(self.root),
        ):
            with self.subTest(path=value), self.assertRaises(ValueError):
                materials.inspect_texture_file(value)
        unsupported = self.root / "source.exr"
        unsupported.write_bytes(png())
        with self.assertRaises(ValueError):
            materials.inspect_texture_file(str(unsupported))

    def test_unknown_fields_directx_and_bad_budget_reject(self):
        for changes in (
            {"execute": "code"},
            {"normal_convention": "DIRECTX"},
            {"max_memory_mb": True},
            {"max_memory_mb": 0},
            {"dry_run": "false"},
            {"name": "x" * 49},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                materials.create_pbr_material({"base_color_path": str(self.path), **changes})
        with self.assertRaises(ValueError):
            materials.create_pbr_material({})


if __name__ == "__main__":
    unittest.main()
