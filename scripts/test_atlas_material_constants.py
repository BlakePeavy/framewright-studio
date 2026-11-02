"""Real Blender material groups, literal factors, fallback links and cleanup."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import bpy  # noqa: E402
from test_material_atlas import cube, handler, inventory, material, source_state  # noqa: E402


class ConstantMaterialTests(unittest.TestCase):
    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        self.sources = [
            cube("Metal", material("MetalMat", (0.2, 0.1, 0.05), metal=0.85, roughness=0.3)),
            cube("Wood", material("WoodMat", (0.15, 0.08, 0.03)), 2),
        ]
        bpy.context.view_layer.update()

    def copies(self):
        result = []
        for source in self.sources:
            copy = source.copy()
            copy.data = source.data.copy()
            bpy.context.scene.collection.objects.link(copy)
            result.append(copy)
        return result

    def images(self):
        return {
            role: bpy.data.images.new("ConstantTest_" + role, width=4, height=4, float_buffer=True)
            for role in ["base_color", "roughness", "metallic", "normal"]
        }

    def test_literal_factors_and_geometry_normals_do_not_sample_blank_atlas(self):
        before = source_state(self.sources)
        copies, outputs = self.copies(), []
        records = handler()._assign_portable_materials(
            copies, self.images(), "UVMap", "ConstantOut", True, outputs
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(len(outputs), 2)
        for source, copy in zip(self.sources, copies, strict=True):
            shader = copy.data.materials[0].node_tree.nodes.get("Principled BSDF")
            original = source.data.materials[0].node_tree.nodes.get("Principled BSDF")
            for role in ["Base Color", "Roughness", "Metallic"]:
                self.assertFalse(shader.inputs[role].is_linked)
                self.assertEqual(
                    shader.inputs[role].default_value[:], original.inputs[role].default_value[:]
                ) if role == "Base Color" else self.assertEqual(
                    shader.inputs[role].default_value, original.inputs[role].default_value
                )
            self.assertFalse(shader.inputs["Normal"].is_linked)
        self.assertEqual(source_state(self.sources), before)

    def test_linked_values_stay_baked_and_equal_groups_deduplicate_per_face(self):
        metallic = self.sources[0].data.materials[0]
        rough = metallic.node_tree.nodes.new("ShaderNodeValue")
        rough.outputs[0].default_value = 0.3
        metallic.node_tree.links.new(
            rough.outputs[0], metallic.node_tree.nodes["Principled BSDF"].inputs["Roughness"]
        )
        self.sources[0].data.materials.append(self.sources[1].data.materials[0])
        for polygon in self.sources[0].data.polygons:
            polygon.material_index = polygon.index % 2
        copies, outputs = self.copies(), []
        indices = [p.material_index for p in copies[0].data.polygons]
        handler()._assign_portable_materials(
            copies, self.images(), "UVMap", "MixedOut", True, outputs
        )
        self.assertEqual(len(outputs), 2)
        self.assertEqual([p.material_index for p in copies[0].data.polygons], indices)
        self.assertIs(copies[0].data.materials[1], copies[1].data.materials[0])
        shader = copies[0].data.materials[0].node_tree.nodes["Principled BSDF"]
        self.assertTrue(shader.inputs["Roughness"].is_linked)
        self.assertEqual(shader.inputs["Roughness"].links[0].from_node.type, "TEX_IMAGE")

    def test_disabled_policy_still_uses_one_fully_baked_material(self):
        copies, outputs = self.copies(), []
        handler()._assign_portable_materials(
            copies, self.images(), "UVMap", "LegacyOut", False, outputs
        )
        self.assertEqual(len(outputs), 1)
        self.assertIs(copies[0].data.materials[0], copies[1].data.materials[0])
        shader = outputs[0].node_tree.nodes["Principled BSDF"]
        self.assertTrue(
            all(
                shader.inputs[name].is_linked
                for name in ["Base Color", "Roughness", "Metallic", "Normal"]
            )
        )

    def test_group_creation_failure_removes_every_owned_material_and_derivative(self):
        module = handler()
        before, state = inventory(), source_state(self.sources)
        original = module._portable_material
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args[0].name)
            if len(calls) == 2:
                raise RuntimeError("injected second group failure")
            return original(*args, **kwargs)

        with (
            patch.object(module, "_bake_pass"),
            patch.object(module, "_portable_material", fail_second),
        ):
            with self.assertRaisesRegex(RuntimeError, "second group"):
                module.bake_material_atlas(
                    {
                        "object_names": [o.name for o in self.sources],
                        "resolution": 128,
                        "margin": 2,
                        "preserve_material_constants": True,
                        "dry_run": False,
                    }
                )
        self.assertEqual(len(calls), 2)
        self.assertEqual(inventory(), before)
        self.assertEqual(source_state(self.sources), state)


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ConstantMaterialTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Atlas material constant checks failed")
