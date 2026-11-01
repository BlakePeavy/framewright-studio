"""Independent native Blender resource accounting review; no external assets."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import production_assets as assets  # noqa: E402


def snapshot():
    kinds = (
        "objects",
        "meshes",
        "curves",
        "materials",
        "node_groups",
        "images",
        "scenes",
        "collections",
    )
    identities = {
        kind: [(item.name, item.as_pointer()) for item in getattr(bpy.data, kind)] for kind in kinds
    }
    sources = []
    for obj in bpy.data.objects:
        geometry = None
        if obj.type == "MESH":
            geometry = (
                [list(v.co) for v in obj.data.vertices],
                [list(p.vertices) for p in obj.data.polygons],
            )
        elif obj.type in {"CURVE", "SURFACE", "FONT"}:
            geometry = [(s.type, [list(p.co) for p in s.points]) for s in obj.data.splines]
        sources.append(
            (
                obj.name,
                obj.type,
                obj.data.as_pointer() if obj.data else None,
                [list(row) for row in obj.matrix_world],
                geometry,
                [
                    (slot.link, slot.material.name if slot.material else None)
                    for slot in obj.material_slots
                ],
                dict(obj.items()),
            )
        )
    image_state = [
        (image.name, list(image.size), image.colorspace_settings.name, list(image.pixels))
        for image in bpy.data.images
    ]
    return json.dumps(
        {
            "identities": identities,
            "sources": sources,
            "images": image_state,
            "active_scene": bpy.context.scene.name,
            "frame": bpy.context.scene.frame_current,
            "subframe": bpy.context.scene.frame_subframe,
            "selection": sorted(o.name for o in bpy.context.selected_objects),
            "active": bpy.context.object.name if bpy.context.object else None,
        },
        sort_keys=True,
    )


def oracle():
    """Independent occurrence totals plus direct GeometrySet mesh accounting.

    Blender5.2 emits a native CURVE occurrence and a synthetic MESH projection
    for the same geometry. Sum only MESH entries for totals; calculate direct
    object triangles from each non-instance GeometrySet mesh. The number of
    remaining mesh entries is the instance count, without duplicating a native
    converted occurrence or copying the implementation's persistent-ID logic.
    """
    graph = bpy.context.evaluated_depsgraph_get()
    rows, direct_counts = [], []
    for occurrence in graph.object_instances:
        obj = occurrence.object
        if obj.type not in {"MESH", "CURVE", "SURFACE", "FONT", "META"}:
            continue
        if not occurrence.is_instance:
            geometry = obj.evaluated_geometry()
            direct = geometry.mesh
            if direct is not None:
                direct.calc_loop_triangles()
                direct_counts.append(len(direct.loop_triangles))
        if obj.type != "MESH":
            continue
        mesh = obj.to_mesh()
        try:
            if mesh is None:
                continue
            mesh.calc_loop_triangles()
            rows.append(
                {
                    "triangles": len(mesh.loop_triangles),
                    "source_type": obj.original.type,
                    "materials": [m.name for m in mesh.materials if m],
                }
            )
        finally:
            obj.to_mesh_clear()
    return {
        "base": sum(direct_counts),
        "total": sum(r["triangles"] for r in rows),
        "instances": len(rows) - len(direct_counts),
        "rows": rows,
    }


def triangle(name="Source", shared=None):
    data = shared or bpy.data.meshes.new(name + "Mesh")
    if shared is None:
        data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def generated_material(name, image_size=(8, 4), nested=False):
    image = bpy.data.images.new(name + "Image", width=image_size[0], height=image_size[1])
    image.generated_color = (0.12, 0.4, 0.6, 1)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    if nested:
        group = bpy.data.node_groups.new(name + "NestedImage", "ShaderNodeTree")
        group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        texture = group.nodes.new("ShaderNodeTexImage")
        texture.image = image
        output = group.nodes.new("NodeGroupOutput")
        group.links.new(texture.outputs["Color"], output.inputs["Color"])
        instance = tree.nodes.new("ShaderNodeGroup")
        instance.node_tree = group
        tree.links.new(
            instance.outputs["Color"], tree.nodes.get("Principled BSDF").inputs["Base Color"]
        )
    else:
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        tree.links.new(
            texture.outputs["Color"], tree.nodes.get("Principled BSDF").inputs["Base Color"]
        )
    return mat, image


def gn_fixture(*, instances=0, nested_instances=0, mixed=None, materials=False):
    mesh = bpy.data.meshes.new("GNSourceEmptyMesh")
    host = bpy.data.objects.new("GeneratedHost", mesh)
    bpy.context.scene.collection.objects.link(host)
    group = bpy.data.node_groups.new("ResourceReviewGeometry", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = group.nodes, group.links
    output = nodes.new("NodeGroupOutput")
    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(join.outputs["Geometry"], output.inputs["Geometry"])
    cube = nodes.new("GeometryNodeMeshCube")
    cube_output = cube.outputs["Mesh"]
    mats, images = [], []
    if materials:
        material, image = generated_material("GeneratedBase", nested=True)
        mats.append(material)
        images.append(image)
        assign = nodes.new("GeometryNodeSetMaterial")
        assign.inputs["Material"].default_value = material
        links.new(cube_output, assign.inputs["Geometry"])
        cube_output = assign.outputs["Geometry"]
    if not nested_instances:
        links.new(cube_output, join.inputs["Geometry"])
    if instances or nested_instances:
        primitive = cube_output
        if not nested_instances:
            ico = nodes.new("GeometryNodeMeshIcoSphere")
            ico.inputs["Subdivisions"].default_value = 1
            primitive = ico.outputs["Mesh"]
            if materials:
                material, image = generated_material("GeneratedInstances", image_size=(4, 4))
                mats.append(material)
                images.append(image)
                assign = nodes.new("GeometryNodeSetMaterial")
                assign.inputs["Material"].default_value = material
                links.new(primitive, assign.inputs["Geometry"])
                primitive = assign.outputs["Geometry"]
        line = nodes.new("GeometryNodeMeshLine")
        line.inputs["Count"].default_value = instances or 2
        inst = nodes.new("GeometryNodeInstanceOnPoints")
        links.new(line.outputs["Mesh"], inst.inputs["Points"])
        links.new(primitive, inst.inputs["Instance"])
        instance_output = inst.outputs["Instances"]
        if nested_instances:
            outer_line = nodes.new("GeometryNodeMeshLine")
            outer_line.inputs["Count"].default_value = nested_instances
            outer = nodes.new("GeometryNodeInstanceOnPoints")
            links.new(outer_line.outputs["Mesh"], outer.inputs["Points"])
            links.new(instance_output, outer.inputs["Instance"])
            instance_output = outer.outputs["Instances"]
        links.new(instance_output, join.inputs["Geometry"])
    if mixed == "curves":
        curve = nodes.new("GeometryNodeCurvePrimitiveLine")
        links.new(curve.outputs["Curve"], join.inputs["Geometry"])
    if mixed == "pointcloud":
        line = nodes.new("GeometryNodeMeshLine")
        line.inputs["Count"].default_value = 5
        points = nodes.new("GeometryNodeMeshToPoints")
        links.new(line.outputs["Mesh"], points.inputs["Mesh"])
        links.new(points.outputs["Points"], join.inputs["Geometry"])
    modifier = host.modifiers.new("GeneratedOutputs", "NODES")
    modifier.node_group = group
    bpy.context.view_layer.update()
    return host, mats, images


class ResourceGeometryReview(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def checked_report(self):
        expected = oracle()
        before = snapshot()
        report = assets.scene_resources({})
        self.assertEqual(
            snapshot(), before, "Resource inspection changed source state or leaked IDs"
        )
        self.assertEqual(report["evaluated_triangles_objects"], expected["base"])
        self.assertEqual(report["evaluated_triangles_with_instances"], expected["total"])
        self.assertEqual(report["instance_occurrences"], expected["instances"])
        json.dumps(report, allow_nan=False)
        return report, expected

    def test_01_generated_materials_and_nested_images_are_counted(self):
        host, mats, images = gn_fixture(instances=3, materials=True)
        generated_material("UnreferencedMustNotCount", image_size=(2, 2))
        self.assertEqual(len(host.material_slots), 0)
        report, expected = self.checked_report()
        self.assertEqual(expected["base"], 12)
        self.assertEqual(expected["total"], 72)
        self.assertEqual(report["unique_materials"], len(mats))
        self.assertEqual(report["textures"], len(images))
        decoded = sum(i.size[0] * i.size[1] * i.channels * (4 if i.is_float else 1) for i in images)
        self.assertEqual(report["texture_decoded_bytes_estimate"], decoded)
        self.assertEqual(report["source_triangles_unique"], 0)
        self.assertEqual(report["unique_mesh_datablocks"], 1)

    def test_02_nested_generated_instances_count_every_occurrence(self):
        gn_fixture(instances=2, nested_instances=3, materials=True)
        report, expected = self.checked_report()
        self.assertEqual(expected["total"], 72)
        self.assertEqual(expected["instances"], 6)
        self.assertEqual(report["referenced_mesh_objects"], 1)
        self.assertEqual(report["unique_materials"], 1)
        self.assertEqual(report["textures"], 1)

    def test_03_mixed_curve_component_is_explicitly_unmeasured(self):
        host, _, _ = gn_fixture(instances=3, mixed="curves")
        report, expected = self.checked_report()
        self.assertEqual(expected["total"], 72)
        self.assertTrue(
            any(
                row["object"] == host.name and row["component"] == "curves"
                for row in report["unsupported_geometry_outputs"]
            )
        )
        self.assertEqual(report["unique_mesh_datablocks"], 1)

    def test_04_mixed_pointcloud_component_is_explicitly_unmeasured(self):
        host, _, _ = gn_fixture(mixed="pointcloud")
        report, expected = self.checked_report()
        self.assertEqual(expected["total"], 12)
        self.assertTrue(
            any(
                row["object"] == host.name and row["component"] == "pointcloud"
                for row in report["unsupported_geometry_outputs"]
            )
        )

    def test_05_shared_source_mesh_distinct_evaluated_modifiers(self):
        source = triangle("PlainSource")
        second = triangle("SolidifiedSource", shared=source.data)
        second.modifiers.new("ActualSolidify", "SOLIDIFY").thickness = 0.2
        bpy.context.view_layer.update()
        report, expected = self.checked_report()
        self.assertGreater(expected["total"], 2)
        self.assertEqual(report["source_triangles_unique"], 1)
        self.assertEqual(report["unique_mesh_datablocks"], 1)
        self.assertEqual(report["referenced_mesh_objects"], 2)
        self.assertEqual(report["evaluated_unique_geometry"], 2)

    def test_06_converted_curve_lod_tag_does_not_pollute_mesh_lod(self):
        source = triangle("LODSource")
        data = bpy.data.curves.new("TaggedCurveData", "CURVE")
        data.dimensions = "3D"
        data.bevel_depth = 0.1
        data.bevel_resolution = 1
        spline = data.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (0, 0, 0, 1)
        spline.points[1].co = (1, 0, 0, 1)
        curve = bpy.data.objects.new("NotAMeshLOD", data)
        bpy.context.scene.collection.objects.link(curve)
        curve["framewright_role"] = "lod"
        curve["framewright_source"] = source.name
        curve["framewright_lod_level"] = 2
        bpy.context.view_layer.update()
        report, expected = self.checked_report()
        self.assertGreater(expected["total"], 1)
        self.assertEqual(report["source_triangles_unique"], 1)
        self.assertEqual(report["lod"]["groups"], [])
        self.assertEqual(report["lod"]["unresolved_derivatives"], [])
        self.assertNotIn(curve.name, report["lod"]["ungrouped_mesh_objects"])

    def test_07_native_surface_tessellation_is_counted_and_repeated_calls_clean(self):
        bpy.ops.surface.primitive_nurbs_surface_surface_add()
        surface = bpy.context.object
        surface.name = "AuthoredNurbsSurface"
        bpy.context.view_layer.update()
        expected = oracle()
        self.assertGreater(expected["total"], 0)
        before = snapshot()
        for _ in range(4):
            report, _ = self.checked_report()
            self.assertEqual(report["mesh_objects"], 0)
            self.assertEqual(report["source_triangles_unique"], 0)
            self.assertEqual(report["unique_mesh_datablocks"], 0)
            self.assertEqual(report["referenced_converted_source_objects"], 1)
        self.assertEqual(snapshot(), before)

    def test_08_material_on_unmeasured_curve_component_still_counts(self):
        host, _, _ = gn_fixture(mixed="curves")
        material, image = generated_material("CurveOnlyMaterial", nested=True)
        group = host.modifiers[0].node_group
        curve = next(n for n in group.nodes if n.bl_idname == "GeometryNodeCurvePrimitiveLine")
        join = next(n for n in group.nodes if n.bl_idname == "GeometryNodeJoinGeometry")
        for link in list(group.links):
            if link.from_node == curve:
                group.links.remove(link)
        assign = group.nodes.new("GeometryNodeSetMaterial")
        assign.inputs["Material"].default_value = material
        group.links.new(curve.outputs["Curve"], assign.inputs["Geometry"])
        group.links.new(assign.outputs["Geometry"], join.inputs["Geometry"])
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        geometry = host.evaluated_get(graph).evaluated_geometry()
        self.assertEqual([m.original for m in geometry.curves.materials], [material])
        self.assertEqual([m for m in geometry.mesh.materials if m], [])
        report, expected = self.checked_report()
        self.assertEqual(expected["total"], 12)
        self.assertEqual(report["unique_materials"], 1)
        self.assertEqual(report["textures"], 1)
        self.assertEqual(
            report["texture_decoded_bytes_estimate"], image.size[0] * image.size[1] * image.channels
        )
        self.assertTrue(
            any(row["component"] == "curves" for row in report["unsupported_geometry_outputs"])
        )

    def test_09_curve_host_generated_mesh_instances_are_not_projection_duplicates(self):
        host, _, _ = gn_fixture(instances=3)
        source = bpy.data.curves.new("CurveHostData", "CURVE")
        source.dimensions = "3D"
        spline = source.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (0, 0, 0, 1)
        spline.points[1].co = (1, 0, 0, 1)
        group = host.modifiers[0].node_group
        old_host = host
        host = bpy.data.objects.new("CurveGeneratedHost", source)
        bpy.context.scene.collection.objects.link(host)
        host.modifiers.new("GeneratedOutputs", "NODES").node_group = group
        bpy.data.objects.remove(old_host, do_unlink=True)
        cube = next(n for n in group.nodes if n.bl_idname == "GeometryNodeMeshCube")
        instances = next(n for n in group.nodes if n.bl_idname == "GeometryNodeInstanceOnPoints")
        for link in list(group.links):
            if link.to_node == instances and link.to_socket == instances.inputs["Instance"]:
                group.links.remove(link)
        group.links.new(cube.outputs["Mesh"], instances.inputs["Instance"])
        bpy.context.view_layer.update()
        self.assertEqual(host.type, "CURVE")
        report, expected = self.checked_report()
        self.assertEqual(expected["base"], 12)
        self.assertEqual(expected["total"], 48)
        self.assertEqual(expected["instances"], 3)
        self.assertEqual(report["source_triangles_unique"], 0)
        self.assertEqual(report["referenced_mesh_objects"], 0)
        self.assertEqual(report["referenced_converted_source_objects"], 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ResourceGeometryReview)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
