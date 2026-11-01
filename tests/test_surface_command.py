"""Public contract for explicit sole/prop markers against an evaluated surface."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, needs_scene_save


def request(params):
    return {
        "schema_version": "1.0",
        "request_id": "surface-contract",
        "command": "animation.surface_contacts",
        "params": params,
    }


def valid():
    return {
        "surface_name": "Floor",
        "markers": [
            {"id": "left_heel", "object_name": "Rig", "bone": "foot.L", "position": [0, 0, 0]}
        ],
        "frame_start": 1,
        "frame_end": 25,
    }


def test_read_only_command_is_discovered_and_dispatches_to_static_handler():
    entries = {item["name"]: item for item in command_metadata()}
    assert "animation.surface_contacts" in entries
    entry = entries["animation.surface_contacts"]
    assert not entry["mutates"]
    assert entry["blender_required"]
    assert entry["effect"] == "read"
    assert not needs_scene_save(request(valid()))
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.inspect_surface_contacts.return_value = {"markers": []}
        result = dispatch(request(valid()))
        assert result["ok"], result
        loader.assert_called_once_with(".contact_analysis", "framewright")
        loader.return_value.inspect_surface_contacts.assert_called_once_with(valid())


@pytest.mark.parametrize(
    "override",
    [
        {"markers": []},
        {"markers": [{"id": "x", "object_name": "Foot", "position": [0, 0]}]},
        {"markers": [{"id": "x", "object_name": "Foot", "position": [0, 0, float("nan")]}]},
        {"markers": [{"id": "x", "object_name": "Foot", "position": [0, 0, 0], "code": "run()"}]},
        {"max_samples": 4097},
        {"step": True},
        {"substeps": 9},
        {"search_distance": 0},
        {"minimum_up_dot": -0.1},
    ],
)
def test_invalid_surface_requests_are_rejected_before_adapter_import(override):
    with patch("framewright.commands.import_module") as loader:
        result = dispatch(request(dict(valid(), **override)))
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_REQUEST"
        loader.assert_not_called()
