"""Independent integration regressions found during release review."""

import os
import tempfile
import unittest
from pathlib import Path
from sys import executable
from unittest.mock import patch

from framewright.api import dispatch
from framewright.commands import needs_scene_save, validate_params
from framewright.mcp_stdio import MCPServer
from framewright.worker import JobManager
from framewright.workflows import validate_workflow


def bound_mutation_request():
    return {
        "schema_version": "1.0",
        "request_id": "bound-apply-review",
        "command": "workflow.run",
        "params": {
            "run_id": "bound-apply-review",
            "dry_run": False,
            "steps": [
                {
                    "id": "options",
                    "command": "asset.manifest_create",
                    "params": {
                        "name": "Review fixture",
                        "recipe": {
                            "tool": "fixture",
                            "version": "1",
                            "operation": "options",
                            "parameters": {"preview": False},
                        },
                    },
                },
                {
                    "id": "build",
                    "command": "model.build_prop",
                    "params": {
                        "name": "ReviewBoundProp",
                        "dry_run": {"$ref": "options.result.recipe.parameters.preview"},
                    },
                },
            ],
        },
    }


class PersistenceReviewTests(unittest.TestCase):
    def test_bound_false_workflow_step_requires_scene_persistence(self):
        request = bound_mutation_request()
        validate_workflow(request["params"])
        self.assertTrue(needs_scene_save(request))

    def test_literal_step_preview_requires_no_scene_persistence(self):
        request = bound_mutation_request()
        request["params"]["steps"][1]["params"]["dry_run"] = True
        self.assertFalse(needs_scene_save(request))

    def test_worker_reserves_derivative_output_for_bound_mutation(self):
        commands = []

        class Process:
            returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

        def spawn(command, **kwargs):
            commands.append(command)
            return Process()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / "source.blend"
            blend.touch()
            manager = JobManager(executable, root, popen=spawn)
            try:
                manager.submit(blend, bound_mutation_request())
                self.assertIn("--save-as", commands[0])
                self.assertEqual(Path(commands[0][-1]).name, "derivative.blend")
            finally:
                manager.close()


class SchemaReviewTests(unittest.TestCase):
    FRAME_COMMANDS = {
        "rig.sample_deformation": {"object_name": "Mesh"},
        "animation.contacts": {"object_name": "Rig", "bones": ["foot"]},
        "animation.bake": {"object_name": "Rig"},
        "animation.retarget": {
            "object_name": "Rig",
            "source_name": "Source",
            "bone_map": {"root": "root"},
        },
        "animation.cleanup": {"object_name": "Rig"},
    }

    def assert_schema_rejected(self, command, params):
        with patch("framewright.commands.import_module") as loader:
            result = dispatch(
                {
                    "schema_version": "1.0",
                    "request_id": "schema-review",
                    "command": command,
                    "params": params,
                }
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
            loader.assert_not_called()

    def test_required_frame_bounds_reject_before_blender_import(self):
        for command, params in self.FRAME_COMMANDS.items():
            for missing in ("frame_start", "frame_end"):
                with self.subTest(command=command, missing=missing):
                    candidate = dict(params, frame_start=1, frame_end=2)
                    del candidate[missing]
                    self.assert_schema_rejected(command, candidate)

    def test_frame_range_and_step_match_handler_boundaries(self):
        for command, params in self.FRAME_COMMANDS.items():
            with self.subTest(command=command):
                valid = dict(params, frame_start=-1_000_000, frame_end=-1_000_000)
                validate_params(command, valid)
                self.assert_schema_rejected(command, dict(valid, frame_start=-1_000_001))
                if command != "animation.cleanup":
                    validate_params(command, dict(valid, step=1000))
                    self.assert_schema_rejected(command, dict(valid, step=1001))

    def test_bake_projection_and_margin_match_handler_boundaries(self):
        base = {"high_object": "High", "low_object": "Low"}
        for ray in (0.0001, 10):
            validate_params(
                "surfaces.bake_normal", dict(base, ray_distance=ray, margin=64, max_memory_mb=32768)
            )
        for changes in (
            {"ray_distance": 0.00001},
            {"ray_distance": 10.1},
            {"margin": 65},
            {"max_memory_mb": 32769},
        ):
            with self.subTest(changes=changes):
                self.assert_schema_rejected("surfaces.bake_normal", dict(base, **changes))

    def test_export_filename_default_is_available_through_api_schema(self):
        validate_params("asset.export", {"object_names": ["Mesh"], "directory": "C:/output"})

    def test_mcp_export_accepts_handler_default_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / "source.blend"
            blend.touch()
            with patch("framewright.worker.JobManager") as manager:
                worker = manager.return_value
                worker.directory = root
                worker.submit.return_value = {"job_id": "owned", "state": "running"}
                server = MCPServer(worker=worker, asset_root=root)
                response = server.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "_meta": {
                                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                "io.modelcontextprotocol/clientCapabilities": {},
                            },
                            "name": "framewright_submit_job",
                            "arguments": {
                                "blend": str(blend),
                                "request": {
                                    "schema_version": "1.0",
                                    "request_id": "export-default",
                                    "command": "asset.export",
                                    "params": {"object_names": ["Mesh"], "directory": str(root)},
                                },
                            },
                        },
                    }
                )
                self.assertFalse(response["result"]["isError"], response)
                worker.submit.assert_called_once()

    def test_mcp_relative_file_paths_reject_before_different_cwd_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server_cwd = root / "deep" / "sub"
            server_cwd.mkdir(parents=True)
            blend = root / "source.blend"
            blend.touch()
            (root / "reference.bin").write_bytes(b"fixture")
            cases = [
                ("asset.export", {"object_names": ["Mesh"], "directory": "../.."}),
                ("asset.reference_intake", {"label": "Fixture", "path": "../../reference.bin"}),
            ]
            with patch("framewright.worker.JobManager") as manager:
                worker = manager.return_value
                worker.directory = root
                worker.submit.return_value = {"job_id": "owned", "state": "running"}
                server = MCPServer(worker=worker, asset_root=root)
                previous_cwd = Path.cwd()
                try:
                    os.chdir(server_cwd)
                    for command, params in cases:
                        with self.subTest(command=command):
                            response = server.handle(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "tools/call",
                                    "params": {
                                        "_meta": {
                                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                            "io.modelcontextprotocol/clientCapabilities": {},
                                        },
                                        "name": "framewright_submit_job",
                                        "arguments": {
                                            "blend": str(blend),
                                            "request": {
                                                "schema_version": "1.0",
                                                "request_id": "relative-path",
                                                "command": command,
                                                "params": params,
                                            },
                                        },
                                    },
                                }
                            )
                            self.assertTrue(response["result"]["isError"], response)
                    worker.submit.assert_not_called()
                finally:
                    os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
