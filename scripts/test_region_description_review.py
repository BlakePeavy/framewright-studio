"""Independent real-Blender admission ordering and empty-dependency boundary checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from test_region_description import RegionDescriptionTests, describe  # noqa: E402

from framewright import region_description, skin_contacts  # noqa: E402


class RegionDescriptionReviewTests(unittest.TestCase):
    setUp = RegionDescriptionTests.setUp
    tearDown = RegionDescriptionTests.tearDown
    inventory = staticmethod(RegionDescriptionTests.inventory)
    mesh = RegionDescriptionTests.mesh
    state = RegionDescriptionTests.state
    params = RegionDescriptionTests.params
    group_params = RegionDescriptionTests.group_params
    group = RegionDescriptionTests.group

    def test_known_all_dependency_triangle_excess_refuses_before_owned_copy(self):
        dependency = self.mesh(
            "BaseTriangleDependency", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
        )
        self.skin.constraints.new("COPY_LOCATION").target = dependency
        before = self.state()
        with patch.object(
            skin_contacts, "_isolated_scene", wraps=skin_contacts._isolated_scene
        ) as copying:
            with self.assertRaisesRegex(ValueError, "triangle.*budget|budget.*triangle"):
                describe(self.params(max_evaluated_triangles=2))
            self.assertEqual(self.state(), before)
            copying.assert_not_called()

    def test_evaluated_triangle_excess_refuses_before_group_extraction(self):
        self.group()
        self.skin.modifiers.new("NativeSubdivision", "SUBSURF").levels = 1
        before = self.state()
        original = region_description._group_extractor
        observed = []

        def instrumented_factory(*args, **kwargs):
            extract = original(*args, **kwargs)

            def extraction(evaluated, mesh):
                observed.append((len(mesh.vertices), len(mesh.loop_triangles)))
                return extract(evaluated, mesh)

            return extraction

        with patch.object(region_description, "_group_extractor", side_effect=instrumented_factory):
            with self.assertRaisesRegex(ValueError, "triangle.*budget|budget.*triangle"):
                describe(self.group_params(max_evaluated_triangles=3))
        self.assertEqual(self.state(), before)
        self.assertEqual(observed, [], "Over-budget evaluated geometry reached group extraction")

    def test_empty_unselected_mesh_dependency_does_not_become_fake_surface(self):
        dependency = self.mesh("EmptyTransformDependency", [], [])
        self.skin.constraints.new("COPY_LOCATION").target = dependency
        before = self.state()
        result = describe(self.params(max_evaluated_triangles=2))
        entries = {item["object_name"]: item for item in result["dependency_geometry"]}
        self.assertEqual(entries[dependency.name]["evaluated_triangles"], 0)
        self.assertEqual(entries[dependency.name]["evaluated_vertices"], 0)
        self.assertEqual(result["evaluated_triangles_all_dependencies"], 2)
        self.assertEqual(result["selected_triangle_count"], 1)
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RegionDescriptionReviewTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
