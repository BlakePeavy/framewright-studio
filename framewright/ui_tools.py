"""Artist-facing production tools over the same validated command API."""

import json

import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty

from .api import dispatch
from .batch import parse_request_json
from .ui import _assert_registration_available, _register_components, _unregister_components


def _run(operator, context, command, params):
    response = dispatch(
        {"schema_version": "1.0", "request_id": "sidebar", "command": command, "params": params}
    )
    context.scene.framewright_tool_report = json.dumps(response, indent=2)
    if not response["ok"]:
        operator.report({"ERROR"}, response["error"]["message"])
        return {"CANCELLED"}
    operator.report({"INFO"}, "Complete; detailed results are available in the report")
    return {"FINISHED"}


class FRAMEWRIGHT_OT_build_asset(bpy.types.Operator):
    bl_idname = "framewright.build_asset"
    bl_label = "Create Editable Asset"
    bl_options = {"REGISTER", "UNDO"}
    kind: EnumProperty(items=[("CABINET", "Workshop Cabinet", ""), ("FACADE", "Facade Bay", "")])
    width: FloatProperty(name="Width (0 = default)", default=0, min=0, max=100)
    depth: FloatProperty(name="Depth (0 = default)", default=0, min=0, max=100)
    height: FloatProperty(name="Height (0 = default)", default=0, min=0, max=100)

    def execute(self, context):
        params = {"dry_run": False, "location": list(context.scene.cursor.location)}
        for key in ("width", "depth", "height"):
            value = getattr(self, key)
            if value:
                params[key] = value
        result = _run(
            self,
            context,
            "model.build_prop" if self.kind == "CABINET" else "model.build_facade",
            params,
        )
        if result == {"FINISHED"}:
            context.scene.framewright_review_collection = json.loads(
                context.scene.framewright_tool_report
            )["result"]["collection"]
        return result


class FRAMEWRIGHT_OT_inspect_production(bpy.types.Operator):
    bl_idname = "framewright.inspect_production"
    bl_label = "Inspect Production Data"
    kind: EnumProperty(
        items=[
            ("MESH", "Evaluated Mesh", ""),
            ("SURFACES", "UVs and Materials", ""),
            ("RIG", "Rig and Weights", ""),
            ("ANIMATION", "Animation", ""),
            ("RESOURCES", "Scene Resources", ""),
        ]
    )

    def execute(self, context):
        commands = {
            "MESH": "mesh.inspect_evaluated",
            "SURFACES": "surfaces.inspect",
            "RIG": "rig.inspect",
            "ANIMATION": "animation.inspect",
            "RESOURCES": "scene.resources",
        }
        params = {}
        if self.kind != "RESOURCES":
            if not context.active_object:
                self.report({"ERROR"}, "Select an object to inspect")
                return {"CANCELLED"}
            params["object_name"] = context.active_object.name
        return _run(self, context, commands[self.kind], params)


class FRAMEWRIGHT_OT_review_lighting(bpy.types.Operator):
    bl_idname = "framewright.review_lighting"
    bl_label = "Create Review Scene"
    bl_options = {"REGISTER", "UNDO"}
    lighting: EnumProperty(
        items=[("neutral", "Neutral", ""), ("day", "Day", ""), ("dusk", "Dusk", "")]
    )

    def execute(self, context):
        params = {"lighting": self.lighting, "dry_run": False}
        if context.scene.framewright_review_collection:
            params["collection_name"] = context.scene.framewright_review_collection
        else:
            params["object_names"] = [obj.name for obj in context.selected_objects]
        return _run(self, context, "lighting.create_review", params)


class FRAMEWRIGHT_OT_make_derivative(bpy.types.Operator):
    bl_idname = "framewright.make_derivative"
    bl_label = "Create Hidden Derivative"
    bl_options = {"REGISTER", "UNDO"}
    kind: EnumProperty(
        items=[
            ("LOD", "LOD Mesh", ""),
            ("COLLISION", "Convex Collision", ""),
            ("WEIGHTS", "Normalize Skin Weights", ""),
        ]
    )
    ratio: FloatProperty(name="LOD Ratio", min=0.01, max=0.99, default=0.5)

    def execute(self, context):
        if not context.active_object:
            self.report({"ERROR"}, "Select a supported source mesh")
            return {"CANCELLED"}
        commands = {
            "LOD": "model.create_lod",
            "COLLISION": "model.create_collision",
            "WEIGHTS": "rig.normalize_weights",
        }
        params = {"object_name": context.active_object.name, "dry_run": False}
        if self.kind == "LOD":
            params["ratio"] = self.ratio
        return _run(self, context, commands[self.kind], params)


