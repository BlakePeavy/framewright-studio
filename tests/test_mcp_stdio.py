"""MCP protocol and subprocess framing tests; no network or live Blender."""

import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from framewright.mcp_stdio import MCPServer, serve

MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def request(method, params=None, identity=1, modern=True):
    params = dict(params or {})
    if modern:
        params["_meta"] = dict(MODERN_META)
    return {"jsonrpc": "2.0", "id": identity, "method": method, "params": params}


class FakeWorker:
    def __init__(self, root):
        self.directory = root
        self.calls = []
        self.closed = False

    def submit(self, blend, request, timeout=300):
        self.calls.append((str(blend), request, timeout))
        return {"job_id": "job-1", "state": "running"}

    def poll(self, job_id):
        return {"job_id": job_id, "state": "completed"}

    def cancel(self, job_id):
        return {"job_id": job_id, "state": "cancelled"}

    def close(self):
        self.closed = True


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_server_version_matches_installed_capability_version_in_both_protocols(self):
        from framewright.api import capabilities

        expected = capabilities()["extension_version"]
        modern = self.server.handle(request("tools/list"))["result"]
        self.assertEqual(modern["_meta"]["io.modelcontextprotocol/serverInfo"]["version"], expected)
        legacy = MCPServer().handle(
            request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "version-check", "version": "1"},
                },
                modern=False,
            )
        )
        self.assertEqual(legacy["result"]["serverInfo"]["version"], expected)

    def test_oversized_response_is_bounded_without_claiming_job_rollback(self):
        class LargeResponse(MCPServer):
            def handle(self, message):
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"large": "x" * (1024 * 1024)},
                }

        output = io.BytesIO()
        serve(LargeResponse(), io.BytesIO((json.dumps(request("ping")) + "\n").encode()), output)
        self.assertLessEqual(len(output.getvalue()), 1024 * 1024)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32000)

    def test_reference_board_checks_both_output_and_local_reference_roots(self):
        from framewright.provenance import create_manifest, create_reference

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = FakeWorker(root)
            server = MCPServer(worker=worker, asset_root=root)
            manifest = create_manifest(
                {
                    "name": "Board",
                    "references": [
                        create_reference({"label": "Local", "location": str(root / "unknown.png")})
                    ],
                }
            )
            api_request = {
                "command": "asset.reference_board",
                "params": {"manifest": manifest, "output": str(root / "board.html")},
            }
            server._guard_paths(api_request)
            manifest["references"][0]["location"] = str(root.parent / "private.png")
            with self.assertRaises(ValueError):
                server._guard_paths(api_request)
            manifest["references"][0]["location"] = "https://example.com/reference"
            api_request["params"]["output"] = str(root.parent / "board.html")
            with self.assertRaises(ValueError):
                server._guard_paths(api_request)

    def test_modern_discovery_and_list_require_no_handshake(self):
        discovery = self.server.handle(request("server/discover"))
        self.assertEqual(discovery["result"]["resultType"], "complete")
        self.assertIn("2026-07-28", discovery["result"]["supportedVersions"])
        tools = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertIn("framewright_capabilities", [tool["name"] for tool in tools])
        self.assertNotIn("framewright_submit_job", [tool["name"] for tool in tools])
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in tools))

    def test_modern_request_requires_metadata_on_every_request(self):
        self.server.handle(request("server/discover"))
        result = self.server.handle(request("tools/list", modern=False))
        self.assertEqual(result["error"]["code"], -32602)

    def test_unsupported_modern_version_lists_supported_versions(self):
        value = request("server/discover")
        value["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "1900-01-01"
        error = self.server.handle(value)["error"]
        self.assertEqual(error["code"], -32022)
        self.assertIn("2026-07-28", error["data"]["supported"])

    def test_legacy_handshake_and_notification(self):
        initialized = self.server.handle(
            request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "Fixture", "version": "1"},
                },
                modern=False,
            )
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        self.assertIsNone(
            self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        self.assertIn("tools", self.server.handle(request("tools/list", modern=False))["result"])

    def test_tool_results_include_text_and_structured_data(self):
        response = self.server.handle(
            request("tools/call", {"name": "framewright_capabilities", "arguments": {}})
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertIn("commands", result["structuredContent"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])

    def test_bad_tool_arguments_fail_without_python_execution(self):
        result = self.server.handle(
            request(
                "tools/call",
                {"name": "framewright_capabilities", "arguments": {"python": "arbitrary code"}},
            )
        )
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(self.server.handle(request("python.exec"))["error"]["code"], -32601)

    def test_malformed_rpc_and_unknown_fields_are_rejected(self):
        for value in [
            [],
            {},
            {**request("tools/list"), "id": True},
            {**request("tools/list"), "unknown": True},
        ]:
            with self.subTest(value=value):
                self.assertEqual(self.server.handle(value)["error"]["code"], -32600)

    def test_stream_rejects_duplicates_and_keeps_stdout_json_only(self):
        stream = io.BytesIO(
            b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n'
            + (json.dumps(request("server/discover")) + "\n").encode()
        )
        output = io.BytesIO()
        serve(self.server, stream, output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertIn("result", lines[1])

    def test_submit_scopes_blend_and_rejects_injected_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "assets"
            root.mkdir()
            blend = root / "source.blend"
            blend.touch()
            (root.parent / "outside.blend").touch()
            worker = FakeWorker(root)
            server = MCPServer(worker=worker, asset_root=root)
            api_request = {
                "schema_version": "1.0",
                "request_id": "job",
                "command": "capabilities",
                "params": {},
            }
            args = {"blend": str(blend), "request": api_request}
            result = server.handle(
                request("tools/call", {"name": "framewright_submit_job", "arguments": args})
            )
            self.assertFalse(result["result"]["isError"])
            self.assertEqual(len(worker.calls), 1)
            result = server.handle(
                request(
                    "tools/call",
                    {
                        "name": "framewright_submit_job",
                        "arguments": {**args, "executable": "cmd.exe"},
                    },
                )
            )
            self.assertTrue(result["result"]["isError"])
            result = server.handle(
                request(
                    "tools/call",
                    {
                        "name": "framewright_submit_job",
                        "arguments": {**args, "blend": str(root.parent / "outside.blend")},
                    },
                )
            )
            self.assertTrue(result["result"]["isError"])
            self.assertEqual(len(worker.calls), 1)

    def test_file_commands_reject_escape_and_dynamic_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blend = root / "source.blend"
            blend.touch()
            worker = FakeWorker(root)
            server = MCPServer(worker=worker, asset_root=root)
            for params in [
                {
                    "object_names": ["Prop"],
                    "directory": str(root.parent),
                    "filename": "prop",
                    "dry_run": False,
                },
                {
                    "object_names": ["Prop"],
                    "directory": {"$ref": "previous.result.path"},
                    "filename": "prop",
                    "dry_run": False,
                },
            ]:
                api_request = {
                    "schema_version": "1.0",
                    "request_id": "job",
                    "command": "asset.export",
                    "params": params,
                }
                result = server.handle(
                    request(
                        "tools/call",
                        {
                            "name": "framewright_submit_job",
                            "arguments": {"blend": str(blend), "request": api_request},
                        },
                    )
                )
                self.assertTrue(result["result"]["isError"])
            self.assertEqual(worker.calls, [])

    def test_file_path_bindings_in_workflows_are_rejected_before_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blend = root / "source.blend"
            blend.touch()
            worker = FakeWorker(root)
            server = MCPServer(worker=worker, asset_root=root)
            workflow = {
                "run_id": "bound-path",
                "dry_run": False,
                "steps": [
                    {
                        "id": "name",
                        "command": "asset.manifest_create",
                        "params": {"name": str(root.parent)},
                    },
                    {
                        "id": "export",
                        "command": "asset.export",
                        "params": {
                            "object_names": ["Prop"],
                            "directory": {"$ref": "name.result.name"},
                            "filename": "prop",
                            "dry_run": False,
                        },
                    },
                ],
            }
            api_request = {
                "schema_version": "1.0",
                "request_id": "job",
                "command": "workflow.run",
                "params": workflow,
            }
            result = server.handle(
                request(
                    "tools/call",
                    {
                        "name": "framewright_submit_job",
                        "arguments": {"blend": str(blend), "request": api_request},
                    },
                )
            )
            self.assertTrue(result["result"]["isError"])
            self.assertEqual(worker.calls, [])

    def test_oversized_stream_message_closes_owned_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FakeWorker(Path(folder))
            server = MCPServer(worker=worker, asset_root=folder)
            output = io.BytesIO()
            serve(server, io.BytesIO(b" " * (1024 * 1024 + 1)), output)
            self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)
            self.assertTrue(worker.closed)

    def test_poll_cancel_and_eof_close_only_configured_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = FakeWorker(root)
            server = MCPServer(worker=worker, asset_root=root)
            for tool, state in [
                ("framewright_poll_job", "completed"),
                ("framewright_cancel_job", "cancelled"),
            ]:
                result = server.handle(
                    request("tools/call", {"name": tool, "arguments": {"job_id": "job-1"}})
                )
                self.assertEqual(result["result"]["structuredContent"]["state"], state)
            serve(server, io.BytesIO(), io.BytesIO())
            self.assertTrue(worker.closed)

    def test_actual_stdio_subprocess_handles_discovery_and_capabilities(self):
        lines = [
            request("server/discover", identity=1),
            request(
                "tools/call", {"name": "framewright_capabilities", "arguments": {}}, identity=2
            ),
        ]
        process = subprocess.run(
            [sys.executable, "-m", "framewright.mcp_stdio", "--pure-only"],
            input="".join(json.dumps(line) + "\n" for line in lines),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2])
        self.assertFalse(responses[1]["result"]["isError"])

    def test_absolute_entry_works_from_an_unrelated_client_directory(self):
        entry = Path(__file__).resolve().parents[1] / "framewright" / "mcp_stdio.py"
        with tempfile.TemporaryDirectory() as folder:
            process = subprocess.run(
                [sys.executable, str(entry), "--pure-only"],
                input=json.dumps(request("server/discover")) + "\n",
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("supportedVersions", json.loads(process.stdout)["result"])

    @unittest.skipUnless(
        os.environ.get("FRAMEWRIGHT_BLENDER"),
        "Set FRAMEWRIGHT_BLENDER for the real owned-worker smoke",
    )
    def test_real_stdio_to_owned_blender_job_preserves_source(self):
        blender = os.environ["FRAMEWRIGHT_BLENDER"]
        with tempfile.TemporaryDirectory(prefix="framewright-mcp-") as folder:
            root = Path(folder)
            assets = root / "assets"
            jobs = root / "jobs"
            assets.mkdir()
            jobs.mkdir()
            blend = assets / "source.blend"
            fixture = subprocess.run(
                [
                    blender,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    "--python-exit-code",
                    "1",
                    "--python-expr",
                    f"import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(fixture.returncode, 0, fixture.stdout + fixture.stderr)
            original = hashlib.sha256(blend.read_bytes()).hexdigest()
            replies = queue.Queue()
            with (root / "transport.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "framewright.mcp_stdio",
                        "--blender",
                        blender,
                        "--job-root",
                        str(jobs),
                        "--asset-root",
                        str(assets),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    text=True,
                    encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )

                def read_replies():
                    for line in process.stdout:
                        replies.put(line)

                reader = threading.Thread(target=read_replies, daemon=True)
                reader.start()

                def call(tool, arguments, identity):
                    process.stdin.write(
                        json.dumps(
                            request(
                                "tools/call",
                                {"name": tool, "arguments": arguments},
                                identity=identity,
                            )
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                    response = json.loads(replies.get(timeout=10))
                    self.assertEqual(response["id"], identity)
                    self.assertFalse(response["result"]["isError"], response)
                    return response["result"]["structuredContent"]

                try:
                    submitted = call(
                        "framewright_submit_job",
                        {
                            "blend": str(blend),
                            "request": {
                                "schema_version": "1.0",
                                "request_id": "mcp-smoke",
                                "command": "capabilities",
                                "params": {},
                            },
                            "timeout": 20,
                        },
                        1,
                    )
                    deadline = time.monotonic() + 25
                    identity = 2
                    while True:
                        state = call(
                            "framewright_poll_job", {"job_id": submitted["job_id"]}, identity
                        )
                        if state["state"] != "running":
                            break
                        self.assertLess(
                            time.monotonic(), deadline, "Owned Blender job did not complete"
                        )
                        identity += 1
                        time.sleep(0.1)
                    self.assertEqual(state["state"], "completed", state)
                    self.assertTrue(state["response"]["ok"])
                    self.assertEqual(hashlib.sha256(blend.read_bytes()).hexdigest(), original)
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    reader.join(timeout=2)
                    process.stdout.close()
                self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
