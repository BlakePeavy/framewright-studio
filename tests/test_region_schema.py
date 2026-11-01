"""Regional geometry queries require explicit topology and bounded sampled work."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params

COMMAND = "contacts.inspect_regions"


def request(**changes):
    return {
        "schema_version": "1.0",
        "request_id": "regional-relations",
        "command": COMMAND,
        "params": {
            "surface_name": "Ground",
            "regions": [
                {
                    "id": "left-sole",
                    "object_name": "Skin",
                    "topology_sha256": "0" * 64,
                    "triangles": [{"index": 0, "vertices": [0, 1, 2]}],
                }
            ],
            "frame_start": 1,
            "frame_end": 61,
            **changes,
        },
    }


def assert_invalid(payload):
    with patch("framewright.commands.import_module") as loader:
        response = dispatch(payload)
    assert response["error"]["code"] == "INVALID_REQUEST", response
    loader.assert_not_called()


def test_discovery_declares_read_only_blender_query_with_explicit_identity():
    entry = next(row for row in command_metadata() if row["name"] == COMMAND)
    assert entry["effect"] == "read"
    assert entry["mutates"] is False and entry["blender_required"] is True
    assert set(entry["input_schema"]["required"]) == {
        "surface_name",
        "regions",
        "frame_start",
        "frame_end",
    }
    validate_params(COMMAND, request()["params"])


@pytest.mark.parametrize(
    "changes",
    [
        {"surface_name": ""},
        {"regions": []},
        {"regions": request()["params"]["regions"] * 9},
        {"frame_start": 1.5},
        {"frame_end": 1_000_001},
        {"substeps": True},
        {"substeps": 9},
        {"max_samples": 4097},
        {"max_evaluated_vertices": 1_000_001},
        {"max_surface_triangles": 500_001},
        {"max_region_triangles": 16_385},
        {"distance_epsilon_m": float("nan")},
        {"distance_epsilon_m": 0},
        {"distance_epsilon_m": 0.0011},
        {"proximity_distance_m": float("inf")},
        {"proximity_distance_m": 1.1},
        {"max_candidate_visits": 50_000_001},
        {"max_pair_checks": 10_000_001},
        {"max_examples": -1},
        {"max_examples": 1001},
        {"max_pair_checks": 0},
        {"dry_run": True},
        {"step": 2},
    ],
)
def test_invalid_budgets_and_implicit_scope_are_refused_before_import(changes):
    assert_invalid(request(**changes))


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"object_name": ""},
        {"topology_sha256": "0" * 63},
        {"triangles": []},
        {"triangles": [{"index": -1, "vertices": [0, 1, 2]}]},
        {"triangles": [{"index": 0, "vertices": [0, 1]}]},
        {"triangles": [{"index": 0, "vertices": [0, True, 2]}]},
        {"triangles": [{"index": 0, "vertices": [0, 1, 2], "guess": True}]},
        {"infer_anatomy": True},
    ],
)
def test_nested_region_identity_is_strict(change):
    payload = deepcopy(request())
    payload["params"]["regions"][0].update(change)
    assert_invalid(payload)


@pytest.mark.parametrize("field", ["surface_name", "regions", "frame_start", "frame_end"])
def test_required_query_scope_cannot_be_omitted(field):
    payload = request()
    del payload["params"][field]
    assert_invalid(payload)


def test_dispatch_uses_only_the_allowlisted_read_only_adapter():
    with patch("framewright.commands.import_module") as loader:
        loader.return_value.inspect_regions.return_value = {"coverage": "complete"}
        response = dispatch(request(max_examples=0))
    assert response["ok"]
    loader.assert_called_once_with(".region_contacts", "framewright")
    loader.return_value.inspect_regions.assert_called_once_with(request(max_examples=0)["params"])
