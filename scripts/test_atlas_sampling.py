"""Public atlas sampling: analytic texel averages, repeatability and preservation."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from test_material_atlas import inventory, source_state  # noqa: E402

from framewright import material_atlas  # noqa: E402
from framewright.api import dispatch  # noqa: E402

EVIDENCE = {}


def sampling(scene):
    return {
        "engine": scene.render.engine,
        "device": scene.cycles.device,
        "samples": scene.cycles.samples,
        "seed": scene.cycles.seed,
        "animated_seed": scene.cycles.use_animated_seed,
        "adaptive_sampling": scene.cycles.use_adaptive_sampling,
        "denoising": scene.cycles.use_denoising,
    }


def source_fixture():
    mesh = bpy.data.meshes.new("AnalyticPlane")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name="SourceUV")
    uv.active_render = True
    for loop in mesh.loops:
        uv.data[loop.index].uv = mesh.vertices[loop.vertex_index].co[:2]
    obj = bpy.data.objects.new("AnalyticPlane", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mat = bpy.data.materials.new("Subpixel sinusoid")
    mat.use_nodes = True
    mesh.materials.append(mat)
    tree = mat.node_tree
    shader = tree.nodes.get("Principled BSDF")
    coord = tree.nodes.new("ShaderNodeTexCoord")
    separate = tree.nodes.new("ShaderNodeSeparateColor")
    tree.links.new(coord.outputs["UV"], separate.inputs[0])
    multiply = tree.nodes.new("ShaderNodeMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = 2 * math.pi * 58.3
    tree.links.new(separate.outputs[0], multiply.inputs[0])
    sine = tree.nodes.new("ShaderNodeMath")
    sine.operation = "SINE"
    tree.links.new(multiply.outputs[0], sine.inputs[0])
    scale = tree.nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY_ADD"
    scale.inputs[1].default_value = 0.5
    scale.inputs[2].default_value = 0.5
    tree.links.new(sine.outputs[0], scale.inputs[0])
    tree.links.new(scale.outputs[0], shader.inputs["Base Color"])
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.7
    bump.inputs["Distance"].default_value = 0.01
    tree.links.new(scale.outputs[0], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    bpy.context.view_layer.update()
    return obj, float(multiply.inputs[1].default_value) / (2 * math.pi)


def analytic_average(derivative, atlas_uv, frequency, resolution):
    """Integrate sin(linear source-U) over actual output texels, away from edges."""
    mesh = derivative.data
    mesh.calc_loop_triangles()
    yy, xx = np.mgrid[:resolution, :resolution]
    centers = np.stack(
        ((xx + 0.5) / resolution, (yy + 0.5) / resolution, np.ones_like(xx)), axis=-1
    )
    expected = np.zeros((resolution, resolution), dtype=np.float64)
    mask = np.zeros_like(expected, dtype=bool)
    for triangle in mesh.loop_triangles:
        uv = np.array([mesh.uv_layers[atlas_uv].data[i].uv[:] for i in triangle.loops])
        basis = np.column_stack((uv, np.ones(3)))
        inverse = np.linalg.inv(basis)
        original_u = np.array([mesh.uv_layers["SourceUV"].data[i].uv.x for i in triangle.loops])
        a, b, c = inverse @ original_u
        interior = np.ones_like(mask)
        # Retried bake jitter does not cross triangle boundaries. Exclude a
        # two-pixel neighborhood, so the analytic square footprint is valid.
        for dx, dy in ((-2, -2), (-2, 2), (2, -2), (2, 2)):
            points = centers + np.array((dx / resolution, dy / resolution, 0))
            interior &= np.min(points @ inverse, axis=-1) > 0
        value = 0.5 + 0.5 * np.sin(
            2 * math.pi * frequency * (a * centers[:, :, 0] + b * centers[:, :, 1] + c)
        ) * np.sinc(frequency * a / resolution) * np.sinc(frequency * b / resolution)
        assert not np.any(mask & interior)
        expected[interior] = value[interior]
        mask |= interior
    assert int(mask.sum()) > resolution**2 / 4, "Insufficient analytic interior"
    return expected, mask


class AtlasSamplingTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.source, self.frequency = source_fixture()
        scene = bpy.context.scene
        scene.frame_set(37)
        scene.cycles.samples = 7
        scene.cycles.seed = 173
        scene.cycles.use_animated_seed = True
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = True
        self.source_scene = scene
        self.preserved = (source_state([self.source]), sampling(scene), scene.frame_current)

    def assert_source_preserved(self):
        self.assertEqual(
            (
                source_state([self.source]),
                sampling(self.source_scene),
                self.source_scene.frame_current,
            ),
            self.preserved,
        )
        self.assertIs(bpy.context.scene, self.source_scene)

    def request(self, **changes):
        return {
            "schema_version": "1.0",
            "request_id": "analytic-atlas",
            "command": "surfaces.bake_material_atlas",
            "params": {
                "object_names": [self.source.name],
                "resolution": 64,
                "margin": 0,
                "dry_run": False,
                **changes,
            },
        }

    def bake(self, label, **changes):
        observations = []
        original = material_atlas._bake_pass

        def observe(scene, *args):
            observations.append(sampling(scene))
            return original(scene, *args)

        started = time.perf_counter()
        with patch.object(material_atlas, "_bake_pass", observe):
            response = dispatch(self.request(**changes))
        self.assertTrue(response["ok"], response)
        result = response["result"]
        arrays, hashes = {}, {}
        folder = ROOT / "artifacts" / "atlas-sampling" / label
        folder.mkdir(parents=True, exist_ok=True)
        for role, info in result["maps"].items():
            image = bpy.data.images[info["image"]]
            values = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(values)
            arrays[role] = values.reshape(64, 64, 4)
            encoded = bytes(image.packed_file.data)
            hashes[role] = hashlib.sha256(encoded).hexdigest()
            (folder / (role + ".png")).write_bytes(encoded)
        derivative = bpy.data.objects[result["derivatives"][self.source.name]]
        expected, mask = analytic_average(derivative, result["uv_layer"], self.frequency, 64)
        error = float(np.abs(arrays["base_color"][:, :, 0] - expected)[mask].mean())
        np.savez_compressed(folder / "raw-and-expected.npz", expected=expected, mask=mask, **arrays)
        self.assert_source_preserved()
        EVIDENCE[label] = {
            "analytic_interior_mae": error,
            "interior_pixels": int(mask.sum()),
            "png_sha256": hashes,
            "output_folder": folder.relative_to(ROOT).as_posix(),
            "raw_and_expected_sha256": hashlib.sha256(
                (folder / "raw-and-expected.npz").read_bytes()
            ).hexdigest(),
            "observed_sampling_per_pass": observations,
            "reported_effective_sampling": result.get("effective_sampling"),
            "seconds": time.perf_counter() - started,
            "source_preserved": True,
        }
        return result, arrays, hashes, error, observations

    def test_default_reduces_actual_public_bake_aliasing_and_seed_repeat_is_exact(self):
        result, arrays, hashes, default_error, observations = self.bake("default16")
        # This genuinely fails against the old one-sample public implementation.
        self.assertLess(default_error, 0.08)
        self.assertEqual(result["bake_samples"], 16)
        self.assertEqual(result["effective_sampling"], observations[0])
        self.assertEqual(observations, [observations[0]] * 4)
        _, legacy_arrays, _, legacy_error, _ = self.bake("legacy1", bake_samples=1)
        self.assertGreater(legacy_error, 0.20)
        self.assertLess(default_error, legacy_error / 4)
        self.assertGreater(float(np.abs(arrays["normal"] - legacy_arrays["normal"]).mean()), 0.01)
        _, _, repeated, _, _ = self.bake("default16_repeat")
        self.assertEqual(hashes, repeated)

    def test_explicit_bounds_apply_to_real_bakes_and_do_not_inherit_source_settings(self):
        for samples in (1, 64):
            with self.subTest(samples=samples):
                result, _, _, _, observations = self.bake(
                    f"explicit{samples}", bake_samples=samples
                )
                expected = {
                    "engine": "CYCLES",
                    "device": "CPU",
                    "samples": samples,
                    "seed": 0,
                    "animated_seed": False,
                    "adaptive_sampling": False,
                    "denoising": False,
                }
                self.assertEqual(observations, [expected] * 4)
                self.assertEqual(result["effective_sampling"], expected)

    def test_preview_allocates_nothing_and_does_not_claim_effective_execution(self):
        before = inventory()
        response = dispatch(self.request(dry_run=True))
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["bake_samples"], 16)
        self.assertNotIn("effective_sampling", response["result"])
        self.assertEqual(inventory(), before)
        self.assert_source_preserved()

    def test_partial_failure_rolls_back_outputs_and_preserves_source_sampling(self):
        before = inventory()
        original = material_atlas._pack_png
        calls = []

        def fail_second(image, role):
            calls.append(role)
            if len(calls) == 2:
                raise RuntimeError("injected second-map packing failure")
            return original(image, role)

        with patch.object(material_atlas, "_pack_png", fail_second):
            response = dispatch(self.request())
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(calls, ["base_color", "roughness"])
        self.assertEqual(inventory(), before)
        self.assert_source_preserved()


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AtlasSamplingTests)
    )
    output = ROOT / "artifacts" / "atlas-sampling"
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(
            {
                "passed": result.wasSuccessful(),
                "tests_run": result.testsRun,
                "blender": bpy.app.version_string,
                "build_hash": bpy.app.build_hash.decode(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "runtime_sha256": {
                    name: hashlib.sha256((ROOT / "framewright" / name).read_bytes()).hexdigest()
                    for name in ("atlas_plan.py", "commands.py", "material_atlas.py")
                },
                "cases": EVIDENCE,
                "limits": "Analytic planar emission interior only; changed normal samples do not establish angular accuracy, universal AA or artistic acceptance.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
