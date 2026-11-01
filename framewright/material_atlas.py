"""Static opaque Principled appearance baked to one owned four-map atlas."""

from __future__ import annotations

import math
import struct
import threading
import uuid
import zlib
from contextlib import contextmanager

import bpy
import numpy as np

from .atlas_plan import parse_atlas_request
from .mesh_diagnostics import triangle_overlap_2d
from .static_data import require_static_mesh_material_data

_NODES = {
    "OUTPUT_MATERIAL",
    "BSDF_PRINCIPLED",
    "TEX_COORD",
    "MAPPING",
    "TEX_NOISE",
    "VALTORGB",
    "BUMP",
    "NORMAL_MAP",
    "TEX_IMAGE",
    "UVMAP",
    "REROUTE",
    "MATH",
    "VECT_MATH",
    "RGB",
    "VALUE",
    "MIX_RGB",
    "SEPARATE_COLOR",
    "COMBINE_COLOR",
}
_SCALARS = {"roughness": "Roughness", "metallic": "Metallic"}


def _principled(material):
    if material is None or material.library or not material.node_tree:
        raise ValueError("Atlas requires local node-based opaque Principled materials")
    tree = material.node_tree
    if material.use_backface_culling:
        raise ValueError("Atlas does not support source backface culling")
    outputs = [
        node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output
    ]
    if len(outputs) != 1 or not outputs[0].inputs["Surface"].is_linked:
        raise ValueError("Atlas requires one active connected material output")
    output = outputs[0]
    shader = output.inputs["Surface"].links[0].from_node
    if (
        shader.type != "BSDF_PRINCIPLED"
        or output.inputs["Volume"].is_linked
        or output.inputs["Displacement"].is_linked
    ):
        raise ValueError(
            "Atlas requires direct opaque Principled surface without volume/displacement"
        )
    if shader.distribution != "MULTI_GGX":
        raise ValueError("Atlas requires Principled MULTI_GGX distribution")
    for name, expected in {
        "Alpha": 1,
        "Transmission Weight": 0,
        "Subsurface Weight": 0,
        "Coat Weight": 0,
        "Sheen Weight": 0,
        "Anisotropic": 0,
        "Diffuse Roughness": 0,
        "Thin Film Thickness": 0,
        "Thin Wall": 0,
        "Weight": 0,
        "Emission Strength": 0,
        "Specular IOR Level": 0.5,
        "IOR": 1.5,
    }.items():
        socket = next((item for item in shader.inputs if item.name == name), None)
        if socket is None:
            continue
        if socket.is_linked or abs(socket.default_value - expected) > 1e-7:
            raise ValueError(f"Unsupported opaque Principled semantic: {name}")
    tint = shader.inputs["Specular Tint"]
    if tint.is_linked or any(abs(value - 1) > 1e-7 for value in tint.default_value):
        raise ValueError("Unsupported opaque Principled semantic: Specular Tint")
    for node in tree.nodes:
        if node.type not in _NODES or node.mute:
            raise ValueError(f"Unsupported or muted shader node: {node.type}")
        if node.type == "TEX_COORD":
            if node.object is not None or node.from_instancer:
                raise ValueError("External/instancer texture coordinates are unsupported")
            for socket in node.outputs:
                if socket.is_linked and socket.name not in {"Generated", "UV", "Object", "Normal"}:
                    raise ValueError(f"Unsupported texture coordinate: {socket.name}")
        if node.type == "TEX_IMAGE":
            image = node.image
            if (
                image is None
                or image.source not in {"FILE", "GENERATED"}
                or image.library
                or getattr(image, "animation_data", None)
            ):
                raise ValueError("Atlas images require local static FILE/GENERATED data")
            if node.projection != "FLAT" or node.interpolation not in {"Linear", "Closest"}:
                raise ValueError("Atlas supports flat linear/closest source image sampling")
            if not image.has_data or min(image.size) < 1 or image.channels not in {1, 3, 4}:
                raise ValueError("Source images must already have decoded pixel data")
        if node.type == "NORMAL_MAP" and node.space != "TANGENT":
            raise ValueError("Source normal maps must use tangent space")
        for socket in node.inputs:
            value = getattr(socket, "default_value", None)
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError("Shader values must be finite")
            if value is not None and not isinstance(value, (str, bool, float, int)):
                try:
                    if any(isinstance(v, (float, int)) and not math.isfinite(v) for v in value):
                        raise ValueError("Shader values must be finite")
                except TypeError:
                    pass
    return shader, output


