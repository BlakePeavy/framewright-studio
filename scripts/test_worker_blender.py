"""Real-process worker checks against owned files only."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from framewright.worker import JobManager  # noqa:E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="framewright-worker-") as temporary:
        root = Path(temporary)
        fixture = root / "fixture.py"
        fixture.write_text(
            "import bpy,sys,addon_utils\naddon_utils.enable('rigify',default_set=True)\n"
            "bpy.ops.object.armature_basic_human_metarig_add()\nbpy.context.object.name='WorkerMetarig'\n"
            "bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])\n",
            encoding="utf-8",
        )
        source = root / "source.blend"
        subprocess.run(
            [
                args.blender,
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--python-exit-code",
                "1",
                "--python",
                str(fixture),
                "--",
                str(source),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
        )
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        manager = JobManager(args.blender, root, enable_rigify=True)
        try:
            for command, params in [
                ("scene.inspect", {}),
                ("model.build_prop", {"name": "WorkerCabinet", "dry_run": False}),
                ("rig.generate", {"object_name": "WorkerMetarig", "dry_run": False}),
            ]:
                job = manager.submit(
                    source,
                    {
                        "schema_version": "1.0",
                        "request_id": "worker-test",
                        "command": command,
                        "params": params,
                    },
                    timeout=45,
                )
                while job["state"] == "running":
                    time.sleep(0.05)
                    job = manager.poll(job["job_id"])
                if job["state"] != "completed":
                    raise AssertionError(
                        {
                            "job": job,
                            "log": (Path(job["directory"]) / "process.log").read_text(
                                errors="replace"
                            ),
                        }
                    )
                if (
                    command in {"model.build_prop", "rig.generate"}
                    and not (Path(job["directory"]) / "derivative.blend").is_file()
                ):
                    raise AssertionError("Missing persisted derivative")
                if (Path(job["directory"]) / "config" / "userpref.blend").exists():
                    raise AssertionError("Worker unexpectedly saved preferences")
            if hashlib.sha256(source.read_bytes()).hexdigest() != before:
                raise AssertionError("Source changed")
            print(
                "FRAMEWRIGHT_WORKER_OK "
                + json.dumps(
                    {
                        "checks": [
                            "real_inspection",
                            "real_mutation",
                            "persisted_derivative",
                            "source_hash_preserved",
                            "isolated_stock_rigify_generation",
                            "no_saved_preferences",
                        ]
                    }
                )
            )
        finally:
            manager.close()


if __name__ == "__main__":
    main()
