"""Real binary GLB parsing and offline native-plan admission; no Unreal process."""

import base64
import copy
import hashlib
import json
import struct
import zlib

import pytest

from framewright.native_handoff import compile_plan, inspect_glb, verify_plan


def digest(data):
    return hashlib.sha256(data).hexdigest()


def glb(document=None, indices=(0, 1, 2)):
    binary = struct.pack("<9f3H", 0, 0, 0, 1, 0, 0, 0, 2, 3, *indices)
    document = document or {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "FW_Export_Pivot", "translation": [1, 2, 3], "children": [1]},
            {"name": "FW_Export_Body", "mesh": 0, "translation": [0.5, 0, 0]},
        ],
        "meshes": [
            {
                "name": "BodyMesh",
                "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}],
            }
        ],
        "materials": [
            {"name": "Oak", "pbrMetallicRoughness": {"baseColorFactor": [0.3, 0.2, 0.1, 1]}}
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (
        struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def document():
    data = glb()
    size = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + size])


def png(width=2, height=3, rgb=(91, 120, 181)):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = (b"\0" + bytes(rgb) * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAADAAIDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAABgf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCIAroY/9k="
)


def pbr_glb(change=None, image_change=None):
    data = document()
    binary = bytearray(glb()[-44:-2])

    def append(payload):
        binary.extend(b"\0" * (-len(binary) % 4))
        index = len(data["bufferViews"])
        data["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)}
        )
        binary.extend(payload)
        return index

    uv_view = append(struct.pack("<6f", 0, 0, 1, 0, 0, 1))
    data["accessors"].append(
        {"bufferView": uv_view, "componentType": 5126, "count": 3, "type": "VEC2"}
    )
    data["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"] = 2
    payloads = [JPEG, png(rgb=(220, 100, 40)), png(rgb=(128, 128, 255))]
    if image_change:
        image_change(payloads)
    data["images"] = [
        {
            "name": "Image" + str(i),
            "bufferView": append(payload),
            "mimeType": "image/jpeg" if i == 0 else "image/png",
        }
        for i, payload in enumerate(payloads)
    ]
    data["textures"] = [{"source": i, "sampler": 0} for i in range(3)]
    data["samplers"] = [{"wrapS": 33071, "wrapT": 33648, "minFilter": 9987, "magFilter": 9729}]
    material = data["materials"][0]
    material["pbrMetallicRoughness"].update(
        baseColorFactor=[0.3, 0.2, 0.1, 1],
        metallicFactor=0.7,
        roughnessFactor=0.2,
        baseColorTexture={"index": 0},
        metallicRoughnessTexture={"index": 1},
    )
    material["normalTexture"] = {"index": 2, "scale": 0.5}
    material["occlusionTexture"] = {"index": 1, "strength": 0.8}
    data["buffers"][0]["byteLength"] = len(binary)
    if change:
        change(data)
    encoded = json.dumps(data).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    return (
        struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


@pytest.fixture
def handoff(tmp_path):
    kit = tmp_path / "kit"
    kit.mkdir()
    game = tmp_path / "game"
    project = game / "Source" / "SundownRunUnreal" / "SundownRun.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps({"EngineAssociation": "5.8"}))
    export = kit / "part.glb"
    export.write_bytes(glb())
    blend = kit / "source.blend"
    blend.write_bytes(b"BLENDER preserved source")

    def record(path):
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": digest(path.read_bytes()),
        }

    data = {
        "schema_version": "1.0",
        "kind": "offline_sundown_handoff_plan",
        "plan_id": "a" * 32,
        "asset": "Cabinet",
        "kit": str(kit),
        "editable_source": record(blend),
        "target_project": {
            "root": str(game),
            "project": record(project),
            "engine_association": "5.8",
        },
        "proposal": {
            "package_root": "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa",
            "replace_existing_assets": False,
        },
        "source_metadata": {
            "units": "metres",
            "object_names": ["Pivot", "Body"],
            "object_records": [
                {"name": "Pivot", "type": "EMPTY", "parent": None},
                {"name": "Body", "type": "MESH", "parent": "Pivot"},
            ],
        },
        "exports": [
            {
                "format": "GLB",
                "file": record(export),
                "settings": {"export_yup": True, "export_animations": False},
                "warnings": ["Procedural Oak is not portable"],
            }
        ],
        "verified_now": {"files": [record(project), record(blend), record(export)]},
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(data))
    return path, game, kit, data