class FRAMEWRIGHT_OT_run_request(bpy.types.Operator):
    bl_idname = "framewright.run_request"
    bl_label = "Run JSON Request"
    bl_description = "Execute a validated Framewright request; edits require explicit dry_run false"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            text = context.scene.framewright_request_json
            request = parse_request_json(text)
        except ValueError as error:
            context.scene.framewright_tool_report = json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": None,
                    "ok": False,
                    "error": {"code": "INVALID_REQUEST", "message": str(error)},
                }
            )
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        response = dispatch(request)
        context.scene.framewright_tool_report = json.dumps(response, indent=2)
        if not response["ok"]:
            self.report({"ERROR"}, response["error"]["message"])
            return {"CANCELLED"}
        if request["command"] == "workflow.run" and response["result"]["status"] in {
            "failed",
            "cancelled",
        }:
            self.report(
                {"ERROR"}, "Workflow stopped; inspect its report. Earlier derivatives are retained."
            )
            return {"CANCELLED"}
        return {"FINISHED"}


class FRAMEWRIGHT_OT_open_tool_report(bpy.types.Operator):
    bl_idname = "framewright.open_tool_report"
    bl_label = "Create Report Text"

    def execute(self, context):
        text = bpy.data.texts.new("Framewright_Report.json")
        text.write(context.scene.framewright_tool_report or "{}")
        self.report({"INFO"}, f"Open {text.name} in the Text Editor")
        return {"FINISHED"}


class FRAMEWRIGHT_PT_production(bpy.types.Panel):
    bl_label = "Production Tools"
    bl_idname = "FRAMEWRIGHT_PT_production"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Framewright"

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Inspect Selected Object")
        for kind, label in [
            ("MESH", "Evaluated Mesh"),
            ("SURFACES", "UVs and Materials"),
            ("RIG", "Rig and Weights"),
            ("ANIMATION", "Animation"),
            ("RESOURCES", "Scene Resources"),
        ]:
            box.operator("framewright.inspect_production", text=label).kind = kind
        box = layout.box()
        box.label(text="Create at 3D Cursor")
        box.operator("framewright.build_asset", text="Workshop Cabinet").kind = "CABINET"
        box.operator("framewright.build_asset", text="Facade Bay").kind = "FACADE"
        box = layout.box()
        box.label(text="Review Lighting")
        box.prop(context.scene, "framewright_review_collection", text="Collection")
        for mode in ("neutral", "day", "dusk"):
            box.operator(
                "framewright.review_lighting", text=mode.title() + " Review Scene"
            ).lighting = mode
        box = layout.box()
        box.label(text="Preserve Source, Create Derivative")
        for kind, label in [
            ("LOD", "LOD Mesh"),
            ("COLLISION", "Convex Collision"),
            ("WEIGHTS", "Normalize Skin Weights"),
        ]:
            box.operator("framewright.make_derivative", text=label).kind = kind
        layout.operator("framewright.open_tool_report")
        box = layout.box()
        box.label(text="AI / Advanced Request")
        box.prop(context.scene, "framewright_request_json", text="JSON")
        box.operator("framewright.run_request")


CLASSES = (
    FRAMEWRIGHT_OT_build_asset,
    FRAMEWRIGHT_OT_inspect_production,
    FRAMEWRIGHT_OT_review_lighting,
    FRAMEWRIGHT_OT_make_derivative,
    FRAMEWRIGHT_OT_run_request,
    FRAMEWRIGHT_OT_open_tool_report,
    FRAMEWRIGHT_PT_production,
)


SCENE_PROPERTIES = (
    "framewright_tool_report",
    "framewright_review_collection",
    "framewright_request_json",
)
_REGISTRATION = {"classes": [], "properties": {}}


def assert_registration_available():
    _assert_registration_available(CLASSES, SCENE_PROPERTIES, _REGISTRATION)


def register():
    properties = {
        "framewright_tool_report": StringProperty(default=""),
        "framewright_review_collection": StringProperty(default=""),
    }
    properties["framewright_request_json"] = StringProperty(
        default=json.dumps(
            {
                "schema_version": "1.0",
                "request_id": "sidebar",
                "command": "capabilities",
                "params": {},
            }
        )
    )
    _register_components(CLASSES, properties, _REGISTRATION)


def unregister():
    _unregister_components(_REGISTRATION)
