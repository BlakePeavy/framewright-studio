"""Measure bounded mesh, skinned-rig and collection-instance Blender workloads."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import blender_adapter, mesh_diagnostics, production_assets, rigging  # noqa: E402
from framewright.core import PROFILES, validate_scene  # noqa: E402
from scripts.benchmark_process_performance import process_memory  # noqa: E402


def measure(function, repeats):
    before = process_memory()
    function()  # Warm-up: exclude first-use imports/caches from steady timings.
    samples = []
    for _ in range(repeats):
        gc.collect()
        start = time.perf_counter_ns()
        value = function()
        samples.append((time.perf_counter_ns() - start) / 1e6)
        del value
    after_timing = process_memory()
    gc.collect()
    tracemalloc.start()
    try:
        value = function()
        _, peak = tracemalloc.get_traced_memory()
        del value
    finally:
        tracemalloc.stop()
    return {
        "milliseconds": samples,
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "python_peak_traced_bytes": peak,
        "memory_measurement_separate_from_timing": True,
        "process_memory_before": before,
        "process_memory_after_timing": after_timing,
        "process_memory_after_python_trace": process_memory(),
    }


def grid_scene(columns, rows):
    scene = bpy.data.scenes.new(f"FW_Benchmark_{columns * rows * 2}")
    mesh = bpy.data.meshes.new(scene.name + "_Mesh")
    vertices = [
        (10 * x / columns, 10 * y / rows, 0.05 * math.sin(x / columns * math.tau))
        for y in range(rows + 1)
        for x in range(columns + 1)
    ]
    faces = []
    for y in range(rows):
        for x in range(columns):
            index = y * (columns + 1) + x
            faces.append((index, index + 1, index + columns + 2, index + columns + 1))
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    layer = mesh.uv_layers.new(name="GridUV")
    for loop in mesh.loops:
        point = mesh.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = (point.x / 10, point.y / 10)
    obj = bpy.data.objects.new(scene.name, mesh)
    scene.collection.objects.link(obj)
    return scene, obj


def rig_instance_scene():
    """16 animated joints, 10k skinned triangles, 100 shared 1k-triangle instances."""
    from mathutils import Quaternion

    scene, skin = grid_scene(125, 40)
    scene.name = "FW_Benchmark_RigInstances"
    skin.name = "FW_Benchmark_Skin"
    bpy.context.window.scene = scene
    data = bpy.data.armatures.new("FW_Benchmark_Skeleton")
    rig = bpy.data.objects.new("FW_Benchmark_Rig", data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    previous = None
    for index in range(16):
        bone = data.edit_bones.new(f"Joint{index:02d}")
        bone.head, bone.tail = (5, index * 0.625, 0), (5, (index + 1) * 0.625, 0)
        bone.parent = previous
        bone.use_connect = previous is not None
        previous = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    skin.parent = rig
    skin.modifiers.new("BenchmarkSkin", "ARMATURE").object = rig
    groups = [skin.vertex_groups.new(name=bone.name) for bone in data.bones]
    for vertex in skin.data.vertices:
        position = min(15.0, max(0.0, vertex.co.y / 10 * 15))
        lower = math.floor(position)
        fraction = position - lower
        groups[lower].add([vertex.index], 1 - fraction, "REPLACE")
        if fraction and lower < 15:
            groups[lower + 1].add([vertex.index], fraction, "REPLACE")
    for frame, amount in ((1, 0), (13, 1), (25, 0)):
        for index, bone in enumerate(rig.pose.bones):
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Quaternion((1, 0, 0), 0.035 * math.sin(index + 0.5) * amount)
            bone.keyframe_insert("rotation_quaternion", frame=frame)
    scene.frame_start, scene.frame_end = 1, 25
    scene.render.fps = 24
    temporary_scene, instance_source = grid_scene(25, 20)
    collection = bpy.data.collections.new("FW_Benchmark_SharedInstanceSource")
    collection.objects.link(instance_source)
    bpy.data.scenes.remove(temporary_scene)
    for index in range(100):
        instance = bpy.data.objects.new(f"FW_Benchmark_Instance{index:03d}", None)
        instance.instance_type = "COLLECTION"
        instance.instance_collection = collection
        instance.location = ((index % 10) * 12, (index // 10) * 12, 0)
        scene.collection.objects.link(instance)
    scene.frame_set(13)
    bpy.context.view_layer.update()
    return scene, skin, rig


DATA_KINDS = ("objects", "scenes", "collections", "meshes", "armatures", "actions")


def fixture_state():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in DATA_KINDS}


def clear_fixture(before, original_scene):
    bpy.context.window.scene = original_scene
    for kind in DATA_KINDS:
        for item in list(getattr(bpy.data, kind)):
            if item.as_pointer() not in before[kind]:
                getattr(bpy.data, kind).remove(item, do_unlink=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "performance")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--fixture", choices=("all", "grid_10k", "grid_100k", "rig_instances"), default="all"
    )
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        parser.error("Run this benchmark in a dedicated background Blender process")
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be between 1 and 10")
    run = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run.mkdir(parents=True, exist_ok=False)
    source_paths = [
        Path(__file__),
        ROOT / "framewright/blender_adapter.py",
        ROOT / "framewright/core.py",
        ROOT / "framewright/mesh_diagnostics.py",
        ROOT / "framewright/production_assets.py",
        ROOT / "framewright/rigging.py",
        ROOT / "scripts/benchmark_process_performance.py",
    ]
    report = {
        "schema_version": "1.1",
        "process_id": os.getpid(),
        "selected_fixture": args.fixture,
        "process_memory_at_start": process_memory(),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "blender_version": bpy.app.version_string,
        "blender_build_hash": bpy.app.build_hash.decode(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_processors": os.cpu_count(),
        "repeats": args.repeats,
        "warmups_per_stage": 1,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
        "fixtures": [],
        "limitations": [
            "Synthetic grids and a bounded 16-bone skinned grid with 100 shared instances; not an approved production character/scene",
            "tracemalloc records Python allocations only; OS process memory separately includes native buffers and shared resident pages",
            "Windows OS peaks are since process startup and include fixture creation and tracing overhead; use the process orchestrator for fresh per-fixture peaks",
            "Timed runs disable tracemalloc; memory comes from a separate invocation",
            "One machine/background process; no presented FPS, GPU timings, engine residency or target-hardware acceptance",
            "Intersection work is capped at 2000 triangles and 10000 candidate pairs; topology extraction still visits the full mesh",
            "Concurrent machine activity can affect timings; these are baseline observations, not pass/fail budgets",
        ],
    }
    original_scene = bpy.context.window.scene
    try:
        fixtures = (
            ("grid_10k", "grid_100k", "rig_instances") if args.fixture == "all" else (args.fixture,)
        )
        for fixture in fixtures:
            before = fixture_state()
            if fixture == "rig_instances":
                scene, obj, rig = rig_instance_scene()
            else:
                columns, rows = (125, 40) if fixture == "grid_10k" else (250, 200)
                scene, obj = grid_scene(columns, rows)
            bpy.context.window.scene = scene
            bpy.context.view_layer.update()
            snapshot = blender_adapter.capture_scene()
            triangles = sum(item.triangle_count for item in snapshot.objects)
            assert triangles == (100_000 if fixture == "grid_100k" else 10_000)
            diagnostic_params = {
                "object_name": obj.name,
                "evaluated": True,
                "max_triangles": 2000,
                "max_pairs": 10000,
                "open_boundary_allowed": True,
            }
            row = {
                "fixture": fixture,
                "name": scene.name,
                "objects": len(scene.objects),
                "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons),
                "triangles": triangles,
                "snapshot_extraction": measure(blender_adapter.capture_scene, args.repeats),
                "pure_preflight_rules": measure(
                    lambda snapshot=snapshot: validate_scene(snapshot, PROFILES["realtime_high"]),
                    args.repeats,
                ),
                "resource_accounting": measure(
                    lambda: production_assets.scene_resources({}), args.repeats
                ),
            }
            if fixture == "rig_instances":
                resources = production_assets.scene_resources({})
                assert resources["instance_occurrences"] == 100
                assert resources["evaluated_triangles_with_instances"] == 110_000
                assert resources["source_triangles_unique"] == 11_000
                assert resources["unique_mesh_datablocks"] == 2
                params = {
                    "object_name": obj.name,
                    "frame_start": 1,
                    "frame_end": 25,
                    "step": 6,
                    "max_samples": 5,
                    "max_vertices": 6000,
                }
                deformation = rigging.sample_deformation(params)
                assert len(deformation["samples"]) == 5
                assert deformation["samples"][2]["max_edge_ratio"] > 1.0001
                row.update(
                    bones=len(rig.data.bones),
                    resources=resources,
                    deformation_limits=params,
                    deformation_samples=deformation["samples"],
                    five_pose_deformation=measure(
                        lambda params=params: rigging.sample_deformation(params), args.repeats
                    ),
                )
            else:
                baseline = mesh_diagnostics.inspect_mesh(diagnostic_params)
                assert baseline["topology"]["triangles"] == triangles
                assert baseline["coverage"] != "complete"
                row["bounded_evaluated_mesh_diagnostics"] = measure(
                    lambda diagnostic_params=diagnostic_params: mesh_diagnostics.inspect_mesh(
                        diagnostic_params
                    ),
                    args.repeats,
                )
                row.update(
                    diagnostic_limits=diagnostic_params,
                    intersection_coverage=baseline["intersections"],
                )
            report["fixtures"].append(row)
            print("PERFORMANCE_FIXTURE " + json.dumps(row), flush=True)
            clear_fixture(before, original_scene)
    finally:
        bpy.context.window.scene = original_scene
    report["process_memory_at_finish"] = process_memory()
    destination = run / "baseline.json"
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("FRAMEWRIGHT_PERFORMANCE_BASELINE " + str(destination), flush=True)


if __name__ == "__main__":
    main()