def compile_fixture(handoff):
    path, game, kit, _ = handoff
    return compile_plan(path, project_root=game, source_root=kit)


def test_actual_accessor_counts_hierarchy_pivot_and_installed_basis():
    graph = inspect_glb(glb())
    assert graph["triangles"] == 1
    assert graph["mesh_count"] == 1
    assert graph["nodes"][1]["parent"] == "FW_Export_Pivot"
    assert graph["nodes"][1]["world_matrix_cm"][0][3] == 150
    assert graph["nodes"][1]["world_matrix_cm"][1][3] == 300
    assert graph["nodes"][1]["world_matrix_cm"][2][3] == 200
    assert graph["meshes"][0]["bounds_cm"] == [[0, 0, 0], [100, 300, 200]]
    assert graph["meshes"][0]["materials"] == ["Oak"]
    assert graph["nodes"][0]["mesh"] is None


def test_compile_is_deterministic_preserves_inputs_and_remains_unverified(handoff):
    path, game, kit, _ = handoff
    before = {
        p: p.read_bytes()
        for p in (path, *kit.iterdir(), game / "Source/SundownRunUnreal/SundownRun.uproject")
    }
    plan = compile_fixture(handoff)
    assert compile_fixture(handoff) == plan
    assert verify_plan(plan) == plan
    assert plan["status"]["native_imported"] == "not_run"
    assert plan["warnings"] == ["Procedural Oak is not portable"]
    assert plan["staging_level"].startswith(plan["package_root"] + "/")
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["nodes"][1].update(children=[0]),
        lambda d: d["nodes"][1].update(name="fw_export_pivot"),
        lambda d: d["nodes"][1].update(translation=[float("nan"), 0, 0]),
        lambda d: d["nodes"][1].update(scale=[1, 0, 1]),
        lambda d: d.update(skins=[{}]),
        lambda d: d.update(animations=[{}]),
        lambda d: d["accessors"][0].update(count=900000000),
        lambda d: d["bufferViews"][1].update(byteOffset=9999),
        lambda d: d["accessors"][0].update(sparse={}),
        lambda d: d["buffers"][0].update(uri="file:///private/data.bin"),
        lambda d: d.update(images=[{"uri": "../outside.png"}]),
        lambda d: d["meshes"][0]["primitives"][0].update(mode=1),
    ],
)
def test_rejects_unsupported_or_malformed_geometry_before_native_work(change):
    data = document()
    change(data)
    with pytest.raises(ValueError):
        inspect_glb(glb(data))


def test_index_values_not_just_accessor_declared_count_are_validated():
    with pytest.raises(ValueError, match="index"):
        inspect_glb(glb(indices=(0, 1, 3)))


def test_finite_float_positions_cannot_overflow_native_centimetres():
    data = bytearray(glb())
    json_size = struct.unpack_from("<I", data, 12)[0]
    struct.pack_into("<f", data, 28 + json_size, 3.4e38)
    with pytest.raises(ValueError):
        inspect_glb(bytes(data))


def test_returned_plan_does_not_mutate_global_basis_contract(handoff):
    plan = compile_fixture(handoff)
    original = plan["basis"]["position"]
    plan["basis"]["position"] = "invented basis"
    assert compile_fixture(handoff)["basis"]["position"] == original


@pytest.mark.parametrize("tail", [b"x", b"\0\0\0\0"])
def test_rejects_payload_outside_declared_glb_length(tail):
    with pytest.raises(ValueError):
        inspect_glb(glb() + tail)


