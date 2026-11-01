"""Independent broad-phase cutoff and thin-feature distance review."""

import math

import pytest

from framewright.region_geometry import PairBudget, compare_regions, triangle_relation


@pytest.mark.parametrize("axis", range(3))
@pytest.mark.parametrize("direction", (-1, 1))
def test_sweep_and_metric_share_the_same_representational_radius_boundary(axis, direction):
    points = [[0.0, 0.0, 0.0] for _ in range(3)]
    other = [index for index in range(3) if index != axis]
    points[1][other[0]], points[2][other[1]] = 1.0, 1.0
    radius = 0.005
    for steps in (0, 1, 8, 12):
        distance = radius
        for _ in range(steps):
            distance = math.nextafter(distance, math.inf)
        shifted = [point.copy() for point in points]
        for point in shifted:
            point[axis] = direction * distance
        direct = triangle_relation(points, shifted, proximity_distance_m=radius)
        swept = compare_regions(
            [points], [shifted], budget=PairBudget(), proximity_distance_m=radius
        )
        assert swept["counts"][direct["relation"]] == 1, (axis, direction, steps, direct, swept)


def test_parallel_thin_triangles_never_report_false_clearance_above_proven_plane_distance():
    # Projected triangles overlap: (-100, -0.5e-6) lies in both. Their parallel
    # planes supply an exact 1e-6 m lower bound and that witness attains it.
    first = [(-500.0, 0.0, 0.0), (500.0, 0.0, 0.0), (0.0, -1e-5, 0.0)]
    second = [(-500.0, -5e-6, 1e-6), (500.0, 5e-6, 1e-6), (0.0, 1e-5, 1e-6)]
    try:
        result = triangle_relation(
            first, second, distance_epsilon_m=1e-9, proximity_distance_m=1.05e-6
        )
    except ValueError as error:
        # Refusal is safe if numerical conditioning is explicitly unsupported.
        assert any(word in str(error).lower() for word in ("numerical", "aspect", "conditioning"))
    else:
        assert result["relation"] == "proximity", result
        assert result["distance_m"] == pytest.approx(1e-6, abs=1e-9), result


def test_angular_cutoff_cannot_hide_a_resolved_nonzero_intersection_segment():
    # Same XY footprint, second plane z=1e-13*x. Both triangles straddle the
    # other's plane by 100*epsilon and meet along a one-million-metre segment.
    first = [(-1e6, 0.0, 0.0), (1e6, 0.0, 0.0), (0.0, 1e6, 0.0)]
    second = [(-1e6, 0.0, -1e-7), (1e6, 0.0, 1e-7), (0.0, 1e6, 0.0)]
    try:
        result = triangle_relation(
            first, second, distance_epsilon_m=1e-9, proximity_distance_m=1e-6
        )
    except ValueError as error:
        assert any(word in str(error).lower() for word in ("numerical", "angular", "conditioning"))
    else:
        assert result["relation"] == "crossing", result
        assert result["distance_m"] == pytest.approx(0.0, abs=1e-9), result
