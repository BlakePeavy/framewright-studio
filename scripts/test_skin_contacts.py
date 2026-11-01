"""Actual evaluated skin contacts and isolated-scene preservation."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import skin_contacts  # noqa: E402

KINDS = ("objects", "scenes", "meshes", "armatures", "shape_keys", "actions", "materials", "lights")


class SkinContactTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.before = self.inventory()
        self.scene = bpy.data.scenes.new("SkinContactFixture")
        bpy.context.window.scene = self.scene
        self.scene.unit_settings.scale_length = 1
        self.scene.render.fps = 24
        self.surface = self.mesh(
            "Ground", [(-4, -4, 0), (4, -4, 0), (4, 4, 0), (-4, 4, 0)], [(0, 1, 2), (0, 2, 3)]
        )
        self.skin = self.mesh(
            "EvaluatedSole", [(-0.2, -0.2, 0), (0.2, -0.2, 0), (0, 0.2, 0)], [(0, 1, 2)]
        )

    @staticmethod
    def inventory():
        return {kind: {item.session_uid for item in getattr(bpy.data, kind)} for kind in KINDS}

    def mesh(self, name, vertices, faces):
        data = bpy.data.meshes.new(name + "Mesh")
        data.from_pydata(vertices, [], faces)
        data.update()
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        return obj

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind in KINDS:
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def params(self, **changes):
        return {
            "surface_name": self.surface.name,
            "markers": [
                {"id": "heel", "object_name": self.skin.name, "vertex_indices": [0], "weights": [1]}
            ],
            "frame_start": 1,
            "frame_end": 3,
            **changes,
        }

    def animate(self, obj, path, values):
        for frame, value in values:
            setattr(obj, path, value)
            obj.keyframe_insert(path, frame=frame)
        owner = obj.id_data
        animation = owner.animation_data
        if animation and animation.action:
            for layer in animation.action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for curve in bag.fcurves:
                            for key in curve.keyframe_points:
                                key.interpolation = "LINEAR"

    def test_evaluated_shape_vertex_and_barycentric_point_follow_full_clip(self):
        self.skin.shape_key_add(name="Basis")
        lift = self.skin.shape_key_add(name="Lift")
        for point in lift.data:
            point.co.z += 0.2
        self.animate(lift, "value", [(1, 0), (3, 1)])
        self.scene.frame_set(2, subframe=0.25)
        before = self.inventory()
        report = skin_contacts.inspect_skin_contacts(
            self.params(
                markers=[
                    {
                        "id": "heel",
                        "object_name": self.skin.name,
                        "vertex_indices": [0],
                        "weights": [1],
                    },
                    {
                        "id": "ball",
                        "object_name": self.skin.name,
                        "vertex_indices": [0, 1, 2],
                        "weights": [0.25, 0.25, 0.5],
                    },
                ],
                substeps=2,
            )
        )
        self.assertEqual(len(report["samples"]), 5)
        self.assertEqual(report["coverage"], "complete_at_samples")
        self.assertTrue(report["temporal_coverage"]["every_integer_frame"])
        self.assertEqual(report["preservation"]["strategy"], "isolated_owned_scene")
        self.assertEqual(self.inventory(), before)
        self.assertEqual((self.scene.frame_current, self.scene.frame_subframe), (2, 0.25))
        for index, sample in enumerate(report["samples"]):
            for marker in sample["markers"]:
                self.assertAlmostEqual(marker["normal_distance_meters"], index * 0.05, places=6)
        self.assertEqual(len(report["marker_meshes"][0]["topology_sha256"]), 64)

    def test_public_dispatch_validates_real_triangle_and_releases_meshes(self):
        from framewright.api import dispatch

        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "skin",
                "command": "animation.skin_contacts",
                "params": self.params(),
            }
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["contact_samples"], 3)
        bad = self.mesh("Disconnected", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0)], [(0, 1, 2)])
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "triangle"):
            skin_contacts.inspect_skin_contacts(
                self.params(
                    markers=[
                        {
                            "id": "bad",
                            "object_name": bad.name,
                            "vertex_indices": [0, 1, 3],
                            "weights": [0.2, 0.3, 0.5],
                        }
                    ]
                )
            )
        self.assertEqual(self.inventory(), before)

    def test_dirty_unrelated_light_material_constraint_and_shape_are_untouched(self):
        light = bpy.data.lights.new("DirtyLight", "AREA")
        obj = bpy.data.objects.new("DirtyLight", light)
        self.scene.collection.objects.link(obj)
        self.animate(light, "energy", [(1, 10), (3, 30)])
        material = bpy.data.materials.new("DirtyMaterial")
        material.use_nodes = True
        self.skin.data.materials.append(material)
        socket = material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"]
        self.animate(socket, "default_value", [(1, 0.2), (3, 0.8)])
        constraint = self.skin.constraints.new("LIMIT_LOCATION")
        self.animate(constraint, "influence", [(1, 0), (3, 1)])
        self.skin.shape_key_add(name="Basis")
        key = self.skin.shape_key_add(name="DirtyKey")
        self.animate(key, "value", [(1, 0), (3, 1)])
        self.scene.frame_set(2, subframe=0.25)
        light.energy = 123.456
        socket.default_value = 0.1234
        constraint.influence = 0.4321
        key.value = 0.7654
        before = (
            light.energy,
            socket.default_value,
            constraint.influence,
            key.value,
            self.skin.data.materials[:],
            self.inventory(),
        )
        skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(
            (
                light.energy,
                socket.default_value,
                constraint.influence,
                key.value,
                self.skin.data.materials[:],
                self.inventory(),
            ),
            before,
        )
        sampler = skin_contacts._EvaluatedMarkers.__call__
        calls = []

        def fail_after_first(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("injected mid-interval")
            return sampler(*args)

        with patch.object(skin_contacts._EvaluatedMarkers, "__call__", fail_after_first):
            with self.assertRaisesRegex(RuntimeError, "mid-interval"):
                skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(
            (
                light.energy,
                socket.default_value,
                constraint.influence,
                key.value,
                self.skin.data.materials[:],
                self.inventory(),
            ),
            before,
        )

    def test_topology_change_rejects_without_partial_pass_or_allocations(self):
        subdivision = self.skin.modifiers.new("ChangingTopology", "SUBSURF")
        self.animate(subdivision, "levels", [(1, 0), (3, 1)])
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "topology"):
            skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(self.inventory(), before)

    def test_budget_and_foreign_driver_or_simulation_fail_before_copy(self):
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "budget"):
            skin_contacts.inspect_skin_contacts(self.params(max_evaluated_vertices=2))
        self.assertEqual(self.inventory(), before)
        curve = self.skin.driver_add("location", 0)
        curve.driver.expression = "__import__('os').getpid()"
        with self.assertRaisesRegex(ValueError, "native"):
            skin_contacts.inspect_skin_contacts(self.params())
        self.skin.driver_remove("location", 0)
        self.skin.modifiers.new("UnsupportedCache", "CLOTH")
        with self.assertRaisesRegex(ValueError, "modifier"):
            skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(self.inventory(), before)

    def test_sampling_failure_cleans_owned_scene_and_keeps_dirty_source(self):
        self.skin.location.z = 0.123
        before = self.inventory()
        with patch.object(
            skin_contacts, "_sample_contacts", side_effect=RuntimeError("injected after copying")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(self.inventory(), before)
        self.assertAlmostEqual(self.skin.location.z, 0.123)

    def test_scaled_sloped_surface_units_and_platform_compensation(self):
        for vertex in self.surface.data.vertices:
            vertex.co.z = 0.5 * vertex.co.x
        self.surface.scale = (2, 1, 0.5)
        self.skin.location.z = 0.175
        self.scene.unit_settings.scale_length = 0.01
        self.animate(self.surface, "location", [(1, (0, 0, 0)), (3, (1, 0, 0.125))])
        self.animate(self.skin, "location", [(1, (0, 0, 0.175)), (3, (1, 0, 0.3))])
        report = skin_contacts.inspect_skin_contacts(
            self.params(contact_tolerance=0.003, penetration_tolerance=0.001)
        )
        self.assertEqual(report["sliding_segments"], 0)
        self.assertAlmostEqual(
            report["samples"][0]["markers"][0]["normal_distance_meters"],
            0.002 / (1 + 0.125**2) ** 0.5,
            places=6,
        )

    def test_ray_miss_and_penetration_are_distinct_outcomes(self):
        self.skin.location.z = -0.1
        report = skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(report["penetration_samples"], 3)
        self.skin.location.x = 10
        report = skin_contacts.inspect_skin_contacts(self.params())
        self.assertEqual(report["coverage"], "partial")
        self.assertEqual(report["projection_misses"], 3)
        self.assertIsNone(report["samples"][0]["markers"][0]["penetrating"])

    def test_armature_and_corrective_driver_dependencies_are_copied_and_sampled(self):
        data = bpy.data.armatures.new("SkinRigData")
        rig = bpy.data.objects.new("SkinRig", data)
        self.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = data.edit_bones.new("Foot")
        bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.animate(rig.pose.bones["Foot"], "location", [(1, (0, 0, 0)), (3, (0, 0.2, 0))])
        self.skin.vertex_groups.new(name="Foot").add([0, 1, 2], 1, "REPLACE")
        self.skin.modifiers.new("Skin", "ARMATURE").object = rig
        self.skin.shape_key_add(name="Basis")
        lift = self.skin.shape_key_add(name="Corrective")
        for point in lift.data:
            point.co.z += 0.1
        rig["amount"] = 0.5
        curve = lift.driver_add("value")
        curve.driver.type = "AVERAGE"
        variable = curve.driver.variables.new()
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = rig
        variable.targets[0].data_path = '["amount"]'
        self.scene.frame_set(2, subframe=0.25)
        rig.pose.bones["Foot"].location = (0.123, 0.456, 0.789)
        before = (tuple(rig.pose.bones["Foot"].location), self.inventory(), lift.value)
        report = skin_contacts.inspect_skin_contacts(self.params(substeps=2))
        self.assertEqual(
            report["dependency_names"], sorted([self.surface.name, self.skin.name, rig.name])
        )
        for index, sample in enumerate(report["samples"]):
            self.assertAlmostEqual(
                sample["markers"][0]["normal_distance_meters"], 0.05 + index * 0.05, places=6
            )
        self.assertEqual(
            (tuple(rig.pose.bones["Foot"].location), self.inventory(), lift.value), before
        )
        self.assertIs(variable.targets[0].id, rig)

    def test_work_limit_and_registered_handlers_reject_without_sampling(self):
        before = self.inventory()
        with (
            patch.object(skin_contacts, "MAX_WORK", 10),
            patch.object(
                skin_contacts,
                "_isolated_scene",
                side_effect=AssertionError("allocated before work admission"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "work budget"):
                skin_contacts.inspect_skin_contacts(self.params())
        calls = []

        def foreign(scene):
            calls.append(scene)

        bpy.app.handlers.frame_change_pre.append(foreign)
        try:
            with self.assertRaisesRegex(ValueError, "handlers"):
                skin_contacts.inspect_skin_contacts(self.params())
            self.assertEqual(calls, [])
        finally:
            bpy.app.handlers.frame_change_pre.remove(foreign)
        self.assertEqual(self.inventory(), before)

    def test_cold_reopen_reproduces_every_sample_without_source_file_changes(self):
        self.animate(self.skin, "location", [(1, (0, 0, 0)), (3, (0, 0, 0.2))])
        params = self.params(substeps=2)
        expected = skin_contacts.inspect_skin_contacts(params)
        with tempfile.TemporaryDirectory(prefix="framewright-skin-contact-") as folder:
            folder = Path(folder)
            source = folder / "authored.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(source), copy=True)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            (folder / "params.json").write_text(json.dumps(params), encoding="utf-8")
            script = folder / "cold.py"
            script.write_text(
                "import sys,json\nfrom pathlib import Path\n"
                f"sys.path.insert(0,{str(ROOT)!r})\nfrom framewright.skin_contacts import inspect_skin_contacts\n"
                "folder=Path(__file__).parent\n"
                "report=inspect_skin_contacts(json.loads((folder/'params.json').read_text()))\n"
                "(folder/'report.json').write_text(json.dumps(report),encoding='utf-8')\n",
                encoding="utf-8",
            )
            child = subprocess.run(
                [
                    bpy.app.binary_path,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    str(source),
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(script),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertEqual(json.loads((folder / "report.json").read_text()), expected)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SkinContactTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Skin contact tests failed")
    print(f"FRAMEWRIGHT_SKIN_CONTACTS_OK tests={result.testsRun} version={bpy.app.version_string}")
