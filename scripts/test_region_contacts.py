"""Actual regional triangle contacts, sparse-marker control and isolated ownership."""

from __future__ import annotations

import copy
import hashlib
import importlib
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_skin_contacts import SkinContactTests  # noqa: E402

from framewright import skin_contacts  # noqa: E402


def definition(obj, indices=None, identity="sole"):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        triangles = array("i", [0]) * (len(mesh.loop_triangles) * 3)
        edges = array("i", [0]) * (len(mesh.edges) * 2)
        loops = array("i", [0]) * len(mesh.loops)
        mesh.loop_triangles.foreach_get("vertices", triangles)
        mesh.edges.foreach_get("vertices", edges)
        mesh.loops.foreach_get("vertex_index", loops)
        digest = hashlib.sha256(
            str((len(mesh.vertices), len(mesh.polygons))).encode()
            + triangles.tobytes()
            + edges.tobytes()
            + loops.tobytes()
        ).hexdigest()
        selected = range(len(mesh.loop_triangles)) if indices is None else indices
        return {
            "id": identity,
            "object_name": obj.name,
            "topology_sha256": digest,
            "triangles": [
                {"index": index, "vertices": list(triangles[index * 3 : index * 3 + 3])}
                for index in selected
            ],
        }
    finally:
        evaluated.to_mesh_clear()


def inspect(params):
    return importlib.import_module("framewright.region_contacts").inspect_regions(params)


