"""Exercise feature schemas and real implementations through the public API."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy  # noqa:E402

from framewright.api import dispatch  # noqa:E402


def call(command, params):
    response = dispatch(
        {"schema_version": "1.0", "request_id": "integration", "command": command, "params": params}
    )
    if not response["ok"]:
        raise AssertionError(response)
    return response["result"]


class FeatureAPITests(unittest.TestCase):
    def test_manifest_endpoints_roundtrip(self):
        manifest = call("asset.manifest_create", {"name": "Fixture"})
        validated = call("asset.manifest_validate", {"manifest": manifest})
        self.assertTrue(validated["valid"])
        self.assertEqual(validated["manifest"]["asset_id"], manifest["asset_id"])

    def test_diagnostics_use_real_active_scene(self):
        mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")
        result = call("mesh.inspect_evaluated", {"object_name": mesh.name})
        self.assertIn("findings", result)
        result = call("surfaces.inspect", {"object_name": mesh.name})
        self.assertIn("findings", result)

    def test_transaction_workflow(self):
        mesh = bpy.data.meshes.new("FW_API_Fixture")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (9, 9, 9)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("FW_API_Fixture", mesh)
        bpy.context.scene.collection.objects.link(obj)
        result = call(
            "workflow.run",
            {
                "run_id": "api-transaction",
                "dry_run": False,
                "steps": [
                    {
                        "id": "preview",
                        "command": "repair.plan_remove_loose",
                        "params": {"object_name": obj.name},
                    },
                    {
                        "id": "apply",
                        "command": "repair.apply_plan",
                        "params": {
                            "plan_token": {"$ref": "preview.result.plan_token"},
                            "source_fingerprint": {"$ref": "preview.result.source_fingerprint"},
                        },
                    },
                ],
            },
        )
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(obj.data.vertices), 4)

    def test_construction_workflow_with_bound_collection(self):
        result = call(
            "workflow.run",
            {
                "run_id": "api-assets",
                "dry_run": False,
                "steps": [
                    {
                        "id": "build",
                        "command": "model.build_prop",
                        "params": {"name": "API_Cabinet"},
                    },
                    {
                        "id": "validate",
                        "command": "scene.validate",
                        "params": {
                            "profile": "studio_static",
                            "overrides": {"require_materials": False},
                        },
                        "require": [{"path": "result.passed", "equals": True}],
                    },
                    {
                        "id": "review",
                        "command": "lighting.create_review",
                        "params": {
                            "collection_name": {"$ref": "build.result.collection"},
                            "resolution": 128,
                        },
                    },
                ],
            },
        )
        self.assertEqual(result["status"], "completed", result)
        review = result["steps"][2]["response"]["result"]
        self.assertIn(review["scene"], bpy.data.scenes)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FeatureAPITests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Feature API tests failed")
