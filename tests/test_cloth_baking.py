"""Bounded AI-facing cloth-bake command validation."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, needs_scene_save


def request(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "bake",
        "command": "secondary.bake_cloth",
        "params": {"object_name": "OwnedCloth", "modifier_name": "Framewright Cloth", **changes},
    }


def test_bake_is_explicit_scene_mutation_and_defaults_to_preview():
    entries = {item["name"]: item for item in command_metadata()}
    entry = entries["secondary.bake_cloth"]
    assert entry["mutates"] and entry["blender_required"] and entry["effect"] == "scene"
    assert not needs_scene_save(request())
    assert needs_scene_save(request(dry_run=False))
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.bake_cloth.return_value = {"dry_run": True}
        assert dispatch(request())["ok"]
        loader.assert_called_once_with(".cloth_baking", "framewright")


@pytest.mark.parametrize(
    "changes",
    [
        {"object_name": ""},
        {"modifier_name": ""},
        {"max_frames": 0},
        {"max_frames": 513},
        {"max_vertices": 50001},
        {"max_vertices": True},
        {"max_memory_mb": 0},
        {"max_memory_mb": 4097},
        {"max_memory_mb": 1.5},
        {"dry_run": "false"},
        {"script": "bake_all()"},
        {"directory": "C:/arbitrary"},
    ],
)
def test_invalid_bake_params_reject_before_blender_import(changes):
    with patch("framewright.commands.import_module") as loader:
        result = dispatch(request(**changes))
        assert result["error"]["code"] == "INVALID_REQUEST"
        loader.assert_not_called()


@pytest.mark.parametrize("missing", ["object_name", "modifier_name"])
def test_bake_requires_explicit_proxy_and_modifier(missing):
    value = request()
    del value["params"][missing]
    with patch("framewright.commands.import_module") as loader:
        assert dispatch(value)["error"]["code"] == "INVALID_REQUEST"
        loader.assert_not_called()
