"""Fake backend proves ordering/guards only; it cannot establish Unreal runtime parity."""

import copy

import pytest
from test_native_handoff import compile_fixture
from test_native_handoff import handoff as _source_handoff

from framewright.native_handoff import apply_plan, surface_expectation


@pytest.fixture
def handoff(tmp_path):
    return _source_handoff.__wrapped__(tmp_path)


class FakeBackend:
    def __init__(self, plan):
        self.plan = plan
        self.events = []
        self.dirty = []
        self.exists = False
        self.failure = None
        self.observed = copy.deepcopy(plan["geometry"])
        self.surface = surface_expectation(plan)
        self.packages = [
            plan["package_root"] + "/Assets/SM_Body",
            plan["package_root"] + "/Assets/M_Oak",
        ]

    def context(self):
        self.events.append("context")
        return {
            "project": self.plan["project"]["path"],
            "engine": "5.8.3",
            "level": "/Game/Maps/Original",
            "dirty_packages": self.dirty,
            "owner": "test-owner",
            "lock_held": True,
            "is_playing": False,
        }

    def namespace_exists(self, root):
        self.events.append("exists")
        return self.exists

    def create_level(self, level):
        self.events.append(("create", level))

    def import_scene(self, source, root):
        self.events.append(("import", source, root))
        if self.failure == "import":
            raise RuntimeError("native partial import failure")

    def inspect_import(self, plan):
        self.events.append("inspect")
        return {"geometry": self.observed, "packages": self.packages, "surfaces": self.surface}

    def save(self, packages, level):
        self.events.append(("save", packages, level))
        if self.failure == "save":
            raise RuntimeError("native partial save failure")

    def restore(self, level):
        self.events.append(("restore", level))
        if self.failure == "restore":
            raise RuntimeError("restore failed")


def execute(plan, backend, **kwargs):
    return apply_plan(plan, backend, dry_run=False, authorized=True, owner="test-owner", **kwargs)


def test_preview_only_reads_and_never_promotes_acceptance(handoff):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    result = apply_plan(plan, backend)
    assert backend.events == ["context", "exists"]
    assert result["status"] == "preview"
    assert result["native_verified"] is False


@pytest.mark.parametrize(
    "change",
    [
        lambda b: setattr(b, "surface", None),
        lambda b: b.surface["materials"][0].update(roughness_factor=0.9998),
        lambda b: b.surface["materials"][0].update(double_sided=True),
        lambda b: b.surface["materials"][0].update(base_color_factor=[1, 1, 1, 1]),
        lambda b: b.surface["materials"][0].update(alpha_mode="BLEND_TRANSLUCENT"),
    ],
)
def test_material_observations_are_required_before_save(handoff, change):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    change(backend)
    result = execute(plan, backend)
    assert result["status"] == "failed"
    assert not any(isinstance(event, tuple) and event[0] == "save" for event in backend.events)


def material_fake():
    """Real readback method against explicitly modeled public getters, not Unreal."""
    from types import SimpleNamespace as NS

    from test_native_handoff import inspect_glb, pbr_glb

    from framewright.unreal_static import UnrealStaticBackend

    plan = {"source": {"path": "part.glb"}, "geometry": inspect_glb(pbr_glb())}
    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"

    class Texture:
        def __init__(self, index):
            self.index = index
            self.props = {
                "srgb": index == 0,
                "flip_green_channel": index == 2,
                "compression_settings": "TC_NORMALMAP" if index == 2 else "TC_DEFAULT",
                "address_x": "TA_CLAMP",
                "address_y": "TA_MIRROR",
                "filter": "TF_TRILINEAR",
            }

        def get_name(self):
            return "Image" + str(self.index)

        def get_path_name(self):
            return backend.owned_root + "/Assets/" + self.get_name()

        def get_editor_property(self, key):
            return self.props[key]

        def blueprint_get_size_x(self):
            return 2

        def blueprint_get_size_y(self):
            return 3

    class Material:
        def __init__(self):
            self.props = {
                "parent": NS(
                    get_path_name=lambda: "/InterchangeAssets/gltf/Substrate/M_GLTF.M_GLTF"
                ),
                "base_property_overrides": NS(override_two_sided=True, two_sided=False),
            }

        def get_editor_property(self, key):
            return self.props[key]

        def get_name(self):
            return "Oak"

        def get_path_name(self):
            return backend.owned_root + "/Assets/Oak"

        def get_blend_mode(self):
            return "BLEND_OPAQUE"

    textures = [Texture(i) for i in range(3)]
    material = Material()
    scalars = {
        "RoughnessFactor": 0.2,
        "MetallicFactor": 0.7,
        "NormalScale": 0.5,
        "OcclusionStrength": 0.8,
        "EmissiveStrength": 1.0,
    }
    vectors = {"BaseColorFactor": [0.3, 0.2, 0.1, 1], "EmissiveFactor": [0, 0, 0, 1]}
    maps = {
        "BaseColorTexture": textures[0],
        "MetallicRoughnessTexture": textures[1],
        "NormalTexture": textures[2],
        "OcclusionTexture": textures[1],
        "EmissiveTexture": None,
    }
    for key in maps:
        scalars[key + "_TexCoord"] = 0.0
        vectors[key + "_TilingMethod"] = [1, 2, 0, 0]
        scalars[key + "_Rotation"] = 0.0
        vectors[key + "_OffsetScale"] = [0, 0, 1, 1]
    switches = {"bHas" + key: value is not None for key, value in maps.items()}
    backend.u = NS(
        MaterialInstanceConstant=Material,
        MaterialInstance=Material,
        Texture2D=Texture,
        MaterialEditingLibrary=NS(
            get_scalar_parameter_names=lambda m: list(scalars),
            get_vector_parameter_names=lambda m: list(vectors),
            get_texture_parameter_names=lambda m: list(maps),
            get_static_switch_parameter_names=lambda m: list(switches),
            get_material_instance_scalar_parameter_value=lambda m, key: scalars[key],
            get_material_instance_vector_parameter_value=lambda m, key: NS(
                to_tuple=lambda: tuple(vectors[key])
            ),
            get_material_instance_texture_parameter_value=lambda m, key: maps[key],
            get_material_instance_static_switch_parameter_value=lambda m, key: switches[key],
        ),
        TextureAddress=NS(TA_WRAP="TA_WRAP", TA_CLAMP="TA_CLAMP", TA_MIRROR="TA_MIRROR"),
        TextureFilter=NS(
            TF_NEAREST="TF_NEAREST",
            TF_BILINEAR="TF_BILINEAR",
            TF_TRILINEAR="TF_TRILINEAR",
            TF_DEFAULT="TF_DEFAULT",
        ),
        TextureCompressionSettings=NS(TC_DEFAULT="TC_DEFAULT", TC_NORMALMAP="TC_NORMALMAP"),
        BlendMode=NS(BLEND_OPAQUE="BLEND_OPAQUE"),
    )
    return backend, plan, [material], textures, scalars, vectors, maps, switches


