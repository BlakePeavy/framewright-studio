"""Fresh-process normal-inspection timing and whole-process memory, without rendering."""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARCHIVE_SHA = "87a8d969a3cd0c40c3373b1803da466bd3ea031abb3c57682fc46809ca36aed0"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_identity():
    paths = sorted((ROOT / "framewright").glob("*.py")) + [
        Path(__file__),
        ROOT / "scripts/benchmark_process_performance.py",
        ROOT / "scripts/benchmark_production_corpus.py",
    ]
    files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for path in paths]
    return {
        "files": files,
        "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
    }


def retained_oracle(path):
    if digest(path) != ARCHIVE_SHA:
        raise ValueError("Baseline requires the exact verified 0.5 archive")
    with zipfile.ZipFile(path) as archive:
        source = archive.read("baking.py").decode()
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_image_evidence"
    )
    namespace = {"array": array}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "verified_0_5_baking.py", "exec"),
        namespace,
    )
    return namespace["_image_evidence"]


def validate_runs(rows, resolution, repeats, runtime_sha):
    if len(rows) != repeats * 2 or len({row["process_id"] for row in rows}) != len(rows):
        raise ValueError(
            "Measurements require distinct fresh processes and exact repetition counts"
        )
    expected_pixels = rows[0]["source_pixels_before"]
    expected_result = rows[0]["expected_outcome"]
    for row in rows:
        memory = row["memory_after"]
        if (
            row["implementation"] not in {"retained_0_5", "chunked"}
            or row["resolution"] != [resolution, resolution]
            or row["runtime_sha256"] != runtime_sha
            or row["source_pixels_before"] != expected_pixels
            or row["source_pixels_after"] != expected_pixels
            or row["outcome"] != expected_result
            or row["expected_outcome"] != expected_result
            or type(row["elapsed_seconds"]) not in (int, float)
            or not math.isfinite(row["elapsed_seconds"])
            or row["elapsed_seconds"] <= 0
            or memory.get("status") != "measured"
            or memory.get("process_id") != row["process_id"]
            or any(
                type(memory.get(key)) is not int or memory[key] <= 0
                for key in ("peak_working_set_bytes", "peak_private_commit_bytes")
            )
        ):
            raise ValueError(
                "Measurement lacks matching pixels, outcomes, runtime, time or OS memory"
            )
    summary = {}
    for name in ("retained_0_5", "chunked"):
        group = [row for row in rows if row["implementation"] == name]
        if len(group) != repeats:
            raise ValueError("Each implementation requires the declared number of repeats")
        summary[name] = {
            "seconds": [row["elapsed_seconds"] for row in group],
            "median_seconds": statistics.median(row["elapsed_seconds"] for row in group),
            "median_peak_working_set_bytes": statistics.median(
                row["memory_after"]["peak_working_set_bytes"] for row in group
            ),
            "median_peak_private_commit_bytes": statistics.median(
                row["memory_after"]["peak_private_commit_bytes"] for row in group
            ),
        }
    return summary


def write_new(path, value):
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, allow_nan=False)


def worker(args):
    import bpy
    import numpy as np

    from framewright.baking import _image_evidence
    from scripts.benchmark_process_performance import process_memory

    if not bpy.app.background or bpy.context.preferences.filepaths.use_scripts_auto_execute:
        raise RuntimeError("Use background factory-startup Blender with autoexec disabled")
    runtime = runtime_identity()
    baseline = retained_oracle(args.oracle)
    function = baseline if args.implementation == "retained_0_5" else _image_evidence
    before_ids = set(bpy.data.images)
    image = bpy.data.images.new(
        "OwnedInspectionBenchmark",
        args.resolution,
        args.resolution,
        float_buffer=True,
        is_data=True,
    )
    try:
        size = args.resolution**2
        values = np.empty((size, 4), dtype=np.float32)
        pattern = np.array([[0.5, 0.5, 1, 1], [0.6, 0.5, 0.99, 1]], dtype=np.float32)
        values.reshape(-1, 2, 4)[:] = pattern
        image.pixels.foreach_set(values.ravel())
        del values
        gc.collect()

        def pixel_hash():
            copy = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(copy)
            return hashlib.sha256(memoryview(copy)).hexdigest()

        before = pixel_hash()
        memory_before = process_memory()
        start = time.perf_counter()
        result = function(image)
        elapsed = time.perf_counter() - start
        memory_after = process_memory()
        after = pixel_hash()
        expected = {
            "valid_normal_pixels": size,
            "valid_normal_fraction": 1.0,
            "channel_ranges": [
                float(pattern[1, 0]) - float(pattern[0, 0]),
                0.0,
                float(pattern[0, 2]) - float(pattern[1, 2]),
            ],
            "detail_present": True,
        }
        if result != expected or before != after or runtime_identity() != runtime:
            raise RuntimeError(
                "Inspection changed source pixels/runtime or disagreed with the independent golden"
            )
        payload = {
            "implementation": args.implementation,
            "resolution": [args.resolution, args.resolution],
            "elapsed_seconds": elapsed,
            "process_id": os.getpid(),
            "outcome": result,
            "expected_outcome": expected,
            "source_pixels_before": before,
            "source_pixels_after": after,
            "runtime_sha256": runtime["sha256"],
            "memory_before": memory_before,
            "memory_after": memory_after,
            "oracle_archive_sha256": ARCHIVE_SHA,
            "blender": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "processor": platform.processor(),
            "scope": "One actual owned RGBA float image; inspection only; includes pixel readback, excludes fixture/hash setup and all baking/rendering",
        }
    finally:
        bpy.data.images.remove(image)
    if set(bpy.data.images) != before_ids:
        raise RuntimeError("Benchmark image cleanup changed pre-existing image identities")
    payload["owned_image_cleanup"] = True
    write_new(args.worker_output, payload)


