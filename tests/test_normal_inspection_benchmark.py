"""Benchmark receipts must not promote missing, mixed or incorrect evidence."""

import copy
import unittest

from scripts.benchmark_normal_inspection import validate_runs


class NormalInspectionReceiptTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "implementation": name,
                "resolution": [8192, 8192],
                "elapsed_seconds": seconds,
                "process_id": index + 1,
                "source_pixels_before": "a" * 64,
                "source_pixels_after": "a" * 64,
                "runtime_sha256": "b" * 64,
                "outcome": {"valid_normal_pixels": 8192**2},
                "expected_outcome": {"valid_normal_pixels": 8192**2},
                "memory_after": {
                    "status": "measured",
                    "process_id": index + 1,
                    "peak_working_set_bytes": 123,
                    "peak_private_commit_bytes": 234,
                },
            }
            for index, (name, seconds) in enumerate(
                (("retained_0_5", 10), ("chunked", 2), ("retained_0_5", 12), ("chunked", 3))
            )
        ]

    def test_matching_repeated_actual_receipts_summarize_only_observed_times(self):
        summary = validate_runs(self.rows(), 8192, 2, "b" * 64)
        self.assertEqual(summary["retained_0_5"]["median_seconds"], 11)
        self.assertEqual(summary["chunked"]["median_seconds"], 2.5)

    def test_changed_pixels_outcome_or_runtime_never_pass(self):
        for field, value in (
            ("source_pixels_after", "c" * 64),
            ("outcome", {}),
            ("runtime_sha256", "d" * 64),
        ):
            with self.subTest(field=field):
                rows = self.rows()
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    validate_runs(rows, 8192, 2, "b" * 64)

    def test_missing_runs_or_reused_processes_never_pass(self):
        for rows in (self.rows()[:-1], self.rows() + [copy.deepcopy(self.rows()[0])]):
            with self.assertRaises(ValueError):
                validate_runs(rows, 8192, 2, "b" * 64)
        rows = self.rows()
        rows[-1]["process_id"] = rows[0]["process_id"]
        with self.assertRaises(ValueError):
            validate_runs(rows, 8192, 2, "b" * 64)

    def test_unavailable_memory_or_wrong_memory_owner_never_pass(self):
        for memory in (
            {"status": "unavailable"},
            {
                "status": "measured",
                "process_id": 99,
                "peak_working_set_bytes": 1,
                "peak_private_commit_bytes": 1,
            },
        ):
            rows = self.rows()
            rows[0]["memory_after"] = memory
            with self.assertRaises(ValueError):
                validate_runs(rows, 8192, 2, "b" * 64)

    def test_wrong_resolution_and_invalid_timing_never_pass(self):
        for field, value in (
            ("resolution", [2048, 2048]),
            ("elapsed_seconds", float("nan")),
            ("elapsed_seconds", -1),
        ):
            rows = self.rows()
            rows[0][field] = value
            with self.assertRaises(ValueError):
                validate_runs(rows, 8192, 2, "b" * 64)

    def test_different_inputs_between_implementations_never_pass(self):
        rows = self.rows()
        rows[1]["source_pixels_before"] = rows[1]["source_pixels_after"] = "c" * 64
        with self.assertRaises(ValueError):
            validate_runs(rows, 8192, 2, "b" * 64)
