"""Scoped high-to-low tangent-normal baking in an isolated Cycles scene."""

from __future__ import annotations

import math
import threading

import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

from .mesh_diagnostics import inspected_mesh
from .normal_inspection import inspect_normal_image
from .static_data import require_static_mesh_material_data
from .surface_diagnostics import _uv_diagnostics


def _world_axis_lengths(obj):
    """Detached copies cannot preserve sheared world transforms as ordinary LRS."""
    matrix = obj.matrix_world
    columns = [matrix.to_3x3().col[index].copy() for index in range(3)]
    lengths = [column.length for column in columns]
    if any(not math.isfinite(value) for row in matrix for value in row) or any(
        not math.isfinite(length) or length <= 1e-12 for length in lengths
    ):
        raise ValueError("Bake source world transforms must be finite and nonsingular")
    if any(
        abs(columns[first].dot(columns[second])) > 1e-6 * lengths[first] * lengths[second]
        for first, second in ((0, 1), (0, 2), (1, 2))
    ):
        raise ValueError(
            "Bake source world transforms must not contain shear; apply transforms on a separate derivative first"
        )
    return lengths


def _request(params, context):
    defaults = {
        "high_object": "",
        "low_object": "",
        "cage_object": "",
        "resolution": 1024,
        "ray_distance": 0.1,
        "max_memory_mb": 512,
        "margin": 8,
        "dry_run": True,
    }
    if not isinstance(params, dict) or set(params) - set(defaults):
        raise ValueError("Unknown or invalid bake parameters")
    p = dict(defaults, **params)
    if type(p["dry_run"]) is not bool:
        raise ValueError("dry_run must be a boolean")
    for key, lower, upper in (
        ("resolution", 64, 8192),
        ("max_memory_mb", 1, 32768),
        ("margin", 0, 64),
    ):
        if type(p[key]) is not int or not lower <= p[key] <= upper:
            raise ValueError(f"{key} must be an integer between {lower} and {upper}")
    ray = p["ray_distance"]
    if (
        isinstance(ray, bool)
        or not isinstance(ray, (int, float))
        or not math.isfinite(ray)
        or not 0.0001 <= ray <= 10
    ):
        raise ValueError("ray_distance must be a finite metre distance between 0.0001 and 10")
    objects = []
    for key in ("high_object", "low_object"):
        if not isinstance(p[key], str) or not p[key]:
            raise ValueError(f"{key} must be an exact active-scene object name")
        matches = [obj for obj in context.scene.objects if obj.name == p[key]]
        if len(matches) != 1:
            raise ValueError("Object name is missing or ambiguous in the active scene")
        obj = matches[0]
        if obj.type != "MESH" or obj.library or obj.data.library:
            raise ValueError("Bake sources must be local meshes in the active scene")
        if obj.animation_data or obj.data.shape_keys or obj.constraints or obj.vertex_groups:
            raise ValueError(
                "Bake currently supports static, unconstrained, unrigged sources without shape keys"
            )
        if any(
            modifier.type
            not in {"BEVEL", "WEIGHTED_NORMAL", "SUBSURF", "TRIANGULATE", "SOLIDIFY", "SMOOTH"}
            for modifier in obj.modifiers
        ):
            raise ValueError(
                "Bake unsupported modifiers into a separate source before normal baking"
            )
        if not obj.data.polygons:
            raise ValueError("Bake sources must contain faces")
        objects.append(obj)
    high, low = objects
    if high == low:
        raise ValueError("High and low sources must be different objects")
    if low.data.uv_layers.active is None:
        raise ValueError("Low mesh needs an active nondegenerate UV map")
    uv = low.data.uv_layers.active
    uv_area = 0.0
    for face in low.data.polygons:
        coordinates = [uv.data[index].uv for index in face.loop_indices]
        if not all(math.isfinite(value) for coordinate in coordinates for value in coordinate):
            raise ValueError("Low mesh UV coordinates must be finite")
        uv_area += (
            abs(
                sum(
                    coordinates[index].x * coordinates[(index + 1) % len(coordinates)].y
                    - coordinates[(index + 1) % len(coordinates)].x * coordinates[index].y
                    for index in range(len(coordinates))
                )
            )
            / 2
        )
    if uv_area <= 1e-10:
        raise ValueError("Low mesh needs an active nondegenerate UV map")
    cage = None
    if not isinstance(p["cage_object"], str):
        raise ValueError("cage_object must be an exact local mesh name")
    if p["cage_object"]:
        matches = [obj for obj in context.scene.objects if obj.name == p["cage_object"]]
        if len(matches) != 1:
            raise ValueError("Cage name is missing or ambiguous")
        cage = matches[0]
        if (
            cage.type != "MESH"
            or cage.library
            or cage.data.library
            or cage.override_library
            or cage in {high, low}
            or cage.modifiers
            or low.modifiers
            or cage.animation_data
            or cage.data.shape_keys
            or cage.constraints
            or cage.vertex_groups
        ):
            raise ValueError(
                "Cage requires a separate local static mesh; cage and low modifiers must be applied on derivatives first"
            )
        if len(cage.data.vertices) != len(low.data.vertices) or [
            tuple(face.vertices) for face in cage.data.polygons
        ] != [tuple(face.vertices) for face in low.data.polygons]:
            raise ValueError(
                "Cage topology must match low vertex count and ordered face indices exactly"
            )
        if any(not math.isfinite(value) for vertex in cage.data.vertices for value in vertex.co):
            raise ValueError("Cage coordinates must be finite")
    require_static_mesh_material_data((high, low, *((cage,) if cage else ())))
    with inspected_mesh({"object_name": low.name}, context) as (_, evaluated_low):
        uv_report, _ = _uv_diagnostics(
            evaluated_low, {"max_triangles": 200000, "max_pairs": 2000000}
        )
        evaluated_uv = evaluated_low.uv_layers.active
        if (
            evaluated_uv is None
            or any(
                not math.isfinite(value) or not -1e-7 <= value <= 1 + 1e-7
                for item in evaluated_uv.data
                for value in item.uv
            )
            or uv_report["coverage"] != "complete"
            or uv_report["overlap_count"]
            or uv_report["zero_area_triangles"]
        ):
            raise ValueError(
                "Bake UVs require a complete bounded check, no overlapping/zero-area triangles and one 0..1 tile"
            )
    for source in (high, low, *((cage,) if cage else ())):
        lengths = _world_axis_lengths(source)
        if (
            source == low
            and cage is None
            and (
                max(lengths) - min(lengths) > max(lengths) * 1e-6
                or source.matrix_world.to_3x3().determinant() <= 0
            )
        ):
            raise ValueError(
                "Implicit cage requires a positive uniform low-object world scale; use an explicit matching cage for nonuniform scale or apply transforms on a separate derivative"
            )
    estimate = p["resolution"] ** 2 * 4 * 4 * 3
    if estimate > p["max_memory_mb"] * 1024 * 1024:
        raise ValueError(
            "Estimated image working memory exceeds max_memory_mb budget; lower resolution or explicitly increase budget"
        )
    return p, high, low, cage, estimate, uv_report