def host(args):
    from scripts.benchmark_production_corpus import (
        USER_DIRS,
        idle_cpu_evidence,
        idle_process_snapshot,
    )

    retained_oracle(args.oracle)
    runtime = runtime_identity()
    idle_before = idle_process_snapshot(args.allow_idle_pid)
    folder = args.output / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    rows = []
    try:
        for repeat in range(args.repeats):
            # Alternate ordering across pairs to avoid always placing one method first.
            order = ("retained_0_5", "chunked") if repeat % 2 == 0 else ("chunked", "retained_0_5")
            for implementation in order:
                idle_cpu_evidence(
                    idle_before,
                    idle_process_snapshot(args.allow_idle_pid),
                    args.max_idle_cpu_seconds,
                )
                name = f"{repeat + 1}-{implementation}"
                output = folder / (name + ".json")
                with tempfile.TemporaryDirectory(
                    prefix="framewright-normal-inspection-"
                ) as directory:
                    environment = dict(
                        os.environ,
                        OMP_NUM_THREADS="1",
                        OPENBLAS_NUM_THREADS="1",
                        MKL_NUM_THREADS="1",
                    )
                    for key in USER_DIRS:
                        target = Path(directory) / key
                        target.mkdir()
                        environment[key] = str(target)
                    command = [
                        str(args.blender),
                        "--background",
                        "--factory-startup",
                        "--disable-autoexec",
                        "--offline-mode",
                        "--threads",
                        "1",
                        "--python-exit-code",
                        "1",
                        "--python",
                        str(Path(__file__).resolve()),
                        "--",
                        "--worker",
                        "--implementation",
                        implementation,
                        "--resolution",
                        str(args.resolution),
                        "--oracle",
                        str(args.oracle.resolve()),
                        "--worker-output",
                        str(output.resolve()),
                    ]
                    print(f"START {name} actual {args.resolution}x{args.resolution}", flush=True)
                    with (folder / (name + ".log")).open("x", encoding="utf-8") as log:
                        completed = subprocess.run(
                            command,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            env=environment,
                            timeout=600,
                            check=False,
                        )
                    if completed.returncode:
                        raise RuntimeError(
                            f"Worker {name} failed with exit{completed.returncode}; see its log"
                        )
                row = json.loads(output.read_text())
                rows.append(row)
                if runtime_identity() != runtime or digest(args.oracle) != ARCHIVE_SHA:
                    raise RuntimeError("Measured source files changed during benchmark")
                print(f"DONE {name}: {row['elapsed_seconds']:.6f}s", flush=True)
        idle_after = idle_process_snapshot(args.allow_idle_pid)
        summary = validate_runs(rows, args.resolution, args.repeats, runtime["sha256"])
        report = {
            "schema_version": "1.0",
            "resolution": [args.resolution, args.resolution],
            "repeats": args.repeats,
            "runtime": runtime,
            "oracle_archive_sha256": digest(args.oracle),
            "runs": rows,
            "summary": summary,
            "observed_median_speed_ratio": summary["retained_0_5"]["median_seconds"]
            / summary["chunked"]["median_seconds"],
            "idle_blender_processes": idle_cpu_evidence(
                idle_before, idle_after, args.max_idle_cpu_seconds
            ),
            "limits": [
                "Timing includes full pixel readback and inspection, not whole baking/rendering",
                "Whole-process OS peaks include startup, synthetic image allocation and hash readback; they are not isolated algorithm allocation peaks",
                "No GPU measurement; synthetic alternating valid normals, not a representative artist-approved map corpus",
                "Coordinated window limits other Blender CPU activity; unrelated OS/background activity is not fully controlled",
            ],
        }
        write_new(folder / "report.json", report)
    except Exception as error:
        write_new(
            folder / "failure.json",
            {"error": str(error), "completed_runs": rows, "runtime": runtime},
        )
        raise
    print("NORMAL_INSPECTION_BENCHMARK_OK " + str(folder), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--implementation", choices=("retained_0_5", "chunked"))
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--resolution", type=int, default=8192)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--oracle", type=Path, default=ROOT / "dist/framewright_studio-0.5.0.zip")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/normal-inspection-performance"
    )
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--allow-idle-pid", type=int, action="append", default=[])
    parser.add_argument("--max-idle-cpu-seconds", type=float, default=2.0)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    if args.resolution not in (64, 256, 1024, 2048, 8192) or not 1 <= args.repeats <= 10:
        parser.error("Use a supported actual resolution and1..10 repeats")
    if not math.isfinite(args.max_idle_cpu_seconds) or not 0 <= args.max_idle_cpu_seconds <= 10:
        parser.error("Idle CPU allowance must be finite and between0 and10 seconds")
    if args.worker:
        if not args.implementation or not args.worker_output:
            parser.error("Worker requires implementation and output")
        worker(args)
    else:
        if not args.blender or not args.blender.is_file():
            parser.error("Specify the installed Blender executable")
        host(args)


if __name__ == "__main__":
    main()
