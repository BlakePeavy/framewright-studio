"""Owned FBX staging for the direct red-channel scalar maps FBX otherwise drops."""

from __future__ import annotations

import struct
import zlib
from array import array
from contextlib import contextmanager

import bpy


def validate_material_dependencies(objects):
    """Reject animated shader dependencies; this exporter does not bake materials."""
    pending = [slot.material for obj in objects for slot in obj.material_slots if slot.material]
    seen = set()
    while pending:
        data = pending.pop()
        if data in seen:
            continue
        seen.add(data)
        if getattr(data, "animation_data", None) is not None:
            raise ValueError(
                "Animated material/node/image dependencies must be baked before scoped export"
            )
        tree = getattr(data, "node_tree", None)
        if tree is not None:
            pending.append(tree)
        for node in getattr(data, "nodes", ()):
            group = getattr(node, "node_tree", None)
            if group is not None:
                pending.append(group)
            image = getattr(node, "image", None)
            if image is not None:
                if image.source in {"SEQUENCE", "MOVIE"}:
                    raise ValueError(
                        "Animated image sequences/movies must be baked before scoped export"
                    )
                pending.append(image)


def plan_scalar_maps(objects, budget_mb, clamp=False):
    """Validate supported links and estimate temporary work without allocating IDs."""
    rows = []
    unique = {}
    materials = {slot.material for obj in objects for slot in obj.material_slots if slot.material}
    for material in sorted(materials, key=lambda item: item.name):
        if not material.node_tree:
            continue
        for shader in material.node_tree.nodes:
            if shader.type != "BSDF_PRINCIPLED":
                continue
            for role in ("Roughness", "Metallic"):
                socket = shader.inputs[role]
                if not socket.is_linked or socket.links[0].from_node.type != "SEPARATE_COLOR":
                    continue
                link = socket.links[0]
                separate = link.from_node
                if shader.mute or separate.mute:
                    raise ValueError(
                        "FBX scalar staging does not support muted shader/separator nodes"
                    )
                if (
                    separate.mode != "RGB"
                    or link.from_socket.name != "Red"
                    or not separate.inputs["Color"].is_linked
                ):
                    raise ValueError(
                        "FBX scalar staging supports only RGB Separate Color red-channel maps"
                    )
                color_link = separate.inputs["Color"].links[0]
                texture = color_link.from_node
                image = getattr(texture, "image", None)
                if texture.mute:
                    raise ValueError("FBX scalar staging does not support muted image nodes")
                if (
                    texture.type != "TEX_IMAGE"
                    or color_link.from_socket.name != "Color"
                    or image is None
                    or image.source != "FILE"
                    or image.colorspace_settings.name != "Non-Color"
                    or tuple(image.size) == (0, 0)
                    or texture.inputs["Vector"].is_linked
                    or texture.projection != "FLAT"
                    or texture.extension != "REPEAT"
                    or texture.interpolation != "Linear"
                    or texture.image_user.frame_offset != 0
                ):
                    raise ValueError(
                        "FBX red-channel staging requires a direct file image, Non-Color, default UVs, flat/repeat/linear sampling"
                    )
                if not image.has_data or len(image.pixels) != image.size[0] * image.size[1] * 4:
                    raise ValueError("FBX scalar image must have decoded RGBA pixels")
                rows.append(
                    {
                        "material": material.name,
                        "shader": shader.name,
                        "socket": role,
                        "texture": texture.name,
                        "image": image.name,
                        "width": image.size[0],
                        "height": image.size[1],
                        "channel": "R",
                    }
                )
                unique[image.name] = image.size[0] * image.size[1]
    estimate = sum(unique.values()) * 64
    if estimate > budget_mb * 1024 * 1024:
        raise ValueError(
            "FBX scalar texture staging estimate exceeds max_material_memory_mb; raise the explicit budget or use GLB"
        )
    return {
        "maps": rows,
        "estimated_temporary_bytes": estimate,
        "max_material_memory_mb": budget_mb,
        "encoding": "16-bit grayscale PNG; red copied without color transform",
        "clamp_scalar_textures": clamp,
        "scalar_images": {},
        "limits": [
            "Conservative 64 bytes per unique image pixel estimate, not an OS/GPU memory cap",
            "Default UV, flat/repeat/linear image sampling only; no procedural shader baking",
            "Native import and rendered acceptance remain separate",
            "Out-of-range red values are rejected unless explicit scalar clamping is requested; source images stay unchanged",
        ],
    }