def _projection(stage, high, low, distance, cage=None):
    """Bounded geometric check: avoid claiming success when every ray misses."""
    with bpy.context.temp_override(scene=stage, view_layer=stage.view_layers[0]):
        graph = bpy.context.evaluated_depsgraph_get()
        high_evaluated, low_evaluated = high.evaluated_get(graph), low.evaluated_get(graph)
        high_mesh, low_mesh = high_evaluated.to_mesh(), low_evaluated.to_mesh()
        try:
            vertices = [high_evaluated.matrix_world @ vertex.co for vertex in high_mesh.vertices]
            tree = BVHTree.FromPolygons(
                vertices, [tuple(face.vertices) for face in high_mesh.polygons]
            )
            low_mesh.calc_loop_triangles()
            triangles = low_mesh.loop_triangles
            step = max(1, math.ceil(len(triangles) / 256))
            hits = samples = 0
            for triangle in list(triangles)[::step]:
                a, b, c = (
                    low_evaluated.matrix_world @ low_mesh.vertices[index].co
                    for index in triangle.vertices
                )
                normal = (b - a).cross(c - a)
                if normal.length < 1e-10:
                    continue
                normal.normalize()
                center = (a + b + c) / 3
                origin = center + normal * distance
                direction, length = -normal, distance * 2
                if cage is not None:
                    origin = (
                        sum(
                            (
                                cage.matrix_world @ cage.data.vertices[index].co
                                for index in triangle.vertices
                            ),
                            a * 0,
                        )
                        / 3
                    )
                    direction = center - origin
                    if direction.length < 1e-10:
                        raise ValueError("Cage must be offset from the low surface")
                    direction.normalize()
                    # Cycles applies max_ray_distance from the cage origin too.
                    # Extending this check to the low surface could report hits
                    # that the actual limited bake cannot reach.
                    length = distance * 2
                result = tree.ray_cast(origin, direction, length)
                samples += 1
                hits += result[0] is not None
            if not hits:
                raise ValueError("No high surface was found inside sampled projection rays")
            return {
                "sampled_triangles": samples,
                "hits": hits,
                "hit_fraction": hits / samples,
                "max_ray_distance": distance * 2,
                "scope": "At most 256 face-centroid rays; not per-texel coverage proof",
            }
        finally:
            high_evaluated.to_mesh_clear()
            low_evaluated.to_mesh_clear()


