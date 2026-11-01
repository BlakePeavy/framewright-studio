"""Read-only UV coverage and conservative Principled material portability checks."""

from __future__ import annotations

import math

from .mesh_diagnostics import (
    DEFAULT_MAX_PAIRS,
    DEFAULT_MAX_TRIANGLES,
    EPSILON,
    SAMPLE_LIMIT,
    _cross2,
    finding,
    inspected_mesh,
    scan_intersections,
    validate_params,
)

MAX_GRAPH_NODES = 4096
PORTABLE_NODE_TYPES = {
    "OUTPUT_MATERIAL",
    "BSDF_PRINCIPLED",
    "TEX_IMAGE",
    "NORMAL_MAP",
    "SEPRGB",
    "SEPARATE_COLOR",
    "UVMAP",
    "TEX_COORD",
    "MAPPING",
    "REROUTE",
    "VALUE",
    "RGB",
}


def _uv_diagnostics(mesh, params):
    name = params.get("uv_layer")
    layer = mesh.uv_layers.get(name) if name is not None else mesh.uv_layers.active
    if layer is None:
        return {
            "coverage": "skipped",
            "layer": name,
            "overlap_count": 0,
            "zero_area_triangles": 0,
            "occupied_udim_tiles": [],
        }, [finding("UV_MISSING", "WARNING", "The requested or active UV layer is missing")]
    triangle_total = len(mesh.loop_triangles)
    selected = [
        mesh.loop_triangles[i]
        for i in range(min(triangle_total, params.get("max_triangles", DEFAULT_MAX_TRIANGLES)))
    ]
    triangles = [
        tuple(tuple(layer.data[loop].uv) for loop in triangle.loops) for triangle in selected
    ]
    face_ids = [triangle.polygon_index for triangle in selected]
    scan = scan_intersections(
        triangles,
        dimensions=2,
        face_ids=face_ids,
        max_triangles=params.get("max_triangles", DEFAULT_MAX_TRIANGLES),
        max_pairs=params.get("max_pairs", DEFAULT_MAX_PAIRS),
    )
    scan["triangles_total"] = triangle_total
    scan["triangles_omitted"] = triangle_total - len(selected)
    if scan["triangles_omitted"]:
        scan["coverage"] = "partial"
    scan["polygon_pairs"] = [[face_ids[first], face_ids[second]] for first, second in scan["pairs"]]
    sampled = triangles[: scan["triangles_tested"]]
    zero = [
        i
        for i, triangle in enumerate(sampled)
        if abs(_cross2(*triangle)) * 0.5 <= EPSILON * EPSILON
    ]
    tiles = set()
    outside = 0
    crossing = 0
    for triangle in sampled:
        center = tuple(sum(point[axis] for point in triangle) / 3 for axis in range(2))
        triangle_tiles = set()
        for point in triangle:
            # Nudge exact tile-edge vertices inward, avoiding a false extra tile.
            u, v = (
                math.floor(point[axis] + (center[axis] - point[axis]) * EPSILON)
                for axis in range(2)
            )
            if 0 <= u <= 9 and 0 <= v <= 99:
                triangle_tiles.add(1001 + u + v * 10)
            else:
                outside += 1
        tiles.update(triangle_tiles)
        crossing += len(triangle_tiles) > 1
    findings = []
    if zero:
        findings.append(
            finding(
                "UV_ZERO_AREA", "ERROR", "UV triangles have zero or near-zero area", len(zero), zero
            )
        )
    if scan["intersection_count"] and not params.get("allow_stacked_uvs", False):
        findings.append(
            finding(
                "UV_OVERLAP",
                "WARNING",
                "UV triangles overlap with positive area; declare intentional stacking explicitly",
                scan["intersection_count"],
                scan["pairs"],
            )
        )
    if outside:
        findings.append(
            finding(
                "UV_OUTSIDE_UDIM_RANGE",
                "WARNING",
                "Sampled UV vertices lie outside the supported UDIM grid; wrapping may be intentional",
                outside,
            )
        )
    if crossing:
        findings.append(
            finding(
                "UV_CROSSES_UDIM_TILE",
                "WARNING",
                "Triangles cross tile boundaries; verify the target exporter and texture layout",
                crossing,
            )
        )
    if scan["coverage"] != "complete":
        findings.append(
            finding(
                "PARTIAL_UV_CHECK",
                "INFO",
                "UV triangle or pair limits omitted coverage; absent overlaps do not establish a clean unwrap",
            )
        )
    return {
        **scan,
        "layer": layer.name,
        "overlap_count": scan["intersection_count"],
        "zero_area_triangles": len(zero),
        "occupied_udim_tiles": sorted(tiles),
        "udim_sampling": "sampled triangle vertices nudged toward each triangle centroid",
        "cross_tile_triangles": crossing,
        "allow_stacked_uvs": params.get("allow_stacked_uvs", False),
    }, findings


