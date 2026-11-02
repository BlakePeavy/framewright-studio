"""Trusted native API paths are normalized; caller input remains strict."""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from framewright.native_handoff import _path
from framewright.unreal_static import UnrealStaticBackend


def backend_for(tmp_path, *, raw, converted):
    root = tmp_path / "owned"
    target = root / "Source/SundownRunUnreal/SundownRun.uproject"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    calls = []

    def normalize(value):
        calls.append(value)
        return converted(target)

    backend = object.__new__(UnrealStaticBackend)
    backend.root = root
    backend.lease = {"owner": "test", "held": True}
    backend.u = NS(
        Paths=NS(get_project_file_path=lambda: raw, convert_relative_path_to_full=normalize),
        SystemLibrary=NS(get_engine_version=lambda: "5.8.3-test"),
        EditorLoadingAndSavingUtils=NS(
            get_dirty_map_packages=lambda: [], get_dirty_content_packages=lambda: []
        ),
    )
    backend.levels = NS(
        get_current_level=lambda: NS(get_outermost=lambda: NS(get_name=lambda: "/Game/Original")),
        is_in_play_in_editor=lambda: False,
    )
    backend.library = NS(does_asset_exist=lambda _: True, load_asset=lambda _: object())
    return backend, target, calls


@pytest.mark.parametrize(
    "raw", ["../../Owned/Source/SundownRunUnreal/SundownRun.uproject", "native-project"]
)
def test_trusted_native_relative_path_is_resolved_by_engine_before_identity(tmp_path, raw):
    backend, target, calls = backend_for(tmp_path, raw=raw, converted=str)
    assert backend.context()["project"] == str(target)
    assert calls == [raw]


def test_native_absolute_path_is_also_normalized_by_engine(tmp_path):
    backend, target, calls = backend_for(tmp_path, raw="unused", converted=str)
    backend.u.Paths.get_project_file_path = lambda: str(target)
    assert backend.context()["project"] == str(target)
    assert calls == [str(target)]


@pytest.mark.parametrize("outside", [False, True])
def test_native_normalized_wrong_project_is_refused_before_level_read(tmp_path, outside):
    wrong = (tmp_path if outside else tmp_path / "owned") / "Wrong.uproject"
    wrong.parent.mkdir(parents=True, exist_ok=True)
    wrong.write_text("{}")
    backend, _, _ = backend_for(tmp_path, raw="../wrong", converted=lambda _: str(wrong))
    backend.levels.get_current_level = lambda: pytest.fail("identity gate must precede level reads")
    with pytest.raises(ValueError, match="not the explicit target"):
        backend.context()


@pytest.mark.parametrize("converted", ["relative.uproject", "//server/project.uproject"])
def test_invalid_engine_conversion_does_not_bypass_local_path_validation(tmp_path, converted):
    backend, _, _ = backend_for(tmp_path, raw="../project", converted=lambda _: converted)
    with pytest.raises(ValueError, match="absolute|network"):
        backend.context()


def test_caller_paths_still_refuse_absolute_traversal(tmp_path):
    target = tmp_path / "project.uproject"
    target.write_text("{}")
    for raw in ("project.uproject", str(tmp_path / "child/../project.uproject")):
        with pytest.raises(ValueError, match="absolute without traversal"):
            _path(raw)
    assert _path(Path(target)) == target
