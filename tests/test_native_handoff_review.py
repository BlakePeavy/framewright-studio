"""Independent strict binary fixtures and protocol tests; never imports Unreal."""

from __future__ import annotations

import copy
import hashlib
import json
import struct

import pytest

from framewright import native_handoff


def binary_fixture(*, vertices=3, primitive_copies=1):
    """Construct container/accessors independently of the production reader."""
    points = [(0.125, -0.5, 0.25), (1.25, 0.25, -0.125), (0.5, 1.75, 0.75)]
    points.extend((index / 16, 0.25, 0.5) for index in range(3, vertices))
    positions = b"".join(struct.pack("<fff", *point) for point in points)
    indices = struct.pack("<III", 0, 1, 2)
    binary = positions + indices
    primitive = {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "FW_Export_Anchor", "children": [1]},
            {"name": "FW_Export_Part", "mesh": 0, "translation": [0.75, 1.5, -0.25]},
        ],
        "meshes": [
            {
                "name": "Part",
                "primitives": [copy.deepcopy(primitive) for _ in range(primitive_copies)],
            }
        ],
        "materials": [
            {"name": "Paint", "pbrMetallicRoughness": {"baseColorFactor": [0.3, 0.4, 0.5, 1.0]}}
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": vertices, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
    }
    return document, binary


