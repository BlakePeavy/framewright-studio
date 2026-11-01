"""Pure bounded contact-sampling request contracts."""

import unittest

from framewright import contact_analysis


def request(**changes):
    return {
        "surface_name": "Ground",
        "markers": [{"id": "heel", "object_name": "Sole", "position": [0, 0, 0]}],
        "frame_start": 1,
        "frame_end": 3,
        **changes,
    }


class ContactRequestTests(unittest.TestCase):
    def test_integer_and_subframe_coverage_include_requested_end(self):
        self.assertEqual(contact_analysis.sample_times(request()), [1.0, 2.0, 3.0])
        self.assertEqual(
            contact_analysis.sample_times(request(substeps=2)), [1.0, 1.5, 2.0, 2.5, 3.0]
        )
        self.assertEqual(
            contact_analysis.sample_times(request(frame_end=4, step=2)), [1.0, 3.0, 4.0]
        )

    def test_oversized_range_rejects_without_silent_truncation(self):
        with self.assertRaisesRegex(ValueError, "max_samples"):
            contact_analysis.sample_times(request(frame_end=1000))
        with self.assertRaisesRegex(ValueError, "max_samples"):
            contact_analysis.sample_times(request(frame_end=4, step=2, max_samples=2))

    def test_sampling_types_and_reversed_ranges_reject(self):
        for changes in (
            {"frame_start": True},
            {"frame_end": 0},
            {"step": 0},
            {"substeps": 9},
            {"max_samples": 4097},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                contact_analysis.sample_times(request(**changes))

    def test_single_frame_is_one_sample(self):
        self.assertEqual(
            contact_analysis.sample_times(request(frame_start=-2, frame_end=-2, substeps=4)), [-2.0]
        )

    def test_marker_identity_offsets_and_unknown_fields_reject_before_blender(self):
        for markers in (
            [],
            [{"id": "x", "object_name": "Sole", "position": [0, 0]}],
            [{"id": "x", "object_name": "Sole", "position": [0, float("nan"), 0]}],
            [{"id": "x", "object_name": "Sole", "position": [0, 0, 0], "python": "x"}],
            [{"id": "x", "object_name": "Sole", "position": [0, 0, 0]}] * 2,
        ):
            with self.subTest(markers=markers), self.assertRaises(ValueError):
                contact_analysis.inspect_surface_contacts(request(markers=markers))

    def test_projection_tolerances_must_fit_search_distance(self):
        for changes in (
            {"contact_tolerance": 1},
            {"penetration_tolerance": 1},
            {"search_distance": 0},
            {"minimum_up_dot": -1},
            {"sliding_speed": True},
            {"max_surface_triangles": 0},
            {"unknown": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                contact_analysis.inspect_surface_contacts(request(**changes))

    def test_public_numeric_and_name_limits_match_parser(self):
        marker = {
            "id": "x" * 128,
            "object_name": "n" * 1024,
            "bone": "b" * 1024,
            "position": [0, 0, 0],
        }
        times, settings = contact_analysis._request(
            request(
                surface_name="s" * 1024,
                markers=[marker],
                search_distance=1_000_000,
                contact_tolerance=1_000_000,
                penetration_tolerance=1_000_000,
            )
        )
        self.assertEqual(times, [1.0, 2.0, 3.0])
        self.assertEqual(settings["search_distance"], 1_000_000)
        _, tiny = contact_analysis._request(
            request(search_distance=0.000001, contact_tolerance=0, penetration_tolerance=0)
        )
        self.assertEqual(tiny["search_distance"], 0.000001)


if __name__ == "__main__":
    unittest.main()
