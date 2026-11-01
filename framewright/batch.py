"""Run one JSON job in an isolated Blender process; see docs/ai-api.md.

Use --background --factory-startup --disable-autoexec BEFORE the input .blend,
then --python-exit-code 1 --python scripts/blender_job.py -- --request ... --output ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not permitted")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number {value} is not permitted")


def parse_request_json(data: bytes | str) -> dict:
    if isinstance(data, str):
        data = data.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise ValueError("Request exceeds the 1 MiB limit")
    return json.loads(
        data.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def read_request(path: Path) -> dict:
    with path.open("rb") as stream:
        return parse_request_json(stream.read(1024 * 1024 + 1))


def validate_destinations(output: Path, save_as: Path | None, current_filepath: str):
    if output.suffix.lower() != ".json":
        raise ValueError("Report output must use .json")
    if output.exists():
        raise ValueError("Report already exists; choose a new output filename")
    if not output.parent.is_dir():
        raise ValueError("Report parent directory must exist")
    if save_as:
        if save_as.suffix.lower() != ".blend" or not save_as.parent.is_dir():
            raise ValueError("Save target must be a .blend file in an existing directory")
        if current_filepath and save_as.resolve() == Path(current_filepath).resolve():
            raise ValueError("Save target cannot replace the source blend file")
        if save_as.exists():
            raise ValueError("Save target already exists; choose a new derivative filename")


def write_report(path: Path, response: dict):
    content = json.dumps(response, indent=2, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def _remove_empty_reservation(path: Path, identity):
    """Remove only the empty file this process exclusively created."""
    if identity is None:
        return
    try:
        current = path.stat()
        if current.st_size == 0 and (current.st_dev, current.st_ino) == (
            identity.st_dev,
            identity.st_ino,
        ):
            path.unlink()
    except OSError:
        # Cleanup must not hide the operation's failure or delete another file.
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--enable-rigify",
        action="store_true",
        help="Load bundled Rigify in this owned background process only",
    )
    parser.add_argument(
        "--save-as", type=Path, help="Explicit derivative .blend destination for applied repairs"
    )
    args = parser.parse_args(argv)
    import bpy

    from .api import dispatch
    from .commands import needs_scene_save

    report_identity = None
    saved_path = None
    try:
        validate_destinations(args.output, args.save_as, bpy.data.filepath)
        request = read_request(args.request)
        if args.enable_rigify:
            if not bpy.app.background:
                raise ValueError("Rigify bootstrap is restricted to background jobs")
            import addon_utils

            # Rigify requires its in-memory preference entry during register().
            # Background jobs never save user preferences; worker roots are isolated.
            addon_utils.enable("rigify", default_set=True, persistent=False)
            if not addon_utils.check("rigify")[1]:
                raise ValueError("Bundled Rigify could not be enabled in this job")
        # No writes are necessary for inspection/preview jobs. Applied repair must persist.
        applying = needs_scene_save(request)
        if applying and args.save_as is None:
            raise ValueError("Applied repairs require --save-as for a new derivative .blend file")
        if args.save_as and not applying:
            raise ValueError("--save-as is only valid for an explicit applied repair")
        # Claim the report before any edit/save, closing the preflight-to-write race.
        # The report and .blend cannot form one filesystem transaction: a later
        # report I/O failure is disclosed separately if the derivative was saved.
        with args.output.open("x", encoding="utf-8") as report:
            report_identity = os.fstat(report.fileno())
            response = dispatch(request)
            if response["ok"] and applying:
                with args.save_as.open("xb") as reservation:
                    derivative_identity = os.fstat(reservation.fileno())
                try:
                    destination = args.save_as.resolve()
                    filepaths = bpy.context.preferences.filepaths
                    previous_save_version = filepaths.save_version
                    try:
                        # Do not back up our empty exclusive-create reservation.
                        # Change only this background process and always restore it.
                        filepaths.save_version = 0
                        saved = bpy.ops.wm.save_as_mainfile(
                            filepath=str(destination), copy=True, check_existing=False
                        )
                    finally:
                        filepaths.save_version = previous_save_version
                    if "FINISHED" not in saved:
                        raise RuntimeError("Blender did not complete saving the derivative")
                    saved_path = destination
                except Exception:
                    _remove_empty_reservation(args.save_as, derivative_identity)
                    raise
            report.write(json.dumps(response, indent=2, allow_nan=False) + "\n")
        if not response["ok"]:
            return 2
        if request["command"] == "workflow.run" and response["result"]["status"] in {
            "failed",
            "cancelled",
        }:
            return 2
        if request["command"] == "scene.validate" and not response["result"]["passed"]:
            return 3
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Framewright job failed: {error}", file=sys.stderr)
        if saved_path is not None:
            print(
                f"Derivative was saved at {saved_path}; report could not be completed at {args.output.resolve()}",
                file=sys.stderr,
            )
        return 2
    finally:
        _remove_empty_reservation(args.output, report_identity)


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    code = main(arguments)
    if code:
        # Blender propagates SystemExit's code; --python-exit-code also guards uncaught errors.
        raise SystemExit(code)
