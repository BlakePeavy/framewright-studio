"""File-boundary tests for unattended Blender jobs."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from framewright.batch import main, read_request, validate_destinations, write_report


class JobBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_request_rejects_duplicate_keys_and_nan(self):
        for content in ['{"command":"x","command":"y"}', '{"x":NaN}']:
            path = self.root / "request.json"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_request(path)

    def test_request_is_bounded(self):
        path = self.root / "request.json"
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            read_request(path)

    def test_report_never_overwrites_existing_file(self):
        path = self.root / "report.json"
        write_report(path, {"ok": True})
        with self.assertRaises(FileExistsError):
            write_report(path, {"ok": False})
        self.assertEqual(json.loads(path.read_text()), {"ok": True})

    def test_save_cannot_replace_source_or_existing_file(self):
        source = self.root / "source.blend"
        source.touch()
        report = self.root / "report.json"
        with self.assertRaises(ValueError):
            validate_destinations(report, source, str(source))
        existing = self.root / "existing.blend"
        existing.touch()
        with self.assertRaises(ValueError):
            validate_destinations(report, existing, str(source))

    def test_outputs_require_correct_extensions(self):
        with self.assertRaises(ValueError):
            validate_destinations(self.root / "report.blend", None, "")
        with self.assertRaises(ValueError):
            validate_destinations(self.root / "report.json", self.root / "save.json", "")

    def test_new_destinations_accepted(self):
        validate_destinations(self.root / "report.json", self.root / "derivative.blend", "")

    def request(self, apply=False):
        request = {
            "schema_version": "1.0",
            "request_id": "job-test",
            "command": "mesh.remove_loose_vertices" if apply else "capabilities",
            "params": {"object_name": "Prop", "dry_run": False} if apply else {},
        }
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path, request

    def bpy(self, save=None):
        def default_save(filepath, **kwargs):
            Path(filepath).write_bytes(b"fixture derivative")
            return {"FINISHED"}

        return SimpleNamespace(
            data=SimpleNamespace(filepath=""),
            ops=SimpleNamespace(wm=SimpleNamespace(save_as_mainfile=save or default_save)),
            context=SimpleNamespace(
                preferences=SimpleNamespace(filepaths=SimpleNamespace(save_version=2))
            ),
        )

    def test_save_suppresses_reservation_backup_and_restores_preferences(self):
        request_path, _ = self.request(apply=True)
        output = self.root / "report.json"
        derivative = self.root / "derivative.blend"
        fake_bpy = self.bpy()

        def checked_save(filepath, **kwargs):
            self.assertEqual(fake_bpy.context.preferences.filepaths.save_version, 0)
            Path(filepath).write_bytes(b"saved derivative")
            return {"FINISHED"}

        fake_bpy.ops.wm.save_as_mainfile = checked_save
        with (
            patch.dict("sys.modules", {"bpy": fake_bpy}),
            patch("framewright.api.dispatch", return_value={"ok": True, "result": {}}),
        ):
            code = main(
                [
                    "--request",
                    str(request_path),
                    "--output",
                    str(output),
                    "--save-as",
                    str(derivative),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(fake_bpy.context.preferences.filepaths.save_version, 2)

    def test_report_race_is_rejected_before_dispatch_or_save(self):
        request_path, request = self.request(apply=True)
        output = self.root / "report.json"
        derivative = self.root / "derivative.blend"

        def concurrent_request_read(path):
            write_report(output, {"competing_job": True})
            return request

        with (
            patch.dict("sys.modules", {"bpy": self.bpy()}),
            patch("framewright.batch.read_request", concurrent_request_read),
            patch("framewright.api.dispatch", return_value={"ok": True, "result": {}}) as dispatch,
            redirect_stderr(io.StringIO()),
        ):
            code = main(
                [
                    "--request",
                    str(request_path),
                    "--output",
                    str(output),
                    "--save-as",
                    str(derivative),
                ]
            )
        self.assertEqual(code, 2)
        dispatch.assert_not_called()
        self.assertFalse(derivative.exists())
        self.assertEqual(json.loads(output.read_text()), {"competing_job": True})

    def test_report_is_reserved_before_dispatch_and_filled_afterward(self):
        request_path, _ = self.request()
        output = self.root / "report.json"
        response = {"ok": True, "result": {"test": True}}

        def inspect_reservation(request):
            self.assertTrue(output.exists())
            with self.assertRaises(FileExistsError):
                write_report(output, {"competing_job": True})
            return response

        with (
            patch.dict("sys.modules", {"bpy": self.bpy()}),
            patch("framewright.api.dispatch", inspect_reservation),
        ):
            code = main(["--request", str(request_path), "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text()), response)

    def test_failed_save_removes_empty_owned_reservations(self):
        request_path, _ = self.request(apply=True)
        output = self.root / "report.json"
        derivative = self.root / "derivative.blend"

        def failed_save(**kwargs):
            raise RuntimeError("Fixture save failed")

        with (
            patch.dict("sys.modules", {"bpy": self.bpy(failed_save)}),
            patch("framewright.api.dispatch", return_value={"ok": True, "result": {}}),
            redirect_stderr(io.StringIO()),
        ):
            code = main(
                [
                    "--request",
                    str(request_path),
                    "--output",
                    str(output),
                    "--save-as",
                    str(derivative),
                ]
            )
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
        self.assertFalse(derivative.exists())

    def test_report_failure_discloses_already_saved_derivative(self):
        request_path, _ = self.request(apply=True)
        output = self.root / "report.json"
        derivative = self.root / "derivative.blend"
        errors = io.StringIO()
        with (
            patch.dict("sys.modules", {"bpy": self.bpy()}),
            patch("framewright.api.dispatch", return_value={"ok": True, "result": {}}),
            patch("framewright.batch.json.dumps", side_effect=OSError("Fixture disk full")),
            redirect_stderr(errors),
        ):
            code = main(
                [
                    "--request",
                    str(request_path),
                    "--output",
                    str(output),
                    "--save-as",
                    str(derivative),
                ]
            )
        self.assertEqual(code, 2)
        self.assertEqual(derivative.read_bytes(), b"fixture derivative")
        self.assertIn(str(derivative.resolve()), errors.getvalue())
        self.assertIn("saved", errors.getvalue().lower())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
