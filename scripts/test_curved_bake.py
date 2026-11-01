"""Curved tangent-normal bake with an explicit cage, visible UV seam and controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import unittest
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
import test_surface_render_parity as rendering  # noqa: E402
from mathutils import Matrix  # noqa: E402

from framewright import baking  # noqa: E402


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cylinder(name, segments, rings, *, radius=1.03, detail=False):
    points, faces = [], []
    for j in range(rings + 1):
        z = -1 + 2 * j / rings
        for i in range(segments):
            theta = 2 * math.pi * i / segments
            r = radius + (
                0.03 * math.sin(8 * theta) * math.sin(3 * math.pi * (z + 1)) if detail else 0
            )
            points.append((r * math.sin(theta), -r * math.cos(theta), z))
    for j in range(rings):
        for i in range(segments):
            n = (i + 1) % segments
            faces.append(
                (j * segments + i, j * segments + n, (j + 1) * segments + n, (j + 1) * segments + i)
            )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="CylinderAtlas")
    for face in mesh.polygons:
        face.use_smooth = True
        j, i = divmod(face.index, segments)
        values = (
            (i / segments, j / rings),
            ((i + 1) / segments, j / rings),
            ((i + 1) / segments, (j + 1) / rings),
            (i / segments, (j + 1) / rings),
        )
        for loop, value in zip(face.loop_indices, values, strict=True):
            uv.data[loop].uv = value
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    # Put the cylindrical UV seam toward the fixed +Z review camera.
    obj.matrix_world = Matrix.Rotation(-math.pi / 2, 4, "X")
    return obj


def image_values(image):
    values = array("f", [0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return values


def render_damaged_seam(baked, path):
    """Reverse tangent X only in the two atlas edge strips, on disposable data."""
    copy = baked.copy()
    copy.data = baked.data.copy()
    owned_materials, owned_images = [], []
    try:
        bpy.context.scene.collection.objects.link(copy)
        for index, slot in enumerate(copy.material_slots):
            material = slot.material.copy()
            owned_materials.append(material)
            copy.data.materials[index] = material
            texture = material.node_tree.nodes["Framewright Tangent Normal"]
            image = texture.image.copy()
            owned_images.append(image)
            texture.image = image
            values = image_values(image)
            width, height = image.size
            for y in range(height):
                for x in (*range(8), *range(width - 8, width)):
                    offset = (y * width + x) * 4
                    values[offset] = 1 - values[offset]
            image.pixels.foreach_set(values)
            image.update()
        return rendering.render([copy], path)
    finally:
        data = copy.data
        bpy.data.objects.remove(copy, do_unlink=True)
        bpy.data.meshes.remove(data)
        for material in owned_materials:
            bpy.data.materials.remove(material)
        for image in owned_images:
            bpy.data.images.remove(image)


def roi_error(reference, actual, left=0.2, right=0.8):
    size = rendering.RESOLUTION
    differences = [
        abs(reference[(y * size + x) * 4 + channel] - actual[(y * size + x) * 4 + channel])
        for y in range(int(size * 0.2), int(size * 0.8))
        for x in range(int(size * left), int(size * right))
        for channel in range(3)
    ]
    return {
        "mae": sum(differences) / len(differences),
        "maximum": max(differences),
        "rgb_values": len(differences),
        "roi": [left, 0.2, right, 0.8],
    }


def assert_parity(candidate, control):
    if control["mae"] <= 0.003:
        raise AssertionError("Removed normal must create measurable curved-surface shading error")
    limit = min(0.015, control["mae"] * 0.65)
    if candidate["mae"] >= limit:
        raise AssertionError(f"Curved normal comparison exceeds fixture limit {limit}: {candidate}")
    return limit


def cold_verify(folder):
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    original = [bpy.data.objects[name] for name in report["sources"]]
    if rendering.source_hash(original) != report["source_fingerprint"]:
        raise AssertionError("Cold source geometry/UV/material graph changed")
    low = bpy.data.objects[report["bake"]["derivative"]]
    current = rendering.render([low], folder / "cold-baked.png")
    warm = rendering.png_pixels(folder / "baked.png")
    error = roi_error(warm, current)
    if error["mae"] > 1e-6:
        raise AssertionError("Packed cold normal render differs")
    (folder / "cold-verification.json").write_text(
        json.dumps(
            {
                "passed": True,
                "comparison": error,
                "source_fingerprint": report["source_fingerprint"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class CurvedBakeTests(unittest.TestCase):
    def test_curvature_and_seam_with_missing_normal_control(self):
        folder = OUTPUT
        folder.mkdir(parents=True, exist_ok=False)
        for obj in list(bpy.context.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        high = cylinder("CurvedHigh", 256, 64, detail=True)
        low = cylinder("CurvedLow", 64, 2)
        cage = cylinder("CurvedCage", 64, 2, radius=1.12)
        surface = rendering.material("CurvedSurface", roughness=0.55)
        for obj in (high, low, cage):
            obj.data.materials.append(surface)
        bpy.context.view_layer.update()
        original = [high, low, cage]
        before = rendering.source_hash(original)
        receipt = baking.bake_normal(
            {
                "high_object": high.name,
                "low_object": low.name,
                "cage_object": cage.name,
                "resolution": 256,
                "ray_distance": 0.15,
                "margin": 8,
                "dry_run": False,
            }
        )
        self.assertEqual(receipt["projection"]["hit_fraction"], 1)
        self.assertGreater(receipt["valid_normal_fraction"], 0.99)
        baked = bpy.data.objects[receipt["derivative"]]
        high_pixels = rendering.render([high], folder / "high.png")
        baked_pixels = rendering.render([baked], folder / "baked.png")
        flat_pixels = rendering.render([baked], folder / "removed-normal.png", "normal_removed")
        damaged_seam = render_damaged_seam(baked, folder / "damaged-seam.png")
        comparisons = {}
        for label, left, right in (("interior", 0.2, 0.8), ("seam", 0.47, 0.53)):
            candidate = roi_error(high_pixels, baked_pixels, left, right)
            control = roi_error(high_pixels, flat_pixels, left, right)
            with self.assertRaises(AssertionError):
                assert_parity(control, control)
            limit = assert_parity(control if INJECT_REMOVED else candidate, control)
            comparisons[label] = {"baked": candidate, "removed": control, "limit": limit}
        seam_candidate = comparisons["seam"]["baked"]
        seam_control = roi_error(high_pixels, damaged_seam, 0.47, 0.53)
        with self.assertRaises(AssertionError):
            assert_parity(seam_control, seam_control)
        comparisons["seam"]["damaged_seam"] = seam_control
        comparisons["seam"]["damaged_seam_limit"] = assert_parity(seam_candidate, seam_control)
        values = image_values(bpy.data.images[receipt["image"]])
        if not all(math.isfinite(value) for value in values):
            raise AssertionError("Nonfinite baked map")
        self.assertEqual(before, rendering.source_hash(original))
        report = {
            "schema_version": "1.0",
            "sources": [obj.name for obj in original],
            "source_fingerprint": before,
            "bake": receipt,
            "comparisons": comparisons,
            "render": {
                "resolution": rendering.RESOLUTION,
                "samples": rendering.SAMPLES,
                "device": "CPU",
                "view_transform": "Standard",
                "seed": 0,
            },
            "source_preserved": True,
            "runtime_sha256": digest(ROOT / "framewright/baking.py"),
            "script_sha256": digest(__file__),
            "limits": [
                "Open cylindrical sidewall, single atlas, one camera and explicit matching cage",
                "Interior and narrow seam ROIs exclude silhouette/parallax and open cylinder ends",
                "Fixture-specific encoded RGB comparison; no native, production asset or artist acceptance",
            ],
        }
        (folder / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        high.hide_render = low.hide_render = cage.hide_render = True
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / "editable-curved-bake.blend"))
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(folder / "editable-curved-bake.blend"),
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold-verify",
            str(folder),
        ]
        child = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        (folder / "cold.log").write_text(child.stdout + "\n" + child.stderr, encoding="utf-8")
        self.assertEqual(child.returncode, 0, "Cold curved verification failed; inspect cold.log")
        report["cold"] = json.loads((folder / "cold-verification.json").read_text(encoding="utf-8"))
        report["blend_sha256"] = digest(folder / "editable-curved-bake.blend")
        report["render_hashes"] = {path.name: digest(path) for path in folder.glob("*.png")}
        (folder / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (folder / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>Curved normal bake</title><style>body{background:#202328;color:#eee;font:16px system-ui}main{display:flex}figure{margin:4px}img{width:256px}</style><h1>Curved surface and UV seam</h1><p>Fixed camera; source, baked low, removed-normal control and cold baked low. <a href="report.json">Measurements</a>.</p><main>'
            + "".join(
                '<figure><img src="' + file + '"><figcaption>' + label + "</figcaption></figure>"
                for file, label in (
                    ("high.png", "High"),
                    ("baked.png", "Baked low"),
                    ("removed-normal.png", "Removed normal"),
                    ("damaged-seam.png", "Damaged seam"),
                    ("cold-baked.png", "Cold baked low"),
                )
            )
            + "</main>",
            encoding="utf-8",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-verify", type=Path)
    parser.add_argument("--inject-removed-normal", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        raise RuntimeError("Use an owned background Blender process")
    rendering.RESOLUTION, rendering.SAMPLES = 256, 48
    if args.cold_verify:
        cold_verify(args.cold_verify)
    else:
        OUTPUT = (
            ROOT
            / "artifacts/curved-bake"
            / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        )
        INJECT_REMOVED = args.inject_removed_normal
        print("FRAMEWRIGHT_CURVED_BAKE " + str(OUTPUT), flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(CurvedBakeTests)
        )
        if not result.wasSuccessful():
            raise SystemExit(1)
