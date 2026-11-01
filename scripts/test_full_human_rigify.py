"""Actual full stock Rigify template/control regressions in isolated Blender.

No anatomical fitting, production skin, native import or artistic approval is implied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import addon_utils  # noqa: E402
import bpy  # noqa: E402

from framewright import rigging, secondary_motion  # noqa: E402

MEASUREMENTS = {}
INJECT_DISABLE_FINGERS = False


def primitive(value):
    if isinstance(value, bpy.types.ID):
        return {"type": value.bl_rna.identifier, "name": value.name, "pointer": value.as_pointer()}
    if isinstance(value, dict) or hasattr(value, "to_dict"):
        return {k: primitive(v) for k, v in dict(value).items()}
    if hasattr(value, "to_list") or isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    return value


def action_record(obj):
    data = obj.animation_data
    if not data or not data.action:
        return None
    action = data.action
    return {
        "pointer": action.as_pointer(),
        "name": action.name,
        "curves": [
            {
                "path": curve.data_path,
                "index": curve.array_index,
                "keys": [list(key.co) for key in curve.keyframe_points],
            }
            for layer in action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            for curve in bag.fcurves
        ],
    }


def snapshot(obj):
    record = {
        "object": obj.as_pointer(),
        "data": obj.data.as_pointer(),
        "channels": rigging._transform_channels(obj),
        "action": action_record(obj),
        "object_properties": primitive(dict(obj.items())),
        "data_properties": primitive(dict(obj.data.items())),
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "matrix": [list(row) for row in bone.matrix_local],
                "connected": bone.use_connect,
                "deform": bone.use_deform,
                "collections": sorted(c.name for c in bone.collections),
                "properties": primitive(dict(bone.items())),
            }
            for bone in obj.data.bones
        ],
        "pose": [
            {
                "name": bone.name,
                "channels": rigging._transform_channels(bone),
                "rigify_type": bone.rigify_type,
                "parameters": primitive(dict(bone.rigify_parameters.items())),
                "custom_shape": bone.custom_shape.as_pointer() if bone.custom_shape else None,
                "properties": primitive(dict(bone.items())),
            }
            for bone in obj.pose.bones
        ],
        "rigify_references": {
            name: primitive(getattr(obj.data, name))
            for name in (
                "rigify_target_rig",
                "rigify_rig_ui",
                "rigify_widgets_collection",
                "rigify_finalize_script",
                "rigify_rig_basename",
            )
        },
    }
    return record


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def visible(rig):
    rig.hide_viewport = False
    rig.hide_render = False
    rig.hide_set(False)
    bpy.context.view_layer.update()


def points(rig, names):
    bpy.context.view_layer.update()
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {name: evaluated.matrix_world @ evaluated.pose.bones[name].tail for name in names}


class FullHumanRigifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not addon_utils.check("rigify")[1]:
            # Stock Rigify's register() reads its in-memory preferences entry.
            # No save_userpref call occurs in this factory-startup test process.
            addon_utils.enable("rigify", default_set=True, persistent=False)

    def setUp(self):
        from rigify.metarigs import human

        self.stores = (
            bpy.data.objects,
            bpy.data.meshes,
            bpy.data.armatures,
            bpy.data.collections,
            bpy.data.texts,
            bpy.data.actions,
        )
        self.retained = [{item.as_pointer() for item in store} for store in self.stores]
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("FullStockHumanTest")
        self.scene.unit_settings.system = "METRIC"
        self.scene.unit_settings.scale_length = 1.0
        bpy.context.window.scene = self.scene
        self.source = bpy.data.objects.new(
            "FullHumanSource", bpy.data.armatures.new("FullHumanData")
        )
        self.scene.collection.objects.link(self.source)
        self.source.select_set(True)
        bpy.context.view_layer.objects.active = self.source
        human.create(self.source)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.source.location = (1.4, -0.6, 0.2)
        self.source.rotation_euler.z = 0.23
        self.source.keyframe_insert("location", frame=1)
        self.source.keyframe_insert("location", frame=11)
        self.scene.frame_set(7)
        self.target = bpy.data.objects.new(
            "PreservedPriorTarget", bpy.data.armatures.new("PriorTargetData")
        )
        self.scene.collection.objects.link(self.target)
        self.target.location = (0.22, 0.33, 0.44)
        self.target["must_survive"] = 31
        self.ui_script = bpy.data.texts.new("PreservedPriorUIScript")
        self.ui_script.write("raise RuntimeError('source UI text must never execute')\n")
        self.widgets = bpy.data.collections.new("PreservedPriorWidgets")
        self.scene.collection.children.link(self.widgets)
        widget = bpy.data.objects.new("PreservedWidget", bpy.data.meshes.new("PreservedWidgetMesh"))
        self.widgets.objects.link(widget)
        self.source.pose.bones["face"].custom_shape = widget
        self.source.data.rigify_target_rig = self.target
        self.source.data.rigify_rig_ui = self.ui_script
        self.source.data.rigify_widgets_collection = self.widgets
        self.source.data.rigify_rig_basename = "DoNotReplaceExisting"
        bpy.context.view_layer.update()
        self.before = snapshot(self.source)
        self.target_before = snapshot(self.target)
        self.script_before = self.ui_script.as_string()
        self.selection_before = {o.name for o in bpy.context.selected_objects}

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.window.scene = self.old_scene
        for store, retained in zip(self.stores, self.retained, strict=True):
            for item in list(store):
                if item.as_pointer() not in retained:
                    store.remove(item, do_unlink=True)
        bpy.data.scenes.remove(self.scene)

    def preserved(self):
        self.assertEqual(snapshot(self.source), self.before)
        self.assertEqual(snapshot(self.target), self.target_before)
        self.assertEqual(self.ui_script.as_string(), self.script_before)
        self.assertIs(self.source.data.rigify_target_rig, self.target)
        self.assertIs(self.source.data.rigify_rig_ui, self.ui_script)
        self.assertIs(self.source.data.rigify_widgets_collection, self.widgets)
        self.assertEqual(self.scene.frame_current, 7)
        self.assertEqual({o.name for o in bpy.context.selected_objects}, self.selection_before)
        self.assertIs(bpy.context.active_object, self.source)

    def generate(self):
        report = rigging.generate_rig({"object_name": self.source.name, "dry_run": False})
        generated = self.scene.objects[report["derivative"]]
        self.assertIsNot(generated, self.source)
        self.assertIsNot(generated, self.target)
        self.assertIsNot(generated.data, self.source.data)
        self.assertTrue(generated.hide_viewport and generated.hide_render)
        self.assertEqual(generated.matrix_world, self.source.matrix_world)
        self.preserved()
        visible(generated)
        return generated, report

    def test_full_template_preview_is_read_only(self):
        before = [{item.as_pointer() for item in store} for store in self.stores]
        report = rigging.generate_rig({"object_name": self.source.name})
        self.assertTrue(report["dry_run"])
        self.assertIn("faces.super_face", report["rig_types"])
        self.assertIn("limbs.super_finger", report["rig_types"])
        self.assertGreater(len(self.source.data.bones), 100)
        self.assertEqual(before, [{item.as_pointer() for item in store} for store in self.stores])
        self.preserved()

    def test_stock_generation_has_hand_face_controls_and_preserves_existing_targets(self):
        generated, result = self.generate()
        controls = (
            "hand_ik.L",
            "hand_ik.R",
            "hand_fk.L",
            "hand_fk.R",
            "f_index.01_master.L",
            "thumb.01_master.R",
            "jaw_master",
            "eyes",
            "lid.T.L.002",
            "lid.T.R.002",
            "tongue",
        )
        for name in controls:
            self.assertIn(name, generated.pose.bones)
            self.assertIsNotNone(generated.pose.bones[name].custom_shape)
        self.assertGreater(sum(b.use_deform for b in generated.data.bones), 100)
        self.assertGreater(len(generated.animation_data.drivers), 20)
        metarig = self.scene.objects[result["metarig_derivative"]]
        self.assertIs(metarig.data.rigify_target_rig, generated)
        self.assertIsNone(metarig.data.rigify_finalize_script)
        self.assertIsNot(metarig.data.rigify_rig_ui, self.ui_script)
        MEASUREMENTS["generation"] = {
            "metarig_bones": len(self.source.data.bones),
            "generated_bones": len(generated.data.bones),
            "deform_bones": sum(b.use_deform for b in generated.data.bones),
            "drivers": len(generated.animation_data.drivers),
            "required_controls": controls,
            "source_fingerprint": digest(self.before),
            "source_preserved": True,
        }

    def test_all_ten_digit_controls_move_deform_tips_without_moving_wrist(self):
        generated, _ = self.generate()
        rows = []
        for side in ("L", "R"):
            for finger in ("f_index", "f_middle", "f_ring", "f_pinky", "thumb"):
                control = generated.pose.bones[f"{finger}.01_master.{side}"]
                tip, wrist = f"DEF-{finger}.03.{side}", f"DEF-hand.{side}"
                before = points(generated, [tip, wrist])
                original = tuple(control.scale)
                control.scale.y = 1 if INJECT_DISABLE_FINGERS else 0.65
                generated.update_tag()
                after = points(generated, [tip, wrist])
                displacement = (after[tip] - before[tip]).length
                self.assertGreater(
                    displacement, 0.005, f"{control.name} did not curl its deform tip"
                )
                self.assertLess((after[wrist] - before[wrist]).length, 1e-6)
                rows.append(
                    {
                        "control": control.name,
                        "scale_y": control.scale.y,
                        "tip_displacement_m": displacement,
                    }
                )
                control.scale = original
                generated.update_tag()
                points(generated, [tip])
        self.preserved()
        MEASUREMENTS["digits"] = rows

    def test_jaw_eye_and_eyelid_controls_have_local_responses(self):
        generated, _ = self.generate()
        rows = []
        for control_name, bone_name, field, value in (
            ("jaw_master", "DEF-jaw", "rotation_euler", (0.25, 0, 0)),
            ("eyes", "ORG-eye.L", "location", (0.025, 0, 0)),
            ("eyes", "ORG-eye.R", "location", (0.025, 0, 0)),
            ("lid.T.L.002", "DEF-lid.T.L.002", "location", (0, 0, -0.008)),
            ("lid.T.R.002", "DEF-lid.T.R.002", "location", (0, 0, -0.008)),
        ):
            control = generated.pose.bones[control_name]
            original = rigging._transform_channels(control)
            before = points(generated, [bone_name, "DEF-hand.R"])
            control.rotation_mode = "XYZ"
            setattr(control, field, value)
            generated.update_tag()
            after = points(generated, [bone_name, "DEF-hand.R"])
            movement = (after[bone_name] - before[bone_name]).length
            self.assertGreater(movement, 0.0005, control_name)
            self.assertLess((after["DEF-hand.R"] - before["DEF-hand.R"]).length, 1e-6)
            rows.append(
                {
                    "control": control_name,
                    "observed_bone": bone_name,
                    "channel": field,
                    "value": value,
                    "tail_displacement_m": movement,
                }
            )
            rigging._restore_transform_channels(control, original)
            generated.update_tag()
            points(generated, [bone_name])
        self.preserved()
        MEASUREMENTS["face"] = rows

    def test_hand_ik_moves_hand_and_finger_without_opposite_limb_motion(self):
        generated, _ = self.generate()
        rows = []
        for side, other in (("L", "R"), ("R", "L")):
            control = generated.pose.bones[f"hand_ik.{side}"]
            parent = generated.pose.bones[f"upper_arm_parent.{side}"]
            old_switch = parent["IK_FK"]
            parent["IK_FK"] = 0.0  # Stock limb constraint uses influence 1 - IK_FK.
            generated.update_tag()
            hand, tip, protected = f"DEF-hand.{side}", f"DEF-f_index.03.{side}", f"DEF-hand.{other}"
            before = points(generated, [hand, tip, protected])
            original = tuple(control.location)
            control.location.x += 0.03
            generated.update_tag()
            after = points(generated, [hand, tip, protected])
            hand_delta = (after[hand] - before[hand]).length
            tip_delta = (after[tip] - before[tip]).length
            self.assertGreater(hand_delta, 0.02)
            self.assertGreater(tip_delta, 0.02)
            self.assertLess((after[protected] - before[protected]).length, 1e-6)
            rows.append(
                {
                    "control": control.name,
                    "IK_FK": 0.0,
                    "local_x_translation": 0.03,
                    "hand_tail_displacement_m": hand_delta,
                    "finger_tip_displacement_m": tip_delta,
                }
            )
            control.location = original
            parent["IK_FK"] = old_switch
            generated.update_tag()
            points(generated, [hand])
        self.preserved()
        MEASUREMENTS["hands"] = rows

    def test_framewright_control_pose_copy_drives_full_face_and_fingers(self):
        generated, _ = self.generate()
        names = ["f_index.01_master.L", "jaw_master", "eyes"]
        observed = ["DEF-f_index.03.L", "DEF-jaw", "ORG-eye.L"]
        rest = points(generated, observed)
        with rigging.preserve_time(bpy.context, (generated,)):
            generated.pose.bones[names[0]].scale.y = 0.65
            generated.pose.bones[names[1]].rotation_mode = "XYZ"
            generated.pose.bones[names[1]].rotation_euler.x = 0.25
            generated.pose.bones[names[2]].location.x = 0.025
            generated.update_tag()
            expected = points(generated, observed)
            captured = secondary_motion.capture_pose(
                {"object_name": generated.name, "bones": names}
            )
        generated.update_tag()
        points(generated, observed)
        before = snapshot(generated)
        result = secondary_motion.apply_pose(
            {
                "object_name": generated.name,
                "pose": captured["pose"],
                "bone_map": {name: name for name in names},
                "dry_run": False,
            }
        )
        derivative = self.scene.objects[result["derivative"]]
        self.assertEqual(snapshot(generated), before)
        visible(derivative)
        actual = points(derivative, observed)
        errors = {name: (actual[name] - expected[name]).length for name in observed}
        for name in observed:
            self.assertGreater((expected[name] - rest[name]).length, 0.0005)
            self.assertLess(errors[name], 1e-5, name)
        self.preserved()
        MEASUREMENTS["pose_copy"] = {
            "control_names": names,
            "deform_tail_errors_m": errors,
            "generated_source_preserved": True,
        }

    def test_custom_finalize_script_is_refused_without_execution(self):
        hook = bpy.data.texts.new("ForbiddenFullHumanFinalize")
        hook.write("bpy.context.scene['forbidden_hook_ran'] = True\n")
        self.source.data.rigify_finalize_script = hook
        before = [{item.as_pointer() for item in store} for store in self.stores]
        source = snapshot(self.source)
        for dry_run in (True, False):
            with self.assertRaisesRegex(ValueError, "script"):
                rigging.generate_rig({"object_name": self.source.name, "dry_run": dry_run})
        self.assertNotIn("forbidden_hook_ran", self.scene)
        self.assertEqual(snapshot(self.source), source)
        self.assertEqual(before, [{item.as_pointer() for item in store} for store in self.stores])

    def test_full_template_failure_cleans_only_owned_generation_data(self):
        before = [{item.as_pointer() for item in store} for store in self.stores]

        def partial_failure(context, metarig):
            bpy.data.meshes.new("InjectedPartialWidget")
            bpy.data.texts.new("InjectedPartialUIScript")
            raise RuntimeError("injected full-template generation failure")

        with patch("rigify.generate.generate_rig", partial_failure):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                rigging.generate_rig({"object_name": self.source.name, "dry_run": False})
        self.assertEqual(before, [{item.as_pointer() for item in store} for store in self.stores])
        self.preserved()


def main():
    global INJECT_DISABLE_FINGERS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/full-human-rigify")
    parser.add_argument("--inject-disable-fingers", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        raise RuntimeError("Use isolated background Blender")
    INJECT_DISABLE_FINGERS = args.inject_disable_fingers
    suite = (
        unittest.TestSuite(
            [
                FullHumanRigifyTests(
                    "test_all_ten_digit_controls_move_deform_tips_without_moving_wrist"
                )
            ]
        )
        if INJECT_DISABLE_FINGERS
        else unittest.defaultTestLoader.loadTestsFromTestCase(FullHumanRigifyTests)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    folder = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    from rigify.metarigs import human

    report = {
        "blender": bpy.app.version_string,
        "blender_build_hash": bpy.app.build_hash.decode(),
        "template": str(Path(human.__file__).resolve()),
        "template_sha256": hashlib.sha256(Path(human.__file__).read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "tests_run": result.testsRun,
        "fixture_units": {"system": "METRIC", "scale_length": 1.0},
        "passed": result.wasSuccessful(),
        "measurements": MEASUREMENTS,
        "injected_disabled_fingers": INJECT_DISABLE_FINGERS,
        "limits": [
            "Bundled stock template only; no anatomical fit or production skin",
            "Bone/control response does not certify hand grip, facial expression or artistic quality",
            "No native game assets, UI usability, control-script cold execution or performance acceptance",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print("FRAMEWRIGHT_FULL_HUMAN_RIGIFY_REPORT " + str(folder))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
