"""AI region authoring requires explicit identities, time and bounded inputs."""

from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params

COMMAND = "contacts.describe_region"


def request(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "describe-left-sole",
        "command": COMMAND,
        "params": {
            "object_name": "Skin",
            "region_id": "left-sole",
            "sample_time": 1.25,
            "vertex_indices": [0, 1, 2],
            **changes,
        },
    }


def assert_invalid(payload):
    with patch("framewright.commands.import_module") as loader:
        response = dispatch(payload)
    assert response["error"]["code"] == "INVALID_REQUEST", response
    loader.assert_not_called()


def test_discovery_is_read_only_with_explicit_time_and_identity():
    entry = next(row for row in command_metadata() if row["name"] == COMMAND)
    assert entry["effect"] == "read"
    assert not entry["mutates"] and entry["blender_required"]
    assert set(entry["input_schema"]["required"]) == {
        "object_name",
        "region_id",
        "sample_time",
    }
    validate_params(COMMAND, request()["params"])
    group = request()["params"]
    del group["vertex_indices"]
    group["vertex_group"] = "AuthoredSole.L"
    validate_params(COMMAND, group)


@pytest.mark.parametrize(
    "changes",
    [
        {"object_name": ""},
        {"object_name": "x" * 257},
        {"region_id": ""},
        {"region_id": "x" * 65},
        {"sample_time": True},
        {"sample_time": float("nan")},
        {"sample_time": float("inf")},
        {"sample_time": -1_000_000.1},
        {"sample_time": 1_000_000.1},
        {"vertex_indices": [0, 1]},
        {"vertex_indices": [0, 1, True]},
        {"vertex_indices": [0, 1, -1]},
        {"vertex_indices": [0, 1, 1_000_000]},
        {"vertex_indices": [0, 1, 2.0]},
        {"vertex_indices": list(range(65_537))},
        {"vertex_group": ""},
        {"vertex_group": "x" * 257},
        {"expected_topology_sha256": "0" * 63},
        {"expected_topology_sha256": "0" * 65},
        {"max_evaluated_vertices": 0},
        {"max_evaluated_vertices": 1_000_001},
        {"max_evaluated_triangles": 500_001},
        {"max_region_triangles": 16_385},
        {"max_group_entries": 0},
        {"max_group_entries": 2_000_001},
        {"dry_run": True},
        {"surface_name": "UnrequestedGround"},
        {"infer_anatomy": True},
        {"sample_time": "current"},
    ],
)
def test_malformed_inputs_are_refused_before_adapter_import(changes):
    assert_invalid(request(**changes))


@pytest.mark.parametrize("field", ["object_name", "region_id", "sample_time"])
def test_required_authoring_scope_cannot_be_omitted(field):
    payload = request()
    del payload["params"][field]
    assert_invalid(payload)


def test_dispatch_uses_only_the_allowlisted_read_only_adapter():
    params = request(expected_topology_sha256="a" * 64)
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.describe_region.return_value = {"geometric_relations_checked": False}
        response = dispatch(params)
    assert response["ok"], response
    loader.assert_called_once_with(".region_description", "framewright")
    loader.return_value.describe_region.assert_called_once_with(params["params"])
