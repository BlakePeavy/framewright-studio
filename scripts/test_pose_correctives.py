"""Real Blender TDD coverage for the bounded public corrective activation command."""

import json
import math
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import pose_correctives  # noqa: E402
from framewright.api import dispatch  # noqa: E402


def counts():
    return tuple(
        len(store)
        for store in (bpy.data.objects, bpy.data.meshes, bpy.data.shape_keys, bpy.data.actions)
    )


def action_curves(action):
    return [
        curve
        for layer in action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        for curve in bag.fcurves
    ]


def sample_geometry(host, rig):
    host.hide_viewport = False
    rows = []
    for angle in (0, 19.99, 20, 20.01, 30, 60, 90, 109.99, 110, 110.01, 130, 75, 0):
        rig.pose.bones["Middle"].rotation_euler.x = math.radians(angle)
        bpy.context.view_layer.update()
        evaluated = host.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            actual = mesh.vertices[0].co.z / 0.1
        finally:
            evaluated.to_mesh_clear()
        expected = (1 - math.cos(math.pi * max(0, min(1, (angle - 20) / 90)))) / 2
        assert abs(actual - expected) < 2e-5, (angle, actual, expected)
        rows.append([angle, actual])
    return rows


class PoseCorrectiveTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("PublicCorrectiveTests")
        bpy.context.window.scene = self.scene
        data = bpy.data.armatures.new("CorrectiveRigData")
        self.rig = bpy.data.objects.new("CorrectiveRig", data)
        self.scene.collection.objects.link(self.rig)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        parent = None
        for name, head, tail in (
            ("Proximal", (0, 0, 2), (0, 0, 1)),
            ("Middle", (0, 0, 1), (0, 0, 0)),
            ("Distal", (0, 0, 0), (0, -0.2, 0)),
        ):
            bone = data.edit_bones.new(name)
            bone.head, bone.tail, bone.parent = head, tail, parent
            bone.use_connect = parent is not None
            parent = bone
        bpy.ops.object.mode_set(mode="OBJECT")
        self.rig.pose.bones["Middle"].rotation_mode = "XYZ"
        self.rig.location = (1.4, -0.6, 0.2)
        self.rig.rotation_euler = (0.12, 0.23, 0.34)
        self.rig.scale = (1.3, 1.3, 1.3)
        data = bpy.data.meshes.new("CorrectiveMeshData")
        data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        self.host = bpy.data.objects.new("CorrectiveMesh", data)
        self.scene.collection.objects.link(self.host)
        self.host.shape_key_add(name="Basis")
        self.key = self.host.shape_key_add(name="Corrective")
        self.key.data[0].co.z = 0.1
        modifier = self.host.modifiers.new("ExplicitBinding", "ARMATURE")
        modifier.object = self.rig
        self.scene.frame_set(7, subframe=0.25)
        bpy.context.view_layer.update()
        self.params = dict(
            object_name=self.host.name,
            shape_key="Corrective",
            armature_name=self.rig.name,
            proximal_bone="Proximal",
            joint_bone="Middle",
            distal_bone="Distal",
        )
        self.initial_actions = set(bpy.data.actions)

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.old_scene
        for obj in list(self.scene.objects):
            data = obj.data
            store = bpy.data.armatures if obj.type == "ARMATURE" else bpy.data.meshes
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                store.remove(data)
        bpy.data.scenes.remove(self.scene)
        for action in set(bpy.data.actions) - self.initial_actions:
            bpy.data.actions.remove(action)

    def snapshot(self):
        keys = self.host.data.shape_keys
        animation = keys.animation_data
        return {
            "keys": [
                (key.name, key.value, key.mute, tuple(tuple(v.co) for v in key.data))
                for key in keys.key_blocks
            ],
            "action": animation.action.as_pointer() if animation and animation.action else None,
            "drivers": [
                (
                    c.data_path,
                    c.driver.expression,
                    tuple(
                        (
                            v.type,
                            tuple(
                                (t.id.as_pointer() if t.id else None, t.data_path, t.bone_target)
                                for t in v.targets
                            ),
                        )
                        for v in c.driver.variables
                    ),
                )
                for c in animation.drivers
            ]
            if animation
            else [],
            "world": tuple(tuple(row) for row in self.host.matrix_world),
            "rig": tuple(tuple(row) for row in self.rig.matrix_world),
            "pose": [
                (p.name, tuple(p.location), tuple(p.rotation_euler), tuple(p.scale))
                for p in self.rig.pose.bones
            ],
            "frame": (self.scene.frame_current, self.scene.frame_subframe),
            "active": bpy.context.view_layer.objects.active.name,
            "selected": sorted(o.name for o in bpy.context.selected_objects),
            "visibility": (self.host.hide_viewport, self.host.hide_render, self.host.hide_get()),
        }

    def apply(self):
        result = pose_correctives.activate_corrective({**self.params, "dry_run": False})
        return bpy.data.objects[result["derivative"]], result

    def add_other_animation(self):
        other = self.host.shape_key_add(name="OtherAnimated")
        other.value = 0.1
        other.keyframe_insert("value", frame=1)
        other.value = 0.8
        other.keyframe_insert("value", frame=20)
        driven = self.host.shape_key_add(name="OtherDriven")
        keys = self.host.data.shape_keys
        keys["control"] = 0.2
        driver = driven.driver_add("value").driver
        driver.type = "SCRIPTED"
        variable = driver.variables.new()
        variable.name = "control"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id_type = "KEY"
        variable.targets[0].id = keys
        variable.targets[0].data_path = '["control"]'
        driver.expression = "control"
        bpy.context.view_layer.update()
        # Authored dirty overrides must survive frame/driver refreshes exactly.
        other.value = 0.37
        driven.value = 0.43
        self.key.value = 0.29

    def test_default_preview_public_dispatch_is_read_only(self):
        self.add_other_animation()
        before, allocation = self.snapshot(), counts()
        response = dispatch(
            dict(
                schema_version="1.0",
                request_id="corrective-preview",
                command="rig.activate_corrective",
                params=self.params,
            )
        )
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["result"]["dry_run"])
        self.assertEqual(response["result"]["angle_zero"], "straight_at_middle_joint")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(allocation, counts())

    def test_apply_preserves_keys_actions_drivers_and_detaches_supported_animation(self):
        self.add_other_animation()
        before = self.snapshot()
        derivative, receipt = self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertTrue(receipt["hidden"])
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        original, copied = self.host.data.shape_keys, derivative.data.shape_keys
        self.assertNotEqual(original, copied)
        self.assertNotEqual(original.animation_data.action, copied.animation_data.action)
        self.assertEqual(
            original.animation_data.action_slot.identifier,
            copied.animation_data.action_slot.identifier,
        )
        self.assertEqual(
            [
                (c.data_path, [tuple(k.co) for k in c.keyframe_points])
                for c in action_curves(original.animation_data.action)
            ],
            [
                (c.data_path, [tuple(k.co) for k in c.keyframe_points])
                for c in action_curves(copied.animation_data.action)
            ],
        )
        for key in original.key_blocks:
            self.assertEqual(
                [tuple(v.co) for v in key.data],
                [tuple(v.co) for v in copied.key_blocks[key.name].data],
            )
        old_driver = copied.animation_data.drivers.find(
            copied.key_blocks["OtherDriven"].path_from_id("value")
        )
        self.assertEqual(old_driver.driver.variables[0].targets[0].id, copied)
        copied["control"] = 0.9
        self.assertEqual(original["control"], 0.2)

    def test_geometry_continuous_and_degenerate_pose_disables_activation(self):
        derivative, receipt = self.apply()
        self.assertTrue(receipt["native_simple_expression"])
        rows = sample_geometry(derivative, self.rig)
        self.assertEqual(rows[0], rows[-1])
        self.rig.pose.bones["Middle"].scale.y = 0
        bpy.context.view_layer.update()
        self.assertEqual(derivative.data.shape_keys.key_blocks["Corrective"].value, 0)
        self.assertTrue(derivative.data.shape_keys.animation_data.drivers[0].driver.is_valid)

    def test_existing_target_animation_and_driver_are_rejected_without_mutation(self):
        self.key.keyframe_insert("value", frame=1)
        before, allocation = self.snapshot(), counts()
        with self.assertRaisesRegex(ValueError, "animation"):
            self.apply()
        self.assertEqual((before, allocation), (self.snapshot(), counts()))
        self.host.data.shape_keys.animation_data_clear()
        self.key.driver_add("value").driver.expression = "0.5"
        before, allocation = self.snapshot(), counts()
        with self.assertRaisesRegex(ValueError, "driver"):
            self.apply()
        self.assertEqual((before, allocation), (self.snapshot(), counts()))

    def test_invalid_requests_and_unsupported_dependencies_fail_before_copy(self):
        for change in (
            {"full_degrees": 20, "onset_degrees": 30},
            {"onset_degrees": float("nan")},
            {"dry_run": 1},
            {"joint_bone": "Proximal"},
            {"distal_bone": "missing"},
            {"shape_key": "Basis"},
        ):
            before, allocation = self.snapshot(), counts()
            with self.assertRaises(ValueError):
                pose_correctives.activate_corrective({**self.params, **change})
            self.assertEqual((before, allocation), (self.snapshot(), counts()))
        self.host.constraints.new("COPY_LOCATION").target = self.rig
        with self.assertRaisesRegex(ValueError, "constraints"):
            self.apply()
        self.host.constraints.clear()
        other = self.host.shape_key_add(name="ExternalDriver")
        driver = other.driver_add("value").driver
        driver.expression = '__import__("math").sin(0)'
        with self.assertRaisesRegex(ValueError, "native"):
            self.apply()
        other.driver_remove("value")
        self.host.data.shape_keys.animation_data.nla_tracks.new()
        with self.assertRaisesRegex(ValueError, "NLA"):
            self.apply()

    def test_copy_failure_cleans_owned_data_and_restores_source(self):
        self.add_other_animation()
        self.host.data.shape_keys.animation_data.action.use_fake_user = True
        before, allocation = self.snapshot(), counts()
        with patch.object(
            pose_correctives, "_install_driver", side_effect=RuntimeError("injected driver failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.apply()
        self.assertEqual((before, allocation), (self.snapshot(), counts()))

    def test_context_restore_failure_also_rolls_back_owned_derivative(self):
        self.add_other_animation()
        before, allocation = self.snapshot(), counts()
        preserve = pose_correctives.preserve_time

        @contextmanager
        def fail_after_restoring(*args):
            with preserve(*args):
                yield
            raise RuntimeError("injected restoration failure")

        with patch.object(pose_correctives, "preserve_time", fail_after_restoring):
            with self.assertRaisesRegex(RuntimeError, "restoration"):
                self.apply()
        self.assertEqual((before, allocation), (self.snapshot(), counts()))

    def test_tiny_valid_world_segments_keep_angle_scale_invariance(self):
        derivative, _ = self.apply()
        self.rig.location = (0, 0, 0)
        self.rig.rotation_euler = (0, 0, 0)
        self.rig.scale = (1e-7, 1e-7, 1e-7)
        sample_geometry(derivative, self.rig)

    def test_external_constraint_pole_dependency_is_rejected_in_preview(self):
        constraint = self.rig.pose.bones["Middle"].constraints.new("IK")
        constraint.target = self.rig
        constraint.subtarget = "Distal"
        constraint.pole_target = self.host
        before = counts()
        with self.assertRaisesRegex(ValueError, "constraints"):
            pose_correctives.activate_corrective(self.params)
        self.assertEqual(before, counts())

    def test_rigify_native_sum_and_polynomial_driver_is_supported(self):
        self.rig["factor"], self.rig["driven"] = 0.25, 0.0
        curve = self.rig.driver_add('["driven"]')
        curve.driver.type = "SUM"
        variable = curve.driver.variables.new()
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = self.rig
        variable.targets[0].data_path = '["factor"]'
        modifier = curve.modifiers.new("GENERATOR")
        modifier.poly_order = 1
        modifier.coefficients = (0, 1)
        before = self.snapshot()
        derivative, _ = self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(curve.driver.type, "SUM")
        self.assertEqual(tuple(modifier.coefficients), (0, 1))
        self.assertIsNotNone(derivative.data.shape_keys.animation_data)

    def test_cold_reopen_with_autoexecution_disabled(self):
        derivative, _ = self.apply()
        derivative.name = "ColdCorrective"
        expected = sample_geometry(derivative, self.rig)
        with tempfile.TemporaryDirectory(prefix="fw-public-corrective-") as temporary:
            blend, output = Path(temporary) / "candidate.blend", Path(temporary) / "result.json"
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
            result = subprocess.run(
                [
                    bpy.app.binary_path,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(Path(__file__).resolve()),
                    "--",
                    "--cold",
                    str(blend),
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])
            self.assertEqual(json.loads(output.read_text()), expected)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if args and args[0] == "--cold":
        bpy.ops.wm.open_mainfile(filepath=args[1])
        assert not bpy.context.preferences.filepaths.use_scripts_auto_execute
        Path(args[2]).write_text(
            json.dumps(
                sample_geometry(
                    bpy.data.objects["ColdCorrective"], bpy.data.objects["CorrectiveRig"]
                )
            )
        )
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(PoseCorrectiveTests)
        )
        if not result.wasSuccessful():
            raise AssertionError("Public corrective activation tests failed")
