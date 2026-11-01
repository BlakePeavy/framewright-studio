"""Owned Blender tests for shared material atlases and exact source preservation."""

from __future__ import annotations

import importlib
import json
import math
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import interchange, production_assets  # noqa: E402


def handler():
    return importlib.import_module("framewright.material_atlas")


def inventory():
    return {
        kind: sorted((item.name, item.as_pointer()) for item in getattr(bpy.data, kind))
        for kind in (
            "objects",
            "meshes",
            "materials",
            "images",
            "collections",
            "scenes",
            "actions",
            "node_groups",
        )
    }


def source_state(objects):
    records = []
    for obj in objects:
        row = {
            "name": obj.name,
            "id": obj.as_pointer(),
            "matrix": [list(row) for row in obj.matrix_world],
            "parent": obj.parent.as_pointer() if obj.parent else None,
            "parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
            "visibility": [obj.hide_render, obj.hide_viewport, obj.hide_get()],
        }
        if obj.type == "MESH":
            row.update(
                data=obj.data.as_pointer(),
                vertices=[list(vertex.co) for vertex in obj.data.vertices],
                faces=[list(face.vertices) for face in obj.data.polygons],
                face_materials=[face.material_index for face in obj.data.polygons],
                uv=[
                    (layer.name, layer.active_render, [list(item.uv) for item in layer.data])
                    for layer in obj.data.uv_layers
                ],
                materials=[
                    (slot.link, slot.material.as_pointer() if slot.material else None)
                    for slot in obj.material_slots
                ],
            )
            graphs = []
            for slot in obj.material_slots:
                if not slot.material or not slot.material.node_tree:
                    continue
                tree = slot.material.node_tree
                nodes = []
                for node in tree.nodes:
                    values = []
                    for socket in node.inputs:
                        if not hasattr(socket, "default_value"):
                            continue
                        value = socket.default_value
                        if not isinstance(value, (str, bool, int, float)):
                            try:
                                value = list(value)
                            except TypeError:
                                continue
                        values.append((socket.identifier, value))
                    nodes.append((node.name, node.type, node.mute, values))
                graphs.append(
                    (
                        tree.as_pointer(),
                        nodes,
                        [
                            (
                                link.from_node.name,
                                link.from_socket.identifier,
                                link.to_node.name,
                                link.to_socket.identifier,
                            )
                            for link in tree.links
                        ],
                    )
                )
            row["graphs"] = graphs
        records.append(row)
    return json.dumps(records, sort_keys=True, allow_nan=False)


def material(name, color, *, metal=0, roughness=0.5):
    mat = bpy.data.materials.new(name)
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metal
    shader.inputs["Roughness"].default_value = roughness
    return mat


