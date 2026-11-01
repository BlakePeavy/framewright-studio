"""Independent transport/readback controls; no Unreal interpreter or editor is loaded."""

import copy
import struct
import zlib
from types import SimpleNamespace as NS

import pytest
from test_native_handoff import pbr_glb
from test_unreal_static_contract import material_fake

from framewright.native_handoff import inspect_glb, surface_expectation


def png_chunk(kind, content):
    return (
        struct.pack(">I", len(content))
        + kind
        + content
        + struct.pack(">I", zlib.crc32(kind + content))
    )


def image_with_metadata(kind, content):
    def change(images):
        # Insert after the valid 13-byte IHDR and its framing.
        images[1] = images[1][:33] + png_chunk(kind, content) + images[1][33:]

    return pbr_glb(image_change=change)


@pytest.mark.parametrize(
    "kind,content",
    [(b"PLTE", b"abcd"), (b"sRGB", b"\x04"), (b"tRNS", b"\x00")],
)
def test_png_color_metadata_with_valid_crc_still_requires_valid_structure(kind, content):
    with pytest.raises(ValueError, match="PNG|palette|sRGB|tRNS"):
        inspect_glb(image_with_metadata(kind, content))


@pytest.mark.parametrize(
    "kind,content",
    [(b"PLTE", b"\x01\x02\x03"), (b"sRGB", b"\x00"), (b"tRNS", b"\0" * 6)],
)
def test_valid_rgb_palette_color_and_transparency_metadata_remain_admitted(kind, content):
    graph = inspect_glb(image_with_metadata(kind, content))
    assert graph["pbr"]["images"][1]["width"] == 2
    assert graph["pbr"]["pixel_content_verified"] is False


def test_distinct_named_textures_can_reuse_image_without_conflating_transfer_roles():
    def change(doc):
        for index, name in enumerate(("ColorView", "ScalarView", "NormalView")):
            doc["textures"][index].update(name=name, source=0)

    graph = inspect_glb(pbr_glb(change))
    expected = surface_expectation({"source": {"path": "reused.glb"}, "geometry": graph})
    assert [t["image"] for t in graph["pbr"]["textures"]] == [0, 0, 0]
    assert [t["name"] for t in expected["textures"]] == ["ColorView", "ScalarView", "NormalView"]
    assert [t["srgb"] for t in expected["textures"]] == [True, False, False]
    assert [t["normal_green_flip"] for t in expected["textures"]] == [False, False, True]


def test_texture_role_conflict_across_materials_is_not_hidden_by_each_material_validity():
    def change(doc):
        second = copy.deepcopy(doc["materials"][0])
        second["name"] = "OtherMaterial"
        second["pbrMetallicRoughness"]["baseColorTexture"]["index"] = 1
        doc["materials"].append(second)

    with pytest.raises(ValueError, match="incompatible|transfer|roles"):
        inspect_glb(pbr_glb(change))


@pytest.mark.parametrize("altered", ["offset_scale", "rotation"])
def test_native_texture_mapping_offsets_and_rotation_are_observed(altered):
    backend, plan, materials, textures, scalars, vectors, maps, _ = material_fake()
    for name in maps:
        vectors[name + "_OffsetScale"] = [0, 0, 1, 1]
        scalars[name + "_Rotation"] = 0.0
    if altered == "offset_scale":
        vectors["BaseColorTexture_OffsetScale"] = [0.25, 0, 2, 1]
    else:
        scalars["BaseColorTexture_Rotation"] = 0.5
    try:
        observed = backend._observe_surfaces(plan, materials, textures)
    except ValueError:
        return
    assert observed != surface_expectation(plan), (
        "Wrong native UV transform was reported as matching"
    )


def import_readback_fixture(*, detached_mesh):
    backend, plan, materials, textures, *_ = material_fake()
    plan["package_root"] = backend.owned_root
    backend._matrix = lambda value: value

    class StaticMesh:
        static_materials = [NS(material_slot_name="Oak", material_interface=materials[0])]

        def get_path_name(self):
            return backend.owned_root + "/Assets/BodyMesh.BodyMesh"

        def get_num_triangles(self, lod):
            return 1

        def get_bounding_box(self):
            return NS(min=NS(to_tuple=lambda: (0, 0, 0)), max=NS(to_tuple=lambda: (100, 300, 200)))

    class StaticMeshComponent:
        static_mesh = StaticMesh()

        def get_num_materials(self):
            return 1

        def get_material(self, index):
            return materials[0]

        def get_relative_transform(self):
            matrix = copy.deepcopy(plan["geometry"]["nodes"][1]["local_matrix_cm"])
            if detached_mesh:
                matrix[0][3] += 100
            return matrix

    component = StaticMeshComponent()
    actors = []
    for index, node in enumerate(plan["geometry"]["nodes"]):
        root = NS(get_relative_transform=lambda node=node: node["local_matrix_cm"])
        if index == 1 and not detached_mesh:
            root = component
        actor = NS(
            get_actor_label=lambda node=node: node["name"],
            get_attach_parent_actor=lambda index=index: actors[0] if index == 1 else None,
            get_root_component=lambda root=root: root,
            get_components_by_class=lambda cls, index=index: [component] if index == 1 else [],
            get_actor_transform=lambda node=node: node["world_matrix_cm"],
        )
        actors.append(actor)
    assets = [component.static_mesh, *materials, *textures]
    by_path = {asset.get_path_name(): asset for asset in assets}
    backend.u.StaticMesh = StaticMesh
    backend.u.StaticMeshComponent = StaticMeshComponent
    backend.u.WorldSettings = type("WorldSettings", (), {})
    backend.u.MaterialInterface = type(materials[0])
    backend.u.Texture = type(textures[0])
    backend.actors = NS(get_all_level_actors=lambda: actors)
    backend.library = NS(list_assets=lambda *a, **k: list(by_path), load_asset=lambda p: by_path[p])
    return backend, plan


def test_mesh_component_at_verified_actor_root_is_admitted():
    backend, plan = import_readback_fixture(detached_mesh=False)
    observed = backend.inspect_import(plan)
    assert observed["geometry"]["nodes"] == plan["geometry"]["nodes"]


def test_offset_mesh_child_cannot_pass_using_only_actor_root_transform():
    backend, plan = import_readback_fixture(detached_mesh=True)
    with pytest.raises(ValueError, match="component|root|transform"):
        backend.inspect_import(plan)
