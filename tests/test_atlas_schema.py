"""Public atlas requests must expose exact bounded scope before loading Blender."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params
from framewright.workflows import run_workflow

COMMAND = "surfaces.bake_material_atlas"


def payload(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "cabinet-portable-materials",
        "command": COMMAND,
        "params": {"object_names": ["Cabinet", "DoorPivot", "Door"], **changes},
    }


def test_discovery_declares_owned_scene_mutation_and_preview_default():
    entry = next(item for item in command_metadata() if item["name"] == COMMAND)
    assert entry["mutates"] is True
    assert entry["blender_required"] is True
    assert entry["effect"] == "scene"
    assert entry["input_schema"]["required"] == ["object_names"]
    assert entry["input_schema"]["properties"]["dry_run"]["default"] is True
    assert entry["input_schema"]["properties"]["object_names"]["uniqueItems"] is True
    validate_params(COMMAND, payload()["params"])


@pytest.mark.parametrize(
    "changes",
    [
        {"object_names": []},
        {"object_names": ["Cabinet", "Cabinet"]},
        {"object_names": ["x" * 1025]},
        {"object_names": [True]},
        {"object_names": [f"Part{i}" for i in range(65)]},
        {"resolution": True},
        {"resolution": 63},
        {"resolution": 8193},
        {"margin": -1},
        {"margin": 65},
        {"max_memory_mb": 0},
        {"max_evaluated_vertices": 1_000_001},
        {"max_evaluated_triangles": 500_001},
        {"name": ""},
        {"dry_run": "false"},
        {"script": "exec('anything')"},
        {"directory": "C:/unrequested-output"},
        {"overwrite": True},
    ],
)
def test_malformed_request_never_imports_a_backend(changes):
    with patch("framewright.commands.import_module") as loader:
        result = dispatch(payload(**changes))
    assert result["error"]["code"] == "INVALID_REQUEST"
    loader.assert_not_called()


def test_missing_scope_never_imports_a_backend():
    request = payload()
    request["params"] = {}
    with patch("framewright.commands.import_module") as loader:
        result = dispatch(request)
    assert result["error"]["code"] == "INVALID_REQUEST"
    loader.assert_not_called()


def test_dispatch_uses_only_fixed_atlas_adapter():
    request = payload(dry_run=False)
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.bake_material_atlas.return_value = {"source_preserved": True}
        response = dispatch(request)
    assert response["ok"], response
    loader.assert_called_once_with(".material_atlas", "framewright")
    loader.return_value.bake_material_atlas.assert_called_once_with(request["params"])


def test_workflow_can_preview_an_explicit_atlas_step():
    result = run_workflow(
        {
            "run_id": "cabinet-atlas-preview",
            "steps": [{"id": "atlas", "command": COMMAND, "params": payload()["params"]}],
        }
    )
    assert result["dry_run"] is True
