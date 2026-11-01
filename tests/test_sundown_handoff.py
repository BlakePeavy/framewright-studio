"""Offline handoff evidence cannot turn receipt claims into native/art acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from scripts import prepare_sundown_pilot
from scripts.prepare_sundown_pilot import prepare_plan


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def kit(tmp_path):
    folder = tmp_path / "kit"
    folder.mkdir()
    exports = folder / "exports"
    exports.mkdir()
    project = tmp_path / "game"
    native = project / "Source/SundownRunUnreal"
    native.mkdir(parents=True)
    _write(native / "SundownRun.uproject", {"FileVersion": 3, "EngineAssociation": "5.8"})
    blend = folder / "source.blend"
    blend.write_bytes(b"BLENDER fixture source")
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    source = [
        {
            "name": "CabinetBody",
            "type": "MESH",
            "parent": None,
            "matrix_world": identity,
            "matrix_local": identity,
            "materials": ["Walnut"],
            "vertices": 3,
            "source_triangles": 1,
            "geometry_sha256": "a" * 64,
            "uv_layers": ["UVMap"],
            "modifiers": [],
        }
    ]
    receipts = []
    for fmt in ("GLB", "FBX"):
        path = exports / f"Cabinet_{fmt.lower()}.{fmt.lower()}"
        data = (
            struct.pack("<4sII", b"glTF", 2, 12)
            if fmt == "GLB"
            else b"Kaydara FBX Binary  \x00\x1a\x00fixture"
        )
        path.write_bytes(data)
        receipt_path = path.with_suffix(".receipt.json")
        settings = (
            {
                "use_selection": True,
                "use_active_scene": True,
                "export_yup": True,
                "export_animations": False,
            }
            if fmt == "GLB"
            else {
                "use_selection": True,
                "axis_forward": "-Y",
                "axis_up": "Z",
                "apply_unit_scale": True,
                "global_scale": 1.0,
                "bake_anim": False,
            }
        )
        receipt = {
            "schema_version": "1.0",
            "dry_run": False,
            "format": fmt,
            "profile": "sundown",
            "target_engine": "Unreal",
            "source_scene": "Sources",
            "blender_version": "5.2.1 LTS",
            "source_frame": 1,
            "fps": 24.0,
            "frame_range": [1, 250],
            "unit_system": "METRIC",
            "unit_scale": 1.0,
            "output_path": str(path),
            "receipt_path": str(receipt_path),
            "output_sha256": _digest(data),
            "output_bytes": len(data),
            "source": copy.deepcopy(source),
            "source_fingerprint_before": _canonical(source),
            "source_fingerprint_after": _canonical(source),
            "settings": settings,
            "verification_reference": {
                "normalized_times": [0],
                "normalized_mesh_bounds": {"CabinetBody": [[[0, 0, 0], [1, 1, 1]]]},
            },
            "warnings": ["Procedural material appearance unverified"],
            "status": {
                "export_generated": True,
                "native_imported": False,
                "world_placed": False,
                "visually_accepted": False,
            },
        }
        receipts.append(receipt)
        _write(receipt_path, receipt)
    manifest = {
        "schema_version": "1.0",
        "blender_version": "5.2.1 LTS",
        "editable_blend": str(blend),
        "editable_blend_sha256": _digest(blend.read_bytes()),
        "source_scene": "Sources",
        "assets": [
            {
                "label": "Cabinet",
                "builder": {
                    "objects": ["CabinetBody"],
                    "materials": ["Walnut"],
                    "units": "metres",
                    "visual_acceptance": "not_reviewed",
                },
                "exports": receipts,
            }
        ],
    }
    cold = {
        "blender": "5.2.1 LTS",
        "results": [
            {
                "asset": "Cabinet",
                "format": fmt,
                "passed": True,
                "scope": "exact object set, UV presence, bounds within 0.2 mm",
            }
            for fmt in ("GLB", "FBX")
        ],
        "art_accepted": False,
        "material_render_parity": "not_verified",
        "native_import": "not_run",
    }
    _write(folder / "manifest.json", manifest)
    _write(folder / "cold-verification.json", cold)
    return {
        "folder": folder,
        "target": project,
        "output": tmp_path / "plan.json",
        "manifest": manifest,
        "cold": cold,
    }


def _save(kit):
    _write(kit["folder"] / "manifest.json", kit["manifest"])
    _write(kit["folder"] / "cold-verification.json", kit["cold"])
    for receipt in kit["manifest"]["assets"][0]["exports"]:
        _write(Path(receipt["receipt_path"]), receipt)


def _prepare(kit):
    return prepare_plan(kit["folder"], "Cabinet", kit["output"], kit["target"])


def test_success_verifies_bytes_and_preserves_claim_boundaries(kit):
    before = {
        p: p.read_bytes()
        for root in (kit["folder"], kit["target"])
        for p in root.rglob("*")
        if p.is_file()
    }
    result = _prepare(kit)
    assert json.loads(kit["output"].read_text()) == result
    assert result["verified_now"]["input_bytes_unchanged"] is True
    assert result["target_project"]["engine_association"] == "5.8"
    assert result["proposal"]["package_root"].startswith("/Game/FramewrightPilots/Cabinet_")
    assert result["status"]["native_imported"] == "not_run"
    assert result["status"]["visually_accepted"] == "not_reviewed"
    assert result["reported_evidence"]["cold_reimport"]["reexecuted_now"] is False
    assert {r["format"] for r in result["exports"]} == {"GLB", "FBX"}
    assert result["source_metadata"]["object_names"] == ["CabinetBody"]
    assert result["source_metadata"]["materials"] == ["Walnut"]
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("which", ["source", "export"])
def test_stale_source_or_export_bytes_fail_before_output(kit, which):
    target = (
        Path(kit["manifest"]["editable_blend"])
        if which == "source"
        else Path(kit["manifest"]["assets"][0]["exports"][0]["output_path"])
    )
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash|size"):
        _prepare(kit)
    assert not kit["output"].exists()


@pytest.mark.parametrize(
    "change",
    [
        "format",
        "object",
        "fingerprint",
        "fps",
        "coordinates",
        "materials",
        "cold_asset",
        "cold_fail",
    ],
)
def test_mixed_or_inconsistent_evidence_is_rejected(kit, change):
    receipt = kit["manifest"]["assets"][0]["exports"][0]
    if change == "format":
        receipt["format"] = "FBX"
    elif change == "object":
        receipt["source"][0]["name"] = "OtherAsset"
    elif change == "fingerprint":
        receipt["source_fingerprint_after"] = "f" * 64
    elif change == "fps":
        receipt["fps"] = 30
    elif change == "coordinates":
        receipt["settings"]["export_yup"] = False
    elif change == "materials":
        kit["manifest"]["assets"][0]["builder"]["materials"] = ["Wrong"]
    elif change == "cold_asset":
        kit["cold"]["results"][0]["asset"] = "OtherAsset"
    else:
        kit["cold"]["results"][0]["passed"] = False
    _save(kit)
    with pytest.raises(ValueError):
        _prepare(kit)
    assert not kit["output"].exists()


def test_external_receipt_must_equal_embedded_receipt(kit):
    receipt = copy.deepcopy(kit["manifest"]["assets"][0]["exports"][0])
    receipt["warnings"] = ["silently edited"]
    _write(Path(receipt["receipt_path"]), receipt)
    with pytest.raises(ValueError, match="receipt"):
        _prepare(kit)


def test_input_reference_outside_explicit_kit_is_refused(kit):
    external = kit["folder"].parent / "outside.blend"
    external.write_bytes(b"source")
    kit["manifest"]["editable_blend"] = str(external)
    kit["manifest"]["editable_blend_sha256"] = _digest(external.read_bytes())
    _save(kit)
    with pytest.raises(ValueError, match="kit"):
        _prepare(kit)


@pytest.mark.parametrize("location", ["kit", "game", "existing"])
def test_no_output_overwrite_or_source_target_writes(kit, location):
    if location == "existing":
        kit["output"].write_bytes(b"preserve")
    else:
        kit["output"] = (kit["folder"] if location == "kit" else kit["target"]) / "plan.json"
    with pytest.raises((ValueError, FileExistsError)):
        _prepare(kit)
    if location == "existing":
        assert kit["output"].read_bytes() == b"preserve"
    else:
        assert not kit["output"].exists()


def test_untrusted_native_success_claim_is_not_promoted(kit):
    kit["cold"]["art_accepted"] = True
    kit["cold"]["native_import"] = "passed"
    _save(kit)
    result = _prepare(kit)
    assert result["status"]["native_imported"] == "not_run"
    assert result["status"]["visually_accepted"] == "not_reviewed"
    assert result["reported_evidence"]["cold_reimport"]["raw_report"]["art_accepted"] is True


def test_duplicate_json_keys_are_refused(kit):
    (kit["folder"] / "manifest.json").write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(ValueError, match="Duplicate"):
        _prepare(kit)


def test_failed_publish_cleans_only_owned_temporary_file(kit, monkeypatch):
    def fail(*args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(prepare_sundown_pilot.os, "link", fail)
    with pytest.raises(OSError, match="injected"):
        _prepare(kit)
    assert not kit["output"].exists()
    assert not list(kit["output"].parent.glob(".framewright-plan-*"))


def test_publish_failure_preserves_foreign_replacement_bytes(kit, monkeypatch):
    def replace_then_fail(source, destination):
        Path(source).write_bytes(b"foreign replacement")
        raise OSError("injected publication failure")

    monkeypatch.setattr(prepare_sundown_pilot.os, "link", replace_then_fail)
    with pytest.raises(OSError, match="injected"):
        _prepare(kit)
    retained = list(kit["output"].parent.glob(".framewright-plan-*"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == b"foreign replacement"
    assert not kit["output"].exists()


def test_identical_path_prefix_is_not_treated_as_inside_target(kit):
    sibling = kit["target"].with_name(kit["target"].name + "-plans")
    sibling.mkdir()
    kit["output"] = sibling / "plan.json"
    assert _prepare(kit)["status"]["native_imported"] == "not_run"


def test_partial_write_failure_leaves_no_owned_plan_or_temporary(kit, monkeypatch):
    original = prepare_sundown_pilot.tempfile.NamedTemporaryFile

    class FailingFile:
        def __init__(self, **kwargs):
            self.file = original(**kwargs)
            self.name = self.file.name

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def fileno(self):
            return self.file.fileno()

        def write(self, data):
            self.file.write(data[:50])
            self.file.flush()
            raise OSError("partial write failure")

    monkeypatch.setattr(prepare_sundown_pilot.tempfile, "NamedTemporaryFile", FailingFile)
    with pytest.raises(OSError, match="partial write"):
        _prepare(kit)
    assert not kit["output"].exists()
    assert not list(kit["output"].parent.glob(".framewright-plan-*"))
