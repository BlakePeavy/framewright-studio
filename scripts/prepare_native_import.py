"""Compile one existing Sundown handoff offline; never starts/connects to Unreal."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framewright.native_handoff import (  # noqa: E402
    MAX_GLB,
    MAX_TOTAL_IMAGE_PIXELS,
    _path,
    _require,
    compile_plan,
)


def output_path(raw, plan):
    path = Path(raw)
    _require(
        path.is_absolute() and ".." not in path.parts and not str(path).startswith(("\\\\", "//")),
        "Output must be an absolute local path",
    )
    _require(":" not in str(path)[len(path.drive) :], "Alternate-stream output is forbidden")
    parent = _path(path.parent, directory=True)
    destination = parent / path.name
    _require(destination.suffix.lower() == ".json", "Output must be JSON")
    for forbidden in (plan["project_root"], plan["source_root"]):
        _require(
            not destination.is_relative_to(Path(forbidden)),
            "Output cannot be inside game/source root",
        )
    _require(destination != Path(plan["handoff"]["path"]), "Output cannot overwrite handoff")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    return destination


def write_json(stream, value):
    stream.write((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())
    stream.flush()
    os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-glb-bytes",
        type=int,
        default=MAX_GLB,
        help="Explicit GLB admission allowance in bytes (default 67108864; ceiling 536870912)",
    )
    parser.add_argument(
        "--max-total-image-pixels",
        type=int,
        default=MAX_TOTAL_IMAGE_PIXELS,
        help="Aggregate embedded image pixels (default 134217728; ceiling 536870912)",
    )
    args = parser.parse_args(argv)
    plan = compile_plan(
        args.handoff,
        project_root=args.project_root,
        source_root=args.source_root,
        max_glb_bytes=args.max_glb_bytes,
        max_total_image_pixels=args.max_total_image_pixels,
    )
    output = output_path(args.output, plan)
    with output.open("xb") as stream:
        write_json(stream, plan)
    print(
        json.dumps(
            {"output": str(output), "plan_sha256": plan["plan_sha256"], "status": plan["status"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
