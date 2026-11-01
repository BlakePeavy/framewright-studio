"""Run each bounded benchmark in a fresh Blender process with OS memory counters."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def process_memory():
    """Read this whole process, including native allocations; no GPU estimate."""
    if platform.system() != "Windows":
        return {"status": "unavailable", "reason": "Windows GetProcessMemoryInfo only"}
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    api.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not api.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "status": "measured",
        "api": "GetProcessMemoryInfo/PROCESS_MEMORY_COUNTERS_EX",
        "process_id": os.getpid(),
        "working_set_bytes": counters.WorkingSetSize,
        "peak_working_set_bytes": counters.PeakWorkingSetSize,
        "private_commit_bytes": counters.PrivateUsage,
        "peak_private_commit_bytes": counters.PeakPagefileUsage,
        "page_fault_count": counters.PageFaultCount,
        "scope": "whole_process; peak_since_process_start; working_set_includes_shared_pages",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts" / "process-performance"
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be between 1 and 10")
    executable = shutil.which(args.blender)
    if not executable:
        parser.error("Blender executable was not found")
    run = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": "1.0",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "orchestrator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "isolation": "one fresh factory-startup Blender process and temporary user directories per fixture",
        "memory_interpretation": [
            "Working set is current resident whole-process memory, including shared pages",
            "OS working-set and private-commit peaks include Blender startup, fixture setup and measured work",
            "Per-stage OS peaks are process-lifetime high-water marks, not attributable stage allocation peaks",
            "Python tracemalloc is separate and excludes native buffers; neither metric is GPU memory",
            "Fixed synthetic workloads provide engineering observations, not runtime FPS or universal budgets",
        ],
        "children": [],
    }
    for fixture in ("grid_10k", "grid_100k", "rig_instances"):
        destination = run / fixture
        destination.mkdir()
        with tempfile.TemporaryDirectory(prefix="framewright-benchmark-user-") as temporary:
            environment = os.environ.copy()
            for variable in (
                "BLENDER_USER_CONFIG",
                "BLENDER_USER_SCRIPTS",
                "BLENDER_USER_EXTENSIONS",
                "BLENDER_USER_DATAFILES",
                "BLENDER_USER_RESOURCES",
            ):
                directory = Path(temporary) / variable.lower()
                directory.mkdir()
                environment[variable] = str(directory)
            start = time.perf_counter()
            child = subprocess.run(
                [
                    executable,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(ROOT / "scripts/benchmark_performance.py"),
                    "--",
                    "--output-dir",
                    str(destination),
                    "--repeats",
                    str(args.repeats),
                    "--fixture",
                    fixture,
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=240,
            )
            wall_seconds = time.perf_counter() - start
        (destination / "blender.log").write_text(
            child.stdout + "\n" + child.stderr, encoding="utf-8"
        )
        if child.returncode:
            raise RuntimeError(f"{fixture} failed; inspect {destination / 'blender.log'}")
        marker = "FRAMEWRIGHT_PERFORMANCE_BASELINE "
        paths = [
            Path(line[len(marker) :]).resolve()
            for line in child.stdout.splitlines()
            if line.startswith(marker)
        ]
        if len(paths) != 1 or not paths[0].is_relative_to(destination):
            raise RuntimeError("Benchmark child did not return its owned report path")
        baseline = json.loads(paths[0].read_text(encoding="utf-8"))
        report["children"].append(
            {
                "fixture": fixture,
                "wall_seconds_including_startup": wall_seconds,
                "report": str(paths[0].relative_to(run)),
                "baseline": baseline,
            }
        )
        print(
            "PROCESS_BENCHMARK_CHILD "
            + json.dumps(
                {
                    "fixture": fixture,
                    "wall_seconds": wall_seconds,
                    "memory": baseline["process_memory_at_finish"],
                }
            ),
            flush=True,
        )
    path = run / "process-baseline.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("FRAMEWRIGHT_PROCESS_BASELINE " + str(path), flush=True)


if __name__ == "__main__":
    main()
