"""Prepare a read-only, offline Sundown handoff plan from one explicit review kit.

This checks bytes and receipt consistency; it does not run Blender or Unreal,
authenticate earlier evidence, inspect native assets, or grant artistic approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MAX_JSON = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024 * 1024
PROJECT_RELATIVE = Path("Source/SundownRunUnreal/SundownRun.uproject")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid SHA256")
    return value


def _hash_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        _require(name not in result, f"Duplicate JSON key: {name}")
        result[name] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _names(values, label):
    _require(isinstance(values, list) and 0 < len(values) <= 500, f"Invalid {label}")
    _require(all(isinstance(v, str) and v and len(v) <= 512 for v in values), f"Invalid {label}")
    _require(len(set(values)) == len(values), f"Duplicate {label}")
    return sorted(values)


class Inputs:
    """Record explicitly selected files only; never walk the target repository."""

    def __init__(self, kit):
        self.kit = kit
        self.files = {}

    def within_kit(self, raw):
        _require(isinstance(raw, (str, Path)), "Expected a kit path")
        path = Path(raw)
        path = (path if path.is_absolute() else self.kit / path).resolve(strict=True)
        _require(path.is_relative_to(self.kit), "Input reference is outside the explicit kit")
        return path

    def record(self, path, expected=None, maximum=MAX_FILE):
        path = Path(path)
        before = path.stat()
        _require(
            stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "Unbounded/non-file input"
        )
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()

        def signature(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

        _require(signature(before) == signature(after), "Input changed during hashing")
        if expected is not None:
            _require(digest == _sha(expected), f"Input hash mismatch: {path.name}")
        item = {"path": str(path), "sha256": digest, "bytes": after.st_size}
        if path in self.files:
            _require(item == self.files[path], "Input changed during preparation")
        self.files[path] = item
        return item

    def load(self, path):
        self.record(path, maximum=MAX_JSON)
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _require(isinstance(value, dict), "Expected a JSON object")
        self.record(path, maximum=MAX_JSON)
        return value

    def recheck(self):
        for path, item in list(self.files.items()):
            self.record(path, item["sha256"])


def _validate_source(receipt, expected_names, expected_materials):
    source = receipt["source"]
    _require(isinstance(source, list), "Invalid source records")
    _require(
        _names([r["name"] for r in source], "source objects") == expected_names,
        "Mixed asset object scope",
    )
    fingerprint = _hash_json(source)
    _require(
        fingerprint
        == _sha(receipt["source_fingerprint_before"])
        == _sha(receipt["source_fingerprint_after"]),
        "Source fingerprint mismatch or changed source",
    )
    materials = set()
    mesh_names = []
    for row in source:
        _require(row["type"] in ("MESH", "EMPTY"), "Only static mesh/empty kits are supported")
        _require(row["parent"] is None or row["parent"] in expected_names, "External parent scope")
        for field in ("matrix_world", "matrix_local"):
            matrix = row[field]
            _require(
                isinstance(matrix, list)
                and len(matrix) == 4
                and all(
                    isinstance(r, list) and len(r) == 4 and all(_number(v) for v in r)
                    for r in matrix
                ),
                "Invalid finite transform metadata",
            )
        _require(isinstance(row["materials"], list), "Invalid material metadata")
        _require(
            all(m is None or isinstance(m, str) for m in row["materials"]), "Invalid material name"
        )
        materials.update(m for m in row["materials"] if m is not None)
        if row["type"] == "MESH":
            mesh_names.append(row["name"])
            _sha(row["geometry_sha256"])
            _names(row["uv_layers"], "UV layers")
            _require(
                type(row["vertices"]) is int and row["vertices"] > 0, "Invalid vertex metadata"
            )
            _require(
                type(row["source_triangles"]) is int and row["source_triangles"] > 0,
                "Invalid triangle metadata",
            )
    _require(
        sorted(materials) == expected_materials, "Material scope does not match the selected asset"
    )
    reference = receipt["verification_reference"]
    _require(
        reference["normalized_times"] == [0], "Only static normalized-time references are supported"
    )
    bounds = reference["normalized_mesh_bounds"]
    _require(set(bounds) == set(mesh_names), "Bounds reference object scope mismatch")
    for samples in bounds.values():
        _require(isinstance(samples, list) and len(samples) == 1, "Invalid static bounds samples")
        pair = samples[0]
        _require(
            isinstance(pair, list)
            and len(pair) == 2
            and all(
                isinstance(vector, list) and len(vector) == 3 and all(_number(v) for v in vector)
                for vector in pair
            ),
            "Invalid finite bounds metadata",
        )
        _require(all(a <= b for a, b in zip(*pair, strict=True)), "Reversed bounds metadata")
    return fingerprint


def _validate_format(receipt, path):
    fmt, settings = receipt["format"], receipt["settings"]
    _require(settings.get("use_selection") is True, "Export selection scope was not explicit")
    _require(path.suffix.lower() == "." + fmt.lower(), "Receipt format/path mismatch")
    with path.open("rb") as stream:
        header = stream.read(24)
    if fmt == "GLB":
        _require(
            header[:4] == b"glTF"
            and int.from_bytes(header[4:8], "little") == 2
            and int.from_bytes(header[8:12], "little") == path.stat().st_size,
            "Invalid GLB header/size",
        )
        _require(
            settings.get("use_active_scene") is True
            and settings.get("export_yup") is True
            and settings.get("export_animations") is False,
            "Unsupported GLB scope/coordinate/animation settings",
        )
        return "glTF Y-up; exporter conversion recorded; native import transform unverified"
    _require(header.startswith(b"Kaydara FBX Binary  \x00\x1a\x00"), "Unsupported FBX header")
    _require(
        settings.get("axis_forward") == "-Y"
        and settings.get("axis_up") == "Z"
        and settings.get("apply_unit_scale") is True
        and type(settings.get("global_scale")) in (int, float)
        and settings["global_scale"] == 1
        and settings.get("bake_anim") is False,
        "Unsupported FBX coordinate/unit/animation settings",
    )
    return "FBX forward -Y, up Z, unit scale applied; native import transform unverified"


def _publish_new(path, data):
    """Publish complete bytes with a no-replace hard link on the same filesystem."""
    temporary = identity = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".framewright-plan-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            owned = os.fstat(stream.fileno())
            identity = (owned.st_dev, owned.st_ino)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Fails atomically if the explicit output exists.
    finally:
        if temporary is not None and identity is not None:
            try:
                current = temporary.lstat()
                if (
                    stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == identity
                    and current.st_size <= len(data)
                    and data.startswith(temporary.read_bytes())
                ):
                    temporary.unlink()
            except FileNotFoundError:
                pass


def prepare_plan(kit, asset, output, target_root):
    """Verify an explicit static review-kit asset and write a new JSON proposal."""
    kit, target_root = Path(kit).resolve(strict=True), Path(target_root).resolve(strict=True)
    _require(kit.is_dir() and target_root.is_dir(), "Kit and target root must be directories")
    _require(
        isinstance(asset, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", asset),
        "Invalid asset label",
    )
    output = Path(output)
    output = output.parent.resolve(strict=True) / output.name
    _require(output.suffix.lower() == ".json", "Output must be a new JSON file")
    _require(
        not output.is_relative_to(kit) and not output.is_relative_to(target_root),
        "Output must be outside kit and target project",
    )
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    inputs = Inputs(kit)
    try:
        manifest = inputs.load(inputs.within_kit("manifest.json"))
        cold_path = inputs.within_kit("cold-verification.json")
        cold = inputs.load(cold_path)
        _require(manifest["schema_version"] == "1.0", "Unsupported kit schema")
        assets = [a for a in manifest["assets"] if a["label"] == asset]
        _require(len(assets) == 1, "Select exactly one asset from the explicit kit")
        selected = assets[0]
        builder = selected["builder"]
        expected_names = _names(builder["objects"], "builder objects")
        expected_materials = _names(builder["materials"], "builder materials")
        _require(builder["units"] == "metres", "Only metre-authored static kits are supported")
        source_path = inputs.within_kit(manifest["editable_blend"])
        source = inputs.record(source_path, manifest["editable_blend_sha256"])
        _require(source_path.suffix.lower() == ".blend", "Expected editable Blender source")
        project = (target_root / PROJECT_RELATIVE).resolve(strict=True)
        _require(
            project.is_relative_to(target_root), "Project metadata resolves outside target root"
        )
        project_data = inputs.load(project)
        _require(
            isinstance(project_data.get("EngineAssociation"), str),
            "Missing target engine association",
        )
        receipts = selected["exports"]
        _require(
            isinstance(receipts, list)
            and len(receipts) == 2
            and sorted(r["format"] for r in receipts) == ["FBX", "GLB"],
            "Require one GLB and one FBX receipt for this asset",
        )
        exports, common = [], None
        for receipt in receipts:
            _require(
                receipt["schema_version"] == "1.0"
                and receipt["dry_run"] is False
                and receipt["status"]["export_generated"] is True,
                "Export was not generated",
            )
            _require(
                receipt["profile"] == "sundown" and receipt["target_engine"] == "Unreal",
                "Wrong staging profile",
            )
            _require(
                receipt["source_scene"] == manifest["source_scene"]
                and receipt["blender_version"] == manifest["blender_version"],
                "Mixed source scene/version",
            )
            receipt_path = inputs.within_kit(receipt["receipt_path"])
            _require(
                inputs.load(receipt_path) == receipt,
                "External receipt differs from embedded receipt",
            )
            exported = inputs.within_kit(receipt["output_path"])
            output_record = inputs.record(exported, receipt["output_sha256"])
            _require(
                type(receipt["output_bytes"]) is int
                and output_record["bytes"] == receipt["output_bytes"],
                "Export size mismatch",
            )
            fingerprint = _validate_source(receipt, expected_names, expected_materials)
            _require(
                _number(receipt["fps"])
                and receipt["fps"] > 0
                and _number(receipt["unit_scale"])
                and receipt["unit_scale"] == 1
                and receipt["unit_system"] == "METRIC",
                "Invalid source time/unit metadata",
            )
            frame_range = receipt["frame_range"]
            _require(
                isinstance(frame_range, list)
                and len(frame_range) == 2
                and all(_number(v) for v in frame_range)
                and frame_range[0] <= frame_range[1]
                and _number(receipt["source_frame"]),
                "Invalid source frame metadata",
            )
            contract = {
                key: receipt[key]
                for key in (
                    "fps",
                    "unit_scale",
                    "unit_system",
                    "source_frame",
                    "frame_range",
                    "source",
                    "verification_reference",
                )
            }
            if common is not None:
                _require(contract == common, "Mixed format source/time/unit/bounds evidence")
            common = contract
            coordinate_basis = _validate_format(receipt, exported)
            matches = [
                r
                for r in cold["results"]
                if r["asset"] == asset and r["format"] == receipt["format"]
            ]
            _require(
                len(matches) == 1
                and matches[0]["passed"] is True
                and isinstance(matches[0]["scope"], str),
                "Missing/failed/duplicate matching cold evidence",
            )
            exports.append(
                {
                    "format": receipt["format"],
                    "file": output_record,
                    "receipt": inputs.files[receipt_path],
                    "coordinate_settings": coordinate_basis,
                    "settings": receipt["settings"],
                    "warnings": receipt.get("warnings", []),
                    "reported_source_fingerprint": fingerprint,
                    "reported_cold_result": matches[0],
                }
            )
        inputs.recheck()
        run_id = uuid4().hex
        result = {
            "schema_version": "1.0",
            "kind": "offline_sundown_handoff_plan",
            "tool": {
                "script": Path(__file__).name,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            "created_utc": datetime.now(UTC).isoformat(),
            "plan_id": run_id,
            "asset": asset,
            "kit": str(kit),
            "editable_source": source,
            "target_project": {
                "root": str(target_root),
                "project": inputs.files[project],
                "engine_association": project_data["EngineAssociation"],
                "authority": "explicit target and literal project file; editor identity not inspected",
            },
            "proposal": {
                "package_root": f"/Game/FramewrightPilots/{asset}_{run_id[:12]}",
                "staging_level": "MigrationReview",
                "acceptance_location": "JourneyIntegration",
                "identity_status": "proposed_new_owned_identity; not created or reserved",
                "replace_existing_assets": False,
            },
            "source_metadata": {
                "object_names": expected_names,
                "materials": expected_materials,
                "source_scene": manifest["source_scene"],
                "units": "metres",
                "fps": common["fps"],
                "frame_range": common["frame_range"],
                "source_frame": common["source_frame"],
                "object_records": common["source"],
                "bounds_reference": common["verification_reference"],
                "status": "receipt metadata cross-checked; Blender geometry not re-extracted",
            },
            "exports": exports,
            "verified_now": {
                "input_bytes_unchanged": True,
                "matching_manifest_receipts": True,
                "source_export_hashes": True,
                "source_record_fingerprint_integrity": True,
                "cross_format_metadata_consistency": True,
                "files": list(inputs.files.values()),
            },
            "reported_evidence": {
                "cold_reimport": {
                    "file": inputs.files[cold_path],
                    "raw_report": cold,
                    "reexecuted_now": False,
                    "authentication": "untrusted local report; hash preserves reviewed bytes, not truth",
                }
            },
            "status": {
                "offline_plan_prepared": True,
                "source_art_reviewed": "not_reviewed",
                "native_imported": "not_run",
                "world_placed": "not_run",
                "native_cold_verified": "not_run",
                "runtime_bound": "not_run",
                "visually_accepted": "not_reviewed",
                "performance_accepted": "not_evaluated",
            },
            "remaining_gates": [
                "Select artist-reviewed source and resolve procedural material warnings",
                "Authorize native editor use; inspect current project ownership and staging identities",
                "Verify native axes/units/pivots/material bindings and explicit collision/LOD scope",
                "Review contact/access and matched 1/5/25 m day/dusk Journey views",
                "Cold verify owned saved placement and measure pinned runtime performance",
            ],
        }
        data = (json.dumps(result, indent=2, allow_nan=False) + "\n").encode("utf-8")
        _publish_new(output, data)
        return result
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed handoff evidence: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-kit", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON in an existing parent directory"
    )
    parser.add_argument(
        "--target-root", type=Path, required=True, help="Read-only Sundown repository root"
    )
    args = parser.parse_args()
    result = prepare_plan(args.from_kit, args.asset, args.output, args.target_root)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "plan_id": result["plan_id"],
                "status": result["status"],
            }
        )
    )


if __name__ == "__main__":
    main()
