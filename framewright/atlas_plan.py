"""Blender-independent admission for a four-map material atlas on owned copies."""

from __future__ import annotations

ENCODING_CHUNK_PIXELS = 65_536
ENCODING_SCRATCH_BYTES = 8 * 1024**2

_DEFAULTS = {
    "name": "FW_MaterialAtlas",
    "resolution": 1024,
    "margin": 8,
    "max_memory_mb": 1024,
    "max_evaluated_vertices": 250_000,
    "max_evaluated_triangles": 100_000,
    "dry_run": True,
}
_BOUNDS = {
    "resolution": (64, 8192),
    "margin": (0, 64),
    "max_memory_mb": (1, 32768),
    "max_evaluated_vertices": (1, 1_000_000),
    "max_evaluated_triangles": (1, 500_000),
}


def parse_atlas_request(params):
    """Validate explicit object scope and owned-image estimates before allocation.

    The adapter separately admits actual geometry, static shader semantics, source
    dependencies and input image memory. This estimate is not a process/GPU cap.
    """
    if not isinstance(params, dict) or set(params) - {*_DEFAULTS, "object_names"}:
        raise ValueError("Atlas request requires known parameters and explicit object_names")
    names = params.get("object_names")
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 64
        or any(not isinstance(name, str) or not 1 <= len(name) <= 1024 for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("object_names must contain 1..64 unique exact object names")
    request = dict(_DEFAULTS, **params)
    request["object_names"] = list(names)
    for field, (lower, upper) in _BOUNDS.items():
        if type(request[field]) is not int or not lower <= request[field] <= upper:
            raise ValueError(f"{field} must be an integer between {lower} and {upper}")
    name = request["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 48 or not name.isprintable():
        raise ValueError("name must contain 1..48 printable characters")
    if type(request["dry_run"]) is not bool:
        raise ValueError("dry_run must be a boolean")
    if request["margin"] * 2 >= request["resolution"]:
        raise ValueError("Twice the margin must be smaller than the atlas resolution")
    buffer_bytes = request["resolution"] ** 2 * 16 * 8
    estimate = buffer_bytes + ENCODING_SCRATCH_BYTES
    if estimate > request["max_memory_mb"] * 1024**2:
        raise ValueError("Estimated atlas image working memory exceeds max_memory_mb")
    return {
        **request,
        "map_roles": ["base_color", "roughness", "metallic", "normal"],
        "estimated_image_working_bytes": estimate,
        "memory_components": {
            "rgba_float_image_equivalents": 8,
            "estimated_image_buffers_bytes": buffer_bytes,
            "bounded_encoding_scratch_bytes": ENCODING_SCRATCH_BYTES,
        },
        "memory_estimate_scope": "owned_images_and_estimated_validation_packing_scratch",
        "native_process_memory_bounded": False,
    }
