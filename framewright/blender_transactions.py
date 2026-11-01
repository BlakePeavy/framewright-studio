"""Process-local plans and owned derivative rollback; never edit source meshes.

Tokens and fingerprints are intentionally bound to Blender ID identities in the
current process. Reopening a .blend does not restore authority to delete objects.
"""

from __future__ import annotations

import hashlib
import re
from uuid import uuid4

import bpy

from . import blender_adapter as adapter
from .provenance import canonical_json

_PLANS: dict[str, dict] = {}
_TRANSACTIONS: dict[str, dict] = {}
_GENERATIONS: dict[tuple[int, int], int] = {}
_TAG = "framewright_transaction_id"


def _params(params, fields):
    if not isinstance(params, dict) or set(params) != set(fields):
        raise ValueError("Missing or unknown transaction parameters")


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a SHA256 digest")


def _explicit_apply(params):
    if params.get("dry_run") is not False:
        raise ValueError("An explicit dry_run=false is required for this transaction")


def _identity(value):
    if value is None:
        return None
    return {"name": value.name_full, "session_uid": value.session_uid}


def _custom_value(value):
    if isinstance(value, bpy.types.ID):
        return _identity(value)
    if hasattr(value, "to_dict"):
        return {key: _custom_value(item) for key, item in value.to_dict().items()}
    if hasattr(value, "to_list"):
        return [_custom_value(item) for item in value.to_list()]
    if isinstance(value, dict):
        return {key: _custom_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_custom_value(item) for item in value]
    return value


def _custom_properties(value):
    return {key: _custom_value(value[key]) for key in value.keys()}


def _attribute_values(value):
    result = {}
    for prop in value.bl_rna.properties:
        if prop.identifier == "rna_type":
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            raise ValueError("Unsupported mesh attribute type prevents a reliable fingerprint")
        item = getattr(value, prop.identifier)
        result[prop.identifier] = list(item) if getattr(prop, "is_array", False) else item
    return result


def source_fingerprint(obj, context=None) -> str:
    """Stream a source/state digest without tessellating or modifying mesh data.

    Includes topology, coordinates, normals, attributes/UVs, transforms, material ID
    bindings, collections and custom properties. Shader graph/image contents are
    external shared data and are not certified by this geometry transaction.
    Selection and edit-visibility flags are excluded because they are UI state.
    """
    context = adapter._context(context)
    if obj.type != "MESH":
        raise ValueError("Transaction fingerprints require a mesh object")
    digest = hashlib.sha256()

    def feed(label, value):
        digest.update(canonical_json([label, value]).encode("utf-8"))
        digest.update(b"\n")

    transform_fields = (
        "location",
        "rotation_euler",
        "rotation_quaternion",
        "rotation_axis_angle",
        "scale",
        "delta_location",
        "delta_rotation_euler",
        "delta_rotation_quaternion",
        "delta_scale",
    )
    feed(
        "object",
        {
            "identity": _identity(obj),
            "mesh": _identity(obj.data),
            "rotation_mode": obj.rotation_mode,
            "transforms": {field: list(getattr(obj, field)) for field in transform_fields},
            "parent": _identity(obj.parent),
            "collections": sorted(collection.session_uid for collection in obj.users_collection),
            "hide_viewport": obj.hide_viewport,
            "hide_render": obj.hide_render,
            "hide_set": obj.hide_get(view_layer=context.view_layer),
            "modifiers": [[modifier.name, modifier.type] for modifier in obj.modifiers],
            "constraints": [[constraint.name, constraint.type] for constraint in obj.constraints],
            "vertex_groups": [[group.name, group.index] for group in obj.vertex_groups],
            "shape_keys": _identity(obj.data.shape_keys),
            "animated_object": obj.animation_data is not None,
            "animated_mesh": obj.data.animation_data is not None,
            "custom_properties": _custom_properties(obj),
        },
    )
    feed("mesh_properties", _custom_properties(obj.data))
    for vertex in obj.data.vertices:
        feed("vertex", list(vertex.co))
    for edge in obj.data.edges:
        feed("edge", list(edge.vertices))
    for polygon in obj.data.polygons:
        feed("polygon", [list(polygon.vertices), polygon.material_index, polygon.use_smooth])
    for slot in obj.material_slots:
        feed("material", [slot.link, _identity(slot.material)])
    for uv_layer in obj.data.uv_layers:
        feed("uv_layer", [uv_layer.name, uv_layer.active_render, uv_layer.active_clone])
        for point in uv_layer.data:
            feed("uv", list(point.uv))
    for attribute in sorted(obj.data.attributes, key=lambda item: item.name):
        if attribute.name.startswith((".select", ".hide")):
            continue
        feed("attribute", [attribute.name, attribute.domain, attribute.data_type])
        for point in attribute.data:
            feed("attribute_value", _attribute_values(point))
    feed("custom_normals", obj.data.has_custom_normals)
    if obj.data.has_custom_normals:
        for normal in obj.data.corner_normals:
            feed("corner_normal", list(normal.vector))
    return digest.hexdigest()


