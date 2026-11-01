"""Owned-scene morph sampling and explicit baked-rig skin rebinding regressions."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import animation, pose_correctives, shape_baking  # noqa: E402
from framewright.api import dispatch  # noqa: E402

START, END = 1, 49


def fixture():
    scene = bpy.context.scene
    data = bpy.data.armatures.new("MorphSourceRigData")
    rig = bpy.data.objects.new("MorphSourceRig", data)
    scene.collection.objects.link(rig)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    parent = None
    for name, head, tail in (
        ("Upper", (0, 0, 2), (0, 0, 1)),
        ("Joint", (0, 0, 1), (0, 0, 0)),
        ("End", (0, 0, 0), (0, -0.3, 0)),
    ):
        bone = data.edit_bones.new(name)
        bone.head, bone.tail, bone.parent = head, tail, parent
        bone.use_connect = parent is not None
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.location = (1.3, -0.4, 0.2)
    rig.rotation_euler = (0.12, 0.23, 0.15)
    rig.pose.bones["Joint"].rotation_mode = "XYZ"
    for frame, angle in ((START, 0), (25, 125), (END, 0)):
        rig.pose.bones["Joint"].rotation_euler.x = math.radians(angle)
        rig.pose.bones["Joint"].keyframe_insert("rotation_euler", frame=frame)
    for layer in rig.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"
    mesh = bpy.data.meshes.new("MorphSourceMeshData")
    vertices = [
        (x, y, z)
        for z in (0.3, 0.8, 1.2, 1.7)
        for x, y in ((-0.17, -0.11), (0.19, -0.11), (0.19, 0.13), (-0.17, 0.13))
    ]
    faces = [
        (i * 4 + j, i * 4 + (j + 1) % 4, (i + 1) * 4 + (j + 1) % 4, (i + 1) * 4 + j)
        for i in range(3)
        for j in range(4)
    ]
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="MorphUV")
    for face in mesh.polygons:
        for loop, co in zip(face.loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
            uv.data[loop].uv = co
    host = bpy.data.objects.new("MorphSourceMesh", mesh)
    scene.collection.objects.link(host)
    host.parent = rig
    group_upper = host.vertex_groups.new(name="Upper")
    group_joint = host.vertex_groups.new(name="Joint")
    for vertex in mesh.vertices:
        upper = max(0, min(1, (vertex.co.z - 0.5)))
        group_upper.add([vertex.index], upper, "REPLACE")
        group_joint.add([vertex.index], 1 - upper, "REPLACE")
    host.modifiers.new("ExplicitArmature", "ARMATURE").object = rig
    host.shape_key_add(name="Basis")
    key = host.shape_key_add(name="JointBulge")
    for index in (4, 5, 8, 9):
        key.data[index].co.y -= 0.12
    other = host.shape_key_add(name="SecondaryPulse")
    for index in (6, 7, 10, 11):
        other.data[index].co.x += 0.07
    for frame, value in ((START, 0), (17, 0.8), (33, 0.1), (END, 0.5)):
        other.value = value
        other.keyframe_insert("value", frame=frame)
    # A nonlinear half-cosine driver plus an independently authored action prove
    # all key channels survive the bake rather than a single convenient curve.
    pose_correctives._install_driver(key, rig, ("Upper", "Joint", "End"), 20, 110)
    scene.frame_start, scene.frame_end = START, END
    scene.frame_set(7, subframe=0.25)
    bpy.context.view_layer.update()
    receipt = animation.bake_animation(
        dict(object_name=rig.name, frame_start=START, frame_end=END, max_samples=128, dry_run=False)
    )
    baked = bpy.data.objects[receipt["derivative"]]
    return rig, host, baked


def ids():
    return {
        name: set(getattr(bpy.data, name))
        for name in ("objects", "meshes", "armatures", "shape_keys", "actions", "scenes")
    }


def source_state(rig, host, baked):
    keys = host.data.shape_keys
    return {
        "frame": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
        "transforms": [
            (
                o.name,
                tuple(o.location),
                tuple(o.rotation_euler),
                tuple(o.scale),
                tuple(tuple(row) for row in o.matrix_world),
            )
            for o in (rig, host, baked)
        ],
        "pose": [
            (
                o.name,
                [
                    (
                        p.name,
                        tuple(p.location),
                        tuple(p.rotation_euler),
                        tuple(p.rotation_quaternion),
                        tuple(p.scale),
                    )
                    for p in o.pose.bones
                ],
            )
            for o in (rig, baked)
        ],
        "keys": [
            (key.name, key.value, key.mute, [tuple(p.co) for p in key.data])
            for key in keys.key_blocks
        ],
        "drivers": [
            (
                c.data_path,
                c.driver.expression,
                [
                    (
                        v.name,
                        [
                            (t.id.as_pointer() if t.id else None, t.bone_target, t.data_path)
                            for t in v.targets
                        ],
                    )
                    for v in c.driver.variables
                ],
            )
            for c in keys.animation_data.drivers
        ],
        "actions": (
            rig.animation_data.action.as_pointer(),
            baked.animation_data.action.as_pointer(),
            keys.animation_data.action.as_pointer(),
        ),
        "action_curves": [
            [
                (
                    bag.slot_handle,
                    curve.data_path,
                    curve.array_index,
                    [
                        (
                            tuple(point.co),
                            tuple(point.handle_left),
                            tuple(point.handle_right),
                            point.interpolation,
                        )
                        for point in curve.keyframe_points
                    ],
                )
                for layer in action.layers
                for strip in layer.strips
                for bag in strip.channelbags
                for curve in bag.fcurves
            ]
            for action in (
                rig.animation_data.action,
                baked.animation_data.action,
                keys.animation_data.action,
            )
        ],
        "weights": [[(g.group, g.weight) for g in v.groups] for v in host.data.vertices],
        "active": bpy.context.view_layer.objects.active,
        "selected": tuple(bpy.context.selected_objects),
    }


class ShapeBakeTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("ShapeBakeTests")
        bpy.context.window.scene = self.scene
        self.before = ids()
        self.rig, self.host, self.baked = fixture()
        self.params = dict(
            object_name=self.host.name,
            armature_name=self.rig.name,
            baked_armature_name=self.baked.name,
            shape_keys=["JointBulge", "SecondaryPulse"],
            frame_start=START,
            frame_end=END,
            max_samples=128,
            max_interpolation_error=0.003,
        )

    def tearDown(self):
        bpy.context.window.scene = self.old_scene
        for name in ("objects", "meshes", "armatures", "actions", "scenes"):
            store = getattr(bpy.data, name)
            for value in set(store) - self.before[name]:
                store.remove(value, do_unlink=True)
        bpy.data.scenes.remove(self.scene)

    def test_public_preview_samples_entire_interval_without_retaining_ids(self):
        before, allocation = source_state(self.rig, self.host, self.baked), ids()
        result = dispatch(
            dict(
                schema_version="1.0",
                request_id="shape-preview",
                command="animation.bake_shape_keys",
                params=self.params,
            )
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["frame_count"], 49)
        self.assertEqual(result["result"]["validation_sample_count"], 97)
        self.assertEqual(before, source_state(self.rig, self.host, self.baked))
        self.assertEqual(allocation, ids())

    def test_derivative_has_owned_action_complete_samples_and_exact_rebinding(self):
        before = source_state(self.rig, self.host, self.baked)
        result = shape_baking.bake_shape_keys({**self.params, "dry_run": False})
        derivative = bpy.data.objects[result["derivative"]]
        keys = derivative.data.shape_keys
        self.assertEqual(before, source_state(self.rig, self.host, self.baked))
        self.assertIs(derivative.parent, self.baked)
        self.assertIs(derivative.modifiers[0].object, self.baked)
        self.assertEqual(derivative.matrix_parent_inverse, self.host.matrix_parent_inverse)
        self.assertNotEqual(keys, self.host.data.shape_keys)
        self.assertNotEqual(
            keys.animation_data.action, self.host.data.shape_keys.animation_data.action
        )
        self.assertFalse(keys.animation_data.drivers)
        self.assertFalse(keys.animation_data.nla_tracks)
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        curves = [
            c
            for layer in keys.animation_data.action.layers
            for s in layer.strips
            for b in s.channelbags
            for c in b.fcurves
        ]
        self.assertEqual(len(curves), 2)
        self.assertTrue(all(len(c.keyframe_points) == 49 for c in curves))
        self.assertTrue(all(k.interpolation == "LINEAR" for c in curves for k in c.keyframe_points))

    def test_sampling_preserves_unrelated_and_internal_dirty_values(self):
        light = bpy.data.lights.new("ShapeUnrelated", "POINT")
        obj = bpy.data.objects.new("ShapeUnrelated", light)
        self.scene.collection.objects.link(obj)
        light.energy = 10
        light.keyframe_insert("energy", frame=1)
        light.energy = 200
        light.keyframe_insert("energy", frame=49)
        constraint = self.rig.pose.bones["Upper"].constraints.new("LIMIT_ROTATION")
        constraint.influence = 0.1
        constraint.keyframe_insert("influence", frame=1)
        constraint.influence = 0.9
        constraint.keyframe_insert("influence", frame=49)
        key = self.host.data.shape_keys.key_blocks["SecondaryPulse"]
        self.scene.frame_set(7, subframe=0.25)
        constraint.influence = 0.4321
        light.energy = 123.456
        key.value = 0.3456
        before = source_state(self.rig, self.host, self.baked)
        exact_light = light.energy
        exact_constraint = constraint.influence
        try:
            shape_baking.bake_shape_keys(self.params)
            self.assertEqual(source_state(self.rig, self.host, self.baked), before)
            self.assertEqual(light.energy, exact_light)
            self.assertEqual(constraint.influence, exact_constraint)
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.lights.remove(light)

    def test_global_handlers_are_rejected_before_callbacks_or_allocations(self):
        light = bpy.data.lights.new("MorphHandlerUnrelated", "POINT")
        light.energy = 123.456
        initial_energy = light.energy
        try:
            for handler_name in (
                "frame_change_pre",
                "frame_change_post",
                "depsgraph_update_pre",
                "depsgraph_update_post",
            ):
                for dry_run in (True, False):
                    with self.subTest(handler=handler_name, dry_run=dry_run):
                        calls = []

                        def mutate_unrelated(*args, log=calls):
                            log.append(args[0].name)
                            light.energy = 42

                        handlers = getattr(bpy.app.handlers, handler_name)
                        allocation = ids()
                        state = source_state(self.rig, self.host, self.baked)
                        handlers.append(mutate_unrelated)
                        try:
                            result = dispatch(
                                dict(
                                    schema_version="1.0",
                                    request_id="shape-handler-guard",
                                    command="animation.bake_shape_keys",
                                    params={**self.params, "dry_run": dry_run},
                                )
                            )
                        finally:
                            handlers.remove(mutate_unrelated)
                        self.assertEqual(calls, [], f"Global {handler_name} callback ran")
                        self.assertFalse(result["ok"], result)
                        self.assertIn("handler", str(result).lower())
                        self.assertEqual(light.energy, initial_energy)
                        self.assertEqual(allocation, ids())
                        self.assertEqual(state, source_state(self.rig, self.host, self.baked))
        finally:
            bpy.data.lights.remove(light)

    def test_animated_armature_data_is_rejected_before_sampling(self):
        for rig in (self.rig, self.baked):
            with self.subTest(rig=rig.name):
                rig.data["authored_review_value"] = 0.1
                rig.data.keyframe_insert('["authored_review_value"]', frame=1)
                rig.data["authored_review_value"] = 0.9
                rig.data.keyframe_insert('["authored_review_value"]', frame=49)
                rig.data["authored_review_value"] = 0.4321
                before = ids()
                with self.assertRaisesRegex(ValueError, "data-animated"):
                    shape_baking.bake_shape_keys(self.params)
                self.assertEqual(rig.data["authored_review_value"], 0.4321)
                self.assertEqual(ids(), before)
                rig.data.animation_data_clear()

    def test_sampling_excludes_display_widgets_and_their_material_dependencies(self):
        widget_mesh = bpy.data.meshes.new("MorphDisplayWidgetMesh")
        widget_mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
        widget = bpy.data.objects.new("MorphDisplayWidget", widget_mesh)
        self.scene.collection.objects.link(widget)
        material = bpy.data.materials.new("MorphDisplayWidgetMaterial")
        material.use_nodes = True
        widget_mesh.materials.append(material)
        socket = material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"]
        socket.default_value = 0.1
        socket.keyframe_insert("default_value", frame=1)
        socket.default_value = 0.9
        socket.keyframe_insert("default_value", frame=49)
        widget.location.x = 0
        widget.keyframe_insert("location", frame=1)
        widget.location.x = 1
        widget.keyframe_insert("location", frame=49)
        for rig in (self.rig, self.baked):
            rig.pose.bones["Joint"].custom_shape = widget
            rig.pose.bones["Joint"].custom_shape_transform = rig.pose.bones["Upper"]
        self.scene.frame_set(7, subframe=0.25)
        widget.location.x = 0.3456
        socket.default_value = 0.4321
        exact_location, exact_socket = tuple(widget.location), socket.default_value
        allocation = ids()
        try:
            with shape_baking._sampling_scene(bpy.context, self.host, self.rig, self.baked) as (
                _,
                _,
                source_copy,
                target_copy,
            ):
                for rig in (source_copy, target_copy):
                    self.assertIsNone(rig.pose.bones["Joint"].custom_shape)
                    self.assertIsNone(rig.pose.bones["Joint"].custom_shape_transform)
            shape_baking.bake_shape_keys(self.params)
            self.assertEqual(tuple(widget.location), exact_location)
            self.assertEqual(socket.default_value, exact_socket)
            self.assertEqual(allocation, ids())
            for rig in (self.rig, self.baked):
                self.assertIs(rig.pose.bones["Joint"].custom_shape, widget)
                self.assertEqual(
                    rig.pose.bones["Joint"].custom_shape_transform, rig.pose.bones["Upper"]
                )
        finally:
            bpy.data.materials.remove(material, do_unlink=True)

    def test_missing_keys_modifiers_segments_and_wrong_rig_are_rejected(self):
        before = ids()
        with self.assertRaises(ValueError):
            shape_baking.bake_shape_keys({**self.params, "shape_keys": ["JointBulge"]})
        self.host.modifiers.new("Unsupported", "SUBSURF")
        with self.assertRaisesRegex(ValueError, "modifier"):
            shape_baking.bake_shape_keys(self.params)
        self.host.modifiers.remove(self.host.modifiers[-1])
        self.rig.data.bones["Joint"].bbone_segments = 4
        with self.assertRaisesRegex(ValueError, "segment|Bendy"):
            shape_baking.bake_shape_keys(self.params)
        self.rig.data.bones["Joint"].bbone_segments = 1
        self.baked.data.bones["Joint"].use_deform = False
        with self.assertRaisesRegex(ValueError, "rest|hierarchy"):
            shape_baking.bake_shape_keys(self.params)
        self.assertEqual(ids(), before)

    def test_strict_midpoint_gate_rejects_nonlinear_sampling_before_derivative(self):
        before, state = ids(), source_state(self.rig, self.host, self.baked)
        with self.assertRaisesRegex(ValueError, "interpolation"):
            shape_baking.bake_shape_keys(
                {**self.params, "max_interpolation_error": 1e-10, "dry_run": False}
            )
        self.assertEqual(ids(), before)
        self.assertEqual(state, source_state(self.rig, self.host, self.baked))

    def test_injected_action_failure_cleans_owned_sampling_and_derivative(self):
        before, state = ids(), source_state(self.rig, self.host, self.baked)
        with patch.object(
            shape_baking, "_write_action", side_effect=RuntimeError("injected action failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                shape_baking.bake_shape_keys({**self.params, "dry_run": False})
        self.assertEqual(ids(), before)
        self.assertEqual(state, source_state(self.rig, self.host, self.baked))

    def test_completed_action_then_failure_is_also_removed(self):
        before, state = ids(), source_state(self.rig, self.host, self.baked)
        original = shape_baking._write_action

        def fail(*args):
            original(*args)
            raise RuntimeError("after action")

        with patch.object(shape_baking, "_write_action", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "after action"):
                shape_baking.bake_shape_keys({**self.params, "dry_run": False})
        self.assertEqual(ids(), before)
        self.assertEqual(state, source_state(self.rig, self.host, self.baked))

    def test_nonportable_skinning_modes_and_wrong_target_motion_are_rejected(self):
        before = ids()
        self.host.modifiers[0].use_deform_preserve_volume = True
        with self.assertRaisesRegex(ValueError, "linear|skinning"):
            shape_baking.bake_shape_keys(self.params)
        self.host.modifiers[0].use_deform_preserve_volume = False
        for layer in self.baked.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.co.x += 3
        with self.assertRaisesRegex(ValueError, "sampled poses"):
            shape_baking.bake_shape_keys(self.params)
        self.assertEqual(ids(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ShapeBakeTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
