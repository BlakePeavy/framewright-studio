"""Actual repair-candidate evaluation in isolated background Blender only."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright.blender_adapter import capture_scene  # noqa: E402
from framewright.blender_transactions import source_fingerprint  # noqa: E402
from framewright.core import PROFILES, validate_scene  # noqa: E402
from framewright.providers import FileReplayProvider, SuppliedPlanProvider, rank_candidates  # noqa: E402
from framewright.workflows import clear_run_cache, run_workflow  # noqa: E402


class RepairEvaluationTests(unittest.TestCase):
    def setUp(self):
        clear_run_cache()
        self.previous_scene = bpy.context.window.scene
        self.created_before = {
            kind: {item.session_uid for item in getattr(bpy.data, kind)}
            for kind in ("objects", "meshes", "materials", "scenes")
        }
        self.scene = bpy.data.scenes.new("EvaluationFixture")
        self.scene.unit_settings.system = "METRIC"
        bpy.context.window.scene = self.scene
        mesh = bpy.data.meshes.new("EvaluationMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (4, 4, 4)],
            [],
            [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
        )
        mesh.uv_layers.new()
        mesh.materials.append(bpy.data.materials.new("EvaluationMaterial"))
        self.source = bpy.data.objects.new("EvaluationSource", mesh)
        self.scene.collection.objects.link(self.source)
        replay = FileReplayProvider(ROOT / "benchmarks" / "evaluation-repair-plans.json")
        self.candidates = {
            name: SuppliedPlanProvider({"fixture": replay.plan({"id": name})})
            for name in ("inspect", "repair")
        }
        self.cases = [
            {
                "id": "fixture",
                "expected_status": "completed",
                "expected_rule_ids": [],
                "require_preservation": True,
            }
        ]

    def tearDown(self):
        bpy.context.window.scene = self.previous_scene
        for kind in ("objects", "scenes", "meshes", "materials"):
            for item in list(getattr(bpy.data, kind)):
                if item.session_uid not in self.created_before[kind]:
                    getattr(bpy.data, kind).remove(item, do_unlink=True)

    def probe(self, case):
        return source_fingerprint(self.source)

    def run_candidate(self, workflow):
        result = run_workflow(workflow)
        name = self.source.name
        for step in result["steps"]:
            if step["response"].get("ok"):
                name = step["response"]["result"].get("derivative", name)
        snapshot = capture_scene()
        focused = replace(
            snapshot, objects=tuple(obj for obj in snapshot.objects if obj.name == name)
        )
        result["diagnostic_evidence"] = validate_scene(focused, PROFILES["studio_static"]).to_dict()
        return result

    def test_actual_repair_outranks_inspection_that_leaves_defect(self):
        before = self.probe({})
        report = rank_candidates(
            self.candidates,
            self.cases,
            self.run_candidate,
            source_probe=self.probe,
            allow_mutation=True,
        )
        self.assertEqual(
            [item["candidate_id"] for item in report["ranking"]], ["repair", "inspect"]
        )
        self.assertTrue(report["ranking"][0]["eligible"])
        self.assertFalse(report["ranking"][1]["eligible"])
        self.assertEqual(report["reports"]["repair"]["cases"][0]["rule_ids"], [])
        self.assertEqual(report["reports"]["inspect"]["cases"][0]["rule_ids"], ["LOOSE_VERTICES"])
        self.assertEqual(before, self.probe({}))
        self.assertEqual(len(self.source.data.vertices), 5)
        derivatives = [obj for obj in self.scene.objects if obj != self.source]
        self.assertEqual(len(derivatives), 1)
        self.assertEqual(len(derivatives[0].data.vertices), 4)
        self.assertTrue(derivatives[0].hide_render)
        self.assertIsNone(report["ranking"][0]["reported_cost"])
        self.assertEqual(report["artist_approval"], "not_evaluated")

    def test_unauthorized_repair_never_creates_a_derivative(self):
        report = rank_candidates(
            {"repair": self.candidates["repair"]},
            self.cases,
            self.run_candidate,
            source_probe=self.probe,
        )
        self.assertFalse(report["ranking"][0]["eligible"])
        self.assertIn("allow_mutation", report["reports"]["repair"]["cases"][0]["failures"][0])
        self.assertEqual(list(self.scene.objects), [self.source])

    def test_source_damage_disqualifies_an_otherwise_clean_derivative(self):
        original = self.source.data.vertices[0].co.copy()

        def contaminated_runner(workflow):
            result = self.run_candidate(workflow)
            self.source.data.vertices[0].co.x += 0.5
            self.source.data.update()
            return result

        try:
            report = rank_candidates(
                {"repair": self.candidates["repair"]},
                self.cases,
                contaminated_runner,
                source_probe=self.probe,
                allow_mutation=True,
            )
            self.assertEqual(report["reports"]["repair"]["cases"][0]["rule_ids"], [])
            self.assertFalse(report["ranking"][0]["source_preserved"])
            self.assertFalse(report["ranking"][0]["eligible"])
        finally:
            self.source.data.vertices[0].co = original
            self.source.data.update()


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an owned background Blender process")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RepairEvaluationTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Repair evaluation acceptance failed")
    print(f"FRAMEWRIGHT_EVALUATION_OK tests={result.testsRun}")