def _reachable_nodes(output):
    nodes = []
    stack = [output]
    seen = set()
    while stack and len(nodes) < MAX_GRAPH_NODES:
        node = stack.pop()
        if node.as_pointer() in seen:
            continue
        seen.add(node.as_pointer())
        nodes.append(node)
        for socket in node.inputs:
            stack.extend(link.from_node for link in socket.links)
    return nodes, not stack


def _upstream_images(socket):
    """Trace top-level graph paths; node groups are explicitly unsupported."""
    stack = [(link, None) for link in socket.links]
    seen = set()
    found = []
    while stack and len(seen) < MAX_GRAPH_NODES:
        link, channel = stack.pop()
        node = link.from_node
        key = (node.as_pointer(), link.from_socket.identifier, channel)
        if key in seen:
            continue
        seen.add(key)
        if node.type == "TEX_IMAGE" and node.image:
            found.append((node.image, channel or link.from_socket.name, link.from_socket.name))
        elif node.type not in {"GROUP", "GROUP_INPUT"}:
            if node.type in {"SEPRGB", "SEPARATE_COLOR"}:
                channel = link.from_socket.name
            for upstream_socket in node.inputs:
                stack.extend((upstream_link, channel) for upstream_link in upstream_socket.links)
    return found, not stack


def _material_slots(obj, mesh):
    slots = list(mesh.materials)
    for index, slot in enumerate(obj.material_slots):
        if slot.link == "OBJECT" and index < len(slots):
            slots[index] = slot.material
    return slots


