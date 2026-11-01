"""Actual B-Bone endpoint bake, preservation, budget and dependency regressions."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402
from test_animation_handoff import surface_distance  # noqa: E402
from test_shape_baking import ids  # noqa: E402

from framewright import bbone_baking, interchange  # noqa: E402
from framewright.api import dispatch  # noqa: E402


def curves(action):
    return [
        c
        for layer in action.layers
        for strip in layer.strips
        for bag in strip.channelbags
        for c in bag.fcurves
    ]


def fixture():
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    data = bpy.data.armatures.new("BendySourceData")
    rig = bpy.data.objects.new("BendySource", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("Bendy")
    bone.head, bone.tail = (0, 0, 0), (0, 2, 0)
    rigid = data.edit_bones.new("Rigid")
    rigid.head, rigid.tail = (0, 0, 0), (0, 0.2, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    bone = data.bones["Bendy"]
    bone.bbone_segments = 10
    bone.bbone_mapping_mode = "CURVED"
    bone.bbone_curveinx = 0.2
    bone.bbone_curveoutz = -0.15
    rig.location, rig.rotation_euler = (0.3, -0.2, 0.5), (0.1, 0.2, 0.3)
    rig.scale = (1.2, 1.2, 1.2)
    pose = rig.pose.bones["Bendy"]
    pose.rotation_mode = "XYZ"
    for frame, strength in ((1, 0.0), (5, 1.0), (9, -0.7), (13, 0.8), (17, 0.0)):
        pose.bbone_curveinx = 0.75 * strength
        pose.bbone_curveoutz = -0.55 * strength
        pose.bbone_rollout = 0.8 * strength
        pose.bbone_scaleout = (1 + 0.2 * strength, 1.0, 1 - 0.1 * strength)
        pose.rotation_euler.z = 0.18 * strength
        for path in (
            "bbone_curveinx",
            "bbone_curveoutz",
            "bbone_rollout",
            "bbone_scaleout",
            "rotation_euler",
        ):
            pose.keyframe_insert(path, frame=frame)
    for curve in curves(rig.animation_data.action):
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"
    coords = [
        (0.12 * math.cos(a * math.tau / 8), y / 8, 0.12 * math.sin(a * math.tau / 8))
        for y in range(17)
        for a in range(8)
    ]
    faces = [
        (r * 8 + a, r * 8 + (a + 1) % 8, (r + 1) * 8 + (a + 1) % 8, (r + 1) * 8 + a)
        for r in range(16)
        for a in range(8)
    ]
    mesh = bpy.data.meshes.new("BendySourceSkinData")
    mesh.from_pydata(coords, [], faces)
    skin = bpy.data.objects.new("BendySourceSkin", mesh)
    bpy.context.scene.collection.objects.link(skin)
    skin.parent = rig
    skin.modifiers.new("BendyDeform", "ARMATURE").object = rig
    for name in ("Bendy", "Rigid", "ProtectedMask"):
        skin.vertex_groups.new(name=name)
    for vertex in mesh.vertices:
        weight = 0.8 + 0.1 * math.sin(vertex.co.y)
        # Original deform totals intentionally differ from one.
        skin.vertex_groups["Bendy"].add([vertex.index], 0.6 * weight, "REPLACE")
        skin.vertex_groups["Rigid"].add([vertex.index], 0.6 * (1 - weight), "REPLACE")
        skin.vertex_groups["ProtectedMask"].add([vertex.index], 0.123, "REPLACE")
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 17
    bpy.context.scene.frame_set(7, subframe=0.25)
    return rig, skin


def state(rig, skin):
    return {
        "time": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
        "fps": (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base),
        "objects": [
            (
                o.name,
                o.data.as_pointer(),
                o.parent.as_pointer() if o.parent else 0,
                list(o.location),
                list(o.rotation_euler),
                list(o.scale),
                [list(row) for row in o.matrix_world],
                o.hide_viewport,
                o.hide_render,
            )
            for o in (rig, skin)
        ],
        "bones": [
            (b.name, b.bbone_segments, [list(row) for row in b.matrix_local])
            for b in rig.data.bones
        ],
        "pose": [
            (
                p.name,
                list(p.location),
                list(p.rotation_euler),
                list(p.scale),
                p.bbone_curveinx,
                p.bbone_curveoutz,
                p.bbone_rollout,
                list(p.bbone_scaleout),
            )
            for p in rig.pose.bones
        ],
        "geometry": [
            (list(v.co), [(g.group, g.weight) for g in v.groups]) for v in skin.data.vertices
        ],
        "action": [
            (
                c.data_path,
                c.array_index,
                [
                    (list(k.co), list(k.handle_left), list(k.handle_right), k.interpolation)
                    for k in c.keyframe_points
                ],
            )
            for c in curves(rig.animation_data.action)
        ],
        "selection": [(o.name, o.select_get()) for o in (rig, skin)],
        "active": bpy.context.view_layer.objects.active.name
        if bpy.context.view_layer.objects.active
        else None,
    }


def points(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [list(evaluated.matrix_world @ v.co) for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def cold_handoff(path, payload_path, format_name):
    payload = json.loads(Path(payload_path).read_text())
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.render.fps = 24
    operator = bpy.ops.import_scene.gltf if format_name == "GLB" else bpy.ops.import_scene.fbx
    assert operator(filepath=path) == {"FINISHED"}
    rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    assert len(rigs) == 1
    rig = rigs[0]
    widgets = {b.custom_shape for b in rig.pose.bones if b.custom_shape}
    skins = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in widgets]
    assert len(skins) == 1
    assert set(rig.data.bones) and rig.animation_data and rig.animation_data.action
    assert set(rig.data.bones.keys()) == set(payload["bones"])
    start, end = rig.animation_data.action.frame_range
    imported_fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    assert abs((end - start) / imported_fps - 16 / 24) < 1e-5
    maximum = 0.0
    for index, expected in enumerate(payload["points"]):
        time = start + (end - start) * index / (len(payload["points"]) - 1)
        bpy.context.scene.frame_set(math.floor(time), subframe=time % 1)
        maximum = max(maximum, surface_distance(expected, points(skins[0])))
    print("BBONE_COLD_ERROR", format_name, maximum)
    assert maximum <= 0.0005, (format_name, "cold output differs from the baked reference", maximum)
    skin = skins[0]
    name = next(
        name
        for name in rig.data.bones.keys()
        if name in skin.vertex_groups
        and any(
            skin.vertex_groups[name].index == group.group and group.weight > 0
            for vertex in skin.data.vertices
            for group in vertex.groups
        )
    )
    group = skin.vertex_groups[name]
    weights = [
        (vertex.index, membership.weight)
        for vertex in skin.data.vertices
        for membership in vertex.groups
        if membership.group == group.index
    ]
    skin.vertex_groups.remove(group)
    broken = []
    for index, expected in enumerate(payload["points"]):
        time = start + (end - start) * index / (len(payload["points"]) - 1)
        bpy.context.scene.frame_set(math.floor(time), subframe=time % 1)
        broken.append(surface_distance(expected, points(skin)))
    assert max(broken) > 0.001, "Missing endpoint influence was not detected"
    group = skin.vertex_groups.new(name=name)
    for index, weight in weights:
        group.add([index], weight, "REPLACE")
    for curve in curves(rig.animation_data.action):
        for key in curve.keyframe_points:
            key.co.x += imported_fps / 24
    offset = []
    for index, expected in enumerate(payload["points"]):
        time = start + (end - start) * index / (len(payload["points"]) - 1)
        bpy.context.scene.frame_set(math.floor(time), subframe=time % 1)
        offset.append(surface_distance(expected, points(skin)))
    assert max(offset) > 0.001, "Offset endpoint action was not detected"
    print("BBONE_NEGATIVE_CONTROLS", format_name, "missing", max(broken), "offset", max(offset))


def run_cold(path, payload, format_name):
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
            str(path),
            str(payload),
            format_name,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr


class BendyBakeTests(unittest.TestCase):
    def setUp(self):
        self.old = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("BendyBakeFixture")
        bpy.context.window.scene = self.scene
        self.before = ids()
        self.rig, self.skin = fixture()
        self.params = dict(
            object_name=self.skin.name,
            armature_name=self.rig.name,
            frame_start=1,
            frame_end=17,
            max_surface_error_m=0.0005,
        )

    def tearDown(self):
        bpy.context.window.scene = self.old
        for name in ("objects", "meshes", "armatures", "actions", "scenes"):
            store = getattr(bpy.data, name)
            for data in set(store) - self.before[name]:
                store.remove(data, do_unlink=True)
        bpy.data.scenes.remove(self.scene)

    def test_preview_full_adaptive_interval_exact_source_and_no_retained_ids(self):
        before, allocation = state(self.rig, self.skin), ids()
        envelope = dispatch(
            dict(
                schema_version="1.0",
                request_id="endpoint-preview",
                command="animation.bake_bbone_skin",
                params=self.params,
            )
        )
        self.assertTrue(envelope["ok"], envelope)
        result = envelope["result"]
        self.assertTrue(result["dry_run"])
        self.assertLessEqual(result["maximum_surface_error_m"], 0.0005)
        self.assertGreater(len(result["key_times"]), 17)
        self.assertGreater(len(result["validation_times"]), len(result["key_times"]))
        self.assertEqual(result["joint_count"], 12)
        self.assertEqual(result["key_times"][0], 1)
        self.assertEqual(result["key_times"][-1], 17)
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertEqual(ids(), allocation)

    def test_apply_retains_hidden_independent_skin_and_action_and_mask(self):
        before = state(self.rig, self.skin)
        result = bbone_baking.bake_bbone_skin({**self.params, "dry_run": False})
        skin, rig = (bpy.data.objects[result[k]] for k in ("derivative", "armature_derivative"))
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertIs(skin.parent, rig)
        self.assertIs(skin.modifiers[0].object, rig)
        self.assertNotEqual(skin.data, self.skin.data)
        self.assertNotEqual(rig.animation_data.action, self.rig.animation_data.action)
        self.assertTrue(all(b.bbone_segments == 1 for b in rig.data.bones))
        self.assertTrue(
            rig.hide_viewport and skin.hide_viewport and rig.hide_render and skin.hide_render
        )
        for vertex in skin.data.vertices:
            self.assertEqual(
                skin.vertex_groups["ProtectedMask"].weight(vertex.index),
                self.skin.vertex_groups["ProtectedMask"].weight(vertex.index),
            )
            total = sum(
                g.weight
                for g in vertex.groups
                if skin.vertex_groups[g.group].name in rig.data.bones
            )
            self.assertAlmostEqual(total, 1, places=6)

    def test_apply_preserves_polygon_material_indices_and_object_slot_overrides(self):
        materials = [bpy.data.materials.new("EndpointMaterial" + str(i)) for i in range(3)]
        try:
            self.skin.data.materials.append(materials[0])
            self.skin.data.materials.append(materials[1])
            self.skin.material_slots[0].link = "OBJECT"
            self.skin.material_slots[0].material = materials[2]
            for polygon in self.skin.data.polygons:
                polygon.material_index = polygon.index % 2
            indices = [p.material_index for p in self.skin.data.polygons]
            source_slots = [(s.link, s.material) for s in self.skin.material_slots]
            data_slots = list(self.skin.data.materials)
            result = bbone_baking.bake_bbone_skin({**self.params, "frame_end": 1, "dry_run": False})
            derivative = bpy.data.objects[result["derivative"]]
            self.assertEqual([p.material_index for p in derivative.data.polygons], indices)
            self.assertEqual(
                [(s.link, s.material) for s in derivative.material_slots], source_slots
            )
            self.assertEqual(list(derivative.data.materials), data_slots)
            self.assertEqual([p.material_index for p in self.skin.data.polygons], indices)
            self.assertEqual([(s.link, s.material) for s in self.skin.material_slots], source_slots)
            self.assertEqual(list(self.skin.data.materials), data_slots)
        finally:
            for material in materials:
                bpy.data.materials.remove(material, do_unlink=True)

    def test_both_cold_formats_separate_bake_error_from_handoff_error(self):
        before = state(self.rig, self.skin)
        result = bbone_baking.bake_bbone_skin({**self.params, "dry_run": False})
        rig, skin = (bpy.data.objects[result[k]] for k in ("armature_derivative", "derivative"))
        expected, original = [], []
        with (
            interchange._staging([self.rig, self.skin, rig, skin], bpy.context, True) as (
                scene,
                copies,
            ),
            bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]),
        ):
            for index in range(129):
                time = 1 + index / 8
                scene.frame_set(math.floor(time), subframe=time % 1)
                expected.append(points(copies[skin]))
                original.append(points(copies[self.skin]))
        source_error = max(surface_distance(a, b) for a, b in zip(expected, original, strict=True))
        self.assertLessEqual(source_error, 0.0005)
        print("BBONE_SOURCE_TO_BAKE", source_error)
        with tempfile.TemporaryDirectory(prefix="fw-bbone-cold-") as temporary:
            folder = Path(temporary)
            payload = folder / "expected.json"
            payload.write_text(
                json.dumps({"points": expected, "bones": list(rig.data.bones.keys())})
            )
            for format_name in ("GLB", "FBX"):
                with self.subTest(format=format_name):
                    filename = "endpoint_" + format_name.lower()
                    path = folder / (filename + "." + format_name.lower())
                    interchange.export_asset(
                        dict(
                            object_names=[rig.name, skin.name],
                            directory=str(folder),
                            filename=filename,
                            format=format_name,
                            include_animation=True,
                            animation_substeps=4,
                            dry_run=False,
                        )
                    )
                    run_cold(path, payload, format_name)
        self.assertEqual(before, state(self.rig, self.skin))

    def test_transformed_bind_and_scene_unit_scale(self):
        self.skin.matrix_parent_inverse = Matrix.Translation((0.03, -0.02, 0.01))
        self.skin.location = (0.03, 0.02, 0.01)
        self.skin.rotation_euler = (0.03, 0.02, 0.01)
        self.skin.scale = (0.9, 1.1, 0.95)
        self.scene.unit_settings.scale_length = 0.01
        self.scene.view_layers[0].update()
        before = state(self.rig, self.skin)
        result = bbone_baking.bake_bbone_skin({**self.params, "max_surface_error_m": 0.000005})
        self.assertLessEqual(result["maximum_surface_error_m"], 0.000005)
        self.assertEqual(result["unit_scale_m"], self.scene.unit_settings.scale_length)
        self.assertEqual(state(self.rig, self.skin), before)

    def test_unparented_source_retains_world_binding_on_parented_export_derivative(self):
        world = self.skin.matrix_world.copy()
        self.skin.parent = None
        self.skin.matrix_world = world
        self.scene.view_layers[0].update()
        before = state(self.rig, self.skin)
        result = bbone_baking.bake_bbone_skin({**self.params, "dry_run": False})
        skin, rig = (bpy.data.objects[result[k]] for k in ("derivative", "armature_derivative"))
        self.assertIs(skin.parent, rig)
        self.assertIsNone(self.skin.parent)
        self.assertEqual(state(self.rig, self.skin), before)
        self.assertLessEqual(result["maximum_surface_error_m"], self.params["max_surface_error_m"])

    def test_dependency_and_deformation_rejections_before_retained_allocation(self):
        before = ids()
        self.skin.modifiers[0].use_deform_preserve_volume = True
        with self.assertRaisesRegex(ValueError, "linear|DQ"):
            bbone_baking.bake_bbone_skin(self.params)
        self.skin.modifiers[0].use_deform_preserve_volume = False
        self.skin.shape_key_add(name="Basis")
        self.skin.shape_key_add(name="Authored")
        with self.assertRaisesRegex(ValueError, "shape"):
            bbone_baking.bake_bbone_skin(self.params)
        self.skin.shape_key_clear()
        self.assertEqual(ids(), before)

    def test_raw_segmented_skin_is_refused_by_both_exporters(self):
        allocation = ids()
        with tempfile.TemporaryDirectory(prefix="fw-raw-bbone-refusal-") as directory:
            for format_name in ("GLB", "FBX"):
                for animated in (False, True):
                    with (
                        self.subTest(format=format_name, animated=animated),
                        self.assertRaisesRegex(ValueError, "segment|B-Bone"),
                    ):
                        interchange.export_asset(
                            dict(
                                object_names=[self.rig.name, self.skin.name],
                                directory=directory,
                                format=format_name,
                                include_animation=animated,
                                dry_run=False,
                            )
                        )
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(ids(), allocation)

    def test_budget_and_failure_rollback(self):
        before, allocation = state(self.rig, self.skin), ids()
        for change in (
            dict(max_key_times=17),
            dict(max_samples=17),
            dict(max_vertex_samples=1),
            dict(max_joints=1),
            dict(max_influences=1),
            dict(max_refinement_depth=0),
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "budget|limit|tolerance"),
            ):
                bbone_baking.bake_bbone_skin({**self.params, **change, "dry_run": False})
            self.assertEqual(ids(), allocation)
            self.assertEqual(state(self.rig, self.skin), before)

    def test_handlers_and_dirty_source_values_are_not_evaluated(self):
        light = bpy.data.lights.new("BendyUnrelated", "POINT")
        light_object = bpy.data.objects.new("BendyUnrelated", light)
        self.scene.collection.objects.link(light_object)
        light.energy = 1
        light.keyframe_insert("energy", frame=1)
        light.energy = 100
        light.keyframe_insert("energy", frame=17)
        light.energy = 12.345
        self.rig.pose.bones["Bendy"].bbone_curveinx = 0.23456
        before = state(self.rig, self.skin)
        value = light.energy
        calls = []

        def callback(*args):
            calls.append(True)
            light.energy = 55

        try:
            for name in (
                "frame_change_pre",
                "frame_change_post",
                "depsgraph_update_pre",
                "depsgraph_update_post",
            ):
                handlers = getattr(bpy.app.handlers, name)
                handlers.append(callback)
                try:
                    with self.assertRaisesRegex(ValueError, "handler"):
                        bbone_baking.bake_bbone_skin(self.params)
                finally:
                    handlers.remove(callback)
            self.assertEqual(calls, [])
            bbone_baking.bake_bbone_skin(self.params)
            self.assertEqual(state(self.rig, self.skin), before)
            self.assertEqual(light.energy, value)
        finally:
            bpy.data.objects.remove(light_object, do_unlink=True)
            bpy.data.lights.remove(light)

    def test_partial_action_failure_rolls_back_all_owned_data(self):
        before, allocation = state(self.rig, self.skin), ids()
        write = bbone_baking._write_action

        def fail_after_action(*args):
            write(*args)
            raise RuntimeError("injected after action creation")

        with (
            patch.object(bbone_baking, "_write_action", side_effect=fail_after_action),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            bbone_baking.bake_bbone_skin({**self.params, "dry_run": False})
        self.assertEqual(ids(), allocation)
        self.assertEqual(state(self.rig, self.skin), before)

    def test_shared_action_keeps_inactive_foreign_slot_outside_rig_scope(self):
        foreign = bpy.data.objects.new("ForeignSlotOwner", None)
        self.scene.collection.objects.link(foreign)
        action = self.rig.animation_data.action
        slot = action.slots.new("OBJECT", foreign.name)
        foreign.animation_data_create()
        foreign.animation_data.action = action
        foreign.animation_data.action_slot = slot
        foreign.location.x = 0.3
        foreign.keyframe_insert("location", frame=1)
        foreign.location.x = 0.7
        foreign.keyframe_insert("location", frame=17)
        foreign.location.x = 0.456
        before, allocation = state(self.rig, self.skin), ids()
        bbone_baking.bake_bbone_skin(self.params)
        self.assertEqual(foreign.location.x, 0.4560000002384186)
        self.assertEqual(ids(), allocation)
        self.assertEqual(state(self.rig, self.skin), before)

    def test_external_dependencies_shared_source_data_and_shear(self):
        sibling = self.skin.copy()
        self.scene.collection.objects.link(sibling)
        before = state(self.rig, self.skin)
        pointer, coordinates = (
            sibling.data.as_pointer(),
            [tuple(v.co) for v in sibling.data.vertices],
        )
        bbone_baking.bake_bbone_skin(self.params)
        self.assertEqual(sibling.data.as_pointer(), pointer)
        self.assertEqual([tuple(v.co) for v in sibling.data.vertices], coordinates)
        self.assertEqual(state(self.rig, self.skin), before)
        constraint = self.rig.pose.bones["Bendy"].constraints.new("COPY_LOCATION")
        constraint.target = sibling
        with self.assertRaisesRegex(ValueError, "internal"):
            bbone_baking.bake_bbone_skin(self.params)
        self.rig.pose.bones["Bendy"].constraints.remove(constraint)
        bpy.context.view_layer.objects.active = self.rig
        self.rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        self.rig.data.edit_bones["Bendy"].parent = self.rig.data.edit_bones["Rigid"]
        bpy.ops.object.mode_set(mode="OBJECT")
        self.rig.pose.bones["Rigid"].scale = (1.4, 1.0, 0.7)
        self.scene.view_layers[0].update()
        before, allocation = state(self.rig, self.skin), ids()
        with self.assertRaisesRegex(ValueError, "shear"):
            bbone_baking.bake_bbone_skin(self.params)
        self.assertEqual(ids(), allocation)
        self.assertEqual(state(self.rig, self.skin), before)


if __name__ == "__main__":
    if "--cold" in sys.argv:
        index = sys.argv.index("--cold")
        cold_handoff(*sys.argv[index + 1 : index + 4])
        raise SystemExit(0)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BendyBakeTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
