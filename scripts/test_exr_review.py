"""Independent real-EXR channel/precision review using tiny uncompressed scanline files."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import bpy  # noqa: E402
from test_materials import png  # noqa: E402

from framewright import materials  # noqa: E402


def raw_exr(path, rows, channels=("B", "G", "R"), pixel_type=2):
    """Write only our fixed uncompressed scanline fixture, not a general encoder."""
    height, width = len(rows), len(rows[0])

    def attribute(name, kind, payload):
        return (
            name.encode()
            + b"\0"
            + kind.encode()
            + b"\0"
            + struct.pack("<I", len(payload))
            + payload
        )

    window = struct.pack("<4i", 0, 0, width - 1, height - 1)
    channel_data = (
        b"".join(
            name.encode() + b"\0" + struct.pack("<iB3xii", pixel_type, 0, 1, 1) for name in channels
        )
        + b"\0"
    )
    data = (
        struct.pack("<II", 20000630, 2)
        + b"".join(
            (
                attribute("channels", "chlist", channel_data),
                attribute("compression", "compression", b"\0"),
                attribute("dataWindow", "box2i", window),
                attribute("displayWindow", "box2i", window),
                attribute("lineOrder", "lineOrder", b"\0"),
                attribute("pixelAspectRatio", "float", struct.pack("<f", 1)),
                attribute("screenWindowCenter", "v2f", struct.pack("<2f", 0, 0)),
                attribute("screenWindowWidth", "float", struct.pack("<f", 1)),
            )
        )
        + b"\0"
    )
    code = "e" if pixel_type == 1 else "f"
    chunks = []
    for y, row in enumerate(rows):
        pixels = b"".join(
            struct.pack("<" + code, pixel[channel]) for channel in channels for pixel in row
        )
        chunks.append(struct.pack("<ii", y, len(pixels)) + pixels)
    offset = len(data) + 8 * height
    offsets = []
    for chunk in chunks:
        offsets.append(struct.pack("<Q", offset))
        offset += len(chunk)
    path.write_bytes(data + b"".join(offsets) + b"".join(chunks))


class EXRReviewTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            kind: set(getattr(bpy.data, kind))
            for kind in ("images", "materials", "scenes", "objects", "meshes", "cameras", "worlds")
        }
        self.temp = tempfile.TemporaryDirectory(prefix="framewright-exr-review-")
        self.folder = Path(self.temp.name)
        self.base = self.folder / "base.png"
        self.base.write_bytes(png())

    def tearDown(self):
        for kind in ("objects", "scenes", "meshes", "materials", "images", "cameras", "worlds"):
            store = getattr(bpy.data, kind)
            for item in set(store) - self.before[kind]:
                store.remove(item, do_unlink=True)
        self.temp.cleanup()

    def intake(self, path):
        result = materials.create_pbr_material(
            {"base_color_path": str(self.base), "roughness_path": str(path), "dry_run": False}
        )
        return result, bpy.data.images[result["maps"][1]["image"]]

    def test_y_half_and_float_decode_actual_scalar_values(self):
        for pixel_type in (1, 2):
            with self.subTest(pixel_type=pixel_type):
                path = self.folder / f"luminance{pixel_type}.exr"
                raw_exr(path, [[{"Y": 0.25}, {"Y": 2.5}]], channels=("Y",), pixel_type=pixel_type)
                result, image = self.intake(path)
                self.assertTrue(result["maps"][1]["exr"]["finite_decoded_buffer_verified"])
                self.assertEqual(list(image.pixels), [0.25, 0.25, 0.25, 1, 2.5, 2.5, 2.5, 1])

    def test_float_rgba_varied_alpha_preserves_raw_hdr_channels(self):
        path = self.folder / "rgba.exr"
        values = [
            {"R": 0.25, "G": 0.5, "B": 2.5, "A": 0.2},
            {"R": -0.125, "G": 0.75, "B": 0.0625, "A": 0.0},
        ]
        raw_exr(path, [values], channels=("A", "B", "G", "R"))
        result, image = self.intake(path)
        actual = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(actual)
        expected = [pixel[channel] for pixel in values for channel in "RGBA"]
        self.assertLess(max(abs(a - b) for a, b in zip(actual, expected, strict=True)), 1e-7)
        self.assertEqual(result["maps"][1]["exr"]["decoded_maximum"], 2.5)

    def test_truncated_scanline_payload_rejected_with_source_ids_preserved(self):
        path = self.folder / "truncated.exr"
        raw_exr(path, [[{"R": 0.25, "G": 0.5, "B": 0.75}] * 3] * 2)
        path.write_bytes(path.read_bytes()[:-7])
        before = {kind: set(getattr(bpy.data, kind)) for kind in ("images", "materials")}
        with self.assertRaises((ValueError, RuntimeError)):
            self.intake(path)
        self.assertEqual(before, {kind: set(getattr(bpy.data, kind)) for kind in before})

    def test_rgba_data_texture_shader_preserves_rgb_independently_of_alpha(self):
        path = self.folder / "alpha_data.exr"
        raw_exr(path, [[{"R": 0.2, "G": 0.4, "B": 0.6, "A": 0.25}]], channels=("A", "B", "G", "R"))
        _result, image = self.intake(path)
        previous = bpy.context.window.scene
        scene = bpy.data.scenes.new("EXRAlphaReview")
        mesh = bpy.data.meshes.new("EXRAlphaPlane")
        mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new()
        for item, value in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
            item.uv = value
        obj = bpy.data.objects.new("EXRAlphaPlane", mesh)
        scene.collection.objects.link(obj)
        material = bpy.data.materials.new("EXRAlphaEmission")
        tree = material.node_tree
        tree.nodes.clear()
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        emission = tree.nodes.new("ShaderNodeEmission")
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(texture.outputs["Color"], emission.inputs["Color"])
        tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        mesh.materials.append(material)
        camera_data = bpy.data.cameras.new("EXRAlphaCamera")
        camera = bpy.data.objects.new("EXRAlphaCamera", camera_data)
        scene.collection.objects.link(camera)
        camera.location = (0, 0, 2)
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = 1
        scene.camera = camera
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 8
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "32"
        scene.render.filepath = str(self.folder / "evaluated.exr")
        try:
            bpy.context.window.scene = scene
            self.assertEqual(bpy.ops.render.render(write_still=True), {"FINISHED"})
            rendered = bpy.data.images.load(scene.render.filepath, check_existing=False)
            self.assertLess(
                max(
                    abs(rendered.pixels[(4 * 8 + 4) * 4 + i] - value)
                    for i, value in enumerate((0.2, 0.4, 0.6))
                ),
                1e-5,
                f"alpha_mode={image.alpha_mode}; actual={list(rendered.pixels[(4 * 8 + 4) * 4 : (4 * 8 + 4) * 4 + 4])}",
            )
        finally:
            bpy.context.window.scene = previous


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EXRReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