def _material_diagnostics(obj, mesh):
    from .blender_adapter import _image_missing

    reports = []
    findings = []
    complete = True
    seen_materials = set()
    material_slots = _material_slots(obj, mesh)
    for slot_index, material in enumerate(material_slots):
        if material is None:
            findings.append(
                finding("EMPTY_MATERIAL_SLOT", "WARNING", f"Material slot {slot_index} is empty")
            )
            continue
        if material.as_pointer() in seen_materials:
            continue
        seen_materials.add(material.as_pointer())
        tree = material.node_tree
        outputs = (
            [
                node
                for node in tree.nodes
                if node.type == "OUTPUT_MATERIAL" and node.is_active_output
            ]
            if tree
            else []
        )
        output = outputs[0] if outputs else None
        if output is None:
            findings.append(
                finding(
                    "MATERIAL_OUTPUT_MISSING",
                    "WARNING",
                    f"{material.name}: active material output is missing",
                )
            )
            reports.append(
                {"name": material.name, "principled_surface": False, "coverage": "skipped"}
            )
            complete = False
            continue
        nodes, graph_complete = _reachable_nodes(output)
        complete = complete and graph_complete
        surface_links = output.inputs["Surface"].links
        principled = surface_links[0].from_node if surface_links else None
        direct_principled = principled is not None and principled.type == "BSDF_PRINCIPLED"
        unsupported = [
            {"name": node.name, "type": node.type}
            for node in nodes
            if node.type not in PORTABLE_NODE_TYPES
        ]
        if not direct_principled or unsupported:
            findings.append(
                finding(
                    "MATERIAL_PORTABILITY",
                    "WARNING",
                    f"{material.name}: graph exceeds the basic directly connected Principled material subset",
                )
            )
        if any(node.type == "GROUP" for node in nodes):
            complete = False
            graph_complete = False
            findings.append(
                finding(
                    "MATERIAL_GROUP_UNINSPECTED",
                    "INFO",
                    f"{material.name}: group socket semantics require export/bake review",
                )
            )
        images = {
            node.image.as_pointer(): node.image
            for node in nodes
            if node.type == "TEX_IMAGE" and node.image
        }
        channels = []
        checked_data_images = set()
        targets = []
        for node in nodes:
            if node.type == "NORMAL_MAP":
                targets.append(("Normal", node.inputs["Color"]))
                if node.space != "TANGENT":
                    findings.append(
                        finding(
                            "NORMAL_MAP_PORTABILITY",
                            "WARNING",
                            f"{material.name}: {node.name} uses {node.space} space; basic glTF normal maps require tangent space",
                        )
                    )
            if node.type == "BSDF_PRINCIPLED":
                targets.extend(
                    (name, node.inputs[name])
                    for name in ("Roughness", "Metallic")
                    if name in node.inputs
                )
                normal = node.inputs.get("Normal")
                if normal and any(
                    link.from_node.type not in {"NORMAL_MAP", "REROUTE"} for link in normal.links
                ):
                    findings.append(
                        finding(
                            "NORMAL_INPUT_PORTABILITY",
                            "WARNING",
                            f"{material.name}: normal input is not a basic Normal Map connection",
                        )
                    )
        for destination, socket in targets:
            upstream, trace_complete = _upstream_images(socket)
            graph_complete = graph_complete and trace_complete
            complete = complete and trace_complete
            for image, channel, image_output in upstream:
                channels.append(
                    {
                        "destination": destination,
                        "image": image.name,
                        "channel": channel,
                        "image_output": image_output,
                    }
                )
                if image_output != "Alpha" and image.as_pointer() not in checked_data_images:
                    checked_data_images.add(image.as_pointer())
                    if not image.colorspace_settings.is_data:
                        findings.append(
                            finding(
                                "DATA_MAP_COLOR_SPACE",
                                "WARNING",
                                f"{material.name}: {image.name} feeds {destination} with a color transform instead of a data color space",
                            )
                        )
        metallic = {
            (item["image"], item["channel"])
            for item in channels
            if item["destination"] == "Metallic"
        }
        roughness = {
            (item["image"], item["channel"])
            for item in channels
            if item["destination"] == "Roughness"
        }
        if metallic & roughness:
            findings.append(
                finding(
                    "DATA_CHANNEL_MAPPING",
                    "WARNING",
                    f"{material.name}: metallic and roughness share an image channel; verify intended packing",
                )
            )
        texture_reports = []
        for image in sorted(images.values(), key=lambda image: image.name):
            missing = _image_missing(image)
            if missing:
                findings.append(
                    finding(
                        "MATERIAL_IMAGE_MISSING",
                        "ERROR",
                        f"{material.name}: image {image.name} has a missing external file",
                    )
                )
            texture_reports.append(
                {
                    "name": image.name,
                    "width": image.size[0],
                    "height": image.size[1],
                    "color_space": image.colorspace_settings.name,
                    "is_data": image.colorspace_settings.is_data,
                    "source": image.source,
                    "missing_file": missing,
                }
            )
        reports.append(
            {
                "name": material.name,
                "principled_surface": direct_principled,
                "coverage": "complete" if graph_complete else "partial",
                "unsupported_nodes": unsupported[:SAMPLE_LIMIT],
                "channels": channels[:SAMPLE_LIMIT],
                "textures": texture_reports[:SAMPLE_LIMIT],
                "node_count": len(nodes),
            }
        )
    if not material_slots:
        findings.append(finding("MATERIALS_MISSING", "WARNING", "Object has no material slots"))
    return reports, findings, complete