def _resolve_owned_object(scene, name, reference, pointer):
    try:
        matches = [obj for obj in scene.objects if obj.name == name]
        if len(matches) != 1:
            raise ValueError("Recorded object name is missing or ambiguous in this scene")
        current = matches[0]
        if current is None or current != reference or reference.as_pointer() != pointer:
            raise ValueError("Recorded object identity was removed, renamed or replaced")
        return current
    except ReferenceError as error:
        raise ValueError("Recorded owned object identity was removed or replaced") from error


def plan_remove_loose(params: dict, context=None) -> dict:
    _params(params, {"object_name"})
    if not isinstance(params["object_name"], str) or not params["object_name"]:
        raise ValueError("object_name must be a nonempty string")
    context = adapter._context(context)
    if sum(obj.name == params["object_name"] for obj in context.scene.objects) != 1:
        raise ValueError("Object name is missing or ambiguous in this scene")
    context, source, _ = adapter._repair_source(params["object_name"], context)
    preview = adapter.preview_remove_loose_vertices(source.name, context)
    fingerprint = source_fingerprint(source, context)
    # Blender can reuse memory addresses after ID deletion; session_uid cannot
    # accidentally grant a replacement object an old plan's authority.
    key = (context.scene.session_uid, source.session_uid)
    payload = {
        "schema_version": "1.0",
        "operation": "mesh.remove_loose_vertices",
        "source": source.name,
        "source_fingerprint": fingerprint,
        "scene_identity": str(key[0]),
        "object_identity": str(key[1]),
        "generation": _GENERATIONS.get(key, 0),
        "preview": preview,
    }
    token = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    result = {
        "schema_version": "1.0",
        "plan_token": token,
        "source": source.name,
        "source_fingerprint": fingerprint,
        "preview": preview,
        "dry_run": True,
        "scope": "current_blender_process",
    }
    if token not in _PLANS:
        _PLANS[token] = {
            "result": result,
            "source_ref": source,
            "source_pointer": source.as_pointer(),
            "scene_uid": key[0],
            "state": "pending",
            "key": key,
        }
    if _PLANS[token]["state"] != "pending":
        raise ValueError("This exact plan is already consumed or cancelled")
    return dict(result, preview=dict(preview))


