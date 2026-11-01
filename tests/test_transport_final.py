"""Final transport regression boundaries; fake workers never execute input files."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from framewright.mcp_stdio import MAX_MESSAGE_BYTES, MCPServer, serve
from framewright.provenance import create_manifest, create_reference


def rpc(method, params=None, identity=1):
    return {
        "jsonrpc": "2.0",
        "id": identity,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


class Worker:
    def __init__(self, root):
        self.directory = root
        self.submitted = []
        self.closed = False
        self.poll_result = {"job_id": "owned", "state": "completed"}

    def submit(self, blend, request, timeout=300):
        self.submitted.append((blend, request, timeout))
        return {"job_id": "owned", "state": "running"}

    def poll(self, job_id):
        return self.poll_result

    def close(self):
        self.closed = True


class FinalTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.jobs = self.root / "jobs"
        self.assets.mkdir()
        self.jobs.mkdir()
        self.blend = self.assets / "source.blend"
        self.map = self.assets / "map.png"
        self.outside = self.root / "outside.png"
        for path in (self.blend, self.map, self.outside):
            path.write_bytes(b"path-policy fixture only")
        self.worker = Worker(self.jobs)
        self.server = MCPServer(worker=self.worker, asset_root=self.assets)

    def submit(self, command, params, **tool_arguments):
        request = {
            "schema_version": "1.0",
            "request_id": "final-review",
            "command": command,
            "params": params,
        }
        return self.server.handle(
            rpc(
                "tools/call",
                {
                    "name": "framewright_submit_job",
                    "arguments": {"blend": str(self.blend), "request": request, **tool_arguments},
                },
            )
        )["result"]

    def manifest(self, location):
        return create_manifest(
            {
                "name": "Review reference",
                "references": [create_reference({"label": "Original", "location": location})],
            }
        )

    def workflow(self, command, params):
        return {
            "run_id": "final-path-review",
            "dry_run": False,
            "steps": [
                {
                    "id": "source",
                    "command": "asset.manifest_create",
                    "params": {
                        "name": "Options",
                        "recipe": {
                            "tool": "fixture",
                            "version": "1",
                            "operation": "arguments",
                            "parameters": {
                                "base_color_path": str(self.outside),
                                "path": str(self.outside),
                            },
                        },
                    },
                },
                {"id": "operation", "command": command, "params": params},
            ],
        }

    def test_material_all_literal_paths_inside_asset_root_reach_worker(self):
        result = self.submit(
            "surfaces.create_pbr_material",
            {
                field: str(self.map)
                for field in ("base_color_path", "roughness_path", "metallic_path", "normal_path")
            },
        )
        self.assertFalse(result["isError"], result)
        self.assertEqual(len(self.worker.submitted), 1)

    def test_each_material_channel_rejects_escape_before_worker(self):
        for field in ("base_color_path", "roughness_path", "metallic_path", "normal_path"):
            for path in (
                str(self.outside),
                str(self.assets / ".." / "outside.png"),
                "../outside.png",
            ):
                with self.subTest(field=field, path=path):
                    result = self.submit(
                        "surfaces.create_pbr_material",
                        {"base_color_path": str(self.map), field: path},
                    )
                    self.assertTrue(result["isError"], result)
        self.assertEqual(self.worker.submitted, [])

    def test_material_bound_fields_and_whole_params_cannot_bypass_path_guard(self):
        for field in ("base_color_path", "roughness_path", "metallic_path", "normal_path"):
            params = {
                "base_color_path": str(self.map),
                field: {"$ref": "source.result.recipe.parameters.path"},
            }
            with self.subTest(field=field):
                self.assertTrue(
                    self.submit(
                        "workflow.run", self.workflow("surfaces.create_pbr_material", params)
                    )["isError"]
                )
        bound_params = {"$ref": "source.result.recipe.parameters"}
        self.assertTrue(
            self.submit(
                "workflow.run", self.workflow("surfaces.create_pbr_material", bound_params)
            )["isError"]
        )
        self.assertEqual(self.worker.submitted, [])

    def test_missing_required_material_and_board_arguments_reject_before_worker(self):
        cases = [
            ("surfaces.create_pbr_material", {}),
            ("asset.reference_board", {"manifest": self.manifest(str(self.map))}),
            ("asset.reference_board", {"output": str(self.jobs / "review.html")}),
        ]
        for command, params in cases:
            with self.subTest(command=command, params=params):
                self.assertTrue(self.submit(command, params)["isError"])
        self.assertEqual(self.worker.submitted, [])

    def test_whole_filesystem_parameter_bindings_explicitly_refuse_before_submission(self):
        for command in (
            "asset.reference_intake",
            "surfaces.create_pbr_material",
            "asset.reference_board",
            "asset.export",
        ):
            with self.subTest(command=command):
                result = self.submit(
                    "workflow.run",
                    self.workflow(command, {"$ref": "source.result.recipe.parameters"}),
                )
                self.assertTrue(result["isError"], result)
                error = result["structuredContent"]["error"]
                self.assertEqual(error["code"], "OPERATION_REJECTED")
                self.assertIn("explicit", error["message"])
        self.assertEqual(self.worker.submitted, [])

    def test_read_only_region_object_binding_reaches_worker_without_path_policy_bypass(self):
        inspect = {
            "surface_name": "Ground",
            "regions": [{"$ref": "source.result.region"}],
            "frame_start": 1,
            "frame_end": 3,
        }
        workflow = self.workflow("contacts.inspect_regions", inspect)
        workflow["steps"][0] = {
            "id": "source",
            "command": "contacts.describe_region",
            "params": {
                "object_name": "Skin",
                "region_id": "authored",
                "sample_time": 1,
                "vertex_indices": [0, 1, 2],
            },
        }
        result = self.submit("workflow.run", workflow)
        self.assertFalse(result["isError"], result)
        self.assertEqual(len(self.worker.submitted), 1)

    def test_reference_board_scopes_output_and_all_local_references(self):
        cases = [
            {"manifest": self.manifest(str(self.map)), "output": str(self.root / "outside.html")},
            {"manifest": self.manifest(str(self.map)), "output": "review.html"},
            {
                "manifest": self.manifest(str(self.outside)),
                "output": str(self.jobs / "review.html"),
            },
            {
                "manifest": self.manifest("javascript:alert(1)"),
                "output": str(self.jobs / "review.html"),
            },
        ]
        for params in cases:
            with self.subTest(params=params):
                self.assertTrue(self.submit("asset.reference_board", params)["isError"])
        self.assertEqual(self.worker.submitted, [])

    def test_reference_board_bound_manifest_location_or_output_reject(self):
        literal = {
            "manifest": self.manifest(str(self.map)),
            "output": str(self.jobs / "review.html"),
        }
        cases = [
            {**literal, "manifest": {"$ref": "source.result"}},
            {**literal, "output": {"$ref": "source.result.name"}},
        ]
        bound_location = self.manifest(str(self.map))
        bound_location["references"][0]["location"] = {
            "$ref": "source.result.recipe.parameters.path"
        }
        cases.append({**literal, "manifest": bound_location})
        for params in cases:
            with self.subTest(params=params):
                self.assertTrue(
                    self.submit("workflow.run", self.workflow("asset.reference_board", params))[
                        "isError"
                    ]
                )
        self.assertEqual(self.worker.submitted, [])

    def test_reference_board_literal_local_or_web_reference_reaches_worker(self):
        for location in (str(self.map), "https://example.com/reference"):
            with self.subTest(location=location):
                result = self.submit(
                    "asset.reference_board",
                    {"manifest": self.manifest(location), "output": str(self.jobs / "review.html")},
                )
                self.assertFalse(result["isError"], result)
        self.assertEqual(len(self.worker.submitted), 2)

    def test_rpc_cannot_enable_rigify_or_inject_bootstrap_script(self):
        for arguments in (
            {"enable_rigify": True},
            {"script": "import arbitrary"},
            {"blender": "different-executable"},
        ):
            with self.subTest(arguments=arguments):
                self.assertTrue(self.submit("capabilities", {}, **arguments)["isError"])
        self.assertTrue(
            self.submit("rig.generate", {"object_name": "Rig", "enable_rigify": True})["isError"]
        )
        self.assertEqual(self.worker.submitted, [])

    def test_oversized_unicode_result_is_bounded_without_claiming_rollback(self):
        self.worker.poll_result = {
            "job_id": "owned",
            "state": "completed",
            "response": {"ok": True, "result": "é" * 600000},
        }
        messages = [
            rpc(
                "tools/call",
                {"name": "framewright_poll_job", "arguments": {"job_id": "owned"}},
                identity=11,
            ),
            rpc("ping", identity=12),
        ]
        stream = io.BytesIO("".join(json.dumps(item) + "\n" for item in messages).encode())
        output = io.BytesIO()
        serve(self.server, stream, output)
        encoded_lines = output.getvalue().splitlines(keepends=True)
        self.assertTrue(all(len(line) <= MAX_MESSAGE_BYTES for line in encoded_lines))
        first, second = [json.loads(line) for line in encoded_lines]
        self.assertEqual(first["id"], 11)
        self.assertEqual(first["error"]["code"], -32000)
        self.assertIn("does not undo completed work", first["error"]["message"])
        self.assertEqual(second["id"], 12)
        self.assertIn("result", second)
        self.assertEqual(self.worker.poll_result["state"], "completed")
        self.assertTrue(self.worker.closed)


if __name__ == "__main__":
    unittest.main()
