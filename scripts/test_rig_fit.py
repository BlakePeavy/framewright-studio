"""Explicit landmark fitting fixtures; no inferred anatomical positions."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import addon_utils  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from test_rigging_animation import RigAnimationTests  # noqa: E402

from framewright import rig_fit, rigging  # noqa: E402


class RigFitTests(unittest.TestCase):
    tearDown = RigAnimationTests.tearDown

    def setUp(self):
        RigAnimationTests.setUp(self)
        if not addon_utils.check("rigify")[1]:
            addon_utils.enable("rigify", default_set=True)
        self.rig.pose.bones["Root"].rigify_type = "basic.super_copy"
        bpy.ops.object.mode_set(mode="EDIT")
        self.rig.data.edit_bones["Tip"].use_connect = True
        bpy.ops.object.mode_set(mode="OBJECT")

    def snapshot(self, obj):
        return {
            "channels": rigging._transform_channels(obj),
            "bones": {
                bone.name: {
                    "matrix": tuple(tuple(row) for row in bone.matrix_local),
                    "head": tuple(bone.head_local),
                    "tail": tuple(bone.tail_local),
                    "parent": bone.parent.name if bone.parent else None,
                    "connected": bone.use_connect,
                }
                for bone in obj.data.bones
            },
            "action": obj.animation_data.action.as_pointer()
            if obj.animation_data and obj.animation_data.action
            else None,
        }

    def test_explicit_world_centimeter_fit_preserves_source_and_connected_chain(self):
        self.rig.location = (1.4, -0.6, 0.2)
        self.rig.rotation_euler = (0.123, 0.234, 0.15)
        bpy.context.view_layer.update()
        landmarks = {
            name: list(self.rig.matrix_world @ Vector(position) * 100.0)
            for name, position in {
                "base": (0, 0, 0),
                "joint": (0, 0, 1.2),
                "end": (0, 0, 2.4),
            }.items()
        }
        params = {
            "object_name": self.rig.name,
            "landmarks": landmarks,
            "bone_map": {
                "Root": {"head": "base", "tail": "joint"},
                "Tip": {"head": "joint", "tail": "end"},
            },
            "units": "centimeters",
        }
        before = self.snapshot(self.rig)
        count = len(self.scene.objects)
        preview = rig_fit.fit_metarig(params)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(len(self.scene.objects), count)
        result = rig_fit.fit_metarig({**params, "dry_run": False})
        derivative = self.scene.objects[result["derivative"]]
        self.assertEqual(self.snapshot(self.rig), before)
        self.assertAlmostEqual(derivative.data.bones["Root"].length, 1.2, places=5)
        self.assertLess(
            (
                derivative.data.bones["Tip"].head_local - derivative.data.bones["Root"].tail_local
            ).length,
            1e-6,
        )
        self.assertTrue(derivative.data.bones["Tip"].use_connect)
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        self.assertIs(bpy.context.active_object, self.rig)

    def test_inconsistent_connectivity_and_zero_lengths_fail_before_creation(self):
        count = len(self.scene.objects)
        params = {
            "object_name": self.rig.name,
            "coordinate_space": "armature_local",
            "units": "blender_units",
            "landmarks": {"head": [0, 0, 0], "tail": [0, 0, 1.2]},
            "bone_map": {"Root": {"head": "head", "tail": "tail"}},
            "dry_run": False,
        }
        with self.assertRaisesRegex(ValueError, "connected"):
            rig_fit.fit_metarig(params)
        params["landmarks"]["tail"] = [0, 0, 0]
        with self.assertRaisesRegex(ValueError, "length"):
            rig_fit.fit_metarig(params)
        params["landmarks"] = {"head": [0, 0, 1], "tail": [0, 0, 1.0000005]}
        with self.assertRaisesRegex(ValueError, "length"):
            rig_fit.fit_metarig({**params, "dry_run": True})
        self.assertEqual(len(self.scene.objects), count)

    def test_unmapped_protected_control_rest_data_is_retained(self):
        params = {
            "object_name": self.rig.name,
            "coordinate_space": "armature_local",
            "units": "blender_units",
            "landmarks": {"head": [0, 0.1, 0], "tail": [0, 0, 1]},
            "bone_map": {"Root": {"head": "head", "tail": "tail"}},
            "protected_bones": ["Tip"],
            "dry_run": False,
        }
        before = self.snapshot(self.rig)
        result = rig_fit.fit_metarig(params)
        derivative = self.scene.objects[result["derivative"]]
        self.assertEqual(
            tuple(derivative.data.bones["Tip"].head_local), before["bones"]["Tip"]["head"]
        )
        self.assertEqual(
            tuple(derivative.data.bones["Tip"].tail_local), before["bones"]["Tip"]["tail"]
        )
        self.assertEqual(self.snapshot(self.rig), before)
        with self.assertRaisesRegex(ValueError, "protected"):
            rig_fit.fit_metarig({**params, "protected_bones": ["Root"]})

    def test_failure_restores_mode_selection_and_removes_only_derivative(self):
        params = {
            "object_name": self.rig.name,
            "coordinate_space": "armature_local",
            "units": "blender_units",
            "landmarks": {"head": [0, 0.1, 0], "tail": [0, 0, 1]},
            "bone_map": {"Root": {"head": "head", "tail": "tail"}},
            "dry_run": False,
        }
        before = self.snapshot(self.rig)
        objects = {obj.as_pointer() for obj in bpy.data.objects}
        with patch.object(rig_fit, "_apply_fit", side_effect=RuntimeError("injected edit failure")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                rig_fit.fit_metarig(params)
        self.assertEqual({obj.as_pointer() for obj in bpy.data.objects}, objects)
        self.assertEqual(self.snapshot(self.rig), before)
        self.assertEqual(bpy.context.mode, "OBJECT")
        self.assertIs(bpy.context.active_object, self.rig)

    def test_bundled_basic_human_explicit_fit_still_generates(self):
        bpy.ops.object.armature_basic_human_metarig_add()
        human = bpy.context.active_object
        before = self.snapshot(human)
        landmarks = {}
        mapping = {}
        for index, bone in enumerate(human.data.bones):
            head, tail = f"head_{index}", f"tail_{index}"
            landmarks[head] = list(bone.head_local)
            landmarks[tail] = list(bone.tail_local)
            mapping[bone.name] = {"head": head, "tail": tail}
        fitted = rig_fit.fit_metarig(
            {
                "object_name": human.name,
                "landmarks": landmarks,
                "bone_map": mapping,
                "units": "blender_units",
                "coordinate_space": "armature_local",
                "dry_run": False,
            }
        )
        generated = rigging.generate_rig({"object_name": fitted["derivative"], "dry_run": False})
        rig = self.scene.objects[generated["derivative"]]
        self.assertGreater(len(rig.data.bones), len(human.data.bones))
        self.assertEqual(self.snapshot(human), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RigFitTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Explicit rig-fit tests failed")
    print(f"FRAMEWRIGHT_RIG_FIT_OK tests={result.testsRun} version={bpy.app.version_string}")