@pytest.mark.parametrize("field", ["export", "project", "handoff"])
def test_verify_rejects_stale_bytes_before_backend(handoff, field):
    path, game, kit, _ = handoff
    plan = compile_fixture(handoff)
    target = {
        "export": kit / "part.glb",
        "project": game / "Source/SundownRunUnreal/SundownRun.uproject",
        "handoff": path,
    }[field]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        verify_plan(plan)


@pytest.mark.parametrize(
    "key,value",
    [
        ("package_root", "/Game/Existing"),
        ("staging_level", "/Game/Other"),
        ("kind", "python_execute"),
    ],
)
def test_plan_tampering_cannot_emit_different_native_operations(handoff, key, value):
    plan = compile_fixture(handoff)
    plan[key] = value
    with pytest.raises(ValueError):
        verify_plan(plan)


def test_outside_source_root_and_unsafe_package_rejected(handoff, tmp_path):
    path, game, kit, data = handoff
    with pytest.raises(ValueError):
        compile_plan(path, project_root=game, source_root=tmp_path / "other")
    data["proposal"]["package_root"] = "/Game/FramewrightPilots/../Other"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        compile_fixture(handoff)


def test_duplicate_json_and_unknown_plan_fields_rejected(handoff):
    plan = compile_fixture(handoff)
    changed = copy.deepcopy(plan)
    changed["python"] = "arbitrary()"
    with pytest.raises(ValueError):
        verify_plan(changed)
    path = handoff[0]
    path.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(ValueError):
        compile_fixture(handoff)


def test_declared_bounds_cannot_hide_actual_binary_extent():
    data = document()
    data["accessors"][0].update(min=[0, 0, 0], max=[0, 0, 0])
    assert inspect_glb(glb(data))["meshes"][0]["bounds_cm"][1] == [100, 300, 200]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(NORMAL=999),
        lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(TEXCOORD_0=1),
        lambda d: d["accessors"][1].update(normalized=True),
        lambda d: d["materials"][0]["pbrMetallicRoughness"].update(baseColorTexture={"index": 0}),
        lambda d: d["materials"][0]["pbrMetallicRoughness"].update(roughnessFactor=float("inf")),
        lambda d: d["bufferViews"].append({"buffer": 99, "byteLength": 8}),
    ],
)
def test_all_attribute_and_material_references_are_admitted(change):
    data = document()
    change(data)
    with pytest.raises(ValueError):
        inspect_glb(glb(data))


