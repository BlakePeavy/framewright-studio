"""Exercise JSON jobs in temporary, isolated Blender processes.

Run: uv run python scripts/test_jobs.py --blender <Blender executable>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "scripts" / "blender_job.py"

FIXTURE_SCRIPT = """
import bpy
import sys

destination = sys.argv[sys.argv.index('--') + 1]
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
mesh = bpy.data.meshes.new('JobFixtureMesh')
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 2, 2)], [], [(0, 1, 2)])
mesh.update()
obj = bpy.data.objects.new('JobFixture', mesh)
bpy.context.scene.collection.objects.link(obj)
# A real structural error makes validation exit 3 independently of warnings.
obj.scale = (0, 1, 1)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
result = bpy.ops.wm.save_as_mainfile(filepath=destination)
if 'FINISHED' not in result:
    raise AssertionError('Fixture could not be saved')
"""

VERIFY_PREVIEW_SCRIPT = """
import bpy

objects = list(bpy.context.scene.objects)
if len(objects) != 1 or objects[0].name != 'JobFixture':
    raise AssertionError('Preview changed the scene objects')
source = objects[0]
if len(source.data.vertices) != 4 or source.hide_viewport or source.hide_render:
    raise AssertionError('Preview changed source data or visibility')
if bpy.context.view_layer.objects.active != source or not source.select_get():
    raise AssertionError('Preview changed active object or selection')
print('FRAMEWRIGHT_PREVIEW_PRESERVED')
"""

VERIFY_SAVED_SCRIPT = """
import bpy

scene = bpy.context.scene
if len(scene.objects) != 2:
    raise AssertionError('Saved repair must contain source and derivative')
source = scene.objects.get('JobFixture')
derivative = scene.objects.get('JobFixture_FW_Clean')
if source is None or derivative is None:
    raise AssertionError('Saved source/derivative identity is missing')
if len(source.data.vertices) != 4 or len(derivative.data.vertices) != 3:
    raise AssertionError('Saved repair changed the source or lost its repair')
if source.data == derivative.data:
    raise AssertionError('Derivative shares the source mesh')
if not derivative.hide_viewport or not derivative.hide_render:
    raise AssertionError('Derivative must remain hidden after reopening')
if source.hide_viewport or source.hide_render:
    raise AssertionError('Source visibility changed')
if tuple(source.scale) != (0.0, 1.0, 1.0):
    raise AssertionError('Source transform changed')
if bpy.context.view_layer.objects.active != source or not source.select_get():
    raise AssertionError('Saved repair changed source selection')
