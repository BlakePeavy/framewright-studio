"""The evidence validator must reject estimates, mixed processes and lost inputs."""

from copy import deepcopy

import pytest

from scripts.test_texture_memory import verify


def receipt():
    rows = []
    for index, stage in enumerate(("before_recipe", "after_recipe", "after_render")):
        size = (index + 1) * 1024**2
        rows.append(
            {
                "stage": stage,
                "elapsed_seconds": float(index),
                "memory": {
                    "status": "measured",
                    "api": "GetProcessMemoryInfo/PROCESS_MEMORY_COUNTERS_EX",
                    "process_id": 123,
                    "working_set_bytes": size,
                    "peak_working_set_bytes": size,
                    "private_commit_bytes": size,
                    "peak_private_commit_bytes": size,
                },
            }
        )
    return {
        "recipe": {"maps": [{"width": 8192, "height": 8192} for _ in range(3)]},
        "render": {"device": "CPU"},
        "performance": {
            "checkpoints": rows,
            "source_hashes_preserved": True,
            "gpu_memory": "not_measured",
        },
    }


def test_report_summary_keeps_growth_and_peak_distinct():
    data = receipt()
    data["performance"]["checkpoints"][-1]["memory"]["private_commit_bytes"] = 2 * 1024**2
    before = deepcopy(data)
    result = verify(data)
    assert result["peak_private_commit_mib"] == 3
    assert result["private_commit_growth_mib"] == 1
    assert data == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "estimated"),
        ("process_id", 124),
        ("private_commit_bytes", float("nan")),
        ("peak_private_commit_bytes", 1),
    ],
)
def test_fabricated_or_inconsistent_counter_fields_fail(field, value):
    data = receipt()
    data["performance"]["checkpoints"][-1]["memory"][field] = value
    with pytest.raises(AssertionError):
        verify(data)


def test_missing_stage_or_unpreserved_inputs_fail():
    for mutation in ("stage", "source"):
        data = receipt()
        if mutation == "stage":
            data["performance"]["checkpoints"].pop()
        else:
            data["performance"]["source_hashes_preserved"] = False
        with pytest.raises(AssertionError):
            verify(data)