def test_native_material_getters_observe_channels_uv_and_sampler_settings():
    backend, plan, materials, textures, *_ = material_fake()
    observed = backend._observe_surfaces(plan, materials, textures)
    assert observed == surface_expectation(plan)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x[3][2].props.update(flip_green_channel=False),
        lambda x: x[3][1].props.update(srgb=True),
        lambda x: x[3][0].props.update(filter="TF_DEFAULT"),
        lambda x: x[4].update(NormalScale=1.0),
        lambda x: x[4].update(NormalTexture_TexCoord=1.0),
        lambda x: x[5].update(BaseColorFactor=[1, 1, 1, 1]),
        lambda x: x[6].update(NormalTexture=x[3][0]),
        lambda x: x[7].update(bHasNormalTexture=False),
    ],
)
def test_native_material_readback_does_not_echo_expected_input(change):
    from framewright.native_handoff import _same_surface

    parts = material_fake()
    change(parts)
    backend, plan, materials, textures, *_ = parts
    observed = backend._observe_surfaces(plan, materials, textures)
    assert not _same_surface(surface_expectation(plan), observed)


def test_missing_native_parameter_refuses_instead_of_reading_default_zero():
    parts = material_fake()
    backend, plan, materials, textures, scalars, *_ = parts
    del scalars["RoughnessFactor"]
    with pytest.raises(ValueError, match="parameter"):
        backend._observe_surfaces(plan, materials, textures)


@pytest.mark.parametrize(
    "change", ["none", "null_slot", "foreign_slot", "wrong_slot", "override", "extra_override"]
)
def test_mesh_and_component_must_use_the_exact_expected_material(change):
    from types import SimpleNamespace as NS

    from framewright.unreal_static import UnrealStaticBackend

    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"

    class Material:
        def __init__(self, name, path):
            self.name, self.path = name, path

        def get_name(self):
            return self.name

        def get_path_name(self):
            return self.path

    oak = Material("Oak", backend.owned_root + "/Assets/Oak.Oak")
    walnut = Material("Walnut", backend.owned_root + "/Assets/Walnut.Walnut")
    slot = NS(material_slot_name="Oak", material_interface=oak)
    used, count = oak, 1
    if change == "null_slot":
        slot.material_interface = None
    if change == "foreign_slot":
        slot.material_interface = Material("Oak", "/Game/Foreign/Oak.Oak")
    if change == "wrong_slot":
        slot.material_interface = walnut
    if change == "override":
        used = walnut
    if change == "extra_override":
        count = 2
    backend.u = NS(MaterialInterface=Material)
    mesh = NS(static_materials=[slot])
    component = NS(get_material=lambda i: used, get_num_materials=lambda: count)
    if change == "none":
        assert backend._mesh_materials(mesh, component, ["Oak"]) == ["Oak"]
    else:
        with pytest.raises(ValueError, match="material"):
            backend._mesh_materials(mesh, component, ["Oak"])


