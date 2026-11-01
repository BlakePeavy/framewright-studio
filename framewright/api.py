"""Versioned, provider-neutral command API. No sockets, code execution, or implicit edits."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from typing import Any, Protocol

from . import __version__
from .commands import (
    BASELINE_SCHEMAS,
    COMMANDS,
    PROFILE_FLAGS,
    PROFILE_LIMITS,
    command_metadata,
    invoke,
    validate_params,
)
from .core import PROFILES, QualityProfile, SceneSnapshot, validate_scene

SCHEMA_VERSION = "1.0"
_LOG = logging.getLogger(__name__)
_LIMITS = PROFILE_LIMITS
_FLAGS = PROFILE_FLAGS
_PARAMS = {
    "capabilities": set(),
    "scene.inspect": set(),
    "scene.validate": {"profile", "overrides"},
    "mesh.remove_loose_vertices": {"object_name", "dry_run"},
}


class Adapter(Protocol):
    def capture_scene(self) -> SceneSnapshot: ...

    def preview_remove_loose_vertices(self, object_name: str) -> dict: ...

    def apply_remove_loose_vertices(self, object_name: str) -> dict: ...


class RequestError(ValueError):
    """An invalid request, rejected before Blender is accessed."""


def resolve_profile(params: dict) -> QualityProfile:
    """Validate per-request settings without mutating shared profiles."""
    name = params.get("profile", "realtime_high")
    if not isinstance(name, str) or name not in PROFILES:
        raise RequestError("Unknown quality profile; use capabilities to list available profiles")
    overrides = params.get("overrides", {})
    if not isinstance(overrides, dict):
        raise RequestError("overrides must be an object")
    for key, value in overrides.items():
        if key in _LIMITS:
            lower, upper = _LIMITS[key]
            if type(value) is not int or not lower <= value <= upper:
                raise RequestError(f"{key} must be an integer between {lower} and {upper}")
        elif key in _FLAGS:
            if type(value) is not bool:
                raise RequestError(f"{key} must be a boolean")
        else:
            raise RequestError("Unknown profile override")
    profile = replace(PROFILES[name], **overrides)
    if profile.texture_target > profile.max_texture_resolution:
        raise RequestError("texture_target cannot exceed max_texture_resolution")
    return profile


def capabilities() -> dict:
    result = {
        "schema_version": SCHEMA_VERSION,
        "extension_version": __version__,
        "commands": [
            {"name": "capabilities", "mutates": False, "params": {}},
            {"name": "scene.inspect", "mutates": False, "params": {}},
            {
                "name": "scene.validate",
                "mutates": False,
                "params": {
                    "profile": "profile id; default realtime_high",
                    "overrides": "optional settings object",
                },
            },
            {
                "name": "mesh.remove_loose_vertices",
                "mutates": True,
                "params": {
                    "object_name": "exact name in active scene",
                    "dry_run": "boolean; default true",
                },
                "preserves_source": True,
                "replay_safe": False,
            },
        ]
        + command_metadata(),
        "profiles": {name: asdict(profile) for name, profile in sorted(PROFILES.items())},
        "override_limits": {
            name: {"minimum": low, "maximum": high} for name, (low, high) in _LIMITS.items()
        },
        "override_flags": list(_FLAGS),
        "limitations": [
            "Structural preflight is not visual acceptance or a claim of AAA quality",
            "Scene preflight inspects base geometry; dedicated diagnostics inspect evaluated output with explicit sampling limits",
            "Texture targets are flexible review hints; resolution alone does not establish material quality",
            "All Blender operations must execute on the main thread",
            "request_id is correlation only; repeated explicit repairs create separate derivatives",
        ],
    }
    for entry in result["commands"]:
        if entry["name"] in BASELINE_SCHEMAS:
            from copy import deepcopy

            entry["input_schema"] = deepcopy(BASELINE_SCHEMAS[entry["name"]])
    return result


def _validate_request(request: Any) -> tuple[str, str, dict]:
    if not isinstance(request, dict):
        raise RequestError("Request must be a JSON object")
    required = {"schema_version", "request_id", "command", "params"}
    if set(request) != required:
        raise RequestError(
            "Request requires exactly schema_version, request_id, command and params"
        )
    if request["schema_version"] != SCHEMA_VERSION:
        raise RequestError("Unsupported schema_version; expected 1.0")
    request_id = request["request_id"]
    if (
        not isinstance(request_id, str)
        or not 1 <= len(request_id) <= 128
        or not request_id.isprintable()
    ):
        raise RequestError("request_id must contain 1 to 128 printable characters")
    command = request["command"]
    if not isinstance(command, str) or command not in _PARAMS and command not in COMMANDS:
        raise RequestError("Unknown command; use capabilities to discover supported commands")
    params = request["params"]
    if command in COMMANDS:
        validate_params(command, params)
        return request_id, command, params
    if not isinstance(params, dict) or set(params) - _PARAMS[command]:
        raise RequestError("Invalid or unknown command parameters")
    validate_params(command, params)
    if command == "scene.validate":
        resolve_profile(params)
    if command == "mesh.remove_loose_vertices":
        name = params.get("object_name")
        if not isinstance(name, str) or not 1 <= len(name) <= 1024 or "\x00" in name:
            raise RequestError("object_name must be a nonempty Blender object name")
        if type(params.get("dry_run", True)) is not bool:
            raise RequestError("dry_run must be a boolean")
    return request_id, command, params


def _response(request_id: str | None, *, result=None, error=None) -> dict:
    envelope = {"schema_version": SCHEMA_VERSION, "request_id": request_id, "ok": error is None}
    envelope["error" if error else "result"] = error if error else result
    # Normalize tuples for consumers using dicts directly, and reject non-finite numbers.
    return json.loads(json.dumps(envelope, allow_nan=False))


def dispatch(request: Any, adapter: Adapter | None = None) -> dict:
    """Run one command. Validation always happens before adapter access.

    In Blender: ``dispatch(request)``. Tests may inject an adapter. This function is
    an in-process API, not a security sandbox for the calling Python interpreter.
    """
    request_id = None
    if isinstance(request, dict):
        candidate = request.get("request_id")
        if isinstance(candidate, str) and 1 <= len(candidate) <= 128 and candidate.isprintable():
            request_id = candidate
    try:
        request_id, command, params = _validate_request(request)
    except (RequestError, ValueError, TypeError) as error:
        return _response(request_id, error={"code": "INVALID_REQUEST", "message": str(error)})
    try:
        if command == "capabilities":
            return _response(request_id, result=capabilities())
        if command in COMMANDS:
            try:
                return _response(request_id, result=invoke(command, params))
            except ModuleNotFoundError as error:
                if error.name in {"bpy", "bmesh", "mathutils"}:
                    return _response(
                        request_id,
                        error={
                            "code": "BLENDER_REQUIRED",
                            "message": "Run this command inside Blender on its main thread",
                        },
                    )
                raise
        if adapter is None:
            try:
                from . import blender_adapter
            except ModuleNotFoundError as error:
                if error.name in {"bpy", "bmesh"}:
                    return _response(
                        request_id,
                        error={
                            "code": "BLENDER_REQUIRED",
                            "message": "Run this command inside Blender on its main thread",
                        },
                    )
                raise
            adapter = blender_adapter
        if command == "scene.inspect":
            result = asdict(adapter.capture_scene())
        elif command == "scene.validate":
            profile = resolve_profile(params)
            result = validate_scene(adapter.capture_scene(), profile).to_dict()
            result["settings"] = asdict(profile)
        elif params.get("dry_run", True):
            result = adapter.preview_remove_loose_vertices(params["object_name"])
        else:
            result = adapter.apply_remove_loose_vertices(params["object_name"])
        return _response(request_id, result=result)
    except (ValueError, KeyError) as error:
        return _response(request_id, error={"code": "OPERATION_REJECTED", "message": str(error)})
    except Exception:
        _LOG.exception("Framewright command failed: %s", command)
        return _response(
            request_id,
            error={
                "code": "INTERNAL_ERROR",
                "message": "Operation failed; inspect the local Blender console for details",
            },
        )
