"""Fixed in-editor entrypoint; default preview. Never launches or contacts an editor.

Apply requires an explicitly authorized native window, owner, --apply and
--authorize-native. Importing this script does nothing. Do not invoke it through
an arbitrary-code MCP tool or a caller-selected script path.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framewright.native_handoff import (
    MAX_JSON,
    _json,
    _path,
    _read_bounded,
    _record,
    _require,
    apply_plan,
    verify_plan,
)  # noqa: E402
from framewright.unreal_static import UnrealStaticBackend, native_owner  # noqa: E402
from scripts.prepare_native_import import output_path, write_json  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--owner")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorize-native", action="store_true")
    args = parser.parse_args(argv)
    if args.apply:
        _require(
            args.authorize_native and args.owner,
            "Explicit native authorization and owner are required",
        )
    else:
        _require(not args.authorize_native, "Native authorization flag requires --apply")
    path = _path(args.plan)
    record = _record(path, maximum=MAX_JSON)
    plan = verify_plan(_json(_read_bounded(path, MAX_JSON, record)))
    report = output_path(args.report, plan)
    _require(report != path, "Report cannot overwrite input plan")
    # Exclusive reservation precedes every native action. A partial write remains
    # evidence and is never overwritten by a later invocation.
    with report.open("xb") as stream:
        try:
            ownership = (
                native_owner(plan["project_root"], args.owner)
                if args.apply
                else contextlib.nullcontext(None)
            )
            with ownership as lease:
                backend = UnrealStaticBackend(plan["project_root"], lease=lease)
                result = apply_plan(
                    plan,
                    backend,
                    dry_run=not args.apply,
                    authorized=args.authorize_native,
                    owner=args.owner,
                )
        except Exception as exc:
            write_json(
                stream,
                {
                    "status": "failed",
                    "native_verified": False,
                    "plan_sha256": plan["plan_sha256"],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise
        write_json(stream, result)
    print(
        json.dumps(
            {
                "report": str(report),
                "status": result["status"],
                "native_verified": result["native_verified"],
            }
        )
    )
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
