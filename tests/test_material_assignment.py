"""Material-assignment command inputs fail before Blender access."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_schema, needs_scene_save


def request(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "assign",
        "command": "surfaces.assign_material",
        "params": {"object_name": "Mesh", "material_name": "PBR", "slot_indices": [0], **changes},
    }


def test_discovered_assignment_schema_and_scene_persistence():
    schema = command_schema("surfaces.assign_material")
    assert schema["properties"]["slot_indices"]["uniqueItems"] is True
    assert not needs_scene_save(request())
    assert needs_scene_save(request(dry_run=False))
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.assign_material.return_value = {"dry_run": True}
        result = dispatch(request())
        assert result["ok"], result
        loader.assert_called_once_with(".material_assignment", "framewright")


@pytest.mark.parametrize(
    "changes",
    [
        {"slot_indices": []},
        {"slot_indices": [0, 0]},
        {"slot_indices": [True]},
        {"slot_indices": [-1]},
        {"slot_indices": [128]},
        {"slot_indices": [0.0]},
        {"slot_indices": list(range(129))},
        {"dry_run": 0},
        {"object_name": ""},
        {"material_name": ""},
        {"python": "run()"},
    ],
)
def test_invalid_assignment_requests_reject_before_import(changes):
    with patch("framewright.commands.import_module") as loader:
        result = dispatch(request(**changes))
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_REQUEST"
        loader.assert_not_called()


@pytest.mark.parametrize("missing", ["object_name", "material_name", "slot_indices"])
def test_assignment_requires_each_name_and_explicit_slot_selection(missing):
    value = request()
    del value["params"][missing]
    with patch("framewright.commands.import_module") as loader:
        assert dispatch(value)["error"]["code"] == "INVALID_REQUEST"
        loader.assert_not_called()
