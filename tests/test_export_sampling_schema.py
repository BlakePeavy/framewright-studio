"""Fractional animation export has explicit bounded sampling parameters."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params


def params(**changes):
    return {
        "object_names": ["Skin", "Rig"],
        "directory": "C:/exports",
        "include_animation": True,
        **changes,
    }


@pytest.mark.parametrize("substeps,budget", [(1, 1), (4, 4096), (64, 65536)])
def test_explicit_animation_sampling_contract(substeps, budget):
    validate_params(
        "asset.export", params(animation_substeps=substeps, max_animation_samples=budget)
    )


def test_sampling_defaults_are_discoverable():
    entry = next(row for row in command_metadata() if row["name"] == "asset.export")
    schema = entry["input_schema"]["properties"]
    assert schema["animation_substeps"]["default"] == 1
    assert schema["max_animation_samples"]["default"] == 16384


@pytest.mark.parametrize(
    "changes",
    [
        {"animation_substeps": 0},
        {"animation_substeps": 65},
        {"animation_substeps": True},
        {"animation_substeps": 1.5},
        {"max_animation_samples": 0},
        {"max_animation_samples": 65537},
        {"max_animation_samples": False},
        {"max_animation_samples": "100"},
    ],
)
def test_invalid_sampling_is_rejected_before_exporter_import(changes):
    with patch("framewright.commands.import_module") as loader:
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "bad-sampling",
                "command": "asset.export",
                "params": params(**changes),
            }
        )
    assert response["error"]["code"] == "INVALID_REQUEST"
    loader.assert_not_called()
