"""Actual interior thick-glass/refraction/contact-shadow evidence in isolated Blender."""

from __future__ import annotations

import hashlib
import html
import json
import sys
import unittest
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402
from test_light_review import context_state  # noqa: E402

from framewright import light_review  # noqa: E402

LAST_FOLDER = None
INJECT_OPAQUE = "--inject-opaque-glass" in (
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
)


class InteriorRenderTests(unittest.TestCase):
    def test_glass_thickness_refraction_and_contact_shadow_controls(self):
        report = render_review()
        self.assertGreater(report["measurements"]["opaque_vs_glass_mae"], 0.015)
        self.assertGreater(report["measurements"]["ior_one_vs_glass_mae"], 0.002)
        self.assertGreater(report["measurements"]["thin_vs_glass_mae"], 0.001)
        self.assertLess(
            report["measurements"]["glass_vs_removed_mae"],
            report["measurements"]["opaque_vs_removed_mae"],
        )
        self.assertNotEqual(report["measurements"]["refraction_best_horizontal_shift_pixels"], 0)
        self.assertGreater(
            report["measurements"]["floor_shadow_mean_rgb_gain_without_block"], 0.002
        )
        self.assertGreaterEqual(report["measurements"]["visible_floor_samples"], 20)
        self.assertEqual(report["measurements"]["repeat_maximum_pixel_difference"], 0)
        self.assertTrue(report["source_preserved"])
        self.assertTrue(report["fixture_controls_restored"])


