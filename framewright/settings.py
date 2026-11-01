"""Versioned settings and defensive saved-report parsing."""

import json
from copy import deepcopy

from .core import PROFILES


def parse_saved_report(text):
    if not isinstance(text, str) or len(text) > 16 * 1024 * 1024:
        return None
    try:
        report = json.loads(text)
    except ValueError:
        return None
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != "1.0"
        or not isinstance(report.get("findings"), list)
    ):
        return None
    for item in report["findings"]:
        if not isinstance(item, dict):
            return None
        if not all(isinstance(item.get(key), str) for key in ("rule_id", "severity", "message")):
            return None
        if item.get("object_name") is not None and not isinstance(item["object_name"], str):
            return None
    return report


def migrate_settings(settings):
    if not isinstance(settings, dict) or set(settings) - {
        "schema_version",
        "profile",
        "triangle_limit",
        "texture_target",
        "texture_max",
    }:
        raise ValueError("Invalid settings object")
    version = settings.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported settings version")
    result = {
        "schema_version": 2,
        "profile": "realtime_high",
        "triangle_limit": 0,
        "texture_target": -1,
        "texture_max": 0,
        **deepcopy(settings),
    }
    result["schema_version"] = 2
    if version == 1 and result["texture_target"] == 0:
        result["texture_target"] = -1
    if not isinstance(result["profile"], str) or result["profile"] not in PROFILES:
        raise ValueError("Unknown profile")
    for field, low, high in [
        ("triangle_limit", 0, 100000000),
        ("texture_target", -1, 65536),
        ("texture_max", 0, 65536),
    ]:
        if type(result[field]) is not int or not low <= result[field] <= high:
            raise ValueError(f"Invalid {field}")
    profile = PROFILES[result["profile"]]
    target = profile.texture_target if result["texture_target"] == -1 else result["texture_target"]
    maximum = result["texture_max"] or profile.max_texture_resolution
    if target > maximum:
        raise ValueError("Texture target exceeds maximum")
    return result


def migrate_request(params):
    if not isinstance(params, dict) or set(params) != {"settings"}:
        raise ValueError("Expected settings only")
    return migrate_settings(params["settings"])