def _write_red_png(image, path, clamp=False):
    # NumPy ships with the supported Blender runtime; no package/network install.
    import numpy as np

    width, height = image.size
    pixels = array("f", [0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    red = np.frombuffer(pixels, dtype=np.float32).reshape(height, width, 4)[:, :, 0]
    if type(clamp) is not bool:
        raise ValueError("Scalar clamp must be a boolean")
    if not np.isfinite(red).all():
        raise ValueError("FBX scalar staging requires finite red-channel values in [0, 1]")
    minimum, maximum = float(red.min()), float(red.max())
    clipped = int(np.count_nonzero((red < 0) | (red > 1)))
    if clipped and not clamp:
        raise ValueError(
            "FBX scalar staging requires finite red-channel values in [0, 1]; explicitly request clamp_scalar_textures to clip owned output"
        )
    evidence = {
        "source_red_min": minimum,
        "source_red_max": maximum,
        "pixel_count": width * height,
        "clipped_pixel_count": clipped if clamp else 0,
        "clamp_requested": clamp,
        "semantics": "owned output R clipped to [0,1] then quantized to 16-bit"
        if clamp
        else "R quantized to 16-bit without clipping",
    }

    def chunk(stream, kind, payload):
        stream.write(struct.pack(">I", len(payload)))
        stream.write(kind)
        stream.write(payload)
        stream.write(struct.pack(">I", zlib.crc32(kind + payload)))

    with path.open("xb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0))
        compressor = zlib.compressobj()
        # Blender buffers are bottom-up; PNG scanlines are top-down. Stream one row.
        for row in red[::-1]:
            output_row = np.clip(row, 0, 1) if clamp else row
            data = compressor.compress(b"\0" + np.rint(output_row * 65535).astype(">u2").tobytes())
            if data:
                chunk(stream, b"IDAT", data)
        chunk(stream, b"IDAT", compressor.flush())
        chunk(stream, b"IEND", b"")
    return evidence


@contextmanager
def stage_scalar_maps(objects, plan, directory):
    """Change only already-owned export objects; discard all copied IDs afterward."""
    copied_materials, images, image_map = {}, [], {}
    try:
        for row in plan["maps"]:
            source_material = bpy.data.materials[row["material"]]
            material = copied_materials.get(source_material)
            if material is None:
                material = source_material.copy()
                copied_materials[source_material] = material
            image = image_map.get(row["image"])
            if image is None:
                path = directory / f"scalar-red-{len(images)}.png"
                source = bpy.data.images[row["image"]]
                evidence = (
                    _write_red_png(source, path, clamp=True)
                    if plan.get("clamp_scalar_textures", False)
                    else _write_red_png(source, path)
                )
                plan.setdefault("scalar_images", {})[row["image"]] = evidence
                image = bpy.data.images.load(str(path), check_existing=False)
                images.append(image)
                image.colorspace_settings.name = "Non-Color"
                image_map[row["image"]] = image
            # Add a direct image node: FBX's Principled wrapper ignores Separate Color.
            texture = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            socket = material.node_tree.nodes[row["shader"]].inputs[row["socket"]]
            material.node_tree.links.new(texture.outputs["Color"], socket)
        for obj in objects:
            for slot in obj.material_slots:
                if slot.material in copied_materials:
                    slot.material = copied_materials[slot.material]
        yield
    finally:
        # Restore owned slots before deleting the copied materials. Foreign/source IDs survive.
        reverse = {copy: original for original, copy in copied_materials.items()}
        for obj in objects:
            for slot in obj.material_slots:
                if slot.material in reverse:
                    slot.material = reverse[slot.material]
        for material in copied_materials.values():
            bpy.data.materials.remove(material, do_unlink=True)
        for image in images:
            bpy.data.images.remove(image, do_unlink=True)
