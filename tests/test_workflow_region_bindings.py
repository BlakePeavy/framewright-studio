"""Structured result bindings validate before execution and again with real data."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from framewright.workflows import clear_run_cache, run_workflow


def region():
    return {
        "id": "sole",
        "object_name": "Skin",
        "topology_sha256": "a" * 64,
        "triangles": [{"index": 0, "vertices": [0, 1, 2]}],
    }


def plan(binding="region", **changes):
    selected = {
        "region": [{"$ref": "describe.result.region"}],
        "regions": {"$ref": "describe.result.regions"},
        "digest": [{**region(), "topology_sha256": {"$ref": "describe.result.digest"}}],
    }[binding]
    return {
        "run_id": "structured-region-binding",
        "steps": [
            {
                "id": "describe",
                "command": "contacts.describe_region",
                "params": {
                    "object_name": "Skin",
                    "region_id": "sole",
                    "sample_time": 1,
                    "vertex_indices": [0, 1, 2],
                },
            },
            {
                "id": "inspect",
                "command": "contacts.inspect_regions",
                "params": {
                    "surface_name": "Ground",
                    "regions": selected,
                    "frame_start": 1,
                    "frame_end": 3,
                },
            },
        ],
        **changes,
    }


@pytest.fixture(autouse=True)
def empty_replay_cache():
    clear_run_cache()
    yield
    clear_run_cache()


@pytest.mark.parametrize("binding", ["region", "regions", "digest"])
def test_preview_accepts_structured_and_fixed_length_bindings_without_executing(binding):
    with patch("framewright.commands.import_module") as loader:
        result = run_workflow(plan(binding))
    assert result["status"] == "validated"
    loader.assert_not_called()


@pytest.mark.parametrize("binding", ["region", "regions", "digest"])
def test_actual_dispatch_receives_complete_detached_bound_data(binding):
    original = region()
    description = {"region": original, "regions": [original], "digest": "a" * 64}

    def inspect(params):
        assert params["regions"] == [original]
        params["regions"][0]["triangles"][0]["vertices"][0] = 999
        return {"counts": {"crossing": 1}}

    inspected = Mock(side_effect=inspect)
    modules = {
        ".region_description": SimpleNamespace(describe_region=lambda params: description),
        ".region_contacts": SimpleNamespace(inspect_regions=inspected),
    }
    with patch(
        "framewright.commands.import_module", side_effect=lambda name, package: modules[name]
    ):
        result = run_workflow(plan(binding, dry_run=False))
    assert result["status"] == "completed", result
    assert original == region()
    assert result["steps"][0]["response"]["result"] == description
    inspected.assert_called_once()


@pytest.mark.parametrize(
    "replacement",
    [
        {},
        {**region(), "topology_sha256": "a" * 63},
        {**region(), "triangles": [{"index": 0, "vertices": [True, 1, 2]}]},
        {**region(), "unexpected": "untrusted upstream output"},
        [],
    ],
)
def test_actual_bound_result_is_revalidated_before_target_adapter_import(replacement):
    module = SimpleNamespace(describe_region=lambda params: {"region": deepcopy(replacement)})
    with patch("framewright.commands.import_module", return_value=module) as loader:
        result = run_workflow(plan(dry_run=False))
    assert result["status"] == "failed", result
    assert result["steps"][1]["response"]["error"]["code"] == "INVALID_REQUEST"
    loader.assert_called_once_with(".region_description", "framewright")


def test_binding_placeholder_does_not_hide_invalid_literal_siblings():
    payload = plan(dry_run=False)
    payload["steps"][1]["params"]["frame_start"] = "not a frame"
    with patch("framewright.commands.import_module") as loader, pytest.raises(ValueError):
        run_workflow(payload)
    loader.assert_not_called()
