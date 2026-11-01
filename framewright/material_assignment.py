"""Explicit material-slot assignments on independent hidden mesh derivatives."""

from __future__ import annotations

import json
from uuid import uuid4

from .rigging import checked_context, discard_derivative, hidden_derivative, scene_object


def _parameters(params):
    required = {"object_name", "material_name", "slot_indices"}
    if (
        not isinstance(params, dict)
        or not required <= params.keys()
        or params.keys() - required - {"dry_run"}
    ):
        raise ValueError(
            "Material assignment requires object_name, material_name and slot_indices; optional dry_run"
        )
    for name in ("object_name", "material_name"):
        value = params[name]
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not value.isprintable():
            raise ValueError(
                f"{name} must be a nonempty exact printable name up to 1024 characters"
            )
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be a boolean")
    indices = params["slot_indices"]
    if (
        not isinstance(indices, list)
        or not 1 <= len(indices) <= 128
        or any(type(index) is not int or not 0 <= index <= 127 for index in indices)
    ):
        raise ValueError("slot_indices requires 1..128 integers from 0 to 127")
    if len(set(indices)) != len(indices):
        raise ValueError("slot_indices must be unique")
    return sorted(indices)


def _assign_slots(derivative, material, indices):
    if not derivative.material_slots:
        derivative.data.materials.append(material)
    else:
        for index in indices:
            # The inherited slot link selects the independent mesh DATA pointer
            # or copied OBJECT pointer; neither path edits the source slot.
            derivative.material_slots[index].material = material


def assign_material(params, context=None):
    """Validate first, preserve base mesh/rig state, and change only chosen slots."""
    indices = _parameters(params)
    context = checked_context(context)
    import bpy

    source = scene_object(context, params["object_name"], "MESH")
    if (
        source.library
        or source.override_library
        or source.data.library
        or source.data.override_library
    ):
        raise ValueError(
            "Material assignment requires a local mesh object and data without library overrides"
        )
    matches = [
        material for material in bpy.data.materials if material.name == params["material_name"]
    ]
    if len(matches) != 1:
        raise ValueError("Material name is missing or ambiguous")
    material = matches[0]
    count = len(source.material_slots)
    if count != len(source.data.materials) or any(
        slot.link not in {"DATA", "OBJECT"} for slot in source.material_slots
    ):
        raise ValueError("Inconsistent material-slot layout is unsupported")
    if (count == 0 and indices != [0]) or (count and indices[-1] >= count):
        raise ValueError(
            "Selected slot index is outside the mesh slots; an empty mesh accepts only [0]"
        )
    if any(polygon.material_index >= max(count, 1) for polygon in source.data.polygons):
        raise ValueError("Source polygon material indices are inconsistent with its slots")
    changes = [
        {
            "index": index,
            "link": source.material_slots[index].link if count else "DATA",
            "previous_material": source.material_slots[index].material.name
            if count and source.material_slots[index].material
            else None,
            "material": material.name,
        }
        for index in indices
    ]
    result = {
        "schema_version": "1.0",
        "dry_run": params.get("dry_run", True),
        "source": source.name,
        "material": material.name,
        "slot_indices": indices,
        "changes": changes,
        "source_preserved": True,
        "visual_acceptance": False,
        "limits": [
            "Base mesh slots are assigned; modifiers and existing skin/parent/action references are retained",
            "The existing material is shared without editing its nodes, images or settings",
            "UV suitability, shader compatibility and visual quality require separate review",
        ],
    }
    if result["dry_run"]:
        return result
    derivative = hidden_derivative(source, context, "Material")
    try:
        _assign_slots(derivative, material, indices)
        assignment_id = str(uuid4())
        derivative["framewright_material_assignment"] = json.dumps(
            {
                "schema_version": "1.0",
                "assignment_id": assignment_id,
                "source": source.name,
                "changes": changes,
            },
            sort_keys=True,
        )
        result.update(derivative=derivative.name, assignment_id=assignment_id, hidden=True)
        return result
    except Exception:
        discard_derivative(derivative)
        raise
