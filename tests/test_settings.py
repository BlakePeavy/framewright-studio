import json
import unittest

from framewright.settings import migrate_settings, parse_saved_report


class SettingsTests(unittest.TestCase):
    def test_report_corruption_never_crashes_ui(self):
        for text in ["", "{", "null", "[]", '{"findings":5}', '{"findings":[null]}']:
            self.assertIsNone(parse_saved_report(text))

    def test_supported_report_is_retained(self):
        report = {
            "schema_version": "1.0",
            "findings": [
                {"rule_id": "TEST", "severity": "INFO", "message": "Review", "object_name": None}
            ],
        }
        self.assertEqual(parse_saved_report(json.dumps(report)), report)

    def test_incompatible_report_version_is_not_rendered(self):
        self.assertIsNone(parse_saved_report('{"schema_version":"9.0","findings":[]}'))

    def test_legacy_settings_migrate_without_mutating_input(self):
        old = {
            "schema_version": 1,
            "profile": "cinematic_8k",
            "triangle_limit": 0,
            "texture_target": 0,
        }
        new = migrate_settings(old)
        self.assertEqual(old["texture_target"], 0)
        self.assertEqual(new["schema_version"], 2)
        self.assertEqual(new["texture_target"], -1)

    def test_current_settings_validate_and_keep_explicit_zero(self):
        settings = {
            "schema_version": 2,
            "profile": "cinematic_8k",
            "triangle_limit": 0,
            "texture_target": 0,
            "texture_max": 0,
        }
        self.assertEqual(migrate_settings(settings), settings)

    def test_unknown_versions_and_bad_fields_rejected(self):
        for data in [
            {"schema_version": 9},
            {"schema_version": 2, "profile": "unknown"},
            {"schema_version": 2, "triangle_limit": True},
        ]:
            with self.assertRaises(ValueError):
                migrate_settings(data)


if __name__ == "__main__":
    unittest.main()
