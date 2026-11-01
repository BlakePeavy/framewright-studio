"""Explicit scalar-clipping consent remains discoverable and type checked."""

import unittest
from unittest.mock import patch

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params


class ScalarClampSchemaTests(unittest.TestCase):
    def test_clipping_is_false_by_default_and_true_is_validated(self):
        entry = next(row for row in command_metadata() if row["name"] == "asset.export")
        self.assertFalse(entry["input_schema"]["properties"]["clamp_scalar_textures"]["default"])
        validate_params(
            "asset.export",
            dict(
                object_names=["Skin"],
                directory="C:/Export",
                format="FBX",
                clamp_scalar_textures=True,
            ),
        )

    def test_nonboolean_clipping_rejected_before_import(self):
        for value in (1, "true", None):
            with self.subTest(value=value), patch("framewright.commands.import_module") as loader:
                response = dispatch(
                    dict(
                        schema_version="1.0",
                        request_id="clip-invalid",
                        command="asset.export",
                        params=dict(
                            object_names=["Skin"],
                            directory="C:/Export",
                            format="FBX",
                            clamp_scalar_textures=value,
                        ),
                    )
                )
                self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
                loader.assert_not_called()
