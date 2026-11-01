"""Controlled scene-linear/EXR/display exposure evidence in isolated Blender."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
GRAY_VALUES = (0.0, 0.003, 0.018, 0.036, 0.18, 0.36, 0.5, 1.0, 2.0, 4.0, 8.0)
PATCHES = [(f"Gray {value:g}", [value] * 3) for value in GRAY_VALUES] + [
    ("Red 0.18", [0.18, 0, 0]),
    ("Green 0.18", [0, 0.18, 0]),
    ("Blue 0.18", [0, 0, 0.18]),
    ("Warm", [0.5, 0.18, 0.03]),
    ("Warm x2", [1.0, 0.36, 0.06]),
    ("Cool", [0, 0.18, 0.36]),
    ("Cool x2", [0, 0.36, 0.72]),
]
LINEAR_TOLERANCE = 2e-5
DISPLAY_TOLERANCE = 1 / 255 + 1e-5


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare(expected, measured):
    require(set(expected) == set(measured), "Patch scope mismatch")
    errors = []
    for name, target in expected.items():
        actual = measured[name]
        require(len(target) == len(actual) == 3, "Expected RGB measurements")
        require(all(math.isfinite(v) for v in target + actual), "Non-finite patch measurement")
        errors.extend(abs(a - b) for a, b in zip(target, actual, strict=True))
    require(errors, "No patch measurements")
    return {"max_absolute_error": max(errors), "mean_absolute_error": sum(errors) / len(errors)}


def srgb_encode(value):
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def assert_linear(expected, measured):
    report = compare(expected, measured)
    require(report["max_absolute_error"] <= LINEAR_TOLERANCE, f"Scene-linear mismatch: {report}")
    return report


def assert_standard(expected, measured, exposure):
    target = {
        name: [max(0, min(1, srgb_encode(value * 2**exposure))) for value in rgb]
        for name, rgb in expected.items()
    }
    report = compare(target, measured)
    require(
        report["max_absolute_error"] <= DISPLAY_TOLERANCE, f"Standard display mismatch: {report}"
    )
    return report


def display_properties(base, plus_one, view):
    balance = max(max(base[f"Gray {v:g}"]) - min(base[f"Gray {v:g}"]) for v in GRAY_VALUES)
    require(balance <= DISPLAY_TOLERANCE, f"{view} neutral channel imbalance: {balance}")
    intensities = [sum(base[f"Gray {v:g}"]) / 3 for v in GRAY_VALUES]
    require(
        all(a <= b + 1e-6 for a, b in zip(intensities, intensities[1:], strict=False)),
        f"{view} grayscale reversed",
    )
    count = len(GRAY_VALUES) if view == "AgX" else 8
    require(
        all(a < b for a, b in zip(intensities[:count], intensities[1:count], strict=False)),
        f"{view} expected grayscale range collapsed",
    )
    pairs = [
        ("Gray 0.018", "Gray 0.036"),
        ("Gray 0.18", "Gray 0.36"),
        ("Gray 0.5", "Gray 1"),
        ("Gray 1", "Gray 2"),
        ("Gray 2", "Gray 4"),
        ("Gray 4", "Gray 8"),
        ("Warm", "Warm x2"),
        ("Cool", "Cool x2"),
    ]
    error = max(
        abs(a - b)
        for left, right in pairs
        for a, b in zip(plus_one[left], base[right], strict=True)
    )
    require(error <= DISPLAY_TOLERANCE, f"{view} +1-stop/double-input mismatch: {error}")
    return {
        "maximum_neutral_channel_spread": balance,
        "grayscale_means": intensities,
        "exposure_equivalence_max_error": error,
        "exposure_pairs": pairs,
        "formula": "display(2*x, exposure=0) == display(x, exposure=1)",
    }


def pixels(path, centers, raw_display=False):
    import bpy

    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        detected = image.colorspace_settings.name
        if raw_display:
            image.colorspace_settings.name = "Non-Color"
        values = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(values)
        width, height = image.size
        measured = {}
        for name, (cx, cy) in centers.items():
            require(2 <= cx < width - 2 and 2 <= cy < height - 2, "Patch center outside image")
            measured[name] = [
                sum(
                    values[4 * (y * width + x) + channel]
                    for y in range(cy - 2, cy + 3)
                    for x in range(cx - 2, cx + 3)
                )
                / 25
                for channel in range(3)
            ]
        return measured, {
            "dimensions": [width, height],
            "detected_color_space": detected,
            "sample_color_space": image.colorspace_settings.name,
            "sample": "mean of central 5x5 pixels; RGB; bottom-left image origin",
        }
    finally:
        bpy.data.images.remove(image)


def settings(scene):
    return {
        "display_device": scene.display_settings.display_device,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "use_curve_mapping": scene.view_settings.use_curve_mapping,
        "use_white_balance": scene.view_settings.use_white_balance,
        "white_balance_temperature": scene.view_settings.white_balance_temperature,
        "white_balance_tint": scene.view_settings.white_balance_tint,
        "dither_intensity": scene.render.dither_intensity,
        "file_format": scene.render.image_settings.file_format,
        "color_depth": scene.render.image_settings.color_depth,
        "color_mode": scene.render.image_settings.color_mode,
    }


def emission_material(name, rgb):
    import bpy

    material = bpy.data.materials.new(name)
    material.node_tree.nodes.clear()
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*rgb, 1)
    emission.inputs["Strength"].default_value = 1
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def build_chart():
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    scene = bpy.data.scenes.new("Framewright_ColorPipelineFixture")
    bpy.context.window.scene = scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.cycles.seed = 0
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = 768, 432
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.threads_mode, scene.render.threads = "FIXED", 4
    scene.render.dither_intensity = 0
    scene.render.film_transparent = False
    scene.display_settings.display_device = "sRGB"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.view_settings.use_curve_mapping = False
    scene.view_settings.use_white_balance = False
    scene.world = bpy.data.worlds.new("ColorFixtureBlackWorld")
    scene.world.color = (0, 0, 0)
    background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
    background.inputs["Color"].default_value = (0, 0, 0, 1)
    background.inputs["Strength"].default_value = 0
    scene.render.image_settings.color_mode = "RGBA"
    scene.camera = bpy.data.objects.new(
        "ColorFixtureOrthographic", bpy.data.cameras.new("ColorFixtureCamera")
    )
    scene.collection.objects.link(scene.camera)
    scene.camera.location = (0, 0, 10)
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 6.4
    label_material = emission_material("ChartLabel", [0.4] * 3)
    centers = {}
    for index, (name, rgb) in enumerate(PATCHES):
        x, y = index % 6 - 2.5, 1 - index // 6
        mesh = bpy.data.meshes.new("Patch_" + name)
        mesh.from_pydata(
            [
                (x - 0.42, y - 0.30, 0),
                (x + 0.42, y - 0.30, 0),
                (x + 0.42, y + 0.40, 0),
                (x - 0.42, y + 0.40, 0),
            ],
            [],
            [(0, 1, 2, 3)],
        )
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        mesh.materials.append(emission_material("Linear_" + name, rgb))
        text_curve = bpy.data.curves.new("Label_" + name, "FONT")
        text_curve.body, text_curve.align_x, text_curve.size = name, "CENTER", 0.10
        label = bpy.data.objects.new("Label_" + name, text_curve)
        scene.collection.objects.link(label)
        label.location = (x, y - 0.44, 0)
        text_curve.materials.append(label_material)
        point = world_to_camera_view(scene, scene.camera, Vector((x, y, 0)))
        centers[name] = [
            int(point.x * scene.render.resolution_x),
            int(point.y * scene.render.resolution_y),
        ]
    bpy.context.view_layer.update()
    return scene, centers


def chart_fingerprint(scene):
    records = []
    for obj in sorted(scene.objects, key=lambda item: item.name):
        if obj.type != "MESH":
            continue
        shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == "EMISSION")
        records.append(
            {
                "name": obj.name,
                "vertices": [list(v.co) for v in obj.data.vertices],
                "matrix": [list(row) for row in obj.matrix_world],
                "emission": list(shader.inputs["Color"].default_value),
                "strength": shader.inputs["Strength"].default_value,
            }
        )
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def cold_decode(folder):
    import bpy

    manifest = json.loads((folder / "inputs.json").read_text())
    require(
        sha256(manifest["ocio_config"]) == manifest["ocio_config_sha256"],
        "OCIO config changed before cold decode",
    )
    expected = dict(manifest["patches"])
    decoded, comparisons = {}, {}
    for name, item in manifest["files"].items():
        path = folder / item["filename"]
        require(sha256(path) == item["sha256"], "Saved chart hash mismatch")
        measured, info = pixels(path, manifest["centers"], raw_display=path.suffix == ".png")
        decoded[name] = {"patches": measured, "image": info}
        if path.suffix == ".exr":
            require(
                info["detected_color_space"] == "Linear Rec.709",
                "Unexpected EXR scene-linear interpretation",
            )
            comparisons[name] = assert_linear(expected, measured)
    for exposure in (0, 1):
        comparisons[f"Standard_{exposure}"] = assert_standard(
            expected, decoded[f"Standard_{exposure}"]["patches"], exposure
        )
    for view in ("Standard", "AgX"):
        comparisons[view + "_properties"] = display_properties(
            decoded[view + "_0"]["patches"], decoded[view + "_1"]["patches"], view
        )
    rejected = False
    try:
        assert_standard(expected, decoded["WrongExposure"]["patches"], 0)
    except AssertionError:
        rejected = True
    require(rejected, "Actual corrupt exposure control was not rejected")
    report = {
        "blender": bpy.app.version_string,
        "cold_process": True,
        "ocio_config_sha256": sha256(manifest["ocio_config"]),
        "comparisons": comparisons,
        "decoded": decoded,
        "wrong_exposure_rejected": rejected,
        "EXR_hdr_maximum": max(
            v
            for name in ("Linear_0", "Linear_1")
            for rgb in decoded[name]["patches"].values()
            for v in rgb
        ),
    }
    (folder / "cold-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print("FRAMEWRIGHT_COLOR_COLD_OK " + str(folder))


def run_fixture(args):
    import bpy

    require(bpy.app.background, "Run only in an isolated background Blender process")
    original_scene = bpy.context.window.scene
    root = args.output_dir.resolve()
    folder = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    print("FRAMEWRIGHT_COLOR_PIPELINE_RUN " + str(folder), flush=True)
    scene, centers = build_chart()
    before = chart_fingerprint(scene)
    bpy.ops.render.render(scene=scene.name)
    rendered = bpy.data.images["Render Result"]
    files = {}
    for view in ("Standard", "AgX"):
        for exposure in (0, 1):
            scene.view_settings.view_transform = view
            scene.view_settings.look = "None"
            scene.view_settings.exposure = exposure
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_depth = "8"
            filename = f"{view}_{exposure}.png"
            rendered.save_render(str(folder / filename), scene=scene)
            files[f"{view}_{exposure}"] = {
                "filename": filename,
                "sha256": sha256(folder / filename),
                "settings": settings(scene),
            }
    # Explicit exposure corruption: these bytes are +1 stop but the negative
    # control asks the independent Standard validator to interpret them at zero.
    scene.view_settings.view_transform, scene.view_settings.exposure = "Standard", 1
    filename = "WrongExposure.png"
    rendered.save_render(str(folder / filename), scene=scene)
    files["WrongExposure"] = {
        "filename": filename,
        "sha256": sha256(folder / filename),
        "settings": settings(scene),
    }
    for exposure in (0, 1):
        scene.view_settings.exposure = exposure
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "32"
        scene.render.image_settings.exr_codec = "ZIP"
        filename = f"Linear_{exposure}.exr"
        rendered.save_render(str(folder / filename), scene=scene)
        files[f"Linear_{exposure}"] = {
            "filename": filename,
            "sha256": sha256(folder / filename),
            "settings": settings(scene),
        }
    require(chart_fingerprint(scene) == before, "Rendering changed chart source geometry/emission")
    config = Path(
        os.environ.get("OCIO")
        or Path(bpy.utils.system_resource("DATAFILES")) / "colormanagement/config.ocio"
    ).resolve()
    require(config.is_file(), "Cannot record active OCIO configuration")
    config_text = config.read_text()
    require(
        "scene_linear: Linear Rec.709" in config_text,
        "Fixture requires explicit Linear Rec.709 scene role",
    )
    ocio_files = {
        str(p.relative_to(config.parent)): sha256(p)
        for p in sorted(config.parent.rglob("*"))
        if p.is_file()
    }
    inputs = {
        "schema_version": "1.0",
        "blender": bpy.app.version_string,
        "blender_build_hash": bpy.app.build_hash.decode(),
        "script_sha256": sha256(__file__),
        "patches": PATCHES,
        "centers": centers,
        "resolution": [768, 432],
        "renderer": "Cycles CPU, 4 samples, fixed seed 0, adaptive/denoising off, 4 threads",
        "scene_linear": "Linear Rec.709",
        "ocio_version": bpy.app.ocio.version_string,
        "oiio_version": bpy.app.oiio.version_string,
        "ocio_config": str(config),
        "ocio_config_sha256": sha256(config),
        "ocio_directory_file_hashes": ocio_files,
        "source_fingerprint": before,
        "source_preserved": True,
        "world": {"background_linear_rgb": [0, 0, 0], "strength": 0},
        "camera": {"projection": "orthographic", "scale": 6.4, "position": [0, 0, 10]},
        "files": files,
        "tolerances": {"linear_absolute": LINEAR_TOLERANCE, "display_absolute": DISPLAY_TOLERANCE},
    }
    (folder / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="framewright-color-cold-") as temporary:
        env = os.environ.copy()
        for name in (
            "BLENDER_USER_CONFIG",
            "BLENDER_USER_SCRIPTS",
            "BLENDER_USER_EXTENSIONS",
            "BLENDER_USER_DATAFILES",
        ):
            env[name] = str(Path(temporary) / name)
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold-decode",
            str(folder),
        ]
        process = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=60, check=False
        )
    (folder / "cold.log").write_text(process.stdout + "\n" + process.stderr)
    require(
        process.returncode == 0,
        "Cold decode failed: " + process.stdout[-3000:] + process.stderr[-3000:],
    )
    report = json.loads((folder / "cold-verification.json").read_text())
    if args.inject_corruption == "exposure":
        assert_standard(dict(PATCHES), report["decoded"]["WrongExposure"]["patches"], 0)
    sections = "".join(
        f'<section><h2>{html.escape(view)} · exposure {exposure:+d}</h2><img src="{view}_{exposure}.png" alt="Known linear emission chart under {view} exposure {exposure}"></section>'
        for view in ("Standard", "AgX")
        for exposure in (0, 1)
    )
    (folder / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Framewright controlled color pipeline</title><style>body{background:#17191b;color:#eee;font:16px system-ui;max-width:1100px;margin:35px auto}img{width:100%;max-width:768px}h2{font-size:20px}</style><h1>Controlled color pipeline</h1><p>Known scene-linear emission patches; sRGB display. EXR preserves HDR up to 8. No physical monitor calibration or art acceptance.</p>'
        + sections
        + '<p><a href="inputs.json">Inputs, settings and hashes</a> · <a href="cold-verification.json">Independent process measurements</a></p></html>',
        encoding="utf-8",
    )
    bpy.context.window.scene = original_scene
    print("FRAMEWRIGHT_COLOR_PIPELINE_OK " + str(folder))


class VerificationTests(unittest.TestCase):
    def test_linear_hdr_retained(self):
        expected = {"gray": [0.18] * 3, "hdr": [4.0] * 3}
        self.assertLess(assert_linear(expected, expected)["max_absolute_error"], 1e-5)

    def test_clipped_hdr_rejected(self):
        with self.assertRaisesRegex(AssertionError, "linear"):
            assert_linear({"hdr": [4.0] * 3}, {"hdr": [1.0] * 3})

    def test_finite_and_exact_patch_scope_required(self):
        with self.assertRaises(AssertionError):
            assert_linear({"gray": [0.18] * 3}, {"gray": [math.nan] * 3})
        with self.assertRaises(AssertionError):
            assert_linear({"gray": [0.18] * 3}, {})

    def test_standard_transfer_and_one_stop(self):
        expected = {"gray": [0.18] * 3, "color": [0.03, 0.18, 0.5]}
        for exposure in (0, 1):
            actual = {
                name: [min(1, srgb_encode(v * 2**exposure)) for v in rgb]
                for name, rgb in expected.items()
            }
            self.assertLess(assert_standard(expected, actual, exposure)["max_absolute_error"], 1e-5)

    def test_wrong_exposure_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Standard"):
            assert_standard({"gray": [0.18] * 3}, {"gray": [srgb_encode(0.36)] * 3}, 0)

    def test_wrong_linear_as_display_encoding_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Standard"):
            assert_standard({"gray": [0.18] * 3}, {"gray": [0.18] * 3}, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cold-decode", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/color-pipeline")
    parser.add_argument("--inject-corruption", choices=("exposure",))
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :]
        if "--" in sys.argv
        else []
        if "--background" in sys.argv
        else sys.argv[1:]
    )
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(VerificationTests)
        )
        if not result.wasSuccessful():
            raise SystemExit(1)
    elif args.cold_decode:
        cold_decode(args.cold_decode.resolve())
    else:
        run_fixture(args)


if __name__ == "__main__":
    main()
