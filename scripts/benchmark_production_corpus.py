"""Pinned local technical fixtures, each operation measured in fresh Blender processes."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SCRIPT_ENTRY_NS = time.perf_counter_ns()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ALLOWED = {
    "scene.resources",
    "scene.inspect",
    "scene.validate",
    "mesh.inspect_evaluated",
    "surfaces.inspect",
    "animation.skin_contacts",
}
USER_DIRS = (
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_EXTENSIONS",
    "BLENDER_USER_DATAFILES",
    "BLENDER_USER_RESOURCES",
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_new(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def read_manifest(path):
    if Path(path).stat().st_size > 1024**2:
        raise ValueError("Manifest exceeds the 1 MiB intake bound")

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate manifest JSON field")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_fields)


def identity_path(identity, root):
    if not isinstance(identity, dict) or set(identity) != {"path", "sha256", "bytes"}:
        raise ValueError("File identity requires path, sha256 and bytes")
    relative = identity["path"]
    if not isinstance(relative, str) or len(relative) > 2048 or "\\" in relative or ":" in relative:
        raise ValueError("File path must be a portable relative artifact path")
    parts = Path(relative).parts
    if not parts or parts[0] != "artifacts" or any(part in {"..", "."} for part in parts):
        raise ValueError("File path must stay inside the explicit artifacts root")
    target = (Path(root) / relative).resolve(strict=True)
    if not target.is_relative_to((Path(root) / "artifacts").resolve()) or not target.is_file():
        raise ValueError("File path escapes the artifacts root")
    if type(identity["bytes"]) is not int or not 0 < identity["bytes"] <= 2 * 1024**3:
        raise ValueError("Invalid file byte bound")
    if not isinstance(identity["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", identity["sha256"]
    ):
        raise ValueError("Invalid file hash")
    if target.stat().st_size != identity["bytes"] or digest(target) != identity["sha256"]:
        raise ValueError("File identity differs from the pinned manifest")
    return target


def _names(value, maximum=256):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or any(not isinstance(x, str) or not x or len(x) > 1024 for x in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Expected unique bounded names")


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ValueError("Invalid fixture/operation identity")


def _checks(checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= 256:
        raise ValueError("Explicit expected observations are required")
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) != {"path", "op", "value"}
            or check["op"] not in {"eq", "len", "gte", "rule"}
            or not isinstance(check["path"], str)
            or not check["path"].startswith("/")
            or len(check["path"]) > 2048
        ):
            raise ValueError("Invalid observation check")
        if (
            check["op"] == "len"
            and (type(check["value"]) is not int or check["value"] < 0)
            or check["op"] == "gte"
            and type(check["value"]) not in (int, float)
            or check["op"] == "rule"
            and (not isinstance(check["value"], str) or not check["value"])
        ):
            raise ValueError("Observation value does not match its operator")


def validate_manifest(data, root=ROOT):
    from framewright.commands import validate_params

    try:
        encoded = json.dumps(data, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValueError("Manifest must contain finite JSON") from error
    if (
        len(encoded) > 1024**2
        or not isinstance(data, dict)
        or set(data) != {"schema_version", "corpus_id", "corpus_version", "fixtures"}
        or data["schema_version"] != "1.0"
    ):
        raise ValueError("Invalid bounded versioned corpus manifest")
    _identifier(data["corpus_id"])
    if type(data["corpus_version"]) is not int or data["corpus_version"] < 1:
        raise ValueError("Invalid corpus version")
    fixtures = data["fixtures"]
    if not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 16:
        raise ValueError("Expected 1 to 16 explicit fixtures")
    ids = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != {
            "id",
            "version",
            "source",
            "dependencies",
            "receipts",
            "scene",
            "objects",
            "scene_objects",
            "operations",
            "provenance",
        }:
            raise ValueError("Invalid fixture fields")
        _identifier(fixture["id"])
        if fixture["id"] in ids or type(fixture["version"]) is not int or fixture["version"] < 1:
            raise ValueError("Fixture identities must be unique and versioned")
        ids.add(fixture["id"])
        if not isinstance(fixture["scene"], str) or not 1 <= len(fixture["scene"]) <= 256:
            raise ValueError("Expected one exact scene")
        _names(fixture["objects"], 128)
        _names(fixture["scene_objects"], 1000)
        if not set(fixture["objects"]) <= set(fixture["scene_objects"]):
            raise ValueError("Subject scope must be contained in the pinned scene scope")
        for key in ("dependencies", "receipts"):
            if not isinstance(fixture[key], list) or len(fixture[key]) > 128:
                raise ValueError("File dependencies must be bounded")
        for item in [fixture["source"], *fixture["dependencies"], *fixture["receipts"]]:
            identity_path(item, root)
        if Path(fixture["source"]["path"]).suffix.lower() != ".blend":
            raise ValueError("Fixture source must be a .blend")
        provenance = fixture["provenance"]
        if (
            not isinstance(provenance, dict)
            or provenance.get("artist_accepted") is not False
            or provenance.get("native_verified") is not False
        ):
            raise ValueError("This technical corpus cannot assign artist or native acceptance")
        operations = fixture["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 8:
            raise ValueError("Expected 1 to 8 operations")
        operation_ids = set()
        for operation in operations:
            if (
                not isinstance(operation, dict)
                or not {"id", "requests", "expectations"} <= set(operation)
                or set(operation) - {"id", "requests", "expectations", "control"}
            ):
                raise ValueError("Invalid operation fields")
            _identifier(operation["id"])
            if operation["id"] in operation_ids:
                raise ValueError("Duplicate operation identity")
            operation_ids.add(operation["id"])
            requests = operation["requests"]
            if not isinstance(requests, list) or not 1 <= len(requests) <= 16:
                raise ValueError("Expected bounded read-only requests")
            for request in requests:
                if (
                    not isinstance(request, dict)
                    or set(request) != {"command", "params"}
                    or request["command"] not in ALLOWED
                ):
                    raise ValueError("Corpus operations allow only explicit read-only commands")
                validate_params(request["command"], request["params"])
                params = request["params"]
                names = [params[k] for k in ("object_name", "surface_name") if k in params]
                names += [marker["object_name"] for marker in params.get("markers", [])]
                if (
                    not set(names) <= set(fixture["objects"])
                    or params.get("scene_name", fixture["scene"]) != fixture["scene"]
                ):
                    raise ValueError("Request escapes the declared subject or scene scope")
            _checks(operation["expectations"])
            control = operation.get("control")
            if control is not None:
                if (
                    not isinstance(control, dict)
                    or set(control) != {"kind", "request_index", "expectations"}
                    or control["kind"] not in {"remove_uvs", "raised_surface", "sample_budget"}
                    or type(control["request_index"]) is not int
                    or not 0 <= control["request_index"] < len(requests)
                ):
                    raise ValueError("Only declared owned-copy controls are allowed")
                command = requests[control["request_index"]]["command"]
                if command != (
                    "surfaces.inspect"
                    if control["kind"] == "remove_uvs"
                    else "animation.skin_contacts"
                ):
                    raise ValueError("Control does not match its diagnostic command")
                _checks(control["expectations"])
    return data


def check_observations(payload, checks):
    for check in checks:
        value = payload
        try:
            for part in check["path"].split("/")[1:]:
                key = part.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
            expected, op = check["value"], check["op"]
            passed = (
                type(value) is type(expected) and canonical_hash(value) == canonical_hash(expected)
                if op == "eq"
                else isinstance(value, (list, dict, str)) and len(value) == expected
                if op == "len"
                else type(value) in (int, float) and math.isfinite(value) and value >= expected
                if op == "gte"
                else isinstance(value, list)
                and any(isinstance(row, dict) and row.get("rule_id") == expected for row in value)
            )
        except (KeyError, IndexError, TypeError, ValueError):
            passed = False
        if not passed:
            raise AssertionError(f"Expected observation failed: {check!r}")


def runtime_identity():
    paths = sorted((ROOT / "framewright").glob("*.py"))
    paths += [
        Path(__file__),
        ROOT / "scripts/benchmark_process_performance.py",
        ROOT / "scripts/build_cabinet_reference_pilot.py",
    ]
    files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for path in paths]
    return {"sha256": canonical_hash(files), "files": files}


def source_state(scene, subjects):
    """Bounded authored-state fingerprint, not serialization of arbitrary Blender RNA."""
    import bpy

    from framewright.interchange import _source_record
    from framewright.rigging import _transform_channels
    from scripts.build_cabinet_reference_pilot import fingerprint

    extra = []
    for obj in subjects:
        keys = getattr(obj.data, "shape_keys", None)
        blocks = [obj, obj.data, keys]
        animations = []
        for block in (b for b in blocks if b is not None):
            anim = getattr(block, "animation_data", None)
            if anim is None:
                continue
            action = anim.action
            animations.append(
                {
                    "owner": block.name,
                    "action": action.name if action else None,
                    "slot": anim.action_slot.handle if anim.action_slot else None,
                    "curves": [
                        (
                            curve.data_path,
                            curve.array_index,
                            [
                                (
                                    tuple(key.co),
                                    tuple(key.handle_left),
                                    tuple(key.handle_right),
                                    key.interpolation,
                                )
                                for key in curve.keyframe_points
                            ],
                        )
                        for layer in action.layers
                        for strip in layer.strips
                        for bag in strip.channelbags
                        for curve in bag.fcurves
                    ]
                    if action
                    else [],
                    "drivers": [
                        (
                            curve.data_path,
                            curve.array_index,
                            curve.driver.type,
                            curve.driver.expression,
                            [
                                (
                                    var.name,
                                    var.type,
                                    [
                                        (
                                            target.id.name if target.id else None,
                                            target.data_path,
                                            target.bone_target,
                                        )
                                        for target in var.targets
                                    ],
                                )
                                for var in curve.driver.variables
                            ],
                        )
                        for curve in anim.drivers
                    ],
                }
            )
        extra.append(
            {
                "name": obj.name,
                "channels": _transform_channels(obj),
                "pose_channels": {bone.name: _transform_channels(bone) for bone in obj.pose.bones}
                if obj.type == "ARMATURE"
                else {},
                "keys": [
                    (key.name, key.value, [tuple(point.co) for point in key.data])
                    for key in keys.key_blocks
                ]
                if keys
                else [],
                "animations": animations,
            }
        )
    meshes = [obj for obj in subjects if obj.type == "MESH"]
    return canonical_hash(
        {
            "source_records": _source_record(subjects),
            "mesh_material_graphs": fingerprint(meshes),
            "extra": extra,
            "context": {
                "scene": scene.name,
                "frame": scene.frame_current,
                "subframe": scene.frame_subframe,
                "units": scene.unit_settings.scale_length,
                "fps": [scene.render.fps, scene.render.fps_base],
                "active": bpy.context.view_layer.objects.active.name
                if bpy.context.view_layer.objects.active
                else None,
                "selected": sorted(obj.name for obj in bpy.context.selected_objects),
            },
            "inventory": {
                kind: sorted(item.session_uid for item in getattr(bpy.data, kind))
                for kind in (
                    "objects",
                    "scenes",
                    "meshes",
                    "armatures",
                    "shape_keys",
                    "actions",
                    "materials",
                    "images",
                    "lights",
                    "cameras",
                )
            },
        }
    )


def _dispatch(request, request_id):
    from framewright.api import dispatch

    return dispatch({"schema_version": "1.0", "request_id": request_id, **request})


def run_control(operation, scene):
    import bpy

    control = operation["control"]
    request = copy.deepcopy(operation["requests"][control["request_index"]])
    params = request["params"]
    owned, data = None, None
    try:
        if control["kind"] == "sample_budget":
            params["max_samples"] = 1
        else:
            key = "object_name" if control["kind"] == "remove_uvs" else "surface_name"
            original = scene.objects[params[key]]
            owned = original.copy()
            owned.data = original.data.copy()
            data = owned.data
            owned.name = "FW_Corpus_Control_" + original.name
            scene.collection.objects.link(owned)
            params[key] = owned.name
            if control["kind"] == "remove_uvs":
                while data.uv_layers:
                    data.uv_layers.remove(data.uv_layers[0])
            else:
                owned.location.z += 0.04 / scene.unit_settings.scale_length
            bpy.context.view_layer.update()
        response = _dispatch(request, "corpus-control")
        check_observations(response, control["expectations"])
        return {"kind": control["kind"], "expectations_met": True, "response": response}
    finally:
        if owned is not None:
            bpy.data.objects.remove(owned, do_unlink=True)
        if data is not None:
            bpy.data.meshes.remove(data)


def run_loaded_operation(fixture, operation, root=ROOT):
    import bpy

    from scripts.benchmark_process_performance import process_memory

    scene = bpy.data.scenes.get(fixture["scene"])
    if scene is None or sorted(obj.name for obj in scene.objects) != sorted(
        fixture["scene_objects"]
    ):
        raise ValueError("Loaded scene does not match the exact pinned object set")
    bpy.context.window.scene = scene
    subjects = [scene.objects[name] for name in sorted(fixture["objects"])]
    if bpy.data.libraries:
        raise ValueError("Linked libraries are not admitted by this corpus")
    declared = {identity_path(item, root) for item in fixture["dependencies"]}
    bindings = []
    for image in bpy.data.images:
        if image.source == "FILE" and image.filepath and not image.packed_file:
            path = Path(bpy.path.abspath(image.filepath)).resolve(strict=True)
            if path not in declared:
                raise ValueError("External image binding was not pinned in fixture dependencies")
            bindings.append({"image": image.name, "path": str(path), "sha256": digest(path)})
    before = source_state(scene, subjects)
    memory_before = process_memory()
    start = time.perf_counter()
    responses, timings = [], []
    for index, request in enumerate(operation["requests"]):
        request_start = time.perf_counter()
        responses.append(_dispatch(request, f"corpus-{index}"))
        timings.append(
            {
                "index": index,
                "command": request["command"],
                "seconds": time.perf_counter() - request_start,
            }
        )
    elapsed = time.perf_counter() - start
    memory_after = process_memory()
    payload = {"responses": responses}
    if any(response["ok"] is not True for response in responses):
        raise AssertionError("Baseline corpus command unexpectedly failed")
    check_observations(payload, operation["expectations"])
    if source_state(scene, subjects) != before:
        raise AssertionError("Corpus command changed protected authored source state")
    control = run_control(operation, scene) if "control" in operation else None
    if source_state(scene, subjects) != before:
        raise AssertionError("Corpus control changed protected source state or leaked owned data")
    return {
        **payload,
        "command_seconds": elapsed,
        "request_timings": timings,
        "memory_before": memory_before,
        "memory_after": memory_after,
        "source_state_sha256": before,
        "source_state_preserved": True,
        "external_image_bindings": bindings,
        "control": control,
    }


def worker(args):
    import bpy

    if not bpy.app.background or bpy.context.preferences.filepaths.use_scripts_auto_execute:
        raise RuntimeError("Worker requires background Blender with auto-execution disabled")
    manifest = validate_manifest(read_manifest(args.manifest), args.root)
    fixture = next(item for item in manifest["fixtures"] if item["id"] == args.fixture)
    operation = next(item for item in fixture["operations"] if item["id"] == args.operation)
    runtime = runtime_identity()
    start = time.perf_counter()
    bpy.ops.wm.open_mainfile(
        filepath=str(identity_path(fixture["source"], args.root)), load_ui=False, use_scripts=False
    )
    load_seconds = time.perf_counter() - start
    result = run_loaded_operation(fixture, operation, args.root)
    validate_manifest(manifest, args.root)
    if runtime_identity() != runtime:
        raise AssertionError("Runtime source bytes changed during the corpus worker")
    result.update(
        schema_version="1.0",
        fixture_id=fixture["id"],
        fixture_version=fixture["version"],
        operation=operation["id"],
        file_load_seconds=load_seconds,
        startup_to_worker_entry_seconds=(SCRIPT_ENTRY_NS - int(os.environ["FW_CORPUS_START_NS"]))
        / 1e9
        if "FW_CORPUS_START_NS" in os.environ
        else None,
        source_files_preserved=True,
        manifest_sha256=digest(args.manifest),
        runtime=runtime,
        blender={
            "version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode(),
            "threads": bpy.context.scene.render.threads,
            "autoexec_enabled": bpy.context.preferences.filepaths.use_scripts_auto_execute,
        },
        host={
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
    )
    write_new(args.worker_output, result)


def active_blender_processes():
    """Conservative Windows process-name guard; never closes a user process."""
    if platform.system() != "Windows":
        return {"status": "unavailable", "processes": None}
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    processes = [
        row[1]
        for row in csv.reader(io.StringIO(result.stdout))
        if len(row) > 1 and row[0].lower() == "blender.exe"
    ]
    return {"status": "measured", "processes": processes}


def process_cpu_identity(pid):
    """Read creation identity and CPU counters; never suspend or terminate a process."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        path, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())

        def ticks(value):
            return value.dwLowDateTime | value.dwHighDateTime << 32

        return {
            "pid": pid,
            "creation_ticks_100ns": ticks(creation),
            "image_path": path.value,
            "cpu_seconds": (ticks(kernel_time) + ticks(user_time)) / 10_000_000,
        }
    finally:
        kernel.CloseHandle(handle)


