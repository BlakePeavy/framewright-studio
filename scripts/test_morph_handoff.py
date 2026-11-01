"""Coupled rig/key bake -> independent GLB/FBX morph+skin cold handoff."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from test_animation_handoff import surface_distance  # noqa: E402
from test_shape_baking import END, START, fixture, ids, source_state  # noqa: E402

from framewright import interchange, shape_baking  # noqa: E402


def capture(scene, rig, skin, start, end):
    rows = []
    for i in range(97):
        normalized = i / 96
        time = start + (end - start) * normalized
        scene.frame_set(math.floor(time), subframe=time - math.floor(time))
        graph = bpy.context.evaluated_depsgraph_get()
        obj = skin.evaluated_get(graph)
        mesh = obj.to_mesh()
        try:
            points = [list(obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
        finally:
            obj.to_mesh_clear()
        evaluated_rig = rig.evaluated_get(graph)
        keys = obj.data.shape_keys
        rows.append(
            dict(
                time=normalized,
                points=points,
                keys={k.name: k.value for k in keys.key_blocks if k.name != "Basis"}
                if keys
                else {},
                joints={
                    b.name: list(evaluated_rig.matrix_world @ b.head)
                    for b in evaluated_rig.pose.bones
                },
            )
        )
    return rows


def compare(reference, actual, tolerance):
    assert len(reference) == len(actual) == 97
    maximum = 0
    for expected, measured in zip(reference, actual, strict=True):
        assert set(expected["keys"]) == set(measured["keys"]) == {"JointBulge", "SecondaryPulse"}, (
            measured["keys"]
        )
        maximum = max(maximum, surface_distance(expected["points"], measured["points"]))
        assert set(expected["joints"]) == set(measured["joints"])
        for name, point in expected["joints"].items():
            error = math.dist(point, measured["joints"][name])
            assert error < tolerance, (name, error, tolerance)
    assert maximum < tolerance, (maximum, tolerance)
    return maximum


def cold(blend_path, payload_path, format_name):
    payload = json.loads(payload_path.read_text())
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.render.fps = 24
    importer = bpy.ops.import_scene.gltf if format_name == "GLB" else bpy.ops.import_scene.fbx
    assert importer(filepath=str(blend_path)) == {"FINISHED"}
    rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    helpers = {bone.custom_shape for rig in rigs for bone in rig.pose.bones if bone.custom_shape}
    skins = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in helpers]
    assert len(rigs) == len(skins) == 1, [(o.name, o.type) for o in bpy.context.scene.objects]
    rig, skin = rigs[0], skins[0]
    assert skin.data.shape_keys, f"{format_name} dropped morph targets"
    keys = skin.data.shape_keys
    assert keys.animation_data and keys.animation_data.action, (
        format_name,
        "dropped morph curves",
        [
            (
                o.name,
                o.type,
                list(o.keys()),
                o.animation_data.action.name
                if o.animation_data and o.animation_data.action
                else None,
            )
            for o in bpy.context.scene.objects
        ],
        [(a.name, [(s.identifier, s.target_id_type) for s in a.slots]) for a in bpy.data.actions],
        [(c.data_path, c.driver.expression) for c in keys.animation_data.drivers]
        if keys.animation_data
        else None,
    )
    assert not keys.animation_data.drivers
    ancestors = []
    ancestor = skin.parent
    while ancestor:
        ancestors.append(ancestor)
        ancestor = ancestor.parent
    assert rig in ancestors
    # glTF may preserve a morph-animated mesh transform using an explicit Empty
    # parent plus mesh child. Only that owned ancestry and importer bone widgets
    # may accompany the one requested skin and rig.
    scoped = {
        o.get("framewright_source_name"): o
        for o in bpy.context.scene.objects
        if o.get("framewright_source_name")
    }
    assert set(scoped) == set(payload["scope"])
    assert set(bpy.context.scene.objects) == set(ancestors) | {skin} | helpers | set(
        scoped.values()
    )
    assert next(m.object for m in skin.modifiers if m.type == "ARMATURE") == rig
    actions = [rig.animation_data.action, keys.animation_data.action]
    starts = [float(a.frame_range[0]) for a in actions]
    ends = [float(a.frame_range[1]) for a in actions]
    assert max(starts) - min(starts) < 1e-4 and max(ends) - min(ends) < 1e-4, (starts, ends)
    imported_fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    assert abs((max(ends) - min(starts)) / imported_fps - 2) < 1e-5
    actual = capture(bpy.context.scene, rig, skin, min(starts), max(ends))
    error = compare(payload["reference"], actual, 3e-5)
    value_error = max(
        abs(row["keys"][name] - expect["keys"][name])
        for row, expect in zip(actual, payload["reference"], strict=True)
        for name in row["keys"]
    )
    assert value_error < 3e-5, value_error
    # An offset morph action must not be accepted merely because its endpoints
    # and the independently animated skeleton still look plausible.
    old_action = keys.animation_data.action
    slot = keys.animation_data.action_slot.identifier
    shifted = old_action.copy()
    keys.animation_data.action = shifted
    keys.animation_data.action_slot = next(s for s in shifted.slots if s.identifier == slot)
    slot_handle = keys.animation_data.action_slot.handle
    for layer in shifted.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                if bag.slot_handle == slot_handle:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.co.x += imported_fps / 24
    try:
        compare(
            payload["reference"],
            capture(bpy.context.scene, rig, skin, min(starts), max(ends)),
            3e-5,
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("Offset morph animation was not detected")
    # Missing morph animation must fail while the skeleton still animates.
    keys.animation_data_clear()
    for key in keys.key_blocks:
        if key.name != "Basis":
            key.value = 0
    broken = capture(bpy.context.scene, rig, skin, min(starts), max(ends))
    try:
        compare(payload["reference"], broken, 3e-5)
    except AssertionError:
        pass
    else:
        raise AssertionError("Missing-morph negative control was not detected")
    print(
        "MORPH_COLD_PASS",
        json.dumps(
            dict(
                format=format_name,
                samples=97,
                max_surface_error=error,
                max_key_error=value_error,
                missing_morph_rejected=True,
                offset_morph_rejected=True,
            )
        ),
    )


class MorphHandoffTests(unittest.TestCase):
    def test_coupled_driver_bake_and_both_cold_formats(self):
        before_ids = ids()
        old_scene = bpy.context.window.scene
        scene = bpy.data.scenes.new("MorphHandoff")
        bpy.context.window.scene = scene
        try:
            rig, source, baked = fixture()
            before = source_state(rig, source, baked)
            report = shape_baking.bake_shape_keys(
                dict(
                    object_name=source.name,
                    armature_name=rig.name,
                    baked_armature_name=baked.name,
                    shape_keys=["JointBulge", "SecondaryPulse"],
                    frame_start=START,
                    frame_end=END,
                    max_samples=128,
                    max_interpolation_error=0.003,
                    dry_run=False,
                )
            )
            skin = bpy.data.objects[report["derivative"]]
            with shape_baking._sampling_scene(bpy.context, source, rig, baked) as (
                owned,
                original_copy,
                rig_copy,
                _target,
            ):
                original = capture(owned, rig_copy, original_copy, START, END)
            with interchange._staging([baked, skin], bpy.context, True) as (owned, copies):
                with bpy.context.temp_override(scene=owned, view_layer=owned.view_layers[0]):
                    reference = capture(owned, copies[baked], copies[skin], START, END)
            source_error = compare(original, reference, 0.0005)
            self.assertEqual(before, source_state(rig, source, baked))
            with tempfile.TemporaryDirectory(prefix="fw-morph-handoff-") as temporary:
                folder = Path(temporary)
                with self.assertRaisesRegex(ValueError, "drivers"):
                    interchange.export_asset(
                        dict(
                            object_names=[rig.name, source.name],
                            directory=temporary,
                            include_animation=True,
                            dry_run=False,
                        )
                    )
                for format_name in ("GLB", "FBX"):
                    with self.subTest(format=format_name):
                        receipt = interchange.export_asset(
                            dict(
                                object_names=[baked.name, skin.name],
                                directory=temporary,
                                filename="morph_" + format_name.lower(),
                                format=format_name,
                                include_animation=True,
                                dry_run=False,
                            )
                        )
                        payload = folder / (format_name + ".json")
                        payload.write_text(
                            json.dumps(dict(reference=reference, scope=[baked.name, skin.name]))
                        )
                        command = [
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
                            receipt["output_path"],
                            str(payload),
                            format_name,
                        ]
                        result = subprocess.run(
                            command, capture_output=True, text=True, timeout=90, check=False
                        )
                        self.assertEqual(
                            result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:]
                        )
                        print(result.stdout)
                self.assertEqual(before, source_state(rig, source, baked))
                skin.modifiers.new("MorphDestroyingSubdivision", "SUBSURF")
                for format_name in ("GLB", "FBX"):
                    with self.assertRaisesRegex(ValueError, "morph|shape"):
                        interchange.export_asset(
                            dict(
                                object_names=[baked.name, skin.name],
                                directory=temporary,
                                filename="invalid_" + format_name.lower(),
                                format=format_name,
                                include_animation=True,
                                dry_run=False,
                            )
                        )
            print("MORPH_SOURCE_COMPARE", source_error)
        finally:
            bpy.context.window.scene = old_scene
            for name in ("objects", "meshes", "armatures", "actions", "scenes"):
                store = getattr(bpy.data, name)
                for item in set(store) - before_ids[name]:
                    store.remove(item, do_unlink=True)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if args and args[0] == "--cold":
        cold(Path(args[1]), Path(args[2]), args[3])
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(MorphHandoffTests)
        )
        if not result.wasSuccessful():
            raise SystemExit(1)
