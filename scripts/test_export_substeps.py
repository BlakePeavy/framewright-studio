"""Explicit export sampling rate: owned timebase, failure isolation and cold morph/skin."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_morph_handoff import capture  # noqa: E402
from test_shape_baking import fixture, ids, source_state  # noqa: E402

from framewright import interchange, shape_baking  # noqa: E402


def snapshot(objects):
    rows = []
    for obj in objects:
        for data in (obj, obj.data, getattr(obj.data, "shape_keys", None)):
            animation = getattr(data, "animation_data", None)
            if animation and animation.action:
                action = animation.action
                rows.append(
                    (
                        data.as_pointer(),
                        action.as_pointer(),
                        animation.action_slot.identifier,
                        [
                            (
                                c.data_path,
                                c.array_index,
                                [
                                    (
                                        tuple(k.co),
                                        tuple(k.handle_left),
                                        tuple(k.handle_right),
                                        k.interpolation,
                                    )
                                    for k in c.keyframe_points
                                ],
                            )
                            for layer in action.layers
                            for strip in layer.strips
                            for bag in strip.channelbags
                            for c in bag.fcurves
                        ],
                    )
                )
    return rows


class ExportSubstepsTests(unittest.TestCase):
    def setUp(self):
        self.old = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("ExportSubstepsFixture")
        bpy.context.window.scene = self.scene
        self.before = ids()
        self.source_rig, self.source_skin, self.rig = fixture()
        receipt = shape_baking.bake_shape_keys(
            dict(
                object_name=self.source_skin.name,
                armature_name=self.source_rig.name,
                baked_armature_name=self.rig.name,
                shape_keys=["JointBulge", "SecondaryPulse"],
                frame_start=1,
                frame_end=49,
                max_interpolation_error=0.003,
                dry_run=False,
            )
        )
        self.skin = bpy.data.objects[receipt["derivative"]]
        self.objects = [self.rig, self.skin]
        self.temporary = tempfile.TemporaryDirectory(prefix="fw-export-substeps-")
        self.params = dict(
            object_names=[o.name for o in self.objects],
            directory=self.temporary.name,
            filename="substeps",
            include_animation=True,
            animation_substeps=4,
            dry_run=False,
        )

    def tearDown(self):
        bpy.context.window.scene = self.old
        for name in ("objects", "meshes", "armatures", "actions", "scenes"):
            store = getattr(bpy.data, name)
            for value in set(store) - self.before[name]:
                store.remove(value, do_unlink=True)
        bpy.data.scenes.remove(self.scene)
        self.temporary.cleanup()

    def test_owned_actions_keys_handles_and_scene_timebase_scale_together(self):
        before, allocation = snapshot(self.objects), ids()
        scene_state = (
            self.scene.frame_current,
            self.scene.frame_subframe,
            self.scene.render.fps,
            self.scene.render.fps_base,
        )
        with interchange._staging(self.objects, bpy.context, True, animation_substeps=4) as (
            scene,
            copies,
        ):
            self.assertEqual(scene.render.fps, scene_state[2] * 4)
            self.assertEqual(scene.render.fps_base, scene_state[3])
            self.assertEqual((scene.frame_start, scene.frame_end), (4, 196))
            self.assertAlmostEqual(
                scene.frame_current + scene.frame_subframe, (scene_state[0] + scene_state[1]) * 4
            )
            after = snapshot(list(copies.values()))
            self.assertEqual(len(before), len(after))
            for old, new in zip(before, after, strict=True):
                self.assertNotEqual(old[1], new[1])
                self.assertEqual(old[2], new[2])
                for curve, copied in zip(old[3], new[3], strict=True):
                    self.assertEqual(curve[:2], copied[:2])
                    for key, copied_key in zip(curve[2], copied[2], strict=True):
                        for index in (0, 1, 2):
                            self.assertAlmostEqual(
                                copied_key[index][0], key[index][0] * 4, places=5
                            )
                            self.assertEqual(copied_key[index][1], key[index][1])
        self.assertEqual(snapshot(self.objects), before)
        self.assertEqual(ids(), allocation)
        self.assertEqual(
            (
                self.scene.frame_current,
                self.scene.frame_subframe,
                self.scene.render.fps,
                self.scene.render.fps_base,
            ),
            scene_state,
        )

    def test_failure_after_owned_action_copy_cleans_without_source_changes(self):
        before, allocation = snapshot(self.objects), ids()
        scale = interchange._scale_owned_action

        def fail(*args):
            scale(*args)
            raise RuntimeError("injected retiming failure")

        with (
            patch.object(interchange, "_scale_owned_action", side_effect=fail),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            interchange.export_asset(self.params)
        self.assertEqual(snapshot(self.objects), before)
        self.assertEqual(ids(), allocation)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_sampling_budget_timing_limits_and_unsupported_curves_reject_early(self):
        allocation = ids()
        for change in (
            dict(include_animation=False),
            dict(max_animation_samples=100),
            dict(animation_substeps=True),
            dict(animation_substeps=65),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                interchange.export_asset({**self.params, **change})
        curve = self.rig.animation_data.action.layers[0].strips[0].channelbags[0].fcurves[0]
        modifier = curve.modifiers.new("CYCLES")
        with self.assertRaisesRegex(ValueError, "modifier"):
            interchange.export_asset(self.params)
        curve.modifiers.remove(modifier)
        track = self.rig.animation_data.nla_tracks.new()
        with self.assertRaisesRegex(ValueError, "NLA"):
            interchange.export_asset(self.params)
        self.rig.animation_data.nla_tracks.remove(track)
        self.scene.render.fps = 1000
        with self.assertRaisesRegex(ValueError, "FPS|fps"):
            interchange.export_asset(
                {**self.params, "animation_substeps": 64, "max_animation_samples": 65536}
            )
        self.scene.render.fps = 24
        self.scene.frame_start, self.scene.frame_end = 500000, 500002
        with self.assertRaisesRegex(ValueError, "frame"):
            interchange.export_asset(self.params)
        self.assertEqual(ids(), allocation)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_global_callbacks_are_refused_before_any_export_side_effect(self):
        calls = []
        allocation = ids()

        def callback(*args):
            calls.append(True)

        for name in (
            "frame_change_pre",
            "frame_change_post",
            "depsgraph_update_pre",
            "depsgraph_update_post",
        ):
            handlers = getattr(bpy.app.handlers, name)
            handlers.append(callback)
            try:
                for substeps in (1, 4):
                    with self.assertRaisesRegex(ValueError, "handler"):
                        interchange.export_asset({**self.params, "animation_substeps": substeps})
            finally:
                handlers.remove(callback)
        self.assertEqual(calls, [])
        self.assertEqual(ids(), allocation)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_coupled_morph_and_skin_survive_both_cold_formats_at_substeps(self):
        before = source_state(self.source_rig, self.source_skin, self.rig)
        actions = snapshot(self.objects)
        with (
            interchange._staging(self.objects, bpy.context, True) as (scene, copies),
            bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]),
        ):
            reference = capture(scene, copies[self.rig], copies[self.skin], 1, 49)
        folder = Path(self.temporary.name)
        payload = folder / "reference.json"
        payload.write_text(
            json.dumps(dict(reference=reference, scope=[o.name for o in self.objects]))
        )
        for format_name in ("GLB", "FBX"):
            with self.subTest(format=format_name):
                receipt = interchange.export_asset(
                    {**self.params, "format": format_name, "filename": format_name.lower()}
                )
                self.assertEqual(receipt["animation_sampling"]["substeps"], 4)
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
                        str(ROOT / "scripts/test_morph_handoff.py"),
                        "--",
                        "--cold",
                        receipt["output_path"],
                        str(payload),
                        format_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                print(result.stdout)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(source_state(self.source_rig, self.source_skin, self.rig), before)
        self.assertEqual(snapshot(self.objects), actions)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportSubstepsTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