def cube(name, surface, x=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(surface)
    return obj


def png_pixel(image, u, v):
    data = bytes(image.packed_file.data)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset, compressed = 8, []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, *_ = struct.unpack(">IIBBBBB", payload)
            assert (depth, color) == (16, 2)
        if kind == b"IDAT":
            compressed.append(payload)
        offset += length + 12
    raw = zlib.decompress(b"".join(compressed))
    x, y = min(width - 1, int(u * width)), min(height - 1, int(v * height))
    offset = (height - 1 - y) * (width * 6 + 1)
    assert raw[offset] == 0
    return [
        component / 65535
        for component in struct.unpack(">HHH", raw[offset + 1 + x * 6 : offset + 7 + x * 6])
    ]


class MaterialAtlasTests(unittest.TestCase):
    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.context.scene.frame_set(1)

    def test_preview_actual_cabinet_does_not_allocate_or_change_sources(self):
        built = production_assets.build_prop({"name": "AtlasSource", "dry_run": False})
        objects = [bpy.data.objects[name] for name in built["objects"]]
        before, state = inventory(), source_state(objects)
        result = handler().bake_material_atlas(
            {"object_names": built["objects"], "resolution": 128}
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source_objects"], sorted(built["objects"]))
        self.assertGreater(result["evaluated_geometry"]["triangles"], 100)
        self.assertEqual(result["input_image_decoded_bytes"], 0)
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state(objects), state)

    def test_two_parts_share_four_packed_maps_and_preserve_parent(self):
        red = cube("RedMetal", material("RedMetalSurface", (0.3, 0.035, 0.01), metal=1), -0.65)
        blue = cube("BlueMatte", material("BlueSurface", (0.025, 0.11, 0.45), roughness=0.8), 0.65)
        pivot = bpy.data.objects.new("AssemblyPivot", None)
        bpy.context.scene.collection.objects.link(pivot)
        for obj in (red, blue):
            obj.parent = pivot
        bpy.context.view_layer.update()
        sources = [red, blue, pivot]
        state = source_state(sources)
        original_uvs = {obj.name: len(obj.data.uv_layers) for obj in (red, blue)}
        result = handler().bake_material_atlas(
            {
                "object_names": [obj.name for obj in sources],
                "resolution": 128,
                "margin": 4,
                "dry_run": False,
            }
        )
        self.assertEqual(set(result["maps"]), {"base_color", "roughness", "metallic", "normal"})
        images = [bpy.data.images[row["image"]] for row in result["maps"].values()]
        self.assertEqual(len(set(images)), 4)
        self.assertTrue(all(image.packed_file for image in images))
        self.assertTrue(all(tuple(image.size) == (128, 128) for image in images))
        self.assertEqual(source_state(sources), state)
        copies = {name: bpy.data.objects[value] for name, value in result["derivatives"].items()}
        self.assertEqual(set(copies), {obj.name for obj in sources})
        for source in (red, blue):
            copy = copies[source.name]
            self.assertIsNot(copy.data, source.data)
            self.assertIs(copy.parent, copies[pivot.name])
            self.assertEqual(copy.matrix_world, source.matrix_world)
            self.assertEqual(len(copy.data.uv_layers), original_uvs[source.name] + 1)
            self.assertIsNotNone(copy.data.uv_layers.get(result["uv_layer"]))
            self.assertTrue(copy.hide_render)
            self.assertTrue(copy.hide_get() or copy.hide_viewport)
        self.assertIs(copies[red.name].active_material, copies[blue.name].active_material)
        self.assertEqual(images[0].source, "FILE")
        for source, expected_color, expected_metal, expected_rough in (
            (red, (0.3, 0.035, 0.01), 1, 0.5),
            (blue, (0.025, 0.11, 0.45), 0, 0.8),
        ):
            copied = copies[source.name]
            layer = copied.data.uv_layers[result["uv_layer"]]
            for triangle in copied.data.loop_triangles:
                u, v = [
                    sum(layer.data[index].uv[axis] for index in triangle.loops) / 3
                    for axis in (0, 1)
                ]
                color = png_pixel(bpy.data.images[result["maps"]["base_color"]["image"]], u, v)
                linear = [
                    value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                    for value in color
                ]
                for actual, expected in zip(linear, expected_color, strict=True):
                    self.assertAlmostEqual(actual, expected, delta=0.001)
                for role, expected in (("metallic", expected_metal), ("roughness", expected_rough)):
                    values = png_pixel(bpy.data.images[result["maps"][role]["image"]], u, v)
                    self.assertTrue(all(abs(value - expected) < 0.001 for value in values))
                normal = png_pixel(bpy.data.images[result["maps"]["normal"]["image"]], u, v)
                self.assertLess(math.dist(normal, (0.5, 0.5, 1)), 0.001)

    def test_unsupported_transmission_and_view_dependent_graphs_fail_without_outputs(self):
        mat = material("UnsupportedGlass", (0.4, 0.3, 0.2))
        obj = cube("UnsupportedSource", mat)
        shader = mat.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Transmission Weight"].default_value = 0.5
        before, state = inventory(), source_state([obj])
        for dry in (True, False):
            with self.assertRaisesRegex(ValueError, "[Tt]ransmission|opaque"):
                handler().bake_material_atlas({"object_names": [obj.name], "dry_run": dry})
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state([obj]), state)
        shader.inputs["Transmission Weight"].default_value = 0
        info = mat.node_tree.nodes.new("ShaderNodeObjectInfo")
        mat.node_tree.links.new(info.outputs["Random"], shader.inputs["Base Color"])
        before = inventory()
        with self.assertRaisesRegex(ValueError, "[Rr]andom|[Uu]nsupported|OBJECT_INFO"):
            handler().bake_material_atlas({"object_names": [obj.name], "dry_run": False})
        self.assertEqual(inventory(), before)

    def test_missing_parent_and_animated_data_are_rejected_before_copying(self):
        obj = cube("AnimatedSurface", material("StaticMaterial", (0.2, 0.1, 0.03)))
        parent = bpy.data.objects.new("OmittedParent", None)
        bpy.context.scene.collection.objects.link(parent)
        obj.parent = parent
        before = inventory()
        with self.assertRaisesRegex(ValueError, "parent|hierarchy"):
            handler().bake_material_atlas({"object_names": [obj.name]})
        self.assertEqual(inventory(), before)
        obj.parent = None
        obj.data.animation_data_create()
        before = inventory()
        with self.assertRaisesRegex(ValueError, "[Aa]nimation|[Ss]tatic|drivers"):
            handler().bake_material_atlas({"object_names": [obj.name]})
        self.assertEqual(inventory(), before)

    def test_active_callback_rejected_without_invocation(self):
        obj = cube("CallbackSource", material("CallbackMaterial", (0.2, 0.1, 0.03)))
        calls = []

        def callback(*args):
            calls.append(True)

        bpy.app.handlers.depsgraph_update_pre.append(callback)
        try:
            before = inventory()
            with self.assertRaisesRegex(ValueError, "handler|callback"):
                handler().bake_material_atlas({"object_names": [obj.name]})
            self.assertEqual(calls, [])
            self.assertEqual(inventory(), before)
        finally:
            bpy.app.handlers.depsgraph_update_pre.remove(callback)

    def test_partial_bake_failure_removes_only_owned_outputs(self):
        obj = cube("FailureSource", material("FailureMaterial", (0.2, 0.1, 0.03)))
        module = handler()
        before, state = inventory(), source_state([obj])
        with patch.object(module, "_bake_pass", side_effect=RuntimeError("injected bake failure")):
            with self.assertRaisesRegex(RuntimeError, "injected bake failure"):
                module.bake_material_atlas(
                    {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": False}
                )
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state([obj]), state)

    def test_bake_callbacks_and_lost_principled_semantics_refuse_before_allocation(self):
        obj = cube("AdmissionSource", material("AdmissionMaterial", (0.1, 0.2, 0.3)))
        module = handler()
        calls = []

        def callback(*args):
            calls.append(True)

        for name in ("object_bake_pre", "object_bake_complete", "object_bake_cancel"):
            handlers = getattr(bpy.app.handlers, name)
            handlers.append(callback)
            try:
                with self.assertRaisesRegex(ValueError, "handler|callback"):
                    module.bake_material_atlas({"object_names": [obj.name]})
                self.assertEqual(calls, [])
            finally:
                handlers.remove(callback)
        shader = obj.active_material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Specular Tint"].default_value = (0.5, 1, 1, 1)
        with self.assertRaisesRegex(ValueError, "Tint|semantic"):
            module.bake_material_atlas({"object_names": [obj.name]})
        shader.inputs["Specular Tint"].default_value = (1, 1, 1, 1)
        obj.active_material.use_backface_culling = True
        with self.assertRaisesRegex(ValueError, "backface|culling"):
            module.bake_material_atlas({"object_names": [obj.name]})

    def test_uv_overlap_guard_rejects_two_complete_stacked_parts(self):
        first = cube("OverlappingFirst", material("OverlapMaterial", (0.2, 0.3, 0.4)))
        second = first.copy()
        second.data = first.data.copy()
        bpy.context.scene.collection.objects.link(second)
        with self.assertRaisesRegex(ValueError, "overlap"):
            handler()._uv_evidence([first, second], first.data.uv_layers.active.name, 128, 4)

    def test_fbx_default_uv_transports_atlas_and_retains_named_source_uv(self):
        obj = cube("FBXAtlasSource", material("FBXAtlasSurface", (0.3, 0.02, 0.01)))
        original = obj.data.uv_layers.active
        original.name = "ConstructionUV"
        for loop in original.data:
            loop.uv = (0.015, 0.02)
            loop.pin_uv = True
        original_data = [(tuple(loop.uv), loop.pin_uv) for loop in original.data]
        before = source_state([obj])
        result = handler().bake_material_atlas(
            {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": False}
        )
        copied = bpy.data.objects[result["derivatives"][obj.name]]
        with tempfile.TemporaryDirectory(prefix="fw-atlas-fbx-") as directory:
            exported = interchange.export_asset(
                {
                    "object_names": result["objects"],
                    "directory": directory,
                    "filename": "atlas",
                    "format": "FBX",
                    "dry_run": False,
                }
            )
            previous = set(bpy.data.objects)
            bpy.ops.import_scene.fbx(filepath=exported["output_path"])
            imported = list(set(bpy.data.objects) - previous)
            self.assertEqual(len(imported), 1)
            cold = imported[0]
            self.assertEqual(cold.data.uv_layers[0].name, result["uv_layer"])
            self.assertEqual(cold.data.uv_layers.active.name, result["uv_layer"])
            self.assertEqual(
                [tuple(loop.uv) for loop in cold.data.uv_layers.active.data],
                [tuple(loop.uv) for loop in copied.data.uv_layers[result["uv_layer"]].data],
            )
            self.assertEqual(
                [tuple(loop.uv) for loop in cold.data.uv_layers["ConstructionUV"].data],
                [item[0] for item in original_data],
            )
        self.assertEqual(
            [
                (tuple(loop.uv), loop.pin_uv)
                for loop in copied.data.uv_layers["ConstructionUV"].data
            ],
            original_data,
        )
        self.assertEqual(source_state([obj]), before)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(MaterialAtlasTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Material atlas acceptance tests failed")