def encode_glb(document, binary):
    payload = json.dumps(document, separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    padded_binary = binary + b"\0" * (-len(binary) % 4)
    chunks = struct.pack("<I4s", len(payload), b"JSON") + payload
    chunks += struct.pack("<I4s", len(padded_binary), b"BIN\0") + padded_binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def file_receipt(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def independent_plan(tmp_path):
    kit = tmp_path / "owned-kit"
    kit.mkdir()
    game = tmp_path / "fake-target"
    project = game / "Source/SundownRunUnreal/SundownRun.uproject"
    project.parent.mkdir(parents=True)
    project.write_text('{"EngineAssociation":"5.8"}', encoding="utf-8")
    source = kit / "part.glb"
    source.write_bytes(encode_glb(*binary_fixture()))
    editable = kit / "editable.blend"
    editable.write_bytes(b"Opaque source bytes: this test never invokes Blender or Unreal")
    handoff = {
        "schema_version": "1.0",
        "kind": "offline_sundown_handoff_plan",
        "asset": "Part",
        "kit": str(kit),
        "editable_source": file_receipt(editable),
        "target_project": {"root": str(game), "project": file_receipt(project)},
        "proposal": {
            "package_root": "/Game/FramewrightPilots/Part_0123456789ab",
            "replace_existing_assets": False,
        },
        "source_metadata": {
            "units": "metres",
            "object_names": ["Anchor", "Part"],
            "object_records": [
                {"name": "Anchor", "type": "EMPTY", "parent": None},
                {"name": "Part", "type": "MESH", "parent": "Anchor"},
            ],
        },
        "exports": [
            {
                "format": "GLB",
                "file": file_receipt(source),
                "settings": {"export_yup": True, "export_animations": False},
            }
        ],
        "verified_now": {
            "files": [file_receipt(project), file_receipt(source), file_receipt(editable)]
        },
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(handoff), encoding="utf-8")
    return native_handoff.compile_plan(path, project_root=game, source_root=kit), source


def test_independent_binary_positive_control_has_actual_geometry():
    result = native_handoff.inspect_glb(encode_glb(*binary_fixture()))
    assert result["mesh_count"] == 1
    assert result["triangles"] == 1
    assert result["meshes"][0]["bounds_cm"] == [[12.5, -12.5, -50.0], [125.0, 75.0, 175.0]]


@pytest.mark.parametrize("minimum", ["2.1", "3.0"])
def test_unknown_required_minimum_gltf_version_refuses(minimum):
    document, binary = binary_fixture()
    document["asset"]["minVersion"] = minimum
    with pytest.raises(ValueError):
        native_handoff.inspect_glb(encode_glb(document, binary))


@pytest.mark.parametrize("field,value", [("root", False), ("root", 0.0), ("scene", False)])
def test_scene_indices_require_literal_integers(field, value):
    document, binary = binary_fixture()
    if field == "root":
        document["scenes"][0]["nodes"] = [value]
    else:
        document["scene"] = value
    with pytest.raises(ValueError):
        native_handoff.inspect_glb(encode_glb(document, binary))


@pytest.mark.parametrize(
    "owner,field,value",
    [
        ("node", "skin", 0),
        ("node", "camera", 0),
        ("node", "weights", [0.5]),
        ("mesh", "weights", [0.5]),
    ],
)
def test_dangling_or_morph_node_semantics_cannot_masquerade_as_static(owner, field, value):
    document, binary = binary_fixture()
    target = document["nodes"][1] if owner == "node" else document["meshes"][0]
    target[field] = value
    # No referenced skin/camera or morph target exists. The static compiler
    # must not erase these unsupported semantics by ignoring their fields.
    with pytest.raises(ValueError):
        native_handoff.inspect_glb(encode_glb(document, binary))


def test_repeated_accessor_references_cannot_multiply_decode_work(monkeypatch):
    data = encode_glb(*binary_fixture(vertices=32, primitive_copies=20))
    # 96 position + 3 index scalars fit the 128 scalar budget. Reusing their
    # descriptors must be cached or separately refused; bounded source size
    # alone must not cause arbitrary repeated binary decoding.
    monkeypatch.setattr(native_handoff, "MAX_SCALARS", 128)
    unpack = struct.unpack_from
    decoded_scalars = 0
    ceiling = 4 * native_handoff.MAX_SCALARS + 64

    class ExcessDecodeWork(RuntimeError):
        pass

    def bounded_unpack(*args, **kwargs):
        nonlocal decoded_scalars
        values = unpack(*args, **kwargs)
        decoded_scalars += len(values)
        if decoded_scalars > ceiling:
            raise ExcessDecodeWork(
                f"Decoded {decoded_scalars} scalars beyond review ceiling {ceiling}"
            )
        return values

    monkeypatch.setattr(native_handoff.struct, "unpack_from", bounded_unpack)
    try:
        native_handoff.inspect_glb(data)
    except ValueError:
        pass  # A preflight work-budget refusal is an acceptable alternative.
    assert decoded_scalars <= ceiling


def test_source_change_during_save_cannot_report_success(independent_plan):
    plan, source = independent_plan
    calls = []
    package = plan["package_root"] + "/Assets/Part"

    class OfflineBackend:
        def context(self):
            return {
                "project": plan["project"]["path"],
                "engine": plan["engine"],
                "is_playing": False,
                "dirty_packages": [],
                "level": "/Game/Existing/SavedLevel",
                "owner": "review",
                "lock_held": True,
                "evidence_kind": "offline_fake",
            }

        def namespace_exists(self, _):
            return False

        def create_level(self, _):
            calls.append("create")

        def import_scene(self, *_):
            calls.append("import")

        def inspect_import(self, _):
            # Satisfy the independent material gate so this test reaches its
            # deliberate save-time source mutation. These are authored glTF
            # fixture defaults, not an assertion of actual engine observations.
            return {
                "packages": [package],
                "geometry": copy.deepcopy(plan["geometry"]),
                "surfaces": {
                    "materials": [
                        {
                            "name": "Paint",
                            "base_color_factor": [0.3, 0.4, 0.5, 1.0],
                            "roughness_factor": 1.0,
                            "metallic_factor": 1.0,
                            "emissive_factor": [0.0, 0.0, 0.0],
                            "double_sided": False,
                            "alpha_mode": "BLEND_OPAQUE",
                            "bindings": {},
                        }
                    ],
                    "textures": [],
                },
            }

        def save(self, *_):
            calls.append("save")
            source.write_bytes(source.read_bytes() + b"changed during fake save")

        def restore(self, _):
            calls.append("restore")

    result = native_handoff.apply_plan(
        plan, OfflineBackend(), dry_run=False, authorized=True, owner="review"
    )
    assert calls == ["create", "import", "save", "restore"]
    assert result["status"] == "failed"
    assert result["native_verified"] is False
    assert result["partial_native_state_possible"] is True
    assert result["original_level_restored"] is True
    # The successful backend save already happened, even though the result
    # must now fail its source contract. Do not conceal persisted owned state.
    assert result["saved_packages"] == [package]