def idle_process_snapshot(allowed_pids):
    inventory = active_blender_processes()
    if inventory["status"] != "measured":
        if allowed_pids:
            raise RuntimeError(
                "Explicit idle PID allowance needs supported Windows process counters"
            )
        return []
    active = {int(pid) for pid in inventory["processes"]}
    if active - set(allowed_pids):
        raise RuntimeError("An unlisted Blender process is active; coordinate the timing window")
    if set(allowed_pids) - active:
        raise RuntimeError(
            "An allowed idle process exited; its original identity cannot be verified"
        )
    return [process_cpu_identity(pid) for pid in sorted(active)]


def idle_cpu_evidence(before, after, maximum):
    if [row["pid"] for row in before] != [row["pid"] for row in after]:
        raise RuntimeError("Allowed idle process identity changed")
    evidence = []
    for first, last in zip(before, after, strict=True):
        if any(first[key] != last[key] for key in ("pid", "creation_ticks_100ns", "image_path")):
            raise RuntimeError("Allowed idle process identity changed")
        delta = last["cpu_seconds"] - first["cpu_seconds"]
        if not 0 <= delta <= maximum:
            raise RuntimeError("Allowed Blender session exceeded the declared idle CPU threshold")
        evidence.append(
            {
                "pid": first["pid"],
                "cpu_seconds_delta": delta,
                "threshold_seconds": maximum,
                "identity_preserved": True,
            }
        )
    return evidence


