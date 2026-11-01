"""Public morph-bake schema rejects invalid requests before Blender imports."""

import unittest
from unittest.mock import patch

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params


class ShapeBakeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.params = dict(
            object_name="Skin",
            armature_name="Rig",
            baked_armature_name="Baked",
            shape_keys=["Corrective"],
            frame_start=1,
            frame_end=49,
        )

    def test_declares_preview_default_and_scene_effect(self):
        entry = next(
            row for row in command_metadata() if row["name"] == "animation.bake_shape_keys"
        )
        self.assertEqual(entry["effect"], "scene")
        self.assertTrue(entry["mutates"])
        self.assertTrue(entry["input_schema"]["properties"]["dry_run"]["default"])
        validate_params("animation.bake_shape_keys", self.params)

    def test_rejects_unbounded_or_invalid_inputs_before_import(self):
        for changes in (
            {"shape_keys": []},
            {"shape_keys": ["x"] * 33},
            {"max_samples": 257},
            {"max_interpolation_error": float("nan")},
            {"max_interpolation_error": -1},
            {"frame_start": 1.5},
            {"step": 2},
            {"dry_run": 1},
        ):
            with (
                self.subTest(changes=changes),
                patch("framewright.commands.import_module") as loader,
            ):
                response = dispatch(
                    dict(
                        schema_version="1.0",
                        request_id="morph-invalid",
                        command="animation.bake_shape_keys",
                        params={**self.params, **changes},
                    )
                )
                self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
                loader.assert_not_called()

    def test_dispatches_only_registered_handler(self):
        with patch("framewright.commands.import_module") as loader:
            loader.return_value.bake_shape_keys.return_value = {"dry_run": True}
            result = dispatch(
                dict(
                    schema_version="1.0",
                    request_id="morph-route",
                    command="animation.bake_shape_keys",
                    params=self.params,
                )
            )
            self.assertTrue(result["ok"])
            loader.assert_called_once_with(".shape_baking", "framewright")
            loader.return_value.bake_shape_keys.assert_called_once_with(self.params)
