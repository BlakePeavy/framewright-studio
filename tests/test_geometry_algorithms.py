"""Geometry edge cases specified before the diagnostic implementation."""

import math

import pytest

from framewright.mesh_diagnostics import (
    scan_intersections,
    triangle_overlap_2d,
    triangles_intersect_3d,
)


def test_uv_overlap_accepts_winding_and_containment():
    outer = ((0, 0), (2, 0), (0, 2))
    inner = ((0.1, 0.1), (0.1, 0.5), (0.5, 0.1))
    assert triangle_overlap_2d(outer, inner)
    assert triangle_overlap_2d(outer, tuple(reversed(outer)))


@pytest.mark.parametrize(
    "other",
    [((1, 0), (1, 1), (0, 1)), ((2, 2), (3, 2), (2, 3)), ((1, 0), (2, 0), (1, -1))],
)
def test_uv_shared_edge_point_and_disjoint_are_not_overlap(other):
    assert not triangle_overlap_2d(((0, 0), (1, 0), (0, 1)), other)


def test_uv_udim_coordinates_do_not_wrap():
    assert not triangle_overlap_2d(((0, 0), (1, 0), (0, 1)), ((1, 0), (2, 0), (1, 1)))


def test_degenerate_uv_is_not_area_overlap():
    assert not triangle_overlap_2d(((0, 0), (0, 0), (0, 0)), ((0, 0), (1, 0), (0, 1)))


def test_nonfinite_geometry_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        triangle_overlap_2d(((math.nan, 0), (1, 0), (0, 1)), ((0, 0), (1, 0), (0, 1)))


def test_3d_coplanar_overlap_and_disjoint():
    first = ((0, 0, 0), (2, 0, 0), (0, 2, 0))
    assert triangles_intersect_3d(first, ((0.2, 0.2, 0), (1, 0.2, 0), (0.2, 1, 0)))
    assert not triangles_intersect_3d(first, ((3, 0, 0), (4, 0, 0), (3, 1, 0)))
    assert not triangles_intersect_3d(first, ((0, 0, 1), (2, 0, 1), (0, 2, 1)))


def test_3d_crossing_and_point_contact():
    first = ((0, 0, 0), (2, 0, 0), (0, 2, 0))
    assert triangles_intersect_3d(first, ((0.5, 0.5, -1), (0.5, 0.5, 1), (1, 0.5, 0)))
    assert not triangles_intersect_3d(first, ((2, 0, 0), (3, 0, 1), (3, 1, 1)))


def test_3d_degenerate_face_is_skipped():
    assert not triangles_intersect_3d(
        ((0, 0, 0), (0, 0, 0), (0, 0, 0)), ((0, 0, 0), (1, 0, 0), (0, 1, 0))
    )


def test_small_uv_triangle_is_translation_invariant():
    base = ((0, 0), (0.001, 0), (0, 0.001))
    translated = tuple((x + 100_000_000, y + 100_000_000) for x, y in base)
    assert triangle_overlap_2d(translated, translated)


def test_scan_excludes_same_face_and_true_shared_edge():
    triangles = [
        ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        ((1, 0, 0), (0, 0, 0), (0, 0, 1)),
    ]
    report = scan_intersections(triangles, vertex_ids=[(0, 1, 2), (1, 0, 3)])
    assert report["pairs"] == []
    assert report["coverage"] == "complete"
    report = scan_intersections([triangles[0], triangles[0]], face_ids=[0, 0])
    assert report["pairs"] == []


def test_scan_does_not_hide_folded_coplanar_adjacent_overlap():
    triangles = [
        ((0, 0, 0), (2, 0, 0), (0, 2, 0)),
        ((0, 0, 0), (2, 0, 0), (0.5, 0.5, 0)),
    ]
    report = scan_intersections(triangles, vertex_ids=[(0, 1, 2), (0, 1, 3)])
    assert report["pairs"] == [[0, 1]]


def test_scan_reports_triangle_and_pair_limits():
    triangle = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
    report = scan_intersections([triangle] * 4, max_pairs=1)
    assert report["coverage"] == "partial"
    assert report["pairs_considered"] == 1
    assert report["pair_limit_reached"]
    report = scan_intersections([triangle] * 4, max_triangles=2)
    assert report["coverage"] == "partial"
    assert report["triangles_tested"] == 2
    assert report["triangles_omitted"] == 2


def test_scan_bounds_are_validated():
    with pytest.raises(ValueError):
        scan_intersections([], max_pairs=True)
    with pytest.raises(ValueError):
        scan_intersections([], max_triangles=0)


def test_uv_scan_shared_edges_are_clean():
    triangles = [((0, 0), (1, 0), (0, 1)), ((1, 0), (1, 1), (0, 1))]
    assert scan_intersections(triangles, dimensions=2)["pairs"] == []