def run(args):
    manifest = validate_manifest(read_manifest(args.manifest), args.root)
    executable = shutil.which(args.blender)
    if not executable:
        raise ValueError("Blender executable is unavailable")
    if not args.confirm_idle:
        raise ValueError(
            "Use --confirm-idle only after coordinating a quiet host; no sessions are closed"
        )
    runtime = runtime_identity()
    manifest_hash = digest(args.manifest)
    idle_initial = idle_process_snapshot(args.allow_idle_pid)
    run_path = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run_path.mkdir(parents=True, exist_ok=False)
    records = []
    for fixture in manifest["fixtures"]:
        for operation in fixture["operations"]:
            for repeat in range(args.repeats):
                idle_before = idle_process_snapshot(args.allow_idle_pid)
                idle_cpu_evidence(idle_initial, idle_before, args.max_idle_cpu_seconds)
                folder = run_path / fixture["id"] / operation["id"] / str(repeat + 1)
                folder.mkdir(parents=True, exist_ok=False)
                output = folder / "result.json"
                with tempfile.TemporaryDirectory(prefix="framewright-corpus-") as temporary:
                    environment = os.environ.copy()
                    for name in USER_DIRS:
                        directory = Path(temporary) / name
                        directory.mkdir()
                        environment[name] = str(directory)
                    command = [
                        executable,
                        "--background",
                        "--factory-startup",
                        "--disable-autoexec",
                        "--offline-mode",
                        "--threads",
                        str(args.threads),
                        "--python-exit-code",
                        "1",
                        "--python",
                        str(Path(__file__).resolve()),
                        "--",
                        "--worker",
                        "--manifest",
                        str(args.manifest.resolve()),
                        "--root",
                        str(args.root.resolve()),
                        "--fixture",
                        fixture["id"],
                        "--operation",
                        operation["id"],
                        "--worker-output",
                        str(output),
                    ]
                    start = time.perf_counter()
                    environment["FW_CORPUS_START_NS"] = str(time.perf_counter_ns())
                    child = subprocess.run(
                        command,
                        env=environment,
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=args.timeout,
                    )
                    wall = time.perf_counter() - start
                (folder / "blender.log").write_text(
                    child.stdout + "\n" + child.stderr, encoding="utf-8"
                )
                idle_after = idle_process_snapshot(args.allow_idle_pid)
                idle_delta = idle_cpu_evidence(idle_before, idle_after, args.max_idle_cpu_seconds)
                idle_cpu_evidence(idle_initial, idle_after, args.max_idle_cpu_seconds)
                if child.returncode != 0:
                    raise RuntimeError(f"Corpus worker failed: {folder / 'blender.log'}")
                result = json.loads(output.read_text(encoding="utf-8"))
                if result["runtime"] != runtime or result["manifest_sha256"] != manifest_hash:
                    raise AssertionError(
                        "Corpus children did not use one pinned runtime and manifest"
                    )
                records.append(
                    {
                        "fixture": fixture["id"],
                        "operation": operation["id"],
                        "repeat": repeat + 1,
                        "wall_seconds_including_startup": wall,
                        "command_seconds": result["command_seconds"],
                        "file_load_seconds": result["file_load_seconds"],
                        "startup_to_worker_entry_seconds": result[
                            "startup_to_worker_entry_seconds"
                        ],
                        "result": output.relative_to(run_path).as_posix(),
                        "allowed_idle_processes_before": idle_before,
                        "allowed_idle_processes_after": idle_after,
                        "allowed_idle_cpu_evidence": idle_delta,
                        "peak_working_set_bytes": result["memory_after"].get(
                            "peak_working_set_bytes"
                        ),
                        "peak_private_commit_bytes": result["memory_after"].get(
                            "peak_private_commit_bytes"
                        ),
                    }
                )
                print("CORPUS_SAMPLE " + json.dumps(records[-1]), flush=True)
    validate_manifest(manifest, args.root)
    if runtime_identity() != runtime or digest(args.manifest) != manifest_hash:
        raise AssertionError("Runtime, manifest, or fixture bytes changed during corpus run")
    summary = []
    idle_final = idle_process_snapshot(args.allow_idle_pid)
    idle_evidence = idle_cpu_evidence(idle_initial, idle_final, args.max_idle_cpu_seconds)
    for fixture in manifest["fixtures"]:
        for operation in fixture["operations"]:
            samples = [
                row["command_seconds"]
                for row in records
                if row["fixture"] == fixture["id"] and row["operation"] == operation["id"]
            ]
            summary.append(
                {
                    "fixture": fixture["id"],
                    "operation": operation["id"],
                    "command_seconds": {
                        "raw": samples,
                        "median": statistics.median(samples),
                        "minimum": min(samples),
                        "maximum": max(samples),
                    },
                }
            )
    write_new(
        run_path / "report.json",
        {
            "schema_version": "1.0",
            "manifest_sha256": manifest_hash,
            "manifest": manifest,
            "runtime": runtime,
            "samples": records,
            "summary": summary,
            "source_files_preserved": True,
            "performance_isolation": {
                "operator_confirmed_idle": True,
                "sequential_fresh_processes": True,
                "threads_argument": args.threads,
                "unrelated_system_activity_measured": False,
                "storage_cache_flushed": False,
                "allowed_idle_processes_initial": idle_initial,
                "allowed_idle_processes_final": idle_final,
                "allowed_idle_cpu_evidence": idle_evidence,
            },
            "cost": {
                "provider_requests": 0,
                "provider_charge_usd": 0,
                "basis": "No network/provider operation exists in this offline runner",
                "upstream_asset_creation_cost_usd": None,
                "machine_energy_or_amortized_cost_usd": None,
            },
            "limits": [
                "Technical observations, no artist/native acceptance or universal performance threshold",
                "Fresh processes do not imply cold storage: hash checks warm the filesystem cache",
                "Memory peaks are whole-process lifetime values including startup, file load and preservation snapshots; no GPU or per-stage allocation estimate",
                "Host wall minus command/load includes admission, controls, preservation checks and startup; it is not pure startup latency",
                "Protected state covers subject geometry/UV/weights/material graphs/shape keys, transforms, pose channels/actions/drivers, context and datablock identities; not every arbitrary Blender RNA property",
            ],
        },
    )
    print("FRAMEWRIGHT_PRODUCTION_CORPUS " + str(run_path / "report.json"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "benchmarks/production-corpus-v1.json"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/production-corpus")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--confirm-idle", action="store_true")
    parser.add_argument("--allow-idle-pid", action="append", type=int, default=[])
    parser.add_argument("--max-idle-cpu-seconds", type=float, default=0.25)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--fixture")
    parser.add_argument("--operation")
    parser.add_argument("--worker-output", type=Path)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else None
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 10 or not 1 <= args.threads <= 64 or not 10 <= args.timeout <= 600:
        parser.error("repeats1..10, threads1..64 and timeout10..600 are required")
    if (
        len(args.allow_idle_pid) > 16
        or len(set(args.allow_idle_pid)) != len(args.allow_idle_pid)
        or any(pid < 1 for pid in args.allow_idle_pid)
        or not math.isfinite(args.max_idle_cpu_seconds)
        or not 0 <= args.max_idle_cpu_seconds <= 10
    ):
        parser.error("Idle allowance needs unique positive PIDs and CPU threshold0..10seconds")
    worker(args) if args.worker else run(args)


if __name__ == "__main__":
    main()