@pytest.mark.parametrize(
    "condition", ["dirty", "existing", "wrong_project", "wrong_owner", "no_authorization"]
)
def test_all_admission_precedes_native_allocations(handoff, condition):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    if condition == "dirty":
        backend.dirty = ["/Game/Important"]
    if condition == "existing":
        backend.exists = True
    if condition == "wrong_project":
        original = backend.context
        backend.context = lambda: dict(original(), project="/wrong/project.uproject")
    if condition == "wrong_owner":
        original = backend.context
        backend.context = lambda: dict(original(), owner="someone-else")
    with pytest.raises(ValueError):
        if condition == "no_authorization":
            apply_plan(plan, backend, dry_run=False)
        else:
            execute(plan, backend)
    assert all(not isinstance(e, tuple) for e in backend.events)


def test_success_saves_exact_owned_packages_and_restores_original_level(handoff):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    result = execute(plan, backend)
    assert backend.events[-2] == ("save", backend.packages, plan["staging_level"])
    assert backend.events[-1] == ("restore", "/Game/Maps/Original")
    assert result["status"] == "saved"
    assert result["cold_verified"] is False
    assert result["visually_accepted"] is False


@pytest.mark.parametrize(
    "failure",
    [
        "import",
        "save",
        "restore",
        "wrong_pivot",
        "wrong_count",
        "foreign_package",
        "empty_packages",
    ],
)
def test_partial_failure_never_reports_success_or_deletes_source(handoff, failure):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    backend.failure = failure
    if failure == "wrong_pivot":
        backend.observed["nodes"][1]["parent"] = None
    if failure == "wrong_count":
        backend.observed["meshes"][0]["triangles"] += 1
    if failure == "foreign_package":
        backend.packages.append("/Game/SomeoneElse/Asset")
    if failure == "empty_packages":
        backend.packages = []
    result = execute(plan, backend)
    assert result["status"] == "failed"
    assert result["native_verified"] is False
    assert backend.events[-1] == ("restore", "/Game/Maps/Original")
    assert not any(
        isinstance(e, tuple) and e[0] in {"delete", "replace", "clear"} for e in backend.events
    )
    if failure in {"wrong_pivot", "wrong_count", "foreign_package", "empty_packages"}:
        assert not any(isinstance(e, tuple) and e[0] == "save" for e in backend.events)


def test_source_change_during_backend_preflight_still_refuses_allocation(handoff):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    original = backend.namespace_exists

    def change_source(root):
        result = original(root)
        (handoff[2] / "part.glb").write_bytes(b"changed")
        return result

    backend.namespace_exists = change_source
    with pytest.raises(ValueError):
        execute(plan, backend)
    assert backend.events == ["context", "exists"]


def test_source_change_during_import_prevents_native_save(handoff):
    plan = compile_fixture(handoff)
    backend = FakeBackend(plan)
    original = backend.inspect_import

    def change_source(import_plan):
        result = original(import_plan)
        (handoff[2] / "part.glb").write_bytes(b"changed during import")
        return result

    backend.inspect_import = change_source
    result = execute(plan, backend)
    assert result["status"] == "failed"
    assert not any(isinstance(e, tuple) and e[0] == "save" for e in backend.events)


def test_native_entrypoint_is_inert_on_import_and_requires_explicit_apply(
    handoff, tmp_path, monkeypatch
):
    import sys

    from scripts import unreal_import_static

    assert "unreal" not in sys.modules
    plan = compile_fixture(handoff)
    import json

    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    report = tmp_path / "report.json"
    with pytest.raises(ValueError, match="authorization"):
        unreal_import_static.main(["--plan", str(path), "--report", str(report), "--apply"])
    assert not report.exists()
    assert "unreal" not in sys.modules


def test_native_backend_pins_import_level_and_installed_engine_pipelines(handoff):
    from types import SimpleNamespace

    from framewright.unreal_static import UnrealStaticBackend

    values, calls = {}, []
    options = SimpleNamespace(set_editor_property=lambda key, value: values.update({key: value}))
    manager = SimpleNamespace(
        import_scene=lambda root, data, args: calls.append((root, data, args)) or True
    )
    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"
    backend.levels = SimpleNamespace(get_current_level=lambda: "owned-level")
    backend.u = SimpleNamespace(
        ImportAssetParameters=lambda: options,
        SoftObjectPath=lambda x: x,
        InterchangeManager=SimpleNamespace(
            get_interchange_manager_scripted=lambda: manager, create_source_data=lambda x: x
        ),
    )
    backend.import_scene(str(handoff[2] / "part.glb"), backend.owned_root + "/Assets")
    assert values["replace_existing"] is False
    assert values["follow_redirectors"] is False
    assert values["import_level"] == "owned-level"
    assert values["force_show_dialog"] is False
    assert values["override_pipelines"] == [
        "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline.DefaultGLTFSceneAssetsPipeline",
        "/Interchange/Pipelines/DefaultGLTFPipeline.DefaultGLTFPipeline",
        "/Interchange/Pipelines/DefaultSceneLevelPipeline.DefaultSceneLevelPipeline",
    ]
    assert len(calls) == 1
