"""Pure deterministic region manifests and bounded single-command response admission."""

from __future__ import annotations

import math
import re
from types import MappingProxyType

from .provenance import canonical_json

MAX_SELECTED_VERTICES = 65_536
SETTINGS = {
    "max_evaluated_vertices": (250_000, 1_000_000),
    "max_evaluated_triangles": (100_000, 500_000),
    "max_region_triangles": (4096, 16_384),
    "max_group_entries": (2_000_000, 2_000_000),
}
# A single completed command, not an arbitrarily nested workflow result. NULs
# are deliberately a serialization upper-bound placeholder, not a valid path:
# each expands more than any normal directory character through both encodings.
TRANSPORT_METADATA = MappingProxyType(
    {
        "directory": "\x00" * 32_768,
        "request_id": "😀" * 128,
        "rpc_id": "\x00" * 128,
        "job_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
    }
)


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _name(value, maximum, label):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not value.isprintable():
        raise ValueError(f"{label} must be a printable exact identity up to {maximum} characters")
    return value


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase 64-character topology SHA256")
    return value


def _vertices(values, maximum):
    if not isinstance(values, (list, tuple)) or not 3 <= len(values) <= MAX_SELECTED_VERTICES:
        raise ValueError("vertex_indices require 3..65536 explicit evaluated vertex identities")
    selected = set()
    for index in values:
        _integer(index, 0, maximum - 1, "evaluated vertex index")
        if index in selected:
            raise ValueError("Duplicate evaluated vertex indices are unsupported")
        selected.add(index)
    return selected


def validate_request(params):
    """Validate the selector XOR and limits before any Blender access."""
    required = {"object_name", "region_id", "sample_time"}
    allowed = (
        required | set(SETTINGS) | {"vertex_indices", "vertex_group", "expected_topology_sha256"}
    )
    if not isinstance(params, dict) or not required <= params.keys() or params.keys() - allowed:
        raise ValueError(
            "Region description requires exact object, region_id and explicit sample_time; unknown fields refuse"
        )
    if ("vertex_indices" in params) == ("vertex_group" in params):
        raise ValueError("Exactly one of vertex_indices or vertex_group is required")
    _name(params["object_name"], 256, "object_name")
    _name(params["region_id"], 64, "region_id")
    time = params["sample_time"]
    if (
        type(time) not in (int, float)
        or not -1_000_000 <= time <= 1_000_000
        or not math.isfinite(time)
    ):
        raise ValueError("sample_time must be finite from -1000000 to 1000000")
    result = dict(params)
    result["sample_time"] = float(time)
    if "vertex_indices" in params:
        if not isinstance(params["vertex_indices"], list):
            raise ValueError("vertex_indices must be a JSON array")
        _vertices(params["vertex_indices"], 1_000_000)
        result["vertex_indices"] = list(params["vertex_indices"])
    else:
        _name(params["vertex_group"], 256, "vertex_group")
    if "expected_topology_sha256" in params:
        _digest(params["expected_topology_sha256"], "expected_topology_sha256")
    for name, (default, maximum) in SETTINGS.items():
        result[name] = _integer(params.get(name, default), 1, maximum, name)
    return result


