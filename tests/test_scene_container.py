"""Observed UE scene-container semantics; fakes prove guards, not native parity."""

import copy
from types import SimpleNamespace as NS

import pytest
from test_native_handoff import document, glb

from framewright.native_handoff import inspect_glb
from framewright.unreal_static import UnrealStaticBackend

IDENTITY = [[float(i == j) for j in range(4)] for i in range(4)]
ROOT = "/Game/FramewrightPilots/Cabinet_aaaaaaaaaaaa"


def test_scene_identity_retained_from_glb():
    doc = document()
    doc["scenes"][0]["name"] = "FW_ExportStage"
    assert inspect_glb(glb(doc))["scene_name"] == "FW_ExportStage"
    assert inspect_glb(glb())["scene_name"] is None


@pytest.mark.parametrize("name", ["", "../Foreign", True, "fw_export_pivot"])
def test_scene_identity_cannot_escape_or_alias_a_source_node(name):
    doc = document()
    doc["scenes"][0]["name"] = name
    with pytest.raises(ValueError):
        inspect_glb(glb(doc))


class Component:
    def get_relative_transform(self):
        return IDENTITY

    def get_class(self):
        return Component

    @staticmethod
    def static_class():
        return Component


class Actor:
    def __init__(self, label, parent=None):
        self.label, self.parent = label, parent
        self.root_component = Component()
        self.components = [self.root_component]
        self.matrix = copy.deepcopy(IDENTITY)
        self.path = ROOT + "/Maps/Staging.Staging:PersistentLevel." + label

    def get_actor_label(self):
        return self.label

    def get_attach_parent_actor(self):
        return self.parent

    def get_components_by_class(self, _):
        return self.components

    def get_actor_transform(self):
        return self.matrix

    def get_path_name(self):
        return self.path

    def get_class(self):
        return Actor

    @staticmethod
    def static_class():
        return Actor


def fixture():
    backend = object.__new__(UnrealStaticBackend)
    backend.owned_root = ROOT
    backend.u = NS(Actor=Actor, SceneComponent=Component)
    backend._matrix = lambda matrix: matrix
    wrapper = Actor("FW_ExportStage")
    pivot = Actor("Pivot", wrapper)
    child = Actor("Child", pivot)
    actors = {a.label: a for a in (wrapper, pivot, child)}
    wanted = {"scene_name": wrapper.label, "nodes": [
        {"name": "Pivot", "parent": None}, {"name": "Child", "parent": "Pivot"}
    ]}
    return backend, actors, wanted, wrapper, pivot, child


def test_accepts_only_verified_identity_container_without_mutation():
    backend, actors, wanted, wrapper, pivot, child = fixture()
    assert backend._scene_container(actors, wanted) is wrapper
    assert len(actors) == 3 and pivot.parent is wrapper and child.parent is pivot


@pytest.mark.parametrize("defect", [
    "wrong_label", "extra_actor", "missing_node", "foreign_path", "parented",
    "translated", "nan", "no_root", "extra_component", "mesh_root", "wrong_class",
    "detached_root", "misparented_child", "missing_scene_name",
])
def test_refuses_unverified_container(defect):
    backend, actors, wanted, wrapper, pivot, child = fixture()
    if defect == "wrong_label":
        actors["Wrong"] = actors.pop(wrapper.label)
    elif defect == "extra_actor":
        actors["Extra"] = Actor("Extra")
    elif defect == "missing_node":
        actors.pop("Child")
    elif defect == "foreign_path":
        wrapper.path = "/Game/Foreign.Actor"
    elif defect == "parented":
        wrapper.parent = Actor("Foreign")
    elif defect == "translated":
        wrapper.matrix[0][3] = 0.01
    elif defect == "nan":
        wrapper.matrix[0][0] = float("nan")
    elif defect == "no_root":
        wrapper.root_component = None
    elif defect == "extra_component":
        wrapper.components.append(Component())
    elif defect == "mesh_root":
        wrapper.root_component.get_class = lambda: "StaticMeshComponent"
    elif defect == "wrong_class":
        wrapper.get_class = lambda: "StaticMeshActor"
    elif defect == "detached_root":
        pivot.parent = None
    elif defect == "misparented_child":
        child.parent = wrapper
    elif defect == "missing_scene_name":
        wanted["scene_name"] = None
    with pytest.raises(ValueError):
        backend._scene_container(actors, wanted)


def test_no_extra_actor_keeps_existing_contract():
    backend, actors, wanted, wrapper, pivot, child = fixture()
    actors.pop(wrapper.label)
    pivot.parent = None
    assert backend._scene_container(actors, wanted) is None


def test_actual_root_property_does_not_call_unreflected_getter():
    actor = Actor("Root")
    assert UnrealStaticBackend._root_component(actor) is actor.root_component
