"""Public isolated evaluated-region authoring and transport/inspection round trips."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_region_contacts import RegionContactTests, definition  # noqa: E402

from framewright.api import dispatch  # noqa: E402
from framewright.batch import parse_request_json  # noqa: E402
from framewright.mcp_stdio import MAX_MESSAGE_BYTES, MCPServer, serve  # noqa: E402
from framewright.provenance import canonical_json  # noqa: E402


def describe(params):
    return importlib.import_module("framewright.region_description").describe_region(params)


class RegionDescriptionTests(unittest.TestCase):
    tearDown = RegionContactTests.tearDown
    inventory = staticmethod(RegionContactTests.inventory)
    mesh = RegionContactTests.mesh
    animate = RegionContactTests.animate

    def setUp(self):
        RegionContactTests.setUp(self)
        self.skin.data.clear_geometry()
        self.skin.data.from_pydata(
            [(-0.2, -0.2, 0), (0.2, -0.2, 0), (-0.2, 0.2, 0), (0.2, 0.2, 0), (1, 1, 0.1)],
            [],
            [(0, 1, 2), (1, 3, 2)],
        )
        self.skin.data.update()

    def params(self, **changes):
        return {
            "object_name": self.skin.name,
            "region_id": "authored",
            "sample_time": 1,
            "vertex_indices": [4, 2, 0, 1],
            **changes,
        }

    def group_params(self, **changes):
        result = self.params(**changes)
        result.pop("vertex_indices")
        result["vertex_group"] = "AuthoredMask"
        return result

    def group(self):
        group = self.skin.vertex_groups.new(name="AuthoredMask")
        group.add([0, 1], 0.25, "REPLACE")
        group.add([2], 1, "REPLACE")
        group.add([3, 4], 0, "REPLACE")
        return group

    def state(self):
        return {
            "time": (self.scene.frame_current, self.scene.frame_subframe),
            "fps": (self.scene.render.fps, self.scene.render.fps_base),
            "objects": [
                (o.name, tuple(o.location), tuple(o.rotation_euler), tuple(o.scale), o.select_get())
                for o in self.scene.objects
            ],
            "active": bpy.context.view_layer.objects.active,
            "mesh": [tuple(v.co) for v in self.skin.data.vertices],
            "groups": [(g.name, g.index, g.lock_weight) for g in self.skin.vertex_groups],
            "weights": [[(g.group, g.weight) for g in v.groups] for v in self.skin.data.vertices],
            "active_group": self.skin.vertex_groups.active_index,
            "uvs": [[tuple(v.uv) for v in layer.data] for layer in self.skin.data.uv_layers],
            "materials": list(self.skin.data.materials),
            "inventory": self.inventory(),
        }

    def test_all_three_manifest_is_deterministic_directly_reusable_and_keeps_uncovered(self):
        before = self.state()
        result = describe(self.params())
        self.assertEqual(result["region"], definition(self.skin, [0], "authored"))
        self.assertEqual(result["selected_vertex_indices"], [0, 1, 2, 4])
        self.assertEqual(result["uncovered_vertex_indices"], [4])
        self.assertEqual(
            (
                result["selected_vertex_count"],
                result["covered_vertex_count"],
                result["uncovered_vertex_count"],
            ),
            (4, 3, 1),
        )
        self.assertEqual(result["triangle_fraction"], 0.5)
        self.assertFalse(result["geometric_relations_checked"])
        self.assertEqual(result, describe(self.params(vertex_indices=[0, 1, 4, 2])))
        query = {
            "schema_version": "1.0",
            "request_id": "inspect-region",
            "command": "contacts.inspect_regions",
            "params": {
                "surface_name": self.surface.name,
                "regions": [result["region"]],
                "frame_start": 1,
                "frame_end": 1,
            },
        }
        roundtrip = dispatch(parse_request_json(canonical_json(query)))
        self.assertTrue(roundtrip["ok"], roundtrip)
        self.assertGreater(roundtrip["result"]["counts"]["coplanar_overlap"], 0)
        self.assertEqual(self.state(), before)

    def test_selector_xor_indices_digest_and_no_complete_triangle_refuse(self):
        variants = [
            self.params(vertex_group="AuthoredMask"),
            self.params(vertex_indices=[0, 1, 1]),
            self.params(vertex_indices=[False, 1, 2]),
            self.params(vertex_indices=[0, 1, 3]),
            self.params(vertex_indices=[0, 1, 999999]),
            self.params(sample_time=True),
            self.params(sample_time=float("nan")),
            self.params(expected_topology_sha256="z" * 64),
            self.params(expected_topology_sha256="0" * 64),
            self.params(dry_run=True),
        ]
        missing = self.params()
        missing.pop("vertex_indices")
        variants.append(missing)
        for params in variants:
            before = self.state()
            with self.assertRaises(ValueError):
                describe(params)
            self.assertEqual(self.state(), before)

    def test_group_strict_positive_evaluated_membership_preserves_weights_and_layers(self):
        self.group()
        self.skin.vertex_groups.new(name="Unrelated").add([0, 1, 2, 3, 4], 0.7, "REPLACE")
        self.skin.vertex_groups.active_index = 1
        self.skin.data.uv_layers.new(name="ProtectedUV")
        material = bpy.data.materials.new("ProtectedMaterial")
        self.skin.data.materials.append(material)
        before = self.state()
        result = describe(self.group_params())
        explicit = describe(self.params(vertex_indices=[0, 1, 2]))
        self.assertEqual(result["region"], explicit["region"])
        self.assertEqual(result["selected_vertex_indices"], [0, 1, 2])
        self.assertEqual(result["group_entries_examined"], 10)
        self.assertEqual(
            result["selector"]["membership_policy"], "evaluated_weight_strictly_positive"
        )
        self.assertEqual(self.state(), before)
        for request in (
            {**self.group_params(), "vertex_group": "authoredmask"},
            self.group_params(max_group_entries=9),
        ):
            with self.assertRaises(ValueError):
                describe(request)
        self.assertEqual(self.state(), before)

    def evaluated_group_indices(self, group):
        evaluated = self.skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh(
            preserve_all_data_layers=True, depsgraph=bpy.context.evaluated_depsgraph_get()
        )
        try:
            return [
                v.index
                for v in mesh.vertices
                if any(entry.group == group.index and entry.weight > 0 for entry in v.groups)
            ]
        finally:
            evaluated.to_mesh_clear()

    def test_subsurf_and_multires_groups_use_generated_evaluated_vertices(self):
        group = self.group()
        for kind in ("SUBSURF", "MULTIRES"):
            with self.subTest(modifier=kind):
                modifier = self.skin.modifiers.new("NativeSubdivision", kind)
                if kind == "SUBSURF":
                    modifier.levels = 1
                else:
                    bpy.context.view_layer.objects.active = self.skin
                    self.skin.select_set(True)
                    bpy.ops.object.multires_subdivide(modifier=modifier.name, mode="CATMULL_CLARK")
                expected = self.evaluated_group_indices(group)
                self.assertGreater(len(expected), 3)
                self.assertGreater(max(expected), len(self.skin.data.vertices) - 1)
                before = self.state()
                result = describe(self.group_params())
                self.assertEqual(result["selected_vertex_indices"], expected)
                self.assertEqual(
                    result["region"], describe(self.params(vertex_indices=expected))["region"]
                )
                self.assertEqual(self.state(), before)
                self.skin.modifiers.remove(modifier)

    def rig(self):
        data = bpy.data.armatures.new("DescriptionRigData")
        rig = bpy.data.objects.new("DescriptionRig", data)
        self.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("Deform")
        bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
        bpy.ops.object.mode_set(mode="OBJECT")
        return rig

    def test_armature_group_and_fractional_time_preserve_dirty_source(self):
        self.group()
        rig = self.rig()
        self.skin.vertex_groups.new(name="Deform").add([0, 1, 2, 3, 4], 1, "REPLACE")
        self.skin.modifiers.new("Armature", "ARMATURE").object = rig
        self.animate(rig.pose.bones["Deform"], "location", [(-2, (0, 0, 0)), (3, (0, 0.2, 0))])
        self.scene.render.fps_base = 1.001
        self.scene.frame_set(-1, subframe=0.125)
        rig.pose.bones["Deform"].location.y = 0.7654
        before = self.state(), tuple(rig.pose.bones["Deform"].location)
        result = describe(self.group_params(sample_time=2.123456789))
        self.assertEqual(result["sample"]["requested_time"], 2.123456789)
        self.assertEqual(result["sample"]["frame"], 2)
        self.assertAlmostEqual(result["sample"]["effective_time"], 2.123456789, places=6)
        self.assertEqual(result["time_basis"]["fps_base"], self.scene.render.fps_base)
        self.assertEqual(result["selected_vertex_indices"], [0, 1, 2])
        self.assertEqual((self.state(), tuple(rig.pose.bones["Deform"].location)), before)

    def test_animated_triangulation_uses_requested_time_and_digest_pin(self):
        quad = self.mesh("MorphQuad", [(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)], [(0, 1, 2, 3)])
        quad.shape_key_add(name="Basis")
        key = quad.shape_key_add(name="Concavity")
        key.data[1].co = (0.1, 0.8, 0)
        self.animate(key, "value", [(1, 0), (3, 1)])
        first = describe(
            self.params(object_name=quad.name, vertex_indices=[0, 1, 2, 3], sample_time=1)
        )
        last = describe(
            self.params(object_name=quad.name, vertex_indices=[0, 1, 2, 3], sample_time=3)
        )
        self.assertNotEqual(first["region"]["topology_sha256"], last["region"]["topology_sha256"])
        with self.assertRaisesRegex(ValueError, "topology"):
            describe(
                self.params(
                    object_name=quad.name,
                    vertex_indices=[0, 1, 2, 3],
                    sample_time=3,
                    expected_topology_sha256=first["region"]["topology_sha256"],
                )
            )

    def test_dependency_triangle_vertex_and_group_budgets_count_complete_work(self):
        dependency = self.mesh(
            "UnselectedDependency", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
        )
        dependency.modifiers.new("Subdivision", "SUBSURF").levels = 2
        self.skin.constraints.new("COPY_LOCATION").target = dependency
        before = self.state()
        for limit in ({"max_evaluated_vertices": 10}, {"max_evaluated_triangles": 3}):
            with self.assertRaisesRegex(ValueError, "budget"):
                describe(self.params(**limit))
            self.assertEqual(self.state(), before)
        report = describe(self.params())
        self.assertEqual(len(report["dependency_geometry"]), 2)
        self.assertEqual(
            report["geometry_work_elements"],
            sum(item["work_elements"] for item in report["dependency_geometry"]),
        )

    def test_degenerate_finite_topology_is_described_without_hidden_epsilon(self):
        self.skin.data.vertices[2].co = self.skin.data.vertices[1].co
        result = describe(self.params())
        self.assertFalse(result["geometric_relations_checked"])
        self.assertEqual(result["selected_triangle_count"], 1)
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "degenerate",
                "command": "contacts.inspect_regions",
                "params": {
                    "surface_name": self.surface.name,
                    "regions": [result["region"]],
                    "frame_start": 1,
                    "frame_end": 1,
                },
            }
        )
        self.assertFalse(response["ok"])

    def test_handler_external_action_and_unsafe_subdivision_refuse_before_copy(self):
        from framewright import skin_contacts

        request = self.params()
        before = self.state()
        calls = []

        def callback(*args):
            calls.append(1)

        bpy.app.handlers.frame_change_post.append(callback)
        try:
            with patch.object(
                skin_contacts, "_isolated_scene", wraps=skin_contacts._isolated_scene
            ) as stage:
                with self.assertRaisesRegex(ValueError, "handlers"):
                    describe(request)
                stage.assert_not_called()
            self.assertEqual(calls, [])
            self.assertEqual(self.state(), before)
        finally:
            bpy.app.handlers.frame_change_post.remove(callback)
        modifier = self.skin.modifiers.new("Unsafe", "SUBSURF")
        self.animate(modifier, "levels", [(1, 4), (10, 0)])
        self.scene.frame_set(10)
        with patch.object(
            skin_contacts, "_isolated_scene", wraps=skin_contacts._isolated_scene
        ) as stage:
            with self.assertRaisesRegex(ValueError, "subdivision"):
                describe(request)
            stage.assert_not_called()

    def test_failure_after_extraction_cleans_all_ids_and_source_channels(self):
        self.group()
        self.skin.location.x = 0.1234
        before = self.state()
        module = importlib.import_module("framewright.region_description")
        with patch.object(
            module.region_selection,
            "select_region",
            side_effect=RuntimeError("injected after extraction"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                describe(self.group_params())
        self.assertEqual(self.state(), before)
        with patch.object(
            module.region_selection,
            "enforce_response_budget",
            side_effect=ValueError("oversize complete result"),
        ):
            with self.assertRaisesRegex(ValueError, "oversize"):
                describe(self.group_params())
        self.assertEqual(self.state(), before)

    def test_public_workflow_and_actual_mcp_double_encoding(self):
        workflow = {
            "run_id": "describe-region-fixture",
            "dry_run": False,
            "steps": [
                {
                    "id": "describe",
                    "command": "contacts.describe_region",
                    "params": self.params(),
                    "require": [{"path": "result.geometric_relations_checked", "equals": False}],
                },
                {
                    "id": "inspect",
                    "command": "contacts.inspect_regions",
                    "params": {
                        "surface_name": self.surface.name,
                        "regions": [{"$ref": "describe.result.region"}],
                        "frame_start": 1,
                        "frame_end": 1,
                    },
                },
            ],
        }
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "workflow",
                "command": "workflow.run",
                "params": workflow,
            }
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["status"], "completed")
        actual = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "description",
                "command": "contacts.describe_region",
                "params": self.params(),
            }
        )
        self.assertTrue(actual["ok"], actual)
        with tempfile.TemporaryDirectory() as folder:

            class Worker:
                directory = folder

                def poll(self, job_id):
                    return {
                        "job_id": job_id,
                        "directory": folder,
                        "state": "completed",
                        "response": actual,
                        "exit_code": 0,
                    }

                def close(self):
                    pass

            server = MCPServer(worker=Worker(), asset_root=folder)
            message = {
                "jsonrpc": "2.0",
                "id": "region-description",
                "method": "tools/call",
                "params": {
                    "name": "framewright_poll_job",
                    "arguments": {"job_id": "fixture"},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            }
            source = io.BytesIO((canonical_json(message) + "\n").encode())
            output = io.BytesIO()
            serve(server, source, output)
            encoded = output.getvalue()
            self.assertLessEqual(len(encoded), MAX_MESSAGE_BYTES)
            returned = json.loads(encoded)
            self.assertEqual(returned["result"]["structuredContent"]["response"], actual)

    def test_large_complete_manifest_refuses_transport_size_without_truncation(self):
        side = 80
        grid = self.mesh(
            "LargeExplicitRegion",
            [(x * 0.01, y * 0.01, 0) for y in range(side) for x in range(side)],
            [
                (y * side + x, y * side + x + 1, (y + 1) * side + x + 1, (y + 1) * side + x)
                for y in range(side - 1)
                for x in range(side - 1)
            ],
        )
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "size|MiB|budget|response|transport"):
            describe(
                self.params(
                    object_name=grid.name,
                    vertex_indices=list(range(side * side)),
                    max_region_triangles=16384,
                )
            )
        self.assertEqual(self.inventory(), before)

    def test_empty_group_and_mesh_refuse_without_source_index_fallback(self):
        self.skin.vertex_groups.new(name="AuthoredMask")
        before = self.state()
        with self.assertRaisesRegex(ValueError, "empty|membership|layer"):
            describe(self.group_params())
        self.assertEqual(self.state(), before)
        empty = self.mesh("EmptySelectedMesh", [], [])
        with self.assertRaisesRegex(ValueError, "empty|geometry"):
            describe(self.params(object_name=empty.name, vertex_indices=[0, 1, 2]))

    def test_corrupt_native_nan_weight_and_missing_deform_index_are_refused(self):
        import bmesh

        self.group()
        self.skin.data.vertices[0].groups[0].weight = float("nan")
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "weight|finite"):
            describe(self.group_params())
        self.assertTrue(math.isnan(self.skin.data.vertices[0].groups[0].weight))
        self.assertEqual(self.inventory(), before)
        self.skin.data.vertices[0].groups[0].weight = 0.25
        edit = bmesh.new()
        try:
            edit.from_mesh(self.skin.data)
            layer = edit.verts.layers.deform.verify()
            edit.verts.ensure_lookup_table()
            edit.verts[0][layer][999] = 0.5
            edit.to_mesh(self.skin.data)
        finally:
            edit.free()
        self.skin.data.update()
        self.assertTrue(any(entry.group == 999 for entry in self.skin.data.vertices[0].groups))
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "group.*index|metadata"):
            describe(self.group_params())
        self.assertEqual(self.inventory(), before)
        self.assertTrue(any(entry.group == 999 for entry in self.skin.data.vertices[0].groups))

    def test_cold_public_description_repeats_exactly_without_modifying_file(self):
        self.group()
        request = {
            "schema_version": "1.0",
            "request_id": "cold-description",
            "command": "contacts.describe_region",
            "params": self.group_params(),
        }
        expected = dispatch(request)
        self.assertTrue(expected["ok"], expected)
        with tempfile.TemporaryDirectory(prefix="framewright-region-description-") as folder:
            folder = Path(folder)
            blend = folder / "source.blend"
            runner = folder / "cold.py"
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
            digest = hashlib.sha256(blend.read_bytes()).hexdigest()
            runner.write_text(
                "import sys,bpy\n"
                + f"sys.path.insert(0,{str(ROOT)!r})\n"
                + "from framewright.api import dispatch\n"
                + f"actual=dispatch({request!r})\nassert actual=={expected!r},actual\n"
            )
            child = subprocess.run(
                [
                    bpy.app.binary_path,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    str(blend),
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
            self.assertEqual(hashlib.sha256(blend.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RegionDescriptionTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Region description tests failed")
    print(
        f"FRAMEWRIGHT_REGION_DESCRIPTION_OK tests={result.testsRun} version={bpy.app.version_string}"
    )
