"""Isolated Blender material-slot derivatives and complete PBR review workflow."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402
from test_materials import png  # noqa: E402

from framewright import material_assignment  # noqa: E402
from framewright.api import dispatch  # noqa: E402
from framewright.workflows import clear_run_cache  # noqa: E402


class MaterialAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_scene = bpy.context.window.scene
        self.kinds = (
            "objects",
            "scenes",
            "meshes",
            "armatures",
            "materials",
            "images",
            "cameras",
            "lights",
            "worlds",
            "collections",
            "actions",
            "libraries",
        )
        self.before_ids = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)} for kind in self.kinds
        }
        self.scene = bpy.data.scenes.new("MaterialAssignmentFixture")
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("SourceMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2), (0, 2, 3)])
        uv = mesh.uv_layers.new()
        for loop in mesh.loops:
            uv.data[loop.index].uv = mesh.vertices[loop.vertex_index].co.xy
        self.source = bpy.data.objects.new("Source", mesh)
        self.scene.collection.objects.link(self.source)
        self.peer = bpy.data.objects.new("SharedMeshPeer", mesh)
        self.scene.collection.objects.link(self.peer)
        self.materials = [bpy.data.materials.new(f"Material{i}") for i in range(4)]
        for material in self.materials[:3]:
            mesh.materials.append(material)
        self.source.material_slots[1].link = "OBJECT"
        self.source.material_slots[1].material = self.materials[3]
        mesh.polygons[0].material_index = 0
        mesh.polygons[1].material_index = 1
        self.target = bpy.data.materials.new("TargetPBR")
        self.target.use_nodes = True

    def tearDown(self):
        clear_run_cache()
        bpy.context.window.scene = self.previous_scene
        for kind in self.kinds:
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.before_ids[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)
        self.temp.cleanup()

    def params(self, **changes):
        return {
            "object_name": self.source.name,
            "material_name": self.target.name,
            "slot_indices": [1, 2],
            **changes,
        }

    def snapshot(self, obj):
        return {
            "data": obj.data.session_uid,
            "vertices": [tuple(v.co) for v in obj.data.vertices],
            "polygons": [(tuple(p.vertices), p.material_index) for p in obj.data.polygons],
            "uv": [tuple(v.uv) for v in obj.data.uv_layers.active.data],
            "slots": [
                (s.link, s.material.session_uid if s.material else None) for s in obj.material_slots
            ],
            "data_materials": [m.session_uid if m else None for m in obj.data.materials],
            "parent": obj.parent,
            "parent_inverse": tuple(tuple(row) for row in obj.matrix_parent_inverse),
            "basis": tuple(tuple(row) for row in obj.matrix_basis),
            "modifiers": [(m.name, m.type, getattr(m, "object", None)) for m in obj.modifiers],
            "weights": [[(g.group, g.weight) for g in v.groups] for v in obj.data.vertices],
        }

    def test_preview_preserves_all_data_and_reports_selected_slots(self):
        before = self.snapshot(self.source), len(bpy.data.objects), len(bpy.data.meshes)
        result = material_assignment.assign_material(self.params())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["slot_indices"], [1, 2])
        self.assertEqual(
            before, (self.snapshot(self.source), len(bpy.data.objects), len(bpy.data.meshes))
        )

    def test_data_and_object_links_geometry_parent_skin_and_shared_peer_are_preserved(self):
        parent = bpy.data.objects.new("Parent", None)
        self.scene.collection.objects.link(parent)
        parent.location = (3, 2, 1)
        parent.rotation_euler.z = 0.4
        parent.scale = (2, 1, 3)
        self.source.parent = parent
        self.source.matrix_parent_inverse = Matrix.Translation((1, 2, 3))
        self.source.location = (0.2, 0.3, 0.4)
        rig = bpy.data.objects.new("SkinRig", bpy.data.armatures.new("SkinRigData"))
        self.scene.collection.objects.link(rig)
        self.source.modifiers.new("Skin", "ARMATURE").object = rig
        self.source.vertex_groups.new(name="Bone").add([0, 1, 2, 3], 0.75, "REPLACE")
        self.source.shape_key_add(name="Basis")
        self.source.shape_key_add(name="Detail").data[0].co.z += 0.2
        before, peer = self.snapshot(self.source), self.snapshot(self.peer)
        target_before = json.dumps([(n.name, n.type) for n in self.target.node_tree.nodes])
        result = material_assignment.assign_material(self.params(dry_run=False))
        derivative = self.scene.objects[result["derivative"]]
        self.assertNotEqual(derivative.data, self.source.data)
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        self.assertEqual(self.snapshot(self.source), before)
        self.assertEqual(self.snapshot(self.peer), peer)
        self.assertEqual([s.link for s in derivative.material_slots], ["DATA", "OBJECT", "DATA"])
        self.assertEqual(
            [s.material for s in derivative.material_slots],
            [self.materials[0], self.target, self.target],
        )
        self.assertEqual(derivative.data.materials[1], self.materials[1])
        self.assertEqual(
            json.dumps([(n.name, n.type) for n in self.target.node_tree.nodes]), target_before
        )
        copied = self.snapshot(derivative)
        for field in (
            "vertices",
            "polygons",
            "uv",
            "parent",
            "parent_inverse",
            "basis",
            "modifiers",
            "weights",
        ):
            self.assertEqual(copied[field], before[field], field)
        self.assertNotEqual(derivative.data.shape_keys, self.source.data.shape_keys)
        self.assertEqual(
            tuple(derivative.data.shape_keys.key_blocks["Detail"].data[0].co),
            tuple(self.source.data.shape_keys.key_blocks["Detail"].data[0].co),
        )

    def test_zero_slots_accepts_only_zero_and_keeps_polygon_indices(self):
        self.source.data.materials.clear()
        for polygon in self.source.data.polygons:
            polygon.material_index = 0
        before = len(bpy.data.objects), len(bpy.data.meshes)
        with self.assertRaises(ValueError):
            material_assignment.assign_material(self.params(slot_indices=[1], dry_run=False))
        self.assertEqual(before, (len(bpy.data.objects), len(bpy.data.meshes)))
        result = material_assignment.assign_material(self.params(slot_indices=[0], dry_run=False))
        derivative = self.scene.objects[result["derivative"]]
        self.assertEqual(list(derivative.data.materials), [self.target])
        self.assertEqual(len(self.source.material_slots), 0)

    def test_invalid_indices_reject_before_allocation(self):
        for selection in ([3], [1, 1], [True], []):
            with self.subTest(selection=selection):
                before = len(bpy.data.objects), len(bpy.data.meshes)
                with self.assertRaises(ValueError):
                    material_assignment.assign_material(
                        self.params(slot_indices=selection, dry_run=False)
                    )
                self.assertEqual(before, (len(bpy.data.objects), len(bpy.data.meshes)))
        self.source.data.polygons[0].material_index = 7
        with self.assertRaisesRegex(ValueError, "polygon"):
            material_assignment.assign_material(self.params(dry_run=False))

    def test_failure_removes_only_derivative_and_keeps_source_and_material(self):
        self.source.shape_key_add(name="Basis")
        self.source.shape_key_add(name="Detail")
        before = (
            self.snapshot(self.source),
            len(bpy.data.objects),
            len(bpy.data.meshes),
            len(bpy.data.materials),
            len(bpy.data.shape_keys),
        )
        original = material_assignment._assign_slots

        def fail_after_one_assignment(derivative, material, indices):
            original(derivative, material, indices[:1])
            raise RuntimeError("Fixture assignment failure")

        with patch.object(
            material_assignment, "_assign_slots", side_effect=fail_after_one_assignment
        ):
            with self.assertRaisesRegex(RuntimeError, "Fixture"):
                material_assignment.assign_material(self.params(dry_run=False))
        self.assertEqual(
            before,
            (
                self.snapshot(self.source),
                len(bpy.data.objects),
                len(bpy.data.meshes),
                len(bpy.data.materials),
                len(bpy.data.shape_keys),
            ),
        )

    def test_repeated_assignment_allocates_unique_derivatives_without_overwrite(self):
        first = material_assignment.assign_material(self.params(dry_run=False))
        before = self.snapshot(self.scene.objects[first["derivative"]])
        second = material_assignment.assign_material(self.params(dry_run=False))
        self.assertNotEqual(first["derivative"], second["derivative"])
        self.assertEqual(self.snapshot(self.scene.objects[first["derivative"]]), before)

    def test_linked_mesh_and_ambiguous_material_reject_before_allocation(self):
        path = str(Path(self.temp.name) / "library.blend")
        bpy.data.libraries.write(path, {self.source, self.target})
        with bpy.data.libraries.load(path, link=True) as (source, target):
            target.materials = [self.target.name]
            target.objects = [self.source.name]
        self.scene.collection.objects.link(target.objects[0])
        before = len(bpy.data.objects), len(bpy.data.meshes)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            material_assignment.assign_material(self.params(dry_run=False))
        linked = target.objects[0]
        bpy.data.objects.remove(linked, do_unlink=True)
        with self.assertRaisesRegex(ValueError, "Material"):
            material_assignment.assign_material(self.params(dry_run=False))
        self.assertEqual((before[0] - 1, before[1]), (len(bpy.data.objects), len(bpy.data.meshes)))

    def test_linked_objects_linked_mesh_data_and_overrides_reject(self):
        path = str(Path(self.temp.name) / "linked.blend")
        bpy.data.libraries.write(path, {self.source})
        self.source.name = "LocalSource"
        with bpy.data.libraries.load(path, link=True) as (_, target):
            target.objects = ["Source"]
        linked = target.objects[0]
        self.scene.collection.objects.link(linked)
        local_with_linked_data = bpy.data.objects.new("LocalWithLinkedMesh", linked.data)
        self.scene.collection.objects.link(local_with_linked_data)
        override = linked.override_create(remap_local_usages=False)
        self.scene.collection.objects.link(override)
        override.name = "OverriddenSource"
        for obj in (linked, local_with_linked_data, override):
            with self.subTest(object=obj.name):
                before = len(bpy.data.objects), len(bpy.data.meshes)
                with self.assertRaisesRegex(ValueError, "local mesh"):
                    material_assignment.assign_material(
                        self.params(object_name=obj.name, dry_run=False)
                    )
                self.assertEqual(before, (len(bpy.data.objects), len(bpy.data.meshes)))

    def test_review_copies_visible_despite_hidden_subject_and_parent(self):
        from framewright import production_assets

        parent = bpy.data.objects.new("OwnedParent", None)
        self.scene.collection.objects.link(parent)
        self.source.parent = parent
        for obj in (self.source, parent):
            obj["framewright_owner"] = production_assets.OWNER
            obj.hide_viewport = True
            obj.hide_render = True
            obj.hide_set(True)
        result = production_assets.setup_review_scene(
            {"object_names": [self.source.name, parent.name], "resolution": 64, "dry_run": False}
        )
        review = bpy.data.scenes[result["scene"]]
        for obj in (self.source, parent):
            copy = review.objects[result["copies"][obj.name]]
            self.assertFalse(copy.hide_viewport)
            self.assertFalse(copy.hide_render)
            self.assertFalse(copy.hide_get(view_layer=review.view_layers[0]))
            self.assertTrue(obj.hide_viewport and obj.hide_render and obj.hide_get())
        self.assertEqual(
            review.objects[result["copies"][self.source.name]].parent,
            review.objects[result["copies"][parent.name]],
        )

    def test_actual_pbr_assignment_review_workflow_preserves_source(self):
        path = Path(self.temp.name) / "color.png"
        path.write_bytes(png())
        before = self.snapshot(self.source)
        workflow = {
            "run_id": "material-review",
            "dry_run": False,
            "steps": [
                {
                    "id": "build",
                    "command": "model.build_prop",
                    "params": {"name": "AssignReviewCabinet", "dry_run": False},
                },
                {
                    "id": "pbr",
                    "command": "surfaces.create_pbr_material",
                    "params": {"base_color_path": str(path), "dry_run": False},
                },
                {
                    "id": "assign",
                    "command": "surfaces.assign_material",
                    "params": {
                        "object_name": "AssignReviewCabinet_Top",
                        "material_name": {"$ref": "pbr.result.material"},
                        "slot_indices": [0],
                        "dry_run": False,
                    },
                },
                {
                    "id": "review",
                    "command": "lighting.create_review",
                    "params": {
                        "object_names": [{"$ref": "assign.result.derivative"}],
                        "resolution": 64,
                        "dry_run": False,
                    },
                },
            ],
        }
        response = dispatch(
            {
                "schema_version": "1.0",
                "request_id": "workflow",
                "command": "workflow.run",
                "params": workflow,
            }
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["status"], "completed", response)
        results = {step["id"]: step["response"]["result"] for step in response["result"]["steps"]}
        derivative = self.scene.objects[results["assign"]["derivative"]]
        material = bpy.data.materials[results["pbr"]["material"]]
        review = bpy.data.scenes[results["review"]["scene"]]
        reviewed = review.objects[results["review"]["copies"][derivative.name]]
        self.assertEqual(reviewed.material_slots[0].material, material)
        self.assertNotEqual(
            self.scene.objects["AssignReviewCabinet_Top"].material_slots[0].material, material
        )
        self.assertTrue(derivative.hide_viewport and derivative.hide_render)
        self.assertFalse(reviewed.hide_viewport)
        self.assertFalse(reviewed.hide_render)
        self.assertTrue(
            any(
                node.type == "TEX_IMAGE" and node.image.size[:] == (2, 2)
                for node in material.node_tree.nodes
            )
        )
        self.assertEqual(self.snapshot(self.source), before)
        self.assertEqual(path.read_bytes(), png())


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an owned background Blender process")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(MaterialAssignmentTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Material assignment tests failed")
    print(f"FRAMEWRIGHT_MATERIAL_ASSIGNMENT_OK tests={result.testsRun}")
