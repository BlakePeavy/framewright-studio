"""Explicit standalone PBR recipes with bounded image metadata preflight."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import threading
import zlib
from pathlib import Path
from uuid import uuid4

from .exr import inspect_header as inspect_exr_header
from .exr import verify_scanline_structure

MAX_HEADER_BYTES = 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
_MAPS = (
    ("base_color", "base_color_path", "sRGB"),
    ("roughness", "roughness_path", "Non-Color"),
    ("metallic", "metallic_path", "Non-Color"),
    ("normal", "normal_path", "Non-Color"),
)


def _dimensions(width, height):
    if not 1 <= width <= 65536 or not 1 <= height <= 65536:
        raise ValueError("Texture dimensions must be 1..65536 pixels per axis")
    return width, height


def _png_dimensions(header):
    if (
        len(header) < 33
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[8:16] != b"\x00\x00\x00\rIHDR"
    ):
        raise ValueError("PNG needs a complete first IHDR chunk")
    if zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]:
        raise ValueError("PNG IHDR checksum is invalid")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", header[16:29]
    )
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if (
        depth not in depths.get(color, ())
        or compression != 0
        or filtering != 0
        or interlace not in (0, 1)
    ):
        raise ValueError("Unsupported or invalid PNG IHDR encoding")
    return _dimensions(width, height)


def _jpeg_dimensions(header):
    if header[:2] != b"\xff\xd8":
        raise ValueError("JPEG start marker is missing")
    offset = 2
    while offset < len(header):
        if header[offset] != 0xFF:
            raise ValueError("Malformed JPEG header marker")
        while offset < len(header) and header[offset] == 0xFF:
            offset += 1
        if offset >= len(header):
            break
        marker = header[offset]
        offset += 1
        if marker in (0xD9, 0xDA):
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(header):
            break
        length = struct.unpack(">H", header[offset : offset + 2])[0]
        if length < 2 or offset + length > len(header):
            break
        if marker in (0xC0, 0xC1, 0xC2):
            body = header[offset + 2 : offset + length]
            if len(body) < 6:
                raise ValueError("Incomplete JPEG frame header")
            precision, height, width, channels = struct.unpack(">BHHB", body[:6])
            if precision != 8 or channels not in (1, 3) or len(body) != 6 + 3 * channels:
                raise ValueError("Only 8-bit grayscale/RGB JPEG frame encoding is supported")
            return _dimensions(width, height)
        offset += length
    raise ValueError("JPEG dimensions missing or truncated within the 1 MiB header limit")


def _file_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def inspect_texture_file(path: str, *, verify_exr_structure=False) -> dict:
    """Read/hash a local file; header validity is not full decoder certification."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("Texture path must be an absolute local PNG/JPEG/EXR path")
    if path.startswith(("\\\\", "//")) or not Path(path).is_absolute():
        raise ValueError(
            "Texture paths must be absolute local paths; UNC/network paths are unsupported"
        )
    source = Path(path).resolve()
    if str(source).startswith(("\\\\", "//")):
        raise ValueError("Texture source resolves to an unsupported UNC path")
    if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".exr"} or not source.is_file():
        raise ValueError("Texture must be an existing PNG/JPEG/EXR file")
    exr = None
    with source.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_FILE_BYTES:
            raise ValueError("Texture must be a regular file no larger than 1 GiB")
        header = stream.read(MAX_HEADER_BYTES)
        if source.suffix.lower() == ".png":
            width, height = _png_dimensions(header)
            image_format = "PNG"
        elif source.suffix.lower() == ".exr":
            exr = inspect_exr_header(header)
            if verify_exr_structure:
                exr.update(verify_scanline_structure(stream, exr, before.st_size))
            width, height = exr["width"], exr["height"]
            image_format = "EXR"
        else:
            width, height = _jpeg_dimensions(header)
            image_format = "JPEG"
        stream.seek(0)
        digest = hashlib.sha256()
        total = 0
        while block := stream.read(1024 * 1024):
            total += len(block)
            if total > MAX_FILE_BYTES:
                raise ValueError("Texture grew beyond the 1 GiB file limit")
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (
        total != before.st_size
        or _file_identity(before) != _file_identity(after)
        or _file_identity(after) != _file_identity(source.stat())
    ):
        raise ValueError("Texture source changed during metadata inspection")
    return {
        "path": str(source),
        "sha256": digest.hexdigest(),
        "width": width,
        "height": height,
        "format": image_format,
        "file_bytes": total,
        **({"exr": exr} if exr else {}),
    }


