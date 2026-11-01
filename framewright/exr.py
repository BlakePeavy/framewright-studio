"""Bounded flat OpenEXR data-map header inspection, without a pixel decoder."""

from __future__ import annotations

import math
import struct

COMPRESSION = ("NONE", "RLE", "ZIPS", "ZIP", "PIZ", "PXR24", "B44", "B44A", "DWAA", "DWAB")
SCANLINES_PER_CHUNK = dict(zip(COMPRESSION, (1, 1, 1, 16, 32, 16, 32, 32, 32, 256), strict=True))
MAX_HEADER_BYTES = 1024 * 1024


def inspect_header(data):
    if len(data) > MAX_HEADER_BYTES:
        raise ValueError("EXR header input exceeds the 1 MiB inspection limit")
    if len(data) < 9 or struct.unpack_from("<I", data)[0] != 20000630:
        raise ValueError("EXR magic/header is missing")
    version = struct.unpack_from("<I", data, 4)[0]
    if version & 255 != 2 or version & ~(255 | 0x400):
        raise ValueError(
            "EXR requires version 2 single-part scanline data; deep/tiled/multipart/unknown flags unsupported"
        )
    name_limit = 255 if version & 0x400 else 31

    def name_at(buffer, offset):
        end = buffer.find(b"\0", offset, offset + name_limit + 1)
        if end < 0:
            raise ValueError("EXR name is truncated or exceeds the declared limit")
        try:
            name = buffer[offset:end].decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("EXR metadata names must use supported ASCII names") from None
        return name, end + 1

    attributes, offset = {}, 8
    while True:
        name, offset = name_at(data, offset)
        if not name:
            break
        kind, offset = name_at(data, offset)
        if not kind or name in attributes or len(attributes) >= 128 or offset + 4 > len(data):
            raise ValueError("EXR duplicate/invalid attributes or header limit exceeded")
        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if offset + size > len(data):
            raise ValueError("EXR attribute is truncated or exceeds the 1 MiB header limit")
        attributes[name] = (kind, data[offset : offset + size])
        offset += size

    def required(name, kind, size=None):
        actual, value = attributes.get(name, (None, b""))
        if actual != kind or (size is not None and len(value) != size):
            raise ValueError(f"EXR requires a complete {name} {kind} attribute")
        return value

    window = struct.unpack("<4i", required("dataWindow", "box2i", 16))
    display = struct.unpack("<4i", required("displayWindow", "box2i", 16))
    if window[:2] != (0, 0) or window != display:
        raise ValueError("EXR data maps require matching zero-origin data/display windows")
    width, height = window[2] + 1, window[3] + 1
    if not 1 <= width <= 65536 or not 1 <= height <= 65536:
        raise ValueError("EXR dimensions must be 1..65536 per axis")
    compression = required("compression", "compression", 1)[0]
    if compression >= len(COMPRESSION):
        raise ValueError("Unsupported EXR compression identifier")
    line_order = required("lineOrder", "lineOrder", 1)[0]
    if line_order not in (0, 1):
        raise ValueError("EXR scanlines require increasing/decreasing line order")
    aspect = struct.unpack("<f", required("pixelAspectRatio", "float", 4))[0]
    center = struct.unpack("<2f", required("screenWindowCenter", "v2f", 8))
    screen_width = struct.unpack("<f", required("screenWindowWidth", "float", 4))[0]
    if (
        aspect != 1
        or not all(math.isfinite(value) for value in (*center, screen_width))
        or screen_width <= 0
    ):
        raise ValueError("EXR data maps require square pixels and finite screen-window metadata")
    if "type" in attributes and attributes["type"] != ("string", b"scanlineimage"):
        raise ValueError("EXR part type must be scanlineimage")
    channel_data = required("channels", "chlist")
    channels, types, cursor = [], [], 0
    while True:
        name, cursor = name_at(channel_data, cursor)
        if not name:
            if cursor != len(channel_data):
                raise ValueError("EXR channel list has trailing bytes")
            break
        if name in channels or len(channels) >= 4 or cursor + 16 > len(channel_data):
            raise ValueError(
                "EXR channels are duplicated, truncated or outside the four-channel limit"
            )
        pixel_type, linear, x_sampling, y_sampling = struct.unpack_from(
            "<iB3xii", channel_data, cursor
        )
        if pixel_type not in (1, 2) or linear not in (0, 1) or (x_sampling, y_sampling) != (1, 1):
            raise ValueError("EXR requires full-resolution HALF/FLOAT channels")
        channels.append(name)
        types.append("HALF" if pixel_type == 1 else "FLOAT")
        cursor += 16
    if set(channels) not in ({"Y"}, {"R", "G", "B"}, {"R", "G", "B", "A"}):
        raise ValueError("EXR data maps support Y, RGB or RGBA channels without named layers")
    declared_chunks = None
    if "chunkCount" in attributes:
        declared_chunks = struct.unpack("<i", required("chunkCount", "int", 4))[0]
    return {
        "width": width,
        "height": height,
        "channels": channels,
        "pixel_types": types,
        "compression": COMPRESSION[compression],
        "lossy_compression": compression >= 5,
        "data_window": list(window),
        "line_order": "INCREASING_Y" if line_order == 0 else "DECREASING_Y",
        "declared_chunk_count": declared_chunks,
        "header_bytes": offset,
        "container_structure_verified": False,
        "finite_decoded_buffer_verified": False,
        "codec_semantics_verified": False,
        "scope": "bounded header only; scanline container and finite Blender decode require separate checks",
    }


