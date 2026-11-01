"""Actual Blender resource accounting for convertible geometry and source retention."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import production_assets as assets  # noqa: E402


def registry():
    return {
        kind: tuple(sorted((item.name, item.as_pointer()) for item in getattr(bpy.data, kind)))
        for kind in (
            "objects",
            "meshes",
            "curves",
            "metaballs",
            "materials",
            "images",
            "collections",
            "scenes",
            "node_groups",
            "volumes",
            "pointclouds",
            "hair_curves",
        )
    }


def curve_object(scene, name="CurveSource", data=None):
    if data is None:
        data = bpy.data.curves.new(name + "Data", "CURVE")
        data.dimensions = "2D"
        data.fill_mode = "BOTH"
        spline = data.splines.new("POLY")
        spline.points.add(2)
        for point, co in zip(
            spline.points, ((0, 0, 0, 1), (2, 0, 0, 1), (0, 1, 0, 1)), strict=True
        ):
            point.co = co
        spline.use_cyclic_u = True
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    return obj


def actual_triangles(scene, source):
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        graph = bpy.context.evaluated_depsgraph_get()
        obj = source.evaluated_get(graph)
        mesh = obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            return len(mesh.loop_triangles)
        finally:
            obj.to_mesh_clear()


class ResourceGeometryTests(unittest.TestCase):
    def setUp(self):
        self.scene = bpy.data.scenes.new(self._testMethodName)

    def report(self):
        return assets.scene_resources({"scene_name": self.scene.name})

    def test_curve_polygons_crash_regression_counts_generated_triangle(self):
        source = curve_object(self.scene)
        expected = actual_triangles(self.scene, source)
        self.assertEqual(expected, 1)
        before = registry()
        data = source.data
        points = tuple(tuple(p.co) for p in data.splines[0].points)
        scene_before = bpy.context.scene
        report = self.report()
        self.assertEqual(report["evaluated_triangles_objects"], expected)
        self.assertEqual(report["evaluated_triangles_with_instances"], expected)
        self.assertEqual(report["source_triangles_unique"], 0)
        self.assertEqual(report["referenced_mesh_objects"], 0)
        self.assertEqual(report["unique_mesh_datablocks"], 0)
        self.assertEqual(report["referenced_converted_source_objects"], 1)
        self.assertEqual(report["unique_converted_source_datablocks"], 1)
        self.assertEqual(registry(), before)
        self.assertIs(source.data, data)
        self.assertEqual(tuple(tuple(p.co) for p in data.splines[0].points), points)
        self.assertIs(bpy.context.scene, scene_before)
        json.dumps(report, allow_nan=False)

    def test_shared_curve_sources_and_collection_occurrences(self):
        source = curve_object(self.scene)
        other = curve_object(self.scene, "SharedCurve", source.data)
        collection = bpy.data.collections.new("CurveCollection")
        self.scene.collection.children.link(collection)
        for obj in (source, other):
            collection.objects.link(obj)
            self.scene.collection.objects.unlink(obj)
        instance = bpy.data.objects.new("CurvesInstance", None)
        instance.instance_type = "COLLECTION"
        instance.instance_collection = collection
        self.scene.collection.objects.link(instance)
        before = registry()
        report = self.report()
        self.assertEqual(report["referenced_converted_source_objects"], 2)
        self.assertEqual(report["unique_converted_source_datablocks"], 1)
        self.assertEqual(report["evaluated_triangles_objects"], 2)
        self.assertEqual(report["evaluated_triangles_with_instances"], 4)
        self.assertEqual(report["instance_occurrences"], 2)
        self.assertEqual(report["lod"]["ungrouped_mesh_objects"], [])
        self.assertEqual(registry(), before)

    def test_font_and_metaball_generated_geometry_counted_with_original_types(self):
        font = bpy.data.curves.new("ActualTextData", "FONT")
        font.body = "07"
        font.extrude = 0.1
        text = bpy.data.objects.new("ActualText", font)
        self.scene.collection.objects.link(text)
        meta = bpy.data.metaballs.new("ActualMetaballData")
        meta.resolution = 0.4
        meta.elements.new().radius = 1.5
        ball = bpy.data.objects.new("ActualMetaball", meta)
        self.scene.collection.objects.link(ball)
        expected = {obj.type: actual_triangles(self.scene, obj) for obj in (text, ball)}
        self.assertTrue(all(count > 0 for count in expected.values()))
        before = registry()
        report = self.report()
        self.assertEqual(report["evaluated_triangles_with_instances"], sum(expected.values()))
        self.assertEqual(report["source_triangles_unique"], 0)
        self.assertEqual(report["referenced_converted_source_objects"], 2)
        for kind, triangles in expected.items():
            self.assertEqual(
                report["geometry_by_source_type"][kind]["evaluated_triangles_with_instances"],
                triangles,
            )
        self.assertEqual(registry(), before)
        self.assertEqual(font.body, "07")
        self.assertIs(ball.data, meta)

    def test_nurbs_surface_counts_evaluated_tessellation(self):
        bpy.ops.surface.primitive_nurbs_surface_surface_add()
        obj = bpy.context.active_object
        self.scene.collection.objects.link(obj)
        for collection in tuple(obj.users_collection):
            if collection != self.scene.collection:
                collection.objects.unlink(obj)
        expected = actual_triangles(self.scene, obj)
        self.assertGreater(expected, 0)
        before = registry()
        report = self.report()
        self.assertEqual(report["evaluated_triangles_with_instances"], expected)
        self.assertEqual(report["geometry_by_source_type"]["SURFACE"]["referenced_objects"], 1)
        self.assertEqual(registry(), before)

    def test_hidden_convertible_source_is_not_silently_a_mesh_source(self):
        curve = curve_object(self.scene)
        curve.hide_viewport = True
        mesh = bpy.data.meshes.new("ActualTriangle")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("ActualMesh", mesh)
        self.scene.collection.objects.link(obj)
        report = self.report()
        self.assertEqual(report["mesh_objects"], 1)
        self.assertEqual(report["referenced_mesh_objects"], 1)
        self.assertEqual(report["unique_mesh_datablocks"], 1)
        self.assertEqual(report["source_triangles_unique"], 1)
        self.assertEqual(report["referenced_converted_source_objects"], 1)
        self.assertEqual(report["evaluated_triangles_with_instances"], 1)
        self.assertEqual(report["geometry_by_source_type"]["CURVE"]["evaluated_occurrences"], 0)

    def test_lod_nonmesh_metadata_cannot_access_polygons(self):
        curve = curve_object(self.scene)
        curve["framewright_role"] = "lod"
        curve["framewright_source"] = "Absent"
        curve["framewright_lod_level"] = 2
        mesh = bpy.data.meshes.new("CurveDerivedMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("CurveDerived", mesh)
        obj["framewright_role"] = "lod"
        obj["framewright_source"] = curve.name
        obj["framewright_lod_level"] = 1
        self.scene.collection.objects.link(obj)
        report = self.report()["lod"]
        self.assertEqual(report["groups"], [])
        self.assertEqual(report["unresolved_derivatives"][0]["reason"], "source_not_mesh")
        self.assertEqual(report["unsupported_derivatives"][0]["object"], curve.name)

    def test_failure_after_conversion_releases_temp_mesh_and_preserves_registry(self):
        curve = curve_object(self.scene)
        before = registry()
        temporary_meshes = []

        def fail(mesh):
            temporary_meshes.append(mesh)
            raise RuntimeError("injected count failure")

        with patch.object(assets, "_resource_mesh_statistics", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "injected count failure"):
                self.report()
        self.assertEqual(registry(), before)
        self.assertEqual(len(temporary_meshes), 1)
        with self.assertRaises(ReferenceError):
            len(temporary_meshes[0].vertices)
        # A second evaluation and complete report must work after the failure.
        self.assertEqual(actual_triangles(self.scene, curve), 1)
        self.assertEqual(self.report()["evaluated_triangles_with_instances"], 1)

    def test_evaluated_component_materials_and_collection_only_references(self):
        curve = curve_object(self.scene)
        material = bpy.data.materials.new("OnlyInstanceMaterial")
        material.use_nodes = True
        image = bpy.data.images.new("OnlyInstanceTexture", width=8, height=4)
        material.node_tree.nodes.new("ShaderNodeTexImage").image = image
        curve.data.materials.append(material)
        collection = bpy.data.collections.new("UnlinkedCurveSources")
        collection.objects.link(curve)
        self.scene.collection.objects.unlink(curve)
        for index in range(3):
            instance = bpy.data.objects.new("CurveInstance" + str(index), None)
            instance.instance_type = "COLLECTION"
            instance.instance_collection = collection
            self.scene.collection.objects.link(instance)
        before = registry()
        report = self.report()
        self.assertEqual(report["mesh_objects"], 0)
        self.assertEqual(report["evaluated_triangles_objects"], 0)
        self.assertEqual(report["evaluated_triangles_with_instances"], 3)
        self.assertEqual(report["material_slots_evaluated_occurrences"], 3)
        self.assertEqual(report["unique_materials"], 1)
        self.assertEqual(report["textures"], 1)
        self.assertEqual(report["texture_decoded_bytes_estimate"], 128)
        self.assertEqual(registry(), before)

    def test_success_releases_every_temporary_mesh_and_restores_selection(self):
        curve = curve_object(self.scene)
        other = curve_object(self.scene, "SecondEditableSource", curve.data)
        other.location = (4, 5, 6)
        temporary_meshes = []
        real_statistics = assets._resource_mesh_statistics

        def observe(mesh):
            temporary_meshes.append(mesh)
            return real_statistics(mesh)

        before = registry()
        selected = tuple(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        with patch.object(assets, "_resource_mesh_statistics", side_effect=observe):
            report = self.report()
        self.assertEqual(report["evaluated_triangles_with_instances"], 2)
        self.assertEqual(len(temporary_meshes), 2)
        for mesh in temporary_meshes:
            with self.assertRaises(ReferenceError):
                len(mesh.vertices)
        self.assertEqual(registry(), before)
        self.assertEqual(tuple(bpy.context.selected_objects), selected)
        self.assertIs(bpy.context.view_layer.objects.active, active)
        self.assertEqual(tuple(other.location), (4, 5, 6))

    def test_modern_curves_and_pointcloud_mesh_outputs_use_source_occurrence(self):
        for collection_name, source_type in (
            ("hair_curves", "CURVES"),
            ("pointclouds", "POINTCLOUD"),
        ):
            with self.subTest(source_type=source_type):
                scene = bpy.data.scenes.new("Modern" + source_type)
                data = getattr(bpy.data, collection_name).new("ModernData" + source_type)
                obj = bpy.data.objects.new("ModernSource" + source_type, data)
                scene.collection.objects.link(obj)
                tree = bpy.data.node_groups.new("GenerateCube" + source_type, "GeometryNodeTree")
                tree.interface.new_socket(
                    name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
                )
                cube = tree.nodes.new("GeometryNodeMeshCube")
                output = tree.nodes.new("NodeGroupOutput")
                tree.links.new(cube.outputs["Mesh"], output.inputs["Geometry"])
                obj.modifiers.new("GeneratedMesh", "NODES").node_group = tree
                before = registry()
                report = assets.scene_resources({"scene_name": scene.name})
                self.assertEqual(report["evaluated_triangles_with_instances"], 12)
                self.assertEqual(report["evaluated_triangles_objects"], 12)
                self.assertEqual(report["instance_occurrences"], 0)
                self.assertEqual(report["referenced_mesh_objects"], 0)
                self.assertEqual(report["referenced_converted_source_objects"], 1)
                self.assertEqual(
                    report["geometry_by_source_type"][source_type]["referenced_objects"], 1
                )
                self.assertIs(obj.data, data)
                self.assertEqual(registry(), before)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ResourceGeometryTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Resource geometry acceptance tests failed")
