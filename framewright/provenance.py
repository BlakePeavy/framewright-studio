"""Versioned local asset evidence. Hashes prove bytes, not ownership or quality."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

SCHEMA_VERSION = "1.0"
MAX_MANIFEST_BYTES = 1024 * 1024
VERIFICATION_STAGES = (
    "source_reviewed",
    "exports_verified",
    "native_imported",
    "world_placed",
    "cold_verified",
    "runtime_bound",
    "visually_accepted",
)
_STATUSES = {"not_checked", "passed", "failed", "not_applicable"}
_ORIGINS = {"unknown", "real_photo", "generated", "user_authored", "external_asset"}
_MANIFEST_FIELDS = {
    "schema_version",
    "asset_id",
    "name",
    "source_sha256",
    "recipe",
    "references",
    "lineage",
    "verification",
    "expected_views",
}
_REFERENCE_FIELDS = {
    "reference_id",
    "label",
    "origin",
    "location",
    "license",
    "sha256",
    "views",
    "landmarks",
}


def _object(value, required, optional=(), label="parameters"):
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object with string keys")
    if not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError(f"{label} has missing or unknown fields")


def _text(value, label, allow_empty=False):
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise ValueError(f"{label} must be a string of at most 4096 characters")
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} cannot be empty")
    return value


def _strings(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    for item in value:
        _text(item, label)
    if len(set(value)) != len(value):
        raise ValueError(f"{label} cannot contain duplicates")


def _uuid(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a canonical UUID") from error
    if str(parsed) != value or parsed.int == 0:
        raise ValueError(f"{label} must be a canonical nonzero UUID")


def _hash(value, label, nullable=True):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase SHA256 digest or null")


def _json_value(value, depth=0):
    if depth > 64:
        raise ValueError("JSON nesting exceeds 64 levels")
    if value is None or isinstance(value, str) or type(value) in {bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("Values must be finite JSON values with string object keys")


def canonical_json(value) -> str:
    """Deterministic UTF-8 JSON representation; not an external RFC 8785 claim."""
    _json_value(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _copy(value):
    return json.loads(canonical_json(value))


def _recipe(value):
    _object(value, {"tool", "version", "operation", "parameters"}, label="recipe")
    for field in ("tool", "version", "operation"):
        _text(value[field], f"recipe.{field}")
    if not isinstance(value["parameters"], dict):
        raise ValueError("recipe.parameters must be a JSON object")
    canonical_json(value["parameters"])


def _reference(value):
    _object(value, _REFERENCE_FIELDS, label="reference")
    _uuid(value["reference_id"], "reference_id")
    _text(value["label"], "reference label")
    _text(value["location"], "reference location", allow_empty=True)
    _text(value["license"], "reference license")
    if not isinstance(value["origin"], str) or value["origin"] not in _ORIGINS:
        raise ValueError(
            "reference origin is unknown, real_photo, generated, user_authored or external_asset"
        )
    _hash(value["sha256"], "reference sha256")
    _strings(value["views"], "reference views")
    if not isinstance(value["landmarks"], list):
        raise ValueError("landmarks must be an array")
    landmark_ids = set()
    for landmark in value["landmarks"]:
        _object(landmark, {"name", "view", "position"}, label="landmark")
        _text(landmark["name"], "landmark name")
        if landmark["view"] not in value["views"]:
            raise ValueError("landmark view must be listed in reference views")
        position = landmark["position"]
        if (
            not isinstance(position, list)
            or len(position) != 2
            or any(
                type(component) not in {int, float}
                or not math.isfinite(component)
                or not 0 <= component <= 1
                for component in position
            )
        ):
            raise ValueError("landmark position must contain two finite normalized coordinates")
        identity = (landmark["view"], landmark["name"])
        if identity in landmark_ids:
            raise ValueError("landmark names must be unique within each view")
        landmark_ids.add(identity)


def _manifest(value):
    _object(value, _MANIFEST_FIELDS, label="manifest")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported manifest schema_version")
    _uuid(value["asset_id"], "asset_id")
    _text(value["name"], "asset name")
    _hash(value["source_sha256"], "source_sha256")
    _recipe(value["recipe"])
    _strings(value["expected_views"], "expected_views")
    if not isinstance(value["references"], list) or not isinstance(value["lineage"], list):
        raise ValueError("references and lineage must be arrays")
    reference_ids = set()
    for reference in value["references"]:
        _reference(reference)
        if reference["reference_id"] in reference_ids:
            raise ValueError("Duplicate reference identity")
        reference_ids.add(reference["reference_id"])
    parent_ids = set()
    for parent in value["lineage"]:
        _object(parent, {"asset_id", "manifest_sha256", "relation"}, label="lineage parent")
        _uuid(parent["asset_id"], "parent asset_id")
        _hash(parent["manifest_sha256"], "parent manifest_sha256", nullable=False)
        if parent["relation"] != "derived_from":
            raise ValueError("Unsupported lineage relation")
        if parent["asset_id"] == value["asset_id"] or parent["asset_id"] in parent_ids:
            raise ValueError("Lineage cannot reference self or duplicate a parent")
        parent_ids.add(parent["asset_id"])
    _object(value["verification"], set(VERIFICATION_STAGES), label="verification")
    for state in value["verification"].values():
        _verification(state)
    if len(canonical_json(value).encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds the 1 MiB limit")
    return value


def _verification(value):
    _object(value, {"status", "evidence"}, label="verification state")
    if not isinstance(value["status"], str) or value["status"] not in _STATUSES:
        raise ValueError("Unknown verification status")
    _strings(value["evidence"], "verification evidence")
    if value["status"] in {"passed", "failed", "not_applicable"} and not value["evidence"]:
        raise ValueError("A checked verification state requires explicit evidence")


def create_manifest(params: dict) -> dict:
    _object(
        params, {"name"}, {"asset_id", "source_sha256", "recipe", "references", "expected_views"}
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": params.get("asset_id", str(uuid4())),
        "name": params["name"],
        "source_sha256": params.get("source_sha256"),
        "recipe": params.get(
            "recipe",
            {"tool": "unknown", "version": "unknown", "operation": "unknown", "parameters": {}},
        ),
        "references": params.get("references", []),
        "lineage": [],
        "verification": {
            stage: {"status": "not_checked", "evidence": []} for stage in VERIFICATION_STAGES
        },
        "expected_views": params.get("expected_views", []),
    }
    return _copy(_manifest(manifest))


def create_reference(params: dict) -> dict:
    _object(params, {"label"}, _REFERENCE_FIELDS - {"label"})
    reference = {
        "reference_id": params.get("reference_id", str(uuid4())),
        "label": params["label"],
        "origin": params.get("origin", "unknown"),
        "location": params.get("location", ""),
        "license": params.get("license", "unknown"),
        "sha256": params.get("sha256"),
        "views": params.get("views", []),
        "landmarks": params.get("landmarks", []),
    }
    _reference(reference)
    return _copy(reference)


def manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(canonical_json(_manifest(manifest)).encode("utf-8")).hexdigest()


def validate_manifest(params: dict) -> dict:
    _object(params, {"manifest"})
    manifest = _copy(_manifest(params["manifest"]))
    available = {view for reference in manifest["references"] for view in reference["views"]}
    return {
        "valid": True,
        "manifest": manifest,
        "sha256": manifest_sha256(manifest),
        "missing_views": sorted(set(manifest["expected_views"]) - available),
    }


def derive_manifest(params: dict) -> dict:
    _object(params, {"parent", "name"}, {"source_sha256", "recipe"})
    parent = _manifest(params["parent"])
    options = {key: value for key, value in params.items() if key != "parent"}
    options.update(references=parent["references"], expected_views=parent["expected_views"])
    child = create_manifest(options)
    child["lineage"] = [
        {
            "asset_id": parent["asset_id"],
            "manifest_sha256": manifest_sha256(parent),
            "relation": "derived_from",
        }
    ]
    return _copy(_manifest(child))


def add_reference(params: dict) -> dict:
    _object(params, {"manifest", "reference"})
    manifest = _copy(_manifest(params["manifest"]))
    _reference(params["reference"])
    manifest["references"].append(_copy(params["reference"]))
    return _copy(_manifest(manifest))


def record_verification(params: dict) -> dict:
    _object(params, {"manifest", "stage", "status", "evidence"})
    if not isinstance(params["stage"], str) or params["stage"] not in VERIFICATION_STAGES:
        raise ValueError("Unknown verification stage")
    manifest = _copy(_manifest(params["manifest"]))
    state = {"status": params["status"], "evidence": params["evidence"]}
    _verification(state)
    manifest["verification"][params["stage"]] = state
    return _copy(_manifest(manifest))


def hash_file(path: Path | str, max_bytes=512 * 1024 * 1024) -> str:
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024 * 1024:
        raise ValueError("max_bytes must be an integer from 1 to 1 GiB")
    path = Path(path)
    before = path.stat()
    if not path.is_file() or before.st_size > max_bytes:
        raise ValueError("Reference must be a regular file within the configured size limit")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Reference exceeded the configured size limit while reading")
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError("Reference changed while hashing; retry with a stable source")
    return digest.hexdigest()


def intake_reference(params: dict) -> dict:
    _object(params, {"path", "label"}, {"origin", "license", "views", "landmarks", "max_bytes"})
    _text(params["path"], "path")
    path = Path(params["path"]).resolve(strict=True)
    digest = hash_file(path, params.get("max_bytes", 512 * 1024 * 1024))
    options = {key: value for key, value in params.items() if key not in {"path", "max_bytes"}}
    options.update(
        location=str(path),
        sha256=digest,
        reference_id=str(uuid5(NAMESPACE_URL, f"framewright-reference:{path}:{digest}")),
    )
    return create_reference(options)


def save_manifest(path: Path | str, manifest: dict) -> None:
    content = canonical_json(_manifest(manifest)) + "\n"
    with Path(path).open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def load_manifest(path: Path | str) -> dict:
    with Path(path).open("rb") as source:
        content = source.read(MAX_MANIFEST_BYTES + 1)
    if len(content) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds the 1 MiB limit")
    value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    return _copy(_manifest(value))
