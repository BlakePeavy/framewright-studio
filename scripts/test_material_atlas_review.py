"""Independent tiny Blender atlas probes. No game, UI session or external files."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

from framewright import material_atlas as atlas  # noqa: E402


def inventory():
    return {
        kind: sorted(item.as_pointer() for item in getattr(bpy.data, kind))
        for kind in (
            "objects",
            "meshes",
            "materials",
            "images",
            "collections",
            "scenes",
            "node_groups",
        )
    }


def material(name, color):
    value = bpy.data.materials.new(name)
    value.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (*color, 1)
    return value


def plane(name, surface):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(surface)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def snapshot(objects, images=()):
    records = []
    for obj in objects:
        row = {
            "id": obj.as_pointer(),
            "matrix": [list(r) for r in obj.matrix_world],
            "parent": obj.parent.as_pointer() if obj.parent else None,
            "parent_inverse": [list(r) for r in obj.matrix_parent_inverse],
            "selected": obj.select_get(),
            "visible": [obj.hide_render, obj.hide_viewport, obj.hide_get()],
        }
        if obj.type == "MESH":
            row.update(
                data=obj.data.as_pointer(),
                vertices=[list(v.co) for v in obj.data.vertices],
                faces=[list(p.vertices) for p in obj.data.polygons],
                material_indices=[p.material_index for p in obj.data.polygons],
                materials=[(slot.link, slot.material.as_pointer()) for slot in obj.material_slots],
                uv_active_index=obj.data.uv_layers.active_index,
                uv=[
                    (u.name, u.active_render, [list(v.uv) for v in u.data])
                    for u in obj.data.uv_layers
                ],
            )
            row["graphs"] = [
                (
                    slot.material.as_pointer(),
                    slot.material.node_tree.as_pointer(),
                    [
                        (
                            n.name,
                            n.type,
                            getattr(n, "uv_map", None),
                            n.image.as_pointer() if n.type == "TEX_IMAGE" and n.image else None,
                        )
                        for n in slot.material.node_tree.nodes
                    ],
                    [
                        (
                            link.from_node.name,
                            link.from_socket.identifier,
                            link.to_node.name,
                            link.to_socket.identifier,
                        )
                        for link in slot.material.node_tree.links
                    ],
                    slot.material.node_tree.nodes.active.name
                    if slot.material.node_tree.nodes.active
                    else None,
                )
                for slot in obj.material_slots
            ]
        records.append(row)
    image_records = []
    for image in images:
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        image_records.append(
            (
                image.as_pointer(),
                image.source,
                image.filepath,
                image.colorspace_settings.name,
                image.alpha_mode,
                image.is_dirty,
                tuple(image.size),
                hashlib.sha256(pixels.tobytes()).hexdigest(),
                hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
                if image.packed_file
                else None,
            )
        )
    state = {
        "objects": records,
        "images": image_records,
        "scene": bpy.context.scene.as_pointer(),
        "active": bpy.context.view_layer.objects.active.as_pointer()
        if bpy.context.view_layer.objects.active
        else None,
        "frame": [bpy.context.scene.frame_current, bpy.context.scene.frame_subframe],
    }
    return json.dumps(state, sort_keys=True, allow_nan=False)


def packed_rgb(image, uv):
    raw = bytes(image.packed_file.data)
    cursor, blocks = 8, []
    while cursor < len(raw):
        size, kind = struct.unpack_from(">I4s", raw, cursor)
        payload = raw[cursor + 8 : cursor + 8 + size]
        if kind == b"IHDR":
            width, height, depth, color, *_ = struct.unpack(">IIBBBBB", payload)
            assert (depth, color) == (16, 2)
        if kind == b"IDAT":
            blocks.append(payload)
        cursor += size + 12
    values = zlib.decompress(b"".join(blocks))
    x, y = min(width - 1, int(uv[0] * width)), min(height - 1, int(uv[1] * height))
    start = (height - 1 - y) * (1 + width * 6)
    assert values[start] == 0
    return np.array(struct.unpack_from(">HHH", values, start + 1 + 6 * x)) / 65535


def atlas_sample(result, source):
    copied = bpy.data.objects[result["derivatives"][source.name]]
    uv = copied.data.uv_layers[result["uv_layer"]]
    copied.data.calc_loop_triangles()
    tri = copied.data.loop_triangles[0]
    center = [sum(uv.data[i].uv[k] for i in tri.loops) / 3 for k in range(2)]
    return packed_rgb(bpy.data.images[result["maps"]["base_color"]["image"]], center)


class AtlasReviewTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_render_uv_wins_over_edit_uv_and_source_image_bytes_are_exact(self):
        for mapping in ("unconnected_image", "empty_uvmap", "texcoord_uv"):
            with self.subTest(mapping=mapping):
                mat = material("Source_" + mapping, (1, 1, 1))
                obj = plane("UV_" + mapping, mat)
                edit = obj.data.uv_layers.new(name="EditBlue")
                render = obj.data.uv_layers.new(name="RenderRed")
                for layer, left in ((edit, 0.6), (render, 0.1)):
                    for loop, uv in zip(
                        layer.data,
                        ((left, 0.1), (left + 0.3, 0.1), (left + 0.3, 0.9), (left, 0.9)),
                        strict=True,
                    ):
                        loop.uv = uv
                render.active_render = True
                obj.data.uv_layers.active = edit
                image = bpy.data.images.new(
                    "PinnedSource_" + mapping, width=8, height=2, alpha=True, float_buffer=True
                )
                pixels = np.zeros((2, 8, 4), np.float32)
                pixels[:, :4] = (0.8, 0.01, 0.01, 1)
                pixels[:, 4:] = (0.01, 0.01, 0.8, 1)
                image.colorspace_settings.name = "Non-Color"
                image.pixels.foreach_set(pixels.ravel())
                image.pack()
                actual_source = np.empty(len(image.pixels), np.float32)
                image.pixels.foreach_get(actual_source)
                np.testing.assert_allclose(actual_source, pixels.ravel(), atol=1e-7, rtol=0)
                tree = mat.node_tree
                texture = tree.nodes.new("ShaderNodeTexImage")
                texture.image = image
                texture.interpolation = "Closest"
                tree.links.new(
                    texture.outputs["Color"], tree.nodes.get("Principled BSDF").inputs["Base Color"]
                )
                if mapping != "unconnected_image":
                    node = tree.nodes.new(
                        "ShaderNodeUVMap" if mapping == "empty_uvmap" else "ShaderNodeTexCoord"
                    )
                    tree.links.new(node.outputs["UV"], texture.inputs["Vector"])
                bpy.context.view_layer.update()
                before = snapshot([obj], [image])
                result = atlas.bake_material_atlas(
                    {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": False}
                )
                self.assertEqual(snapshot([obj], [image]), before)
                copied = bpy.data.objects[result["derivatives"][obj.name]]
                atlas_uv = copied.data.uv_layers[result["uv_layer"]]
                extents = [
                    max(loop.uv[axis] for loop in atlas_uv.data)
                    - min(loop.uv[axis] for loop in atlas_uv.data)
                    for axis in (0, 1)
                ]
                self.assertAlmostEqual(
                    extents[0] / extents[1],
                    1.0,
                    delta=0.001,
                    msg="A square surface chart must stay square in a square atlas; source image aspect is unrelated",
                )
                value = atlas_sample(result, obj)
                self.assertGreater(value[0], 0.8)
                self.assertLess(
                    value[2], 0.2, "The atlas sampled the blue edit UV instead of the red render UV"
                )

    def test_shared_mesh_object_material_override_and_parent_transform(self):
        first = plane("SharedDataRed", material("DataRed", (0.7, 0.01, 0.01)))
        second = first.copy()
        second.name = "SharedDataBlue"
        bpy.context.scene.collection.objects.link(second)
        second.material_slots[0].link = "OBJECT"
        second.material_slots[0].material = material("ObjectBlue", (0.01, 0.01, 0.7))
        pivot = bpy.data.objects.new("NonuniformParent", None)
        bpy.context.scene.collection.objects.link(pivot)
        pivot.location = (3, -2, 1)
        pivot.rotation_euler = (0.2, -0.3, 0.4)
        pivot.scale = (1.2, 0.8, 1.5)
        first.parent = pivot
        second.parent = pivot
        second.location.x = 3
        bpy.context.view_layer.update()
        before = snapshot([first, second, pivot])
        result = atlas.bake_material_atlas(
            {
                "object_names": [second.name, first.name, pivot.name],
                "resolution": 64,
                "margin": 2,
                "dry_run": False,
            }
        )
        self.assertEqual(snapshot([first, second, pivot]), before)
        for source in (first, second):
            copy = bpy.data.objects[result["derivatives"][source.name]]
            self.assertEqual(copy.matrix_world, source.matrix_world)
            self.assertIsNot(copy.data, source.data)
        red, blue = atlas_sample(result, first), atlas_sample(result, second)
        self.assertGreater(red[0], 0.8)
        self.assertLess(red[2], 0.2)
        self.assertGreater(blue[2], 0.8)
        self.assertLess(blue[0], 0.2)

    def test_material_publication_failure_removes_created_material(self):
        obj = plane("PublishFailure", material("PublishSource", (0.2, 0.3, 0.4)))
        bpy.context.view_layer.update()
        before, state = inventory(), snapshot([obj])
        original = atlas._portable_material

        def fail_after_material_creation(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected publication failure after material creation")

        with patch.object(atlas, "_portable_material", side_effect=fail_after_material_creation):
            with self.assertRaisesRegex(RuntimeError, "publication failure"):
                atlas.bake_material_atlas(
                    {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": False}
                )
        self.assertEqual(snapshot([obj]), state)
        self.assertEqual(inventory(), before)

    def test_packed_image_failure_restores_sources_and_removes_owned_outputs(self):
        obj = plane("PackingFailure", material("PackingSource", (0.2, 0.3, 0.4)))
        bpy.context.view_layer.update()
        before, state = inventory(), snapshot([obj])
        original = atlas._pack_png

        def fail_after_pack(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected failure after PNG packing")

        with patch.object(atlas, "_pack_png", side_effect=fail_after_pack):
            with self.assertRaisesRegex(RuntimeError, "PNG packing"):
                atlas.bake_material_atlas(
                    {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": False}
                )
        self.assertEqual(snapshot([obj]), state)
        self.assertEqual(inventory(), before)

    def test_missing_named_normal_uv_refuses_before_owned_id_allocation(self):
        mat = material("MissingUVMaterial", (0.2, 0.3, 0.4))
        obj = plane("MissingNormalUV", mat)
        obj.data.uv_layers.new(name="ExistingUV")
        normal = mat.node_tree.nodes.new("ShaderNodeNormalMap")
        normal.uv_map = "DoesNotExist"
        normal.inputs["Color"].default_value = (0.8, 0.5, 0.9, 1)
        mat.node_tree.links.new(
            normal.outputs["Normal"], mat.node_tree.nodes.get("Principled BSDF").inputs["Normal"]
        )
        bpy.context.view_layer.update()
        before, state = inventory(), snapshot([obj])
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                with self.assertRaisesRegex(ValueError, "UV|uv"):
                    atlas.bake_material_atlas(
                        {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": dry}
                    )
                self.assertEqual(inventory(), before)
                self.assertEqual(snapshot([obj]), state)

    def test_missing_default_render_uv_is_rejected_by_preview_and_apply(self):
        for mapping in ("normal_map", "image_texture", "empty_uvmap", "texcoord_uv"):
            with self.subTest(mapping=mapping):
                mat = material("MissingDefault_" + mapping, (0.2, 0.3, 0.4))
                obj = plane("NoUV_" + mapping, mat)
                tree = mat.node_tree
                shader = tree.nodes.get("Principled BSDF")
                if mapping == "normal_map":
                    node = tree.nodes.new("ShaderNodeNormalMap")
                    tree.links.new(node.outputs["Normal"], shader.inputs["Normal"])
                else:
                    texture = tree.nodes.new("ShaderNodeTexImage")
                    texture.image = bpy.data.images.new("NoUVImage_" + mapping, 2, 2)
                    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
                    if mapping != "image_texture":
                        node = tree.nodes.new(
                            "ShaderNodeUVMap" if mapping == "empty_uvmap" else "ShaderNodeTexCoord"
                        )
                        tree.links.new(node.outputs["UV"], texture.inputs["Vector"])
                bpy.context.view_layer.update()
                before, state = inventory(), snapshot([obj])
                for dry in (True, False):
                    with self.subTest(dry_run=dry):
                        with self.assertRaisesRegex(ValueError, "UV|uv"):
                            atlas.bake_material_atlas(
                                {
                                    "object_names": [obj.name],
                                    "resolution": 64,
                                    "margin": 2,
                                    "dry_run": dry,
                                }
                            )
                        self.assertEqual(inventory(), before)
                        self.assertEqual(snapshot([obj]), state)

    def test_nondefault_principled_distribution_cannot_silently_change(self):
        mat = material("GGXSource", (0.9, 0.5, 0.2))
        shader = mat.node_tree.nodes.get("Principled BSDF")
        self.assertEqual(shader.distribution, "MULTI_GGX")
        shader.distribution = "GGX"
        obj = plane("GGXPlane", mat)
        bpy.context.view_layer.update()
        before, state = inventory(), snapshot([obj])
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                with self.assertRaisesRegex(ValueError, "distribution|GGX|semantic"):
                    atlas.bake_material_atlas(
                        {"object_names": [obj.name], "resolution": 64, "margin": 2, "dry_run": dry}
                    )
                self.assertEqual(inventory(), before)
                self.assertEqual(snapshot([obj]), state)

    def test_rotated_source_tangent_normal_keeps_its_physical_direction(self):
        mat = material("RotatedNormalSource", (0.3, 0.3, 0.3))
        obj = plane("RotatedNormalPlane", mat)
        source_uv = obj.data.uv_layers.new(name="RotatedSourceUV")
        for loop, coords in zip(source_uv.data, ((0, 0), (0, 1), (1, 1), (1, 0)), strict=True):
            loop.uv = coords
        source_uv.active_render = True
        normal = mat.node_tree.nodes.new("ShaderNodeNormalMap")
        normal.uv_map = source_uv.name
        normal.inputs["Color"].default_value = (0.8, 0.5, 0.9, 1)
        mat.node_tree.links.new(
            normal.outputs["Normal"], mat.node_tree.nodes.get("Principled BSDF").inputs["Normal"]
        )
        bpy.context.view_layer.update()
        before = snapshot([obj])
        result = atlas.bake_material_atlas(
            {"object_names": [obj.name], "resolution": 128, "margin": 4, "dry_run": False}
        )
        self.assertEqual(snapshot([obj]), before)
        copy = bpy.data.objects[result["derivatives"][obj.name]]
        mesh = copy.data
        mesh.calc_tangents(uvmap=result["uv_layer"])
        uv = mesh.uv_layers[result["uv_layer"]]
        for tri in mesh.loop_triangles:
            center = [sum(uv.data[index].uv[axis] for index in tri.loops) / 3 for axis in (0, 1)]
            encoded = packed_rgb(bpy.data.images[result["maps"]["normal"]["image"]], center)
            tangent_normal = 2 * encoded - 1
            loop = mesh.loops[tri.loops[0]]
            tangent = loop.tangent
            face_normal = loop.normal
            bitangent = face_normal.cross(tangent) * loop.bitangent_sign
            physical = (
                tangent * tangent_normal[0]
                + bitangent * tangent_normal[1]
                + face_normal * tangent_normal[2]
            )
            physical.normalize()
            # Source U follows +Y, V follows +X. A +0.6 tangent-X tilt must stay +Y.
            self.assertLess((physical - Vector((0, 0.6, 0.8))).length, 0.002)

    def test_png_encoding_preserves_asymmetric_rows_and_scalar_data(self):
        values = np.array(
            [
                [[0.0, 0.003, 1.0, 1], [0.02, 0.2, 0.7, 1], [0.9, 0.1, 0.4, 1]],
                [[0.8, 0.6, 0.3, 1], [0.05, 0.15, 0.25, 1], [0.45, 0.65, 0.85, 1]],
            ],
            dtype=np.float32,
        )
        for role in ("base_color", "roughness", "metallic", "normal"):
            with self.subTest(role=role):
                image = bpy.data.images.new("Encoder_" + role, 3, 2, alpha=True, float_buffer=True)
                image.colorspace_settings.name = "Non-Color"
                image.pixels.foreach_set(values.ravel())
                result = atlas._pack_png(image, role)
                self.assertEqual(result["roundoff_clamped_components"], 0)
                for y in range(2):
                    for x in range(3):
                        decoded = packed_rgb(image, ((x + 0.5) / 3, (y + 0.5) / 2))
                        if role == "base_color":
                            decoded = np.where(
                                decoded <= 0.04045,
                                decoded / 12.92,
                                ((decoded + 0.055) / 1.055) ** 2.4,
                            )
                        np.testing.assert_allclose(decoded, values[y, x, :3], rtol=0, atol=2e-5)

    def test_global_chart_padding_measurement_matches_known_separate_rectangles(self):
        meshes = []
        for index, left in enumerate((0.1, 0.4)):
            obj = plane(
                "Chart_" + str(index), material("ChartSurface_" + str(index), (0.2, 0.3, 0.4))
            )
            uv = obj.data.uv_layers.new(name="KnownAtlas")
            for loop, coords in zip(
                uv.data,
                ((left, 0.1), (left + 0.2, 0.1), (left + 0.2, 0.3), (left, 0.3)),
                strict=True,
            ):
                loop.uv = coords
            meshes.append(obj)
        result = atlas._uv_evidence(meshes, "KnownAtlas", 128, 8)
        self.assertEqual(result["chart_count"], 2, "The shared diagonal belongs inside each chart")
        self.assertEqual(result["triangles"], 4)
        self.assertEqual(result["overlap_count"], 0)
        self.assertEqual(result["coverage"], "complete")
        self.assertAlmostEqual(result["minimum_chart_gap_px_lower_bound"], 12.8, delta=1e-5)
        self.assertAlmostEqual(result["minimum_tile_border_px"], 12.8, delta=1e-5)
        self.assertTrue(result["padding_measured_not_mipmap_guarantee"])

    def test_encoder_rejects_nonfinite_and_out_of_range_without_packing(self):
        for role, bad in (
            ("base_color", float("nan")),
            ("normal", float("inf")),
            ("roughness", -0.01),
            ("metallic", 1.01),
        ):
            with self.subTest(role=role, bad=bad):
                image = bpy.data.images.new(
                    "InvalidEncoding_" + role, 3, 2, alpha=True, float_buffer=True
                )
                image.colorspace_settings.name = "Non-Color"
                pixels = np.full((2, 3, 4), 0.5, np.float32)
                pixels[0, 0, 0] = bad
                image.pixels.foreach_set(pixels.ravel())
                with self.assertRaisesRegex(ValueError, "nonfinite|range"):
                    atlas._pack_png(image, role)
                self.assertIsNone(image.packed_file)
                self.assertEqual(image.source, "GENERATED")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AtlasReviewTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Independent material atlas review failed")
