"""Protocol acceptance tests written before the dispatcher implementation."""

import json
import unittest

from framewright.api import dispatch
from framewright.core import ObjectSnapshot, SceneSnapshot


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def capture_scene(self):
        self.calls.append("capture")
        return SceneSnapshot("Test", objects=(ObjectSnapshot("Prop", "MESH"),))

    def preview_remove_loose_vertices(self, object_name):
        self.calls.append(("preview", object_name))
        return {"source": object_name, "removed_vertices": 2, "dry_run": True}

    def apply_remove_loose_vertices(self, object_name):
        self.calls.append(("apply", object_name))
        return {
            "source": object_name,
            "derivative": "Prop_FW",
            "removed_vertices": 2,
            "dry_run": False,
        }


def request(command="capabilities", **params):
    return {"schema_version": "1.0", "request_id": "test-1", "command": command, "params": params}


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_capabilities_need_no_blender(self):
        response = dispatch(request())
        self.assertTrue(response["ok"])
        self.assertIn("scene.validate", [c["name"] for c in response["result"]["commands"]])
        self.assertIn("cinematic_8k", response["result"]["profiles"])
        json.dumps(response, allow_nan=False)

    def test_inspect_serializes_snapshot(self):
        response = dispatch(request("scene.inspect"), self.adapter)
        self.assertEqual(response["result"]["objects"][0]["name"], "Prop")
        self.assertEqual(self.adapter.calls, ["capture"])

    def test_validate_with_explicit_profile_and_overrides(self):
        response = dispatch(
            request(
                "scene.validate",
                profile="cinematic_8k",
                overrides={"max_triangles": 1234, "texture_target": 4096},
            ),
            self.adapter,
        )
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["passed"])
        self.assertEqual(response["result"]["settings"]["max_triangles"], 1234)
        self.assertEqual(response["result"]["settings"]["texture_target"], 4096)

    def test_repairs_default_to_preview(self):
        response = dispatch(request("mesh.remove_loose_vertices", object_name="Prop"), self.adapter)
        self.assertTrue(response["result"]["dry_run"])
        self.assertEqual(self.adapter.calls, [("preview", "Prop")])

    def test_explicit_repair_is_dispatched(self):
        response = dispatch(
            request("mesh.remove_loose_vertices", object_name="Prop", dry_run=False), self.adapter
        )
        self.assertEqual(response["result"]["derivative"], "Prop_FW")
        self.assertEqual(self.adapter.calls, [("apply", "Prop")])

    def test_invalid_request_never_touches_adapter(self):
        invalid = [
            None,
            [],
            {},
            {**request(), "schema_version": "2"},
            {**request(), "request_id": ""},
            {**request(), "request_id": 2},
            {**request(), "extra": "ignored?"},
            {**request(), "params": None},
            {**request(), "command": "python.exec"},
            request("capabilities", code="print(1)"),
            request("scene.inspect", path="secret"),
            request("scene.validate", profile="missing"),
            request("scene.validate", profile=[]),
            request("scene.validate", overrides={"max_triangles": True}),
            request("scene.validate", overrides={"max_triangles": -1}),
            request("scene.validate", overrides={"max_triangles": 1.5}),
            request("scene.validate", overrides={"require_uvs": 1}),
            request("scene.validate", overrides={"execute": "anything"}),
            request("scene.validate", overrides=[]),
            request(
                "scene.validate", overrides={"texture_target": 8192, "max_texture_resolution": 4096}
            ),
            request("mesh.remove_loose_vertices"),
            request("mesh.remove_loose_vertices", object_name=""),
            request("mesh.remove_loose_vertices", object_name="Prop", dry_run="false"),
        ]
        for value in invalid:
            with self.subTest(value=value):
                response = dispatch(value, self.adapter)
                self.assertFalse(response["ok"])
                self.assertIn("code", response["error"])
        self.assertEqual(self.adapter.calls, [])

    def test_expected_adapter_failure_is_structured(self):
        self.adapter.preview_remove_loose_vertices = lambda name: (_ for _ in ()).throw(
            ValueError("Shape keys are unsupported")
        )
        response = dispatch(request("mesh.remove_loose_vertices", object_name="Prop"), self.adapter)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "OPERATION_REJECTED")

    def test_unexpected_error_does_not_expose_local_details(self):
        self.adapter.capture_scene = lambda: (_ for _ in ()).throw(
            RuntimeError("C:/private/secret")
        )
        response = dispatch(request("scene.inspect"), self.adapter)
        self.assertFalse(response["ok"])
        self.assertNotIn("private", json.dumps(response))
        self.assertEqual(response["error"]["code"], "INTERNAL_ERROR")

    def test_request_is_not_modified(self):
        value = request("scene.validate", overrides={"max_triangles": 20})
        before = json.dumps(value, sort_keys=True)
        dispatch(value, self.adapter)
        self.assertEqual(before, json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
