"""Container topology checks are bounded and do not claim to decode compressed pixels."""

import io
import struct

import pytest

from framewright import exr
from tests.test_exr_intake import attribute, header

LINES = (1, 1, 1, 16, 32, 16, 32, 32, 32, 256)


def container(compression=0, height=35, reverse=False, extra=b""):
    data = header(width=3, height=height, compression=compression, extra=extra)
    if reverse:
        data = data.replace(
            attribute("lineOrder", "lineOrder", b"\0"), attribute("lineOrder", "lineOrder", b"\1")
        )
    block = LINES[compression]
    chunks = {
        y: struct.pack(
            "<ii", y, (size := 3 * 6 * min(block, height - y) if compression == 0 else 7)
        )
        + b"\0" * size
        for y in range(0, height, block)
    }
    offset = len(data) + 8 * len(chunks)
    offsets = {}
    order = sorted(chunks, reverse=reverse)
    for y in order:
        offsets[y] = offset
        offset += len(chunks[y])
    return bytearray(
        data
        + b"".join(struct.pack("<Q", offsets[y]) for y in sorted(chunks))
        + b"".join(chunks[y] for y in order)
    )


def verify(data):
    metadata = exr.inspect_header(bytes(data))
    return exr.verify_scanline_structure(io.BytesIO(data), metadata, len(data))


@pytest.mark.parametrize("compression", range(10))
@pytest.mark.parametrize("reverse", [False, True])
def test_supported_block_counts_and_rows_in_both_storage_orders(compression, reverse):
    result = verify(container(compression=compression, reverse=reverse))
    assert result["container_structure_verified"]
    assert result["scanline_chunks"] == (35 + LINES[compression] - 1) // LINES[compression]
    assert result["covered_rows"] == 35
    assert result["finite_decoded_buffer_verified"] is False
    assert result["codec_semantics_verified"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated_table",
        "zero_offset",
        "offset_in_header",
        "offset_past_end",
        "aliased_chunk",
        "overlapping_chunk",
        "wrong_row",
        "negative_size",
        "truncated_payload",
        "wrong_uncompressed_size",
    ],
)
def test_invalid_chunk_tables_and_extents_rejected(mutation):
    data = container(height=2)
    start = exr.inspect_header(bytes(data))["header_bytes"]
    first, second = struct.unpack_from("<2Q", data, start)
    if mutation == "truncated_table":
        data = data[: start + 15]
    elif mutation == "zero_offset":
        struct.pack_into("<Q", data, start, 0)
    elif mutation == "offset_in_header":
        struct.pack_into("<Q", data, start, 8)
    elif mutation == "offset_past_end":
        struct.pack_into("<Q", data, start, len(data) + 1)
    elif mutation == "aliased_chunk":
        struct.pack_into("<Q", data, start + 8, first)
    elif mutation == "overlapping_chunk":
        struct.pack_into("<Q", data, start + 8, first + 8)
        struct.pack_into("<ii", data, first + 8, 1, 18)
    elif mutation == "wrong_row":
        struct.pack_into("<i", data, second, 0)
    elif mutation == "negative_size":
        struct.pack_into("<i", data, second + 4, -1)
    elif mutation == "truncated_payload":
        data = data[:-7]
    elif mutation == "wrong_uncompressed_size":
        struct.pack_into("<i", data, second + 4, 17)
    with pytest.raises(ValueError):
        verify(data)


def test_declared_chunk_count_must_match_supported_scanline_geometry():
    data = container(height=2, extra=attribute("chunkCount", "int", struct.pack("<i", 999)))
    with pytest.raises(ValueError):
        verify(data)


def test_header_work_bound_enforced_for_direct_parser_call():
    with pytest.raises(ValueError, match="limit"):
        exr.inspect_header(header(extra=attribute("huge", "string", b"x" * (1024 * 1024))))


def test_structure_validator_never_reads_pixel_payloads():
    data = container(compression=0, height=65536)
    metadata = exr.inspect_header(bytes(data[: 1024 * 1024]))

    class CountingStream(io.BytesIO):
        read_bytes = 0

        def read(self, size=-1):
            value = super().read(size)
            self.read_bytes += len(value)
            return value

    stream = CountingStream(data)
    result = exr.verify_scanline_structure(stream, metadata, len(data))
    assert result["scanline_chunks"] == 65536
    assert stream.read_bytes == 65536 * 16
