"""Readiness must be scoped, owned and complete before reading platform dimensions."""

from types import SimpleNamespace as NS

import pytest
from test_unreal_static_contract import material_fake


def setup():
    backend, plan, materials, textures, *_ = material_fake()
    backend.lease = {"owner": "readiness-test", "held": True}
    calls = []
    ready = {"value": False}

    def finish(selected, root):
        calls.append((list(selected), root))
        ready["value"] = True
        return NS(ready=True, error="", texture_count=3, pending_before=3, pending_after=0)

    backend.u.FramewrightTextureLibrary = NS(finish_owned_textures=finish)
    for texture in textures:

        def size(value):
            assert ready["value"], "platform dimensions read before compilation completed"
            return value

        texture.blueprint_get_size_x = lambda: size(2)
        texture.blueprint_get_size_y = lambda: size(3)
    return backend, plan, materials, textures, calls


def test_compilation_finishes_for_exact_owned_set_before_readback():
    backend, plan, materials, textures, calls = setup()
    observed = backend._observe_surfaces(plan, materials, textures)
    assert calls == [(textures, backend.owned_root)]
    assert observed["textures"][0]["width"] == 2
    assert backend.texture_readiness == {
        "scope": "owned_texture_platform_data",
        "texture_count": 3,
        "pending_before": 3,
        "pending_after": 0,
        "ready": True,
    }


@pytest.mark.parametrize("lease", [None, {"held": False}])
def test_missing_or_expired_owner_refuses_before_compilation(lease):
    backend, plan, materials, textures, calls = setup()
    backend.lease = lease
    with pytest.raises(ValueError, match="owner|lease"):
        backend._observe_surfaces(plan, materials, textures)
    assert not calls


def test_missing_bridge_cannot_report_placeholder_dimensions_as_observations():
    backend, plan, materials, textures, calls = setup()
    del backend.u.FramewrightTextureLibrary
    with pytest.raises(ValueError, match="FramewrightNativeBridge"):
        backend._observe_surfaces(plan, materials, textures)
    assert not calls


@pytest.mark.parametrize(
    "change",
    [
        {"ready": False, "error": "still compiling"},
        {"texture_count": 2},
        {"pending_before": 4},
        {"pending_before": -1},
        {"pending_after": 1},
        {"error": "unexpected"},
    ],
)
def test_incomplete_or_inconsistent_bridge_result_refuses(change):
    backend, plan, materials, textures, _ = setup()
    row = dict(ready=True, error="", texture_count=3, pending_before=3, pending_after=0)
    row.update(change)
    backend.u.FramewrightTextureLibrary.finish_owned_textures = lambda *args: NS(**row)
    with pytest.raises(ValueError, match="readiness|compilation"):
        backend._observe_surfaces(plan, materials, textures)


def test_foreign_texture_refuses_entire_batch_before_any_compile_or_dimension_read():
    backend, plan, materials, textures, calls = setup()
    textures[-1].get_path_name = lambda: "/Game/Unrelated/Texture.Texture"
    with pytest.raises(ValueError, match="foreign"):
        backend._observe_surfaces(plan, materials, textures)
    assert not calls


def test_empty_texture_set_has_no_bridge_dependency_or_compilation():
    backend, *_ = material_fake()
    backend.lease = {"held": True}
    result = backend._finish_owned_textures([])
    assert result == {
        "scope": "owned_texture_platform_data",
        "texture_count": 0,
        "pending_before": 0,
        "pending_after": 0,
        "ready": True,
    }