class RegionContactTests(unittest.TestCase):
    setUp = SkinContactTests.setUp
    tearDown = SkinContactTests.tearDown
    inventory = staticmethod(SkinContactTests.inventory)
    mesh = SkinContactTests.mesh
    animate = SkinContactTests.animate

    def params(self, **changes):
        return {
            "surface_name": self.surface.name,
            "regions": [definition(self.skin)],
            "frame_start": 1,
            "frame_end": 3,
            **changes,
        }

    def ridge(self):
        self.surface.data.clear_geometry()
        self.surface.data.from_pydata(
            [
                (-4, -4, -0.1),
                (4, -4, -0.1),
                (4, 4, -0.1),
                (-4, 4, -0.1),
                (-0.05, 0, -0.1),
                (0.05, 0, -0.1),
                (0, 0, 0.1),
            ],
            [],
            [(0, 1, 2), (0, 2, 3), (4, 5, 6)],
        )
        self.surface.data.update()

    def test_sparse_markers_miss_ridge_but_region_crossing_detects_and_control_clears(self):
        self.ridge()
        old = skin_contacts.inspect_skin_contacts(
            {
                "surface_name": self.surface.name,
                "markers": [
                    {
                        "id": f"corner_{i}",
                        "object_name": self.skin.name,
                        "vertex_indices": [i],
                        "weights": [1],
                    }
                    for i in range(3)
                ],
                "frame_start": 1,
                "frame_end": 3,
            }
        )
        self.assertEqual(old["penetration_samples"], 0)
        self.assertTrue(
            all(
                point["normal_distance_meters"] > 0.09
                for sample in old["samples"]
                for point in sample["markers"]
            )
        )
        before = self.inventory()
        result = inspect(self.params())
        self.assertEqual(result["counts"]["crossing"], 3)
        self.assertEqual(result["coverage"], "complete_at_samples")
        self.assertFalse(result["containment_checked"])
        self.assertEqual(result["regions"][0]["selected_triangles"], 1)
        self.assertEqual(self.inventory(), before)
        self.surface.location.x = 1
        self.assertEqual(inspect(self.params())["counts"]["crossing"], 0)

    def test_parallel_coplanar_touch_and_proximity_have_distinct_meanings(self):
        for z, relation, distance in [
            (0, "coplanar_overlap", 0),
            (0.002, "proximity", 0.002),
            (0.02, "separated", None),
        ]:
            self.skin.location.z = z
            result = inspect(self.params(frame_end=1))
            self.assertGreater(result["counts"][relation], 0)
            observed = result["samples"][0]["regions"][0]["minimum_distance_within_radius_m"]
            if distance is None:
                self.assertIsNone(observed)
            else:
                self.assertAlmostEqual(observed, distance, places=6)
        for vertex in self.skin.data.vertices:
            vertex.co.z = 0 if vertex.index == 0 else 0.1
        self.skin.location.z = 0
        self.assertGreater(inspect(self.params(frame_end=1))["counts"]["touch"], 0)

    def test_meter_millimeter_nonuniform_transform_and_moving_platform_match(self):
        self.skin.location.z = 0.002
        baseline = inspect(self.params(substeps=4))
        self.scene.unit_settings.scale_length = 0.001
        for obj in (self.skin, self.surface):
            for vertex in obj.data.vertices:
                vertex.co *= 1000
            obj.scale = (2, 3, 1)
        self.skin.location.z = 2
        parent = bpy.data.objects.new("MovingPlatform", None)
        self.scene.collection.objects.link(parent)
        self.surface.parent = self.skin.parent = parent
        self.animate(parent, "rotation_euler", [(1, (0.1, 0.2, 0)), (3, (0.4, -0.2, 0.7))])
        self.animate(parent, "location", [(1, (1000, -2000, 300)), (3, (1200, -1900, 500))])
        self.scene.frame_set(2, subframe=0.25)
        before = (self.inventory(), tuple(parent.location), tuple(parent.rotation_euler))
        result = inspect(self.params(substeps=4))
        self.assertEqual(result["sample_times"], [1 + i / 4 for i in range(9)])
        self.assertEqual(result["counts"], baseline["counts"])
        for sample in result["samples"]:
            self.assertAlmostEqual(
                sample["regions"][0]["minimum_distance_within_radius_m"], 0.002, places=6
            )
        self.assertEqual(
            (self.inventory(), tuple(parent.location), tuple(parent.rotation_euler)), before
        )
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))

    def test_all_dependency_geometry_counts_surface_edges_and_loops(self):
        self.surface.data.calc_loop_triangles()
        self.skin.data.calc_loop_triangles()
        expected = (
            sum(
                len(obj.data.vertices)
                + 3 * len(obj.data.loop_triangles)
                + 2 * len(obj.data.edges)
                + len(obj.data.loops)
                for obj in (self.skin, self.surface)
            )
            * 3
        )
        result = inspect(self.params())
        self.assertEqual(result["sampled_geometry_work_elements"], expected)
        target = self.mesh("ExtraDependency", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        constraint = self.skin.constraints.new("COPY_LOCATION")
        constraint.target = target
        target.modifiers.new("Subdiv", "SUBSURF").levels = 2
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "budget"):
            inspect(self.params(max_evaluated_vertices=10))
        self.assertEqual(self.inventory(), before)

    def test_explicit_topology_and_triangle_identity_refusals(self):
        valid = self.params()
        variants = []
        for key, value in [
            ("topology_sha256", "0" * 64),
            ("topology_sha256", "z" * 64),
            ("triangles", [{"index": 0, "vertices": [2, 1, 0]}]),
            ("triangles", [{"index": 999, "vertices": [0, 1, 2]}]),
        ]:
            request = copy.deepcopy(valid)
            request["regions"][0][key] = value
            variants.append(request)
        duplicate = copy.deepcopy(valid)
        duplicate["regions"][0]["triangles"] *= 2
        variants.append(duplicate)
        overlap = copy.deepcopy(valid)
        overlap["regions"].append({**overlap["regions"][0], "id": "other"})
        variants.append(overlap)
        for request in variants:
            before = self.inventory()
            with self.assertRaises(ValueError):
                inspect(request)
            self.assertEqual(self.inventory(), before)

    def test_changing_topology_refuses_no_partial_clear(self):
        request = self.params()
        modifier = self.skin.modifiers.new("Changing", "SUBSURF")
        self.animate(modifier, "levels", [(1, 0), (2, 1), (3, 0)])
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "topology"):
            inspect(request)
        self.assertEqual(self.inventory(), before)

    def test_same_count_triangulation_change_refuses_stale_identity(self):
        quad = self.mesh(
            "ChangingQuad", [(0, 0, 0.1), (2, 0, 0.1), (2, 1, 0.1), (0, 1, 0.1)], [(0, 1, 2, 3)]
        )
        quad.shape_key_add(name="Basis")
        key = quad.shape_key_add(name="Concavity")
        key.data[1].co = (0.1, 0.8, 0.1)
        self.animate(key, "value", [(1, 0), (3, 1)])
        self.scene.frame_set(1)
        first = definition(quad)
        self.scene.frame_set(3)
        last = definition(quad)
        self.assertEqual(len(first["triangles"]), len(last["triangles"]))
        self.assertNotEqual(first["topology_sha256"], last["topology_sha256"])
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "topology"):
            inspect(self.params(regions=[first]))
        self.assertEqual(self.inventory(), before)

    def test_unselected_dependency_topology_and_external_action_are_not_omitted(self):
        target = self.mesh("Dependency", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        self.skin.constraints.new("COPY_LOCATION").target = target
        modifier = target.modifiers.new("ChangingDependency", "SUBSURF")
        self.animate(modifier, "levels", [(1, 0), (2, 1), (3, 0)])
        with self.assertRaisesRegex(ValueError, "topology"):
            inspect(self.params())
        target.modifiers.remove(modifier)
        external = bpy.data.objects.new("ExternalActionOwner", None)
        self.scene.collection.objects.link(external)
        self.skin["outside"] = external
        self.skin.location = (0, 0, 0)
        self.skin.keyframe_insert("location", frame=1)
        self.skin.keyframe_insert("location", frame=3)
        animation = self.skin.animation_data
        bag = animation.action.layers[0].strips[0].channelbag(animation.action_slot)
        curve = bag.fcurves[0]
        curve.data_path = '["outside"].location'
        self.scene.frame_set(2)
        external.location.x = 0.91
        original = tuple(external.location)
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "local"):
            inspect(self.params())
        self.assertEqual(tuple(external.location), original)
        self.assertEqual(self.inventory(), before)

    def test_pair_geometry_and_sample_budgets_fail_whole_request(self):
        for changes in (
            {"max_pair_checks": 1},
            {"max_candidate_visits": 1},
            {"max_evaluated_vertices": 1},
            {"max_surface_triangles": 1},
            {"max_samples": 2},
        ):
            before = self.inventory()
            with self.assertRaisesRegex(ValueError, "budget|max_samples"):
                inspect(self.params(**changes))
            self.assertEqual(self.inventory(), before)
        request = self.params(max_examples=1)
        result = inspect(request)
        self.assertEqual(
            sum(
                len(region["examples"])
                for sample in result["samples"]
                for region in sample["regions"]
            ),
            1,
        )
        self.assertEqual(result["pair_work"]["narrow_checks"], 6)

    def test_dirty_source_and_unrelated_channels_survive_success_and_midclip_failure(self):
        self.animate(self.skin, "location", [(1, (0, 0, 0)), (3, (0, 0, 0.02))])
        light = bpy.data.lights.new("DirtyLight", "AREA")
        obj = bpy.data.objects.new("DirtyLight", light)
        self.scene.collection.objects.link(obj)
        self.animate(light, "energy", [(1, 10), (3, 30)])
        self.scene.frame_set(2, subframe=0.25)
        self.skin.location.z = 0.123456
        light.energy = 456.789
        request = self.params()
        before = (
            self.inventory(),
            tuple(self.skin.location),
            light.energy,
            self.scene.frame_current,
            self.scene.frame_subframe,
        )
        inspect(request)
        module = importlib.import_module("framewright.region_contacts")
        original = module._sample_geometry
        calls = []

        def injected(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("injected midclip")
            return original(*args, **kwargs)

        with patch.object(module, "_sample_geometry", injected):
            with self.assertRaisesRegex(RuntimeError, "midclip"):
                inspect(request)
        self.assertEqual(
            (
                self.inventory(),
                tuple(self.skin.location),
                light.energy,
                self.scene.frame_current,
                self.scene.frame_subframe,
            ),
            before,
        )

    def test_external_action_driver_and_invalid_sample_driver_refuse(self):
        external = bpy.data.objects.new("External", None)
        self.scene.collection.objects.link(external)
        self.skin["outside"] = external
        self.skin["gain"] = 1.0
        curve = self.skin.driver_add("location", 2)
        variable = curve.driver.variables.new()
        variable.name, variable.type = "gain", "SINGLE_PROP"
        variable.targets[0].id = self.skin
        variable.targets[0].data_path = '["outside"].location[0]'
        curve.driver.expression = "gain"
        external.location.x = 0.91
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "local"):
            inspect(self.params())
        self.assertEqual(external.location.x, float(external.location.x))
        self.assertAlmostEqual(external.location.x, 0.91)
        self.assertEqual(self.inventory(), before)
        variable.targets[0].data_path = '["gain"]'
        curve.driver.expression = "0.01/gain"
        for frame, value in [(1, 1), (2, 0), (3, 1)]:
            self.skin["gain"] = value
            self.skin.keyframe_insert('["gain"]', frame=frame)
        self.skin.update_tag()
        self.scene.frame_set(3)
        self.assertTrue(curve.driver.is_valid)
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "driver"):
            inspect(self.params())
        self.assertEqual(self.inventory(), before)

    def test_foreign_handlers_refused_without_invocation(self):
        invoked = []

        def handler(*args):
            invoked.append(1)

        request = self.params()
        before = self.inventory()
        bpy.app.handlers.frame_change_post.append(handler)
        try:
            with self.assertRaisesRegex(ValueError, "handlers"):
                inspect(request)
            self.assertEqual(invoked, [])
            self.assertEqual(self.inventory(), before)
        finally:
            bpy.app.handlers.frame_change_post.remove(handler)

    def test_degenerate_and_singular_inputs_never_report_clear(self):
        request = self.params()
        self.skin.scale.z = 0
        with self.assertRaisesRegex(ValueError, "transform|singular"):
            inspect(request)
        self.skin.scale.z = 1
        self.skin.data.vertices[2].co = self.skin.data.vertices[1].co
        with self.assertRaisesRegex(ValueError, "degenerate|altitude"):
            inspect(request)

    def test_contained_closed_surfaces_explicitly_do_not_claim_volume_clearance(self):
        points = [
            (-1, -1, -1),
            (1, -1, -1),
            (1, 1, -1),
            (-1, 1, -1),
            (-1, -1, 1),
            (1, -1, 1),
            (1, 1, 1),
            (-1, 1, 1),
        ]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        outer = self.mesh("ClosedOuter", points, faces)
        inner = self.mesh(
            "ClosedInner", [tuple(value * 0.1 for value in point) for point in points], faces
        )
        result = inspect(
            self.params(surface_name=outer.name, regions=[definition(inner)], frame_end=1)
        )
        self.assertEqual(result["counts"]["crossing"], 0)
        self.assertFalse(result["containment_checked"])
        self.assertIsNone(result["samples"][0]["regions"][0]["minimum_distance_within_radius_m"])

    def test_direct_parameter_validation_matches_declared_bounds(self):
        for changes in (
            {"dry_run": True},
            {"step": 2},
            {"max_pair_checks": True},
            {"max_examples": 1001},
            {"proximity_distance_m": 1e-8, "distance_epsilon_m": 1e-6},
            {"distance_epsilon_m": float("nan")},
            {"surface_name": self.skin.name},
        ):
            before = self.inventory()
            with self.assertRaises(ValueError):
                inspect(self.params(**changes))
            self.assertEqual(self.inventory(), before)
        result = inspect(self.params(max_examples=1000, frame_start=-2, frame_end=1, substeps=4))
        self.assertEqual(result["sample_times"], [-2 + i / 4 for i in range(13)])

    def test_fractional_source_fps_reports_physical_duration_without_retiming(self):
        self.scene.render.fps = 24
        self.scene.render.fps_base = 1.001
        self.scene.frame_set(2, subframe=0.125)
        before = (
            self.scene.render.fps,
            self.scene.render.fps_base,
            self.scene.frame_current,
            self.scene.frame_subframe,
            self.inventory(),
        )
        result = inspect(self.params(frame_start=-2, frame_end=3, substeps=2))
        basis = result["time_basis"]
        self.assertEqual(basis["fps"], before[0])
        self.assertEqual(basis["fps_base"], before[1])
        self.assertEqual(basis["effective_fps"], before[0] / before[1])
        self.assertEqual(basis["interval_duration_seconds"], 5 / basis["effective_fps"])
        self.assertEqual(len(result["sample_times"]), 11)
        self.assertEqual(
            (
                self.scene.render.fps,
                self.scene.render.fps_base,
                self.scene.frame_current,
                self.scene.frame_subframe,
                self.inventory(),
            ),
            before,
        )

    def test_public_dispatch_and_disabled_autoexec_cold_reproduction(self):
        from framewright.api import dispatch

        request = self.params(substeps=2)
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "regions",
                "command": "contacts.inspect_regions",
                "params": request,
            }
        )
        self.assertTrue(response["ok"], response)
        expected = response["result"]
        with tempfile.TemporaryDirectory(prefix="framewright-region-test-") as folder:
            folder = Path(folder)
            source, runner = folder / "source.blend", folder / "cold.py"
            bpy.ops.wm.save_as_mainfile(filepath=str(source), copy=True)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            runner.write_text(
                "import sys,json,bpy\n"
                f"sys.path.insert(0,{str(ROOT)!r})\n"
                "from framewright.region_contacts import inspect_regions\n"
                f"result=inspect_regions({request!r})\n"
                f"assert result=={expected!r}, 'cold report mismatch'\n",
                encoding="utf-8",
            )
            child = subprocess.run(
                [
                    bpy.app.binary_path,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    str(source),
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(runner),
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RegionContactTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Regional contact tests failed")
    print(
        f"FRAMEWRIGHT_REGION_CONTACTS_OK tests={result.testsRun} version={bpy.app.version_string}"
    )