def select_region(
    *,
    object_name,
    region_id,
    topology_sha256,
    vertex_count,
    triangles,
    vertex_indices,
    max_region_triangles=4096,
    expected_topology_sha256=None,
):
    """Return all-three membership using actual ordered evaluated triangle IDs.

    The supplied digest is produced/verified by the Blender geometry extractor.
    This helper does not recompute it from incomplete topology, infer anatomy,
    silently remap identities, or perform geometric contact/area checks.
    """
    _name(object_name, 256, "object_name")
    _name(region_id, 64, "region_id")
    _digest(topology_sha256, "topology_sha256")
    if expected_topology_sha256 is not None:
        _digest(expected_topology_sha256, "expected_topology_sha256")
        if expected_topology_sha256 != topology_sha256:
            raise ValueError("Expected topology_sha256 does not match evaluated topology")
    _integer(vertex_count, 1, 1_000_000, "evaluated vertex count")
    _integer(max_region_triangles, 1, 16_384, "max_region_triangles")
    if not isinstance(triangles, (list, tuple)) or not 1 <= len(triangles) <= 500_000:
        raise ValueError("Evaluated topology requires 1..500000 complete triangles")
    selected = _vertices(vertex_indices, vertex_count)
    records, covered = [], set()
    for index, vertices in enumerate(triangles):
        if not isinstance(vertices, (list, tuple)) or len(vertices) != 3:
            raise ValueError("Each evaluated triangle must have three ordered vertex indices")
        for vertex in vertices:
            _integer(vertex, 0, vertex_count - 1, "triangle vertex index")
        if len(set(vertices)) != 3:
            raise ValueError("Each evaluated triangle requires three distinct vertex identities")
        if all(vertex in selected for vertex in vertices):
            if len(records) >= max_region_triangles:
                raise ValueError("Complete selected triangle manifest exceeds max_region_triangles")
            records.append({"index": index, "vertices": list(vertices)})
            covered.update(vertices)
    if not records:
        raise ValueError("Selected evaluated vertices contain no complete triangle")
    uncovered = selected - covered
    return {
        "region": {
            "id": region_id,
            "object_name": object_name,
            "topology_sha256": topology_sha256,
            "triangles": records,
        },
        "selected_vertex_indices": sorted(selected),
        "uncovered_vertex_indices": sorted(uncovered),
        "selected_vertex_count": len(selected),
        "covered_vertex_count": len(covered),
        "uncovered_vertex_count": len(uncovered),
        "evaluated_triangle_count": len(triangles),
        "selected_triangle_count": len(records),
        "triangle_fraction": len(records) / len(triangles),
        "membership_policy": "all_three_evaluated_vertices",
        "geometric_relations_checked": False,
    }


def _mcp_poll_envelope(report):
    # These are the current transport's actual fields and encoding, rather than
    # a guessed fixed byte multiplier. Tests exercise real MCPServer/serve with
    # this exact worker poll shape, including text plus structuredContent.
    from .api import SCHEMA_VERSION
    from .mcp_stdio import SERVER_INFO

    api = {
        "schema_version": SCHEMA_VERSION,
        "request_id": TRANSPORT_METADATA["request_id"],
        "ok": True,
        "result": report,
    }
    poll = {
        "job_id": TRANSPORT_METADATA["job_id"],
        "directory": TRANSPORT_METADATA["directory"],
        "state": "completed",
        "response": api,
        "exit_code": 0,
    }
    response = {
        "jsonrpc": "2.0",
        "id": TRANSPORT_METADATA["rpc_id"],
        "result": {
            "content": [{"type": "text", "text": canonical_json(poll)}],
            "structuredContent": poll,
            "isError": False,
            "resultType": "complete",
            "_meta": {"io.modelcontextprotocol/serverInfo": dict(SERVER_INFO)},
        },
    }
    return api, response


def enforce_response_budget(report):
    """Admit a final report through a bounded actual single-command MCP envelope.

    Does not mutate the report. Call after assembling every result field and do
    not append these returned metrics afterward without checking again. Scope:
    directory<=32768 characters, API ID<=128 printable Unicode characters, RPC
    string ID<=128 characters or signed64-bit integer, UUID job ID, one completed
    command. Arbitrary workflow nesting/larger external metadata is not covered;
    the real transport continues to enforce its own final1MiB limit.
    """
    from .mcp_stdio import MAX_MESSAGE_BYTES

    if not isinstance(report, dict):
        raise ValueError("Region report must be a finite JSON object")
    report_bytes = len(canonical_json(report).encode("utf-8"))
    if report_bytes > MAX_MESSAGE_BYTES:
        raise ValueError("Complete region response exceeds the1MiB transport budget")
    api, envelope = _mcp_poll_envelope(report)
    api_bytes = len(canonical_json(api).encode("utf-8"))
    mcp_bytes = len((canonical_json(envelope) + "\n").encode("utf-8"))
    if api_bytes > MAX_MESSAGE_BYTES or mcp_bytes > MAX_MESSAGE_BYTES:
        raise ValueError(
            "Complete region response exceeds the bounded1MiB MCP poll envelope budget"
        )
    return {
        "report_json_bytes": report_bytes,
        "api_response_json_bytes": api_bytes,
        "mcp_poll_jsonrpc_bytes": mcp_bytes,
        "limit_bytes": MAX_MESSAGE_BYTES,
        "scope": "single_completed_command_with_bounded_metadata",
    }