def _bake(stage, high, low, params):
    with bpy.context.temp_override(
        scene=stage,
        view_layer=stage.view_layers[0],
        active_object=low,
        selected_objects=[high, low],
        selected_editable_objects=[high, low],
    ):
        result = bpy.ops.object.bake(
            type="NORMAL",
            normal_space="TANGENT",
            normal_r="POS_X",
            normal_g="POS_Y",
            normal_b="POS_Z",
            use_selected_to_active=True,
            use_cage=bool(params["cage_object"]),
            cage_object=params["cage_object"],
            cage_extrusion=params["cage_extrusion_local"],
            max_ray_distance=params["ray_distance"] * 2,
            margin=params["margin"],
            use_clear=True,
        )
        if result != {"FINISHED"}:
            raise RuntimeError("Cycles normal bake did not finish")


def _image_evidence(image):
    return inspect_normal_image(image)


def bake_normal(params, context=None):
    """Bake a new packed tangent normal image and hidden low-mesh derivative."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender access must run on the main thread")
    context = context or bpy.context
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before baking")
    if any(
        getattr(bpy.app.handlers, name)
        for name in (
            "frame_change_pre",
            "frame_change_post",
            "depsgraph_update_pre",
            "depsgraph_update_post",
        )
    ):
        raise ValueError("Normal baking requires no active frame/dependency-graph handlers")
    source_units = context.scene.unit_settings.scale_length
    if not math.isfinite(source_units) or source_units <= 0:
        raise ValueError("Source scene requires finite positive metres per Blender unit")
    p, source_high, source_low, source_cage, estimate, uv_report = _request(params, context)
    # Cycles cage_extrusion is measured in the low object's local coordinates,
    # whereas max_ray_distance is measured in staging-world coordinates.
    # A scalar extrusion is physically uniform only for a uniform low transform.
    extrusion = (
        0.0
        if source_cage is not None
        else p["ray_distance"] / (source_units * _world_axis_lengths(source_low)[0])
    )
    if extrusion > bpy.ops.object.bake.get_rna_type().properties["cage_extrusion"].hard_max:
        raise ValueError(
            "Implicit cage extrusion exceeds Blender's local-coordinate limit; use an explicit matching cage"
        )
    result = {
        "dry_run": p["dry_run"],
        "parameters": p,
        "estimated_image_working_bytes": estimate,
        "memory_scope": "Three RGBA float image buffers only; geometry, BVH, Cycles and driver memory are additional",
        "normal_convention": "Tangent +X +Y +Z (OpenGL)",
        "cage": source_cage.name if source_cage else None,
        "unit_conversion": {
            "source_metres_per_blender_unit": source_units,
            "bake_metres_per_blender_unit": 1.0,
            "staging_world_scale": source_units,
            "returned_geometry": "original authoring scene coordinates",
            "implicit_cage_extrusion_local_units": extrusion if source_cage is None else None,
            "projection_distance_metres": p["ray_distance"],
            "maximum_ray_length_metres": p["ray_distance"] * 2,
        },
        "uv_validation": uv_report,
        "visual_acceptance": "not_reviewed",
        "limitations": [
            "Single 0..1 atlas only; complete bounded UV overlap/area checks do not establish texel density or rendered seam quality",
            "Projection samples and pixel validity do not prove every texel captured the intended high surface",
            "A flat but valid normal map can be correct; detail_present reports variation separately",
            "Source/rendered comparison and native normal convention still require review",
            "Both preview and apply evaluate geometry and refuse active frame/dependency-graph handlers",
            "Copied mesh/shape/material/node-tree dependencies, including nested groups, must be static with no animation data; source actions/drivers are not cleared",
            "Implicit cages require positive uniform low-world scale; explicit matching cages support nonuniform scale. Sheared/singular source worlds require an applied separate derivative",
        ],
    }
    if p["dry_run"]:
        return result
    original_scene, original_layer, window = context.scene, context.view_layer, context.window
    original_active = original_layer.objects.active
    original_selected = [
        (obj, obj.select_get(view_layer=original_layer)) for obj in original_layer.objects
    ]
    original_frame = (original_scene.frame_current, original_scene.frame_subframe)
    created = []
    keep = set()

    def own(kind, value):
        created.append((kind, value))
        return value

    try:
        stage = own("scenes", bpy.data.scenes.new("FW_NormalBakeStage"))
        stage.render.engine = "CYCLES"
        stage.cycles.device = "CPU"
        stage.cycles.samples = 1
        stage.unit_settings.system = "METRIC"
        stage.unit_settings.scale_length = 1
        copies = []
        for source in (source_high, source_low):
            copy = own("objects", source.copy())
            copy.data = own("meshes", source.data.copy())
            copy.parent = None
            copy.matrix_world = Matrix.Scale(source_units, 4) @ source.matrix_world
            copy.hide_viewport = False
            copy.hide_render = False
            stage.collection.objects.link(copy)
            copy.select_set(True, view_layer=stage.view_layers[0])
            copies.append(copy)
        high, low = copies
        cage = None
        if source_cage is not None:
            cage = own("objects", source_cage.copy())
            cage.data = own("meshes", source_cage.data.copy())
            cage.parent = None
            cage.matrix_world = Matrix.Scale(source_units, 4) @ source_cage.matrix_world
            cage.hide_viewport = False
            cage.hide_render = True
            stage.collection.objects.link(cage)
        low.name = source_low.name + "_NormalBake"
        stage.view_layers[0].objects.active = low
        stage.view_layers[0].update()
        result["projection"] = _projection(stage, high, low, p["ray_distance"], cage)
        image = own(
            "images",
            bpy.data.images.new(
                low.name + "_NormalGL",
                width=p["resolution"],
                height=p["resolution"],
                alpha=True,
                float_buffer=True,
                is_data=True,
            ),
        )
        image.colorspace_settings.name = "Non-Color"
        image.file_format = "OPEN_EXR"
        image["framewright_source_high"] = source_high.name
        image["framewright_source_low"] = source_low.name
        materials = []
        shader_links = []
        # Mesh slot removal resets polygon indices and drops object overrides.
        # Capture effective surfaces and their link modes before rebuilding the
        # owned slots, so the bake cannot silently change the derivative's look.
        originals = [(slot.link, slot.material) for slot in low.material_slots] or [("DATA", None)]
        polygon_material_indices = [face.material_index for face in low.data.polygons]
        low.data.materials.clear()
        for index, (link, original) in enumerate(originals):
            material = own(
                "materials",
                original.copy()
                if original
                else bpy.data.materials.new(low.name + f"_Surface{index}"),
            )
            material.use_nodes = True
            shaders = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
            if len(shaders) != 1:
                raise ValueError(
                    "Low-material baking currently requires one Principled BSDF per slot"
                )
            node = material.node_tree.nodes.new("ShaderNodeTexImage")
            node.name = "Framewright Tangent Normal"
            node.image = image
            node.label = "Baked tangent normal (Non-Color)"
            for other in material.node_tree.nodes:
                other.select = other == node
            material.node_tree.nodes.active = node
            low.data.materials.append(material)
            low.material_slots[index].link = link
            low.material_slots[index].material = material
            materials.append(material)
            shader_links.append((material, node, shaders[0]))
        for face, index in zip(low.data.polygons, polygon_material_indices, strict=True):
            face.material_index = index
        _bake(
            stage,
            high,
            low,
            {**p, "cage_object": cage.name if cage else "", "cage_extrusion_local": extrusion},
        )
        result.update(_image_evidence(image))
        for material, texture, shader in shader_links:
            normal = material.node_tree.nodes.new("ShaderNodeNormalMap")
            normal.space = "TANGENT"
            normal.uv_map = low.data.uv_layers.active.name
            material.node_tree.links.new(texture.outputs["Color"], normal.inputs["Color"])
            material.node_tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
        image.pack()
        collection = own("collections", bpy.data.collections.new("FW_NormalBake"))
        collection["framewright_owner"] = "baking"
        original_scene.collection.children.link(collection)
        collection.objects.link(low)
        stage.collection.objects.unlink(low)
        # The bake scene uses metres; the retained derivative belongs back in
        # the original scene's coordinates with the source's exact placement.
        low.matrix_world = source_low.matrix_world.copy()
        low["framewright_owner"] = "baking"
        low["framewright_source_high"] = source_high.name
        low["framewright_source_low"] = source_low.name
        low.hide_render = True
        low.hide_set(True, view_layer=original_layer)
        keep = {item.as_pointer() for item in (low, low.data, image, collection, *materials)}
        result.update(
            derivative=low.name,
            image=image.name,
            collection=collection.name,
            materials=[material.name for material in materials],
            resolution=[p["resolution"], p["resolution"]],
            packed=True,
            hidden=True,
        )
        return result
    finally:
        if window is not None:
            window.scene = original_scene
            window.view_layer = original_layer
        if (original_scene.frame_current, original_scene.frame_subframe) != original_frame:
            original_scene.frame_set(original_frame[0], subframe=original_frame[1])
        for obj, selected in original_selected:
            obj.select_set(selected, view_layer=original_layer)
        original_layer.objects.active = original_active
        for kind in ("objects", "scenes", "collections", "meshes", "materials", "images"):
            for item_kind, item in reversed(created):
                if item_kind == kind and item.as_pointer() not in keep:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)
