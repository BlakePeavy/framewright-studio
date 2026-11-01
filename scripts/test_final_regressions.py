"""Independent final review regressions for workflow/file/bake boundaries."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import baking, interchange, reference_board, workflows  # noqa: E402
from framewright.provenance import create_manifest  # noqa: E402
from scripts.test_baking import counts, fixture  # noqa: E402


class FinalRegressionTests(unittest.TestCase):
    def test_export_failed_write_keeps_changed_output_and_removes_owned_partial(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        before = interchange._source_record([obj])
        for replace in (False, True):
            with (
                self.subTest(replace=replace),
                tempfile.TemporaryDirectory(prefix="framewright-export-write-") as temporary,
            ):
                output = Path(temporary) / "asset.glb"
                replacement = b"unrelated replacement contents"

                def fail_copy(
                    incoming, destination, *args, replacement=replacement, replace=replace, **kwargs
                ):
                    destination.write(replacement if replace else incoming.read(64))
                    destination.flush()
                    raise OSError("Injected publication failure")

                with (
                    patch.object(interchange.shutil, "copyfileobj", fail_copy),
                    self.assertRaisesRegex(OSError, "publication"),
                ):
                    interchange.export_asset(
                        {"object_names": [obj.name], "directory": temporary, "dry_run": False}
                    )
                if replace:
                    self.assertTrue(output.exists(), "Cleanup deleted another writer's data")
                    self.assertEqual(output.read_bytes(), replacement)
                else:
                    self.assertFalse(output.exists(), "Owned partial output prevents retry")
                self.assertFalse(output.with_suffix(".receipt.json").exists())
                self.assertEqual(interchange._source_record([obj]), before)

    def test_export_receipt_failure_preserves_foreign_changes_to_published_asset(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        with tempfile.TemporaryDirectory(prefix="framewright-export-receipt-") as temporary:
            output = Path(temporary) / "asset.glb"
            receipt = Path(temporary) / "asset.receipt.json"
            original_open = Path.open
            replacement = b"foreign edit after publication"

            def fail_receipt(path, *args, **kwargs):
                if path == receipt and args and "x" in args[0]:
                    output.write_bytes(replacement)
                    raise OSError("Injected receipt failure")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", fail_receipt), self.assertRaises(OSError):
                interchange.export_asset(
                    {"object_names": [obj.name], "directory": temporary, "dry_run": False}
                )
            self.assertTrue(output.exists(), "Receipt cleanup deleted changed asset data")
            self.assertEqual(output.read_bytes(), replacement)
            self.assertFalse(receipt.exists())

    def test_addon_registration_failure_rolls_back_all_partially_registered_classes(self):
        import framewright
        from framewright import ui, ui_tools

        original_register = bpy.utils.register_class
        try:
            for target in (ui.CLASSES[2], ui_tools.CLASSES[2]):

                def fail_mid_registration(cls, target=target):
                    if cls is target:
                        raise RuntimeError("Injected class registration failure")
                    return original_register(cls)

                with self.subTest(stage=target.__name__):
                    with (
                        patch.object(bpy.utils, "register_class", fail_mid_registration),
                        self.assertRaisesRegex(RuntimeError, "Injected"),
                    ):
                        framewright.register()
                    leaked = [
                        cls.__name__
                        for cls in (*ui.CLASSES, *ui_tools.CLASSES)
                        if cls.is_registered
                    ]
                    self.assertEqual(
                        leaked, [], "A failed enable leaves classes registered and breaks retry"
                    )
                    self.assertTrue(
                        all(
                            not hasattr(bpy.types.Scene, name)
                            for name in (*ui.SCENE_PROPERTIES, *ui_tools.SCENE_PROPERTIES)
                        )
                    )
            framewright.register()
            self.assertTrue(all(cls.is_registered for cls in (*ui.CLASSES, *ui_tools.CLASSES)))
            framewright.unregister()
        finally:
            # Remove only classes this isolated test may have registered.
            for cls in reversed((*ui.CLASSES, *ui_tools.CLASSES)):
                if cls.is_registered:
                    bpy.utils.unregister_class(cls)

    def test_registration_refuses_foreign_operator_or_property_without_removing_it(self):
        import framewright
        from framewright import ui, ui_tools

        foreign = type(
            "FRAMEWRIGHT_OT_build_asset",
            (bpy.types.Operator,),
            {
                "bl_idname": "framewright.build_asset",
                "bl_label": "Unrelated owner",
                "execute": lambda self, context: {"FINISHED"},
            },
        )
        bpy.utils.register_class(foreign)
        try:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                framewright.register()
            framewright.unregister()
            self.assertTrue(foreign.is_registered)
            self.assertTrue(all(not cls.is_registered for cls in (*ui.CLASSES, *ui_tools.CLASSES)))
        finally:
            bpy.utils.unregister_class(foreign)
        bpy.types.Scene.framewright_profile = bpy.props.StringProperty(default="retained owner")
        try:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                framewright.register()
            framewright.unregister()
            self.assertEqual(bpy.context.scene.framewright_profile, "retained owner")
        finally:
            del bpy.types.Scene.framewright_profile

    def test_reference_board_write_failure_removes_only_its_partial_output(self):
        with tempfile.TemporaryDirectory(prefix="framewright-board-failure-") as temporary:
            output = Path(temporary) / "review.html"
            original_open = Path.open

            class FailingWrite:
                def __init__(self, stream):
                    self.stream = stream

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

                def write(self, data):
                    self.stream.write(data[:64])
                    self.stream.flush()
                    raise OSError("Injected partial disk write")

            def partial_open(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return FailingWrite(stream) if path == output and args == ("xb",) else stream

            with (
                patch.object(Path, "open", partial_open),
                self.assertRaisesRegex(OSError, "partial"),
            ):
                reference_board.create_board(
                    {
                        "manifest": create_manifest({"name": "Failure fixture"}),
                        "output": str(output),
                        "dry_run": False,
                    }
                )
            self.assertFalse(
                output.exists(),
                "Failed writes leave an owned HTML stub that prevents a clean retry",
            )

    def test_reference_board_failed_write_cleanup_retains_foreign_replacement_bytes(self):
        with tempfile.TemporaryDirectory(prefix="framewright-board-replacement-") as temporary:
            output = Path(temporary) / "review.html"
            original_open = Path.open
            replacement = b"another writer replaced these bytes"

            class ChangedWrite:
                def __init__(self, stream):
                    self.stream = stream

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

                def write(self, data):
                    self.stream.write(replacement)
                    self.stream.flush()
                    raise OSError("Injected changed output bytes")

            def changed_open(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return ChangedWrite(stream) if path == output and args == ("xb",) else stream

            with patch.object(Path, "open", changed_open), self.assertRaises(OSError):
                reference_board.create_board(
                    {
                        "manifest": create_manifest({"name": "Replacement fixture"}),
                        "output": str(output),
                        "dry_run": False,
                    }
                )
            self.assertEqual(output.read_bytes(), replacement)

    def test_dynamic_file_binding_and_failed_gate_preserve_no_overwrite_contract(self):
        with tempfile.TemporaryDirectory(prefix="framewright-workflow-review-") as temporary:
            output = Path(temporary) / "review.html"
            workflows.clear_run_cache()
            plan = {
                "run_id": "dynamic-file-review",
                "dry_run": False,
                "steps": [
                    {
                        "id": "manifest",
                        "command": "asset.manifest_create",
                        "params": {
                            "name": "Dynamic board",
                            "recipe": {
                                "tool": "fixture",
                                "version": "1",
                                "operation": "review",
                                "parameters": {"output": str(output), "preview": False},
                            },
                        },
                    },
                    {
                        "id": "board",
                        "command": "asset.reference_board",
                        "params": {
                            "manifest": {"$ref": "manifest.result"},
                            "output": {"$ref": "manifest.result.recipe.parameters.output"},
                            "dry_run": {"$ref": "manifest.result.recipe.parameters.preview"},
                        },
                        "require": [{"path": "result.dry_run", "equals": False}],
                    },
                ],
            }
            result = workflows.run_workflow(plan)
            self.assertEqual(result["status"], "completed", result)
            original = output.read_bytes()
            replay = workflows.run_workflow(plan)
            self.assertTrue(replay["replayed"])
            self.assertEqual(output.read_bytes(), original)
            plan["run_id"] = "dynamic-file-no-overwrite"
            failed = workflows.run_workflow(plan)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(failed["steps"][-1]["response"]["ok"])

    def test_explicit_cage_projection_matches_actual_bake_distance(self):
        high, low = fixture()
        cage = low.copy()
        cage.data = low.data.copy()
        cage.name = "ReviewFarCage"
        for vertex in cage.data.vertices:
            vertex.co.z = 0.8
        bpy.context.scene.collection.objects.link(cage)
        bpy.context.view_layer.update()
        before = counts()
        try:
            result = baking.bake_normal(
                {
                    "high_object": high.name,
                    "low_object": low.name,
                    "cage_object": cage.name,
                    "ray_distance": 0.1,
                    "resolution": 64,
                    "dry_run": False,
                }
            )
        except ValueError:
            self.assertEqual(counts(), before)
        else:
            print(
                "FINAL_REVIEW_CAGE_EVIDENCE "
                + json.dumps(
                    {
                        key: result[key]
                        for key in (
                            "projection",
                            "channel_ranges",
                            "detail_present",
                            "valid_normal_fraction",
                        )
                    }
                )
            )
            self.assertTrue(
                result["detail_present"],
                "Cage preflight must not report hits while the actual limited bake misses a known corrugated high surface",
            )


if __name__ == "__main__":
    if not bpy.app.background:
        raise RuntimeError("Run only in an isolated background Blender process")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FinalRegressionTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("Final review regressions failed")
