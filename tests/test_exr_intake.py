"""Bounded EXR metadata admission; header checks never certify pixel decoding."""

import struct

import pytest

from framewright import materials


def attribute(name, kind, payload):
    return name.encode() + b"\0" + kind.encode() + b"\0" + struct.pack("<I", len(payload)) + payload


def header(
    *,
    version=2,
    width=32,
    height=16,
    channels=("B", "G", "R"),
    pixel_type=1,
    sampling=1,
    compression=3,
    extra=b"",
    origin=(0, 0),
):
    window = struct.pack("<4i", origin[0], origin[1], origin[0] + width - 1, origin[1] + height - 1)
    channel_data = (
        b"".join(
            name.encode() + b"\0" + struct.pack("<iB3xii", pixel_type, 0, sampling, sampling)
            for name in channels
        )
        + b"\0"
    )
    return (
        struct.pack("<II", 20000630, version)
        + b"".join(
            (
                attribute("channels", "chlist", channel_data),
                attribute("compression", "compression", bytes([compression])),
                attribute("dataWindow", "box2i", window),
                attribute("displayWindow", "box2i", window),
                attribute("pixelAspectRatio", "float", struct.pack("<f", 1)),
                attribute("lineOrder", "lineOrder", b"\0"),
                attribute("screenWindowCenter", "v2f", struct.pack("<ff", 0, 0)),
                attribute("screenWindowWidth", "float", struct.pack("<f", 1)),
            )
        )
        + extra
        + b"\0"
    )


@pytest.mark.parametrize("channels", [("Y",), ("R", "G", "B"), ("B", "G", "R", "A")])
@pytest.mark.parametrize("pixel_type", [1, 2])
def test_supported_flat_data_header_preserves_channels_and_precision(
    tmp_path, channels, pixel_type
):
    path = tmp_path / "data.exr"
    path.write_bytes(header(channels=channels, pixel_type=pixel_type))
    result = materials.inspect_texture_file(str(path))
    assert (result["width"], result["height"], result["format"]) == (32, 16, "EXR")
    assert result["exr"]["channels"] == list(channels)
    assert result["exr"]["pixel_types"] == ["HALF" if pixel_type == 1 else "FLOAT"] * len(channels)
    assert result["exr"]["finite_decoded_buffer_verified"] is False


@pytest.mark.parametrize(
    "compression,lossy",
    [
        (0, False),
        (1, False),
        (2, False),
        (3, False),
        (4, False),
        (5, True),
        (6, True),
        (7, True),
        (8, True),
        (9, True),
    ],
)
def test_compression_is_explicit_and_lossy_sources_are_not_mislabeled(tmp_path, compression, lossy):
    path = tmp_path / "data.exr"
    path.write_bytes(header(compression=compression))
    result = materials.inspect_texture_file(str(path))
    assert result["exr"]["lossy_compression"] is lossy


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 1},
        {"version": 2 | 0x200},
        {"version": 2 | 0x800},
        {"version": 2 | 0x1000},
        {"version": 2 | 0x2000},
        {"width": 0},
        {"height": 65537},
        {"origin": (1, 0)},
        {"channels": ("Z",)},
        {"channels": ("R", "R", "B")},
        {"channels": ("beauty.R", "beauty.G", "beauty.B")},
        {"pixel_type": 0},
        {"sampling": 2},
        {"compression": 10},
    ],
)
def test_unsupported_or_invalid_exr_is_rejected_before_loading(tmp_path, changes):
    path = tmp_path / "data.exr"
    path.write_bytes(header(**changes))
    with pytest.raises(ValueError):
        materials.inspect_texture_file(str(path))


@pytest.mark.parametrize(
    "data",
    [
        b"not exr",
        header()[:-1],
        header(extra=attribute("dataWindow", "box2i", b"x" * 16)),
        header(extra=attribute("oversized", "string", b"x" * (1024 * 1024))),
    ],
)
def test_truncation_duplicate_and_header_budget_reject(tmp_path, data):
    path = tmp_path / "data.exr"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        materials.inspect_texture_file(str(path))


def test_exr_data_maps_require_budget_for_decoded_and_validation_buffers(tmp_path):
    from tests.test_materials import png

    color = tmp_path / "color.png"
    color.write_bytes(png())
    data = tmp_path / "rough.exr"
    data.write_bytes(header(width=8192, height=8192))
    with pytest.raises(ValueError, match="budget"):
        materials.create_pbr_material(
            {"base_color_path": str(color), "roughness_path": str(data), "max_memory_mb": 1024}
        )
    result = materials.create_pbr_material(
        {"base_color_path": str(color), "roughness_path": str(data), "max_memory_mb": 2305}
    )
    assert result["maps"][1]["color_space"] == "Non-Color"
    assert result["estimated_decoded_bytes"] == 4 * 16 + 8192 * 8192 * 36


def test_base_color_exr_requires_explicit_color_workflow_instead_of_guessing_srgb(tmp_path):
    path = tmp_path / "color.exr"
    path.write_bytes(header())
    with pytest.raises(ValueError, match="base.color|Base.color"):
        materials.create_pbr_material({"base_color_path": str(path)})