def _density_mapping(material, mesh):
    """Return only directly interpretable image/UV mappings; never infer a bake."""
    metadata = {
        "image": None,
        "image_dimensions": None,
        "uv_layer": None,
        "coordinate_source": None,
    }

    def unknown(reason):
        return {**metadata, "unknown_reasons": [reason]}, None

    if material is None or material.node_tree is None:
        return unknown("missing_material_or_node_tree")
    outputs = [
        node
        for node in material.node_tree.nodes
        if node.type == "OUTPUT_MATERIAL" and node.is_active_output
    ]
    if len(outputs) != 1 or outputs[0].mute:
        return unknown("missing_or_ambiguous_active_output")
    links = outputs[0].inputs["Surface"].links
    if len(links) != 1 or links[0].from_node.type != "BSDF_PRINCIPLED" or links[0].from_node.mute:
        return unknown("surface_is_not_direct_active_principled")
    links = links[0].from_node.inputs["Base Color"].links
    if (
        len(links) != 1
        or links[0].from_node.type != "TEX_IMAGE"
        or links[0].from_socket.name != "Color"
    ):
        return unknown("base_color_is_not_direct_image_color")
    texture = links[0].from_node
    image = texture.image
    if texture.mute or image is None:
        return unknown("missing_or_muted_image_texture")
    metadata.update(image=image.name, image_dimensions=list(image.size))
    if image.source not in {"FILE", "GENERATED"}:
        return unknown("unsupported_image_source")
    if not all(type(value) is int and value > 0 for value in metadata["image_dimensions"]):
        return unknown("unknown_image_dimensions")
    from .blender_adapter import _image_missing

    if _image_missing(image):
        return unknown("missing_image_file")
    if texture.projection != "FLAT":
        return unknown("unsupported_image_projection")
    internal = getattr(texture, "texture_mapping", None)
    if internal and (
        tuple(internal.translation) != (0, 0, 0)
        or tuple(internal.rotation) != (0, 0, 0)
        or tuple(internal.scale) != (1, 1, 1)
        or internal.use_min
        or internal.use_max
        or internal.vector_type != "POINT"
    ):
        return unknown("unsupported_internal_texture_mapping")
    layer_name = None
    metadata["coordinate_source"] = "default_render_uv"
    vector_links = texture.inputs["Vector"].links
    if vector_links:
        if len(vector_links) != 1:
            return unknown("unsupported_vector_mapping")
        link = vector_links[0]
        node = link.from_node
        if node.mute or getattr(node, "from_instancer", False):
            return unknown("unsupported_vector_mapping")
        if node.type == "UVMAP" and link.from_socket.name == "UV":
            layer_name = node.uv_map or None
            metadata["coordinate_source"] = "uv_map_node"
        elif node.type == "TEX_COORD" and link.from_socket.name == "UV":
            metadata["coordinate_source"] = "texture_coordinate_uv"
        else:
            return unknown("unsupported_vector_mapping")
    layer = (
        mesh.uv_layers.get(layer_name)
        if layer_name
        else next((layer for layer in mesh.uv_layers if layer.active_render), None)
    )
    if layer is None:
        return unknown("missing_shader_uv_layer")
    metadata["uv_layer"] = layer.name
    return {**metadata, "unknown_reasons": []}, layer


