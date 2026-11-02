"""Editor-only override fields require StructBase.get_editor_property in UE."""

from types import SimpleNamespace as NS

import pytest

from framewright.unreal_static import UnrealStaticBackend


class EditorStruct:
    def __init__(self, **fields):
        self.fields = fields

    def get_editor_property(self, name):
        return self.fields[name]


class Material:
    def __init__(self, path, **properties):
        self.path, self.properties = path, properties

    def get_path_name(self):
        return self.path

    def get_editor_property(self, name):
        return self.properties[name]


class Instance(Material):
    pass


@pytest.mark.parametrize("enabled,local,inherited,expected", [
    (True, False, True, False), (True, True, False, True),
    (False, True, False, False), (False, False, True, True),
])
def test_override_and_inheritance_use_editor_properties(enabled, local, inherited, expected):
    backend = object.__new__(UnrealStaticBackend)
    backend.u = NS(MaterialInstance=Instance)
    base = Material("Base", two_sided=inherited)
    child = Instance("Child", parent=base, base_property_overrides=EditorStruct(
        override_two_sided=enabled, two_sided=local))
    assert backend._two_sided(child) is expected


def test_cyclic_material_inheritance_still_refused():
    backend = object.__new__(UnrealStaticBackend)
    backend.u = NS(MaterialInstance=Instance)
    child = Instance("Child", base_property_overrides=EditorStruct(
        override_two_sided=False, two_sided=False))
    child.properties["parent"] = child
    with pytest.raises(ValueError, match="Cyclic"):
        backend._two_sided(child)