def _admit(params, context):
    if threading.current_thread() is not threading.main_thread() or context.mode != "OBJECT":
        raise ValueError("Atlas requires Blender main thread in Object mode")
    for kind in (
        "frame_change_pre",
        "frame_change_post",
        "depsgraph_update_pre",
        "depsgraph_update_post",
        "object_bake_pre",
        "object_bake_complete",
        "object_bake_cancel",
        "render_pre",
        "render_post",
        "render_init",
        "render_complete",
        "render_cancel",
        "render_write",
    ):
        if getattr(bpy.app.handlers, kind):
            raise ValueError(
                "Atlas requires a clean context without global frame/depsgraph handlers"
            )
    objects = []
    for name in params["object_names"]:
        obj = context.scene.objects.get(name)
        if obj is None or obj.type not in {"MESH", "EMPTY"} or obj.library or obj.override_library:
            raise ValueError(
                "Atlas names must identify local Mesh/Empty objects in the active scene"
            )
        if obj.animation_data or obj.constraints or obj.instance_type != "NONE":
            raise ValueError("Atlas supports static unconstrained non-instanced objects")
        if obj.parent and obj.parent.name not in params["object_names"]:
            raise ValueError("Select the complete parent hierarchy for atlas sources")
        if obj.parent_type != "OBJECT":
            raise ValueError("Atlas supports ordinary object parenting only")
        if (
            any(not math.isfinite(v) for row in obj.matrix_world for v in row)
            or abs(obj.matrix_world.determinant()) < 1e-12
        ):
            raise ValueError("Atlas transforms must be finite and nonsingular")
        if obj.type == "MESH":
            if (
                obj.data.library
                or obj.data.shape_keys
                or obj.vertex_groups
                or not obj.data.polygons
            ):
                raise ValueError(
                    "Atlas mesh sources must be local static faces without skin/shape keys"
                )
            if any(
                mod.type not in {"BEVEL", "WEIGHTED_NORMAL", "TRIANGULATE"} for mod in obj.modifiers
            ):
                raise ValueError(
                    "Atlas supports only Bevel, Weighted Normal and Triangulate modifiers"
                )
            if not obj.material_slots or any(slot.material is None for slot in obj.material_slots):
                raise ValueError("Every atlas material slot must contain a material")
        objects.append(obj)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("Atlas requires at least one mesh")
    require_static_mesh_material_data(objects)
    images = set()
    for obj in meshes:
        source_uv = next((uv.name for uv in obj.data.uv_layers if uv.active_render), "")
        for slot in obj.material_slots:
            _principled(slot.material)
            for node in slot.material.node_tree.nodes:
                if node.type == "TEX_IMAGE":
                    images.add(node.image)
                if (
                    node.type in {"UVMAP", "NORMAL_MAP"}
                    and node.uv_map
                    and node.uv_map not in obj.data.uv_layers
                ):
                    raise ValueError("Named source UV map is missing")
                if _uses_default_uv(node) and not source_uv:
                    raise ValueError("Source shader requires an existing render UV map")
    image_bytes = sum(image.size[0] * image.size[1] * 4 * 4 for image in images)
    total = params["estimated_image_working_bytes"] + image_bytes
    if total > params["max_memory_mb"] * 1024**2:
        raise ValueError(
            "Known source decoded images plus atlas image estimate exceed memory budget"
        )
    base_vertices = sum(len(obj.data.vertices) for obj in meshes)
    base_triangles = sum(
        sum(len(face.vertices) - 2 for face in obj.data.polygons) for obj in meshes
    )
    if (
        base_vertices > params["max_evaluated_vertices"]
        or base_triangles > params["max_evaluated_triangles"]
    ):
        raise ValueError("Source geometry exceeds evaluated geometry budget")
    return objects, images, image_bytes


