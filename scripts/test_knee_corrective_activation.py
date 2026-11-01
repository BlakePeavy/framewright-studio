"""Real geometry and cold-open tests for continuous knee corrective activation."""

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
from knee_corrective_activation import install_knee_activation  # noqa: E402

ANGLES = [
    0,
    10,
    19.99,
    20,
    20.01,
    30,
    45,
    60,
    75,
    90,
    100,
    109.99,
    110,
    110.01,
    125,
    135,
    90,
    45,
    0,
]


def samples():
    rig, host = bpy.data.objects["ActivationRig"], bpy.data.objects["ActivationMesh"]
    rows = []
    for angle in ANGLES:
        rig.pose.bones["ORG-shin.L"].rotation_euler.x = math.radians(angle)
        bpy.context.view_layer.update()
        owner = host.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = owner.to_mesh()
        try:
            actual = mesh.vertices[0].co.z / 0.1
        finally:
            owner.to_mesh_clear()
        t = max(0, min(1, (angle - 20) / 90))
        expected = (1 - math.cos(math.pi * t)) / 2
        if abs(actual - expected) > 2e-5:
            raise AssertionError((angle, actual, expected))
        rows.append({"angle": angle, "weight": actual})
    return rows


class KneeActivationTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("ActivationTest")
        bpy.context.window.scene = self.scene
        data = bpy.data.armatures.new("ActivationArmature")
        self.rig = bpy.data.objects.new("ActivationRig", data)
        self.scene.collection.objects.link(self.rig)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="EDIT")
        parent = None
        for name, head, tail in (
            ("ORG-thigh.L", (0, 0, 2), (0, 0, 1)),
            ("ORG-shin.L", (0, 0, 1), (0, 0, 0)),
            ("ORG-foot.L", (0, 0, 0), (0, -0.2, 0)),
        ):
            bone = data.edit_bones.new(name)
            bone.head, bone.tail, bone.parent = head, tail, parent
            bone.use_connect = parent is not None
            parent = bone
        bpy.ops.object.mode_set(mode="OBJECT")
        self.rig.pose.bones["ORG-shin.L"].rotation_mode = "XYZ"
        self.rig.location = (-2.2, 0.4, 0.6)
        self.rig.rotation_euler = (0.12, 0.23, 0.34)
        self.rig.scale = (1.3, 1.3, 1.3)
        data = bpy.data.meshes.new("ActivationMeshData")
        data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        self.host = bpy.data.objects.new("ActivationMesh", data)
        self.scene.collection.objects.link(self.host)
        self.host.shape_key_add(name="Basis")
        self.key = self.host.shape_key_add(name="KneeCorrection")
        self.key.data[0].co.z = 0.1
        bpy.context.view_layer.update()

    def tearDown(self):
        bpy.context.window.scene = self.old_scene
        for obj in list(self.scene.objects):
            data = obj.data
            store = bpy.data.armatures if obj.type == "ARMATURE" else bpy.data.meshes
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                store.remove(data)
        bpy.data.scenes.remove(self.scene)

    def test_geometry_follows_measured_angle_continuously_and_reversibly(self):
        receipt = install_knee_activation(self.key, self.rig, "L")
        rows = samples()
        self.assertEqual(rows[0]["weight"], rows[-1]["weight"])
        self.assertEqual(receipt["measurement"], "world_joint_distances_law_of_cosines")
        self.assertTrue(
            self.host.data.shape_keys.animation_data.drivers[0].driver.is_simple_expression
        )
        self.assertIsNone(self.rig.animation_data)

    def test_invalid_ranges_or_missing_bones_do_not_mutate(self):
        for start, full in ((30, 20), (-1, 110), (20, float("nan")), (20, 180)):
            with self.assertRaises(ValueError):
                install_knee_activation(self.key, self.rig, "L", start, full)
        with self.assertRaises(ValueError):
            install_knee_activation(self.key, self.rig, "R")
        self.assertIsNone(self.host.data.shape_keys.animation_data)

    def test_existing_driver_is_not_replaced(self):
        install_knee_activation(self.key, self.rig, "L")
        expression = self.host.data.shape_keys.animation_data.drivers[0].driver.expression
        with self.assertRaises(ValueError):
            install_knee_activation(self.key, self.rig, "L")
        self.assertEqual(
            self.host.data.shape_keys.animation_data.drivers[0].driver.expression, expression
        )

    def test_cold_process_needs_no_autoexecution(self):
        install_knee_activation(self.key, self.rig, "L")
        expected = samples()
        with tempfile.TemporaryDirectory(prefix="fw-knee-activation-") as temporary:
            folder = Path(temporary)
            blend, output = folder / "activation.blend", folder / "result.json"
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
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
                str(blend),
                str(output),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=60, check=False
            )
            self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])
            self.assertEqual(json.loads(output.read_text()), expected)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if args and args[0] == "--cold":
        bpy.ops.wm.open_mainfile(filepath=args[1])
        Path(args[2]).write_text(json.dumps(samples()))
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(KneeActivationTests)
        )
        if not result.wasSuccessful():
            raise AssertionError("Continuous knee activation tests failed")