def apply_plan(params: dict, context=None) -> dict:
    _params(params, {"plan_token", "source_fingerprint", "dry_run"})
    _explicit_apply(params)
    _digest(params["plan_token"], "plan_token")
    _digest(params["source_fingerprint"], "source_fingerprint")
    record = _PLANS.get(params["plan_token"])
    if record is None:
        raise ValueError("Unknown plan token; plans belong to the current Blender process")
    if record["state"] != "pending":
        raise ValueError("Plan was already consumed, applied or cancelled")
    context = adapter._context(context)
    if context.scene.session_uid != record["scene_uid"]:
        raise ValueError("Plan belongs to a different scene")
    plan = record["result"]
    source = _resolve_owned_object(
        context.scene, plan["source"], record["source_ref"], record["source_pointer"]
    )
    adapter._repair_source(source.name, context)
    if params["source_fingerprint"] != plan["source_fingerprint"]:
        raise ValueError("Supplied source fingerprint does not match the plan")
    if source_fingerprint(source, context) != plan["source_fingerprint"]:
        raise ValueError("Source changed; this repair plan is stale")
    derivative = None
    derivative_mesh = None
    try:
        result = adapter.apply_remove_loose_vertices(source.name, context)
        derivative = context.scene.objects[result["derivative"]]
        derivative_mesh = derivative.data
        transaction_id = str(uuid4())
        derivative[_TAG] = transaction_id
        derivative_mesh[_TAG] = transaction_id
        derivative["framewright_asset_id"] = str(uuid4())
        derivative["framewright_source_fingerprint"] = plan["source_fingerprint"]
        derivative_digest = source_fingerprint(derivative, context)
        if source_fingerprint(source, context) != plan["source_fingerprint"]:
            raise ValueError("Source changed during repair; derivative was discarded")
        response = {
            **result,
            "transaction_id": transaction_id,
            "state": "applied",
            "asset_id": derivative["framewright_asset_id"],
            "plan_token": params["plan_token"],
            "source_fingerprint": plan["source_fingerprint"],
            "derivative_fingerprint": derivative_digest,
            "scope": "current_blender_process",
        }
        _TRANSACTIONS[transaction_id] = {
            "result": response,
            "state": "applied",
            "scene_uid": context.scene.session_uid,
            "derivative_ref": derivative,
            "derivative_pointer": derivative.as_pointer(),
            "mesh_pointer": derivative_mesh.as_pointer(),
        }
        record["state"] = "applied"
        _GENERATIONS[record["key"]] = _GENERATIONS.get(record["key"], 0) + 1
        return dict(response)
    except Exception:
        # The adapter cleans failures within creation. Once returned, these exact
        # references are exclusively owned by this uncommitted transaction.
        if derivative is not None:
            bpy.data.objects.remove(derivative, do_unlink=True)
        if derivative_mesh is not None and derivative_mesh.users == 0:
            bpy.data.meshes.remove(derivative_mesh)
        raise


def cancel_plan(params: dict, context=None) -> dict:
    _params(params, {"plan_token"})
    _digest(params["plan_token"], "plan_token")
    adapter._context(context)
    record = _PLANS.get(params["plan_token"])
    if record is None or record["state"] != "pending":
        raise ValueError("Only a pending plan in this process can be cancelled")
    record["state"] = "cancelled"
    _GENERATIONS[record["key"]] = _GENERATIONS.get(record["key"], 0) + 1
    return {"plan_token": params["plan_token"], "state": "cancelled", "dry_run": True}


def rollback_plan(params: dict, context=None) -> dict:
    _params(params, {"transaction_id", "dry_run"})
    _explicit_apply(params)
    if not isinstance(params["transaction_id"], str):
        raise ValueError("transaction_id must be a string")
    record = _TRANSACTIONS.get(params["transaction_id"])
    if record is None or record["state"] != "applied":
        raise ValueError("Unknown, foreign or already rolled-back transaction")
    context = adapter._context(context)
    if context.scene.session_uid != record["scene_uid"]:
        raise ValueError("Transaction belongs to a different scene")
    result = record["result"]
    derivative = _resolve_owned_object(
        context.scene, result["derivative"], record["derivative_ref"], record["derivative_pointer"]
    )
    if derivative.type != "MESH" or derivative.data is None:
        raise ValueError("Derivative no longer has the transaction's owned mesh")
    if (
        derivative.data.as_pointer() != record["mesh_pointer"]
        or derivative.get(_TAG) != params["transaction_id"]
        or derivative.data.get(_TAG) != params["transaction_id"]
    ):
        raise ValueError("Derivative no longer has the transaction's exact owned identity")
    if derivative.data.users != 1:
        raise ValueError("Derivative mesh is shared; rollback cannot delete shared data")
    if source_fingerprint(derivative, context) != result["derivative_fingerprint"]:
        raise ValueError("Derivative changed since apply; rollback refused")
    mesh = derivative.data
    bpy.data.objects.remove(derivative, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    record["state"] = "rolled_back"
    return {
        "transaction_id": params["transaction_id"],
        "state": "rolled_back",
        "source": result["source"],
        "removed_derivative": result["derivative"],
        "dry_run": False,
    }
