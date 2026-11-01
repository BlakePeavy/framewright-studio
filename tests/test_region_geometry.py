"""Metre-based triangle relations, sparse-marker blind spots and bounded traversal."""

import itertools
import math
import unittest

from framewright import region_geometry as geometry

TRIANGLE = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
PLATE = ((-1, -1, 0), (1, -1, 0), (0, 1, 0))
RIDGE = ((-0.1, 0, -0.1), (0.1, 0, -0.1), (0, 0, 0.1))


def translated(triangle, offset):
    return tuple(tuple(value + offset[axis] for axis, value in enumerate(p)) for p in triangle)


class TriangleRelationTests(unittest.TestCase):
    def test_thin_ridge_crosses_between_clear_region_vertices(self):
        result = geometry.triangle_relation(PLATE, RIDGE)
        self.assertEqual(result["relation"], "crossing")
        self.assertAlmostEqual(result["distance_m"], 0, places=12)

    def test_parallel_gap_and_threshold_categories(self):
        for gap, expected in ((0.002, "proximity"), (0.005, "proximity"), (0.02, "separated")):
            with self.subTest(gap=gap):
                result = geometry.triangle_relation(TRIANGLE, translated(TRIANGLE, (0, 0, gap)))
                self.assertEqual(result["relation"], expected)
                self.assertAlmostEqual(result["distance_m"], gap, places=12)

    def test_coplanar_overlap_has_own_category(self):
        self.assertEqual(
            geometry.triangle_relation(TRIANGLE, translated(TRIANGLE, (0.2, 0.2, 0)))["relation"],
            "coplanar_overlap",
        )

    def test_near_parallel_planes_within_epsilon_report_tolerance_coplanar_distance(self):
        result = geometry.triangle_relation(TRIANGLE, translated(TRIANGLE, (0, 0, 0.5e-6)))
        self.assertEqual(result["relation"], "coplanar_overlap")
        self.assertAlmostEqual(result["distance_m"], 0.5e-6, places=12)

    def test_coplanar_and_noncoplanar_vertex_edge_touches(self):
        for second in (
            ((1, 0, 0), (2, 0, 0), (1, -1, 0)),
            ((0, 0, 0), (1, 0, 0), (0.5, -1, 0)),
            ((0, 0, 0), (1, 0, 0), (0.5, 0, 1)),
            ((0.2, 0.2, 0), (0.2, 0.2, 1), (0.3, 0.2, 1)),
        ):
            with self.subTest(second=second):
                result = geometry.triangle_relation(TRIANGLE, second)
                self.assertEqual(result["relation"], "touch")
                self.assertAlmostEqual(result["distance_m"], 0, places=12)

    def test_overlapping_aabbs_do_not_invent_triangle_intersection(self):
        second = ((1, 1, 0), (1, 0.8, 0), (0.8, 1, 0))
        result = geometry.triangle_relation(TRIANGLE, second)
        self.assertEqual(result["relation"], "separated")
        self.assertAlmostEqual(result["distance_m"], 0.8 / math.sqrt(2), places=12)

    def test_plane_hit_near_triangle_corner_does_not_invent_crossing(self):
        for gap, expected in ((1.2e-6, "touch"), (2e-6, "proximity")):
            second = ((0.8 + gap, 0.2, 0), (1 + gap, 0.2, -0.1), (1 + gap, 0.2, 0.1))
            with self.subTest(gap=gap):
                result = geometry.triangle_relation(TRIANGLE, second)
                self.assertEqual(result["relation"], expected)
                self.assertAlmostEqual(result["distance_m"], gap / math.sqrt(2), places=11)

    def test_closest_points_can_both_lie_in_edge_interiors(self):
        first = ((-1, 0, 0), (1, 0, 0), (0, -1, -1))
        second = ((0, -1, 0.002), (0, 1, 0.002), (-1, 0, 1.002))
        result = geometry.triangle_relation(first, second)
        self.assertEqual(result["relation"], "proximity")
        self.assertAlmostEqual(result["distance_m"], 0.002, places=12)
        for actual, expected in zip(result["closest_first"], (0, 0, 0), strict=True):
            self.assertAlmostEqual(actual, expected, places=10)
        for actual, expected in zip(result["closest_second"], (0, 0, 0.002), strict=True):
            self.assertAlmostEqual(actual, expected, places=10)

    def test_all_vertex_permutations_and_argument_order_keep_relation(self):
        for first in itertools.permutations(PLATE):
            for second in itertools.permutations(RIDGE):
                self.assertEqual(geometry.triangle_relation(first, second)["relation"], "crossing")
                self.assertEqual(geometry.triangle_relation(second, first)["relation"], "crossing")

    def test_pair_local_origin_large_translation_and_unit_scaling(self):
        for scale in (0.001, 1, 100):
            gap = 0.002 * scale
            first = tuple(tuple(v * scale for v in p) for p in TRIANGLE)
            second = translated(first, (0, 0, gap))
            for offset in ((0, 0, 0), (1e6, -2e6, 3e6)):
                with self.subTest(scale=scale, offset=offset):
                    result = geometry.triangle_relation(
                        translated(first, offset),
                        translated(second, offset),
                        distance_epsilon_m=max(1e-9, 1e-6 * scale),
                        proximity_distance_m=0.005 * scale,
                    )
                    self.assertEqual(result["relation"], "proximity")
                    self.assertAlmostEqual(result["distance_m"], gap, delta=max(1e-9, gap * 1e-8))

    def test_thin_parallel_distance_permutations_and_rotations_compute_or_refuse(self):
        first = ((-500, 0, 0), (500, 0, 0), (0, -1e-5, 0))
        second = ((-500, -5e-6, 1e-6), (500, 5e-6, 1e-6), (0, 1e-5, 1e-6))
        for a in itertools.permutations(first):
            for b in itertools.permutations(second):
                result = geometry.triangle_relation(
                    a, b, distance_epsilon_m=1e-9, proximity_distance_m=1.05e-6
                )
                self.assertEqual(result["relation"], "proximity")
                self.assertAlmostEqual(result["distance_m"], 1e-6, delta=1e-9)

        def rotate(triangle, angle):
            c, s = math.cos(angle), math.sin(angle)
            return tuple(
                (c * x - s * y, c * (s * x + c * y) - s * z, s * (s * x + c * y) + c * z)
                for x, y, z in triangle
            )

        for angle in (0.2, 0.7, 1.1):
            for a, b in ((first, second), (second, first)):
                try:
                    result = geometry.triangle_relation(
                        rotate(a, angle),
                        rotate(b, angle),
                        distance_epsilon_m=1e-9,
                        proximity_distance_m=1.05e-6,
                    )
                except ValueError as error:
                    self.assertIn("numerical", str(error))
                else:
                    self.assertEqual(result["relation"], "proximity")
                    self.assertAlmostEqual(result["distance_m"], 1e-6, delta=1e-9)

    def test_degenerate_nonfinite_and_malformed_triangles_refuse(self):
        for first in (
            ((0, 0, 0), (1, 0, 0), (2, 0, 0)),
            ((0, 0, 0), (1, 0, 0), (1, 0.5e-6, 0)),
            ((0, 0, 0), (math.nan, 0, 0), (0, 1, 0)),
            ((0, 0, 0), (math.inf, 0, 0), (0, 1, 0)),
            ((True, 0, 0), (1, 0, 0), (0, 1, 0)),
            ((0, 0), (1, 0), (0, 1)),
            ((10**1000, 0, 0), (1, 0, 0), (0, 1, 0)),
        ):
            with self.subTest(first=first), self.assertRaises(ValueError):
                geometry.triangle_relation(first, TRIANGLE)

    def test_distance_tolerance_and_radius_bounds(self):
        for settings in (
            {"distance_epsilon_m": 0},
            {"distance_epsilon_m": 0.002},
            {"distance_epsilon_m": True},
            {"proximity_distance_m": math.nan},
            {"proximity_distance_m": 1.1},
            {"proximity_distance_m": 0.5e-6},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                geometry.triangle_relation(TRIANGLE, TRIANGLE, **settings)


class RegionalTraversalTests(unittest.TestCase):
    def test_relations_and_sparse_broad_phase_keep_complete_pair_counts(self):
        budget = geometry.PairBudget()
        result = geometry.compare_regions(
            [TRIANGLE, translated(TRIANGLE, (100, 0, 0))],
            [translated(TRIANGLE, (0, 0, 0.002)), translated(TRIANGLE, (200, 0, 0))],
            budget=budget,
        )
        self.assertEqual(result["counts"]["proximity"], 1)
        self.assertEqual(result["counts"]["separated"], 3)
        self.assertEqual(sum(result["counts"].values()), 4)
        self.assertEqual(budget.candidate_visits, 1)
        self.assertEqual(budget.narrow_checks, 1)
        self.assertAlmostEqual(result["minimum_distance_within_radius_m"], 0.002, places=12)
        self.assertFalse(result["containment_checked"])

    def test_candidate_limit_counts_before_other_axis_rejection(self):
        budget = geometry.PairBudget(max_candidate_visits=3, max_narrow_checks=100)
        with self.assertRaises(geometry.RegionBudgetExceeded):
            geometry.compare_regions(
                [TRIANGLE] * 5, [translated(TRIANGLE, (0, 5, 0))], budget=budget
            )
        self.assertEqual(budget.candidate_visits, 3)
        self.assertEqual(budget.narrow_checks, 0)

    def test_narrow_limit_and_interval_counters_are_cumulative(self):
        budget = geometry.PairBudget(max_candidate_visits=20, max_narrow_checks=2)
        geometry.compare_regions([TRIANGLE], [TRIANGLE], budget=budget)
        geometry.compare_regions([TRIANGLE], [TRIANGLE], budget=budget)
        with self.assertRaises(geometry.RegionBudgetExceeded):
            geometry.compare_regions([TRIANGLE], [TRIANGLE], budget=budget)
        self.assertEqual(budget.candidate_visits, 3)
        self.assertEqual(budget.narrow_checks, 2)

    def test_examples_are_bounded_and_have_input_mapping(self):
        result = geometry.compare_regions(
            [TRIANGLE] * 4, [TRIANGLE] * 3, budget=geometry.PairBudget(), max_examples=2
        )
        self.assertEqual(result["counts"]["coplanar_overlap"], 12)
        self.assertEqual(len(result["examples"]), 2)
        for example in result["examples"]:
            self.assertIn(example["first_index"], range(4))
            self.assertIn(example["second_index"], range(3))

    def test_all_geometry_validated_even_if_spatially_pruned(self):
        invalid = translated(((0, 0, 0), (1, 0, 0), (2, 0, 0)), (100, 100, 100))
        budget = geometry.PairBudget()
        with self.assertRaises(ValueError):
            geometry.compare_regions([TRIANGLE], [invalid], budget=budget)
        self.assertEqual(budget.candidate_visits, 0)

    def test_empty_inputs_and_invalid_work_limits_refuse(self):
        for first, second in (([], [TRIANGLE]), ([TRIANGLE], [])):
            with self.assertRaises(ValueError):
                geometry.compare_regions(first, second, budget=geometry.PairBudget())
        for values in (
            {"max_candidate_visits": 0},
            {"max_narrow_checks": True},
            {"max_candidate_visits": 50_000_001},
            {"max_narrow_checks": 10_000_001},
        ):
            with self.assertRaises(ValueError):
                geometry.PairBudget(**values)

    def test_rigid_motion_preserves_all_region_pair_relations(self):
        def move(triangle):
            return tuple((-p[1] + 4, p[0] - 2, p[2] + 7) for p in triangle)

        first = geometry.compare_regions([PLATE], [RIDGE], budget=geometry.PairBudget())
        moved = geometry.compare_regions([move(PLATE)], [move(RIDGE)], budget=geometry.PairBudget())
        self.assertEqual(first["counts"], moved["counts"])

    def test_boundary_only_analysis_does_not_claim_containment(self):
        corners = ((0, 0, 0), (3, 0, 0), (0, 3, 0), (0, 0, 3))
        outer = [
            tuple(corners[i] for i in face) for face in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
        ]
        inner = [((0.4, 0.4, 0.4), (0.5, 0.4, 0.4), (0.4, 0.5, 0.4))]
        result = geometry.compare_regions(inner, outer, budget=geometry.PairBudget())
        self.assertEqual(result["counts"]["separated"], 4)
        self.assertIsNone(result["minimum_distance_within_radius_m"])
        self.assertFalse(result["containment_checked"])
