"""Provisional fixed UE 5.8.3 static-scene backend. Importing this module is inert.

The exact project must already be open in an explicitly authorized native window.
This module does not open an editor, connect to MCP, enable plugins, run supplied
code, publish packages to the game, replace content, or alter an existing level.
Actual native execution/cold validation is required before compatibility claims.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re

from .native_handoff import SURFACE_ROLES, _path, _require, surface_expectation

PIPELINES = (
    "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline.DefaultGLTFSceneAssetsPipeline",
    "/Interchange/Pipelines/DefaultGLTFPipeline.DefaultGLTFPipeline",
    "/Interchange/Pipelines/DefaultSceneLevelPipeline.DefaultSceneLevelPipeline",
)


@contextlib.contextmanager
def native_owner(project_root, owner):
    """Match Sundown's exclusive Windows Saved/NarrativeArt.lock handle.

    Called only by the explicit native apply entrypoint. The lock prevents a
    second cooperating owner; it does not supply authorization/authentication.
    """
    _require(os.name == "nt", "Native owner lock currently supports Windows only")
    _require(isinstance(owner, str) and 1 <= len(owner) <= 128, "An explicit owner is required")
    root = _path(project_root, directory=True)
    saved = _path(root / "Source/SundownRunUnreal/Saved", root=root, directory=True)
    lock_path = saved / "NarrativeArt.lock"
    if lock_path.exists():
        _path(lock_path, root=saved)
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(lock_path), 0xC0000000, 0, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    lease = {"owner": owner, "held": True}
    try:
        yield lease
    finally:
        lease["held"] = False
        kernel.CloseHandle(handle)


class UnrealStaticBackend:
    """Trusted backend; JSON cannot choose methods, modules or executable code."""

    def __init__(self, project_root, *, lease=None):
        self.root = _path(project_root, directory=True)
        self.u = importlib.import_module("unreal")
        self.lease = lease
        self.levels = self.u.get_editor_subsystem(self.u.LevelEditorSubsystem)
        self.actors = self.u.get_editor_subsystem(self.u.EditorActorSubsystem)
        _require(
            self.levels is not None and self.actors is not None,
            "Required native editor subsystems unavailable",
        )
        self.library = self.u.EditorAssetLibrary
        self.owned_root = None

    def _dirty(self):
        library = self.u.EditorLoadingAndSavingUtils
        return sorted(
            {
                p.get_name()
                for p in [*library.get_dirty_map_packages(), *library.get_dirty_content_packages()]
            }
        )

    def context(self):
        project = _path(self.u.Paths.get_project_file_path())
        _require(
            project == self.root / "Source/SundownRunUnreal/SundownRun.uproject",
            "Active Unreal project is not the explicit target",
        )
        version = self.u.SystemLibrary.get_engine_version()
        match = re.match(r"^(\d+\.\d+\.\d+)(?:-|$)", version)
        _require(match is not None, "Unrecognized native engine version")
        level = self.levels.get_current_level()
        _require(level is not None, "No current native level")
        level_path = level.get_outermost().get_name()
        _require(self.library.does_asset_exist(level_path), "Current source level is unsaved")
        _require(
            all(self.library.load_asset(path) is not None for path in PIPELINES),
            "Installed fixed GLTF scene pipelines unavailable",
        )
        return {
            "project": str(project),
            "engine": match.group(1),
            "level": level_path,
            "dirty_packages": self._dirty(),
            "owner": self.lease["owner"] if self.lease else None,
            "lock_held": bool(self.lease and self.lease["held"]),
            "is_playing": bool(self.levels.is_in_play_in_editor()),
            "evidence_kind": "unreal_live",
        }

    def namespace_exists(self, root):
        _require(
            re.fullmatch(r"/Game/FramewrightPilots/[A-Za-z][A-Za-z0-9_]{0,63}_[0-9a-f]{12}", root)
            is not None,
            "Invalid owned root",
        )
        content = _path(
            self.root / "Source/SundownRunUnreal/Content", root=self.root, directory=True
        )
        destination = content / root.removeprefix("/Game/")
        # Disk check also catches stale/unregistered content. Existing parent links
        # are inspected without creating or modifying directories.
        for parent in destination.parents:
            if parent == content:
                break
            if parent.exists():
                _path(parent, root=content, directory=True)
        return (
            destination.exists()
            or self.library.does_directory_exist(root)
            or bool(self.library.list_assets(root, recursive=True, include_folder=False))
        )

    def create_level(self, level):
        _require(self.lease and self.lease["held"], "Native ownership no longer held")
        root = level.removesuffix("/Maps/Staging")
        _require(
            level == root + "/Maps/Staging" and not self.namespace_exists(root),
            "Owned level namespace occupied",
        )
        _require(not self._dirty(), "Native state became dirty before allocation")
        self.owned_root = root
        _require(self.levels.new_level(level), "Could not create new owned staging level")
        _require(
            self.levels.get_current_level().get_outermost().get_name() == level,
            "Native level creation returned unexpected level",
        )

    def import_scene(self, source, root):
        _require(
            self.owned_root and root == self.owned_root + "/Assets",
            "Import destination differs from owned root",
        )
        _path(source)
        parameters = self.u.ImportAssetParameters()
        parameters.set_editor_property("is_automated", True)
        parameters.set_editor_property("replace_existing", False)
        parameters.set_editor_property("follow_redirectors", False)
        parameters.set_editor_property("force_show_dialog", False)
        parameters.set_editor_property("import_level", self.levels.get_current_level())
        # Exact installed BaseEngine.ini SceneImportSettings GLTF override stack.
        # The plan cannot supply custom pipeline classes, assets or Python.
        parameters.set_editor_property(
            "override_pipelines", [self.u.SoftObjectPath(path) for path in PIPELINES]
        )
        manager = self.u.InterchangeManager.get_interchange_manager_scripted()
        data = self.u.InterchangeManager.create_source_data(source)
        _require(
            data is not None and manager.import_scene(root, data, parameters),
            "Interchange scene import failed",
        )

    def _matrix(self, transform):
        origin = transform.transform_location(self.u.Vector(0, 0, 0))
        columns = [
            transform.transform_location(self.u.Vector(*v)) - origin
            for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))
        ]
        return [
            [float(tuple(c.to_tuple())[i]) for c in columns] + [float(tuple(origin.to_tuple())[i])]
            for i in range(3)
        ] + [[0, 0, 0, 1]]

    def _enum(self, value, namespace, names):
        for name in names:
            if value == getattr(namespace, name):
                return name
        raise ValueError("Unrecognized native texture/material enumeration")

    def _two_sided(self, material):
        # IsTwoSided is not reflected in 5.8; follow reflected instance overrides.
        cursor, seen = material, set()
        for _ in range(16):
            path = cursor.get_path_name()
            _require(path not in seen, "Cyclic material parent graph")
            seen.add(path)
            if not isinstance(cursor, self.u.MaterialInstance):
                return bool(cursor.get_editor_property("two_sided"))
            overrides = cursor.get_editor_property("base_property_overrides")
            if overrides.override_two_sided:
                return bool(overrides.two_sided)
            cursor = cursor.get_editor_property("parent")
            _require(cursor is not None, "Missing native material parent")
        raise ValueError("Material inheritance depth exceeds budget")

    def _observe_surfaces(self, plan, material_assets, texture_assets):
        """Read native properties; no source values copied as observations.

        Settings do not verify decoded pixels or the renderer. Imported glTF
        minification conversion loses some modes, and magFilter is not mapped.
        """
        expected = surface_expectation(plan)
        material_by_name = {m.get_name(): m for m in material_assets}
        texture_by_name = {t.get_name(): t for t in texture_assets}
        _require(
            len(material_by_name) == len(material_assets)
            and set(material_by_name) == {m["name"] for m in expected["materials"]},
            "Imported material identities differ",
        )
        _require(
            len(texture_by_name) == len(texture_assets)
            and set(texture_by_name) == {t["name"] for t in expected["textures"]},
            "Imported texture identities differ",
        )
        textures, texture_indexes = [], {}
        for index, wanted in enumerate(expected["textures"]):
            texture = texture_by_name[wanted["name"]]
            _require(
                isinstance(texture, self.u.Texture2D)
                and texture.get_path_name().startswith(self.owned_root + "/Assets/"),
                "Unexpected/foreign texture asset",
            )
            texture_indexes[texture.get_path_name()] = index
            prop = texture.get_editor_property
            textures.append(
                {
                    "name": texture.get_name(),
                    "width": int(texture.blueprint_get_size_x()),
                    "height": int(texture.blueprint_get_size_y()),
                    "srgb": bool(prop("srgb")),
                    "normal_green_flip": bool(prop("flip_green_channel")),
                    "compression": self._enum(
                        prop("compression_settings"),
                        self.u.TextureCompressionSettings,
                        ("TC_DEFAULT", "TC_NORMALMAP"),
                    ),
                    "address_x": self._enum(
                        prop("address_x"),
                        self.u.TextureAddress,
                        ("TA_WRAP", "TA_CLAMP", "TA_MIRROR"),
                    ),
                    "address_y": self._enum(
                        prop("address_y"),
                        self.u.TextureAddress,
                        ("TA_WRAP", "TA_CLAMP", "TA_MIRROR"),
                    ),
                    "filter": self._enum(
                        prop("filter"),
                        self.u.TextureFilter,
                        ("TF_DEFAULT", "TF_NEAREST", "TF_BILINEAR", "TF_TRILINEAR"),
                    ),
                }
            )
        library, materials = self.u.MaterialEditingLibrary, []
        allowed_parents = {
            "/InterchangeAssets/gltf/Substrate/M_GLTF.M_GLTF",
            "/InterchangeAssets/gltf/MaterialInstances/MI_Default_Opaque.MI_Default_Opaque",
            "/InterchangeAssets/gltf/MaterialInstances/MI_Default_Opaque_DS.MI_Default_Opaque_DS",
        }
        for wanted in expected["materials"]:
            material = material_by_name[wanted["name"]]
            _require(
                isinstance(material, self.u.MaterialInstanceConstant)
                and material.get_path_name().startswith(self.owned_root + "/Assets/"),
                "Require an owned GLTF material instance",
            )
            parent = material.get_editor_property("parent")
            _require(
                parent is not None and parent.get_path_name() in allowed_parents,
                "Unexpected GLTF parent material; material graph is unverified",
            )
            available = {
                "scalar": {str(n) for n in library.get_scalar_parameter_names(material)},
                "vector": {str(n) for n in library.get_vector_parameter_names(material)},
                "texture": {str(n) for n in library.get_texture_parameter_names(material)},
                "static_switch": {
                    str(n) for n in library.get_static_switch_parameter_names(material)
                },
            }

            def parameter(kind, name, available=available, material=material):
                _require(name in available[kind], f"Missing native {kind} parameter: {name}")
                getter = getattr(library, f"get_material_instance_{kind}_parameter_value")
                return getter(material, name)

            def vector(name, parameter=parameter):
                return [float(v) for v in parameter("vector", name).to_tuple()]

            row = {
                "name": material.get_name(),
                "base_color_factor": vector("BaseColorFactor"),
                "roughness_factor": float(parameter("scalar", "RoughnessFactor")),
                "metallic_factor": float(parameter("scalar", "MetallicFactor")),
                "emissive_factor": vector("EmissiveFactor")[:3],
                "double_sided": self._two_sided(material),
                "alpha_mode": self._enum(
                    material.get_blend_mode(), self.u.BlendMode, ("BLEND_OPAQUE",)
                ),
                "bindings": {},
            }
            # The core GLB does not carry KHR_materials_emissive_strength.
            _require(
                abs(float(parameter("scalar", "EmissiveStrength")) - 1.0) <= 1e-5,
                "Unexpected native emissive strength",
            )
            for role, name in SURFACE_ROLES.items():
                enabled = bool(parameter("static_switch", "bHas" + name))
                if not enabled:
                    continue
                texture = parameter("texture", name)
                _require(
                    texture is not None and texture.get_path_name() in texture_indexes,
                    "Material refers to an unexpected/foreign texture",
                )
                binding = {
                    "texture": texture_indexes[texture.get_path_name()],
                    "texcoord": float(parameter("scalar", name + "_TexCoord")),
                    "tiling": vector(name + "_TilingMethod"),
                    "offset_scale": vector(name + "_OffsetScale"),
                    "rotation": float(parameter("scalar", name + "_Rotation")),
                }
                if role == "normal":
                    binding["scale"] = float(parameter("scalar", "NormalScale"))
                elif role == "occlusion":
                    binding["strength"] = float(parameter("scalar", "OcclusionStrength"))
                row["bindings"][role] = binding
            materials.append(row)
        return {"materials": materials, "textures": textures}

    def _mesh_materials(self, mesh, component, expected_names):
        slots = list(mesh.static_materials)
        names = [str(slot.material_slot_name) for slot in slots]
        _require(
            names == expected_names and component.get_num_materials() == len(slots),
            "Native mesh/component material slot count or labels differ",
        )
        for index, (slot, name) in enumerate(zip(slots, names, strict=True)):
            assigned = slot.material_interface
            effective = component.get_material(index)
            _require(
                isinstance(assigned, self.u.MaterialInterface)
                and assigned.get_name() == name
                and assigned.get_path_name().startswith(self.owned_root + "/Assets/"),
                "Native static mesh uses a null/foreign/swapped material",
            )
            _require(
                isinstance(effective, self.u.MaterialInterface)
                and effective.get_path_name() == assigned.get_path_name(),
                "Native component overrides the verified mesh material",
            )
        return names

    def inspect_import(self, plan):
        _require(plan["package_root"] == self.owned_root, "Unexpected inspection root")
        actual_actors = [
            a for a in self.actors.get_all_level_actors() if not isinstance(a, self.u.WorldSettings)
        ]
        by_label = {}
        for actor in actual_actors:
            label = actor.get_actor_label()
            _require(label not in by_label, "Duplicate imported actor label")
            by_label[label] = actor
        wanted = plan["geometry"]
        _require(
            set(by_label) == {n["name"] for n in wanted["nodes"]},
            "Imported actor identities include missing/renamed/extra nodes; native hierarchy unverified",
        )
        nodes, mesh_rows, mesh_paths = [], {}, {}
        for expected in wanted["nodes"]:
            actor = by_label[expected["name"]]
            parent = actor.get_attach_parent_actor()
            component = actor.get_root_component()
            _require(component is not None, "Imported actor has no root component")
            components = actor.get_components_by_class(self.u.StaticMeshComponent)
            index = expected["mesh"]
            if index is None:
                _require(not components, "Pivot unexpectedly contains mesh geometry")
            else:
                _require(len(components) == 1, "Mesh node did not retain one mesh component")
                _require(
                    components[0] == component,
                    "Imported mesh component is not the verified actor root transform",
                )
                mesh = components[0].static_mesh
                _require(
                    isinstance(mesh, self.u.StaticMesh)
                    and mesh.get_path_name().startswith(self.owned_root + "/"),
                    "Unexpected/foreign mesh identity",
                )
                if index in mesh_paths:
                    _require(
                        mesh_paths[index] == mesh.get_path_name(),
                        "Shared mesh identity was split unexpectedly",
                    )
                mesh_paths[index] = mesh.get_path_name()
                bounds = mesh.get_bounding_box()
                mesh_rows[index] = {
                    "triangles": int(mesh.get_num_triangles(0)),
                    "bounds_cm": [list(bounds.min.to_tuple()), list(bounds.max.to_tuple())],
                    "materials": self._mesh_materials(
                        mesh, components[0], wanted["meshes"][index]["materials"]
                    ),
                }
            nodes.append(
                {
                    "name": expected["name"],
                    "parent": parent.get_actor_label() if parent else None,
                    "mesh": index,
                    "local_matrix_cm": self._matrix(component.get_relative_transform()),
                    "world_matrix_cm": self._matrix(actor.get_actor_transform()),
                }
            )
        _require(
            len(set(mesh_paths.values())) == len(wanted["meshes"]),
            "Distinct source meshes were merged",
        )
        meshes = [mesh_rows[i] for i in range(len(wanted["meshes"]))]
        packages = sorted(
            self.library.list_assets(
                self.owned_root + "/Assets", recursive=True, include_folder=False
            )
        )
        _require(0 < len(packages) <= 2048, "Native package budget exceeded")
        material_names, material_assets, texture_assets = set(), [], []
        for package in packages:
            obj = self.library.load_asset(package)
            _require(obj is not None, "Unresolvable imported package")
            if isinstance(obj, self.u.MaterialInterface):
                material_names.add(obj.get_name())
                material_assets.append(obj)
            elif isinstance(obj, self.u.Texture):
                texture_assets.append(obj)
        # Preserve material order from source, but require the actual exact set.
        _require(material_names == set(wanted["materials"]), "Imported material identity mismatch")
        return {
            "geometry": {
                "nodes": nodes,
                "meshes": meshes,
                "mesh_count": len(meshes),
                "triangles": sum(m["triangles"] for m in meshes),
                "materials": wanted["materials"],
            },
            "surfaces": self._observe_surfaces(plan, material_assets, texture_assets),
            "packages": packages,
        }

    def save(self, packages, level):
        _require(
            packages and level == self.owned_root + "/Maps/Staging",
            "Empty/out-of-scope native save",
        )
        for path in packages:
            _require(path.startswith(self.owned_root + "/Assets/"), "Save outside owned import")
            _require(
                self.library.save_asset(path, only_if_is_dirty=False),
                f"Could not save owned package: {path}",
            )
        _require(
            self.levels.get_current_level().get_outermost().get_name() == level,
            "Current level changed before save",
        )
        _require(self.levels.save_current_level(), "Could not save owned staging level")

    def restore(self, level):
        # Never discard dirty foreign work. Failure keeps the current world and
        # reports restoration failure instead of pretending global rollback.
        _require(self.owned_root is not None, "No owned native stage to restore from")
        foreign_dirty = [p for p in self._dirty() if not p.startswith(self.owned_root + "/")]
        _require(
            not foreign_dirty, "Foreign packages became dirty; refusing automatic level restoration"
        )
        current = self.levels.get_current_level().get_outermost().get_name()
        if current != level:
            _require(
                current == self.owned_root + "/Maps/Staging",
                "Unexpected current world; refusing to replace it",
            )
            _require(self.levels.load_level(level), "Could not restore original clean level")
        _require(
            self.levels.get_current_level().get_outermost().get_name() == level,
            "Original level restoration unverified",
        )
