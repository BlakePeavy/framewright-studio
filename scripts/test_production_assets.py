"""Isolated Blender acceptance tests for authored assets and review scenes."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import production_assets as assets  # noqa: E402


def counts():
    return tuple(
        len(getattr(bpy.data, kind))
        for kind in (
            "objects",
            "meshes",
            "collections",
            "materials",
            "scenes",
            "worlds",
            "cameras",
            "lights",
        )
    )


class ProductionAssetTests(unittest.TestCase):
    def test_01_dry_runs_leave_all_datablocks_unchanged(self):
        before = counts()
        self.assertTrue(assets.build_prop({})["dry_run"])
        self.assertTrue(assets.build_facade({})["dry_run"])
        self.assertEqual(counts(), before)

    def test_02_invalid_parameters_fail_without_allocating(self):
        before = counts()
        for params in (
            {"width": float("nan")},
            {"dry_run": "false"},
            {"unknown": 1},
            {"width": 0.1},
        ):
            with self.assertRaises(ValueError):
                assets.build_prop(params)
        with self.assertRaises(ValueError):
            assets.build_facade({"width": 2, "dry_run": False})
        self.assertEqual(counts(), before)

    def test_03_prop_is_editable_uv_mapped_and_context_preserved(self):
        old_scene = bpy.context.scene
        old_active = bpy.context.view_layer.objects.active
        old_selection = tuple(bpy.context.selected_objects)
        result = assets.build_prop({"name": "TestCabinet", "dry_run": False})
        self.assertGreater(len(result["objects"]), 25)
        collection = bpy.data.collections[result["collection"]]
        self.assertEqual(collection["framewright_owner"], "production_assets")
        meshes = [obj for obj in collection.objects if obj.type == "MESH"]
        self.assertTrue(all(obj.data.uv_layers for obj in meshes))
        self.assertTrue(all(any(mod.type == "BEVEL" for mod in obj.modifiers) for obj in meshes))
        self.assertTrue(all(obj.data.materials for obj in meshes))
        self.assertIn("door_pivot", result["controls"])
        self.assertIs(bpy.context.scene, old_scene)
        self.assertIs(bpy.context.view_layer.objects.active, old_active)
        self.assertEqual(tuple(bpy.context.selected_objects), old_selection)

    def test_04_door_is_articulated_and_source_names_are_unique(self):
        first = assets.build_prop(
            {"name": "RepeatCabinet", "door_open_degrees": 65, "dry_run": False}
        )
        second = assets.build_prop({"name": "RepeatCabinet", "dry_run": False})
        self.assertNotEqual(first["collection"], second["collection"])
        pivot = bpy.data.objects[first["controls"]["door_pivot"]]
        self.assertAlmostEqual(pivot.rotation_euler.z, -65 * 3.141592653589793 / 180, places=5)
        self.assertGreater(len(pivot.children), 8)

    def test_05_facade_has_separate_construction_and_glazing(self):
        result = assets.build_facade({"name": "TestFacade", "dry_run": False})
        collection = bpy.data.collections[result["collection"]]
        roles = {obj.get("framewright_role") for obj in collection.objects}
        self.assertTrue({"wall", "glazing", "window_frame", "sill", "door"}.issubset(roles))
        self.assertGreater(len(collection.objects), 20)
        for obj in collection.objects:
            if obj.type == "MESH":
                self.assertTrue(obj.data.uv_layers)
                self.assertTrue(obj.data.materials)

    def test_06_failed_build_cleans_only_its_owned_datablocks(self):
        before = counts()
        actual = assets._box
        calls = 0

        def fail_after_one(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected fixture failure")
            return actual(*args, **kwargs)

        with patch.object(assets, "_box", side_effect=fail_after_one):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                assets.build_prop({"dry_run": False})
        self.assertEqual(counts(), before)

    def test_07_review_dry_run_and_resolution_do_not_allocate_images(self):
        prop = assets.build_prop({"name": "ReviewSource", "dry_run": False})
        before = counts()
        result = assets.setup_review_scene(
            {"collection_name": prop["collection"], "resolution": 8192}
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(counts(), before)
        with self.assertRaises(ValueError):
            assets.setup_review_scene({"collection_name": prop["collection"], "resolution": 16384})

    def test_08_review_scene_is_separate_with_independent_meshes(self):
        prop = assets.build_prop(
            {"name": "IsolatedSource", "location": [3, 4, 0], "dry_run": False}
        )
        old_scene = bpy.context.scene
        source = bpy.data.collections[prop["collection"]]
        original = {obj.name: (obj.data, obj.matrix_world.copy()) for obj in source.objects}
        image_count = len(bpy.data.images)
        review = assets.setup_review_scene(
            {
                "collection_name": prop["collection"],
                "lighting": "dusk",
                "resolution": 8192,
                "dry_run": False,
            }
        )
        scene = bpy.data.scenes[review["scene"]]
        self.assertIs(bpy.context.scene, old_scene)
        self.assertEqual(scene.render.resolution_x, 8192)
        self.assertEqual(scene.view_settings.view_transform, "AgX")
        self.assertEqual(set(review["cameras"]), {"front", "side", "back", "three_quarter"})
        self.assertEqual(len([obj for obj in scene.objects if obj.type == "LIGHT"]), 3)
        self.assertEqual(len(bpy.data.images), image_count)
        for name, (data, matrix) in original.items():
            self.assertEqual(bpy.data.objects[name].matrix_world, matrix)
            if bpy.data.objects[name].type == "MESH":
                copy = bpy.data.objects[review["copies"][name]]
                self.assertIsNot(copy.data, data)

    def test_09_review_rejects_unowned_sources(self):
        mesh = bpy.data.meshes.new("UnownedMesh")
        obj = bpy.data.objects.new("UnownedObject", mesh)
        bpy.context.scene.collection.objects.link(obj)
        before = counts()
        with self.assertRaises(ValueError):
            assets.setup_review_scene({"object_names": [obj.name], "dry_run": False})
        self.assertEqual(counts(), before)

    def test_10_resource_counts_distinguish_shared_meshes_and_instances(self):
        scene = bpy.data.scenes.new("ResourceFixture")
        collection = bpy.data.collections.new("ResourceMeshes")
        scene.collection.children.link(collection)
        mesh = bpy.data.meshes.new("SharedTriangle")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        for index in range(2):
            obj = bpy.data.objects.new(f"Triangle{index}", mesh)
            collection.objects.link(obj)
        instance = bpy.data.objects.new("CollectionInstance", None)
        instance.instance_type = "COLLECTION"
        instance.instance_collection = collection
        scene.collection.objects.link(instance)
        report = assets.scene_resources({"scene_name": scene.name})
        self.assertEqual(report["unique_mesh_datablocks"], 1)
        self.assertEqual(report["source_triangles_unique"], 1)
        self.assertEqual(report["evaluated_triangles_objects"], 2)
        self.assertEqual(report["evaluated_triangles_with_instances"], 4)
        self.assertEqual(report["instance_occurrences"], 2)
        json.dumps(report, allow_nan=False)

    def test_11_resource_report_is_read_only(self):
        before = counts()
        active = bpy.context.scene
        assets.scene_resources({})
        self.assertEqual(counts(), before)
        self.assertIs(bpy.context.scene, active)

    def test_12_cabinet_sides_stop_below_top_board(self):
        result = assets.build_prop({"name": "TopJoin", "dry_run": False})
        objects = bpy.data.collections[result["collection"]].objects
        top = next(obj for obj in objects if obj.name.endswith("_Top"))
        top_bottom = min((top.matrix_world @ vertex.co).z for vertex in top.data.vertices)
        for side in (obj for obj in objects if "_Side" in obj.name):
            side_top = max((side.matrix_world @ vertex.co).z for vertex in side.data.vertices)
            self.assertAlmostEqual(side_top, top_bottom, places=5)

    def test_13_invalid_lighting_rejects_with_value_error(self):
        with self.assertRaises(ValueError):
            assets.setup_review_scene({"lighting": []})

    def resource_fixture(self, name):
        scene = bpy.data.scenes.new(name)
        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
            [],
            [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
        )
        source = bpy.data.objects.new(name + "Source", mesh)
        scene.collection.objects.link(source)
        return scene, source

    def test_14_lod_accounting_uses_persisted_metadata_after_rename(self):
        from framewright import lod

        scene, source = self.resource_fixture("LODAccounting")
        with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
            result = lod.create_lod(
                {"object_name": source.name, "level": 3, "ratio": 0.6, "dry_run": False}
            )
        derivative = bpy.data.objects[result["derivative"]]
        derivative.name = "ArbitraryRenamedDerivative"
        before = counts()
        report = assets.scene_resources({"scene_name": scene.name})
        self.assertEqual(counts(), before)
        group = report["lod"]["groups"][0]
        self.assertEqual(group["source"], source.name)
        self.assertEqual(group["levels"], [3])
        self.assertEqual(group["metadata_coverage"], "complete_for_declared_derivatives")
        row = group["derivatives"][0]
        self.assertEqual(row["object"], derivative.name)
        self.assertEqual(row["level"], 3)
        self.assertTrue(row["hidden_viewport"])
        self.assertEqual(row["evaluated_occurrences"], 0)
        self.assertGreater(row["source_triangles"], 0)

    def test_15_lod_missing_or_duplicate_metadata_is_reported_without_guessing(self):
        scene, source = self.resource_fixture("LODMissing")
        names = []
        for name, source_name, level in (
            ("Legacy_LOD7", source.name, None),
            ("KnownLevel", source.name, 2),
            ("DuplicateLevel", source.name, 2),
            ("Orphan", "AbsentSource", 1),
        ):
            derivative = bpy.data.objects.new(name, source.data.copy())
            scene.collection.objects.link(derivative)
            derivative["framewright_role"] = "lod"
            derivative["framewright_source"] = source_name
            if level is not None:
                derivative["framewright_lod_level"] = level
            names.append(derivative.name)
        untagged = bpy.data.objects.new("LooksLike_LOD4", source.data)
        scene.collection.objects.link(untagged)
        report = assets.scene_resources({"scene_name": scene.name})["lod"]
        group = report["groups"][0]
        self.assertEqual(group["levels"], [2])
        self.assertEqual(group["duplicate_levels"], [2])
        self.assertEqual(group["metadata_coverage"], "incomplete_or_conflicting")
        self.assertIsNone(
            next(row for row in group["derivatives"] if row["object"] == names[0])["level"]
        )
        self.assertEqual(report["unresolved_derivatives"][0]["object"], names[3])
        self.assertIn(untagged.name, report["ungrouped_mesh_objects"])
        self.assertEqual(report["unknown_level_count"], 1)
        json.dumps(report, allow_nan=False)

    def test_16_collection_only_instance_sources_are_counted(self):
        scene, source = self.resource_fixture("InstancedOnly")
        collection = bpy.data.collections.new("InstanceOnlySourceCollection")
        collection.objects.link(source)
        scene.collection.objects.unlink(source)
        for index in range(3):
            instance = bpy.data.objects.new(f"OnlyInstance{index}", None)
            instance.instance_type = "COLLECTION"
            instance.instance_collection = collection
            scene.collection.objects.link(instance)
        report = assets.scene_resources({"scene_name": scene.name})
        self.assertEqual(report["mesh_objects"], 0)
        self.assertEqual(report["referenced_mesh_objects"], 1)
        self.assertEqual(report["unique_mesh_datablocks"], 1)
        self.assertEqual(report["source_triangles_unique"], 4)
        self.assertEqual(report["evaluated_triangles_objects"], 0)
        self.assertEqual(report["evaluated_triangles_with_instances"], 12)
        self.assertEqual(report["instance_occurrences"], 3)


def render_fixtures(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for builder, name, lighting in (
        (assets.build_prop, "WorkshopCabinet", "neutral"),
        (assets.build_facade, "PeriodFacade", "day"),
    ):
        asset = builder({"name": name, "dry_run": False})
        review = assets.setup_review_scene(
            {
                "name": name + "Review",
                "collection_name": asset["collection"],
                "lighting": lighting,
                "resolution": 512,
                "dry_run": False,
            }
        )
        scene = bpy.data.scenes[review["scene"]]
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 24
        scene.cycles.use_denoising = True
        scene.render.filepath = str((directory / (name + ".png")).resolve())
        bpy.ops.render.render(scene=scene.name, write_still=True)
        outputs.append({"asset": asset, "review": review, "render": scene.render.filepath})
    (directory / "fixtures.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-dir", type=Path)
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProductionAssetTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Production asset acceptance tests failed")
    if arguments.render_dir:
        render_fixtures(arguments.render_dir)
