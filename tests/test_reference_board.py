import tempfile
import unittest
from pathlib import Path

from framewright.provenance import create_manifest, create_reference
from framewright.reference_board import create_board


class ReferenceBoardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "board.html"
        self.manifest = create_manifest(
            {
                "name": "Pilot <script>alert(1)</script>",
                "expected_views": ["front", "side"],
                "references": [
                    create_reference(
                        {
                            "label": "Reference",
                            "location": str(self.root / "missing.png"),
                            "views": ["front"],
                            "landmarks": [
                                {"name": "Eye", "view": "front", "position": [0.5, 0.25]}
                            ],
                        }
                    )
                ],
            }
        )

    def test_preview_creates_nothing_and_missing_evidence_is_explicit(self):
        result = create_board({"manifest": self.manifest, "output": str(self.output)})
        self.assertFalse(self.output.exists())
        self.assertEqual(result["missing_views"], ["side"])
        self.assertEqual(result["unavailable_references"], ["Reference"])
        self.assertEqual(result["artist_approval"], "not_evaluated")

    def test_output_escapes_metadata_preserves_manifest_and_never_copies_images(self):
        import copy

        original = copy.deepcopy(self.manifest)
        result = create_board(
            {"manifest": self.manifest, "output": str(self.output), "dry_run": False}
        )
        content = self.output.read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn("<script>", content)
        self.assertIn("Content-Security-Policy", content)
        self.assertIn("Missing views", content)
        self.assertIn("Eye", content)
        self.assertEqual(self.manifest, original)
        self.assertEqual([p.name for p in self.root.iterdir()], ["board.html"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_overwrite_and_active_url_schemes_rejected(self):
        self.output.write_text("retained")
        with self.assertRaises(ValueError):
            create_board({"manifest": self.manifest, "output": str(self.output), "dry_run": False})
        self.assertEqual(self.output.read_text(), "retained")
        self.manifest["references"][0]["location"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            create_board({"manifest": self.manifest, "output": str(self.root / "new.html")})

    def test_local_images_link_without_remote_fetch_or_source_change(self):
        image = self.root / "reference.png"
        image.write_bytes(b"retained fixture bytes")
        self.manifest["references"][0]["location"] = str(image)
        create_board({"manifest": self.manifest, "output": str(self.output), "dry_run": False})
        self.assertIn(image.as_uri(), self.output.read_text(encoding="utf-8"))
        self.assertEqual(image.read_bytes(), b"retained fixture bytes")


if __name__ == "__main__":
    unittest.main()
