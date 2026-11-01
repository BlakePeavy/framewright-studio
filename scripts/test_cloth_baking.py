"""Allowlisted isolated cloth baking, ownership, budgets and cold playback."""

import argparse
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from test_cloth_simulation import ClothSimulationTests, coordinates, source_state  # noqa: E402

from framewright import cloth_baking  # noqa: E402
from framewright.api import dispatch  # noqa: E402
from framewright.workflows import clear_run_cache  # noqa: E402


def cold_verify(path):
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    scene = bpy.data.scenes[receipt["result"]["scene"]]
    bpy.context.window.scene = scene
    derivative = scene.objects[receipt["result"]["derivative"]]
    derivative.hide_viewport = False
    derivative.hide_render = False
    derivative.hide_set(False)
    cache = derivative.modifiers[receipt["result"]["modifier"]].point_cache
    assert cache.is_baked and not cache.use_external and not cache.use_disk_cache
    maximum = 0.0
    for frame in (61, 1, 31, 16):
        scene.frame_set(frame)
        actual = coordinates(derivative)
        maximum = max(
            maximum,
            max(
                abs(a - b)
                for p, q in zip(actual, receipt["frames"][str(frame)], strict=True)
                for a, b in zip(p, q, strict=True)
            ),
        )
    assert maximum < 0.00001, maximum
    original = bpy.data.objects[receipt["source_proxy"]]
    assert not original.modifiers[receipt["source_modifier"]].point_cache.is_baked
    assert (
        hashlib.sha256(Path(receipt["authored_file"]).read_bytes()).hexdigest()
        == receipt["authored_sha"]
    )
    assert not list(Path(path).parent.rglob("*.bphys"))
    print(json.dumps({"cloth_command_cold_verified": True, "maximum_vertex_error": maximum}))


