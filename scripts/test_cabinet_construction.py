"""Functional framed-door construction regressions in an owned Blender scene."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

from framewright import production_assets as assets  # noqa: E402

KINDS = (
    "objects",
    "scenes",
    "collections",
    "meshes",
    "materials",
    "actions",
    "worlds",
    "lights",
    "cameras",
)
CASES = (
    {},
    {"width": 0.45, "depth": 0.3, "height": 0.65, "board_thickness": 0.012, "bevel": 0.001},
    {"width": 1.2, "depth": 0.6, "height": 1.9, "board_thickness": 0.035, "bevel": 0.003},
    {"width": 0.9, "depth": 0.5, "height": 1.25, "board_thickness": 0.005, "bevel": 0.001},
    {"width": 1.1, "depth": 0.9, "height": 1.4, "board_thickness": 0.08, "bevel": 0.01},
    {"width": 2.5, "depth": 0.8, "height": 1.1, "board_thickness": 0.05, "bevel": 0.005},
    {"width": 0.3, "depth": 0.2, "height": 0.4, "board_thickness": 0.005, "bevel": 0.0001},
    {"width": 10, "depth": 5, "height": 10, "board_thickness": 0.1, "bevel": 0.03},
)


def inventory():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


def bounds(obj):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return [
        (min(point[axis] for point in points), max(point[axis] for point in points))
        for axis in range(3)
    ]


def world_geometry(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    vertices, triangles = [], []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            offset = len(vertices)
            vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
            triangles.extend(
                tuple(offset + index for index in tri.vertices) for tri in mesh.loop_triangles
            )
        finally:
            evaluated.to_mesh_clear()
    return vertices, triangles


class CabinetConstructionTests(unittest.TestCase):
    def setUp(self):
        self.before = inventory()
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("CabinetConstructionTest")
        bpy.context.window.scene = self.scene

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def build(self, params=None):
        result = assets.build_prop(
            {"name": "FunctionalCabinet", **(params or {}), "dry_run": False}
        )
        collection = bpy.data.collections[result["collection"]]
        return result, {
            obj.name.split("FunctionalCabinet_", 1)[1].split(".", 1)[0]: obj
            for obj in collection.objects
        }

    def test_hinge_pins_share_the_actual_rotation_axis_across_dimensions(self):
        for case in CASES:
            with self.subTest(params=case):
                result, parts = self.build({**case, "location": [3.25, -1.75, 0.625]})
                pivot = bpy.data.objects[result["controls"]["door_pivot"]]
                pins = [parts[f"HingePin{index}"] for index in (0, 1)]
                for pin in pins:
                    self.assertLess(
                        (
                            Vector(pivot.matrix_world.translation[:2])
                            - Vector(pin.matrix_world.translation[:2])
                        ).length,
                        1e-6,
                    )
                pin_points = [pin.matrix_world.translation.copy() for pin in pins]
                local_axis_points = [pivot.matrix_world.inverted() @ point for point in pin_points]
                fixed_before = [pin.matrix_world.copy() for pin in pins]
                for angle in range(0, 161, 5):
                    pivot.rotation_euler.z = -math.radians(angle)
                    bpy.context.view_layer.update()
                    for point, local_point, pin, matrix in zip(
                        pin_points, local_axis_points, pins, fixed_before, strict=True
                    ):
                        self.assertLess((pivot.matrix_world @ local_point - point).length, 2e-6)
                        self.assertEqual(pin.matrix_world, matrix)

    def test_inset_panels_cover_actual_openings_with_symmetric_seats(self):
        for case in CASES:
            with self.subTest(params=case):
                _, parts = self.build(case)
                left, right = bounds(parts["DoorStile-1"]), bounds(parts["DoorStile1"])
                for index in (0, 1):
                    panel = bounds(parts[f"InsetPanel{index}"])
                    lower = bounds(parts[f"DoorRail{index}"])
                    upper = bounds(parts[f"DoorRail{index + 1}"])
                    self.assertGreater(upper[2][0] - lower[2][1], 0)
                    seats = (
                        left[0][1] - panel[0][0],
                        panel[0][1] - right[0][0],
                        lower[2][1] - panel[2][0],
                        panel[2][1] - upper[2][0],
                    )
                    self.assertGreater(min(seats), 0, "Panel leaves a through-gap at a frame joint")
                    self.assertLess(
                        max(seats) - min(seats),
                        2e-6,
                        "Panel seating must be symmetric on all four edges",
                    )
                    self.assertLess(panel[2][1], bounds(parts["DoorRail2"])[2][1])
                    self.assertGreater(panel[2][0], bounds(parts["DoorRail0"])[2][0])

    def test_closed_door_has_no_unintended_ray_gap_at_middle_rail(self):
        for case in CASES:
            with self.subTest(params=case):
                _, parts = self.build(case)
                door = [obj for obj in parts.values() if obj.get("framewright_role") == "door"]
                vertices, triangles = world_geometry(door)
                tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
                rail = bounds(parts["DoorRail1"])
                depth = case.get("depth", 0.5)
                for z in (rail[2][0] - 0.001, rail[2][1] + 0.001):
                    point, _, _, _ = tree.ray_cast(
                        Vector((0, -depth - 1, z)), Vector((0, 1, 0)), depth * 2 + 2
                    )
                    self.assertIsNotNone(
                        point, "A ray directly beside the middle rail passes through the door"
                    )

    def test_impossible_panel_openings_refuse_preview_and_apply_before_allocation(self):
        params = {
            "width": 0.401,
            "depth": 0.401,
            "height": 0.401,
            "board_thickness": 0.05,
            "bevel": 0.003,
        }
        before = inventory()
        for dry in (True, False):
            with self.subTest(dry=dry), self.assertRaisesRegex(ValueError, "panel|opening|rail"):
                assets.build_prop({**params, "dry_run": dry})
        self.assertEqual(inventory(), before)

    def test_evaluated_door_motion_clears_stationary_body_at_every_five_degrees(self):
        for case in CASES:
            with self.subTest(params=case):
                result, parts = self.build(case)
                pivot = bpy.data.objects[result["controls"]["door_pivot"]]
                moving = [obj for obj in pivot.children if obj.type == "MESH"]
                fixed = [
                    obj
                    for obj in parts.values()
                    if obj.type == "MESH"
                    and obj.get("framewright_role") in {"carcass", "shelf", "plinth"}
                ]
                fixed_vertices, fixed_triangles = world_geometry(fixed)
                fixed_tree = BVHTree.FromPolygons(
                    fixed_vertices, fixed_triangles, all_triangles=True
                )
                for angle in range(0, 161, 5):
                    pivot.rotation_euler.z = -math.radians(angle)
                    bpy.context.view_layer.update()
                    vertices, triangles = world_geometry(moving)
                    moving_tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
                    self.assertEqual(
                        fixed_tree.overlap(moving_tree),
                        [],
                        f"Door/body intersections at {angle} degrees",
                    )
                    distances = [fixed_tree.find_nearest(vertex)[3] for vertex in vertices]
                    self.assertTrue(
                        all(
                            distance is not None and math.isfinite(distance)
                            for distance in distances
                        )
                    )
                    self.assertGreater(min(distances), 1e-5)

    def test_generated_parts_remain_finite_closed_and_uv_mapped(self):
        for case in (CASES[0], CASES[3], CASES[4]):
            with self.subTest(params=case):
                _, parts = self.build(case)
                for obj in parts.values():
                    if obj.type != "MESH":
                        continue
                    self.assertTrue(any(mod.type == "BEVEL" for mod in obj.modifiers))
                    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
                    mesh = ev.to_mesh()
                    bm = bmesh.new()
                    try:
                        bm.from_mesh(mesh)
                        self.assertTrue(all(edge.is_manifold for edge in bm.edges), obj.name)
                        self.assertTrue(
                            all(face.calc_area() > 1e-12 for face in bm.faces), obj.name
                        )
                        self.assertTrue(
                            all(
                                math.isfinite(value)
                                for vertex in mesh.vertices
                                for value in vertex.co
                            )
                        )
                        self.assertTrue(mesh.uv_layers)
                        self.assertTrue(
                            all(
                                math.isfinite(value)
                                for loop in mesh.uv_layers.active.data
                                for value in loop.uv
                            )
                        )
                    finally:
                        bm.free()
                        ev.to_mesh_clear()

    def test_source_geometry_dirty_channels_context_and_action_are_preserved(self):
        mesh = bpy.data.meshes.new("AuthoredSourceData")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        source = bpy.data.objects.new("AuthoredSource", mesh)
        self.scene.collection.objects.link(source)
        material = bpy.data.materials.new("AuthoredSourceMaterial")
        material.use_nodes = True
        mesh.materials.append(material)
        source.shape_key_add(name="Basis")
        key = source.shape_key_add(name="AuthoredShape")
        for frame, value in ((1, 0.1), (3, 0.9)):
            key.value = value
            key.keyframe_insert("value", frame=frame)
        self.scene.frame_set(2, subframe=0.25)
        key.value = 0.4321
        source.location = (2.123, -1.456, 3.789)
        bpy.context.view_layer.objects.active = source
        source.select_set(True)
        action = mesh.shape_keys.animation_data.action
        before = (
            tuple(source.location),
            key.value,
            tuple(tuple(v.co) for v in mesh.vertices),
            tuple(source.data.materials),
            bpy.context.view_layer.objects.active,
            tuple(bpy.context.selected_objects),
            self.scene.frame_current,
            self.scene.frame_subframe,
            action,
        )
        self.build({"door_open_degrees": 65})
        after = (
            tuple(source.location),
            key.value,
            tuple(tuple(v.co) for v in mesh.vertices),
            tuple(source.data.materials),
            bpy.context.view_layer.objects.active,
            tuple(bpy.context.selected_objects),
            self.scene.frame_current,
            self.scene.frame_subframe,
            mesh.shape_keys.animation_data.action,
        )
        self.assertEqual(after, before)

    def test_partial_panel_failure_cleans_only_owned_data(self):
        before = inventory()
        original = assets._box

        def fail_after_panel(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1].endswith("_InsetPanel1"):
                raise RuntimeError("injected after second panel allocation")
            return result

        with patch.object(assets, "_box", side_effect=fail_after_panel):
            with self.assertRaisesRegex(RuntimeError, "second panel"):
                self.build()
        self.assertEqual(inventory(), before)

    def test_articulated_door_keeps_metre_geometry_after_scene_unit_conversion(self):
        expected = {}
        for scale in (1, 0.01, 10):
            self.scene.unit_settings.scale_length = scale
            actual_scale = self.scene.unit_settings.scale_length
            result, parts = self.build({"location": [1.25, -2.75, 0.5]})
            pivot = bpy.data.objects[result["controls"]["door_pivot"]]
            for angle in (0, 45, 90, 160):
                with self.subTest(scale=scale, angle=angle):
                    pivot.rotation_euler.z = -math.radians(angle)
                    bpy.context.view_layer.update()
                    geometry = [
                        (obj.matrix_world @ vertex.co) * actual_scale
                        for name, obj in sorted(parts.items())
                        if obj.type == "MESH"
                        for vertex in obj.data.vertices
                    ]
                    if scale == 1:
                        expected[angle] = geometry
                    else:
                        self.assertLess(
                            max(
                                (a - b).length
                                for a, b in zip(expected[angle], geometry, strict=True)
                            ),
                            5e-5,
                        )

    def test_review_unit_conversion_preserves_nested_parent_world_placement(self):
        for scale in (0.01, 1, 10):
            with self.subTest(scale=scale):
                self.scene.unit_settings.scale_length = scale
                actual_scale = self.scene.unit_settings.scale_length
                root = bpy.data.objects.new("Z_Root", None)
                middle = bpy.data.objects.new("A_Middle", None)
                mesh = bpy.data.meshes.new("NestedPhysicalMesh")
                mesh.from_pydata(
                    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                    [],
                    [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
                )
                source = bpy.data.objects.new("B_PhysicalMesh", mesh)
                objects = [root, middle, source]
                for obj in objects:
                    self.scene.collection.objects.link(obj)
                    obj["framewright_owner"] = assets.OWNER
                root.location = (3, -1, 0.5)
                root.rotation_euler = (0.3, -0.2, 0.4)
                root.scale = (1.5, 0.75, 2)
                middle.parent = root
                middle.matrix_parent_inverse = Matrix.Translation((0.2, -0.1, 0.15))
                middle.location = (2, 1, 0.2)
                middle.rotation_euler = (0.1, -0.3, 0.6)
                middle.scale = (0.6, 1.8, 1.2)
                source.parent = middle
                source.matrix_parent_inverse = Matrix.Translation((-0.3, 0.25, 0.1))
                source.rotation_euler = (0.2, 0.3, -0.5)
                source.scale = (0.8, 0.7, 1.5)
                bpy.context.view_layer.update()
                before = {
                    obj: (obj.matrix_world.copy(), obj.matrix_parent_inverse.copy(), obj.parent)
                    for obj in objects
                }
                expected = [
                    (source.matrix_world @ vertex.co) * actual_scale for vertex in mesh.vertices
                ]
                result = assets.setup_review_scene(
                    {
                        "object_names": [obj.name for obj in objects],
                        "resolution": 64,
                        "dry_run": False,
                    }
                )
                scene = bpy.data.scenes[result["scene"]]
                scene.view_layers[0].update()
                copies = {obj: bpy.data.objects[result["copies"][obj.name]] for obj in objects}
                actual = [
                    copies[source].matrix_world @ vertex.co
                    for vertex in copies[source].data.vertices
                ]
                self.assertLess(
                    max((a - b).length for a, b in zip(expected, actual, strict=True)), 1e-4
                )
                self.assertIs(copies[source].parent, copies[middle])
                self.assertIs(copies[middle].parent, copies[root])
                self.assertEqual(scene.unit_settings.scale_length, 1)
                self.assertEqual(self.scene.unit_settings.scale_length, actual_scale)
                self.assertEqual(
                    {
                        obj: (obj.matrix_world, obj.matrix_parent_inverse, obj.parent)
                        for obj in objects
                    },
                    before,
                )

    def test_review_cameras_lights_and_evaluated_bevels_keep_physical_scale(self):
        expected = None
        for scale in (1, 0.01, 10):
            with self.subTest(scale=scale):
                self.scene.unit_settings.scale_length = scale
                actual_scale = self.scene.unit_settings.scale_length
                built, parts = self.build({"location": [1.25, -2.75, 0.5], "door_open_degrees": 65})
                self.assertEqual(
                    built["unit_conversion"]["output_scene_metres_per_unit"], actual_scale
                )
                vertices, triangles = world_geometry(
                    [obj for _, obj in sorted(parts.items()) if obj.type == "MESH"]
                )
                positions = [tuple(vertex * actual_scale) for vertex in vertices]
                review = assets.setup_review_scene(
                    {"collection_name": built["collection"], "resolution": 64, "dry_run": False}
                )
                self.assertEqual(
                    review["unit_conversion"]["source_scene_metres_per_unit"], actual_scale
                )
                self.assertEqual(review["unit_conversion"]["output_scene_metres_per_unit"], 1)
                scene = bpy.data.scenes[review["scene"]]
                scene.view_layers[0].update()
                cameras = [
                    tuple(bpy.data.objects[name].matrix_world.translation)
                    for _, name in sorted(review["cameras"].items())
                ]
                lights = sorted(
                    (tuple(obj.location), obj.data.energy, obj.data.size)
                    for obj in scene.objects
                    if obj.type == "LIGHT"
                )
                current = (positions, cameras, lights, len(triangles))
                if expected is None:
                    expected = current
                else:
                    for first, second in zip(
                        expected[0] + expected[1], positions + cameras, strict=True
                    ):
                        self.assertLess((Vector(first) - Vector(second)).length, 5e-5)
                    for first, second in zip(expected[2], lights, strict=True):
                        self.assertLess((Vector(first[0]) - Vector(second[0])).length, 5e-5)
                        self.assertAlmostEqual(first[1] / second[1], 1, places=5)
                        self.assertAlmostEqual(first[2], second[2], places=5)
                    self.assertEqual(expected[3], len(triangles))

    def test_review_rejects_collection_outside_active_unit_context_before_allocation(self):
        result, _ = self.build()
        other = bpy.data.scenes.new("DifferentUnitContext")
        other.unit_settings.scale_length = 0.01
        bpy.context.window.scene = other
        before = inventory()
        with self.assertRaisesRegex(ValueError, "active scene|source scene"):
            assets.setup_review_scene(
                {"collection_name": result["collection"], "resolution": 64, "dry_run": False}
            )
        self.assertEqual(inventory(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CabinetConstructionTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Cabinet functional construction tests failed")
    print(
        f"FRAMEWRIGHT_CABINET_CONSTRUCTION_OK tests={result.testsRun} version={bpy.app.version_string}"
    )
