"""Pure request validation for isolated evaluated-skin contacts."""

import unittest

from framewright import skin_contacts


def request(**changes):
    return {
        "surface_name": "Ground",
        "markers": [{"id": "heel", "object_name": "Skin", "vertex_indices": [0], "weights": [1]}],
        "frame_start": 1,
        "frame_end": 3,
        **changes,
    }


class SkinContactRequestTests(unittest.TestCase):
    def test_full_integer_and_fractional_interval_is_explicit(self):
        rigid, times, maximum = skin_contacts._request(request(substeps=2))
        self.assertEqual(times, [1, 1.5, 2, 2.5, 3])
        self.assertEqual(maximum, 250000)
        self.assertEqual(rigid["markers"][0]["position"], [0, 0, 0])

    def test_vertex_and_actual_triangle_barycentric_requests(self):
        markers = [
            {"id": "heel", "object_name": "Skin", "vertex_indices": [0], "weights": [1]},
            {
                "id": "ball",
                "object_name": "Skin",
                "vertex_indices": [1, 2, 3],
                "weights": [0.2, 0.3, 0.5],
            },
        ]
        skin_contacts._request(request(markers=markers))

    def test_invalid_marker_shapes_fail_before_blender(self):
        base = request()["markers"][0]
        for changes in (
            {"vertex_indices": []},
            {"vertex_indices": [0, 1], "weights": [0.5, 0.5]},
            {"vertex_indices": [0, 0, 1], "weights": [0.2, 0.3, 0.5]},
            {"vertex_indices": [True]},
            {"vertex_indices": [-1]},
            {"vertex_indices": [1000000]},
            {"weights": [True]},
            {"weights": [0.999]},
            {"weights": [float("nan")]},
            {"weights": [1, 0, 0]},
            {"position": [0, 0, 0]},
            {"id": "a.b"},
            {"bone": "Foot"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                skin_contacts.inspect_skin_contacts(request(markers=[{**base, **changes}]))

    def test_unknown_fields_and_sampling_skip_are_rejected(self):
        for changes in ({"step": 2}, {"python": "x"}, {"frame_end": 0}, {"substeps": 9}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                skin_contacts.inspect_skin_contacts(request(**changes))

    def test_bounds_do_not_silently_truncate(self):
        for changes in (
            {"frame_end": 1000},
            {"max_evaluated_vertices": 0},
            {"max_evaluated_vertices": 1000001},
            {"max_evaluated_vertices": True},
            {"markers": request()["markers"] * 2},
            {"search_distance": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                skin_contacts.inspect_skin_contacts(request(**changes))

    def test_registry_marks_command_read_only(self):
        from framewright.commands import (
            COMMANDS,
            command_mutates,
            needs_scene_save,
            validate_params,
        )

        params = request()
        self.assertEqual(COMMANDS["animation.skin_contacts"]["module"], "skin_contacts")
        validate_params("animation.skin_contacts", params)
        self.assertFalse(command_mutates("animation.skin_contacts"))
        self.assertFalse(needs_scene_save({"command": "animation.skin_contacts", "params": params}))

    def test_native_rigify_target_weights_stay_inside_owner_but_id_hops_reject(self):
        class NumericOwner:
            def path_resolve(self, path):
                return 1.0

        owner = NumericOwner()
        skin_contacts._numeric_path(owner, 'bones["DEF-arm"].bbone_easeout')
        skin_contacts._numeric_path(
            owner, 'pose.bones["MCH-parent"].constraints["SWITCH_PARENT"].targets[0].weight'
        )
        for path in (
            '["foreign_light"].energy',
            'constraints["Copy"].target.location',
            'pose.bones["MCH-parent"].constraints["SWITCH_PARENT"].targets[0].target.location',
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                skin_contacts._numeric_path(owner, path)

    def test_numeric_custom_enum_uses_stored_value_not_rna_display_identifier(self):
        class EnumOwner:
            def path_resolve(self, path):
                return "P1"

            def __getitem__(self, name):
                return 1

        skin_contacts._numeric_path(EnumOwner(), '["parent_switch"]')


if __name__ == "__main__":
    unittest.main()