class ClothBakeTests(unittest.TestCase):
    plane = ClothSimulationTests.plane
    fixture = ClothSimulationTests.fixture
    sample = ClothSimulationTests.sample

    def setUp(self):
        ClothSimulationTests.setUp(self)
        self.kinds += ("lights", "images")
        for kind in ("lights", "images"):
            self.before[kind] = {item.session_uid for item in getattr(bpy.data, kind)}

    def tearDown(self):
        clear_run_cache()
        ClothSimulationTests.tearDown(self)

    def params(self, fixture, **changes):
        return {
            "object_name": fixture["proxy"].name,
            "modifier_name": "Framewright Cloth",
            **changes,
        }

    def ids(self):
        return {
            kind: {item.session_uid for item in getattr(bpy.data, kind)}
            for kind in ("objects", "meshes", "collections", "scenes")
        }

    def source_snapshot(self, fixture):
        cache = fixture["proxy"].modifiers["Framewright Cloth"].point_cache
        return {
            "geometry": source_state([fixture["source"], fixture["ground"], fixture["proxy"]]),
            "frame": [fixture["scene"].frame_current, fixture["scene"].frame_subframe],
            "cache": [
                cache.info,
                cache.is_baked,
                cache.is_outdated,
                cache.use_disk_cache,
                cache.use_external,
                cache.frame_start,
                cache.frame_end,
            ],
            "selected": sorted(obj.name for obj in bpy.context.selected_objects),
            "active": bpy.context.view_layer.objects.active,
        }

    def test_preview_reports_estimates_without_allocations(self):
        fixture = self.fixture()
        before = self.ids(), self.source_snapshot(fixture)
        result = cloth_baking.bake_cloth(self.params(fixture))
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["frame_count"], 61)
        self.assertEqual(result["cloth_vertices"], 81)
        self.assertGreater(result["estimated_memory_bytes"], 0)
        self.assertEqual(before, (self.ids(), self.source_snapshot(fixture)))

    def test_missing_or_foreign_ownership_refuses_before_allocation(self):
        for target in ("proxy", "collection", "collider"):
            with self.subTest(target=target):
                fixture = self.fixture()
                cloth = fixture["proxy"].modifiers["Framewright Cloth"]
                owner = {
                    "proxy": fixture["proxy"],
                    "collection": cloth.collision_settings.collection,
                    "collider": fixture["scene"].objects[
                        fixture["result"]["collider_derivatives"][0]
                    ],
                }[target]
                owner["framewright_cloth_id"] = "foreign"
                before = self.ids()
                with self.assertRaisesRegex(ValueError, "ownership"):
                    cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
                self.assertEqual(before, self.ids())
        fixture = self.fixture()
        del fixture["proxy"]["framewright_cloth_id"]
        with self.assertRaisesRegex(ValueError, "ownership"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))

    def test_valid_ownership_survives_proxy_collider_and_collection_renames(self):
        fixture = self.fixture()
        fixture["proxy"].name = "RenamedProxy"
        collection = fixture["proxy"].modifiers["Framewright Cloth"].collision_settings.collection
        collection.name = "RenamedColliders"
        for obj in collection.objects:
            obj.name = "RenamedCollider"
        self.assertTrue(cloth_baking.bake_cloth(self.params(fixture))["dry_run"])

    def test_frame_geometry_memory_and_work_budgets_reject_before_allocation(self):
        fixture = self.fixture()
        before = self.ids()
        for options in ({"max_frames": 60}, {"max_vertices": 80}, {"max_memory_mb": 1}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "budget"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False, **options))
        with patch.object(cloth_baking, "MAX_WORK_UNITS", 1):
            with self.assertRaisesRegex(ValueError, "work budget"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(before, self.ids())

    def test_static_dependency_and_external_cache_rejections(self):
        fixture = self.fixture()
        proxy = fixture["proxy"]
        before = self.ids()
        proxy.parent = fixture["source"]
        with self.assertRaisesRegex(ValueError, "parent"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        proxy.parent = None
        proxy.animation_data_create()
        with self.assertRaisesRegex(ValueError, "animated"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        proxy.animation_data_clear()
        extra = proxy.modifiers.new("Unsupported", "BEVEL")
        with self.assertRaisesRegex(ValueError, "modifier"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        proxy.modifiers.remove(extra)
        cache = proxy.modifiers["Framewright Cloth"].point_cache
        for flag in ("use_disk_cache", "use_external"):
            setattr(cache, flag, True)
            with self.assertRaisesRegex(ValueError, "embedded"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
            setattr(cache, flag, False)
        self.assertEqual(before, self.ids())

    def test_existing_bake_is_refused_without_replacement(self):
        fixture = self.fixture()
        self.sample(fixture)
        proxy = fixture["proxy"]
        cache = proxy.modifiers["Framewright Cloth"].point_cache
        with bpy.context.temp_override(point_cache=cache, object=proxy, active_object=proxy):
            bpy.ops.ptcache.bake_from_cache()
        before = self.ids(), self.source_snapshot(fixture)
        with self.assertRaisesRegex(ValueError, "already baked"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(before, (self.ids(), self.source_snapshot(fixture)))

    def test_multiple_caches_and_custom_frame_handlers_reject_before_allocation(self):
        fixture = self.fixture()
        proxy = fixture["proxy"]
        cache = proxy.modifiers["Framewright Cloth"].point_cache
        with bpy.context.temp_override(point_cache=cache, object=proxy, active_object=proxy):
            self.assertEqual(bpy.ops.ptcache.add(), {"FINISHED"})
        before = self.ids()
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(before, self.ids())

        def foreign_handler(*args):
            raise AssertionError("Foreign handler must never execute")

        bpy.app.handlers.frame_change_pre.append(foreign_handler)
        try:
            with self.assertRaisesRegex(ValueError, "handlers"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        finally:
            bpy.app.handlers.frame_change_pre.remove(foreign_handler)
        self.assertEqual(before, self.ids())

    def test_operator_without_a_completed_cache_fails_closed_and_cleans(self):
        fixture = self.fixture()
        before = self.ids(), self.source_snapshot(fixture)
        with patch.object(cloth_baking, "_bake_selected", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "embedded bake"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(before, (self.ids(), self.source_snapshot(fixture)))

    def test_static_material_is_retained_and_unrelated_animated_light_override_preserved(self):
        fixture = self.fixture()
        material = bpy.data.materials.new("StaticClothMaterial")
        material.use_nodes = True
        image = bpy.data.images.new("StaticClothImage", width=2, height=2)
        material.node_tree.nodes.new("ShaderNodeTexImage").image = image
        fixture["proxy"].data.materials.append(material)
        light_data = bpy.data.lights.new("UnrelatedAnimatedLight", "AREA")
        light = bpy.data.objects.new("UnrelatedAnimatedLight", light_data)
        fixture["scene"].collection.objects.link(light)
        for frame, energy in ((1, 10), (61, 100)):
            light_data.energy = energy
            light_data.keyframe_insert("energy", frame=frame)
        fixture["scene"].frame_set(3, subframe=0.25)
        light_data.energy = 123.456
        before = (
            self.source_snapshot(fixture),
            light_data.energy,
            len(material.node_tree.nodes),
            image.colorspace_settings.name,
        )
        result = cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(
            before,
            (
                self.source_snapshot(fixture),
                light_data.energy,
                len(material.node_tree.nodes),
                image.colorspace_settings.name,
            ),
        )
        derivative = bpy.data.scenes[result["scene"]].objects[result["derivative"]]
        self.assertEqual(derivative.data.materials[0], material)

    def test_mid_bake_failure_removes_only_new_scene_and_derivatives(self):
        fixture = self.fixture()
        fixture["scene"].frame_set(3, subframe=0.25)
        before = self.ids(), self.source_snapshot(fixture)

        def fail(scene, proxy, cache):
            for frame in range(1, 6):
                scene.frame_set(frame)
                coordinates(proxy)
            raise RuntimeError("Injected mid-bake failure")

        with patch.object(cloth_baking, "_bake_selected", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                cloth_baking.bake_cloth(self.params(fixture, dry_run=False))
        self.assertEqual(bpy.context.scene, fixture["scene"])
        self.assertEqual(before, (self.ids(), self.source_snapshot(fixture)))

    def test_public_workflow_bakes_independent_cache_and_cold_reopens(self):
        fixture = self.fixture(save_source=True)
        scene = fixture["scene"]
        for frame in range(1, 4):
            scene.frame_set(frame)
            coordinates(fixture["proxy"])
        before = self.source_snapshot(fixture)
        workflow = {
            "run_id": "cloth-command",
            "dry_run": False,
            "steps": [
                {
                    "id": "proxy",
                    "command": "secondary.create_cloth_proxy",
                    "params": {
                        "object_name": fixture["source"].name,
                        "pin_group": "PinnedEdge",
                        "frame_start": 1,
                        "frame_end": 61,
                        "quality": 8,
                        "collision_distance": 0.01,
                        "collider_names": [fixture["ground"].name],
                        "dry_run": False,
                    },
                },
                {
                    "id": "bake",
                    "command": "secondary.bake_cloth",
                    "params": {
                        "object_name": {"$ref": "proxy.result.derivative"},
                        "modifier_name": "Framewright Cloth",
                        "dry_run": False,
                    },
                    "require": [{"path": "result.is_baked", "equals": True}],
                },
            ],
        }
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "cloth-workflow",
                "command": "workflow.run",
                "params": workflow,
            }
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["status"], "completed", response)
        result = response["result"]["steps"][-1]["response"]["result"]
        self.assertEqual(before, self.source_snapshot(fixture))
        self.assertEqual(bpy.context.scene, scene)
        self.assertTrue(result["is_baked"])
        self.assertEqual(result["evaluated_frames"], 61)
        baked_scene = bpy.data.scenes[result["scene"]]
        derivative = baked_scene.objects[result["derivative"]]
        self.assertNotEqual(derivative.data, fixture["proxy"].data)
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        bpy.context.window.scene = baked_scene
        derivative.hide_viewport = False
        derivative.hide_render = False
        expected = {}
        for frame in (1, 16, 31, 61):
            baked_scene.frame_set(frame)
            expected[str(frame)] = coordinates(derivative)
        self.assertLess(min(point[2] for point in expected["61"]), 1.4)
        self.assertGreater(min(point[2] for point in expected["61"]), 0.88)
        derivative.hide_viewport = True
        derivative.hide_render = True
        bpy.context.window.scene = scene
        output = self.directory / "command-baked.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
        source_proxy = response["result"]["steps"][0]["response"]["result"]["derivative"]
        receipt = {
            "result": result,
            "frames": expected,
            "source_proxy": source_proxy,
            "source_modifier": "Framewright Cloth",
            "authored_file": str(fixture["authored_file"]),
            "authored_sha": fixture["authored_sha"],
        }
        receipt_path = self.directory / "command-receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(output),
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold",
            str(receipt_path),
        ]
        cold = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(cold.returncode, 0, cold.stdout[-5000:] + cold.stderr[-5000:])
        self.assertIn('"cloth_command_cold_verified": true', cold.stdout)
        self.assertEqual(
            hashlib.sha256(fixture["authored_file"].read_bytes()).hexdigest(),
            fixture["authored_sha"],
        )
        self.assertFalse(list(self.directory.rglob("*.bphys")))
        evidence = {
            "workflow_status": response["result"]["status"],
            "result": result,
            "authored_file_sha256": fixture["authored_sha"],
            "authored_file_unchanged": True,
            "output_file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "cold_verification": next(
                json.loads(line)
                for line in cold.stdout.splitlines()
                if line.startswith('{"cloth_command_cold_verified"')
            ),
            "external_bphys_files": 0,
            "artist_review": "not_evaluated",
        }
        (self.directory / "command-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        print("CLOTH_COMMAND_EVIDENCE " + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold", type=Path)
    parser.add_argument("--pilot-dir", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        raise RuntimeError("Run only in owned background Blender")
    if args.cold:
        cold_verify(args.cold)
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ClothBakeTests)
        )
        if not result.wasSuccessful():
            raise RuntimeError("Cloth command tests failed")
        print(f"FRAMEWRIGHT_CLOTH_BAKING_OK tests={result.testsRun}")
        if args.pilot_dir:
            args.pilot_dir.mkdir(parents=True, exist_ok=False)
            pilot = ClothBakeTests("test_public_workflow_bakes_independent_cache_and_cold_reopens")
            pilot.setUp()
            try:
                pilot.directory = args.pilot_dir.resolve()
                pilot.test_public_workflow_bakes_independent_cache_and_cold_reopens()
            finally:
                pilot.tearDown()
