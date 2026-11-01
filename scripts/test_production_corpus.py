"""Real Blender corpus worker, quality controls, isolation and preservation checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from scripts import benchmark_production_corpus as corpus  # noqa: E402


class ProductionCorpusTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.inventory = {
            kind: {obj.session_uid for obj in getattr(bpy.data, kind)}
            for kind in ("objects", "scenes", "meshes", "materials", "images")
        }
        self.scene = bpy.data.scenes.new("CorpusFixture")
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("CorpusTriangle")
        mesh.from_pydata([(0, 0, 0.002), (1, 0, 0.002), (0, 1, 0.002)], [], [(0, 1, 2)])
        mesh.uv_layers.new(name="UVMap")
        for loop, value in zip(mesh.uv_layers.active.data, [(0, 0), (1, 0), (0, 1)], strict=True):
            loop.uv = value
        self.subject = bpy.data.objects.new("Subject", mesh)
        self.scene.collection.objects.link(self.subject)

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for kind, old in self.inventory.items():
            for obj in list(getattr(bpy.data, kind)):
                if obj.session_uid not in old:
                    getattr(bpy.data, kind).remove(obj, do_unlink=True)

    def fixture(self):
        return {
            "id": "triangle",
            "version": 1,
            "scene": self.scene.name,
            "objects": [self.subject.name],
            "scene_objects": sorted(obj.name for obj in self.scene.objects),
            "dependencies": [],
        }

    def operation(self):
        return {
            "id": "surface",
            "requests": [
                {
                    "command": "surfaces.inspect",
                    "params": {
                        "object_name": self.subject.name,
                        "max_triangles": 10,
                        "max_pairs": 10,
                    },
                }
            ],
            "expectations": [
                {"path": "/responses/0/result/uv/layer", "op": "eq", "value": "UVMap"}
            ],
            "control": {
                "kind": "remove_uvs",
                "request_index": 0,
                "expectations": [
                    {"path": "/ok", "op": "eq", "value": True},
                    {"path": "/result/findings", "op": "rule", "value": "UV_MISSING"},
                ],
            },
        }

    def test_missing_uv_quality_control_uses_owned_copy_and_preserves_source(self):
        before = corpus.source_state(self.scene, [self.subject])
        result = corpus.run_loaded_operation(self.fixture(), self.operation())
        self.assertTrue(result["source_state_preserved"])
        self.assertTrue(result["control"]["expectations_met"])
        self.assertEqual(corpus.source_state(self.scene, [self.subject]), before)
        self.assertEqual(result["memory_after"]["status"], "measured")
        self.assertGreater(result["memory_after"]["peak_working_set_bytes"], 0)
        self.assertGreaterEqual(result["command_seconds"], 0)

    def test_control_failure_cleans_only_owned_geometry(self):
        before = corpus.source_state(self.scene, [self.subject])
        with patch.object(
            corpus, "_dispatch", side_effect=RuntimeError("injected control failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                corpus.run_control(self.operation(), self.scene)
        self.assertEqual(corpus.source_state(self.scene, [self.subject]), before)

    def test_quality_control_rejects_a_false_unchanged_response(self):
        operation = self.operation()
        baseline = corpus._dispatch(operation["requests"][0], "baseline-control")
        before = corpus.source_state(self.scene, [self.subject])
        with patch.object(corpus, "_dispatch", return_value=baseline):
            with self.assertRaisesRegex(AssertionError, "observation"):
                corpus.run_control(operation, self.scene)
        self.assertEqual(corpus.source_state(self.scene, [self.subject]), before)

    def test_source_fingerprint_rejects_an_injected_original_geometry_edit(self):
        actual_dispatch = corpus._dispatch

        def changed_source(request, request_id):
            response = actual_dispatch(request, request_id)
            self.subject.data.vertices[0].co.x += 0.25
            return response

        with patch.object(corpus, "_dispatch", side_effect=changed_source):
            with self.assertRaisesRegex(AssertionError, "protected authored source"):
                corpus.run_loaded_operation(self.fixture(), self.operation())

    def test_source_subject_or_scene_scope_mismatch_fails(self):
        fixture = self.fixture()
        fixture["scene_objects"].append("Absent")
        with self.assertRaisesRegex(ValueError, "object set"):
            corpus.run_loaded_operation(fixture, self.operation())

    def test_sample_budget_control_reports_expected_public_api_failure(self):
        operation = {
            "requests": [
                {
                    "command": "animation.skin_contacts",
                    "params": {
                        "surface_name": "DeclaredGround",
                        "markers": [
                            {
                                "id": "sole",
                                "object_name": self.subject.name,
                                "vertex_indices": [0],
                                "weights": [1],
                            }
                        ],
                        "frame_start": 1,
                        "frame_end": 3,
                    },
                }
            ],
            "control": {
                "kind": "sample_budget",
                "request_index": 0,
                "expectations": [{"path": "/ok", "op": "eq", "value": False}],
            },
        }
        before = corpus.source_state(self.scene, [self.subject])
        result = corpus.run_control(operation, self.scene)
        self.assertIn("max_samples", result["response"]["error"]["message"])
        self.assertEqual(corpus.source_state(self.scene, [self.subject]), before)

    def test_raised_surface_reveals_penetration_without_editing_source(self):
        mesh = bpy.data.meshes.new("GroundMesh")
        mesh.from_pydata(
            [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)], [], [(0, 1, 2), (0, 2, 3)]
        )
        ground = bpy.data.objects.new("Ground", mesh)
        self.scene.collection.objects.link(ground)
        fixture = self.fixture()
        fixture["objects"].append(ground.name)
        operation = {
            "id": "contacts",
            "requests": [
                {
                    "command": "animation.skin_contacts",
                    "params": {
                        "surface_name": ground.name,
                        "markers": [
                            {
                                "id": "sole",
                                "object_name": self.subject.name,
                                "vertex_indices": [0],
                                "weights": [1],
                            }
                        ],
                        "frame_start": 1,
                        "frame_end": 3,
                    },
                }
            ],
            "expectations": [
                {"path": "/responses/0/result/penetration_samples", "op": "eq", "value": 0}
            ],
            "control": {
                "kind": "raised_surface",
                "request_index": 0,
                "expectations": [
                    {"path": "/ok", "op": "eq", "value": True},
                    {"path": "/result/penetration_samples", "op": "gte", "value": 1},
                ],
            },
        }
        result = corpus.run_loaded_operation(fixture, operation)
        self.assertEqual(result["control"]["response"]["result"]["penetration_samples"], 3)

    def test_independent_cold_worker_uses_temporary_user_directories_and_exact_files(self):
        with tempfile.TemporaryDirectory(prefix="framewright-corpus-test-") as temporary:
            root = Path(temporary)
            folder = root / "artifacts" / "fixture"
            folder.mkdir(parents=True)
            source = folder / "fixture.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(source), copy=True)
            fixture = self.fixture()
            fixture.update(
                source={
                    "path": source.relative_to(root).as_posix(),
                    "sha256": corpus.digest(source),
                    "bytes": source.stat().st_size,
                },
                receipts=[],
                operations=[self.operation()],
                provenance={"artist_accepted": False, "native_verified": False},
            )
            manifest = {
                "schema_version": "1.0",
                "corpus_id": "fixture-corpus",
                "corpus_version": 1,
                "fixtures": [fixture],
            }
            manifest_path = root / "manifest.json"
            corpus.write_new(manifest_path, manifest)
            output = root / "result.json"
            env = os.environ.copy()
            for name in corpus.USER_DIRS:
                path = root / name
                path.mkdir()
                env[name] = str(path)
            command = [
                bpy.app.binary_path,
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--offline-mode",
                "--python-exit-code",
                "1",
                "--python",
                str(ROOT / "scripts/benchmark_production_corpus.py"),
                "--",
                "--worker",
                "--root",
                str(root),
                "--manifest",
                str(manifest_path),
                "--fixture",
                fixture["id"],
                "--operation",
                "surface",
                "--worker-output",
                str(output),
            ]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = json.loads(output.read_text())
            self.assertTrue(receipt["source_files_preserved"])
            self.assertFalse(receipt["blender"]["autoexec_enabled"])
            self.assertNotEqual(receipt["memory_after"]["process_id"], os.getpid())
            self.assertEqual(corpus.digest(source), fixture["source"]["sha256"])
            self.assertEqual(receipt["manifest_sha256"], corpus.digest(manifest_path))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProductionCorpusTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
