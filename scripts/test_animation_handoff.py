"""Coupled retarget, constraint bake, skin binding and cold GLB/FBX parity tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Quaternion, Vector  # noqa: E402
from mathutils.kdtree import KDTree  # noqa: E402

from framewright import animation, interchange  # noqa: E402

START, END, FPS = 1, 25, 24
TOLERANCE = 3e-4
SOURCE_BONES = ("SourceRoot", "SourceMiddle", "SourceTip")
TARGET_BONES = ("TargetRoot", "TargetMiddle", "TargetTip")


def matrix_rows(matrix):
    return [list(row) for row in matrix]


def source_hash(objects):
    """Hash static source data plus actual action curves, not just action names."""
    records = interchange._source_record(objects)
    for obj, record in zip(objects, records, strict=True):
        record["data_name"] = obj.data.name
        record["channels"] = {
            name: list(getattr(obj, name))
            for name in (
                "location",
                "rotation_euler",
                "rotation_quaternion",
                "rotation_axis_angle",
                "scale",
                "delta_location",
                "delta_rotation_euler",
                "delta_rotation_quaternion",
                "delta_scale",
            )
        }
        record["modifier_targets"] = [
            [modifier.type, getattr(getattr(modifier, "object", None), "name", None)]
            for modifier in obj.modifiers
        ]
        record["material_values"] = {
            slot.material.name: {
                name: list(value) if name == "Base Color" else float(value)
                for name in ("Base Color", "Roughness", "Metallic")
                for value in (
                    slot.material.node_tree.nodes["Principled BSDF"].inputs[name].default_value,
                )
            }
            for slot in obj.material_slots
        }
        action = obj.animation_data.action if obj.animation_data else None
        if action:
            record["curves"] = [
                {
                    "slot": bag.slot_handle,
                    "path": curve.data_path,
                    "index": curve.array_index,
                    "points": [
                        [
                            list(key.co),
                            list(key.handle_left),
                            list(key.handle_right),
                            key.interpolation,
                        ]
                        for key in curve.keyframe_points
                    ],
                }
                for layer in action.layers
                for strip in layer.strips
                for bag in strip.channelbags
                for curve in bag.fcurves
            ]
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest()


def make_rig(name, names, points):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    previous = None
    for index, bone_name in enumerate(names):
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = points[index], points[index + 1]
        bone.parent = previous
        bone.use_connect = previous is not None
        previous = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def make_fixture():
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = START, END
    scene.render.fps, scene.render.fps_base = FPS, 1.0
    source = make_rig(
        "HandoffSource",
        SOURCE_BONES,
        [(0, 0, 0), (0, 0, 0.65), (0.15, 0, 1.25), (0.35, 0.05, 1.75)],
    )
    points = [(0, 0, 0), (0, 0, 0.9), (0.24, 0, 1.72), (0.5, 0.1, 2.38)]
    target = make_rig("HandoffTarget", TARGET_BONES, points)
    target.location = (1.4, -0.6, 0.2)
    target.rotation_euler.z = 0.15
    for frame, amount in ((1, 0), (7, 0.6), (13, -0.35), (19, 1.0), (25, 0)):
        for index, name in enumerate(SOURCE_BONES):
            bone = source.pose.bones[name]
            bone.rotation_mode = "QUATERNION"
            axis = ((0, 0, 1), (1, 0, 0), (0, 1, 0))[index]
            bone.rotation_quaternion = Quaternion(axis, amount * (0.18 + index * 0.17))
            bone.keyframe_insert("rotation_quaternion", frame=frame)
        root = source.pose.bones[SOURCE_BONES[0]]
        root.location = (amount * 0.3, 0, amount * 0.04)
        root.keyframe_insert("location", frame=frame)
    for layer in source.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"
    vertices, weights = [], []
    for ring in range(7):
        position = ring / 2
        segment = min(2, int(position))
        fraction = position - segment
        center = Vector(points[segment]).lerp(Vector(points[segment + 1]), fraction)
        width, depth = 0.18 - ring * 0.012, 0.12 + (ring % 2) * 0.015
        for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vertices.append(center + Vector((x * width, y * depth, 0)))
            if ring in (2, 4):
                joint = ring // 2
                weights.append({TARGET_BONES[joint - 1]: 0.5, TARGET_BONES[joint]: 0.5})
            else:
                weights.append({TARGET_BONES[segment]: 1.0})
    faces = [(3, 2, 1, 0), (24, 25, 26, 27)]
    faces += [
        (
            ring * 4 + side,
            ring * 4 + (side + 1) % 4,
            (ring + 1) * 4 + (side + 1) % 4,
            (ring + 1) * 4 + side,
        )
        for ring in range(6)
        for side in range(4)
    ]
    data = bpy.data.meshes.new("HandoffSkinData")
    data.from_pydata(vertices, [], faces)
    data.update()
    uv = data.uv_layers.new(name="HandoffAtlas")
    for face in data.polygons:
        origin = ((face.index % 6) / 6, (face.index // 6) / 5)
        for loop_index, offset in zip(
            face.loop_indices, ((0.01, 0.01), (0.15, 0.01), (0.15, 0.19), (0.01, 0.19)), strict=True
        ):
            uv.data[loop_index].uv = (origin[0] + offset[0], origin[1] + offset[1])
        face.material_index = face.index % 2
    for name, color in (
        ("HandoffWarm", (0.5, 0.12, 0.03, 1)),
        ("HandoffCool", (0.03, 0.18, 0.42, 1)),
    ):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
        data.materials.append(material)
    mesh = bpy.data.objects.new("HandoffSkin", data)
    scene.collection.objects.link(mesh)
    mesh.parent = target
    groups = {name: mesh.vertex_groups.new(name=name) for name in TARGET_BONES}
    for index, assignments in enumerate(weights):
        for name, weight in assignments.items():
            groups[name].add([index], weight, "REPLACE")
    mesh.modifiers.new("ExplicitSkin", "ARMATURE").object = target
    scene.frame_set(4, subframe=0.25)
    bpy.context.view_layer.update()
    return source, target, mesh


def copy_skin(mesh, rig, name):
    copy = mesh.copy()
    copy.data = mesh.data.copy()
    copy.name = name
    bpy.context.scene.collection.objects.link(copy)
    copy.parent = rig
    for modifier in copy.modifiers:
        if modifier.type == "ARMATURE":
            modifier.object = rig
    return copy


def capture(rig, mesh, normalized_times, start=START, end=END):
    scene = bpy.context.scene
    original = (scene.frame_current, scene.frame_subframe)
    samples = []
    try:
        for normalized in normalized_times:
            frame = start + normalized * (end - start)
            integer = math.floor(frame)
            scene.frame_set(integer, subframe=frame - integer)
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated_rig, evaluated_mesh = rig.evaluated_get(graph), mesh.evaluated_get(graph)
            data = evaluated_mesh.to_mesh()
            try:
                points = [list(evaluated_mesh.matrix_world @ vertex.co) for vertex in data.vertices]
                world = evaluated_rig.matrix_world
                samples.append(
                    {
                        "normalized_time": normalized,
                        "points": points,
                        "bounds": [
                            [operation(point[axis] for point in points) for axis in range(3)]
                            for operation in (min, max)
                        ],
                        "joints": {
                            name: list(world @ evaluated_rig.pose.bones[name].head)
                            for name in TARGET_BONES
                        },
                        "deform": {
                            name: matrix_rows(
                                world
                                @ evaluated_rig.pose.bones[name].matrix
                                @ rig.data.bones[name].matrix_local.inverted()
                                @ world.inverted()
                            )
                            for name in TARGET_BONES
                        },
                        "corners": [
                            [
                                points[loop.vertex_index],
                                list(data.uv_layers[0].data[loop.index].uv),
                                data.materials[face.material_index].name,
                            ]
                            for face in data.polygons
                            for loop in (data.loops[index] for index in face.loop_indices)
                        ],
                    }
                )
            finally:
                evaluated_mesh.to_mesh_clear()
    finally:
        scene.frame_set(original[0], subframe=original[1])
    return samples


def distance(first, second):
    return (Vector(first) - Vector(second)).length


def surface_distance(first, second):
    """Bidirectional vertex-cloud error, insensitive to seam duplication/order."""
    maximum = 0.0
    for source, target in ((first, second), (second, first)):
        tree = KDTree(len(target))
        for index, point in enumerate(target):
            tree.insert(Vector(point), index)
        tree.balance()
        maximum = max(maximum, max(tree.find(Vector(point))[2] for point in source))
    return maximum


def parity(actual, expected, tolerance=TOLERANCE):
    assert len(actual) == len(expected)
    maxima = {"surface_m": 0.0, "joint_m": 0.0, "bounds_m": 0.0, "deform_matrix": 0.0, "uv": 0.0}
    for sample, reference in zip(actual, expected, strict=True):
        assert abs(sample["normalized_time"] - reference["normalized_time"]) < 1e-9
        maxima["surface_m"] = max(
            maxima["surface_m"], surface_distance(sample["points"], reference["points"])
        )
        maxima["bounds_m"] = max(
            maxima["bounds_m"],
            *(distance(a, b) for a, b in zip(sample["bounds"], reference["bounds"], strict=True)),
        )
        for name in TARGET_BONES:
            maxima["joint_m"] = max(
                maxima["joint_m"], distance(sample["joints"][name], reference["joints"][name])
            )
            maxima["deform_matrix"] = max(
                maxima["deform_matrix"],
                *(
                    abs(a - b)
                    for row, other in zip(
                        sample["deform"][name], reference["deform"][name], strict=True
                    )
                    for a, b in zip(row, other, strict=True)
                ),
            )
        # Exporters triangulate and duplicate seam vertices; every UV/material
        # corner association must survive in both directions, without index equality.
        for corners, targets in (
            (sample["corners"], reference["corners"]),
            (reference["corners"], sample["corners"]),
        ):
            for point, uv, material in corners:
                candidates = [
                    other_uv
                    for other_point, other_uv, other_material in targets
                    if other_material == material and distance(point, other_point) < tolerance
                ]
                assert candidates, ("missing world/material corner", point, material)
                maxima["uv"] = max(maxima["uv"], min(distance(uv, other) for other in candidates))
    assert all(value < tolerance for value in maxima.values()), maxima
    return maxima


def cold_verify(reference_path):
    payload = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    receipt = payload["receipt"]
    if receipt["format"] == "GLB":
        bpy.ops.import_scene.gltf(filepath=receipt["output_path"])
    else:
        bpy.ops.import_scene.fbx(filepath=receipt["output_path"], use_anim=True)
    scoped = {
        obj.get("framewright_source_name"): obj
        for obj in bpy.context.scene.objects
        if obj.get("framewright_source_name")
    }
    assert set(scoped) == set(payload["scope"]), list(scoped)
    helpers = {
        bone.custom_shape
        for obj in scoped.values()
        if obj.type == "ARMATURE"
        for bone in obj.pose.bones
        if bone.custom_shape
    }
    assert len([obj for obj in bpy.context.scene.objects if obj not in helpers]) == 2
    rig, mesh = scoped[payload["rig"]], scoped[payload["mesh"]]
    assert set(rig.data.bones.keys()) == set(TARGET_BONES)
    assert rig.data.bones[TARGET_BONES[1]].parent.name == TARGET_BONES[0]
    assert rig.data.bones[TARGET_BONES[2]].parent.name == TARGET_BONES[1]
    assert mesh.parent == rig
    assert len(mesh.data.uv_layers) == 1
    mesh.data.calc_loop_triangles()
    assert len(mesh.data.loop_triangles) == 52
    assert {slot.material.name for slot in mesh.material_slots} == {"HandoffWarm", "HandoffCool"}
    for vertex in mesh.data.vertices:
        assert abs(sum(group.weight for group in vertex.groups) - 1) < 1e-5
    assert rig.animation_data and rig.animation_data.action
    start, end = rig.animation_data.action.frame_range
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    assert abs((end - start) / fps - 1.0) < 1e-5, (start, end, fps)
    actual = capture(rig, mesh, payload["times"], start, end)
    errors = parity(actual, payload["reference"])
    print(
        "FRAMEWRIGHT_ANIMATION_HANDOFF_OK "
        + json.dumps(
            {
                "format": receipt["format"],
                "samples": len(actual),
                "duration_seconds": (end - start) / fps,
                "max_errors": errors,
            }
        )
    )


class AnimationHandoffTests(unittest.TestCase):
    def test_01_retarget_bake_bind_export_full_clip_cold_parity(self):
        source, target, skin = make_fixture()
        originals = [source, target, skin]
        before = source_hash(originals)
        context_before = (
            bpy.context.scene,
            bpy.context.view_layer.objects.active,
            tuple(bpy.context.selected_objects),
            bpy.context.scene.frame_current,
            bpy.context.scene.frame_subframe,
        )
        mapped = animation.retarget_animation(
            {
                "object_name": target.name,
                "source_name": source.name,
                "bone_map": dict(zip(SOURCE_BONES, TARGET_BONES, strict=True)),
                "root_bone": SOURCE_BONES[0],
                "translation_scale": 1.3,
                "frame_start": START,
                "frame_end": END,
                "dry_run": False,
            }
        )
        retargeted = bpy.data.objects[mapped["derivative"]]
        retargeted.hide_viewport = False
        retargeted.hide_render = False
        self.assertNotEqual(
            target.data.bones[TARGET_BONES[0]].length, source.data.bones[SOURCE_BONES[0]].length
        )
        for frame in range(START, END + 1):
            bpy.context.scene.frame_set(frame)
            for source_name, target_name in zip(SOURCE_BONES, TARGET_BONES, strict=True):
                expected = source.pose.bones[source_name].matrix_basis.to_quaternion()
                actual = retargeted.pose.bones[target_name].matrix_basis.to_quaternion()
                self.assertAlmostEqual(abs(expected.dot(actual)), 1, places=5)
            self.assertLess(
                (
                    retargeted.pose.bones[TARGET_BONES[0]].location
                    - source.pose.bones[SOURCE_BONES[0]].location * 1.3
                ).length,
                1e-5,
            )
        bpy.context.scene.frame_set(context_before[3], subframe=context_before[4])
        working_skin = copy_skin(skin, retargeted, "HandoffWorkingSkin")
        integer_times = [index / 24 for index in range(25)]
        unconstrained_reference = capture(retargeted, working_skin, integer_times)
        constraint = retargeted.pose.bones[TARGET_BONES[1]].constraints.new("LIMIT_ROTATION")
        constraint.owner_space = "LOCAL"
        constraint.use_limit_x = True
        constraint.min_x, constraint.max_x = -0.15, 0.15
        constrained_reference = capture(retargeted, working_skin, integer_times)
        self.assertGreater(
            surface_distance(
                constrained_reference[18]["points"], unconstrained_reference[18]["points"]
            ),
            0.01,
        )
        baked_report = animation.bake_animation(
            {
                "object_name": retargeted.name,
                "frame_start": START,
                "frame_end": END,
                "dry_run": False,
            }
        )
        baked = bpy.data.objects[baked_report["derivative"]]
        baked.hide_viewport = False
        baked.hide_render = False
        baked_skin = copy_skin(skin, baked, "HandoffBakedSkin")
        self.assertIsNot(baked.data, target.data)
        self.assertIsNot(baked_skin.data, skin.data)
        self.assertTrue(all(not bone.constraints for bone in baked.pose.bones))
        parity(capture(baked, baked_skin, integer_times), constrained_reference)
        times = [index / 48 for index in range(49)]
        reference = capture(baked, baked_skin, times)
        self.assertGreater(surface_distance(reference[0]["points"], reference[36]["points"]), 0.1)
        with tempfile.TemporaryDirectory(prefix="framewright-animation-handoff-") as temporary:
            # A copy parented to a derivative but still bound to the source rig
            # must be rejected; silent source-rig leakage is not an acceptable fix.
            baked_skin.modifiers[0].object = target
            with self.assertRaisesRegex(ValueError, "dependency"):
                interchange.export_asset(
                    {"object_names": [baked.name, baked_skin.name], "directory": temporary}
                )
            baked_skin.modifiers[0].object = baked
            for format_name in ("GLB", "FBX"):
                with self.subTest(format=format_name):
                    receipt = interchange.export_asset(
                        {
                            "object_names": [baked.name, baked_skin.name],
                            "directory": temporary,
                            "filename": "handoff_" + format_name.lower(),
                            "format": format_name,
                            "include_animation": True,
                            "dry_run": False,
                        }
                    )
                    self.assertEqual(
                        receipt["source_fingerprint_before"], receipt["source_fingerprint_after"]
                    )
                    payload = {
                        "scope": [baked.name, baked_skin.name],
                        "rig": baked.name,
                        "mesh": baked_skin.name,
                        "receipt": receipt,
                        "times": times,
                        "reference": reference,
                    }
                    reference_path = Path(temporary) / (format_name.lower() + "_reference.json")
                    reference_path.write_text(json.dumps(payload), encoding="utf-8")
                    environment = os.environ.copy()
                    for variable in (
                        "BLENDER_USER_CONFIG",
                        "BLENDER_USER_SCRIPTS",
                        "BLENDER_USER_EXTENSIONS",
                        "BLENDER_USER_DATAFILES",
                    ):
                        directory = Path(temporary) / (format_name.lower() + "_" + variable.lower())
                        directory.mkdir()
                        environment[variable] = str(directory)
                    child = subprocess.run(
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
                            "--verify",
                            str(reference_path),
                        ],
                        cwd=temporary,
                        env=environment,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        capture_output=True,
                        timeout=120,
                    )
                    print(child.stdout)
                    if child.stderr:
                        print(child.stderr)
                    self.assertEqual(child.returncode, 0)
                    self.assertIn("FRAMEWRIGHT_ANIMATION_HANDOFF_OK", child.stdout)
        self.assertEqual(before, source_hash(originals))
        self.assertEqual(
            context_before,
            (
                bpy.context.scene,
                bpy.context.view_layer.objects.active,
                tuple(bpy.context.selected_objects),
                bpy.context.scene.frame_current,
                bpy.context.scene.frame_subframe,
            ),
        )
        print("FRAMEWRIGHT_ANIMATION_SOURCES_UNCHANGED " + before)

    def test_02_parity_oracle_rejects_interior_motion_uv_and_material_corruption(self):
        # These false-data controls prove that plausible bounds or matching clip
        # endpoints alone cannot make the full-clip parity test pass.
        source, target, skin = make_fixture()
        sample = capture(target, skin, [0.0, 0.5, 1.0])
        for field in ("motion", "uv", "material", "joint", "deform"):
            corrupted = deepcopy(sample)
            if field == "motion":
                corrupted[1]["points"][0][0] += 0.05
            elif field == "uv":
                corrupted[1]["corners"][0][1][0] += 0.1
            elif field == "material":
                corrupted[1]["corners"][0][2] = "WrongMaterial"
            elif field == "joint":
                corrupted[1]["joints"][TARGET_BONES[1]][0] += 0.05
            else:
                corrupted[1]["deform"][TARGET_BONES[1]][0][0] += 0.1
            with self.subTest(corruption=field), self.assertRaises(AssertionError):
                parity(corrupted, sample)


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run this fixture only in an isolated background Blender process")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.verify:
        cold_verify(args.verify)
    else:
        outcome = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(AnimationHandoffTests)
        )
        if not outcome.wasSuccessful():
            raise RuntimeError("Animation handoff acceptance tests failed")
