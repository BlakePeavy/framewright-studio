"""Owned background Blender jobs: bounded concurrency, cancellation and timeouts."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .commands import needs_scene_save


class JobManager:
    """Poll from a host process or Blender timer; never run bpy on worker threads.

    This manager launches only the packaged static entry script. Jobs are independent
    files/processes; it never attaches to or terminates a pre-existing Blender session.
    Completed job directories are retained as evidence until the owner removes them.
    """

    def __init__(
        self,
        blender,
        directory,
        *,
        max_concurrency=1,
        enable_rigify=False,
        popen=subprocess.Popen,
        clock=time.monotonic,
    ):
        self.blender = Path(blender).resolve()
        self.directory = Path(directory).resolve()
        if not self.blender.is_file() or not self.directory.is_dir():
            raise ValueError("Blender executable and existing job directory are required")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 4:
            raise ValueError("max_concurrency must be 1..4")
        self.max_concurrency = max_concurrency
        if type(enable_rigify) is not bool:
            raise ValueError("enable_rigify must be a boolean")
        self.enable_rigify = enable_rigify
        self.popen = popen
        self.clock = clock
        self.jobs = {}

    def submit(self, blend, request, *, timeout=300):
        from .api import _validate_request

        _validate_request(request)
        if type(timeout) not in (int, float) or not 1 <= timeout <= 3600:
            raise ValueError("timeout must be between 1 and 3600 seconds")
        blend = Path(blend).resolve()
        if not blend.is_file() or blend.suffix.lower() != ".blend":
            raise ValueError("Input must be an existing .blend file")
        for job_id in list(self.jobs):
            self.poll(job_id)
        if sum(j["state"] == "running" for j in self.jobs.values()) >= self.max_concurrency:
            raise ValueError("Maximum concurrent jobs already running")
        payload = json.dumps(request, allow_nan=False)
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Request exceeds 1 MiB")
        job_id = str(uuid4())
        root = self.directory / job_id
        root.mkdir()
        request_path = root / "request.json"
        request_path.write_text(payload, encoding="utf-8")
        output = root / "report.json"
        entry = Path(__file__).with_name("job_entry.py")
        command = [
            str(self.blender),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(blend),
            "--python-exit-code",
            "1",
            "--python",
            str(entry),
            "--",
            "--request",
            str(request_path),
            "--output",
            str(output),
        ]
        if needs_scene_save(request):
            command += ["--save-as", str(root / "derivative.blend")]
        if self.enable_rigify:
            command.append("--enable-rigify")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        for key, name in [
            ("BLENDER_USER_CONFIG", "config"),
            ("BLENDER_USER_SCRIPTS", "scripts"),
            ("BLENDER_USER_EXTENSIONS", "extensions"),
        ]:
            location = root / name
            location.mkdir()
            environment[key] = str(location)
        log = (root / "process.log").open("wb")
        try:
            process = self.popen(
                command,
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            log.close()
            raise
        self.jobs[job_id] = {
            "job_id": job_id,
            "directory": str(root),
            "state": "running",
            "deadline": self.clock() + timeout,
            "process": process,
            "log": log,
            "response": None,
            "exit_code": None,
        }
        return self._public(self.jobs[job_id])

    def _job(self, job_id):
        if job_id not in self.jobs:
            raise ValueError("Unknown or unowned job_id")
        return self.jobs[job_id]

    @staticmethod
    def _public(job):
        return {
            key: value for key, value in job.items() if key not in {"process", "log", "deadline"}
        }

    def _stop(self, job, state):
        process = job["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        job["state"] = state
        job["exit_code"] = process.poll()
        job["log"].close()

    def cancel(self, job_id):
        job = self._job(job_id)
        if job["state"] == "running":
            self._stop(job, "cancelled")
        return self._public(job)

    def poll(self, job_id):
        job = self._job(job_id)
        if job["state"] != "running":
            return self._public(job)
        code = job["process"].poll()
        if code is None:
            if self.clock() >= job["deadline"]:
                self._stop(job, "timed_out")
            return self._public(job)
        job["exit_code"] = code
        job["log"].close()
        report = Path(job["directory"]) / "report.json"
        try:
            if report.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Report exceeds 16 MiB")
            response = json.loads(report.read_text(encoding="utf-8"))
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise ValueError("Invalid response")
            job["response"] = response
            job["state"] = (
                "completed"
                if code == 0 and response["ok"]
                else "completed_with_findings"
                if code == 3 and response["ok"]
                else "failed"
            )
        except (OSError, ValueError):
            job["state"] = "failed"
        return self._public(job)

    def close(self):
        for job in self.jobs.values():
            if job["state"] == "running":
                self._stop(job, "cancelled")