def render_review():
    global LAST_FOLDER
    if not bpy.app.background:
        raise RuntimeError("Rendered fixture tests require isolated background Blender")
    folder = (
        ROOT
        / "artifacts/interior-glass"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    )
    folder.mkdir(parents=True, exist_ok=False)
    LAST_FOLDER = folder
    source_before = context_state()
    previous = bpy.context.window.scene
    result = light_review.create_interior_fixture(
        {
            "resolution": 256,
            "samples": 64,
            "glass_thickness": 0.20,
            "roughness": 0.0,
            "dry_run": False,
        }
    )
    scene = bpy.data.scenes[result["scene"]]
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    glass = bpy.data.objects[result["objects"]["glass"]]
    block = bpy.data.objects[result["objects"]["contact_block"]]
    block_location = block.location.copy()
    floor = bpy.data.objects[result["objects"]["floor"]]
    shader = next(n for n in glass.data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    pixels = {}
    images = []

    def render(label):
        path = folder / (label + ".png")
        scene.render.filepath = str(path)
        bpy.context.view_layer.update()
        if bpy.ops.render.render(write_still=True) != {"FINISHED"}:
            raise RuntimeError("Render failed")
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            image.colorspace_settings.name = "Non-Color"
            data = array("f", [0]) * len(image.pixels)
            image.pixels.foreach_get(data)
            pixels[label] = np.asarray(data).reshape(256, 256, 4).copy()
        finally:
            bpy.data.images.remove(image)
        images.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "label": label,
            }
        )

    try:
        bpy.context.window.scene = scene
        bpy.context.view_layer.update()
        projections = [
            world_to_camera_view(scene, scene.camera, glass.matrix_world @ Vector(corner))
            for corner in glass.bound_box
        ]
        lower = np.array([min(p.x for p in projections), min(p.y for p in projections)])
        upper = np.array([max(p.x for p in projections), max(p.y for p in projections)])
        margin = (upper - lower) * 0.24
        x0, y0 = ((lower + margin) * 256).astype(int)
        x1, y1 = ((upper - margin) * 256).astype(int)
        if not (0 <= x0 < x1 <= 256 and 0 <= y0 < y1 <= 256):
            raise AssertionError("Glass interior ROI is outside camera")
        floor_samples = []
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eye = scene.camera.matrix_world.translation.copy()
        for x in np.linspace(1.6, 2.45, 17):
            for y in np.linspace(-1.05, -0.05, 17):
                point = Vector((float(x), float(y), 0))
                direction = point - eye
                hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                    depsgraph, eye, direction.normalized(), distance=direction.length + 0.1
                )
                if not hit or obj != floor or (location - point).length > 0.03:
                    continue
                projected = world_to_camera_view(scene, scene.camera, point)
                px, py = int(projected.x * 256), int(projected.y * 256)
                if 0 <= px < 256 and 0 <= py < 256:
                    floor_samples.append({"world": list(point), "pixel": [px, py]})
        shader.inputs["Transmission Weight"].default_value = 0 if INJECT_OPAQUE else 1
        render("glass_thick")
        shader.inputs["Transmission Weight"].default_value = 0
        render("opaque_transmission_zero")
        shader.inputs["Transmission Weight"].default_value = 1
        glass.hide_render = True
        render("glass_removed")
        glass.hide_render = False
        shader.inputs["IOR"].default_value = 1
        render("ior_one")
        shader.inputs["IOR"].default_value = 1.5
        glass.scale.y = 0.005 / 0.20
        render("glass_thin_5mm")
        glass.scale.y = 1
        block.hide_render = True
        render("contact_block_removed")
        block.hide_render = False
        block.location.z += 0.2
        render("contact_block_20cm_gap")
        block.location = block_location
        shader.inputs["Transmission Weight"].default_value = 0 if INJECT_OPAQUE else 1
        render("glass_thick_repeat")
        scene.camera = bpy.data.objects[result["cameras"]["front"]]
        render("glass_front")
        scene.camera = bpy.data.objects[result["cameras"]["three_quarter"]]
        scene.render.filepath = str(folder / "glass_thick.png")
        bpy.context.view_layer.update()

        def crop(label):
            return pixels[label][y0:y1, x0:x1, :3]

        def difference(a, b):
            return float(np.abs(crop(a) - crop(b)).mean())

        thick_edges = np.diff(crop("glass_thick").mean(axis=2), axis=1)
        straight_edges = np.diff(crop("ior_one").mean(axis=2), axis=1)
        correlations = {}
        for shift in range(-6, 7):
            if shift > 0:
                a, b = thick_edges[:, shift:], straight_edges[:, :-shift]
            elif shift < 0:
                a, b = thick_edges[:, :shift], straight_edges[:, -shift:]
            else:
                a, b = thick_edges, straight_edges
            correlations[shift] = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        best_shift = max(correlations, key=correlations.get)
        gains = []
        for sample in floor_samples:
            x, y = sample["pixel"]
            baseline = float(np.mean(pixels["glass_thick"][y, x, :3]))
            removed = float(np.mean(pixels["contact_block_removed"][y, x, :3]))
            gains.append(removed - baseline)
            sample.update(baseline_rgb_mean=baseline, block_removed_rgb_mean=removed)
        measures = {
            "opaque_vs_glass_mae": difference("opaque_transmission_zero", "glass_thick"),
            "ior_one_vs_glass_mae": difference("ior_one", "glass_thick"),
            "thin_vs_glass_mae": difference("glass_thin_5mm", "glass_thick"),
            "glass_vs_removed_mae": difference("glass_thick", "glass_removed"),
            "opaque_vs_removed_mae": difference("opaque_transmission_zero", "glass_removed"),
            "refraction_best_horizontal_shift_pixels": best_shift,
            "horizontal_edge_correlations": correlations,
            "visible_floor_samples": len(floor_samples),
            "floor_shadow_mean_rgb_gain_without_block": float(np.mean(gains)) if gains else 0,
            "repeat_maximum_pixel_difference": float(
                np.abs(pixels["glass_thick"] - pixels["glass_thick_repeat"]).max()
            ),
            "glass_roi_pixels": [int(x0), int(y0), int(x1), int(y1)],
            "space": "normalized PNG RGB readback, no photometric unit claim",
        }
        if bpy.ops.wm.save_as_mainfile(
            filepath=str(folder / "interior-glass-reference.blend"), check_existing=False
        ) != {"FINISHED"}:
            raise RuntimeError("Editable fixture save failed")
    finally:
        bpy.context.window.scene = previous
    source_after = context_state()
    report = {
        "schema_version": "1.0",
        "blender": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(),
        "parameters": result["parameters"],
        "budget": result["budget"],
        "measurements": measures,
        "floor_samples": floor_samples,
        "images": images,
        "source_preserved": source_before == source_after,
        "fixture_controls_restored": tuple(block.location) == tuple(block_location)
        and tuple(glass.scale) == (1, 1, 1)
        and shader.inputs["IOR"].default_value == 1.5
        and shader.inputs["Transmission Weight"].default_value == (0 if INJECT_OPAQUE else 1)
        and not glass.hide_render
        and not block.hide_render,
        "injected_opaque_baseline": INJECT_OPAQUE,
        "source_before_sha256": hashlib.sha256(
            json.dumps(source_before, sort_keys=True).encode()
        ).hexdigest(),
        "source_after_sha256": hashlib.sha256(
            json.dumps(source_after, sort_keys=True).encode()
        ).hexdigest(),
        "blend_sha256": hashlib.sha256(
            (folder / "interior-glass-reference.blend").read_bytes()
        ).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "module_sha256": hashlib.sha256(Path(light_review.__file__).read_bytes()).hexdigest(),
        "render": {
            "engine": "Cycles CPU",
            "samples": 64,
            "seed": 0,
            "threads": 4,
            "resolution": [256, 256],
            "view": "AgX",
            "look": "None",
            "exposure": 0,
            "gamma": 1,
            "transmission_bounces": 12,
            "caustics_reflective": False,
            "caustics_refractive": False,
        },
        "visual_acceptance": False,
        "native_glass_parity": False,
        "limits": [
            "Known closed glass slab and geometric checker target; no arbitrary shader or asset support",
            "Pixel/correlation thresholds are fixture-specific evidence, not studio quality standards",
            "Floor samples exclude directly occluded object pixels; indirect light/reflections can also contribute",
            "No caustic, spectral, photographed-material, monitor or native-engine acceptance",
        ],
    }
    (folder / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (folder / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Interior thick-glass controls</title><style>body{font:16px system-ui;background:#191b1d;color:#eee;margin:30px}figure{display:inline-block;margin:10px}img{width:384px;image-rendering:auto}</style><h1>Interior glass / refraction / contact controls</h1><p>Explicit synthetic benchmark fixture. Artistic and native-engine acceptance remain open.</p>'
        + "".join(
            f'<figure><img src="{item["file"]}"><figcaption>{html.escape(item["label"])}</figcaption></figure>'
            for item in images
        )
        + '<p><a href="report.json">Measurements</a> · <a href="interior-glass-reference.blend">Editable scene</a></p></html>',
        encoding="utf-8",
    )
    print("FRAMEWRIGHT_INTERIOR_RENDER " + str(folder))
    return report


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(InteriorRenderTests)
    )
    if LAST_FOLDER:
        (LAST_FOLDER / "test-result.json").write_text(
            json.dumps(
                {
                    "passed": result.wasSuccessful(),
                    "tests": result.testsRun,
                    "failures": len(result.failures),
                    "errors": len(result.errors),
                },
                indent=2,
            )
            + "\n"
        )
    if not result.wasSuccessful():
        raise RuntimeError("Interior rendered controls failed")