def _evaluated_counts(objects, context):
    graph = context.evaluated_depsgraph_get()
    vertices = triangles = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(graph)
        try:
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
            mesh.calc_loop_triangles()
            if any(not math.isfinite(value) for vertex in mesh.vertices for value in vertex.co):
                raise ValueError("Evaluated source geometry must be finite")
            vertices += len(mesh.vertices)
            triangles += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return {"vertices": vertices, "triangles": triangles}


def _uses_default_uv(node):
    return (
        (node.type == "TEX_IMAGE" and not node.inputs["Vector"].is_linked)
        or (node.type == "TEX_COORD" and node.outputs["UV"].is_linked)
        or (node.type in {"NORMAL_MAP", "UVMAP"} and not node.uv_map)
    )


def _pin_uv(material, source_uv):
    tree = material.node_tree
    pin = None
    for node in list(tree.nodes):
        needs_uv = node.type == "TEX_IMAGE" and not node.inputs["Vector"].is_linked
        has_default_uv = node.type == "TEX_COORD" and node.outputs["UV"].is_linked
        normal_uv = node.type == "NORMAL_MAP" and not node.uv_map
        named_default_uv = node.type == "UVMAP" and not node.uv_map
        if needs_uv or has_default_uv or normal_uv or named_default_uv:
            if not source_uv:
                raise ValueError("Source shader requires an existing render UV map")
            if pin is None:
                pin = tree.nodes.new("ShaderNodeUVMap")
                pin.uv_map = source_uv
            if needs_uv:
                tree.links.new(pin.outputs["UV"], node.inputs["Vector"])
            if has_default_uv:
                for link in list(node.outputs["UV"].links):
                    tree.links.new(pin.outputs["UV"], link.to_socket)
            if normal_uv:
                node.uv_map = source_uv
            if named_default_uv:
                node.uv_map = source_uv


@contextmanager
def _square_uv_image(meshes):
    """Give UV packing square target aspect instead of any source image aspect."""
    image = bpy.data.images.new("FW_AtlasPackingAspect", width=1, height=1)
    nodes = []
    try:
        for obj in meshes:
            for material in obj.data.materials:
                tree = material.node_tree
                previous = tree.nodes.active
                node = tree.nodes.new("ShaderNodeTexImage")
                nodes.append((tree, node, previous))
                node.image = image
                tree.nodes.active = node
        yield
    finally:
        for tree, node, previous in reversed(nodes):
            tree.nodes.remove(node)
            tree.nodes.active = previous
        bpy.data.images.remove(image)


