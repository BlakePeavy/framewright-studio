"""Review atlas-owned assemblies without bypassing existing source admission."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framewright.api import dispatch
from framewright.production_assets import setup_review_scene


class AtlasReviewTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.collection = bpy.data.collections.new("AuthoredAtlas")
        self.collection["framewright_owner"] = "material_atlas"
        bpy.context.scene.collection.children.link(self.collection)
        self.parent = bpy.data.objects.new("AtlasDoorPivot", None)
        self.parent["framewright_owner"] = "material_atlas"
        self.collection.objects.link(self.parent)
        self.parent.location = (0.25, -0.5, 1.0)
        self.parent.rotation_euler.z = 0.3
        mesh = bpy.data.meshes.new("AtlasSourceGeometry")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        mesh.uv_layers.new(name="OriginalConstructionUV")
        mesh.uv_layers.new(name="MaterialAtlasUV")
        for layer in mesh.uv_layers:
            for item, uv in zip(layer.data, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
                item.uv = uv
        self.mesh = bpy.data.objects.new("AtlasDoor", mesh)
        self.mesh["framewright_owner"] = "material_atlas"
        self.collection.objects.link(self.mesh)
        self.mesh.parent = self.parent
        self.mesh.location = (0.1, 0.2, 0.3)
        self.mesh.hide_render = True
        self.mesh.hide_set(True)
        self.material = bpy.data.materials.new("PackedAtlasMaterial")
        self.material.use_nodes = True
        self.image = bpy.data.images.new("AtlasColor", width=2, height=2)
        self.image.pixels[:] = [0.12, 0.34, 0.56, 1.0] * 4
        node = self.material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = self.image
        shader = self.material.node_tree.nodes.get("Principled BSDF")
        self.material.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
        self.mesh.data.materials.append(self.material)
        bpy.context.view_layer.update()

    def fingerprint(self):
        return (
            tuple(tuple(row) for row in self.parent.matrix_world),
            tuple(tuple(row) for row in self.mesh.matrix_world),
            self.mesh.parent.as_pointer(),
            self.mesh.data.as_pointer(),
            tuple(tuple(vertex.co) for vertex in self.mesh.data.vertices),
            tuple(
                (layer.name, tuple(tuple(item.uv) for item in layer.data))
                for layer in self.mesh.data.uv_layers
            ),
            self.mesh.hide_render,
            self.mesh.hide_get(),
            tuple(self.image.pixels[:]),
            self.image.colorspace_settings.name,
            tuple(
                (link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name)
                for link in self.material.node_tree.links
            ),
        )

    def test_preview_accepts_atlas_collection_without_allocating_or_changing_source(self):
        before = self.fingerprint()
        ids = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.scenes))
        result = setup_review_scene({"collection_name": self.collection.name})
        self.assertTrue(result["dry_run"])
        self.assertEqual(set(result["source_objects"]), {self.mesh.name, self.parent.name})
        self.assertEqual(result["visual_acceptance"], "not_reviewed")
        self.assertEqual(ids, (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.scenes)))
        self.assertEqual(self.fingerprint(), before)

    def test_actual_review_keeps_pivot_hierarchy_images_and_original_uvs(self):
        before = self.fingerprint()
        result = setup_review_scene(
            {"collection_name": self.collection.name, "name": "AtlasReview", "dry_run": False}
        )
        review = bpy.data.scenes[result["scene"]]
        child = review.objects["AtlasReview_AtlasDoor"]
        parent = review.objects["AtlasReview_AtlasDoorPivot"]
        self.assertIs(child.parent, parent)
        self.assertIsNot(child.data, self.mesh.data)
        self.assertFalse(child.hide_render)
        self.assertFalse(child.hide_get(view_layer=review.view_layers[0]))
        # Native LRS reconstruction can round a rotated derivative by one float32 ULP.
        self.assertLessEqual(
            max(
                abs(value - expected)
                for row, original in zip(child.matrix_world, before[1], strict=True)
                for value, expected in zip(row, original, strict=True)
            ),
            1e-6,
        )
        self.assertEqual(
            [uv.name for uv in child.data.uv_layers], ["OriginalConstructionUV", "MaterialAtlasUV"]
        )
        self.assertIs(child.data.materials[0], self.material)
        self.assertEqual(self.fingerprint(), before)

    def test_unknown_owner_inside_atlas_collection_is_refused_before_output(self):
        self.mesh["framewright_owner"] = "unrelated"
        before = set(bpy.data.scenes)
        with self.assertRaisesRegex(ValueError, "owned"):
            setup_review_scene({"collection_name": self.collection.name, "dry_run": False})
        self.assertEqual(set(bpy.data.scenes), before)

    def test_atlas_ownership_does_not_bypass_animated_material_refusal(self):
        shader = self.material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Roughness"].keyframe_insert("default_value", frame=1)
        before = set(bpy.data.scenes)
        with self.assertRaisesRegex(ValueError, "animation|drivers"):
            setup_review_scene({"collection_name": self.collection.name, "dry_run": False})
        self.assertEqual(set(bpy.data.scenes), before)

    def test_explicit_object_scope_accepts_mixed_known_owners(self):
        self.parent["framewright_owner"] = "production_assets"
        result = setup_review_scene({"object_names": [self.parent.name, self.mesh.name]})
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["source_objects"]), 2)

    def test_cold_hidden_hierarchy_uses_authored_transforms_without_source_evaluation(self):
        self.parent.scale = (1.2, 0.8, 1.1)
        self.mesh.matrix_parent_inverse = Matrix.Translation((0.2, -0.1, 0.4))
        self.mesh.delta_location = (0.05, 0.1, -0.2)
        bpy.context.view_layer.update()
        expected = {obj.name: obj.matrix_world.copy() for obj in (self.parent, self.mesh)}
        for obj in (self.parent, self.mesh):
            obj.hide_viewport = True
        root = Path(__file__).resolve().parents[1] / "artifacts/test-temp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="atlas-review-cold-", dir=root) as directory:
            path = Path(directory) / "hidden.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
            self.parent = bpy.data.objects["AtlasDoorPivot"]
            self.mesh = bpy.data.objects["AtlasDoor"]
            self.collection = bpy.data.collections["AuthoredAtlas"]
            self.material = bpy.data.materials["PackedAtlasMaterial"]
            self.image = bpy.data.images["AtlasColor"]
            before = self.fingerprint()
            self.assertGreater(
                (self.mesh.matrix_world.translation - expected[self.mesh.name].translation).length,
                0.5,
                "Control must reproduce the cold hidden-object evaluation cache defect",
            )
            result = setup_review_scene(
                {"collection_name": self.collection.name, "name": "ColdReview", "dry_run": False}
            )
            for name, matrix in expected.items():
                copy = bpy.data.objects[result["copies"][name]]
                error = max(
                    abs(copy.matrix_world[i][j] - matrix[i][j]) for i in range(4) for j in range(4)
                )
                self.assertLessEqual(error, 1e-6, name)
            self.assertEqual(self.fingerprint(), before)
            self.assertTrue(self.parent.hide_viewport and self.mesh.hide_viewport)

    def test_review_floor_fits_evaluated_derivative_modifier_bounds(self):
        solid = self.mesh.modifiers.new("AuthoredThickness", "SOLIDIFY")
        solid.thickness = 0.4
        solid.offset = -1
        bpy.context.view_layer.update()
        evaluated = self.mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        expected_bottom = min(
            (evaluated.matrix_world @ vertex.co).z for vertex in evaluated.data.vertices
        )
        setup_review_scene(
            {"collection_name": self.collection.name, "name": "BoundsReview", "dry_run": False}
        )
        floor = bpy.data.objects["BoundsReview_Floor"]
        self.assertAlmostEqual(floor.location.z, expected_bottom - 0.025, places=5)

    def test_animated_external_parent_refuses_before_allocating_review(self):
        self.parent.keyframe_insert("location", frame=1)
        ids = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.scenes))
        with self.assertRaisesRegex(ValueError, "parent|static"):
            setup_review_scene({"object_names": [self.mesh.name], "dry_run": False})
        self.assertEqual(ids, (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.scenes)))

    def test_documented_workflow_binds_built_parts_through_atlas_into_review(self):
        path = Path(__file__).resolve().parents[1] / "examples/build-atlas-review.json"
        request = json.loads(path.read_text())
        counts = (len(bpy.data.objects), len(bpy.data.images), len(bpy.data.scenes))
        preview = dispatch(request)
        self.assertTrue(preview["ok"], preview)
        self.assertEqual(preview["result"]["status"], "validated")
        self.assertEqual(
            counts, (len(bpy.data.objects), len(bpy.data.images), len(bpy.data.scenes))
        )
        request["params"]["dry_run"] = False
        request["params"]["steps"][1]["params"].update(resolution=128, margin=1)
        reply = dispatch(request)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"]["status"], "completed", reply)
        stages = {step["id"]: step["response"]["result"] for step in reply["result"]["steps"]}
        self.assertEqual(len(stages["build"]["objects"]), 30)
        self.assertEqual(set(stages["atlas"]["derivatives"]), set(stages["build"]["objects"]))
        self.assertEqual(set(stages["review"]["source_objects"]), set(stages["atlas"]["objects"]))
        self.assertEqual(stages["review"]["visual_acceptance"], "not_reviewed")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AtlasReviewTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
