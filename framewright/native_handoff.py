"""Offline static GLB admission and a fixed native-backend protocol.

No bpy/unreal import, network client, shell, arbitrary script or native launch.
The backend is trusted application code; plan JSON cannot select executable code.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import struct
import zlib
from pathlib import Path

MAX_JSON = 8 * 1024 * 1024
MAX_GLB = 64 * 1024 * 1024
MAX_SCALARS = 16_000_000
MAX_IMAGE_PIXELS = 8192 * 8192
MAX_TOTAL_IMAGE_PIXELS = 2 * MAX_IMAGE_PIXELS
HARD_MAX_GLB = 512 * 1024 * 1024
HARD_MAX_TOTAL_IMAGE_PIXELS = 8 * MAX_IMAGE_PIXELS
ENGINE = "5.8.3"
BASIS = {
    "id": "ue58_interchange_gltf_xyz_to_xzy_cm",
    "position": "(x, z, y) * 100",
    "source": "UE 5.8 GLTFCore/Private/GLTF/ConversionUtilities.h ConvertVec3/ConvertQuat; Import/Private/Gltf/InterchangeGltfPrivate.h GltfUnitConversionMultiplier; InterchangeGltfTranslator.cpp ScaleNodeTranslations",
    "scope": "Expected installed-importer basis; actual native parity requires native observations",
}
_PLAN_KEYS = {
    "schema_version",
    "kind",
    "strategy",
    "asset",
    "handoff",
    "source_root",
    "project_root",
    "project",
    "source",
    "inputs",
    "engine",
    "package_root",
    "staging_level",
    "geometry",
    "admission_budgets",
    "basis",
    "warnings",
    "status",
    "plan_sha256",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, f"Invalid {label}")
    return value


def _admission_budgets(max_glb_bytes, max_total_image_pixels):
    """Explicit resource allowances, independent of native authorization."""
    return {
        "max_glb_bytes": _integer(max_glb_bytes, 28, HARD_MAX_GLB, "GLB byte budget"),
        "max_total_image_pixels": _integer(
            max_total_image_pixels, 0, HARD_MAX_TOTAL_IMAGE_PIXELS, "aggregate image pixel budget"
        ),
    }


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Nonfinite JSON value: {value}")


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid UTF-8 JSON") from exc


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path(raw, *, root=None, directory=False):
    _require(isinstance(raw, (str, Path)), "Expected absolute local path")
    text = str(raw)
    _require(not text.startswith(("\\\\", "//")), "UNC/network paths are unsupported")
    path = Path(text)
    _require(
        path.is_absolute() and ".." not in path.parts, "Path must be absolute without traversal"
    )
    _require(":" not in text[len(path.drive) :], "Alternate-stream path is unsupported")
    try:
        for cursor in (path, *path.parents):
            info = cursor.lstat()
            _require(
                not cursor.is_symlink()
                and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "Reparse/symlink paths are unsupported",
            )
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Unavailable path: {path}") from exc
    _require(resolved.is_dir() if directory else resolved.is_file(), "Unexpected path kind")
    if root is not None:
        _require(resolved.is_relative_to(root), "Input path is outside declared root")
    return resolved


def _record(path, expected=None, maximum=2 * 1024**3):
    before = path.stat()
    _require(
        stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "Input file exceeds budget"
    )
    if expected is not None:
        _require(
            isinstance(expected, dict) and type(expected.get("bytes")) is int,
            "Invalid file receipt",
        )
        _require(before.st_size == expected["bytes"], "File path/hash/size differs from receipt")
        maximum = min(maximum, expected["bytes"])
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(min(1024 * 1024, maximum - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= maximum, "Input file exceeds budget during hashing")
            digest.update(block)
    after = path.stat()

    def signature(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns

    _require(signature(before) == signature(after), "Input changed during hashing")
    value = {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}
    if expected is not None:
        _require(value == expected, "File path/hash/size differs from receipt")
    return value


def _read_bounded(path, maximum, expected):
    """Bound allocation and bind exactly parsed bytes to their initial receipt."""
    with path.open("rb") as stream:
        payload = stream.read(maximum + 1)
    _require(len(payload) <= maximum, "Input file exceeds byte budget during read")
    _require(
        len(payload) == expected["bytes"]
        and hashlib.sha256(payload).hexdigest() == expected["sha256"],
        "Parsed input bytes differ from receipt",
    )
    return payload


def _name(value, label):
    _require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", value),
        f"Invalid {label} name",
    )
    return value


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def _matrix(node):
    if "matrix" in node:
        _require(
            not any(k in node for k in ("translation", "rotation", "scale")), "Mixed matrix/TRS"
        )
        values = node["matrix"]
        _require(
            isinstance(values, list) and len(values) == 16 and all(_finite(v) for v in values),
            "Invalid node matrix",
        )
        result = [[values[j * 4 + i] for j in range(4)] for i in range(4)]
    else:
        t, q, s = (
            node.get("translation", [0, 0, 0]),
            node.get("rotation", [0, 0, 0, 1]),
            node.get("scale", [1, 1, 1]),
        )
        for values, count in ((t, 3), (q, 4), (s, 3)):
            _require(
                isinstance(values, list)
                and len(values) == count
                and all(_finite(v) for v in values),
                "Invalid finite TRS",
            )
        _require(
            abs(sum(v * v for v in q) - 1) <= 1e-5 and all(v > 1e-8 for v in s),
            "Nonunit quaternion or unsupported zero/mirrored scale",
        )
        x, y, z, w = q
        rotation = [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
        result = [[rotation[i][j] * s[j] for j in range(3)] + [t[i]] for i in range(3)] + [
            [0, 0, 0, 1]
        ]
    _admit_matrix(result)
    return result


def _admit_matrix(m):
    _require(all(_finite(v) and abs(v) <= 1e9 for row in m for v in row), "Unbounded transform")
    _require(m[3] == [0, 0, 0, 1], "Non-affine transform")
    columns = [[m[i][j] for i in range(3)] for j in range(3)]
    lengths = [math.sqrt(sum(v * v for v in c)) for c in columns]
    _require(all(v > 1e-8 for v in lengths), "Singular transform")
    _require(
        all(
            abs(sum(columns[i][k] * columns[j][k] for k in range(3)))
            <= 1e-6 * lengths[i] * lengths[j]
            for i in range(3)
            for j in range(i)
        ),
        "Sheared hierarchy is unsupported",
    )
    det = sum(
        m[0][i] * (m[1][(i + 1) % 3] * m[2][(i + 2) % 3] - m[1][(i + 2) % 3] * m[2][(i + 1) % 3])
        for i in range(3)
    )
    _require(det > 0, "Mirrored transform is unsupported")


def _native_matrix(m):
    order = [0, 2, 1]
    return [
        [float(m[order[i]][order[j]]) for j in range(3)] + [float(100 * m[order[i]][3])]
        for i in range(3)
    ] + [[0, 0, 0, 1]]


def _png_idat_blocks(payload):
    """Rewalk validated chunk headers without retaining a per-chunk view list."""
    cursor, view = 8, memoryview(payload)
    while cursor < len(payload):
        length = struct.unpack_from(">I", payload, cursor)[0]
        if payload[cursor + 4 : cursor + 8] == b"IDAT":
            end = cursor + 8 + length
            for offset in range(cursor + 8, end, 65536):
                yield view[offset : min(offset + 65536, end)]
        cursor += length + 12


def _image_size(payload, mime, *, remaining_pixels):
    """Bounded container/stream admission, not a JPEG decoder or pixel parity claim."""
    if mime == "image/png":
        _require(payload.startswith(b"\x89PNG\r\n\x1a\n"), "PNG signature mismatch")
        cursor, header, ended = 8, None, False
        seen_idat, closed_idat = False, False
        metadata_seen = set()
        while cursor < len(payload):
            _require(cursor + 12 <= len(payload), "Truncated PNG chunk")
            length = struct.unpack_from(">I", payload, cursor)[0]
            _require(cursor + 12 + length <= len(payload), "PNG chunk exceeds payload")
            kind = payload[cursor + 4 : cursor + 8]
            data = memoryview(payload)[cursor + 8 : cursor + 8 + length]
            crc = struct.unpack_from(">I", payload, cursor + 8 + length)[0]
            _require(zlib.crc32(data, zlib.crc32(kind)) == crc, "PNG CRC mismatch")
            if header is None:
                _require(kind == b"IHDR" and length == 13, "Require PNG IHDR first")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(
                    ">IIBBBBB", data
                )
                _require(
                    0 < width <= 8192 and 0 < height <= 8192 and width * height <= MAX_IMAGE_PIXELS,
                    "Image dimensions exceed budget",
                )
                _require(
                    width * height <= remaining_pixels, "Aggregate image pixel budget exceeded"
                )
                _require(
                    depth in (8, 16)
                    and color in (0, 2, 4, 6)
                    and compression == filtering == interlace == 0,
                    "Require noninterlaced 8/16-bit grayscale/RGB PNG",
                )
                channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
                row_size = 1 + width * channels * depth // 8
                header = (width, height)
            elif kind == b"IHDR":
                raise ValueError("Duplicate PNG IHDR")
            elif kind in (b"PLTE", b"sRGB", b"tRNS"):
                _require(
                    not seen_idat and kind not in metadata_seen,
                    "Duplicate or misplaced PNG color/transparency metadata",
                )
                if kind == b"PLTE":
                    _require(
                        color in (2, 6)
                        and 0 < length <= 768
                        and length % 3 == 0
                        and b"tRNS" not in metadata_seen,
                        "Invalid PNG palette",
                    )
                elif kind == b"sRGB":
                    _require(
                        length == 1 and data[0] in range(4) and b"PLTE" not in metadata_seen,
                        "Invalid PNG sRGB intent/order",
                    )
                else:
                    _require(
                        color in (0, 2) and length == (2 if color == 0 else 6),
                        "Invalid PNG tRNS transparency",
                    )
                    _require(
                        all(
                            value <= (1 << depth) - 1 for (value,) in struct.iter_unpack(">H", data)
                        ),
                        "PNG tRNS sample exceeds bit depth",
                    )
                metadata_seen.add(kind)
            elif kind == b"IDAT":
                _require(not closed_idat, "Nonconsecutive PNG IDAT chunks")
                seen_idat = True
            elif kind == b"IEND":
                _require(length == 0 and seen_idat, "Invalid PNG IEND")
                ended = True
                cursor += length + 12
                break
            else:
                if seen_idat:
                    closed_idat = True
                _require(kind != b"acTL", "Animated PNG is unsupported")
                _require(kind == b"PLTE" or (kind[0] & 32), "Unknown PNG critical chunk")
            cursor += length + 12
        _require(ended and cursor == len(payload), "Incomplete/trailing PNG payload")
        # Bound both input and output chunks. Passing a whole large IDAT while
        # limiting only output repeatedly allocates its huge unconsumed tail.
        # No decoded texture or full scanline allocation is retained.
        decoder, count = zlib.decompressobj(), 0
        expected = row_size * header[1]
        try:
            for block in _png_idat_blocks(payload):
                remaining = block
                while remaining:
                    output = decoder.decompress(remaining, 65536)
                    remaining = decoder.unconsumed_tail
                    _require(count + len(output) <= expected, "PNG decoded byte budget exceeded")
                    first = (-count) % row_size
                    _require(
                        all(output[i] <= 4 for i in range(first, len(output), row_size)),
                        "Invalid PNG scanline filter",
                    )
                    count += len(output)
                    _require(not decoder.unused_data, "Trailing PNG compressed data")
            _require(decoder.eof and count == expected, "Incomplete PNG compressed rows")
        except zlib.error as exc:
            raise ValueError("Invalid PNG compressed stream") from exc
        return header
    _require(mime == "image/jpeg" and payload.startswith(b"\xff\xd8"), "JPEG signature mismatch")
    cursor, size, scans = 2, None, 0
    while cursor < len(payload):
        _require(payload[cursor] == 255, "Invalid JPEG marker")
        while cursor < len(payload) and payload[cursor] == 255:
            cursor += 1
        _require(cursor < len(payload), "Truncated JPEG marker")
        marker = payload[cursor]
        cursor += 1
        if marker == 0xD9:
            _require(
                size is not None and scans > 0 and cursor == len(payload),
                "Incomplete/trailing JPEG payload",
            )
            return size
        _require(
            marker not in (0, 0xD8) and not 0xD0 <= marker <= 0xD7,
            "Unexpected JPEG standalone marker",
        )
        _require(cursor + 2 <= len(payload), "Truncated JPEG segment")
        length = struct.unpack_from(">H", payload, cursor)[0]
        _require(length >= 2 and cursor + length <= len(payload), "JPEG segment exceeds payload")
        segment = memoryview(payload)[cursor + 2 : cursor + length]
        if marker in (0xC0, 0xC2):
            _require(size is None and len(segment) >= 6, "Invalid JPEG frame")
            depth, height, width, channels = struct.unpack_from(">BHHB", segment)
            _require(
                depth == 8 and channels in (1, 3) and len(segment) == 6 + 3 * channels,
                "Unsupported JPEG frame encoding",
            )
            _require(
                0 < width <= 8192 and 0 < height <= 8192 and width * height <= MAX_IMAGE_PIXELS,
                "Image dimensions exceed budget",
            )
            _require(width * height <= remaining_pixels, "Aggregate image pixel budget exceeded")
            size = width, height
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            raise ValueError("Unsupported JPEG frame encoding")
        cursor += length
        if marker == 0xDA:
            _require(
                size is not None and len(segment) >= 4 and len(segment) == 4 + 2 * segment[0],
                "Invalid JPEG scan header",
            )
            scans += 1
            # Skip entropy bytes, stuffed FF00 and restart markers. Entropy decoding
            # is deliberately left to the native image importer, not claimed here.
            while cursor < len(payload):
                if payload[cursor] != 255:
                    cursor += 1
                    continue
                following = cursor + 1
                while following < len(payload) and payload[following] == 255:
                    following += 1
                _require(following < len(payload), "Truncated JPEG entropy marker")
                if payload[following] == 0 or 0xD0 <= payload[following] <= 0xD7:
                    cursor = following + 1
                else:
                    break
    raise ValueError("JPEG end marker missing")


def _inspect_pbr(doc, binary, views, max_total_image_pixels):
    images, textures, samplers = (doc.get(k, []) for k in ("images", "textures", "samplers"))
    for items in (images, textures, samplers):
        _require(isinstance(items, list) and len(items) <= 256, "PBR resource count budget")
    image_rows, pixels = [], 0
    for source in images:
        _require(
            isinstance(source, dict)
            and set(source) <= {"name", "bufferView", "mimeType", "extras"},
            "Only embedded PNG/JPEG image views are supported",
        )
        view = views[_integer(source["bufferView"], 0, len(views) - 1, "image bufferView")]
        _require(
            "byteStride" not in view and "target" not in view, "Invalid image bufferView layout"
        )
        start = view.get("byteOffset", 0)
        payload = binary[start : start + view["byteLength"]]
        width, height = _image_size(
            payload, source["mimeType"], remaining_pixels=max_total_image_pixels - pixels
        )
        pixels += width * height
        image_rows.append(
            {
                "name": source.get("name"),
                "mime_type": source["mimeType"],
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": width,
                "height": height,
            }
        )
    sampler_rows = []
    for source in samplers:
        _require(
            isinstance(source, dict)
            and set(source) <= {"name", "wrapS", "wrapT", "minFilter", "magFilter", "extras"},
            "Unsupported sampler fields",
        )
        row = {
            "wrap_s": source.get("wrapS", 10497),
            "wrap_t": source.get("wrapT", 10497),
            "min_filter": source.get("minFilter"),
            "mag_filter": source.get("magFilter"),
        }
        for key in ("wrap_s", "wrap_t"):
            _require(
                type(row[key]) is int and row[key] in (10497, 33071, 33648), "Invalid texture wrap"
            )
        for key, allowed in (
            ("min_filter", (9728, 9729, 9984, 9985, 9986, 9987)),
            ("mag_filter", (9728, 9729)),
        ):
            _require(
                row[key] is None or type(row[key]) is int and row[key] in allowed,
                "Invalid texture filter",
            )
        sampler_rows.append(row)
    texture_rows = []
    for source in textures:
        _require(
            isinstance(source, dict) and set(source) <= {"name", "source", "sampler", "extras"},
            "Unsupported texture fields",
        )
        index = _integer(source["source"], 0, len(images) - 1, "texture image index")
        sampler = (
            sampler_rows[_integer(source["sampler"], 0, len(sampler_rows) - 1, "sampler index")]
            if "sampler" in source
            else {"wrap_s": 10497, "wrap_t": 10497, "min_filter": None, "mag_filter": None}
        )
        texture_rows.append({"name": source.get("name"), "image": index, "sampler": dict(sampler)})
    return {
        "images": image_rows,
        "textures": texture_rows,
        "materials": [],
        "pixel_content_verified": False,
        "image_validation_scope": "Container structure, bounds, hashes; PNG compressed rows; JPEG entropy is not decoded",
    }


def _material_pbr(material, pbr_resources):
    _require(
        set(material)
        <= {
            "name",
            "pbrMetallicRoughness",
            "emissiveFactor",
            "emissiveTexture",
            "normalTexture",
            "occlusionTexture",
            "alphaMode",
            "alphaCutoff",
            "doubleSided",
            "extras",
        },
        "Unsupported material channel",
    )
    pbr = material.get("pbrMetallicRoughness", {})
    _require(
        isinstance(pbr, dict)
        and set(pbr)
        <= {
            "baseColorFactor",
            "roughnessFactor",
            "metallicFactor",
            "baseColorTexture",
            "metallicRoughnessTexture",
            "extras",
        },
        "Unsupported PBR channel",
    )

    def scalar(value, label, low=0, high=1):
        _require(_finite(value) and low <= value <= high, f"Invalid {label}")
        return float(value)

    def color(value, count, label):
        _require(
            isinstance(value, list)
            and len(value) == count
            and all(_finite(v) and 0 <= v <= 1 for v in value),
            f"Invalid {label}",
        )
        return [float(v) for v in value]

    _require(
        material.get("alphaMode", "OPAQUE") == "OPAQUE",
        "Only opaque material admission is supported",
    )
    _require(type(material.get("doubleSided", False)) is bool, "Invalid doubleSided flag")
    row = {
        "name": material["name"],
        "base_color_factor": color(pbr.get("baseColorFactor", [1, 1, 1, 1]), 4, "PBR color"),
        "roughness_factor": scalar(pbr.get("roughnessFactor", 1), "PBR roughness"),
        "metallic_factor": scalar(pbr.get("metallicFactor", 1), "PBR metallic"),
        "emissive_factor": color(material.get("emissiveFactor", [0, 0, 0]), 3, "emissive factor"),
        "double_sided": material.get("doubleSided", False),
        "bindings": {},
    }
    roles = (
        ("base_color", pbr, "baseColorTexture", "sRGB", {"color": "RGB", "alpha": "A"}),
        (
            "metallic_roughness",
            pbr,
            "metallicRoughnessTexture",
            "linear",
            {"roughness": "G", "metallic": "B"},
        ),
        ("normal", material, "normalTexture", "linear", {"normal": "RGB"}),
        ("occlusion", material, "occlusionTexture", "linear", {"occlusion": "R"}),
        ("emissive", material, "emissiveTexture", "sRGB", {"emissive": "RGB"}),
    )
    for role, owner, key, transfer, channels in roles:
        if key not in owner:
            continue
        source = owner[key]
        extra = {"scale"} if role == "normal" else {"strength"} if role == "occlusion" else set()
        _require(
            isinstance(source, dict) and set(source) <= {"index", "texCoord", "extras"} | extra,
            "Unsupported texture binding",
        )
        texture = _integer(
            source["index"], 0, len(pbr_resources["textures"]) - 1, "texture binding index"
        )
        binding = {
            "texture": texture,
            "image": pbr_resources["textures"][texture]["image"],
            "texcoord": _integer(source.get("texCoord", 0), 0, 1, "texture coordinate set"),
            "transfer": transfer,
            "channels": channels,
        }
        if role == "normal":
            binding.update(
                scale=scalar(source.get("scale", 1), "normal scale", -1e4, 1e4),
                normal_convention="OPENGL",
            )
        if role == "occlusion":
            binding["strength"] = scalar(source.get("strength", 1), "occlusion strength")
        row["bindings"][role] = binding
    return row


def inspect_glb(data, *, max_glb_bytes=MAX_GLB, max_total_image_pixels=MAX_TOTAL_IMAGE_PIXELS):
    """Read indexed static geometry and bounded embedded core PBR metadata.

    Defaults: 64 MiB input, 128 Mi pixels; explicit budgets have bounded ceilings.
    Nodes/accessors remain bounded independently. Bounds use binary positions,
    not untrusted accessor min/max; every triangle index is checked.
    """
    try:
        return _inspect_glb(data, **_admission_budgets(max_glb_bytes, max_total_image_pixels))
    except (KeyError, IndexError, TypeError, struct.error, OverflowError) as exc:
        raise ValueError(f"Malformed static GLB: {exc}") from exc


def _inspect_glb(data, *, max_glb_bytes, max_total_image_pixels):
    _require(
        isinstance(data, bytes) and 28 <= len(data) <= max_glb_bytes, "Invalid GLB byte budget"
    )
    _require(
        struct.unpack_from("<III", data) == (0x46546C67, 2, len(data)), "Invalid GLB header/length"
    )
    cursor, chunks = 12, []
    for expected_kind in (0x4E4F534A, 0x004E4942):
        _require(cursor + 8 <= len(data), "Truncated GLB chunk")
        length, kind = struct.unpack_from("<II", data, cursor)
        _require(kind == expected_kind, "Require JSON then embedded BIN")
        _require(length % 4 == 0 and cursor + 8 + length <= len(data), "Invalid GLB chunk bounds")
        if kind == 0x4E4F534A:
            _require(length <= MAX_JSON, "GLB JSON exceeds budget")
        chunks.append((kind, data[cursor + 8 : cursor + 8 + length]))
        cursor += 8 + length
    _require(cursor == len(data), "Require exactly JSON then embedded BIN; extra chunk forbidden")
    doc, binary = _json(chunks[0][1]), chunks[1][1]
    _require(isinstance(doc, dict) and doc["asset"]["version"] == "2.0", "Require glTF 2.0")
    _require(doc["asset"].get("minVersion", "2.0") == "2.0", "Unsupported required glTF version")
    for unsupported in (
        "animations",
        "skins",
        "cameras",
        "extensionsUsed",
        "extensionsRequired",
    ):
        _require(not doc.get(unsupported), f"Unsupported static-geometry scope: {unsupported}")

    def no_extensions(value, depth=0):
        _require(depth < 32, "GLB JSON nesting exceeds budget")
        if isinstance(value, dict):
            _require(not value.get("extensions"), "GLB extensions are unsupported")
            for v in value.values():
                no_extensions(v, depth + 1)
        elif isinstance(value, list):
            for v in value:
                no_extensions(v, depth + 1)

    no_extensions(doc)
    buffers = doc["buffers"]
    _require(
        len(buffers) == 1 and "uri" not in buffers[0], "Require one embedded buffer without URI"
    )
    declared = _integer(buffers[0]["byteLength"], 1, max_glb_bytes, "buffer bytes")
    _require(declared <= len(binary) <= declared + 3, "Embedded buffer length mismatch")
    views, accessors = doc["bufferViews"], doc["accessors"]
    _require(
        isinstance(views, list)
        and len(views) <= 4096
        and isinstance(accessors, list)
        and len(accessors) <= 4096,
        "Accessor/view budget",
    )
    for view in views:
        _require(
            type(view.get("buffer")) is int and view["buffer"] == 0, "External/invalid buffer view"
        )
        start = _integer(view.get("byteOffset", 0), 0, declared, "view offset")
        length = _integer(view["byteLength"], 1, declared, "view length")
        _require(start + length <= declared, "Buffer view exceeds embedded payload")
    descriptors, work = [], 0
    formats = {
        5120: ("b", 1),
        5121: ("B", 1),
        5122: ("h", 2),
        5123: ("H", 2),
        5125: ("I", 4),
        5126: ("f", 4),
    }
    widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    for a in accessors:
        _require(
            "sparse" not in a and a["componentType"] in formats and a["type"] in widths,
            "Unsupported accessor",
        )
        view = views[_integer(a["bufferView"], 0, len(views) - 1, "bufferView index")]
        _require(view["buffer"] == 0, "External buffer reference")
        code, size = formats[a["componentType"]]
        width = widths[a["type"]]
        count = _integer(a["count"], 1, 6_000_000, "accessor count")
        work += count * width
        _require(work <= MAX_SCALARS, "Accessor work budget exceeded")
        view_start = _integer(view.get("byteOffset", 0), 0, declared, "view offset")
        view_length = _integer(view["byteLength"], 1, declared, "view length")
        offset = _integer(a.get("byteOffset", 0), 0, view_length, "accessor offset")
        stride = _integer(view.get("byteStride", width * size), width * size, 252, "byte stride")
        _require(stride % size == 0 and (view_start + offset) % size == 0, "Misaligned accessor")
        _require(
            view_start + view_length <= declared
            and offset + (count - 1) * stride + width * size <= view_length,
            "Accessor exceeds buffer bounds",
        )
        descriptors.append((view_start + offset, stride, count, "<" + code * width))

    def values(index):
        index = _integer(index, 0, len(accessors) - 1, "accessor index")
        offset, stride, count, fmt = descriptors[index]
        for i in range(count):
            row = struct.unpack_from(fmt, binary, offset + i * stride)
            _require(all(_finite(v) for v in row), "Nonfinite accessor value")
            yield row

    # Include every later position/index decode, even when primitives repeatedly
    # reference the same accessor. The unique-accessor sum alone is not a work bound.
    _require(isinstance(doc["meshes"], list) and 0 < len(doc["meshes"]) <= 512, "Mesh budget")
    decode_work = work
    for mesh in doc["meshes"]:
        _require("weights" not in mesh, "Mesh morph weights are unsupported")
        _require(
            isinstance(mesh["primitives"], list) and 0 < len(mesh["primitives"]) <= 256,
            "Primitive budget",
        )
        for primitive in mesh["primitives"]:
            position = _integer(
                primitive["attributes"]["POSITION"], 0, len(accessors) - 1, "POSITION index"
            )
            index = _integer(primitive["indices"], 0, len(accessors) - 1, "triangle index accessor")
            decode_work += accessors[position]["count"] * 3 + accessors[index]["count"]
            _require(decode_work <= MAX_SCALARS, "Expanded accessor decode work budget exceeded")
    for i in range(len(accessors)):
        for _ in values(i):
            pass
    pbr_resources = _inspect_pbr(doc, binary, views, max_total_image_pixels)
    mats = doc.get("materials", [])
    _require(isinstance(mats, list) and len(mats) <= 256, "Material budget")
    material_names = [_name(m["name"], "material") for m in mats]
    _require(
        len({n.casefold() for n in material_names}) == len(material_names),
        "Duplicate material identity",
    )
    pbr_resources["materials"] = [_material_pbr(material, pbr_resources) for material in mats]
    texture_roles = {}
    for material in pbr_resources["materials"]:
        for role, binding in material["bindings"].items():
            semantics = (binding["transfer"], role == "normal")
            previous = texture_roles.setdefault(binding["texture"], semantics)
            _require(previous == semantics, "One texture has incompatible transfer/normal roles")
    meshes = []
    _require(0 < len(doc["meshes"]) <= 512, "Mesh budget")
    for source in doc["meshes"]:
        triangles, materials = 0, []
        low, high = [math.inf] * 3, [-math.inf] * 3
        _require(0 < len(source["primitives"]) <= 256, "Primitive budget")
        for primitive in source["primitives"]:
            _require(
                primitive.get("mode", 4) == 4 and not primitive.get("targets"),
                "Require static triangles",
            )
            position = _integer(
                primitive["attributes"]["POSITION"], 0, len(accessors) - 1, "POSITION index"
            )
            _require(
                accessors[position]["type"] == "VEC3"
                and accessors[position]["componentType"] == 5126,
                "Require float POSITION",
            )
            count = accessors[position]["count"]
            for semantic, attribute in primitive["attributes"].items():
                allowed = {
                    "POSITION": ("VEC3",),
                    "NORMAL": ("VEC3",),
                    "TANGENT": ("VEC4",),
                    "TEXCOORD_0": ("VEC2",),
                    "TEXCOORD_1": ("VEC2",),
                    "COLOR_0": ("VEC3", "VEC4"),
                }
                _require(semantic in allowed, "Unsupported vertex attribute")
                attribute = _integer(attribute, 0, len(accessors) - 1, "attribute accessor index")
                item = accessors[attribute]
                _require(
                    item["type"] in allowed[semantic] and item["count"] == count,
                    "Attribute type/count mismatch",
                )
                if semantic in {"POSITION", "NORMAL", "TANGENT"}:
                    _require(
                        item["componentType"] == 5126 and not item.get("normalized", False),
                        "Invalid float attribute encoding",
                    )
                else:
                    _require(
                        item["componentType"] == 5126
                        and item.get("normalized", False) is False
                        or item["componentType"] in (5121, 5123)
                        and item.get("normalized") is True,
                        "Invalid UV/color attribute encoding",
                    )
            for p in values(position):
                _require(
                    all(abs(v) <= 1_000_000 for v in p),
                    "POSITION exceeds native staging coordinate budget",
                )
                for axis, value in enumerate((100 * p[0], 100 * p[2], 100 * p[1])):
                    low[axis], high[axis] = min(low[axis], value), max(high[axis], value)
            index = _integer(primitive["indices"], 0, len(accessors) - 1, "triangle index accessor")
            _require(
                accessors[index]["type"] == "SCALAR"
                and accessors[index]["componentType"] in (5121, 5123, 5125)
                and accessors[index]["count"] % 3 == 0
                and not accessors[index].get("normalized", False),
                "Invalid triangle index accessor",
            )
            for (value,) in values(index):
                _require(value < count, "Triangle index out of range")
            triangles += accessors[index]["count"] // 3
            if "material" in primitive:
                material_index = _integer(primitive["material"], 0, len(mats) - 1, "material index")
                name = material_names[material_index]
                for binding in pbr_resources["materials"][material_index]["bindings"].values():
                    _require(
                        f"TEXCOORD_{binding['texcoord']}" in primitive["attributes"],
                        "Material texture references missing primitive UV coordinates",
                    )
                if name not in materials:
                    materials.append(name)
            _require(
                not any(k.startswith(("JOINTS_", "WEIGHTS_")) for k in primitive["attributes"]),
                "Skin attributes unsupported",
            )
        meshes.append({"triangles": triangles, "bounds_cm": [low, high], "materials": materials})
    nodes = doc["nodes"]
    _require(isinstance(nodes, list) and 0 < len(nodes) <= 512, "Node budget")
    names = [_name(n["name"], "node") for n in nodes]
    _require(len({n.casefold() for n in names}) == len(names), "Duplicate node identity")
    parents = {}
    for i, node in enumerate(nodes):
        _require(
            not any(k in node for k in ("skin", "camera", "weights")),
            "Non-static node semantics are unsupported",
        )
        for child in node.get("children", []):
            _integer(child, 0, len(nodes) - 1, "child index")
            _require(child != i and child not in parents, "Cycle/shared hierarchy child")
            parents[child] = i
    _require(len(doc["scenes"]) == 1, "Require one selected scene")
    _integer(doc.get("scene", 0), 0, 0, "selected scene index")
    roots = doc["scenes"][0]["nodes"]
    _require(isinstance(roots, list), "Invalid scene roots")
    for root in roots:
        _integer(root, 0, len(nodes) - 1, "scene root index")
    _require(
        isinstance(roots, list)
        and set(roots) == set(range(len(nodes))) - set(parents)
        and len(roots) == len(set(roots)),
        "Invalid scene roots",
    )
    worlds, visiting = {}, set()

    def world(i):
        _require(i not in visiting, "Cyclic node graph")
        if i in worlds:
            return worlds[i]
        visiting.add(i)
        local = _matrix(nodes[i])
        result = _mul(world(parents[i]), local) if i in parents else local
        _admit_matrix(result)
        worlds[i] = result
        visiting.remove(i)
        return result

    records, referenced = [], set()
    for i, node in enumerate(nodes):
        mesh = node.get("mesh")
        if mesh is not None:
            _integer(mesh, 0, len(meshes) - 1, "mesh index")
            referenced.add(mesh)
        records.append(
            {
                "name": names[i],
                "parent": names[parents[i]] if i in parents else None,
                "mesh": mesh,
                "local_matrix_cm": _native_matrix(_matrix(node)),
                "world_matrix_cm": _native_matrix(world(i)),
            }
        )
    _require(referenced == set(range(len(meshes))), "Unreferenced meshes unsupported")
    return {
        "nodes": records,
        "meshes": meshes,
        "mesh_count": len(meshes),
        "triangles": sum(m["triangles"] for m in meshes),
        "materials": material_names,
        "images": len(pbr_resources["images"]),
        "pbr": pbr_resources,
    }


def compile_plan(
    handoff_path,
    *,
    project_root,
    source_root,
    max_glb_bytes=MAX_GLB,
    max_total_image_pixels=MAX_TOTAL_IMAGE_PIXELS,
):
    """Compile one explicit existing handoff into a deterministic new native proposal."""
    try:
        return _compile_plan(
            handoff_path,
            project_root=project_root,
            source_root=source_root,
            budgets=_admission_budgets(max_glb_bytes, max_total_image_pixels),
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed handoff: {exc}") from exc


def _compile_plan(handoff_path, *, project_root, source_root, budgets):
    game = _path(project_root, directory=True)
    sources = _path(source_root, directory=True)
    path = _path(handoff_path)
    handoff_record = _record(path, maximum=MAX_JSON)
    handoff = _json(_read_bounded(path, MAX_JSON, handoff_record))
    _require(
        handoff["schema_version"] == "1.0" and handoff["kind"] == "offline_sundown_handoff_plan",
        "Unsupported handoff schema",
    )
    kit = _path(handoff["kit"], root=sources, directory=True)
    _require(_path(handoff["target_project"]["root"], directory=True) == game, "Wrong project root")
    project = _path(handoff["target_project"]["project"]["path"], root=game)
    _require(
        project == game / "Source/SundownRunUnreal/SundownRun.uproject",
        "Wrong target project identity",
    )
    project_record = _record(project, handoff["target_project"]["project"], MAX_JSON)
    _require(
        _json(_read_bounded(project, MAX_JSON, project_record))["EngineAssociation"] == "5.8",
        "Unsupported target engine",
    )
    asset = _name(handoff["asset"], "asset")
    root = handoff["proposal"]["package_root"]
    _require(
        isinstance(root, str)
        and re.fullmatch(r"/Game/FramewrightPilots/[A-Za-z][A-Za-z0-9_]{0,63}_[0-9a-f]{12}", root),
        "Invalid owned package root",
    )
    _require(handoff["proposal"]["replace_existing_assets"] is False, "Replacement is forbidden")
    exports = [e for e in handoff["exports"] if e["format"] == "GLB"]
    _require(len(exports) == 1, "Require one explicit GLB export")
    export = exports[0]
    source = _path(export["file"]["path"], root=kit)
    _require(source.suffix.lower() == ".glb", "Require GLB source")
    source_record = _record(source, export["file"], budgets["max_glb_bytes"])
    _require(
        export["settings"]["export_yup"] is True
        and export["settings"]["export_animations"] is False,
        "Wrong GLB coordinate/animation contract",
    )
    _require(handoff["source_metadata"]["units"] == "metres", "Require metre-authored source")
    geometry = inspect_glb(
        _read_bounded(source, budgets["max_glb_bytes"], source_record), **budgets
    )
    source_records = handoff["source_metadata"]["object_records"]
    by_name = {r["name"]: r for r in source_records}
    _require(
        len(by_name) == len(source_records)
        and set(by_name) == set(handoff["source_metadata"]["object_names"]),
        "Source identity mismatch",
    )
    _require(
        {n["name"] for n in geometry["nodes"]} == {"FW_Export_" + n for n in by_name},
        "Actual exported node names differ from source records",
    )
    for n in geometry["nodes"]:
        original = by_name[n["name"].removeprefix("FW_Export_")]
        _require(
            original["type"] == ("MESH" if n["mesh"] is not None else "EMPTY"),
            "Source/export node type mismatch",
        )
        expected_parent = "FW_Export_" + original["parent"] if original["parent"] else None
        _require(n["parent"] == expected_parent, "Source/export hierarchy mismatch")
    inputs = {}
    receipts = handoff["verified_now"]["files"]
    _require(isinstance(receipts, list) and 0 < len(receipts) <= 64, "Input receipt budget")
    _require(
        all(
            isinstance(r, dict) and type(r.get("bytes")) is int and r["bytes"] >= 0
            for r in receipts
        )
        and sum(r["bytes"] for r in receipts) <= 2 * 1024**3,
        "Aggregate input hashing budget exceeded",
    )

    def input_limit(selected):
        if selected == source:
            return budgets["max_glb_bytes"]
        return MAX_JSON if selected in (path, project) else 2 * 1024**3

    for record in [*receipts, handoff["editable_source"], project_record, source_record]:
        selected = _path(record["path"])
        _require(
            selected == project or selected.is_relative_to(kit),
            "Receipt input escapes explicit kit/project",
        )
        actual = _record(selected, record, maximum=input_limit(selected))
        inputs[str(selected)] = actual
    warnings = export.get("warnings", [])
    _require(
        isinstance(warnings, list)
        and len(warnings) <= 128
        and all(isinstance(w, str) and len(w) <= 4096 for w in warnings),
        "Invalid warnings",
    )
    result = {
        "schema_version": "1.1",
        "kind": "framewright_native_static_plan",
        "strategy": "GLB_STATIC_SCENE",
        "asset": asset,
        "handoff": handoff_record,
        "source_root": str(sources),
        "project_root": str(game),
        "project": project_record,
        "source": source_record,
        "inputs": sorted(inputs.values(), key=lambda r: r["path"]),
        "engine": ENGINE,
        "package_root": root,
        "staging_level": root + "/Maps/Staging",
        "geometry": geometry,
        "admission_budgets": budgets,
        "basis": dict(BASIS),
        "warnings": warnings,
        "status": {
            "native_imported": "not_run",
            "cold_verified": "not_run",
            "source_art_reviewed": "not_reviewed",
            "visually_accepted": "not_reviewed",
            "world_placed": "not_run",
            "runtime_bound": "not_run",
        },
    }
    for record in [handoff_record, *inputs.values()]:
        selected = Path(record["path"])
        _record(selected, record, maximum=input_limit(selected))
    result["plan_sha256"] = _hash(result)
    return result


def verify_plan(plan):
    _require(
        isinstance(plan, dict) and set(plan) == _PLAN_KEYS, "Unknown/missing native plan fields"
    )
    _require(
        plan["plan_sha256"] == _hash({k: v for k, v in plan.items() if k != "plan_sha256"}),
        "Native plan digest mismatch",
    )
    budgets = plan["admission_budgets"]
    _require(
        isinstance(budgets, dict) and set(budgets) == {"max_glb_bytes", "max_total_image_pixels"},
        "Unknown/missing native admission budget fields",
    )
    budgets = _admission_budgets(**budgets)
    expected = compile_plan(
        plan["handoff"]["path"],
        project_root=plan["project_root"],
        source_root=plan["source_root"],
        **budgets,
    )
    _require(plan == expected, "Native plan is stale or differs from current source")
    return plan


SURFACE_ROLES = {
    "base_color": "BaseColorTexture",
    "metallic_roughness": "MetallicRoughnessTexture",
    "normal": "NormalTexture",
    "occlusion": "OcclusionTexture",
    "emissive": "EmissiveTexture",
}


def surface_expectation(plan):
    """Expected *observable settings*, never an observation or pixel equivalence proof.

    Filter conversion follows the installed Interchange source: several glTF
    minification modes collapse to TF_DEFAULT, and magFilter has no native mapping.
    Source values remain in the PBR record; this contract does not call that parity.
    """
    pbr = plan["geometry"]["pbr"]
    texture_uses = {}
    materials = []
    for source in pbr["materials"]:
        row = {
            k: source[k]
            for k in (
                "name",
                "base_color_factor",
                "roughness_factor",
                "metallic_factor",
                "emissive_factor",
                "double_sided",
            )
        }
        # Avoid mutable aliases to a verified plan.
        row = _json(_canonical(row))
        row.update(alpha_mode="BLEND_OPAQUE", bindings={})
        for role, binding in source["bindings"].items():
            index = binding["texture"]
            texture_uses[index] = (binding["transfer"], role == "normal")
            sampler = pbr["textures"][index]["sampler"]
            wrap = {10497: 0.0, 33071: 1.0, 33648: 2.0}
            item = {
                "texture": index,
                "texcoord": float(binding["texcoord"]),
                "tiling": [wrap[sampler["wrap_s"]], wrap[sampler["wrap_t"]], 0.0, 0.0],
                "offset_scale": [0.0, 0.0, 1.0, 1.0],
                "rotation": 0.0,
            }
            if role == "normal":
                item["scale"] = binding["scale"]
            elif role == "occlusion":
                item["strength"] = binding["strength"]
            row["bindings"][role] = item
        materials.append(row)
    _require(
        set(texture_uses) == set(range(len(pbr["textures"]))),
        "Native texture observation requires each texture to be material-bound",
    )
    textures = []
    for index, source in enumerate(pbr["textures"]):
        image = pbr["images"][source["image"]]
        name = (
            source["name"]
            or image["name"]
            or f"{Path(plan['source']['path']).stem}_texture_{index}"
        )
        _name(name, "native texture")
        transfer, normal = texture_uses[index]
        sampler = source["sampler"]
        address = {10497: "TA_WRAP", 33071: "TA_CLAMP", 33648: "TA_MIRROR"}
        textures.append(
            {
                "name": name,
                "width": image["width"],
                "height": image["height"],
                "srgb": transfer == "sRGB",
                "normal_green_flip": normal,
                "compression": "TC_NORMALMAP" if normal else "TC_DEFAULT",
                "address_x": address[sampler["wrap_s"]],
                "address_y": address[sampler["wrap_t"]],
                "filter": {9728: "TF_NEAREST", 9985: "TF_BILINEAR", 9987: "TF_TRILINEAR"}.get(
                    sampler["min_filter"], "TF_DEFAULT"
                ),
            }
        )
    _require(
        len({t["name"].casefold() for t in textures}) == len(textures),
        "Native texture labels collide; use distinct exported texture names",
    )
    return {"materials": materials, "textures": textures}


def _same_geometry(expected, actual):
    """Exact identities/counts; 0.001cm absolute matrix/bounds tolerance only."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(expected) == set(actual)
            and all(_same_geometry(v, actual[k]) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(_same_geometry(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if type(expected) is float:
        return _finite(actual) and abs(expected - actual) <= 0.001
    return type(expected) is type(actual) and expected == actual


def _same_surface(expected, actual):
    """Identity/settings comparison with a separate, strict parameter tolerance."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(expected) == set(actual)
            and all(_same_surface(v, actual[k]) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(_same_surface(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if type(expected) is float:
        return _finite(actual) and abs(expected - actual) <= 1e-5
    return type(expected) is type(actual) and expected == actual


def apply_plan(plan, backend, *, dry_run=True, authorized=False, owner=None):
    """Only a trusted fixed backend can execute. No launch or remote code dispatch."""
    _require(
        type(dry_run) is bool and type(authorized) is bool, "Literal boolean controls required"
    )
    verify_plan(plan)
    expected_surfaces = surface_expectation(plan)
    context = backend.context()
    _require(str(_path(context["project"])) == plan["project"]["path"], "Native project mismatch")
    _require(
        context["engine"] == plan["engine"] and context.get("is_playing") is False,
        "Wrong engine or active play session",
    )
    _require(not context["dirty_packages"], "Refuse dirty native packages before level change")
    _require(
        isinstance(context["level"], str)
        and context["level"].startswith("/Game/")
        and context["level"] != plan["staging_level"],
        "Require an existing saved source level",
    )
    _require(not backend.namespace_exists(plan["package_root"]), "Owned namespace already exists")
    result = {
        "schema_version": "1.0",
        "plan_sha256": plan["plan_sha256"],
        "status": "preview",
        "native_verified": False,
        "verification_scope": "Same-process node/parent identities, transforms/bounds within 0.001 cm, triangle counts, material slots and Interchange material/texture settings within 1e-5; not full surface, decoded pixels, sampler equivalence or appearance parity",
        "material_settings_verified": False,
        "surface_geometry_verified": False,
        "material_appearance_verified": False,
        "collision_verified": False,
        "lod_verified": False,
        "cold_verified": False,
        "visually_accepted": False,
        "saved_packages": [],
        "partial_native_state_possible": False,
        "original_level_restored": None,
    }
    if dry_run:
        return result
    _require(
        authorized
        and isinstance(owner, str)
        and 1 <= len(owner) <= 128
        and context.get("owner") == owner
        and context.get("lock_held") is True,
        "Explicit native authorization and matching held owner lock required",
    )
    verify_plan(plan)  # Rehash immediately before the first native mutation.
    try:
        result["partial_native_state_possible"] = True
        backend.create_level(plan["staging_level"])
        backend.import_scene(plan["source"]["path"], plan["package_root"] + "/Assets")
        observed = backend.inspect_import(plan)
        packages = observed["packages"]
        _require(
            isinstance(packages, list)
            and 0 < len(packages) <= 2048
            and len(set(packages)) == len(packages)
            and all(
                isinstance(p, str)
                and p.startswith(plan["package_root"] + "/")
                and ".." not in p
                and "\\" not in p
                for p in packages
            ),
            "Unexpected/empty/out-of-scope imported packages",
        )
        result["observed_packages"] = packages
        _require(
            _same_geometry(
                {k: v for k, v in plan["geometry"].items() if k not in {"pbr", "images"}},
                {k: v for k, v in observed["geometry"].items() if k not in {"pbr", "images"}},
            ),
            "Imported hierarchy/pivot/geometry/material observations do not match",
        )
        result["observed_surfaces"] = observed.get("surfaces")
        _require(
            _same_surface(expected_surfaces, observed.get("surfaces")),
            "Imported material/texture settings do not match source expectations",
        )
        verify_plan(plan)
        backend.save(packages, plan["staging_level"])
        result["saved_packages"] = packages
        verify_plan(plan)
        result.update(
            status="saved",
            saved_packages=packages,
            native_verified=context.get("evidence_kind") == "unreal_live",
            material_settings_verified=context.get("evidence_kind") == "unreal_live",
        )
    except Exception as exc:
        result.update(
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            native_verified=False,
            material_settings_verified=False,
        )
    finally:
        try:
            backend.restore(context["level"])
            result["original_level_restored"] = True
        except Exception as exc:
            result.update(
                status="failed",
                native_verified=False,
                material_settings_verified=False,
                original_level_restored=False,
                restore_error=f"{type(exc).__name__}: {exc}",
            )
    return result
