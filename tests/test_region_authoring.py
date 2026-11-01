"""Pure region manifest selection and actual MCP-envelope admission boundaries."""

import copy
import io
import json
import math
import tempfile
import unittest

from framewright import region_authoring as authoring
from framewright.batch import parse_request_json
from framewright.mcp_stdio import MCPServer, serve
from framewright.provenance import canonical_json

DIGEST = "a" * 64
TRIANGLES = [(0, 1, 2), (1, 3, 2)]


def request(**changes):
    return {
        "object_name": "ExplicitSkin",
        "region_id": "caller_sole",
        "sample_time": -1.25,
        "vertex_indices": [4, 2, 0, 1],
        **changes,
    }


def select(**changes):
    return authoring.select_region(
        **{
            "object_name": "ExplicitSkin",
            "region_id": "caller_sole",
            "topology_sha256": DIGEST,
            "vertex_count": 5,
            "triangles": TRIANGLES,
            "vertex_indices": [4, 2, 0, 1],
            **changes,
        }
    )


class RegionRequestTests(unittest.TestCase):
    def test_defaults_and_explicit_fractional_time_are_retained_without_mutation(self):
        original = request()
        before = copy.deepcopy(original)
        result = authoring.validate_request(original)
        self.assertEqual(original, before)
        self.assertEqual(result["sample_time"], -1.25)
        self.assertEqual(result["max_evaluated_vertices"], 250000)
        self.assertEqual(result["max_evaluated_triangles"], 100000)
        self.assertEqual(result["max_region_triangles"], 4096)
        self.assertEqual(result["max_group_entries"], 2000000)

    def test_exactly_one_selector_is_enforced_without_blender(self):
        absent = request()
        del absent["vertex_indices"]
        for value in (absent, request(vertex_group="Sole"), request(vertex_indices=None)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                authoring.validate_request(value)
        group = {**absent, "vertex_group": "Sole"}
        self.assertEqual(authoring.validate_request(group)["vertex_group"], "Sole")

    def test_required_fields_unknown_names_and_invalid_time_refuse(self):
        for field in ("object_name", "region_id", "sample_time"):
            value = request()
            del value[field]
            with self.assertRaises(ValueError):
                authoring.validate_request(value)
        for changes in (
            {"object_name": ""},
            {"region_id": "x" * 65},
            {"dry_run": True},
            {"object_name": "invalid\n"},
            {"sample_time": True},
            {"sample_time": math.inf},
            {"sample_time": 1_000_001},
            {"sample_time": 10**1000},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                authoring.validate_request(request(**changes))

    def test_selector_duplicates_bounds_and_budget_types_refuse(self):
        for changes in (
            {"vertex_indices": [0, 1, 1]},
            {"vertex_indices": [0, 1, True]},
            {"vertex_indices": [0, 1, -1]},
            {"vertex_indices": [0, 1, 1_000_000]},
            {"vertex_indices": [0, 1]},
            {"vertex_indices": list(range(65537))},
            {"max_group_entries": 2_000_001},
            {"max_region_triangles": 16385},
            {"max_evaluated_vertices": True},
            {"max_evaluated_triangles": 0},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError):
                authoring.validate_request(request(**changes))

    def test_expected_digest_is_optional_and_strict(self):
        self.assertEqual(
            authoring.validate_request(request(expected_topology_sha256=DIGEST))[
                "expected_topology_sha256"
            ],
            DIGEST,
        )
        for value in (None, "A" * 64, "a" * 63, "g" * 64, 42):
            with self.subTest(value=value), self.assertRaises(ValueError):
                authoring.validate_request(request(expected_topology_sha256=value))


class RegionSelectionTests(unittest.TestCase):
    def test_all_three_membership_and_uncovered_vertices_are_complete(self):
        result = select()
        self.assertEqual(
            result["region"],
            {
                "id": "caller_sole",
                "object_name": "ExplicitSkin",
                "topology_sha256": DIGEST,
                "triangles": [{"index": 0, "vertices": [0, 1, 2]}],
            },
        )
        self.assertEqual(result["selected_vertex_indices"], [0, 1, 2, 4])
        self.assertEqual(result["uncovered_vertex_indices"], [4])
        self.assertEqual(
            (
                result["selected_vertex_count"],
                result["covered_vertex_count"],
                result["uncovered_vertex_count"],
            ),
            (4, 3, 1),
        )
        self.assertEqual(result["triangle_fraction"], 0.5)
        self.assertFalse(result["geometric_relations_checked"])

    def test_input_permutation_does_not_change_output_or_inputs(self):
        before = copy.deepcopy(TRIANGLES)
        self.assertEqual(select(), select(vertex_indices=[0, 1, 2, 4]))
        self.assertEqual(TRIANGLES, before)

    def test_ordered_triangle_identity_and_duplicate_faces_are_not_rewritten(self):
        result = select(triangles=[(2, 0, 1), (2, 0, 1)], vertex_indices=[0, 1, 2])
        self.assertEqual(
            result["region"]["triangles"],
            [{"index": 0, "vertices": [2, 0, 1]}, {"index": 1, "vertices": [2, 0, 1]}],
        )

    def test_empty_complete_triangle_selection_and_empty_geometry_refuse(self):
        for changes in ({"vertex_indices": [0, 1, 3]}, {"triangles": []}, {"vertex_count": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                select(**changes)

    def test_expected_topology_mismatch_never_returns_reidentified_manifest(self):
        with self.assertRaisesRegex(ValueError, "topology"):
            select(expected_topology_sha256="b" * 64)
        self.assertEqual(select(expected_topology_sha256=DIGEST), select())

    def test_selection_and_complete_triangle_budgets_fail_without_partial_result(self):
        for changes in (
            {"vertex_indices": [0, 1, 2, 3], "max_region_triangles": 1},
            {"vertex_indices": [0, 1, 5]},
            {"vertex_indices": [0, 1, 1]},
            {"vertex_count": True},
            {"triangles": [(0, 1, 2)] * 500001},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError):
                select(**changes)

    def test_invalid_unselected_topology_is_not_silently_ignored(self):
        for triangle in ((1, 2, 9), (1, 1, 2), (True, 2, 3), (1, 2)):
            with self.subTest(triangle=triangle), self.assertRaises(ValueError):
                select(triangles=[(0, 1, 2), triangle])

    def test_manifest_round_trips_into_existing_inspection_request(self):
        result = select()
        payload = {
            "schema_version": "1.0",
            "request_id": "describe-chain",
            "command": "contacts.inspect_regions",
            "params": {
                "surface_name": "Ground",
                "regions": [result["region"]],
                "frame_start": 1,
                "frame_end": 1,
            },
        }
        restored = parse_request_json(json.dumps(payload))
        from framewright.api import _validate_request

        self.assertEqual(_validate_request(restored)[1], "contacts.inspect_regions")


class RegionTransportTests(unittest.TestCase):
    def actual_mcp_bytes(self, report, metadata):
        response = {
            "schema_version": "1.0",
            "request_id": metadata["request_id"],
            "ok": True,
            "result": report,
        }
        poll = {
            "job_id": metadata["job_id"],
            "directory": metadata["directory"],
            "state": "completed",
            "response": response,
            "exit_code": 0,
        }
        with tempfile.TemporaryDirectory(prefix="fw-region-authoring-") as folder:

            class Worker:
                directory = folder

                def poll(self, job_id):
                    return poll

                def close(self):
                    pass

            server = MCPServer(worker=Worker(), asset_root=folder)
            message = {
                "jsonrpc": "2.0",
                "id": metadata["rpc_id"],
                "method": "tools/call",
                "params": {
                    "name": "framewright_poll_job",
                    "arguments": {"job_id": metadata["job_id"]},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            }
            unbounded = server.handle(message)
            output = io.BytesIO()
            serve(server, io.BytesIO((canonical_json(message) + "\n").encode()), output)
            return len((canonical_json(unbounded) + "\n").encode()), output.getvalue()

    def test_scoped_envelope_matches_actual_double_encoded_poll_and_serve(self):
        report = {**select(), "unicode": "wood雪", "escaped": '"\\'}
        before = copy.deepcopy(report)
        admission = authoring.enforce_response_budget(report)
        actual_size, encoded = self.actual_mcp_bytes(report, authoring.TRANSPORT_METADATA)
        self.assertEqual(admission["mcp_poll_jsonrpc_bytes"], actual_size)
        self.assertEqual(len(encoded), actual_size)
        self.assertEqual(
            json.loads(encoded)["result"]["structuredContent"]["response"]["result"], report
        )
        self.assertEqual(report, before)

    def test_actual_escaping_can_exceed_transport_even_below_raw_megabyte(self):
        report = {"escaped": "\\" * 190000}
        self.assertLess(len(canonical_json(report).encode()), 1024 * 1024)
        actual_size, encoded = self.actual_mcp_bytes(report, authoring.TRANSPORT_METADATA)
        self.assertGreater(actual_size, 1024 * 1024)
        self.assertEqual(json.loads(encoded)["error"]["code"], -32000)
        with self.assertRaisesRegex(ValueError, "MCP|response|transport"):
            authoring.enforce_response_budget(report)

    def test_nonfinite_and_unbounded_nested_reports_refuse(self):
        with self.assertRaises(ValueError):
            authoring.enforce_response_budget({"bad": math.nan})
        nested = {}
        for _ in range(70):
            nested = {"child": nested}
        with self.assertRaises(ValueError):
            authoring.enforce_response_budget(nested)