def _unwrap(stage, meshes, uv_name, margin, resolution):
    layer = stage.view_layers[0]
    for obj in meshes:
        uv = obj.data.uv_layers.new(name=uv_name)
        obj.data.uv_layers.active = uv
        uv.active_render = True
        obj.select_set(True, view_layer=layer)
    layer.objects.active = meshes[0]
    with (
        _square_uv_image(meshes),
        bpy.context.temp_override(
            scene=stage,
            view_layer=layer,
            active_object=meshes[0],
            object=meshes[0],
            selected_objects=meshes,
            selected_editable_objects=meshes,
        ),
    ):
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(
                angle_limit=math.radians(66), island_margin=0, correct_aspect=False
            )
            bpy.ops.uv.average_islands_scale()
            bpy.ops.uv.pack_islands(
                rotate=True,
                scale=True,
                margin_method="FRACTION",
                margin=2 * margin / resolution,
                merge_overlap=False,
            )
        finally:
            if meshes[0].mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
    for obj in meshes:
        obj.data.calc_loop_triangles()
        uv = obj.data.uv_layers[uv_name]
        for tri in obj.data.loop_triangles:
            a, b, c = [uv.data[index].uv for index in tri.loops]
            if not all(
                math.isfinite(v) and -1e-6 <= v <= 1 + 1e-6 for pair in (a, b, c) for v in pair
            ):
                raise ValueError("Atlas UV packing produced invalid coordinates")
            if abs((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) < 1e-14:
                raise ValueError("Atlas UV packing produced a degenerate triangle")


def _uv_evidence(meshes, uv_name, resolution, margin):
    """Complete bounded global overlap and chart-boundary padding measurement."""
    triangles, edges = [], {}
    for object_index, obj in enumerate(meshes):
        obj.data.calc_loop_triangles()
        uv = obj.data.uv_layers[uv_name]
        for triangle in obj.data.loop_triangles:
            points = tuple(tuple(uv.data[index].uv) for index in triangle.loops)
            index = len(triangles)
            triangles.append(points)
            for a, b in ((0, 1), (1, 2), (2, 0)):
                key = tuple(
                    sorted(
                        (
                            (object_index, triangle.vertices[a], *points[a]),
                            (object_index, triangle.vertices[b], *points[b]),
                        )
                    )
                )
                edges.setdefault(key, []).append((index, points[a], points[b]))
    parents = list(range(len(triangles)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for entries in edges.values():
        if len(entries) > 1:
            for row in entries[1:]:
                parents[root(row[0])] = root(entries[0][0])
    boxes = [
        (
            min(p[0] for p in tri),
            max(p[0] for p in tri),
            min(p[1] for p in tri),
            max(p[1] for p in tri),
        )
        for tri in triangles
    ]
    order = sorted(range(len(triangles)), key=lambda index: boxes[index][0])
    visits = 0
    for position, first in enumerate(order):
        for next_position in range(position + 1, len(order)):
            second = order[next_position]
            if boxes[second][0] > boxes[first][1] + 1e-8:
                break
            visits += 1
            if visits > 2_000_000:
                raise ValueError(
                    "Complete atlas UV overlap inspection exceeds 2000000 candidate visits"
                )
            if boxes[first][3] < boxes[second][2] or boxes[second][3] < boxes[first][2]:
                continue
            if triangle_overlap_2d(triangles[first], triangles[second]):
                raise ValueError("Atlas UV triangles overlap; no texture bake retained")
    boundaries = [
        (root(row[0]), row[1], row[2])
        for entries in edges.values()
        if len(entries) == 1
        for row in entries
    ]
    search = max(2 * margin / resolution, 1e-7)
    boundaries.sort(key=lambda edge: min(edge[1][0], edge[2][0]))
    closest = search

    def point_distance(point, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = (
            max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length))
            if length
            else 0
        )
        return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)

    padding_visits = 0
    for position, (island, a, b) in enumerate(boundaries):
        for next_position in range(position + 1, len(boundaries)):
            other, c, d = boundaries[next_position]
            if min(c[0], d[0]) > max(a[0], b[0]) + search:
                break
            padding_visits += 1
            if padding_visits > 2_000_000:
                raise ValueError(
                    "Complete atlas padding inspection exceeds 2000000 candidate visits"
                )
            if (
                other == island
                or max(a[1], b[1]) + search < min(c[1], d[1])
                or max(c[1], d[1]) + search < min(a[1], b[1])
            ):
                continue
            closest = min(
                closest,
                point_distance(a, c, d),
                point_distance(b, c, d),
                point_distance(c, a, b),
                point_distance(d, a, b),
            )
    tile_border = min(min(p[0], p[1], 1 - p[0], 1 - p[1]) for tri in triangles for p in tri)
    return {
        "coverage": "complete",
        "triangles": len(triangles),
        "overlap_count": 0,
        "overlap_candidate_visits": visits,
        "padding_candidate_visits": padding_visits,
        "chart_count": len({root(index) for index in range(len(triangles))}),
        "minimum_chart_gap_px_lower_bound": closest * resolution,
        "gap_search_radius_px": search * resolution,
        "minimum_tile_border_px": tile_border * resolution,
        "requested_bake_margin_px": margin,
        "padding_measured_not_mipmap_guarantee": True,
    }


def _primary_atlas_uv(meshes, uv_name):
    """Make owned atlas UV the portable default; retain named source layer data.

    Blender's FBX exporter currently does not emit a texture UVSet name. Its
    importer consequently samples the first layer even when another was render
    active before export. Reorder only owned derivative layers after baking.
    """
    for obj in meshes:
        layers = obj.data.uv_layers
        records = []
        for layer in layers:
            values = np.empty(len(layer.data) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", values)
            pins = np.empty(len(layer.data), dtype=np.bool_)
            layer.data.foreach_get("pin_uv", pins)
            records.append((layer.name, values, pins, layer.active_clone))
        records.sort(key=lambda row: row[0] != uv_name)
        for layer in list(layers):
            layers.remove(layer)
        for name, values, pins, clone in records:
            layer = layers.new(name=name, do_init=False)
            layer.data.foreach_set("uv", values)
            layer.data.foreach_set("pin_uv", pins)
            if clone:
                layer.active_clone = True
        layers.active = layers[uv_name]
        layers[uv_name].active_render = True


def _bake_pass(stage, meshes, image, role, margin):
    temporary = []
    restored = []
    try:
        for obj in meshes:
            for material in obj.data.materials:
                tree = material.node_tree
                shader, output = _principled(material)
                target = tree.nodes.new("ShaderNodeTexImage")
                target.image = image
                tree.nodes.active = target
                temporary.append((tree, target))
                if role != "normal":
                    emission = tree.nodes.new("ShaderNodeEmission")
                    temporary.append((tree, emission))
                    original = output.inputs["Surface"].links[0].from_socket
                    restored.append((tree, original, output.inputs["Surface"]))
                    tree.links.new(emission.outputs[0], output.inputs["Surface"])
                    source = shader.inputs["Base Color" if role == "base_color" else _SCALARS[role]]
                    if role in _SCALARS:
                        clamp = tree.nodes.new("ShaderNodeClamp")
                        temporary.append((tree, clamp))
                        if source.is_linked:
                            tree.links.new(source.links[0].from_socket, clamp.inputs["Value"])
                        else:
                            clamp.inputs["Value"].default_value = source.default_value
                        tree.links.new(clamp.outputs[0], emission.inputs["Color"])
                    elif source.is_linked:
                        tree.links.new(source.links[0].from_socket, emission.inputs["Color"])
                    else:
                        emission.inputs["Color"].default_value = source.default_value
        layer = stage.view_layers[0]
        with bpy.context.temp_override(
            scene=stage,
            view_layer=layer,
            active_object=meshes[0],
            object=meshes[0],
            selected_objects=meshes,
            selected_editable_objects=meshes,
        ):
            status = bpy.ops.object.bake(
                type="NORMAL" if role == "normal" else "EMIT",
                margin=margin,
                use_clear=True,
                use_selected_to_active=False,
                normal_space="TANGENT",
                normal_r="POS_X",
                normal_g="POS_Y",
                normal_b="POS_Z",
                target="IMAGE_TEXTURES",
            )
            if "FINISHED" not in status:
                raise RuntimeError(f"Atlas {role} bake did not finish")
    finally:
        for tree, source, target in restored:
            tree.links.new(source, target)
        for tree, node in reversed(temporary):
            tree.nodes.remove(node)


def _png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _pack_png(image, role):
    """Encode owned linear float pixels explicitly; PNG rows are top-to-bottom."""
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    compressor = zlib.compressobj(6)
    chunks = []
    clipped = 0
    minimum, maximum = math.inf, -math.inf
    for y in range(height - 1, -1, -1):
        values = pixels[y, :, :3].astype(np.float64)
        if not np.isfinite(values).all():
            raise ValueError("Atlas bake produced nonfinite pixels")
        minimum, maximum = min(minimum, float(values.min())), max(maximum, float(values.max()))
        tolerance = 1e-4 if role == "normal" else 1e-6
        if values.min() < -tolerance or values.max() > 1 + tolerance:
            raise ValueError(f"Atlas {role} data exceeds 0..1 encoding range")
        clipped += int(np.count_nonzero((values < 0) | (values > 1)))
        np.clip(values, 0, 1, out=values)
        if role == "base_color":
            values = np.where(
                values <= 0.0031308, 12.92 * values, 1.055 * values ** (1 / 2.4) - 0.055
            )
        row = b"\0" + np.rint(values * 65535).astype(">u2").tobytes()
        chunks.append(compressor.compress(row))
    chunks.append(compressor.flush())
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", b"".join(chunks))
        + _png_chunk(b"IEND", b"")
    )
    del pixels, chunks, values, row
    image.pack(data=payload, data_len=len(payload))
    image.source = "FILE"
    image.filepath = "//" + image.name + ".png"
    image.colorspace_settings.name = "sRGB" if role == "base_color" else "Non-Color"
    image.reload()
    if (
        image.packed_file is None
        or bytes(image.packed_file.data) != payload
        or tuple(image.size) != (width, height)
    ):
        raise RuntimeError("Packed atlas PNG failed byte/dimension verification")
    return {
        "image": image.name,
        "resolution": [width, height],
        "color_space": image.colorspace_settings.name,
        "packed": True,
        "encoding": "PNG_16_RGB",
        "packed_bytes": len(payload),
        "roundoff_clamped_components": clipped,
        "baked_range": [minimum, maximum],
        "data_roundoff_tolerance": 1e-4 if role == "normal" else 1e-6,
    }


def _portable_material(material, images, uv_name):
    shader = material.node_tree.nodes.get("Principled BSDF")
    for role, image in images.items():
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        if role == "normal":
            normal = material.node_tree.nodes.new("ShaderNodeNormalMap")
            normal.uv_map = uv_name
            material.node_tree.links.new(texture.outputs["Color"], normal.inputs["Color"])
            material.node_tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
        else:
            material.node_tree.links.new(
                texture.outputs["Color"],
                shader.inputs["Base Color" if role == "base_color" else _SCALARS[role]],
            )
    return material


def bake_material_atlas(params, context=None):
    context = context or bpy.context
    p = parse_atlas_request(params)
    sources, input_images, image_bytes = _admit(p, context)
    counts = _evaluated_counts(sources, context)
    if (
        counts["vertices"] > p["max_evaluated_vertices"]
        or counts["triangles"] > p["max_evaluated_triangles"]
    ):
        raise ValueError("Evaluated source geometry exceeds atlas budget")
    result = {
        **p,
        "source_objects": sorted(obj.name for obj in sources),
        "evaluated_geometry": counts,
        "input_image_decoded_bytes": image_bytes,
        "input_images": sorted(image.name for image in input_images),
        "total_known_image_working_bytes": p["estimated_image_working_bytes"] + image_bytes,
        "source_preservation_scope": "selected local static source geometry/UV/material graphs/images/transforms/hierarchy/visibility; no source time change",
        "limitations": [
            "Static opaque Principled subset only",
            "Modifiers frozen on derivatives; source UV layers retained",
            "No external output files; four packed PNG maps",
            "Image estimates exclude geometry, renderer, driver and process allocations",
            "No visual or native-game acceptance",
        ],
    }
    if p["dry_run"]:
        return result
    owned_objects, owned_meshes, owned_materials, owned_images = [], [], [], []
    stage = collection = output_material = None
    success = False
    source_scene = context.scene
    window = context.window
    original_window_scene = window.scene if window else None
    uv_name = "FW_Atlas_" + uuid.uuid4().hex[:8]
    try:
        stage = bpy.data.scenes.new(p["name"] + "_BakeStage")
        stage.render.engine = "CYCLES"
        stage.cycles.device = "CPU"
        stage.cycles.samples = 1
        stage.render.threads_mode = "FIXED"
        stage.render.threads = 4
        stage.render.bake.use_clear = True
        stage.render.bake.margin_type = "EXTEND"
        stage.world = None
        collection = bpy.data.collections.new(p["name"])
        collection["framewright_owner"] = "material_atlas"
        stage.collection.children.link(collection)
        mapping = {}
        graph = context.evaluated_depsgraph_get()
        for source in sources:
            copy = source.copy()
            owned_objects.append(copy)
            copy.name = p["name"] + "_" + source.name
            copy.animation_data_clear()
            copy.hide_viewport = copy.hide_render = False
            copy["framewright_owner"] = "material_atlas"
            copy["framewright_source"] = source.name
            if source.type == "MESH":
                mesh = bpy.data.meshes.new_from_object(
                    source.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph
                )
                owned_meshes.append(mesh)
                copy.data = mesh
                copy.modifiers.clear()
                indices = [face.material_index for face in mesh.polygons]
                mesh.materials.clear()
                source_uv = next((uv.name for uv in source.data.uv_layers if uv.active_render), "")
                for slot in source.material_slots:
                    material = slot.material.copy()
                    owned_materials.append(material)
                    _pin_uv(material, source_uv)
                    mesh.materials.append(material)
                for slot in copy.material_slots:
                    slot.link = "DATA"
                for face, index in zip(mesh.polygons, indices, strict=True):
                    face.material_index = index
            collection.objects.link(copy)
            mapping[source] = copy
        for source, copy in mapping.items():
            copy.parent = mapping.get(source.parent)
            copy.matrix_parent_inverse = source.matrix_parent_inverse.copy()
        if window:
            window.scene = stage
        stage.view_layers[0].update()
        meshes = [copy for copy in owned_objects if copy.type == "MESH"]
        _unwrap(stage, meshes, uv_name, p["margin"], p["resolution"])
        uv_evidence = _uv_evidence(meshes, uv_name, p["resolution"], p["margin"])
        maps = {}
        images = {}
        for role in p["map_roles"]:
            image = bpy.data.images.new(
                p["name"] + "_" + role,
                width=p["resolution"],
                height=p["resolution"],
                alpha=False,
                float_buffer=True,
            )
            owned_images.append(image)
            image.colorspace_settings.name = "Non-Color"
            _bake_pass(stage, meshes, image, role, p["margin"])
            maps[role] = _pack_png(image, role)
            images[role] = image
        output_material = bpy.data.materials.new(p["name"] + "_Material")
        _portable_material(output_material, images, uv_name)
        _primary_atlas_uv(meshes, uv_name)
        for obj in meshes:
            obj.data.materials.clear()
            obj.data.materials.append(output_material)
            for face in obj.data.polygons:
                face.material_index = 0
        source_scene.collection.children.link(collection)
        for obj in owned_objects:
            obj.hide_render = True
            obj.hide_viewport = True
        result.update(
            objects=sorted(obj.name for obj in owned_objects),
            derivatives={source.name: copy.name for source, copy in mapping.items()},
            collection=collection.name,
            material=output_material.name,
            uv_layer=uv_name,
            maps=maps,
            hidden=True,
            uv_evidence=uv_evidence,
            uv_policy="owned Smart Project charts, area-scaled and globally packed with explicit fractional margin; atlas is first/render UV for portable default sampling; original named layers retained",
        )
        success = True
        return result
    finally:
        if window and original_window_scene:
            window.scene = original_window_scene
        if not success:
            for obj in owned_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for mesh in owned_meshes:
                bpy.data.meshes.remove(mesh)
            if output_material:
                bpy.data.materials.remove(output_material)
            for image in owned_images:
                bpy.data.images.remove(image)
        for material in owned_materials:
            bpy.data.materials.remove(material, do_unlink=True)
        if stage:
            bpy.data.scenes.remove(stage)
        if not success and collection:
            bpy.data.collections.remove(collection)
