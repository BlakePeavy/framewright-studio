"""Import precision must be requested before import and independently read back."""

from types import SimpleNamespace as NS

import pytest

from framewright.unreal_static import PIPELINES, UnrealStaticBackend


def import_fake(tmp_path):
    source = tmp_path / "source.glb"
    source.write_bytes(b"owned source")
    values, calls = {}, []

    class Pipeline:
        package = "/Engine/Transient"
        precision = True

        def get_path_name(self):
            return self.package + ".FullPrecisionPipeline"

        def get_outermost(self):
            return NS(get_name=lambda: self.package)

        def get_editor_property(self, name):
            assert name == "common_meshes_properties"
            return NS(get_editor_property=lambda key: self.precision if key == "use_full_precision_u_vs" else None)

    pipeline = Pipeline()
    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"
    backend.lease = {"held": True}
    backend.levels = NS(get_current_level=lambda: "owned-level")
    manager = NS(import_scene=lambda root, data, args: calls.append((root, data, args)) or True)
    backend.u = NS(
        ImportAssetParameters=lambda: NS(set_editor_property=lambda key, value: values.update({key: value})),
        SoftObjectPath=lambda value: value,
        InterchangeGenericAssetsPipeline=Pipeline,
        FramewrightImportLibrary=NS(create_full_precision_gltf_pipeline=lambda: pipeline),
        InterchangeManager=NS(get_interchange_manager_scripted=lambda: manager, create_source_data=lambda x: x),
    )
    return backend, source, pipeline, values, calls


def test_initial_import_uses_owned_transient_full_precision_pipeline(tmp_path):
    backend, source, pipeline, values, calls = import_fake(tmp_path)
    backend.import_scene(str(source), backend.owned_root + "/Assets")
    assert values["override_pipelines"] == [pipeline.get_path_name(), *PIPELINES[1:]]
    assert values["replace_existing"] is False and values["follow_redirectors"] is False
    assert values["force_show_dialog"] is False and values["is_automated"] is True
    assert values["import_level"] == "owned-level" and len(calls) == 1


def test_missing_companion_stops_before_import(tmp_path):
    backend, source, _, _, calls = import_fake(tmp_path)
    del backend.u.FramewrightImportLibrary
    with pytest.raises(ValueError, match="FramewrightNativeBridge"):
        backend.import_scene(str(source), backend.owned_root + "/Assets")
    assert not calls


@pytest.mark.parametrize("fault", ["null", "saved", "half"])
def test_invalid_pipeline_stops_before_import(tmp_path, fault):
    backend, source, pipeline, _, calls = import_fake(tmp_path)
    if fault == "null":
        backend.u.FramewrightImportLibrary.create_full_precision_gltf_pipeline = lambda: None
    elif fault == "saved":
        pipeline.package = "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline"
    else:
        pipeline.precision = False
    with pytest.raises(ValueError, match="pipeline|precision"):
        backend.import_scene(str(source), backend.owned_root + "/Assets")
    assert not calls


@pytest.mark.parametrize("lease", [None, {"held": False}])
def test_expired_owner_cannot_start_import(tmp_path, lease):
    backend, source, _, _, calls = import_fake(tmp_path)
    backend.lease = lease
    with pytest.raises(ValueError, match="owner|lease"):
        backend.import_scene(str(source), backend.owned_root + "/Assets")
    assert not calls


@pytest.mark.parametrize("full", [True, False])
def test_native_mesh_setting_is_checked_independently(full):
    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"
    backend.u = NS(StaticMeshEditorSubsystem="mesh-editor", get_editor_subsystem=lambda _: NS(
        get_lod_build_settings=lambda mesh, lod: NS(get_editor_property=lambda name: full)))
    mesh = NS(get_path_name=lambda: backend.owned_root + "/Assets/Body.Body")
    if full:
        assert backend._mesh_precision(mesh) == {"mesh": mesh.get_path_name(), "lod": 0, "full_precision_uvs": True}
    else:
        with pytest.raises(ValueError, match="precision"):
            backend._mesh_precision(mesh)
