"""Absolute MCP entry under the extension's installed package identity."""

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def request(method, params=None, identity=1):
    return {
        "jsonrpc": "2.0",
        "id": identity,
        "method": method,
        "params": {**(params or {}), "_meta": dict(META)},
    }


class InstalledMCPEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="framewright-installed-mcp-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = tomllib.loads((ROOT / "framewright" / "blender_manifest.toml").read_text())
        self.package = self.root / "installation" / self.manifest["id"]
        self.assertEqual(self.package.name, "framewright_studio")
        shutil.copytree(
            ROOT / "framewright",
            self.package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        self.entry = self.package / "mcp_stdio.py"
        self.cwd = self.root / "unrelated-cwd"
        self.cwd.mkdir()
        self.environment = os.environ.copy()
        self.environment.pop("PYTHONPATH", None)
        self.environment.pop("PYTHONHOME", None)

    def test_installed_absolute_pure_entry_discovery_capabilities_and_version(self):
        messages = [
            request("server/discover"),
            request("tools/call", {"name": "framewright_capabilities", "arguments": {}}, 2),
        ]
        completed = subprocess.run(
            [sys.executable, str(self.entry), "--pure-only"],
            input="".join(json.dumps(message) + "\n" for message in messages),
            cwd=self.cwd,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([reply["id"] for reply in responses], [1, 2])
        self.assertIn("supportedVersions", responses[0]["result"])
        self.assertEqual(
            responses[0]["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["version"],
            self.manifest["version"],
        )
        self.assertFalse(responses[1]["result"]["isError"])
        capabilities = responses[1]["result"]["structuredContent"]
        self.assertEqual(capabilities["extension_version"], self.manifest["version"])
        self.assertIn("scene.inspect", {entry["name"] for entry in capabilities["commands"]})

    @unittest.skipUnless(
        os.environ.get("FRAMEWRIGHT_BLENDER"),
        "Set FRAMEWRIGHT_BLENDER for the installed-package owned worker",
    )
    def test_installed_absolute_entry_runs_owned_scene_inspection_and_preserves_input(self):
        blender = os.environ["FRAMEWRIGHT_BLENDER"]
        assets, jobs = self.root / "assets", self.root / "jobs"
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
            timeout=45,
            check=False,
        )
        self.assertEqual(fixture.returncode, 0, fixture.stdout + fixture.stderr)
        original = hashlib.sha256(blend.read_bytes()).hexdigest()
        replies = queue.Queue()
        with (self.root / "transport.log").open("w", encoding="utf-8") as error_log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(self.entry),
                    "--blender",
                    blender,
                    "--job-root",
                    str(jobs),
                    "--asset-root",
                    str(assets),
                ],
                cwd=self.cwd,
                env=self.environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=error_log,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def read_responses():
                for line in process.stdout:
                    replies.put(line)
                replies.put(None)

            reader = threading.Thread(target=read_responses, daemon=True)
            reader.start()

            def call(name, arguments, identity):
                process.stdin.write(
                    json.dumps(
                        request("tools/call", {"name": name, "arguments": arguments}, identity)
                    )
                    + "\n"
                )
                process.stdin.flush()
                line = replies.get(timeout=15)
                self.assertIsNotNone(line, "Installed MCP process ended before replying")
                result = json.loads(line)
                self.assertEqual(result["id"], identity)
                self.assertFalse(result["result"]["isError"], result)
                return result["result"]["structuredContent"]

            try:
                submitted = call(
                    "framewright_submit_job",
                    {
                        "blend": str(blend),
                        "timeout": 30,
                        "request": {
                            "schema_version": "1.0",
                            "request_id": "installed-inspect",
                            "command": "scene.inspect",
                            "params": {},
                        },
                    },
                    1,
                )
                deadline, identity = time.monotonic() + 40, 2
                while True:
                    status = call("framewright_poll_job", {"job_id": submitted["job_id"]}, identity)
                    if status["state"] != "running":
                        break
                    self.assertLess(
                        time.monotonic(), deadline, "Installed owned inspection exceeded deadline"
                    )
                    identity += 1
                    time.sleep(0.1)
                self.assertEqual(status["state"], "completed", status)
                self.assertEqual(status["exit_code"], 0)
                self.assertTrue(status["response"]["ok"], status)
                self.assertIn(
                    "Cube", {obj["name"] for obj in status["response"]["result"]["objects"]}
                )
                job = Path(status["directory"])
                self.assertTrue(job.resolve().is_relative_to(jobs.resolve()))
                self.assertEqual(json.loads((job / "report.json").read_text()), status["response"])
                self.assertFalse((job / "derivative.blend").exists())
                self.assertEqual(list(jobs.iterdir()), [job])
                self.assertEqual(list(assets.iterdir()), [blend])
                self.assertEqual(hashlib.sha256(blend.read_bytes()).hexdigest(), original)
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                reader.join(timeout=2)
                process.stdout.close()
            self.assertFalse(reader.is_alive())
            self.assertEqual(process.returncode, 0)
        self.assertEqual(hashlib.sha256(blend.read_bytes()).hexdigest(), original)


if __name__ == "__main__":
    unittest.main()
