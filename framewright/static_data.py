"""Bounded admission of static mesh and shader data before Blender evaluation."""

from collections import deque

import bpy

MAX_DATA_BLOCKS = 4096
MAX_SHADER_NODES = 65536


def require_static_mesh_material_data(objects):
    """Reject actions/drivers on copied data and shader groups without evaluating.

    FCurve paths can traverse an ID-valued custom property and write another ID.
    Neither object-only animation checks nor disabled script autoexec prevent
    native drivers on Mesh, Key, Material or ShaderNodeTree data from doing this.
    """
    pending = deque()
    seen = set()
    node_count = 0

    def enqueue(block):
        if block is None:
            return
        pointer = block.as_pointer()
        if pointer in seen:
            return
        if len(seen) >= MAX_DATA_BLOCKS:
            raise ValueError("Static data dependency inspection exceeds 4096 datablocks")
        seen.add(pointer)
        pending.append(block)

    for obj in objects:
        if obj.type == "MESH":
            enqueue(obj.data)
            # Effective OBJECT overrides and underlying mesh-slot references
            # both remain dependencies until an independent copy is rebuilt.
            for slot in obj.material_slots:
                enqueue(slot.material)
    while pending:
        block = pending.popleft()
        if getattr(block, "animation_data", None) is not None:
            raise ValueError(
                f"Static mesh/material dependencies must have no animation or drivers: {block.name!r}"
            )
        if isinstance(block, bpy.types.Mesh):
            enqueue(block.shape_keys)
            for material in block.materials:
                enqueue(material)
        elif isinstance(block, bpy.types.Material):
            enqueue(block.node_tree)
        elif isinstance(block, bpy.types.NodeTree):
            for node in block.nodes:
                node_count += 1
                if node_count > MAX_SHADER_NODES:
                    raise ValueError("Static data dependency inspection exceeds 65536 shader nodes")
                enqueue(getattr(node, "node_tree", None))