def verify_scanline_structure(stream, metadata, file_size):
    """Check bounded offset/row/payload extents, never decompress or read pixel payloads.

    Header metadata must come from inspect_header. The offset table is ordered by
    increasing row, even when chunks are physically stored in decreasing order.
    """
    width, height = metadata["width"], metadata["height"]
    block_rows = SCANLINES_PER_CHUNK[metadata["compression"]]
    count = (height + block_rows - 1) // block_rows
    if not 1 <= count <= 65536:
        raise ValueError("EXR scanline chunk count exceeds supported work bounds")
    if metadata["declared_chunk_count"] not in (None, count):
        raise ValueError("EXR declared chunkCount disagrees with scanline geometry")
    start = metadata["header_bytes"]
    table_end = start + count * 8
    if table_end > file_size:
        raise ValueError("EXR scanline offset table is truncated")
    stream.seek(start)
    table = stream.read(count * 8)
    if len(table) != count * 8:
        raise ValueError("EXR scanline offset table is truncated")
    bytes_per_pixel = sum(2 if kind == "HALF" else 4 for kind in metadata["pixel_types"])
    ranges = []
    payload_bytes = 0
    for index, (offset,) in enumerate(struct.iter_unpack("<Q", table)):
        if offset < table_end or offset + 8 > file_size:
            raise ValueError("EXR scanline chunk offset is outside its payload region")
        stream.seek(offset)
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            raise ValueError("EXR scanline chunk header is truncated")
        row, size = struct.unpack("<ii", chunk_header)
        expected_row = index * block_rows
        if row != expected_row:
            raise ValueError(
                "EXR scanline rows are duplicated, missing or inconsistent with the offset table"
            )
        unpacked_size = width * min(block_rows, height - expected_row) * bytes_per_pixel
        if size <= 0 or size > unpacked_size or offset + 8 + size > file_size:
            raise ValueError("EXR scanline pixel payload is truncated or has an invalid size")
        if metadata["compression"] == "NONE" and size != unpacked_size:
            raise ValueError("EXR uncompressed scanline size differs from channel/row geometry")
        ranges.append((offset, offset + 8 + size))
        payload_bytes += size
    ranges.sort()
    if any(right[0] < left[1] for left, right in zip(ranges, ranges[1:], strict=False)):
        raise ValueError("EXR scanline chunks overlap or alias another chunk")
    return {
        "container_structure_verified": True,
        "finite_decoded_buffer_verified": False,
        "codec_semantics_verified": False,
        "scanline_chunks": count,
        "scanlines_per_chunk": block_rows,
        "covered_rows": height,
        "offset_table_bytes": count * 8,
        "referenced_payload_bytes": payload_bytes,
        "scope": "Complete non-overlapping scanline container extents and row coverage; compressed payload semantics are not decoded by this check",
    }
