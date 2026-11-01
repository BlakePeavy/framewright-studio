import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy  # noqa:E402

import framewright  # noqa:E402


class ProductionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        framewright.register()

    @classmethod
    def tearDownClass(cls):
        framewright.unregister()

    def test_panel_registered(self):
        self.assertTrue(hasattr(bpy.types, "FRAMEWRIGHT_PT_production"))

    def test_builder_operator_creates_editable_asset(self):
        self.assertEqual(bpy.ops.framewright.build_asset(kind="CABINET"), {"FINISHED"})
        report = json.loads(bpy.context.scene.framewright_tool_report)
        self.assertTrue(report["ok"])
        self.assertIn(report["result"]["collection"], bpy.data.collections)

    def test_diagnostic_operator_produces_report(self):
        bpy.context.view_layer.objects.active = next(
            o for o in bpy.context.scene.objects if o.type == "MESH"
        )
        self.assertEqual(bpy.ops.framewright.inspect_production(kind="MESH"), {"FINISHED"})
        self.assertTrue(json.loads(bpy.context.scene.framewright_tool_report)["ok"])

    def test_request_operator_rejects_code(self):
        bpy.context.scene.framewright_request_json = json.dumps(
            {"schema_version": "1.0", "request_id": "bad", "command": "python.exec", "params": {}}
        )
        try:
            result = bpy.ops.framewright.run_request()
        except RuntimeError:
            result = {"CANCELLED"}
        self.assertEqual(result, {"CANCELLED"})
        self.assertFalse(json.loads(bpy.context.scene.framewright_tool_report)["ok"])

    def test_failed_workflow_is_not_reported_as_finished(self):
        bpy.context.scene.framewright_request_json = json.dumps(
            {
                "schema_version": "1.0",
                "request_id": "gate",
                "command": "workflow.run",
                "params": {
                    "run_id": "ui-failed-gate",
                    "dry_run": False,
                    "steps": [
                        {
                            "id": "check",
                            "command": "capabilities",
                            "params": {},
                            "require": [{"path": "result.nonexistent", "equals": True}],
                        }
                    ],
                },
            }
        )
        try:
            result = bpy.ops.framewright.run_request()
        except RuntimeError:
            result = {"CANCELLED"}
        self.assertEqual(result, {"CANCELLED"})
        report = json.loads(bpy.context.scene.framewright_tool_report)
        self.assertEqual(report["result"]["status"], "failed")

    def test_duplicate_json_keys_rejected_before_mutation(self):
        before = set(bpy.data.objects.keys())
        bpy.context.scene.framewright_request_json = (
            '{"schema_version":"1.0","request_id":"ambiguous",'
            '"command":"model.build_prop","params":{"dry_run":true,"dry_run":false}}'
        )
        try:
            result = bpy.ops.framewright.run_request()
        except RuntimeError:
            result = {"CANCELLED"}
        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(set(bpy.data.objects.keys()), before)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProductionUITests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Production UI tests failed")
