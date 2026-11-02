"""Declared texture minification must influence atlas padding before allocation."""

from copy import deepcopy

import pytest

from framewright.atlas_plan import parse_atlas_request
from framewright.commands import validate_params


@pytest.mark.parametrize(("level", "margin"), [(0, 8), (1, 8), (2, 12), (3, 24), (4, 48)])
def test_requested_mip_range_raises_implicit_padding_without_mutating_request(level, margin):
    request = {"object_names": ["Hardware", "Body"], "padding_mip_level": level}
    before = deepcopy(request)
    validate_params("surfaces.bake_material_atlas", request)
    result = parse_atlas_request(request)
    assert result["margin"] == margin
    assert result["mip_padding"]["state"] == "planned"
    assert result["mip_padding"]["maximum_mip_level"] == level
    assert result["mip_padding"]["native_filtering_verified"] is False
    assert request == before
    # Entire box-mip + bilinear support, including diagonal chart boundaries,
    # fits inside the conservative integer padding budget at every phase.
    for phase in [0, 0.125, 0.5, 0.875, 1]:
        axis_radius = max(0.5 + phase, 1.5 - phase) * 2**level - 0.5
        assert 2 * axis_radius < result["mip_padding"]["required_margin_px"]


def test_explicit_underpadding_is_refused_instead_of_silently_replaced():
    with pytest.raises(ValueError, match="padding_mip_level.*requires.*24"):
        parse_atlas_request({"object_names": ["Body"], "padding_mip_level": 3, "margin": 4})
    assert (
        parse_atlas_request({"object_names": ["Body"], "padding_mip_level": 3, "margin": 32})[
            "margin"
        ]
        == 32
    )


@pytest.mark.parametrize("value", [True, None, 3.0, -1, 14])
def test_schema_and_core_reject_invalid_mip_requests(value):
    request = {"object_names": ["Body"], "padding_mip_level": value}
    with pytest.raises(ValueError):
        parse_atlas_request(request)
    with pytest.raises(ValueError):
        validate_params("surfaces.bake_material_atlas", request)


def test_padding_contract_does_not_overrun_existing_memory_layout_or_margin_limits():
    for params in [
        {"padding_mip_level": 5},
        {"padding_mip_level": 4, "resolution": 64},
        {"padding_mip_level": 3, "resolution": 73},
        {"padding_mip_level": 4, "resolution": 8192},
    ]:
        with pytest.raises(ValueError):
            parse_atlas_request({"object_names": ["Body"], **params})


def test_omitted_contract_preserves_legacy_margin_and_reports_unverified_filtering():
    result = parse_atlas_request({"object_names": ["Body"], "margin": 4})
    assert result["margin"] == 4
    assert result["mip_padding"]["state"] == "not_requested"
    assert result["mip_padding"]["native_filtering_verified"] is False
