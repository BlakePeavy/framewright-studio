"""Admission controls for an owned multi-part procedural-material atlas."""

from copy import deepcopy

import pytest

from framewright.atlas_plan import parse_atlas_request


def test_defaults_keep_explicit_part_order_and_do_not_modify_request():
    request = {"object_names": ["DoorPivot", "Door", "Cabinet"]}
    before = deepcopy(request)
    result = parse_atlas_request(request)
    assert result["object_names"] == request["object_names"]
    assert result["object_names"] is not request["object_names"]
    assert result["dry_run"] is True
    assert result["name"] == "FW_MaterialAtlas"
    assert result["resolution"] == 1024
    assert result["margin"] == 8
    assert result["max_evaluated_vertices"] == 250_000
    assert result["max_evaluated_triangles"] == 100_000
    assert result["map_roles"] == ["base_color", "roughness", "metallic", "normal"]
    assert result["estimated_image_working_bytes"] == 136 * 1024**2
    assert result["memory_components"] == {
        "rgba_float_image_equivalents": 8,
        "estimated_image_buffers_bytes": 128 * 1024**2,
        "bounded_encoding_scratch_bytes": 8 * 1024**2,
    }
    assert (
        result["memory_estimate_scope"] == "owned_images_and_estimated_validation_packing_scratch"
    )
    assert result["native_process_memory_bounded"] is False
    assert request == before


@pytest.mark.parametrize(
    "params",
    [
        None,
        [],
        {},
        {"object_names": "Cabinet"},
        {"object_names": []},
        {"object_names": ["Cabinet", "Cabinet"]},
        {"object_names": [""]},
        {"object_names": [True]},
        {"object_names": ["x" * 1025]},
        {"object_names": [f"Part{i}" for i in range(65)]},
        {"object_names": ["Cabinet"], "output": "overwrite.blend"},
        {"object_names": ["Cabinet"], "maps": ["base_color"]},
    ],
)
def test_requires_explicit_bounded_unique_scope_and_known_contract(params):
    with pytest.raises(ValueError):
        parse_atlas_request(params)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resolution", True),
        ("resolution", 64.0),
        ("resolution", 63),
        ("resolution", 8193),
        ("margin", -1),
        ("margin", 65),
        ("margin", False),
        ("max_memory_mb", 0),
        ("max_memory_mb", 32769),
        ("max_memory_mb", 1.5),
        ("max_evaluated_vertices", 0),
        ("max_evaluated_vertices", 1_000_001),
        ("max_evaluated_triangles", 0),
        ("max_evaluated_triangles", 500_001),
        ("max_evaluated_triangles", True),
        ("dry_run", 1),
        ("name", ""),
        ("name", "x" * 49),
        ("name", "Bad\nName"),
        ("name", None),
    ],
)
def test_rejects_invalid_type_range_or_nonprintable_output_name(field, value):
    with pytest.raises(ValueError):
        parse_atlas_request({"object_names": ["Cabinet"], field: value})


@pytest.mark.parametrize("margin", [32, 33, 64])
def test_padding_cannot_consume_the_entire_atlas(margin):
    with pytest.raises(ValueError, match="margin"):
        parse_atlas_request({"object_names": ["Cabinet"], "resolution": 64, "margin": margin})


def test_image_budget_refuses_large_request_before_native_allocation():
    with pytest.raises(ValueError, match="memory"):
        parse_atlas_request({"object_names": ["Cabinet"], "resolution": 8192})
    result = parse_atlas_request(
        {"object_names": ["Cabinet"], "resolution": 8192, "max_memory_mb": 8200}
    )
    assert result["estimated_image_working_bytes"] == 8 * 1024**3 + 8 * 1024**2
    assert result["native_process_memory_bounded"] is False


def test_small_or_non_power_of_two_atlases_remain_configurable():
    result = parse_atlas_request(
        {
            "object_names": ["Cabinet"],
            "name": "Atlas été",
            "resolution": 73,
            "max_memory_mb": 9,
            "margin": 0,
            "dry_run": False,
        }
    )
    assert result["name"] == "Atlas été"
    assert result["resolution"] == 73
    assert result["dry_run"] is False
    assert result["estimated_image_working_bytes"] <= 9 * 1024**2


def test_memory_boundary_is_not_rounded_down():
    with pytest.raises(ValueError, match="memory"):
        parse_atlas_request({"object_names": ["Cabinet"], "resolution": 91, "max_memory_mb": 9})
    assert (
        parse_atlas_request({"object_names": ["Cabinet"], "resolution": 90, "max_memory_mb": 9})[
            "estimated_image_working_bytes"
        ]
        <= 9 * 1024**2
    )
