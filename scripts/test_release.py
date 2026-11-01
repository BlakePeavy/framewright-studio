"""Install and exercise a release ZIP using disposable Blender preferences only."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPOSITORY_ID = "framewright_release_test"
EXTENSION_ID = "framewright_studio"
SUCCESS_MARKER = "FRAMEWRIGHT_INSTALLED_RELEASE_OK"

# This script is copied into the temporary directory. It deliberately imports the
# installed extension namespace, never the development checkout's package.
VERIFY_SCRIPT = r"""
import importlib
import json
import os
import sys
from pathlib import Path

import addon_utils
import bpy

repo_id = os.environ["FRAMEWRIGHT_TEST_REPOSITORY_ID"]
module_name = "bl_ext." + repo_id + ".framewright_studio"
installed_root = Path(os.environ["FRAMEWRIGHT_TEST_REPOSITORY_PATH"]).resolve()
config_root = Path(os.environ["BLENDER_USER_CONFIG"]).resolve()

assert Path(bpy.utils.user_resource("CONFIG")).resolve() == config_root
assert module_name in bpy.context.preferences.addons, "Enablement was not saved"
assert addon_utils.check(module_name) == (True, True), "Startup did not enable the add-on"
assert module_name in sys.modules, "Expected Blender to import the enabled extension"
package = importlib.import_module(module_name)
package_path = Path(package.__file__).resolve()
assert package_path.is_relative_to(installed_root), str(package_path)
assert hasattr(bpy.types.Scene, "framewright_profile"), "UI properties are not registered"
assert hasattr(bpy.types, "FRAMEWRIGHT_PT_studio"), "Studio panel is not registered"

api = importlib.import_module(module_name + ".api")

def request(command, params=None):
    response = api.dispatch({
        "schema_version": "1.0",
        "request_id": "installed-release-smoke",
        "command": command,
        "params": {} if params is None else params,
    })
    assert response["ok"], response
    json.dumps(response, allow_nan=False)
    return response["result"]

capabilities = request("capabilities")
assert capabilities["extension_version"] == os.environ["FRAMEWRIGHT_EXPECTED_VERSION"]
assert "scene.validate" in {item["name"] for item in capabilities["commands"]}
assert "cinematic_8k" in capabilities["profiles"]
inspection = request("scene.inspect")
assert inspection["name"] == bpy.context.scene.name
report = request("scene.validate", {"profile": "cinematic_8k"})
assert isinstance(report["findings"], list)
assert report["settings"]["texture_target"] == 8192

bpy.context.scene.framewright_profile = "cinematic_8k"
assert bpy.ops.framewright.validate_scene() == {"FINISHED"}
ui_report = json.loads(bpy.context.scene.framewright_report)
assert isinstance(ui_report["findings"], list)
assert ui_report["settings"]["id"] == "cinematic_8k"

if capabilities["extension_version"] != "0.1.0":
    assert hasattr(bpy.types, "FRAMEWRIGHT_PT_production"), "Production panel missing"
    source_names = set(bpy.context.scene.objects.keys())
    result = request("workflow.run", {"run_id": "installed-flow", "dry_run": False, "steps": [
        {"id": "build", "command": "model.build_prop", "params": {"name": "InstalledCabinet"}},
        {"id": "check", "command": "scene.validate", "params": {"overrides": {"require_materials": False}},
         "require": [{"path": "result.passed", "equals": True}]},
    ]})
    assert result["status"] == "completed", result
    assert source_names <= set(bpy.context.scene.objects.keys())
    assert request("asset.manifest_validate", {"manifest": request("asset.manifest_create", {"name": "Installed"})})["valid"]

# Exercise Blender's actual add-on lifecycle after the saved-preferences startup.
addon_utils.disable(module_name, default_set=True)
assert not addon_utils.check(module_name)[1]
assert not hasattr(bpy.types.Scene, "framewright_profile")
assert not hasattr(bpy.types, "FRAMEWRIGHT_PT_studio")
addon_utils.enable(module_name, default_set=True)
assert addon_utils.check(module_name) == (True, True)
assert hasattr(bpy.types.Scene, "framewright_profile")
assert bpy.ops.framewright.validate_scene() == {"FINISHED"}

