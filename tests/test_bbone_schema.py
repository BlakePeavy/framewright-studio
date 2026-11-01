"""B-Bone surface baking requires explicit tolerances and bounded work."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params


def request(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "bbone-contract",
        "command": "animation.bake_bbone_skin",
        "params": {
            "object_name": "Skin",
            "armature_name": "Rig",
            "frame_start": 1,
            "frame_end": 25,
            "max_surface_error_m": 0.001,
            **changes,
        },
    }


def test_discovery_declares_scene_effect_and_preview_default():
    entry = next(row for row in command_metadata() if row["name"] == request()["command"])
    assert entry["effect"] == "scene"
    assert entry["mutates"] and entry["blender_required"]
    assert entry["input_schema"]["properties"]["dry_run"]["default"] is True
    assert "max_surface_error_m" in entry["input_schema"]["required"]
    validate_params(request()["command"], request()["params"])


@pytest.mark.parametrize(
    "changes",
    [
        {"max_surface_error_m": float("nan")},
        {"max_surface_error_m": 0},
        {"max_surface_error_m": 1.01},
        {"frame_start": 1.5},
        {"frame_end": 1_000_001},
        {"max_key_times": 1026},
        {"max_samples": 4098},
        {"max_vertex_samples": 100_000_001},
        {"max_joints": 1025},
        {"max_influences": 33},
        {"max_refinement_depth": 7},
        {"max_samples": True},
        {"max_influences": 0},
        {"dry_run": 0},
        {"step": 2},
        {"object_name": ""},
    ],
)
def test_invalid_request_rejected_before_runtime_import(changes):
    with patch("framewright.commands.import_module") as loader:
        response = dispatch(request(**changes))
    assert response["error"]["code"] == "INVALID_REQUEST"
    loader.assert_not_called()


def test_missing_explicit_surface_tolerance_rejected_before_import():
    payload = request()
    del payload["params"]["max_surface_error_m"]
    with patch("framewright.commands.import_module") as loader:
        response = dispatch(payload)
    assert response["error"]["code"] == "INVALID_REQUEST"
    loader.assert_not_called()


def test_dispatch_uses_only_registered_bbone_handler():
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.bake_bbone_skin.return_value = {"dry_run": True}
        response = dispatch(request())
    assert response["ok"]
    loader.assert_called_once_with(".bbone_baking", "framewright")
    loader.return_value.bake_bbone_skin.assert_called_once_with(request()["params"])
