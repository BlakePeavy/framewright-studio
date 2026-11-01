"""Owned cloth dynamics, collision scope and embedded-cache cold playback."""

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import secondary_motion  # noqa: E402

START, END = 1, 61
GROUND_Z = 0.9
SIDE = 9


def coordinates(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        result = [list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices]
        if not all(math.isfinite(value) for point in result for value in point):
            raise AssertionError("Cloth produced non-finite evaluated vertices")
        return result
    finally:
        evaluated.to_mesh_clear()


def source_state(objects):
    return [
        {
            "name": obj.name,
            "vertices": [list(vertex.co) for vertex in obj.data.vertices],
            "polygons": [list(poly.vertices) for poly in obj.data.polygons],
            "weights": [
                [[group.group, group.weight] for group in vertex.groups]
                for vertex in obj.data.vertices
            ],
            "modifiers": [[modifier.name, modifier.type] for modifier in obj.modifiers],
            "matrix": [list(row) for row in obj.matrix_world],
        }
        for obj in objects
    ]


def cold_verify(receipt_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    scene = bpy.data.scenes[receipt["scene"]]
    bpy.context.window.scene = scene
    proxy = scene.objects[receipt["proxy"]]
    cache = next(modifier.point_cache for modifier in proxy.modifiers if modifier.type == "CLOTH")
    assert cache.is_baked, "Cold reopen lost the baked cache"
    assert not cache.use_disk_cache and not cache.use_external
    assert cache.id_data == proxy, "Cache is not owned by the proxy"
    collision_collection = next(
        modifier.collision_settings.collection
        for modifier in proxy.modifiers
        if modifier.type == "CLOTH"
    )
    assert collision_collection.name == receipt["collision_collection"]
    assert sorted(obj.name for obj in collision_collection.all_objects) == sorted(
        receipt["collider_derivatives"]
    )
    maximum = 0.0
    # Deliberately nonsequential: this must play the saved bake, not a fresh sim.
    for frame in (END, START, 41, 21):
        scene.frame_set(frame)
        actual = coordinates(proxy)
        expected = receipt["frames"][str(frame)]
        maximum = max(
            maximum,
            max(
                abs(a - b)
                for p, q in zip(actual, expected, strict=True)
                for a, b in zip(p, q, strict=True)
            ),
        )
    assert maximum < 0.00001, f"Cold playback differs by {maximum} Blender units"
    assert (
        source_state([scene.objects[name] for name in receipt["sources"]])
        == receipt["source_state"]
    )
    assert (
        hashlib.sha256(Path(receipt["authored_file"]).read_bytes()).hexdigest()
        == receipt["authored_sha256"]
    )
    assert not list(Path(receipt_path).parent.rglob("*.bphys")), "Unexpected external physics cache"
    print(
        json.dumps(
            {"cold_cache_verified": True, "maximum_vertex_error": maximum, "baked": cache.is_baked}
        )
    )


class ClothSimulationTests(unittest.TestCase):
    def setUp(self):
        self.previous_scene = bpy.context.window.scene
        self.kinds = ("objects", "scenes", "meshes", "collections", "materials", "actions")
        self.before = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)} for kind in self.kinds
        }
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        bpy.context.window.scene = self.previous_scene
        for kind in self.kinds:
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)
        self.temp.cleanup()

    def plane(self, scene, name, z, half=3):
        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata(
            [(-half, -half, z), (half, -half, z), (half, half, z), (-half, half, z)],
            [],
            [(0, 1, 2, 3)],
        )
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return obj

    def fixture(self, *, floor=True, intruder=False, gravity=-9.81, save_source=False):
        scene = bpy.data.scenes.new("ClothDynamics")
        bpy.context.window.scene = scene
        scene.frame_start, scene.frame_end = START, END
        scene.render.fps = 24
        scene.gravity = (0, 0, gravity)
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1
        mesh = bpy.data.meshes.new("AuthoredSheetMesh")
        vertices = [
            (x / (SIDE - 1) - 0.5, y / (SIDE - 1), 1.5) for y in range(SIDE) for x in range(SIDE)
        ]
        polygons = [
            (y * SIDE + x, y * SIDE + x + 1, (y + 1) * SIDE + x + 1, (y + 1) * SIDE + x)
            for y in range(SIDE - 1)
            for x in range(SIDE - 1)
        ]
        mesh.from_pydata(vertices, [], polygons)
        source = bpy.data.objects.new("AuthoredSheet", mesh)
        scene.collection.objects.link(source)
        source.vertex_groups.new(name="PinnedEdge").add(list(range(SIDE)), 1.0, "REPLACE")
        ground = self.plane(scene, "AuthoredFloor", GROUND_Z)
        if intruder:
            foreign = self.plane(scene, "UnselectedCollider", 1.2)
            foreign.modifiers.new("Existing foreign collision", "COLLISION")
        bpy.context.view_layer.update()
        before = source_state([source, ground])
        authored_file, authored_sha = None, None
        if save_source:
            authored_file = self.directory / "authored.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(authored_file), check_existing=False)
            authored_sha = hashlib.sha256(authored_file.read_bytes()).hexdigest()
        result = secondary_motion.create_cloth_proxy(
            {
                "object_name": source.name,
                "pin_group": "PinnedEdge",
                "frame_start": START,
                "frame_end": END,
                "quality": 8,
                "collision_distance": 0.01,
                "collider_names": [ground.name] if floor else [],
                "dry_run": False,
            }
        )
        proxy = scene.objects[result["derivative"]]
        for name in [proxy.name, *result["collider_derivatives"]]:
            obj = scene.objects[name]
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_set(False)
        bpy.context.view_layer.update()
        return {
            "scene": scene,
            "source": source,
            "ground": ground,
            "proxy": proxy,
            "result": result,
            "before": before,
            "authored_file": authored_file,
            "authored_sha": authored_sha,
        }

    def sample(self, fixture):
        scene, proxy = fixture["scene"], fixture["proxy"]
        bpy.context.window.scene = scene
        samples = {}
        for frame in range(START, END + 1):
            scene.frame_set(frame)
            samples[frame] = coordinates(proxy)
        initial = samples[START]
        pin_drift = max(
            math.dist(point, initial[index])
            for frame in samples.values()
            for index, point in enumerate(frame[:SIDE])
        )
        minimum = min(point[2] for frame in samples.values() for point in frame[SIDE:])
        drop = max(
            initial[index][2] - point[2]
            for frame in samples.values()
            for index, point in enumerate(frame)
            if index >= SIDE
        )
        self.assertEqual(source_state([fixture["source"], fixture["ground"]]), fixture["before"])
        return {
            "frames": samples,
            "pin_drift": pin_drift,
            "minimum_z": minimum,
            "maximum_drop": drop,
        }

    def test_gravity_pins_and_floor_collision_are_evaluated_over_every_frame(self):
        fixture = self.fixture()
        report = self.sample(fixture)
        self.assertLess(report["pin_drift"], 0.0001)
        self.assertGreater(report["maximum_drop"], 0.1)
        self.assertGreaterEqual(report["minimum_z"], GROUND_Z - 0.02)
        self.assertLess(report["minimum_z"], GROUND_Z + 0.08)
        self.assertFalse(fixture["result"]["simulation_evaluated"])

    def test_controls_detect_missing_gravity_and_missing_collider(self):
        still = self.sample(self.fixture(gravity=0))
        self.assertLess(still["maximum_drop"], 0.00001)
        falling = self.sample(self.fixture(floor=False))
        self.assertLess(falling["minimum_z"], GROUND_Z - 0.1)

    def test_explicit_colliders_exclude_unselected_scene_collision_objects(self):
        baseline = self.sample(self.fixture())
        contaminated = self.sample(self.fixture(intruder=True))
        self.assertAlmostEqual(contaminated["minimum_z"], baseline["minimum_z"], delta=0.001)
        self.assertLess(
            max(
                abs(a - b)
                for p, q in zip(baseline["frames"][END], contaminated["frames"][END], strict=True)
                for a, b in zip(p, q, strict=True)
            ),
            0.001,
        )

    def test_empty_collider_selection_does_not_enable_foreign_scene_collisions(self):
        baseline = self.sample(self.fixture(floor=False))
        intruder = self.sample(self.fixture(floor=False, intruder=True))
        self.assertAlmostEqual(intruder["minimum_z"], baseline["minimum_z"], delta=0.001)

    def test_owned_collision_collection_has_exact_members_and_failure_cleanup(self):
        fixture = self.fixture()
        cloth = next(
            modifier for modifier in fixture["proxy"].modifiers if modifier.type == "CLOTH"
        )
        collection = cloth.collision_settings.collection
        self.assertIsNotNone(collection)
        self.assertEqual(collection.name, fixture["result"]["collision_collection"])
        self.assertEqual(
            sorted(obj.name for obj in collection.all_objects),
            sorted(fixture["result"]["collider_derivatives"]),
        )
        self.assertNotIn(fixture["ground"].name, collection.objects)
        before = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)}
            for kind in ("objects", "meshes", "collections")
        }
        original = secondary_motion.hidden_derivative
        calls = []

        def fail_collider(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("Injected collider-copy failure")
            return original(*args)

        with patch.object(secondary_motion, "hidden_derivative", side_effect=fail_collider):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                secondary_motion.create_cloth_proxy(
                    {
                        "object_name": fixture["source"].name,
                        "pin_group": "PinnedEdge",
                        "collider_names": [fixture["ground"].name],
                        "dry_run": False,
                    }
                )
        self.assertEqual(
            before,
            {kind: {item.session_uid for item in getattr(bpy.data, kind)} for kind in before},
        )

    def test_selected_embedded_bake_survives_cold_reopen_without_external_cache(self):
        fixture = self.fixture(save_source=True)
        report = self.sample(fixture)
        scene, proxy = fixture["scene"], fixture["proxy"]
        cloth = next(modifier for modifier in proxy.modifiers if modifier.type == "CLOTH")
        cache = cloth.point_cache
        other = secondary_motion.create_cloth_proxy(
            {
                "object_name": fixture["source"].name,
                "pin_group": "PinnedEdge",
                "frame_end": END,
                "dry_run": False,
            }
        )
        other_proxy = scene.objects[other["derivative"]]
        other_cache = next(
            modifier.point_cache for modifier in other_proxy.modifiers if modifier.type == "CLOTH"
        )
        self.assertNotEqual(cache.as_pointer(), other_cache.as_pointer())
        self.assertEqual(cache.id_data, proxy)
        with bpy.context.temp_override(
            scene=scene, object=proxy, active_object=proxy, point_cache=cache
        ):
            self.assertEqual(bpy.ops.ptcache.bake_from_cache(), {"FINISHED"})
        self.assertTrue(cache.is_baked)
        self.assertFalse(other_cache.is_baked)
        self.assertFalse(cache.use_disk_cache or cache.use_external)
        baked = self.directory / "baked-owned.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(baked), check_existing=False)
        receipt = {
            "scene": scene.name,
            "proxy": proxy.name,
            "frames": {str(frame): report["frames"][frame] for frame in (START, 21, 41, END)},
            "sources": [fixture["source"].name, fixture["ground"].name],
            "source_state": fixture["before"],
            "authored_file": str(fixture["authored_file"]),
            "authored_sha256": fixture["authored_sha"],
            "collision_collection": fixture["result"]["collision_collection"],
            "collider_derivatives": fixture["result"]["collider_derivatives"],
        }
        receipt_path = self.directory / "cache-receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(baked),
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold",
            str(receipt_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-6000:] + result.stderr[-6000:])
        self.assertIn('"cold_cache_verified": true', result.stdout)
        self.assertEqual(
            hashlib.sha256(fixture["authored_file"].read_bytes()).hexdigest(),
            fixture["authored_sha"],
        )
        self.assertFalse(list(self.directory.rglob("*.bphys")))
        measurements = {key: value for key, value in report.items() if key != "frames"}
        measurements.update(
            sampled_frames=END - START + 1,
            vertices=len(fixture["source"].data.vertices),
            pinned_vertices=SIDE,
            scene_unit_scale=scene.unit_settings.scale_length,
            effective_fps=scene.render.fps / scene.render.fps_base,
            source_file_sha256_unchanged=True,
            baked_file_sha256=hashlib.sha256(baked.read_bytes()).hexdigest(),
            cold_verification=next(
                json.loads(line)
                for line in result.stdout.splitlines()
                if line.startswith('{"cold_cache_verified"')
            ),
            external_bphys_files=0,
            cache_owner=proxy.name,
            cache_embedded=True,
            visual_acceptance=False,
        )
        (self.directory / "measurements.json").write_text(
            json.dumps(measurements, indent=2), encoding="utf-8"
        )
        print("CLOTH_MEASUREMENTS " + json.dumps(measurements, sort_keys=True))


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
            unittest.defaultTestLoader.loadTestsFromTestCase(ClothSimulationTests)
        )
        if not result.wasSuccessful():
            raise RuntimeError("Actual cloth/cache regression failed")
        print(f"FRAMEWRIGHT_CLOTH_SIMULATION_OK tests={result.testsRun}")
        if args.pilot_dir:
            args.pilot_dir.mkdir(parents=True, exist_ok=False)
            pilot = ClothSimulationTests(
                "test_selected_embedded_bake_survives_cold_reopen_without_external_cache"
            )
            pilot.setUp()
            try:
                pilot.directory = args.pilot_dir.resolve()
                pilot.test_selected_embedded_bake_survives_cold_reopen_without_external_cache()
            finally:
                pilot.tearDown()
