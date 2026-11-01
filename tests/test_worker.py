import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from framewright.worker import JobManager


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.blender = self.root / "blender.exe"
        self.blender.touch()
        self.blend = self.root / "source.blend"
        self.blend.write_bytes(b"original")
        self.process = Mock()
        self.process.poll.return_value = None
        self.launch = Mock(return_value=self.process)
        self.manager = JobManager(self.blender, self.root, popen=self.launch, clock=lambda: 0)
        self.addCleanup(self.manager.close)
        self.request = {
            "schema_version": "1.0",
            "request_id": "test",
            "command": "scene.inspect",
            "params": {},
        }

    def test_launch_uses_static_entry_and_separate_process(self):
        job = self.manager.submit(self.blend, self.request)
        command = self.launch.call_args.args[0]
        self.assertIn("--disable-autoexec", command)
        self.assertIn("--factory-startup", command)
        self.assertNotIn("--python-expr", command)
        self.assertEqual(job["state"], "running")
        self.assertEqual(self.blend.read_bytes(), b"original")

    def test_result_requires_report_even_with_zero_exit(self):
        job = self.manager.submit(self.blend, self.request)
        self.process.poll.return_value = 0
        self.assertEqual(self.manager.poll(job["job_id"])["state"], "failed")

    def test_valid_report_is_returned(self):
        job = self.manager.submit(self.blend, self.request)
        (Path(job["directory"]) / "report.json").write_text(
            json.dumps({"ok": True, "result": {"name": "Test"}})
        )
        self.process.poll.return_value = 0
        result = self.manager.poll(job["job_id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["response"]["result"]["name"], "Test")

    def test_concurrency_limit_rejects_before_launch(self):
        self.manager.submit(self.blend, self.request)
        with self.assertRaises(ValueError):
            self.manager.submit(self.blend, self.request)
        self.assertEqual(self.launch.call_count, 1)

    def test_cancel_terminates_only_owned_child(self):
        job = self.manager.submit(self.blend, self.request)
        result = self.manager.cancel(job["job_id"])
        self.assertEqual(result["state"], "cancelled")
        self.process.terminate.assert_called_once()
        with self.assertRaises(ValueError):
            self.manager.cancel("not-owned")

    def test_timeout_cancels_process(self):
        job = self.manager.submit(self.blend, self.request, timeout=1)
        self.manager.clock = lambda: 2
        self.assertEqual(self.manager.poll(job["job_id"])["state"], "timed_out")

    def test_invalid_request_never_launches(self):
        self.request["command"] = "python.exec"
        with self.assertRaises(ValueError):
            self.manager.submit(self.blend, self.request)
        self.launch.assert_not_called()

    def test_mutation_saves_new_owned_destination(self):
        self.request.update(command="model.build_prop", params={"dry_run": False})
        job = self.manager.submit(self.blend, self.request)
        command = self.launch.call_args.args[0]
        target = Path(command[command.index("--save-as") + 1])
        self.assertEqual(target.parent, Path(job["directory"]))
        self.assertNotEqual(target, self.blend)

    def test_rigify_worker_bootstrap_is_explicit_and_process_local(self):
        self.manager.submit(self.blend, self.request)
        self.assertNotIn("--enable-rigify", self.launch.call_args.args[0])
        configured = JobManager(self.blender, self.root, popen=self.launch, enable_rigify=True)
        self.addCleanup(configured.close)
        configured.submit(self.blend, self.request)
        self.assertIn("--enable-rigify", self.launch.call_args.args[0])
        with self.assertRaises(ValueError):
            JobManager(self.blender, self.root, enable_rigify="yes")


if __name__ == "__main__":
    unittest.main()
