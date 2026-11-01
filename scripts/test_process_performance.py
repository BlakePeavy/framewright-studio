"""Check Windows OS process-memory measurements with real resident allocations."""

from __future__ import annotations

import ctypes
import gc
import json
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_process_performance import process_memory  # noqa: E402


class ProcessMemoryTests(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Windows", "Windows native API measurement")
    def test_real_allocation_changes_process_private_memory_and_retains_peak(self):
        before = process_memory()
        self.assertEqual(before["status"], "measured")
        self.assertGreater(before["working_set_bytes"], 0)
        size = 32 * 1024 * 1024
        buffer = ctypes.create_string_buffer(size)
        for offset in range(0, size, 4096):
            buffer[offset] = b"x"
        resident = process_memory()
        self.assertGreaterEqual(
            resident["private_commit_bytes"] - before["private_commit_bytes"], size * 0.75
        )
        self.assertGreaterEqual(resident["peak_working_set_bytes"], resident["working_set_bytes"])
        self.assertGreaterEqual(
            resident["peak_working_set_bytes"], before["peak_working_set_bytes"]
        )
        del buffer
        gc.collect()
        released = process_memory()
        self.assertGreaterEqual(
            released["peak_working_set_bytes"], resident["peak_working_set_bytes"]
        )
        json.dumps(released, allow_nan=False)

    def test_unsupported_platform_is_explicit_without_invented_zeroes(self):
        with patch("scripts.benchmark_process_performance.platform.system", return_value="Linux"):
            result = process_memory()
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("working_set_bytes", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
