"""Bounded, replay-safe in-process workflows over the same allowlisted API."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from copy import deepcopy

from .commands import BASELINE_SCHEMAS, COMMANDS, _validate, command_mutates, command_schema, effect

_RUNS = OrderedDict()
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def clear_run_cache():
    _RUNS.clear()


def _stub(schema):
    kind = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "string":
        return "x" * schema.get("minLength", min(1, schema.get("maxLength", 1)))
    if kind in {"integer", "number"}:
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    if kind == "array":
        return [_stub(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if kind == "object":
        properties = schema.get("properties", {})
        return {name: _stub(properties.get(name, {})) for name in schema.get("required", [])}
    return {}


def _bind(value, earlier, *, responses=None, schema=None):
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("Bindings require exactly one string $ref")
            parts = value["$ref"].split(".")
            if len(parts) < 2 or parts[0] not in earlier:
                raise ValueError("Binding must reference an earlier step")
            if responses is None:
                return _stub(schema or {})
            result = responses[parts[0]]
            for part in parts[1:]:
                if not isinstance(result, dict) or part not in result:
                    raise ValueError("Binding refers to an unavailable result field")
                result = result[part]
            return deepcopy(result)
        return {
            key: _bind(
                item,
                earlier,
                responses=responses,
                schema=(schema or {}).get("properties", {}).get(key, {}),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _bind(item, earlier, responses=responses, schema=(schema or {}).get("items", {}))
            for item in value
        ]
    return value


def validate_workflow(params):
    if (
        not isinstance(params, dict)
        or set(params) - {"run_id", "steps", "dry_run"}
        or not {"run_id", "steps"} <= params.keys()
    ):
        raise ValueError("Workflow requires run_id and steps; optional dry_run")
    if not isinstance(params["run_id"], str) or not _ID.fullmatch(params["run_id"]):
        raise ValueError("run_id must be 1..80 letters, digits, hyphens or underscores")
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be a boolean")
    steps = params["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError("Workflow must have 1..32 steps")
    if len(json.dumps(params, allow_nan=False)) > 1024 * 1024:
        raise ValueError("Workflow exceeds 1 MiB")
    earlier = set()
    for step in steps:
        if (
            not isinstance(step, dict)
            or not {"id", "command", "params"} <= step.keys()
            or step.keys() - {"id", "command", "params", "require"}
        ):
            raise ValueError("Each step requires id, command and params; optional require")
        requirements = step.get("require", [])
        if not isinstance(requirements, list) or len(requirements) > 8:
            raise ValueError("Step require must be an array of at most eight equality checks")
        for check in requirements:
            if (
                not isinstance(check, dict)
                or set(check) != {"path", "equals"}
                or not isinstance(check["path"], str)
                or not re.fullmatch(r"result(?:\.[A-Za-z][A-Za-z0-9_]{0,79}){1,8}", check["path"])
                or type(check["equals"]) not in (str, bool, int, float, type(None))
            ):
                raise ValueError("require checks need a result field path and scalar equals value")
        if (
            not isinstance(step["id"], str)
            or not _ID.fullmatch(step["id"])
            or step["id"] in earlier
        ):
            raise ValueError("Step ids must be valid and unique")
        command = step["command"]
        if (
            not isinstance(command, str)
            or command not in COMMANDS
            and command not in BASELINE_SCHEMAS
            or command.startswith(("workflow.", "worker.", "transport."))
        ):
            raise ValueError("Unsupported or recursive workflow command")
        schema = command_schema(command)
        substituted = _bind(step["params"], earlier, schema=schema)
        _validate(substituted, schema)
        if command == "scene.validate":
            from .api import resolve_profile

            resolve_profile(substituted)
        earlier.add(step["id"])


def run_workflow(params, context=None, *, dispatch_fn=None, cancelled=None):
    """Validate everything before executing; preserve all per-step outcomes.

    A workflow is not an atomic transaction. Previous successful derivatives remain
    if a later step fails. Results identify partial success for explicit rollback.
    Run-id replay protection lasts for the current process (up to 128 cached runs).
    """
    validate_workflow(params)
    steps = params["steps"]
    run_id = params["run_id"]
    if params.get("dry_run", True):
        return {
            "run_id": run_id,
            "dry_run": True,
            "status": "validated",
            "steps": [
                {"id": s["id"], "command": s["command"], "effect": effect(s["command"])}
                for s in steps
            ],
        }
    digest = hashlib.sha256(
        json.dumps(params, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    if run_id in _RUNS:
        old_hash, old_result = _RUNS[run_id]
        if old_hash != digest:
            raise ValueError("run_id was already used for a different workflow")
        return {**deepcopy(old_result), "replayed": True}
    if dispatch_fn is None:
        from .api import dispatch

        dispatch_fn = dispatch
    result = {
        "run_id": run_id,
        "dry_run": False,
        "status": "running",
        "replayed": False,
        "steps": [],
        "atomic": False,
    }
    _RUNS[run_id] = (digest, result)
    if len(_RUNS) > 128:
        _RUNS.popitem(last=False)
    responses = {}
    try:
        for step in steps:
            if cancelled and cancelled():
                result["status"] = "cancelled"
                break
            arguments = _bind(step["params"], set(responses), responses=responses)
            if command_mutates(step["command"]):
                arguments.setdefault("dry_run", False)
            response = dispatch_fn(
                {
                    "schema_version": "1.0",
                    "request_id": step["id"],
                    "command": step["command"],
                    "params": arguments,
                }
            )
            responses[step["id"]] = response
            result["steps"].append({"id": step["id"], "response": response})
            if not response["ok"]:
                result["status"] = "failed"
                break
            for check in step.get("require", []):
                actual = response
                found = True
                for part in check["path"].split("."):
                    if not isinstance(actual, dict) or part not in actual:
                        found = False
                        actual = None
                        break
                    actual = actual[part]
                expected = check["equals"]
                if not found or type(actual) is not type(expected) or actual != expected:
                    result["steps"][-1]["gate_failure"] = {
                        "path": check["path"],
                        "expected": expected,
                        "actual": actual,
                        "field_present": found,
                    }
                    result["status"] = "failed"
                    break
            if result["status"] == "failed":
                break
        else:
            result["status"] = "completed"
    except Exception as error:
        result["status"] = "failed"
        result["error"] = {"code": "WORKFLOW_ERROR", "message": str(error)}
    return deepcopy(result)
