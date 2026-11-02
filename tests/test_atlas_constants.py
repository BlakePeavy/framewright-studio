"""Constant preservation is explicit and strictly typed at public/core boundaries."""

import pytest

from framewright.atlas_plan import parse_atlas_request
from framewright.commands import command_schema, validate_params


@pytest.mark.parametrize("enabled", [True, False])
def test_constant_policy_is_explicit_and_visible(enabled):
    params = {"object_names": ["Cabinet"], "preserve_material_constants": enabled}
    validate_params("surfaces.bake_material_atlas", params)
    assert parse_atlas_request(params)["preserve_material_constants"] is enabled


def test_default_preserves_single_material_contract():
    assert (
        parse_atlas_request({"object_names": ["Cabinet"]})["preserve_material_constants"] is False
    )
    assert command_schema("surfaces.bake_material_atlas")["properties"][
        "preserve_material_constants"
    ] == {"type": "boolean", "default": False}


@pytest.mark.parametrize("value", [1, 0, "true", None, []])
def test_nonboolean_policy_cannot_change_material_assignment(value):
    params = {"object_names": ["Cabinet"], "preserve_material_constants": value}
    with pytest.raises(ValueError):
        validate_params("surfaces.bake_material_atlas", params)
    with pytest.raises(ValueError):
        parse_atlas_request(params)