print('FRAMEWRIGHT_SAVED_REPAIR_PRESERVED')
"""


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(arguments: list[str], expected: int, label: str) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        check=False,
    )
    combined = result.stdout + result.stderr
    require(
        result.returncode == expected,
        f"{label}: expected exit {expected}, got {result.returncode}\n{combined[-6000:]}",
    )
    return combined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, help="Blender 5.2 executable")
    args = parser.parse_args()
    blender = shutil.which(args.blender)
    if blender is None:
        parser.error("Blender executable was not found")
    base = [blender, "--background", "--factory-startup", "--disable-autoexec", "--offline-mode"]
    with tempfile.TemporaryDirectory(prefix="framewright-jobs-") as directory:
        temporary = Path(directory)
        source = temporary / "source.blend"
        fixture = temporary / "fixture.py"
        fixture.write_text(FIXTURE_SCRIPT, encoding="utf-8")
        verify_preview = temporary / "verify_preview.py"
        verify_preview.write_text(VERIFY_PREVIEW_SCRIPT, encoding="utf-8")
        verify_saved = temporary / "verify_saved.py"
        verify_saved.write_text(VERIFY_SAVED_SCRIPT, encoding="utf-8")
        run(
            [*base, "--python-exit-code", "1", "--python", str(fixture), "--", str(source)],
            0,
            "fixture",
        )
        source_hash = fingerprint(source)

        def job(command, params, stem, expected=0, save_as=None, output=None, after=None):
            request = temporary / f"{stem}-request.json"
            output = output or temporary / f"{stem}-report.json"
            request.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "request_id": stem,
                        "command": command,
                        "params": params,
                    }
                ),
                encoding="utf-8",
            )
            arguments = [*base, str(source), "--python-exit-code", "1", "--python", str(JOB)]
            if after:
                arguments.extend(["--python", str(after)])
            arguments.extend(["--", "--request", str(request), "--output", str(output)])
            if save_as:
                arguments.extend(["--save-as", str(save_as)])
            stdout = run(arguments, expected, stem)
            require(fingerprint(source) == source_hash, f"{stem}: source blend changed")
            return output, stdout

        report, _ = job("capabilities", {}, "capabilities")
        response = json.loads(report.read_text(encoding="utf-8"))
        require(response["ok"] is True, "Capabilities must succeed")
        require(
            "scene.validate" in {item["name"] for item in response["result"]["commands"]},
            "Capabilities response is incomplete",
        )

        report, _ = job("scene.validate", {"profile": "studio_static"}, "validate", expected=3)
        response = json.loads(report.read_text(encoding="utf-8"))
        require(response["ok"] and not response["result"]["passed"], "Expected failed validation")
        require(response["result"]["counts"]["ERROR"] >= 1, "Validation report lost ERROR findings")
        require(
            any(item["rule_id"] == "INVALID_SCALE" for item in response["result"]["findings"]),
            "Validation must explain the fixture's invalid scale",
        )

        before_blends = {path.name for path in temporary.glob("*.blend*")}
        report, stdout = job(
            "mesh.remove_loose_vertices",
            {"object_name": "JobFixture"},
            "preview",
            after=verify_preview,
        )
        response = json.loads(report.read_text(encoding="utf-8"))
        require(response["ok"] and response["result"]["dry_run"], "Preview must be dry-run")
        require(response["result"]["removed_vertices"] == 1, "Preview lost isolated vertex")
        require("FRAMEWRIGHT_PREVIEW_PRESERVED" in stdout, "Preview preservation check did not run")
        require(
            {path.name for path in temporary.glob("*.blend*")} == before_blends,
            "Preview created or replaced a blend file",
        )

        repaired = temporary / "repaired.blend"
        repair_params = {"object_name": "JobFixture", "dry_run": False}
        report, _ = job("mesh.remove_loose_vertices", repair_params, "apply", save_as=repaired)
        response = json.loads(report.read_text(encoding="utf-8"))
        require(response["ok"] and not response["result"]["dry_run"], "Repair must be applied")
        require(
            response["result"]["hidden"] is True, "Repair response must report hidden derivative"
        )
        require(repaired.is_file() and repaired.stat().st_size > 0, "Repair blend is missing")
        empty_backups = [
            path.name
            for path in temporary.glob("repaired.blend*")
            if path != repaired and path.stat().st_size == 0
        ]
        require(not empty_backups, f"Repair left empty backup reservations: {empty_backups}")
        stdout = run(
            [*base, str(repaired), "--python-exit-code", "1", "--python", str(verify_saved)],
            0,
            "reopen-repair",
        )
        require("FRAMEWRIGHT_SAVED_REPAIR_PRESERVED" in stdout, "Saved repair check did not run")
        require(fingerprint(source) == source_hash, "Reopening derivative altered source")

        report, _ = job("mesh.remove_loose_vertices", repair_params, "missing-save", expected=2)
        require(not report.exists(), "Rejected repair should not leave a report reservation")

        existing_report = temporary / "keep-report.json"
        existing_report.write_text('{"keep":"existing report"}\n', encoding="utf-8")
        existing_hash = fingerprint(existing_report)
        uncreated = temporary / "must-not-be-saved.blend"
        job(
            "mesh.remove_loose_vertices",
            repair_params,
            "existing-report",
            expected=2,
            save_as=uncreated,
            output=existing_report,
        )
        require(fingerprint(existing_report) == existing_hash, "Existing report was overwritten")
        require(not uncreated.exists(), "Existing report rejection still saved a derivative")

        repaired_hash = fingerprint(repaired)
        report, _ = job(
            "mesh.remove_loose_vertices",
            repair_params,
            "existing-save",
            expected=2,
            save_as=repaired,
        )
        require(fingerprint(repaired) == repaired_hash, "Existing derivative was overwritten")
        require(not report.exists(), "Rejected save should not leave a report reservation")

        report, _ = job(
            "mesh.remove_loose_vertices", repair_params, "source-save", expected=2, save_as=source
        )
        require(not report.exists(), "Source overwrite rejection left a report reservation")
    print("FRAMEWRIGHT_JOB_TESTS_OK checks=8")


if __name__ == "__main__":
    main()