def _texel_density(obj, mesh, params, context):
    """Area-equivalent texels per metre on bounded, explicitly supported triangles."""
    slots = _material_slots(obj, mesh)
    bindings, reports = {}, {}

    def row_for(slot_index):
        material = slots[slot_index] if 0 <= slot_index < len(slots) else None
        key = material.as_pointer() if material else ("missing", slot_index)
        if key not in reports:
            metadata, layer = _density_mapping(material, mesh)
            bindings[key] = layer
            reports[key] = {
                "material": material.name if material else None,
                "slot_indices": [],
                **metadata,
                "sampled_triangles": 0,
                "measured_triangles": 0,
                "unknown_reason_counts": {},
                "finite_sampled_world_area_m2": 0.0,
                "measured_world_area_m2": 0.0,
                "measured_uv_area": 0.0,
                "measured_texel_area": 0.0,
                "area_equivalent_texels_per_meter": None,
                "minimum_triangle_texels_per_meter": None,
                "maximum_triangle_texels_per_meter": None,
            }
        row = reports[key]
        if slot_index not in row["slot_indices"]:
            row["slot_indices"].append(slot_index)
        return row, bindings[key]

    for index in range(len(slots)):
        row_for(index)
    world = (
        obj.evaluated_get(context.evaluated_depsgraph_get()).matrix_world
        if params.get("evaluated", True)
        else obj.matrix_world
    )
    scale = context.scene.unit_settings.scale_length
    transform_valid = (
        math.isfinite(scale)
        and scale > 0
        and all(math.isfinite(value) for row in world for value in row)
    )
    total = len(mesh.loop_triangles)
    sampled = min(total, params.get("max_triangles", DEFAULT_MAX_TRIANGLES))
    for index in range(sampled):
        triangle = mesh.loop_triangles[index]
        row, layer = row_for(triangle.material_index)
        row["sampled_triangles"] += 1
        reason = None
        world_area = 0.0
        if not transform_valid:
            reason = "non_finite_or_invalid_world_transform_or_units"
        else:
            points = [world @ mesh.vertices[vertex].co for vertex in triangle.vertices]
            if not all(math.isfinite(value) for point in points for value in point):
                reason = "non_finite_world_triangle"
            else:
                world_area = (
                    (points[1] - points[0]).cross(points[2] - points[0]).length * 0.5 * scale**2
                )
                if not math.isfinite(world_area):
                    reason = "non_finite_world_triangle"
                elif world_area <= EPSILON * EPSILON:
                    reason = "degenerate_world_triangle"
                else:
                    row["finite_sampled_world_area_m2"] += world_area
        if reason is None and layer is None:
            reason = row["unknown_reasons"][0]
        if reason is None:
            coordinates = [tuple(layer.data[loop].uv) for loop in triangle.loops]
            if not all(math.isfinite(value) for point in coordinates for value in point):
                reason = "non_finite_uv_triangle"
            elif not all(
                -EPSILON <= value <= 1 + EPSILON for point in coordinates for value in point
            ):
                reason = "uv_outside_single_tile"
            else:
                uv_area = abs(_cross2(*coordinates)) * 0.5
                if uv_area <= EPSILON * EPSILON:
                    reason = "degenerate_uv_triangle"
                else:
                    width, height = row["image_dimensions"]
                    texel_area = uv_area * width * height
                    density = math.sqrt(texel_area / world_area)
                    if not math.isfinite(density):
                        reason = "non_finite_density"
        if reason is not None:
            row["unknown_reason_counts"][reason] = row["unknown_reason_counts"].get(reason, 0) + 1
            if reason not in row["unknown_reasons"]:
                row["unknown_reasons"].append(reason)
            continue
        row["measured_triangles"] += 1
        row["measured_world_area_m2"] += world_area
        row["measured_uv_area"] += uv_area
        row["measured_texel_area"] += texel_area
        row["minimum_triangle_texels_per_meter"] = min(
            density,
            row["minimum_triangle_texels_per_meter"]
            if row["minimum_triangle_texels_per_meter"] is not None
            else density,
        )
        row["maximum_triangle_texels_per_meter"] = max(
            density,
            row["maximum_triangle_texels_per_meter"]
            if row["maximum_triangle_texels_per_meter"] is not None
            else density,
        )
    for row in reports.values():
        row["unknown_triangles"] = row["sampled_triangles"] - row["measured_triangles"]
        row["coverage"] = (
            "not_sampled"
            if not row["sampled_triangles"]
            else "unknown"
            if not row["measured_triangles"]
            else "partial"
            if row["unknown_triangles"] or sampled < total
            else "complete"
        )
        if row["measured_triangles"]:
            row["area_equivalent_texels_per_meter"] = math.sqrt(
                row["measured_texel_area"] / row["measured_world_area_m2"]
            )
    measured = sum(row["measured_triangles"] for row in reports.values())
    return {
        "unit": "texels_per_meter_area_equivalent",
        "coverage": "skipped"
        if not sampled
        else "unknown"
        if not measured
        else "complete"
        if measured == total
        else "partial",
        "triangles_total": total,
        "triangles_sampled": sampled,
        "triangles_measured": measured,
        "triangles_omitted": total - sampled,
        "materials": list(reports.values()),
        "limits": [
            "sqrt(sum(UV triangle area * actual image width * height) / sum(world triangle area in square metres)); range is per measured triangle",
            "Area-equivalent density is not minimum directional resolution or an anisotropy/distortion guarantee",
            "Only direct active Principled base-color images, flat projection and explicit/default UV coordinates in one 0..1 tile are supported",
            "Mapping/procedural/generated/object coordinates, tiled/sequence/movie images and ambiguous graphs are unknown",
            "UV diagnostic layer overrides do not change the shader's actual UV selection",
            "Triangle sampling uses max_triangles; weighted values describe only measured samples, with reused UV area counted per triangle",
            "No universal density target or visual-quality pass is assigned; shot coverage, asset class and target hardware need review",
        ],
    }


def inspect_surfaces(params: dict, context=None) -> dict:
    """Inspect one object's evaluated UVs and referenced material graph metadata."""
    validate_params(params, ("allow_stacked_uvs", "uv_layer"))
    if "uv_layer" in params and (
        not isinstance(params["uv_layer"], str)
        or not params["uv_layer"]
        or len(params["uv_layer"]) > 256
    ):
        raise ValueError("uv_layer must be a nonempty UV layer name")
    with inspected_mesh(params, context) as (obj, mesh):
        import bpy

        uv, findings = _uv_diagnostics(mesh, params)
        materials, material_findings, complete = _material_diagnostics(obj, mesh)
        density = _texel_density(obj, mesh, params, context or bpy.context)
        return {
            "schema_version": "1.0",
            "object_name": obj.name,
            "evaluated": params.get("evaluated", True),
            "coverage": "complete"
            if uv["coverage"] == "complete" and complete and density["coverage"] == "complete"
            else "partial",
            "uv": uv,
            "materials": materials,
            "texel_density": density,
            "findings": findings + material_findings,
            "limits": [
                "Current-frame UV triangle sampling only",
                "UDIM coordinates are not wrapped",
                "Texel density is bounded and conservative; no bake result, exporter roundtrip or visual acceptance",
                "Material groups and procedural shading need bake/export review",
                "Scene texture sequences are checked at the current file only",
            ],
        }
