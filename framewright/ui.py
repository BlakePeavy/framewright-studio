"""Small production preflight panel with explicit, undoable derivative repair."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import blender_adapter
from .core import PROFILES, validate_scene
from .settings import parse_saved_report


class FRAMEWRIGHT_OT_validate_scene(bpy.types.Operator):
    bl_idname = "framewright.validate_scene"
    bl_label = "Validate Scene"
    bl_description = "Inspect source geometry; visual quality still requires review"

    def execute(self, context):
        try:
            profile = PROFILES[context.scene.framewright_profile]
            overrides = {}
            if context.scene.framewright_triangle_limit:
                overrides["max_triangles"] = context.scene.framewright_triangle_limit
            if context.scene.framewright_texture_target >= 0:
                overrides["texture_target"] = context.scene.framewright_texture_target
            if context.scene.framewright_texture_max:
                overrides["max_texture_resolution"] = context.scene.framewright_texture_max
            profile = replace(profile, **overrides)
            report = validate_scene(blender_adapter.capture_scene(context), profile)
            data = report.to_dict()
            data["settings"] = asdict(profile)
            context.scene.framewright_report = json.dumps(data, indent=2)
            self.report(
                {"INFO"},
                f"Preflight: {len(report.findings)} findings; visual review still required",
            )
            return {"FINISHED"}
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FRAMEWRIGHT_OT_export_report(bpy.types.Operator, ExportHelper):
    bl_idname = "framewright.export_report"
    bl_label = "Export JSON Report"
    bl_description = "Save the most recent report to a location you choose"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bool(context.scene.framewright_report)

    def execute(self, context):
        try:
            Path(self.filepath).write_text(
                context.scene.framewright_report + "\n", encoding="utf-8"
            )
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write report: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class FRAMEWRIGHT_OT_preview_repair(bpy.types.Operator):
    bl_idname = "framewright.preview_repair"
    bl_label = "Preview Loose Vertex Repair"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        try:
            result = blender_adapter.preview_remove_loose_vertices(
                context.active_object.name, context
            )
            context.scene.framewright_repair_preview = f"{result['source']}: {result['removed_vertices']} isolated vertices; source will be preserved"
            self.report({"INFO"}, context.scene.framewright_repair_preview)
            return {"FINISHED"}
        except (ValueError, RuntimeError) as exc:
            context.scene.framewright_repair_preview = str(exc)
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}


class FRAMEWRIGHT_OT_repair_derivative(bpy.types.Operator):
    bl_idname = "framewright.repair_derivative"
    bl_label = "Create Clean Derivative"
    bl_description = "Remove isolated vertices on a new object; preserve the source"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        try:
            result = blender_adapter.apply_remove_loose_vertices(
                context.active_object.name, context
            )
            context.scene.framewright_repair_preview = f"Created hidden {result['derivative']}; removed {result['removed_vertices']} isolated vertices"
            context.scene.framewright_report = ""
            self.report({"INFO"}, context.scene.framewright_repair_preview)
            return {"FINISHED"}
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FRAMEWRIGHT_PT_studio(bpy.types.Panel):
    bl_label = "Framewright Studio"
    bl_idname = "FRAMEWRIGHT_PT_studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Framewright"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text="Production preflight", icon="CHECKMARK")
        layout.prop(scene, "framewright_profile", text="Profile")
        layout.prop(scene, "framewright_triangle_limit", text="Triangle limit")
        layout.prop(scene, "framewright_texture_target", text="Texture target")
        layout.prop(scene, "framewright_texture_max", text="Texture maximum")
        layout.label(text="Limits: 0 uses the profile's setting")
        layout.label(text="Target: -1 uses profile, 0 disables")
        layout.operator("framewright.validate_scene")
        report = parse_saved_report(scene.framewright_report)
        if scene.framewright_report and report is None:
            layout.label(text="Saved report is incompatible; validate again", icon="ERROR")
        if report is not None:
            box = layout.box()
            box.label(text="Last validation snapshot")
            box.label(text=f"{len(report['findings'])} findings; visual review required")
            for finding in report["findings"][:12]:
                row = box.column(align=True)
                row.label(text=f"{finding['severity']}: {finding['rule_id']}")
                if finding["object_name"]:
                    row.label(text=finding["object_name"])
                row.label(text=finding["message"])
            if len(report["findings"]) > 12:
                box.label(text="Export JSON for all findings")
            box.operator("framewright.export_report")
        layout.separator()
        layout.label(text="Static mesh repair")
        layout.operator("framewright.preview_repair")
        layout.operator("framewright.repair_derivative")
        layout.label(text="Derivatives start hidden; reveal to compare")
        if scene.framewright_repair_preview:
            layout.label(text=scene.framewright_repair_preview)


CLASSES = (
    FRAMEWRIGHT_OT_validate_scene,
    FRAMEWRIGHT_OT_export_report,
    FRAMEWRIGHT_OT_preview_repair,
    FRAMEWRIGHT_OT_repair_derivative,
    FRAMEWRIGHT_PT_studio,
)


SCENE_PROPERTIES = (
    "framewright_profile",
    "framewright_triangle_limit",
    "framewright_texture_target",
    "framewright_texture_max",
    "framewright_report",
    "framewright_repair_preview",
)
_REGISTRATION = {"classes": [], "properties": {}}


def _assert_registration_available(classes, names, state):
    if state["classes"] or state["properties"]:
        raise RuntimeError("Framewright components are already registered")
    for cls in classes:
        base = bpy.types.Operator if issubclass(cls, bpy.types.Operator) else bpy.types.Panel
        identifier = getattr(cls, "bl_idname", cls.__name__)
        if base is bpy.types.Operator:
            namespace, operator = identifier.split(".", 1)
            identifier = namespace.upper() + "_OT_" + operator
        if cls.is_registered or base.bl_rna_get_subclass_py(identifier) is not None:
            raise RuntimeError(f"Registration identifier already exists: {identifier}")
    if any(hasattr(bpy.types.Scene, name) for name in names):
        raise RuntimeError("Framewright scene property already exists; existing state was retained")


def _unregister_components(state):
    for name, identity in reversed(tuple(state["properties"].items())):
        current = bpy.types.Scene.bl_rna.properties.get(name)
        if current is not None and current.as_pointer() == identity:
            delattr(bpy.types.Scene, name)
    state["properties"].clear()
    for cls in reversed(state["classes"]):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    state["classes"].clear()


def _register_components(classes, properties, state):
    _assert_registration_available(classes, properties, state)
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            state["classes"].append(cls)
        for name, value in properties.items():
            setattr(bpy.types.Scene, name, value)
            state["properties"][name] = bpy.types.Scene.bl_rna.properties[name].as_pointer()
    except Exception:
        _unregister_components(state)
        raise


def assert_registration_available():
    _assert_registration_available(CLASSES, SCENE_PROPERTIES, _REGISTRATION)


def register():
    properties = {}
    properties["framewright_profile"] = EnumProperty(
        name="Quality Profile",
        items=[
            (key, key.replace("_", " ").title(), "Provisional structural targets")
            for key in PROFILES
        ],
        default="studio_static",
    )
    properties["framewright_triangle_limit"] = IntProperty(
        name="Triangle Limit",
        description="Per-object source mesh budget; 0 uses the profile",
        default=0,
        min=0,
        max=100_000_000,
    )
    properties["framewright_texture_target"] = IntProperty(
        name="Texture Target",
        description="Target pixels, e.g. 8192; -1 uses profile and 0 disables target",
        default=-1,
        min=-1,
        max=65536,
    )
    properties["framewright_texture_max"] = IntProperty(
        name="Texture Maximum",
        description="Maximum texture side in pixels; 0 uses the profile",
        default=0,
        min=0,
        max=65536,
    )
    properties["framewright_report"] = StringProperty(name="Last Report", default="")
    properties["framewright_repair_preview"] = StringProperty(name="Repair Preview", default="")
    _register_components(CLASSES, properties, _REGISTRATION)


def unregister():
    _unregister_components(_REGISTRATION)
