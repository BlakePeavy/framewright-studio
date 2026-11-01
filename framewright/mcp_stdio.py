"""Optional MCP stdio process. No network listener, model calls or live Blender access."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

if __package__ in {None, ""}:
    # MCP hosts often launch from a different working directory. The absolute
    # packaged entry path works without installing runtime dependencies.
    package_path = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_path.parent))
    __package__ = package_path.name

from . import __version__  # noqa: E402
from .commands import COMMANDS, JSON_OBJECT, _validate, number, obj, string  # noqa: E402
from .provenance import canonical_json, validate_manifest  # noqa: E402
from .workflows import validate_workflow  # noqa: E402

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]
MAX_MESSAGE_BYTES = 1024 * 1024
SERVER_INFO = {"name": "framewright-studio", "version": __version__}
_META_PREFIX = "io.modelcontextprotocol/"


class RPCError(ValueError):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


def _error(identity, code, message, data=None):
    response = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if identity is not None:
        response["id"] = identity
    if data is not None:
        response["error"]["data"] = data
    return response


def _valid_id(value):
    return type(value) is int or isinstance(value, str) and 1 <= len(value) <= 128


def _exact(value, required=(), optional=()):
    if (
        not isinstance(value, dict)
        or set(required) - value.keys()
        or value.keys() - set(required) - set(optional)
    ):
        raise RPCError(-32602, "Missing or unknown method parameters")


def _client_info(value):
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), str) and value[key] for key in ("name", "version")
    ):
        raise RPCError(-32602, "clientInfo requires name and version strings")


def _within(value, root, *, existing=False):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(
            "File paths must be explicit strings; dynamic path bindings are unsupported"
        )
    # Worker jobs use their own cwd; the same relative string could otherwise
    # pass this check here and resolve outside the configured root in Blender.
    if not Path(value).is_absolute():
        raise ValueError("MCP file paths must be absolute")
    path = Path(value).resolve(strict=existing)
    if not path.is_relative_to(root):
        raise ValueError("File path escapes its configured root")
    return path


class MCPServer:
    """Trusted local pipe endpoint with explicit worker configuration.

    asset_root scopes input blend/reference paths, not Blender's linked resources.
    This is not a filesystem sandbox; the process has its OS caller's authority.
    """

    def __init__(self, *, worker=None, asset_root=None):
        self.worker = worker
        self.asset_root = Path(asset_root).resolve() if asset_root is not None else None
        if worker is not None and (self.asset_root is None or not self.asset_root.is_dir()):
            raise ValueError("Worker mode requires an existing explicit asset_root")
        self.job_root = Path(worker.directory).resolve() if worker is not None else None
        self.legacy_initialized = False
        self.legacy_ready = False

    def _tools(self):
        tools = {
            "framewright_capabilities": (
                "List Framewright commands, schemas and limitations",
                obj(),
            ),
            "framewright_manifest_validate": (
                "Validate supplied asset evidence without reading reference files",
                obj({"manifest": JSON_OBJECT}, ["manifest"]),
            ),
            "framewright_workflow_validate": (
                "Validate a supplied workflow without running any step",
                obj({"workflow": JSON_OBJECT}, ["workflow"]),
            ),
        }
        if self.worker is not None:
            tools.update(
                {
                    "framewright_submit_job": (
                        "Submit an owned isolated Blender job; poll its job_id for completion and timeout enforcement",
                        obj(
                            {
                                "blend": string(32768),
                                "request": JSON_OBJECT,
                                "timeout": number(1, 3600),
                            },
                            ["blend", "request"],
                        ),
                    ),
                    "framewright_poll_job": (
                        "Poll an owned job and enforce its deadline",
                        obj({"job_id": string(128)}, ["job_id"]),
                    ),
                    "framewright_cancel_job": (
                        "Cancel only an owned job created by this worker",
                        obj({"job_id": string(128)}, ["job_id"]),
                    ),
                }
            )
        return tools

    def _guard_paths(self, request):
        command = request["command"]
        params = request["params"]
        if "$ref" in params and (
            command
            in {
                "asset.reference_intake",
                "surfaces.create_pbr_material",
                "asset.reference_board",
                "asset.export",
            }
            or COMMANDS.get(command, {}).get("effect") == "files"
        ):
            raise ValueError(
                "MCP filesystem command parameters must be explicit before job submission; "
                "whole-parameter bindings cannot be path-checked"
            )
        if command == "workflow.run":
            validate_workflow(params)
            for step in params["steps"]:
                self._guard_paths(step)
        elif command == "asset.reference_intake":
            _within(params["path"], self.asset_root, existing=True)
        elif command == "surfaces.create_pbr_material":
            for field in ("base_color_path", "roughness_path", "metallic_path", "normal_path"):
                if field in params:
                    _within(params[field], self.asset_root, existing=True)
        elif command == "asset.reference_board":
            from .reference_board import reference_location

            _within(params["output"], self.job_root)
            manifest = validate_manifest({"manifest": params["manifest"]})["manifest"]
            for reference in manifest["references"]:
                location = reference_location(reference["location"])
                if location["kind"] == "local":
                    _within(reference["location"], self.asset_root)
        elif command == "asset.export":
            _within(params["directory"], self.job_root)
            filename = params.get("filename", "asset")
            if (
                not isinstance(filename, str)
                or filename in {"", ".", ".."}
                or any(character in filename for character in ("/", "\\", ":"))
            ):
                raise ValueError("Export filename must be an explicit plain basename")
        elif COMMANDS.get(command, {}).get("effect") == "files":
            raise ValueError("This file-writing command has no MCP path policy yet")

    def _call_tool(self, name, arguments):
        tools = self._tools()
        if not isinstance(name, str) or name not in tools:
            raise RPCError(-32602, "Unknown or unavailable tool")
        try:
            _validate(arguments, tools[name][1], "arguments")
            if name == "framewright_capabilities":
                from .api import capabilities

                result = capabilities()
            elif name == "framewright_manifest_validate":
                result = validate_manifest(arguments)
            elif name == "framewright_workflow_validate":
                validate_workflow(arguments["workflow"])
                result = {
                    "valid": True,
                    "executed": False,
                    "steps": len(arguments["workflow"]["steps"]),
                }
            elif name == "framewright_submit_job":
                from .api import _validate_request

                _validate_request(arguments["request"])
                blend = _within(arguments["blend"], self.asset_root, existing=True)
                if not blend.is_file() or blend.suffix.lower() != ".blend":
                    raise ValueError("Input must be an existing .blend file")
                self._guard_paths(arguments["request"])
                result = self.worker.submit(
                    blend, arguments["request"], timeout=arguments.get("timeout", 300)
                )
            elif name == "framewright_poll_job":
                result = self.worker.poll(arguments["job_id"])
            else:
                result = self.worker.cancel(arguments["job_id"])
            return {
                "content": [{"type": "text", "text": canonical_json(result)}],
                "structuredContent": result,
                "isError": False,
            }
        except (ValueError, OSError, KeyError) as error:
            result = {"error": {"code": "OPERATION_REJECTED", "message": str(error)}}
            return {
                "content": [{"type": "text", "text": canonical_json(result)}],
                "structuredContent": result,
                "isError": True,
            }
        except Exception as error:
            print(f"Framewright MCP tool failed: {type(error).__name__}", file=sys.stderr)
            return {
                "content": [{"type": "text", "text": "Internal tool failure; inspect local logs"}],
                "isError": True,
            }

    def handle(self, message):
        identity = (
            message.get("id")
            if isinstance(message, dict) and _valid_id(message.get("id"))
            else None
        )
        try:
            if (
                not isinstance(message, dict)
                or set(message) - {"jsonrpc", "id", "method", "params"}
                or message.get("jsonrpc") != "2.0"
                or not isinstance(message.get("method"), str)
                or "id" in message
                and not _valid_id(message["id"])
            ):
                raise RPCError(-32600, "Invalid JSON-RPC request")
            canonical_json(message)
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise RPCError(-32602, "Method params must be an object")
            method = message["method"]
            if "id" not in message:
                if method == "notifications/initialized" and self.legacy_initialized:
                    self.legacy_ready = True
                # Completed submit calls have no in-flight RPC to cancel. Jobs use
                # the explicit cancel_job tool and their independent job_id.
                return None
            if method == "initialize":
                _exact(params, {"protocolVersion", "capabilities", "clientInfo"}, {"_meta"})
                if (
                    self.legacy_initialized
                    or not isinstance(params["protocolVersion"], str)
                    or not isinstance(params["capabilities"], dict)
                ):
                    raise RPCError(-32602, "Invalid or repeated legacy initialization")
                _client_info(params["clientInfo"])
                self.legacy_initialized = True
                return {
                    "jsonrpc": "2.0",
                    "id": identity,
                    "result": {
                        "protocolVersion": LEGACY_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": dict(SERVER_INFO),
                        "instructions": "Use allowlisted tools. Jobs are asynchronous; poll deadlines and cancel by job_id.",
                    },
                }
            metadata = params.get("_meta", {})
            if not isinstance(metadata, dict):
                raise RPCError(-32602, "_meta must be an object")
            version = metadata.get(_META_PREFIX + "protocolVersion")
            modern = version is not None
            if modern:
                if not isinstance(version, str):
                    raise RPCError(-32602, "Protocol version metadata must be a string")
                if version != MODERN_VERSION:
                    raise RPCError(
                        -32022,
                        "Unsupported protocol version",
                        {"supported": SUPPORTED_VERSIONS, "requested": version},
                    )
                if not isinstance(metadata.get(_META_PREFIX + "clientCapabilities"), dict):
                    raise RPCError(-32602, "Modern requests require clientCapabilities metadata")
                if _META_PREFIX + "clientInfo" in metadata:
                    _client_info(metadata[_META_PREFIX + "clientInfo"])
            elif not self.legacy_ready and method != "ping":
                raise RPCError(
                    -32602, "Required modern metadata or completed legacy initialization is missing"
                )
            clean = {key: value for key, value in params.items() if key != "_meta"}
            if method == "server/discover":
                _exact(clean)
                if not modern:
                    raise RPCError(-32602, "Discovery requires modern per-request metadata")
                result = {
                    "supportedVersions": SUPPORTED_VERSIONS,
                    "capabilities": {"tools": {}},
                    "instructions": "Local stdio authority only. No network listener or arbitrary-code tool. Poll owned jobs to enforce deadlines.",
                }
            elif method == "ping":
                _exact(clean)
                result = {}
            elif method == "tools/list":
                _exact(clean)
                result = {
                    "tools": [
                        {
                            "name": name,
                            "description": description,
                            "inputSchema": deepcopy(schema),
                            "annotations": {
                                "readOnlyHint": not name.endswith(
                                    ("submit_job", "cancel_job", "poll_job")
                                )
                            },
                        }
                        for name, (description, schema) in sorted(self._tools().items())
                    ]
                }
            elif method == "tools/call":
                _exact(clean, {"name"}, {"arguments"})
                result = self._call_tool(clean["name"], clean.get("arguments", {}))
            else:
                raise RPCError(-32601, "Method not found")
            if modern:
                result = {
                    **result,
                    "resultType": "complete",
                    "_meta": {_META_PREFIX + "serverInfo": dict(SERVER_INFO)},
                }
            return {"jsonrpc": "2.0", "id": identity, "result": result}
        except RPCError as error:
            return _error(identity, error.code, str(error), error.data)
        except (ValueError, TypeError, RecursionError):
            return _error(identity, -32600, "Request is not bounded finite JSON data")

    def close(self):
        if self.worker is not None:
            self.worker.close()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys")
        result[key] = value
    return result


def serve(server: MCPServer, source, destination):
    """Process newline-delimited UTF-8 JSON; close owned jobs on EOF/failure.

    This loop intentionally has no background polling thread. Hosts must call
    poll_job to enforce deadlines while stdin is idle; close cancels owned jobs.
    """
    try:
        while True:
            line = source.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE_BYTES:
                response = _error(None, -32700, "Message exceeds 1 MiB; closing transport")
                destination.write((canonical_json(response) + "\n").encode("utf-8"))
                destination.flush()
                break
            try:
                message = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_keys)
                canonical_json(message)
                response = server.handle(message)
            except (ValueError, UnicodeError, RecursionError):
                response = _error(None, -32700, "Invalid UTF-8 JSON message")
            if response is not None:
                encoded = (canonical_json(response) + "\n").encode("utf-8")
                if len(encoded) > MAX_MESSAGE_BYTES:
                    response = _error(
                        response.get("id"),
                        -32000,
                        "Response exceeds 1 MiB. Inspect owned job files when applicable; this does not undo completed work.",
                        {"limit_bytes": MAX_MESSAGE_BYTES},
                    )
                    encoded = (canonical_json(response) + "\n").encode("utf-8")
                destination.write(encoded)
                destination.flush()
    finally:
        server.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pure-only",
        action="store_true",
        help="Expose only capabilities and supplied-data validation",
    )
    parser.add_argument("--blender", type=Path, help="Explicit trusted Blender executable")
    parser.add_argument("--job-root", type=Path, help="Existing directory for owned job output")
    parser.add_argument(
        "--asset-root", type=Path, help="Existing root for input blend/reference files"
    )
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument(
        "--enable-rigify",
        action="store_true",
        help="Enable bundled Rigify inside owned background jobs only",
    )
    args = parser.parse_args(argv)
    if args.pure_only:
        if args.enable_rigify or any(
            value is not None for value in (args.blender, args.job_root, args.asset_root)
        ):
            parser.error("--pure-only cannot be combined with worker paths")
        server = MCPServer()
    else:
        if not all(value is not None for value in (args.blender, args.job_root, args.asset_root)):
            parser.error("Provide --blender, --job-root and --asset-root, or use --pure-only")
        from .worker import JobManager

        try:
            worker = JobManager(
                args.blender,
                args.job_root,
                max_concurrency=args.max_concurrency,
                enable_rigify=args.enable_rigify,
            )
            server = MCPServer(worker=worker, asset_root=args.asset_root)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    try:
        serve(server, sys.stdin.buffer, sys.stdout.buffer)
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