def _request(params):
    allowed = {
        "name",
        "normal_convention",
        "max_memory_mb",
        "dry_run",
        *(field for _, field, _ in _MAPS),
    }
    if not isinstance(params, dict) or set(params) - allowed or "base_color_path" not in params:
        raise ValueError("PBR recipe requires base_color_path and known optional fields")
    name = params.get("name", "FW_PBR")
    if not isinstance(name, str) or not 1 <= len(name) <= 48 or not name.isprintable():
        raise ValueError("name must contain 1..48 printable characters")
    if params.get("normal_convention", "OPENGL") != "OPENGL":
        raise ValueError(
            "Only OPENGL tangent normals have supported portable semantics; convert DirectX maps explicitly before intake"
        )
    budget = params.get("max_memory_mb", 512)
    if type(budget) is not int or not 1 <= budget <= 32768:
        raise ValueError("max_memory_mb must be an integer from 1 to 32768")
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be a boolean")
    maps = [
        {"role": role, "color_space": color_space, **inspect_texture_file(params[field])}
        for role, field, color_space in _MAPS
        if field in params
    ]
    if any(item["role"] == "base_color" and item["format"] == "EXR" for item in maps):
        raise ValueError(
            "EXR base color requires an explicit linear-color workflow; this recipe accepts EXR data maps only"
        )
    estimate = sum(
        item["width"] * item["height"] * (36 if item["format"] == "EXR" else 16) for item in maps
    )
    if estimate > budget * 1024 * 1024:
        raise ValueError("Estimated RGBA-float decoded image memory exceeds max_memory_mb budget")
    return {
        "schema_version": "1.0",
        "name": name,
        "dry_run": params.get("dry_run", True),
        "maps": maps,
        "normal_convention": "OPENGL",
        "scalar_channel": "R",
        "alpha_mode": "OPAQUE",
        "estimated_decoded_bytes": estimate,
        "max_memory_mb": budget,
        "material_assigned": False,
        "visual_acceptance": False,
        "limitations": [
            "Budget estimates 16 bytes/pixel per PNG/JPEG and 36 per EXR (decoded float RGBA, validation copy and finite mask); decoder temporaries, GPU memory and runtime residency are additional",
            "Separate roughness/metallic maps use their red channel; base-color alpha is not connected",
            "Headers and hashes are preflight evidence, not rendered material, UV, tangent or native-engine acceptance",
        ],
    }


def _load_image(path):
    import bpy

    return bpy.data.images.load(path, check_existing=False)


def _verify_exr_pixels(image, item):
    from array import array

    import numpy as np  # Bundled by the supported Blender runtime.

    pixels = array("f", [0]) * len(image.pixels)
    image.pixels.foreach_get(pixels)
    values = np.frombuffer(pixels, dtype=np.float32)
    if len(values) != item["width"] * item["height"] * 4 or not np.isfinite(values).all():
        raise ValueError("EXR data map must decode to complete finite RGBA pixels")
    rgb = values.reshape(-1, 4)[:, :3]
    item["exr"].update(
        finite_decoded_buffer_verified=True,
        decoded_minimum=float(rgb.min()),
        decoded_maximum=float(rgb.max()),
        outside_unit_range=bool(rgb.min() < 0 or rgb.max() > 1),
    )


def create_pbr_material(params, context=None):
    """Create a new standalone material; never assign or recolor existing data."""
    result = _request(params)
    if result["dry_run"]:
        return result
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender material creation must run on the main thread")
    import bpy

    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Object Mode is required for material creation")
    # Blender can return finite zero-filled buffers for truncated scanlines. Check
    # the complete container before allocating any Blender IDs, without decoding it.
    for item in result["maps"]:
        if item["format"] == "EXR":
            verified = inspect_texture_file(item["path"], verify_exr_structure=True)
            if any(
                verified[key] != item[key] for key in ("sha256", "width", "height", "file_bytes")
            ):
                raise RuntimeError("Texture source changed before EXR container validation")
            item["exr"] = verified["exr"]
    material, images = None, []
    try:
        material = bpy.data.materials.new(result["name"])
        material.use_nodes = True
        material.use_fake_user = True
        material["framewright_owner"] = "materials"
        material["framewright_asset_id"] = str(uuid4())
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.inputs["Roughness"].default_value = 0.5
        shader.inputs["Metallic"].default_value = 0.0
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        for index, item in enumerate(result["maps"]):
            image = _load_image(item["path"])
            images.append(image)
            if tuple(image.size) != (item["width"], item["height"]):
                raise RuntimeError("Decoded image dimensions differ from preflight metadata")
            # Touch a pixel to require successful decode before publishing a recipe.
            if not image.has_data or not len(image.pixels):
                raise RuntimeError("Blender did not decode the texture data")
            image.pixels[0]
            image.colorspace_settings.name = item["color_space"]
            if item["format"] == "EXR":
                _verify_exr_pixels(image, item)
            image.name = f"{result['name']}_{item['role']}"
            image["framewright_owner"] = "materials"
            image["framewright_source_sha256"] = item["sha256"]
            verified = inspect_texture_file(item["path"])
            if any(
                verified[key] != item[key] for key in ("sha256", "width", "height", "file_bytes")
            ):
                raise RuntimeError("Texture source changed while Blender loaded it")
            node = nodes.new("ShaderNodeTexImage")
            node.image = image
            node.name = "FW_" + item["role"]
            node.label = item["role"]
            node.location = (-600, -index * 280)
            if item["role"] == "base_color":
                links.new(node.outputs["Color"], shader.inputs["Base Color"])
            elif item["role"] in {"roughness", "metallic"}:
                separate = nodes.new("ShaderNodeSeparateColor")
                separate.mode = "RGB"
                separate.location = (-300, -index * 280)
                links.new(node.outputs["Color"], separate.inputs["Color"])
                links.new(separate.outputs["Red"], shader.inputs[item["role"].title()])
            else:
                normal = nodes.new("ShaderNodeNormalMap")
                normal.space = "TANGENT"
                normal.location = (-300, -index * 280)
                links.new(node.outputs["Color"], normal.inputs["Color"])
                links.new(normal.outputs["Normal"], shader.inputs["Normal"])
            item["image"] = image.name
        material["framewright_material_recipe"] = json.dumps(
            result, sort_keys=True, allow_nan=False
        )
        result.update(material=material.name, asset_id=material["framewright_asset_id"])
        return result
    except Exception:
        if material is not None:
            bpy.data.materials.remove(material, do_unlink=True)
        for image in images:
            bpy.data.images.remove(image, do_unlink=True)
        raise
