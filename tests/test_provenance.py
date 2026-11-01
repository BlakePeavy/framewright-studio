"""Provenance contracts: evidence stays explicit, versioned and independent."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from framewright.provenance import (
    VERIFICATION_STAGES,
    add_reference,
    canonical_json,
    create_manifest,
    create_reference,
    derive_manifest,
    hash_file,
    intake_reference,
    load_manifest,
    manifest_sha256,
    record_verification,
    save_manifest,
    validate_manifest,
)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_identity_is_generated_once_and_survives_roundtrip(self):
        manifest = create_manifest({"name": "Hero prop"})
        self.assertEqual(str(UUID(manifest["asset_id"])), manifest["asset_id"])
        self.assertEqual(manifest["schema_version"], "1.0")
        path = self.root / "asset.json"
        save_manifest(path, manifest)
        self.assertEqual(load_manifest(path), manifest)

    def test_supplied_stable_identity_is_retained(self):
        identity = "db94ce22-36c4-4b41-85d1-c88accfce773"
        manifest = create_manifest({"name": "Prop", "asset_id": identity})
        self.assertEqual(manifest["asset_id"], identity)
        self.assertEqual(
            validate_manifest({"manifest": manifest})["manifest"]["asset_id"], identity
        )

    def test_unknown_evidence_stays_unknown(self):
        manifest = create_manifest({"name": "Prop"})
        self.assertIsNone(manifest["source_sha256"])
        self.assertEqual(manifest["recipe"]["tool"], "unknown")
        self.assertEqual(set(manifest["verification"]), set(VERIFICATION_STAGES))
        self.assertTrue(
            all(v["status"] == "not_checked" for v in manifest["verification"].values())
        )
        reference = create_reference({"label": "Unattributed reference"})
        self.assertEqual(reference["origin"], "unknown")
        self.assertEqual(reference["license"], "unknown")
        self.assertIsNone(reference["sha256"])

    def test_external_asset_origin_is_distinct_from_user_authorship(self):
        reference = create_reference(
            {"label": "External authored base", "origin": "external_asset", "license": "CC0-1.0"}
        )
        self.assertEqual(reference["origin"], "external_asset")

    def test_canonical_hash_ignores_dict_order_not_content(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))
        manifest = create_manifest({"name": "Prop"})
        shuffled = dict(reversed(list(manifest.items())))
        self.assertEqual(manifest_sha256(manifest), manifest_sha256(shuffled))
        shuffled["name"] = "Changed"
        self.assertNotEqual(manifest_sha256(manifest), manifest_sha256(shuffled))

    def test_canonical_json_rejects_non_json_or_nonfinite_values(self):
        for value in [{1: "integer key"}, {"x": float("nan")}, {"x": (1, 2)}, {"x": object()}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json(value)

    def test_schema_rejects_unknown_missing_and_future_fields(self):
        base = create_manifest({"name": "Prop"})
        candidates = [{**base, "unexpected": True}, {**base, "schema_version": "2.0"}]
        missing = copy.deepcopy(base)
        del missing["source_sha256"]
        candidates.append(missing)
        for manifest in candidates:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                validate_manifest({"manifest": manifest})

    def test_identity_and_hash_formats_are_strict(self):
        for params in [
            {"name": "Prop", "asset_id": "not-a-uuid"},
            {"name": "Prop", "source_sha256": "123"},
            {"name": ""},
            {"name": "Prop", "unexpected": True},
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                create_manifest(params)

    def test_reference_intake_hashes_original_without_copy(self):
        source = self.root / "reference.png"
        content = b"fixture original bytes"
        source.write_bytes(content)
        before = set(self.root.iterdir())
        reference = intake_reference(
            {
                "path": str(source),
                "label": "Front reference",
                "origin": "real_photo",
                "license": "unknown",
                "views": ["front"],
            }
        )
        self.assertEqual(reference["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(reference["location"], str(source.resolve()))
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_reference_size_limit_is_enforced(self):
        source = self.root / "reference.bin"
        source.write_bytes(b"12345")
        with self.assertRaises(ValueError):
            intake_reference({"path": str(source), "label": "Large", "max_bytes": 4})
        self.assertEqual(hash_file(source, max_bytes=5), hashlib.sha256(b"12345").hexdigest())

    def test_missing_reference_does_not_invent_a_hash(self):
        with self.assertRaises(FileNotFoundError):
            intake_reference({"path": str(self.root / "missing.png"), "label": "Missing"})

    def test_reference_fields_and_normalized_landmarks_are_validated(self):
        valid = create_reference(
            {
                "label": "Front",
                "views": ["front"],
                "landmarks": [{"name": "handle", "view": "front", "position": [0.5, 0.25]}],
            }
        )
        self.assertEqual(valid["landmarks"][0]["position"], [0.5, 0.25])
        for params in [
            {"label": "Bad", "origin": "certainly licensed"},
            {"label": "Bad", "landmarks": [{"name": "x", "view": "front", "position": [1.1, 0]}]},
            {"label": "Bad", "landmarks": [{"name": "x", "view": "front", "position": [True, 0]}]},
            {"label": "Bad", "views": ["front", "front"]},
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                create_reference(params)

    def test_missing_reference_views_remain_explicit(self):
        manifest = create_manifest({"name": "Prop", "expected_views": ["front", "side", "back"]})
        reference = create_reference({"label": "Front", "views": ["front"]})
        enriched = add_reference({"manifest": manifest, "reference": reference})
        report = validate_manifest({"manifest": enriched})
        self.assertEqual(report["missing_views"], ["back", "side"])
        self.assertEqual(manifest["references"], [])

    def test_duplicate_reference_identity_is_rejected(self):
        reference = create_reference({"label": "Front"})
        manifest = create_manifest({"name": "Prop", "references": [reference]})
        with self.assertRaises(ValueError):
            add_reference({"manifest": manifest, "reference": reference})

    def test_derivative_has_new_identity_and_hashed_parent_link(self):
        source = create_manifest({"name": "Source", "source_sha256": "a" * 64})
        derivative = derive_manifest(
            {
                "parent": source,
                "name": "Clean derivative",
                "recipe": {
                    "tool": "Framewright",
                    "version": "0.2",
                    "operation": "remove_loose",
                    "parameters": {"threshold": 0},
                },
            }
        )
        self.assertNotEqual(derivative["asset_id"], source["asset_id"])
        self.assertEqual(
            derivative["lineage"],
            [
                {
                    "asset_id": source["asset_id"],
                    "manifest_sha256": manifest_sha256(source),
                    "relation": "derived_from",
                }
            ],
        )
        self.assertEqual(source["lineage"], [])
        self.assertIsNone(derivative["source_sha256"])

    def test_verification_stages_are_independent_and_require_evidence(self):
        source = create_manifest({"name": "Prop"})
        changed = record_verification(
            {
                "manifest": source,
                "stage": "exports_verified",
                "status": "passed",
                "evidence": ["fixture-export-report.json sha256:abc"],
            }
        )
        self.assertEqual(changed["verification"]["exports_verified"]["status"], "passed")
        self.assertEqual(changed["verification"]["visually_accepted"]["status"], "not_checked")
        self.assertEqual(source["verification"]["exports_verified"]["status"], "not_checked")
        with self.assertRaises(ValueError):
            record_verification(
                {
                    "manifest": source,
                    "stage": "visually_accepted",
                    "status": "passed",
                    "evidence": [],
                }
            )

    def test_derivative_does_not_inherit_parent_acceptance(self):
        parent = record_verification(
            {
                "manifest": create_manifest({"name": "Source"}),
                "stage": "visually_accepted",
                "status": "passed",
                "evidence": ["Source review"],
            }
        )
        derivative = derive_manifest({"parent": parent, "name": "Derivative"})
        self.assertTrue(
            all(state["status"] == "not_checked" for state in derivative["verification"].values())
        )

    def test_self_lineage_and_unknown_verification_are_rejected(self):
        manifest = create_manifest({"name": "Prop"})
        manifest["lineage"] = [
            {
                "asset_id": manifest["asset_id"],
                "manifest_sha256": "a" * 64,
                "relation": "derived_from",
            }
        ]
        with self.assertRaises(ValueError):
            validate_manifest({"manifest": manifest})
        with self.assertRaises(ValueError):
            record_verification(
                {
                    "manifest": create_manifest({"name": "Prop"}),
                    "stage": "AAA",
                    "status": "passed",
                    "evidence": ["guess"],
                }
            )

    def test_save_never_overwrites_existing_manifest(self):
        path = self.root / "asset.json"
        manifest = create_manifest({"name": "Original"})
        save_manifest(path, manifest)
        with self.assertRaises(FileExistsError):
            save_manifest(path, create_manifest({"name": "Replacement"}))
        self.assertEqual(load_manifest(path), manifest)

    def test_load_rejects_duplicate_keys_and_oversized_input(self):
        path = self.root / "invalid.json"
        path.write_text('{"schema_version":"1.0","schema_version":"2.0"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_manifest(path)
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_validated_output_is_detached_from_input(self):
        manifest = create_manifest({"name": "Prop"})
        result = validate_manifest({"manifest": manifest})
        result["manifest"]["recipe"]["parameters"]["new"] = True
        self.assertEqual(manifest["recipe"]["parameters"], {})
        self.assertEqual(result["sha256"], manifest_sha256(manifest))


if __name__ == "__main__":
    unittest.main()