def test_cli_publishes_new_output_only_and_refuses_game_write(handoff, tmp_path):
    from scripts.prepare_native_import import main

    path, game, kit, _ = handoff
    output = tmp_path / "compiled.json"
    args = [
        "--handoff",
        str(path),
        "--project-root",
        str(game),
        "--source-root",
        str(kit),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    assert json.loads(output.read_text())["geometry"]["triangles"] == 1
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(args)
    assert output.read_bytes() == before
    with pytest.raises(ValueError):
        main(args[:-1] + [str(game / "forbidden.json")])
    assert not (game / "forbidden.json").exists()


def test_embedded_core_pbr_records_exact_payloads_and_channel_semantics():
    graph = inspect_glb(pbr_glb())
    pbr = graph["pbr"]
    assert graph["images"] == 3
    assert pbr["images"][0]["sha256"] == digest(JPEG)
    assert pbr["images"][0]["width"] == 2 and pbr["images"][0]["height"] == 3
    assert pbr["images"][1]["sha256"] == digest(png(rgb=(220, 100, 40)))
    material = pbr["materials"][0]
    assert material["base_color_factor"] == [0.3, 0.2, 0.1, 1]
    assert material["metallic_factor"] == 0.7 and material["roughness_factor"] == 0.2
    assert material["bindings"]["base_color"]["transfer"] == "sRGB"
    assert material["bindings"]["metallic_roughness"]["channels"] == {
        "roughness": "G",
        "metallic": "B",
    }
    assert material["bindings"]["occlusion"]["channels"] == {"occlusion": "R"}
    assert material["bindings"]["normal"]["normal_convention"] == "OPENGL"
    assert pbr["textures"][0]["sampler"] == {
        "wrap_s": 33071,
        "wrap_t": 33648,
        "min_filter": 9987,
        "mag_filter": 9729,
    }
    assert pbr["pixel_content_verified"] is False


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["images"][0].update(uri="file:///private.png"),
        lambda d: d["images"][0].update(mimeType="image/png"),
        lambda d: d["images"][0].update(bufferView=True),
        lambda d: d["images"][0].update(bufferView=999),
        lambda d: d["textures"][0].update(source=999),
        lambda d: d["samplers"][0].update(wrapS=True),
        lambda d: d["samplers"][0].update(minFilter=123),
        lambda d: d["materials"][0]["normalTexture"].update(texCoord=1),
        lambda d: d["materials"][0]["normalTexture"].update(index=True),
        lambda d: d["materials"][0]["occlusionTexture"].update(strength=1.1),
        lambda d: d["materials"][0]["pbrMetallicRoughness"].update(metallicFactor=1.01),
        lambda d: d["materials"][0]["pbrMetallicRoughness"].update(roughnessFactor=-0.01),
        lambda d: d["materials"][0]["pbrMetallicRoughness"].update(
            baseColorTexture={"index": 0, "extensions": {"KHR_texture_transform": {}}}
        ),
    ],
)
def test_embedded_pbr_rejects_invalid_refs_factors_and_external_content(change):
    with pytest.raises(ValueError):
        inspect_glb(pbr_glb(change))


@pytest.mark.parametrize(
    "image_change",
    [
        lambda xs: xs.__setitem__(0, xs[0][:-2]),
        lambda xs: xs.__setitem__(1, xs[1][:-12]),
        lambda xs: xs.__setitem__(1, xs[1][:-1] + b"X"),
    ],
)
def test_embedded_images_require_complete_bounded_containers(image_change):
    with pytest.raises(ValueError):
        inspect_glb(pbr_glb(image_change=image_change))


def test_sampler_omission_is_recorded_without_inventing_filter_choice():
    def change(d):
        d["textures"][0].pop("sampler")

    sampler = inspect_glb(pbr_glb(change))["pbr"]["textures"][0]["sampler"]
    assert sampler == {"wrap_s": 10497, "wrap_t": 10497, "min_filter": None, "mag_filter": None}


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["materials"][0]["normalTexture"].update(index=0),
        lambda d: d["materials"][0]["pbrMetallicRoughness"]["metallicRoughnessTexture"].update(
            index=0
        ),
        lambda d: d["materials"][0].update(emissiveFactor=[float("nan"), 0, 0]),
        lambda d: d["accessors"][2].update(componentType=5122),
        lambda d: d["accessors"][2].update(normalized=True),
    ],
)
def test_ambiguous_texture_roles_and_invalid_uv_encoding_refuse(change):
    with pytest.raises(ValueError):
        inspect_glb(pbr_glb(change))


def test_native_surface_expectations_record_actual_interchange_limitations():
    from framewright.native_handoff import surface_expectation

    plan = {"source": {"path": "part.glb"}, "geometry": inspect_glb(pbr_glb())}
    expected = surface_expectation(plan)
    assert expected["materials"][0]["base_color_factor"] == [0.3, 0.2, 0.1, 1]
    assert expected["materials"][0]["bindings"]["normal"]["texcoord"] == 0.0
    assert expected["textures"][2]["normal_green_flip"] is True
    assert expected["textures"][2]["compression"] == "TC_NORMALMAP"
    assert expected["textures"][1]["srgb"] is False
    assert expected["textures"][0]["filter"] == "TF_TRILINEAR"
    assert expected["textures"][0]["address_x"] == "TA_CLAMP"
    assert expected["textures"][0]["address_y"] == "TA_MIRROR"
