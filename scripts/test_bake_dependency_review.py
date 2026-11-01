"""Independent static-bake dependency refusal and external-ID preservation checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_baking import fixture  # noqa: E402

from framewright import baking  # noqa: E402

KINDS = (
    "objects",
    "meshes",
    "materials",
    "images",
    "node_groups",
    "actions",
    "scenes",
    "collections",
)


def identities():
    return {kind: set(getattr(bpy.data, kind)) for kind in KINDS}


def animation_state(owner):
    animation = owner.animation_data
    if animation is None:
        return None
    action = animation.action
    curves = (
        tuple(
            (
                bag.slot_handle,
                curve.data_path,
                curve.array_index,
                tuple(tuple(key.co) for key in curve.keyframe_points),
            )
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            for curve in bag.fcurves
        )
        if action
        else ()
    )
    return (
        action.as_pointer() if action else None,
        animation.action_slot.handle if animation.action_slot else None,
        curves,
        tuple(
            (curve.data_path, curve.array_index, curve.driver.expression)
            for curve in animation.drivers
        ),
    )


class BakeDependencyReviewTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.initial = identities()
        self.scene = bpy.data.scenes.new("BakeDependencyReview")
        bpy.context.window.scene = self.scene
        self.high, self.low = fixture()
        self.source_objects = [self.high, self.low]
        self.external = bpy.data.objects.new("UnrelatedBakeOwner", None)
        self.scene.collection.objects.link(self.external)
        self.material = bpy.data.materials.new("BakeSourceMaterial")
        self.material.use_nodes = True
        self.low.data.materials.append(self.material)

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for value in set(getattr(bpy.data, kind)) - self.initial[kind]:
                getattr(bpy.data, kind).remove(value, do_unlink=True)

    def state(self):
        return {
            "scene": bpy.context.scene.as_pointer(),
            "time": (self.scene.frame_current, self.scene.frame_subframe),
            "active": bpy.context.view_layer.objects.active,
            "selection": tuple(bpy.context.selected_objects),
            "external": (tuple(self.external.location), tuple(self.external.rotation_euler)),
            "meshes": tuple(
                (
                    obj.as_pointer(),
                    obj.data.as_pointer(),
                    tuple(obj.location),
                    tuple(obj.rotation_euler),
                    tuple(obj.scale),
                    tuple(tuple(vertex.co) for vertex in obj.data.vertices),
                    tuple(tuple(face.vertices) for face in obj.data.polygons),
                    tuple(face.material_index for face in obj.data.polygons),
                    tuple(tuple(item.uv) for layer in obj.data.uv_layers for item in layer.data),
                    tuple((slot.link, slot.material) for slot in obj.material_slots),
                    animation_state(obj.data),
                )
                for obj in self.source_objects
            ),
            "material_animation": animation_state(self.material),
            "tree_animation": animation_state(self.material.node_tree),
            "links": tuple(
                (link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name)
                for link in self.material.node_tree.links
            ),
            "nodes": tuple(
                (node.name, node.type, node.select) for node in self.material.node_tree.nodes
            ),
            "active_node": self.material.node_tree.nodes.active,
        }

    def params(self, dry_run):
        return {
            "high_object": self.high.name,
            "low_object": self.low.name,
            "resolution": 64,
            "dry_run": dry_run,
        }

    def external_driver(self, owner):
        owner["review_value"] = 0.0
        owner["external_owner"] = self.external
        # Blender rejects this ID-spanning path in driver_add itself, but an
        # existing/imported FCurve can hold it and native evaluation writes it.
        curve = owner.driver_add('["review_value"]')
        curve.data_path = '["external_owner"].location'
        curve.array_index = 1
        curve.driver.expression = "0.7"
        self.scene.frame_set(2)
        self.assertAlmostEqual(self.external.location.y, 0.7, places=6)
        self.assertTrue(curve.driver.is_valid)
        self.external.location.y = 0.83
        owner.update_tag()

    def assert_refused_unchanged(self, params):
        before, allocation = self.state(), identities()
        error = None
        try:
            baking.bake_normal(params)
        except ValueError as caught:
            error = caught
        self.assertEqual(self.state(), before, "Refusal must precede external/source evaluation")
        self.assertEqual(identities(), allocation, "Refusal must precede owned allocation")
        self.assertIsNotNone(error, "Static baking accepted an animated dependency")
        self.assertRegex(str(error), "static|animat|driver|dependency")

    def driver_case(self, kind, dry_run):
        owner = {
            "mesh": self.low.data,
            "material": self.material,
            "node_tree": self.material.node_tree,
        }[kind]
        self.external_driver(owner)
        self.assert_refused_unchanged(self.params(dry_run))

    def test_mesh_driver_preview_refuses_before_external_write(self):
        self.driver_case("mesh", True)

    def test_mesh_driver_apply_refuses_before_external_write(self):
        self.driver_case("mesh", False)

    def test_material_driver_preview_refuses_before_external_write(self):
        self.driver_case("material", True)

    def test_material_driver_apply_refuses_before_external_write(self):
        self.driver_case("material", False)

    def test_node_tree_driver_preview_refuses_before_external_write(self):
        self.driver_case("node_tree", True)

    def test_node_tree_driver_apply_refuses_before_external_write(self):
        self.driver_case("node_tree", False)

    def nested_group(self):
        group = bpy.data.node_groups.new("BakeNestedColor", "ShaderNodeTree")
        group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        value = group.nodes.new("ShaderNodeRGB")
        output = group.nodes.new("NodeGroupOutput")
        group.links.new(value.outputs[0], output.inputs[0])
        instance = self.material.node_tree.nodes.new("ShaderNodeGroup")
        instance.node_tree = group
        shader = next(
            node for node in self.material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
        )
        self.material.node_tree.links.new(instance.outputs[0], shader.inputs["Base Color"])
        return group

    def test_nested_group_driver_refuses_preview_and_apply_before_external_write(self):
        group = self.nested_group()
        self.external_driver(group)
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                self.assert_refused_unchanged(self.params(dry_run))

    def test_static_nested_group_preview_and_real_bake_preserve_sources(self):
        group = self.nested_group()
        before, allocation = self.state(), identities()
        preview = baking.bake_normal(self.params(True))
        self.assertTrue(preview["dry_run"])
        self.assertEqual(self.state(), before)
        self.assertEqual(identities(), allocation)
        result = baking.bake_normal(self.params(False))
        self.assertTrue(result["packed"])
        self.assertTrue(result["detail_present"])
        self.assertEqual(self.state(), before)
        self.assertIsNone(group.animation_data)

    def test_ordinary_animated_mesh_high_low_cage_refuses_before_evaluation(self):
        cage = self.low.copy()
        cage.data = self.low.data.copy()
        cage.location.z = 0.09
        self.scene.collection.objects.link(cage)
        self.source_objects.append(cage)
        for obj in (self.high, self.low, cage):
            for dry_run in (True, False):
                with self.subTest(owner=obj.name, dry_run=dry_run):
                    obj.data["review_value"] = 0.0
                    obj.data.keyframe_insert(data_path='["review_value"]', frame=1)
                    params = {**self.params(dry_run), "cage_object": cage.name}
                    try:
                        with patch.object(
                            baking,
                            "inspected_mesh",
                            side_effect=AssertionError("Animated source reached graph evaluation"),
                        ):
                            self.assert_refused_unchanged(params)
                    finally:
                        obj.data.animation_data_clear()


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BakeDependencyReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
