"""Isolated tests for the bounded interior/glass reference scene."""

from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import light_review  # noqa: E402
from framewright.api import dispatch  # noqa: E402

KINDS = (
    "objects",
    "meshes",
    "materials",
    "collections",
    "scenes",
    "worlds",
    "cameras",
    "lights",
    "images",
)


def ids():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


def context_state():
    scene = bpy.context.scene
    return {
        "scene": scene.as_pointer(),
        "active": bpy.context.view_layer.objects.active.as_pointer()
        if bpy.context.view_layer.objects.active
        else None,
        "selection": [(obj.as_pointer(), obj.select_get()) for obj in scene.objects],
        "frame": (scene.frame_current, scene.frame_subframe),
        "settings": (
            scene.render.engine,
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.view_settings.view_transform,
            scene.view_settings.exposure,
        ),
        "objects": [
            (
                obj.as_pointer(),
                tuple(value for row in obj.matrix_world for value in row),
                tuple(tuple(vertex.co) for vertex in obj.data.vertices)
                if obj.type == "MESH"
                else None,
            )
            for obj in scene.objects
        ],
    }


class InteriorFixtureTests(unittest.TestCase):
    def setUp(self):
        self.before_ids = ids()
        self.before_context = context_state()

    def tearDown(self):
        self.assertEqual(context_state(), self.before_context)
        for kind in (
            "objects",
            "scenes",
            "collections",
            "meshes",
            "cameras",
            "lights",
            "worlds",
            "materials",
            "images",
        ):
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before_ids[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def test_preview_has_explicit_budgets_and_allocates_nothing(self):
        result = light_review.create_interior_fixture({})
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["budget"]["pixel_samples"], 512 * 512 * 64)
        self.assertFalse(result["visual_acceptance"])
        self.assertEqual(ids(), self.before_ids)

    def test_public_dispatch_schema_preview_and_apply(self):
        request = {
            "schema_version": "1.0",
            "request_id": "interior-fixture-test",
            "command": "lighting.create_interior_fixture",
            "params": {},
        }
        response = dispatch(request)
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["result"]["dry_run"])
        self.assertEqual(ids(), self.before_ids)
        request["params"] = {"samples": True}
        self.assertFalse(dispatch(request)["ok"])
        self.assertEqual(ids(), self.before_ids)
        request["params"] = {"dry_run": False, "resolution": 128, "samples": 8}
        response = dispatch(request)
        self.assertTrue(response["ok"], response)
        self.assertEqual(bpy.data.scenes[response["result"]["scene"]].render.resolution_x, 128)

    def test_worker_thread_refused_before_any_blender_mutation(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(light_review.create_interior_fixture, {"dry_run": False})
            with self.assertRaisesRegex(RuntimeError, "main thread"):
                future.result()
        self.assertEqual(ids(), self.before_ids)

    def test_budget_rejection_precedes_creation_and_explicit_8k_preview_is_possible(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            light_review.create_interior_fixture({"resolution": 8192, "dry_run": False})
        result = light_review.create_interior_fixture(
            {
                "resolution": 8192,
                "samples": 1,
                "max_pixel_samples": 8192**2,
                "max_render_memory_mb": 4096,
            }
        )
        self.assertEqual(result["budget"]["estimated_render_buffer_bytes"], 8192**2 * 64)
        self.assertEqual(ids(), self.before_ids)

    def test_invalid_parameters_refused_without_data(self):
        for params in (
            {"unknown": 1},
            {"dry_run": 0},
            {"samples": True},
            {"glass_thickness": float("nan")},
            {"ior": 0.9},
            {"roughness": 0.5},
            {"window_power": -1},
            {"resolution": 32},
            {"max_render_memory_mb": 0},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                light_review.create_interior_fixture(params)
        self.assertEqual(ids(), self.before_ids)

    def test_apply_creates_independent_editable_glass_room_without_changing_sources(self):
        result = light_review.create_interior_fixture(
            {"glass_thickness": 0.12, "ior": 1.52, "samples": 16, "dry_run": False}
        )
        scene = bpy.data.scenes[result["scene"]]
        glass = bpy.data.objects[result["objects"]["glass"]]
        self.assertNotEqual(scene, bpy.context.scene)
        self.assertEqual(scene["framewright_owner"], "light_review")
        self.assertAlmostEqual(
            max(v.co.y for v in glass.data.vertices) - min(v.co.y for v in glass.data.vertices),
            0.12,
            places=6,
        )
        edges = {
            tuple(sorted((p.vertices[i], p.vertices[(i + 1) % len(p.vertices)])))
            for p in glass.data.polygons
            for i in range(len(p.vertices))
        }
        self.assertEqual(
            (len(glass.data.vertices), len(edges), len(glass.data.polygons)), (8, 12, 6)
        )
        shader = next(
            n for n in glass.data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED"
        )
        self.assertEqual(shader.inputs["Transmission Weight"].default_value, 1)
        self.assertAlmostEqual(shader.inputs["IOR"].default_value, 1.52, places=5)
        self.assertAlmostEqual(result["contact"]["glass_bottom_to_floor"], 0, places=6)
        self.assertAlmostEqual(result["contact"]["block_bottom_to_floor"], 0, places=6)
        self.assertEqual(scene.cycles.transmission_bounces, 12)
        self.assertEqual(scene.render.resolution_x, 512)
        self.assertEqual(scene.cycles.samples, 16)
        self.assertEqual(scene.view_settings.view_transform, "AgX")
        self.assertEqual(set(result["cameras"]), {"front", "three_quarter"})
        self.assertEqual(len(scene.objects), result["object_count"])
        self.assertEqual(ids()["images"], self.before_ids["images"])

    def test_failed_creation_rolls_back_only_owned_datablocks(self):
        original = light_review._box
        calls = 0

        def fail_after_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected interior creation failure")
            return original(*args, **kwargs)

        with (
            patch.object(light_review, "_box", side_effect=fail_after_first),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            light_review.create_interior_fixture({"dry_run": False})
        self.assertEqual(ids(), self.before_ids)

    def test_repeated_names_never_replace_existing_scene(self):
        first = light_review.create_interior_fixture({"name": "RepeatedInterior", "dry_run": False})
        second = light_review.create_interior_fixture(
            {"name": "RepeatedInterior", "dry_run": False}
        )
        self.assertNotEqual(first["scene"], second["scene"])
        self.assertNotEqual(first["objects"]["glass"], second["objects"]["glass"])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(InteriorFixtureTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Interior fixture tests failed")
