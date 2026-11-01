"""Validate real 8K pilot process-memory evidence, separately from estimates."""

import argparse
import json
import math
from pathlib import Path


def verify(receipt):
    performance = receipt["performance"]
    rows = performance["checkpoints"]
    assert [row["stage"] for row in rows] == ["before_recipe", "after_recipe", "after_render"]
    assert performance["source_hashes_preserved"] is True
    assert len(receipt["recipe"]["maps"]) == 3
    assert all(
        (item["width"], item["height"]) == (8192, 8192) for item in receipt["recipe"]["maps"]
    )
    assert receipt["render"]["device"] == "CPU"
    previous_time = -1.0
    process_ids = set()
    for row in rows:
        elapsed = row["elapsed_seconds"]
        assert type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= previous_time
        previous_time = elapsed
        memory = row["memory"]
        assert memory["status"] == "measured"
        assert memory["api"] == "GetProcessMemoryInfo/PROCESS_MEMORY_COUNTERS_EX"
        process_ids.add(memory["process_id"])
        for name in (
            "working_set_bytes",
            "peak_working_set_bytes",
            "private_commit_bytes",
            "peak_private_commit_bytes",
        ):
            assert type(memory[name]) is int and memory[name] > 0
        assert memory["peak_working_set_bytes"] >= memory["working_set_bytes"]
        assert memory["peak_private_commit_bytes"] >= memory["private_commit_bytes"]
    assert len(process_ids) == 1, "Checkpoints must measure the same actual process"
    first, last = rows[0]["memory"], rows[-1]["memory"]
    assert last["peak_working_set_bytes"] >= first["peak_working_set_bytes"]
    assert last["peak_private_commit_bytes"] >= first["peak_private_commit_bytes"]
    assert last["peak_private_commit_bytes"] > first["private_commit_bytes"] + 1024 * 1024
    assert performance["gpu_memory"] == "not_measured"
    return {
        "peak_working_set_mib": last["peak_working_set_bytes"] / 1024**2,
        "peak_private_commit_mib": last["peak_private_commit_bytes"] / 1024**2,
        "private_commit_growth_mib": (last["private_commit_bytes"] - first["private_commit_bytes"])
        / 1024**2,
        "recipe_seconds": rows[1]["elapsed_seconds"] - rows[0]["elapsed_seconds"],
        "scene_and_render_seconds": rows[2]["elapsed_seconds"] - rows[1]["elapsed_seconds"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.receipt.read_text(encoding="utf-8"))), indent=2))