print("FRAMEWRIGHT_INSTALLED_RELEASE_OK " + json.dumps({
    "blender": bpy.app.version_string,
    "extension": capabilities["extension_version"],
    "module": module_name,
    "installed_path": str(package_path),
    "checks": ["isolated_config", "persisted_enablement", "installed_import",
               "capabilities", "scene_inspection", "scene_validation",
               "registered_operator", "disable_enable"],
}, sort_keys=True))
"""


def run_blender(
    blender: str, arguments: list[str], *, environment: dict[str, str], directory: Path
) -> str:
    command = [blender, "--background", "--disable-autoexec", "--offline-mode", *arguments]
    print("+ " + subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=directory,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    completed.check_returncode()
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, help="Blender 5.2 executable")
    parser.add_argument("--zip", required=True, type=Path, dest="archive", help="Built release ZIP")
    parser.add_argument(
        "--previous-zip", type=Path, help="Test upgrade and rollback from this prior release"
    )
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        parser.error(f"Release ZIP was not found: {archive}")
    if args.previous_zip and not args.previous_zip.is_file():
        parser.error("Previous release ZIP was not found")
    blender = shutil.which(args.blender)
    if blender is None:
        parser.error("Blender executable was not found")
    blender = str(Path(blender).resolve())

    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(f"Release ZIP: {archive.name}; sha256={digest}", flush=True)

    # tempfile owns creation and cleanup. No user's Blender preference or script
    # directory is renamed, deleted, copied or modified by the test runner.
    with tempfile.TemporaryDirectory(prefix="framewright-release-") as temporary:
        root = Path(temporary).resolve()
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        user_directories = {
            "BLENDER_USER_RESOURCES": "resources",
            "BLENDER_USER_CONFIG": "config",
            "BLENDER_USER_SCRIPTS": "scripts",
            "BLENDER_USER_EXTENSIONS": "extensions",
            "BLENDER_USER_DATAFILES": "datafiles",
            "TEMP": "temp",
            "TMP": "temp",
        }
        for variable, relative in user_directories.items():
            location = root / relative
            location.mkdir(exist_ok=True)
            environment[variable] = str(location)
        repository = root / "extensions" / REPOSITORY_ID
        repository.mkdir()
        environment["FRAMEWRIGHT_TEST_REPOSITORY_ID"] = REPOSITORY_ID
        environment["FRAMEWRIGHT_TEST_REPOSITORY_PATH"] = str(repository)
        verifier = root / "verify_installed_release.py"
        verifier.write_text(VERIFY_SCRIPT, encoding="utf-8")

        # Only this first process uses factory-startup. Later processes must load
        # the isolated saved preferences to test actual install persistence.
        run_blender(
            blender,
            [
                "--factory-startup",
                "--command",
                "extension",
                "repo-add",
                REPOSITORY_ID,
                "--directory",
                str(repository),
                "--clear-all",
            ],
            environment=environment,
            directory=root,
        )
        sequence = [archive]
        if args.previous_zip:
            previous = args.previous_zip.resolve()
            sequence = [previous, archive, previous, archive]
        for candidate in sequence:
            with zipfile.ZipFile(candidate) as zipped:
                version = tomllib.loads(zipped.read("blender_manifest.toml").decode())["version"]
            environment["FRAMEWRIGHT_EXPECTED_VERSION"] = version
            run_blender(
                blender,
                [
                    "--command",
                    "extension",
                    "install-file",
                    str(candidate),
                    "--repo",
                    REPOSITORY_ID,
                    "--enable",
                ],
                environment=environment,
                directory=root,
            )
            output = run_blender(
                blender,
                ["--python-exit-code", "1", "--python", str(verifier)],
                environment=environment,
                directory=root,
            )
            if SUCCESS_MARKER not in output:
                raise RuntimeError("Blender exited without confirming installed release checks")
        print("FRAMEWRIGHT_RELEASE_LIFECYCLE_OK " + str([path.name for path in sequence]))
    print("Installed release smoke passed; disposable Blender files removed", flush=True)


if __name__ == "__main__":
    main()
