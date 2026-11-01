"""Real Blender fixtures for evaluated mesh, UV and material diagnostics."""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy  # noqa: E402

from framewright import mesh_diagnostics, surface_diagnostics  # noqa: E402


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.original_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("DiagnosticTest")
        bpy.context.window.scene = self.scene

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.original_scene
        for obj in list(self.scene.objects):
            mesh = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(self.scene)

    def make_mesh(self, vertices=None, faces=None):
        mesh = bpy.data.meshes.new("DiagnosticMesh")
        mesh.from_pydata(vertices or [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], faces or [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new("DiagnosticProp", mesh)
        self.scene.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        return obj

    def test_evaluated_modifier_output_and_preservation(self):
        obj = self.make_mesh()
        modifier = obj.modifiers.new("Repeat", "ARRAY")
        modifier.count = 2
        modifier.relative_offset_displace = (2, 0, 0)
        before = len(bpy.data.meshes)
        original = mesh_diagnostics.inspect_mesh({"object_name": obj.name, "evaluated": False})
        evaluated = mesh_diagnostics.inspect_mesh({"object_name": obj.name})
        self.assertEqual(original["topology"]["vertices"], 3)
        self.assertEqual(evaluated["topology"]["vertices"], 6)
        self.assertEqual(len(obj.data.vertices), 3)
        self.assertEqual(len(bpy.data.meshes), before)
        self.assertIs(bpy.context.active_object, obj)
        self.assertTrue(obj.select_get())
        with patch.object(
            mesh_diagnostics, "_inspect_mesh_data", side_effect=RuntimeError("fixture")
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                mesh_diagnostics.inspect_mesh({"object_name": obj.name})
        self.assertEqual(len(bpy.data.meshes), before)

    def test_boundary_policy_and_duplicate_faces(self):
        obj = self.make_mesh(faces=[(0, 1, 2), (2, 1, 0)])
        report = mesh_diagnostics.inspect_mesh({"object_name": obj.name, "evaluated": False})
        self.assertEqual(report["topology"]["duplicate_faces"], 1)
        simple = self.make_mesh()
        report = mesh_diagnostics.inspect_mesh({"object_name": simple.name})
        self.assertIn("OPEN_BOUNDARY", [finding["rule_id"] for finding in report["findings"]])
        report = mesh_diagnostics.inspect_mesh(
            {"object_name": simple.name, "open_boundary_allowed": True}
        )
        self.assertNotIn("OPEN_BOUNDARY", [finding["rule_id"] for finding in report["findings"]])

    def test_crossing_faces_and_budget_are_reported(self):
        obj = self.make_mesh(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0.5, 0.5, -1), (0.5, 0.5, 1), (1, 0.5, 0)],
            [(0, 1, 2), (3, 4, 5)],
        )
        report = mesh_diagnostics.inspect_mesh({"object_name": obj.name})
        self.assertEqual(report["intersections"]["intersection_count"], 1)
        report = mesh_diagnostics.inspect_mesh({"object_name": obj.name, "max_triangles": 1})
        self.assertEqual(report["coverage"], "partial")
        self.assertEqual(report["intersections"]["triangles_omitted"], 1)

    def test_uv_overlap_shared_edge_and_stack_policy(self):
        obj = self.make_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [(0, 1, 2), (1, 3, 2)])
        uv = obj.data.uv_layers.new(name="UVMap")
        for polygon in obj.data.polygons:
            for loop_index in polygon.loop_indices:
                position = obj.data.vertices[obj.data.loops[loop_index].vertex_index].co
                uv.data[loop_index].uv = position[:2]
        report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
        self.assertEqual(report["uv"]["overlap_count"], 0)
        for index, point in zip(
            obj.data.polygons[1].loop_indices, [(0, 0), (1, 0), (0, 1)], strict=True
        ):
            uv.data[index].uv = point
        report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
        self.assertEqual(report["uv"]["overlap_count"], 1)
        self.assertIn("UV_OVERLAP", [finding["rule_id"] for finding in report["findings"]])
        report = surface_diagnostics.inspect_surfaces(
            {"object_name": obj.name, "allow_stacked_uvs": True}
        )
        self.assertEqual(report["uv"]["overlap_count"], 1)
        self.assertNotIn("UV_OVERLAP", [finding["rule_id"] for finding in report["findings"]])

    def test_uv_zero_area_and_udim_coordinates(self):
        obj = self.make_mesh()
        uv = obj.data.uv_layers.new(name="UVMap")
        for loop in uv.data:
            loop.uv = (1.2, 0.2)
        report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
        self.assertEqual(report["uv"]["zero_area_triangles"], 1)
        self.assertEqual(report["uv"]["occupied_udim_tiles"], [1002])

    def test_normal_encoding_and_material_portability(self):
        obj = self.make_mesh()
        material = bpy.data.materials.new("DiagnosticMaterial")
        image = bpy.data.images.new("DiagnosticNormal", 4, 4)
        try:
            obj.data.materials.append(material)
            tree = material.node_tree
            principled = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            normal = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(texture.outputs["Color"], normal.inputs["Color"])
            tree.links.new(normal.outputs["Normal"], principled.inputs["Normal"])
            report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
            self.assertIn(
                "DATA_MAP_COLOR_SPACE", [finding["rule_id"] for finding in report["findings"]]
            )
            image.colorspace_settings.name = "Non-Color"
            report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
            self.assertNotIn(
                "DATA_MAP_COLOR_SPACE", [finding["rule_id"] for finding in report["findings"]]
            )
            normal.space = "OBJECT"
            report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
            self.assertIn(
                "NORMAL_MAP_PORTABILITY", [finding["rule_id"] for finding in report["findings"]]
            )
        finally:
            bpy.data.materials.remove(material)
            bpy.data.images.remove(image)

    def test_linked_source_is_read_only_and_inspectable(self):
        obj = self.make_mesh()
        with tempfile.TemporaryDirectory(prefix="framewright-linked-") as directory:
            path = str(Path(directory) / "fixture.blend")
            bpy.data.libraries.write(path, {obj})
            with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
                data_to.objects = [data_from.objects[0]]
            linked = data_to.objects[0]
            self.scene.collection.objects.link(linked)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                mesh_diagnostics.inspect_mesh({"object_name": linked.name})
            obj.name = "LocalOriginal"
            report = mesh_diagnostics.inspect_mesh({"object_name": linked.name})
            self.assertTrue(report["linked_source"])
            self.assertEqual(len(linked.data.vertices), 3)

    def test_packed_channels_and_missing_image_are_reported(self):
        obj = self.make_mesh()
        material = bpy.data.materials.new("PackedMaterial")
        image = bpy.data.images.new("PackedORM", 4, 4)
        try:
            obj.data.materials.append(material)
            image.colorspace_settings.name = "Non-Color"
            tree = material.node_tree
            principled = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            separate = tree.nodes.new("ShaderNodeSeparateColor")
            tree.links.new(texture.outputs["Color"], separate.inputs["Color"])
            tree.links.new(separate.outputs["Green"], principled.inputs["Roughness"])
            tree.links.new(separate.outputs["Blue"], principled.inputs["Metallic"])
            report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
            codes = [finding["rule_id"] for finding in report["findings"]]
            self.assertNotIn("DATA_CHANNEL_MAPPING", codes)
            channels = {
                channel["destination"]: channel["channel"]
                for channel in report["materials"][0]["channels"]
            }
            self.assertEqual(channels, {"Roughness": "Green", "Metallic": "Blue"})
            tree.links.new(separate.outputs["Green"], principled.inputs["Metallic"])
            image.source = "FILE"
            image.filepath = "//framewright_missing_packed_orm.png"
            report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})
            codes = [finding["rule_id"] for finding in report["findings"]]
            self.assertIn("DATA_CHANNEL_MAPPING", codes)
            self.assertIn("MATERIAL_IMAGE_MISSING", codes)
        finally:
            bpy.data.materials.remove(material)
            bpy.data.images.remove(image)

    def test_invalid_params_and_edit_mode_fail_closed(self):
        obj = self.make_mesh()
        with self.assertRaises(ValueError):
            mesh_diagnostics.inspect_mesh({"object_name": obj.name, "max_pairs": True})
        with self.assertRaises(ValueError):
            surface_diagnostics.inspect_surfaces(
                {"object_name": obj.name, "allow_stacked_uvs": "yes"}
            )
        bpy.ops.object.mode_set(mode="EDIT")
        with self.assertRaisesRegex(ValueError, "Object Mode"):
            mesh_diagnostics.inspect_mesh({"object_name": obj.name})

    def density_fixture(self, width=256, height=128):
        obj = self.make_mesh([(0, 0, 0), (2, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        uv = obj.data.uv_layers.new(name="RenderUV")
        for loop, point in zip(uv.data, ((0, 0), (1, 0), (0, 1)), strict=True):
            loop.uv = point
        material = bpy.data.materials.new("TexelDensityMaterial")
        image = bpy.data.images.new("TexelDensityImage", width, height)
        self.addCleanup(bpy.data.materials.remove, material)
        self.addCleanup(bpy.data.images.remove, image)
        obj.data.materials.append(material)
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        material.node_tree.links.new(
            texture.outputs["Color"],
            material.node_tree.nodes["Principled BSDF"].inputs["Base Color"],
        )
        bpy.context.view_layer.update()
        return obj, material, texture

    def test_texel_density_exact_world_area_and_source_preservation(self):
        obj, material, texture = self.density_fixture()
        before = (
            len(bpy.data.meshes),
            tuple(tuple(v.co) for v in obj.data.vertices),
            tuple(tuple(v.uv) for v in obj.data.uv_layers[0].data),
            tuple(material.node_tree.links),
            obj.matrix_world.copy(),
        )
        report = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"]
        self.assertEqual(report["coverage"], "complete")
        row = report["materials"][0]
        self.assertAlmostEqual(row["measured_world_area_m2"], 1)
        self.assertAlmostEqual(row["measured_uv_area"], 0.5)
        self.assertEqual(row["image_dimensions"], [256, 128])
        self.assertAlmostEqual(row["area_equivalent_texels_per_meter"], 128)
        self.assertAlmostEqual(row["minimum_triangle_texels_per_meter"], 128)
        self.assertAlmostEqual(row["maximum_triangle_texels_per_meter"], 128)
        self.assertEqual(
            before,
            (
                len(bpy.data.meshes),
                tuple(tuple(v.co) for v in obj.data.vertices),
                tuple(tuple(v.uv) for v in obj.data.uv_layers[0].data),
                tuple(material.node_tree.links),
                obj.matrix_world.copy(),
            ),
        )

    def test_texel_density_uses_units_nonuniform_scale_and_render_uv(self):
        obj, material, texture = self.density_fixture()
        other = obj.data.uv_layers.new(name="OtherUV")
        for loop, point in zip(other.data, ((0, 0), (0.5, 0), (0, 0.5)), strict=True):
            loop.uv = point
        obj.data.uv_layers.active_index = 1
        obj.data.uv_layers[0].active_render = True
        obj.scale = (2, 3, 0.5)
        self.scene.unit_settings.scale_length = 0.01
        bpy.context.view_layer.update()
        row = surface_diagnostics.inspect_surfaces(
            {"object_name": obj.name, "uv_layer": "OtherUV"}
        )["texel_density"]["materials"][0]
        self.assertEqual(row["uv_layer"], "RenderUV")
        self.assertAlmostEqual(row["measured_world_area_m2"], 0.0006)
        self.assertAlmostEqual(
            row["area_equivalent_texels_per_meter"], 12800 / math.sqrt(6), places=2
        )
        node = material.node_tree.nodes.new("ShaderNodeUVMap")
        node.uv_map = "OtherUV"
        material.node_tree.links.new(node.outputs["UV"], texture.inputs["Vector"])
        row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
            "materials"
        ][0]
        self.assertEqual(row["uv_layer"], "OtherUV")
        self.assertAlmostEqual(
            row["area_equivalent_texels_per_meter"], 6400 / math.sqrt(6), places=2
        )

    def test_texel_density_evaluated_object_material_override_and_budget(self):
        obj, material, texture = self.density_fixture()
        override = material.copy()
        image = bpy.data.images.new("DensityOverride", 512, 256)
        self.addCleanup(bpy.data.materials.remove, override)
        self.addCleanup(bpy.data.images.remove, image)
        override.node_tree.nodes[texture.name].image = image
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = override
        modifier = obj.modifiers.new("DensityArray", "ARRAY")
        modifier.count = 2
        modifier.relative_offset_displace = (2, 0, 0)
        report = surface_diagnostics.inspect_surfaces(
            {"object_name": obj.name, "allow_stacked_uvs": True}
        )["texel_density"]
        self.assertEqual(report["triangles_total"], 2)
        row = report["materials"][0]
        self.assertEqual(row["material"], override.name)
        self.assertEqual(row["measured_triangles"], 2)
        self.assertAlmostEqual(row["measured_world_area_m2"], 2)
        self.assertAlmostEqual(row["area_equivalent_texels_per_meter"], 256)
        limited = surface_diagnostics.inspect_surfaces(
            {"object_name": obj.name, "max_triangles": 1}
        )["texel_density"]
        self.assertEqual(limited["coverage"], "partial")
        self.assertEqual(limited["triangles_omitted"], 1)
        self.assertEqual(limited["materials"][0]["measured_triangles"], 1)

    def test_texel_density_unsupported_mapping_and_degenerate_geometry_are_unknown(self):
        obj, material, texture = self.density_fixture()
        mapping = material.node_tree.nodes.new("ShaderNodeMapping")
        material.node_tree.links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
        row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
            "materials"
        ][0]
        self.assertIsNone(row["area_equivalent_texels_per_meter"])
        self.assertIn("unsupported_vector_mapping", row["unknown_reasons"])
        material.node_tree.nodes.remove(mapping)
        obj.scale.x = 0
        bpy.context.view_layer.update()
        row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
            "materials"
        ][0]
        self.assertIsNone(row["area_equivalent_texels_per_meter"])
        self.assertIn("degenerate_world_triangle", row["unknown_reasons"])

    def test_texel_density_weights_area_instead_of_averaging_triangle_densities(self):
        _, material, _ = self.density_fixture()
        obj = self.make_mesh(
            [(0, 0, 0), (2, 0, 0), (0, 1, 0), (0, 0, 1), (4, 0, 1), (0, 2, 1)],
            [(0, 1, 2), (3, 4, 5)],
        )
        obj.data.materials.append(material)
        uv = obj.data.uv_layers.new(name="AreaUV")
        for triangle in obj.data.polygons:
            for index, point in zip(triangle.loop_indices, ((0, 0), (1, 0), (0, 1)), strict=True):
                uv.data[index].uv = point
        row = surface_diagnostics.inspect_surfaces(
            {"object_name": obj.name, "allow_stacked_uvs": True}
        )["texel_density"]["materials"][0]
        self.assertAlmostEqual(row["measured_world_area_m2"], 5)
        self.assertAlmostEqual(row["measured_uv_area"], 1)
        self.assertAlmostEqual(row["area_equivalent_texels_per_meter"], math.sqrt(256 * 128 / 5))
        self.assertAlmostEqual(row["minimum_triangle_texels_per_meter"], 64)
        self.assertAlmostEqual(row["maximum_triangle_texels_per_meter"], 128)

    def test_texel_density_generated_object_coordinates_and_sequences_are_unknown(self):
        obj, material, texture = self.density_fixture()
        coordinates = material.node_tree.nodes.new("ShaderNodeTexCoord")
        for output in ("Generated", "Object"):
            material.node_tree.links.new(coordinates.outputs[output], texture.inputs["Vector"])
            row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
                "materials"
            ][0]
            self.assertIn("unsupported_vector_mapping", row["unknown_reasons"])
            self.assertIsNone(row["area_equivalent_texels_per_meter"])
        material.node_tree.links.new(coordinates.outputs["UV"], texture.inputs["Vector"])
        row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
            "materials"
        ][0]
        self.assertAlmostEqual(row["area_equivalent_texels_per_meter"], 128)
        texture.image.source = "SEQUENCE"
        row = surface_diagnostics.inspect_surfaces({"object_name": obj.name})["texel_density"][
            "materials"
        ][0]
        self.assertIn("unsupported_image_source", row["unknown_reasons"])
        self.assertIsNone(row["area_equivalent_texels_per_meter"])

    def test_texel_density_invalid_shader_uvs_are_unknown_without_nonfinite_json(self):
        obj, material, texture = self.density_fixture()
        layer = obj.data.uv_layers.new(name="InvalidShaderUV")
        node = material.node_tree.nodes.new("ShaderNodeUVMap")
        node.uv_map = layer.name
        material.node_tree.links.new(node.outputs["UV"], texture.inputs["Vector"])
        for coordinates, reason in (
            (((0, 0), (0, 0), (0, 0)), "degenerate_uv_triangle"),
            (((2, 0), (3, 0), (2, 1)), "uv_outside_single_tile"),
            (((0, 0), (float("nan"), 0), (0, 1)), "non_finite_uv_triangle"),
        ):
            for item, point in zip(layer.data, coordinates, strict=True):
                item.uv = point
            report = surface_diagnostics.inspect_surfaces(
                {"object_name": obj.name, "uv_layer": "RenderUV"}
            )["texel_density"]
            self.assertEqual(report["coverage"], "unknown")
            self.assertIn(reason, report["materials"][0]["unknown_reasons"])
            self.assertIsNone(report["materials"][0]["area_equivalent_texels_per_meter"])
            json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Diagnostic fixture tests failed")
    print(f"FRAMEWRIGHT_DIAGNOSTICS_OK tests={result.testsRun} version={bpy.app.version_string}")
