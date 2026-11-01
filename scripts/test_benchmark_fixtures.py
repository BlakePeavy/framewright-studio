"""Verify the bounded rig/instance workload and separate OS/Python measurements."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy  # noqa: E402

from framewright import production_assets, rigging  # noqa: E402
from scripts.benchmark_performance import (  # noqa: E402
    clear_fixture,
    fixture_state,
    measure,
    rig_instance_scene,
)


class BenchmarkFixtureTests(unittest.TestCase):
    def test_rig_and_collection_instances_have_checked_workload_and_cleanup(self):
        before = fixture_state()
        original_scene = bpy.context.scene
        try:
            scene, skin, rig = rig_instance_scene()
            self.assertEqual(len(scene.objects), 102)
            self.assertEqual(len(rig.data.bones), 16)
            self.assertEqual(len(skin.data.vertices), 5166)
            self.assertTrue(
                all(
                    abs(sum(group.weight for group in vertex.groups) - 1) < 1e-6
                    for vertex in skin.data.vertices
                )
            )
            resources = production_assets.scene_resources({})
            self.assertEqual(resources["mesh_objects"], 1)
            self.assertEqual(resources["referenced_mesh_objects"], 2)
            self.assertEqual(resources["unique_mesh_datablocks"], 2)
            self.assertEqual(resources["source_triangles_unique"], 11_000)
            self.assertEqual(resources["instance_occurrences"], 100)
            self.assertEqual(resources["evaluated_triangles_with_instances"], 110_000)
            before_frame = (scene.frame_current, scene.frame_subframe)
            sampled = rigging.sample_deformation(
                {
                    "object_name": skin.name,
                    "frame_start": 1,
                    "frame_end": 25,
                    "step": 6,
                    "max_samples": 5,
                    "max_vertices": 6000,
                }
            )
            self.assertEqual(len(sampled["samples"]), 5)
            self.assertGreater(sampled["samples"][2]["max_edge_ratio"], 1.0001)
            self.assertEqual(before_frame, (scene.frame_current, scene.frame_subframe))
        finally:
            clear_fixture(before, original_scene)
        self.assertEqual(fixture_state(), before)
        self.assertIs(bpy.context.scene, original_scene)

    def test_measure_reports_distinct_python_allocations_and_native_process_counters(self):
        report = measure(lambda: bytearray(2 * 1024 * 1024), repeats=1)
        self.assertEqual(len(report["milliseconds"]), 1)
        self.assertGreaterEqual(report["python_peak_traced_bytes"], 2 * 1024 * 1024)
        self.assertTrue(report["memory_measurement_separate_from_timing"])
        for label in (
            "process_memory_before",
            "process_memory_after_timing",
            "process_memory_after_python_trace",
        ):
            memory = report[label]
            if memory["status"] == "measured":
                self.assertEqual(memory["process_id"], os.getpid())
                self.assertGreater(memory["working_set_bytes"], 0)
                self.assertGreaterEqual(
                    memory["peak_working_set_bytes"], memory["working_set_bytes"]
                )


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an isolated background Blender process")
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BenchmarkFixtureTests)
    )
    if not outcome.wasSuccessful():
        raise RuntimeError("Benchmark fixture acceptance tests failed")
