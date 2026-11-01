"""Independent review regressions in isolated factory-startup Blender."""

import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy  # noqa: E402
from test_integration_review import bound_mutation_request  # noqa: E402

from framewright import baking, batch, blender_adapter, interchange, lod  # noqa: E402
from framewright.workflows import clear_run_cache  # noqa: E402


class ReleaseReviewTests(unittest.TestCase):
    def setUp(self):
        clear_run_cache()
        self.old_scene = bpy.context.window.scene
        self.before_ids = {
            kind: {item.as_pointer() for item in getattr(bpy.data, kind)}
            for kind in ("objects", "scenes", "collections", "meshes", "materials", "libraries")
        }
        self.scene = bpy.data.scenes.new("ReleaseReviewFixture")
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("ReviewSourceMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
            [],
            [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
        )
        self.source = bpy.data.objects.new("ReviewSource", mesh)
        self.scene.collection.objects.link(self.source)

    def tearDown(self):
        bpy.context.window.scene = self.old_scene
        for kind in ("objects", "scenes", "collections", "meshes", "materials", "libraries"):
            for item in list(getattr(bpy.data, kind)):
                if item.as_pointer() not in self.before_ids[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    @contextmanager
    def linked_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "fixture.blend")
            bpy.data.libraries.write(path, {self.source})
            with bpy.data.libraries.load(path, link=True) as (_, loaded):
                loaded.objects = [self.source.name]
            self.scene.collection.objects.link(loaded.objects[0])
            self.assertEqual(sum(obj.name == self.source.name for obj in self.scene.objects), 2)
            yield directory

    def test_legacy_repair_rejects_local_linked_name_ambiguity_without_edit(self):
        self.source.data.vertices.add(1)
        self.source.data.update()
        with self.linked_duplicate():
            before = (len(bpy.data.objects), len(bpy.data.meshes))
            original = [tuple(vertex.co) for vertex in self.source.data.vertices]
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                blender_adapter.apply_remove_loose_vertices(self.source.name)
            self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), before)
            self.assertEqual([tuple(vertex.co) for vertex in self.source.data.vertices], original)

    def test_export_rejects_local_linked_name_ambiguity(self):
        with self.linked_duplicate() as directory:
            before = (len(bpy.data.objects), len(bpy.data.meshes))
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                interchange.export_asset(
                    {"object_names": [self.source.name], "directory": directory}
                )
            self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), before)
            self.assertFalse((Path(directory) / "asset.glb").exists())

    def test_bake_rejects_local_linked_name_ambiguity(self):
        low_mesh = self.source.data.copy()
        low = bpy.data.objects.new("ReviewLow", low_mesh)
        self.scene.collection.objects.link(low)
        uv = low_mesh.uv_layers.new()
        for index, item in enumerate(uv.data):
            item.uv = (index % 2, index % 3)
        with self.linked_duplicate():
            before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.images))
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                baking.bake_normal({"high_object": self.source.name, "low_object": low.name})
            self.assertEqual(
                (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.images)), before
            )

    def test_batch_rejects_bound_mutation_without_save_before_execution(self):
        before = len(bpy.data.objects)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(bound_mutation_request()), encoding="utf-8")
            code = batch.main(["--request", str(request), "--output", str(root / "report.json")])
            self.assertEqual(code, 2)
            self.assertEqual(len(bpy.data.objects), before)
            self.assertFalse((root / "report.json").exists())

    def test_bound_mutation_persists_and_replay_does_not_duplicate(self):
        original = [tuple(vertex.co) for vertex in self.source.data.vertices]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(bound_mutation_request()), encoding="utf-8")
            code = batch.main(
                [
                    "--request",
                    str(request),
                    "--output",
                    str(root / "report.json"),
                    "--save-as",
                    str(root / "result.blend"),
                ]
            )
            self.assertEqual(code, 0)
            self.assertGreater((root / "result.blend").stat().st_size, 0)
            result = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(result["result"]["steps"][1]["response"]["result"]["dry_run"])
            count = len(bpy.data.objects)
            replay = batch.main(
                [
                    "--request",
                    str(request),
                    "--output",
                    str(root / "replay.json"),
                    "--save-as",
                    str(root / "replayed.blend"),
                ]
            )
            self.assertEqual(replay, 0)
            self.assertEqual(len(bpy.data.objects), count)
            self.assertTrue(
                json.loads((root / "replay.json").read_text(encoding="utf-8"))["result"]["replayed"]
            )
            self.assertEqual([tuple(vertex.co) for vertex in self.source.data.vertices], original)

    def test_lod_rejects_empty_mesh_instead_of_creating_empty_derivative(self):
        self.source.data.clear_geometry()
        with self.assertRaises(ValueError):
            lod.create_lod({"object_name": self.source.name, "dry_run": False})

    def test_surface_comparison_requires_candidate_surface(self):
        mesh = bpy.data.meshes.new("PointOnly")
        mesh.from_pydata([(0, 0, 0)], [], [])
        candidate = bpy.data.objects.new("PointOnly", mesh)
        self.scene.collection.objects.link(candidate)
        with self.assertRaises(ValueError):
            lod.compare_surface({"source_name": self.source.name, "candidate_name": candidate.name})

    def test_collision_link_failure_removes_owned_unlinked_object_and_mesh(self):
        before = (len(bpy.data.objects), len(bpy.data.meshes))

        class Links:
            def link(self, obj):
                raise RuntimeError("Fixture collection link rejected")

        context = SimpleNamespace(
            mode="OBJECT",
            scene=SimpleNamespace(
                objects=self.scene.objects, collection=SimpleNamespace(objects=Links())
            ),
            view_layer=bpy.context.view_layer,
            evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get,
        )
        with self.assertRaises(RuntimeError):
            lod.create_collision({"object_name": self.source.name, "dry_run": False}, context)
        self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseReviewTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Release review regressions failed")
    print(f"FRAMEWRIGHT_REVIEW_REGRESSIONS_OK tests={result.testsRun}")
