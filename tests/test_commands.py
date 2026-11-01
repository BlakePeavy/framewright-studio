"""Discovery and validation contract for production commands."""

import unittest
from unittest.mock import patch

from framewright.api import dispatch
from framewright.commands import command_metadata, validate_params


class CommandTests(unittest.TestCase):
    def test_discovery_contains_json_schemas(self):
        entries = {entry["name"]: entry for entry in command_metadata()}
        self.assertIn("model.build_prop", entries)
        self.assertTrue(entries["model.build_prop"]["mutates"])
        self.assertFalse(entries["mesh.inspect_evaluated"]["mutates"])
        self.assertEqual(entries["model.build_prop"]["input_schema"]["type"], "object")

    def test_bad_inputs_are_rejected_before_import(self):
        cases = [
            ("model.build_prop", {"dry_run": "false"}),
            ("model.build_prop", {"width": -1}),
            ("model.build_prop", {"width": float("nan")}),
            ("model.build_prop", {"location": [0, 0]}),
            ("model.build_prop", {"execute": "print(1)"}),
            ("mesh.inspect_evaluated", {}),
            ("mesh.inspect_evaluated", {"object_name": "Cube", "max_pairs": True}),
            ("repair.apply_plan", {"plan_token": "x", "source_fingerprint": "y", "dry_run": 0}),
            ("lighting.create_review", {"object_names": ["Cube"], "lighting": "unknown"}),
        ]
        for command, params in cases:
            with (
                self.subTest(command=command, params=params),
                patch("framewright.commands.import_module") as loader,
            ):
                response = dispatch(
                    {
                        "schema_version": "1.0",
                        "request_id": "invalid",
                        "command": command,
                        "params": params,
                    }
                )
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
                loader.assert_not_called()

    def test_valid_params_are_preserved(self):
        params = {"width": 1.2, "location": [0, 0, 0], "dry_run": False}
        validate_params("model.build_prop", params)
        self.assertEqual(params["width"], 1.2)

    def test_dispatch_uses_only_registered_handler(self):
        with patch("framewright.commands.import_module") as loader:
            loader.return_value.build_prop.return_value = {"dry_run": True}
            response = dispatch(
                {
                    "schema_version": "1.0",
                    "request_id": "plan",
                    "command": "model.build_prop",
                    "params": {},
                }
            )
            self.assertTrue(response["ok"])
            loader.assert_called_once_with(".production_assets", "framewright")
            loader.return_value.build_prop.assert_called_once_with({})


if __name__ == "__main__":
    unittest.main()
