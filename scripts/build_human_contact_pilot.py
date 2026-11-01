"""Owned human sole contact pilot; runs only in a factory background Blender process."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

from framewright import secondary_motion  # noqa: E402
from framewright.api import dispatch  # noqa: E402

SOURCE = ROOT / "artifacts/knee-refinement/20261030T175350Z-d566f95d/public-api-candidate.blend"
RIG = "Provisional_Human_Basic_Metarig_Source_FW_FittedMetarig_FW_Rig_FW_Pose_FW_Pose"
SKIN = "GEO-body_male_realistic_FW_Bound_FW_PoseSkin_FW_PoseSkin_FW_Corrective_FW_Corrective_FW_PublicPreparation_FW_AngleCorrective_FW_AngleCorrective"
PHASES = [
    {
        "frames": [1, 15],
        "intent": "Both soles planted; left and right contact expected at the authored sole points",
    },
    {"frames": [16, 30], "intent": "Left foot lifts and moves forward; right sole remains planted"},
    {"frames": [31, 40], "intent": "Left foot held above ground; right sole remains planted"},
    {"frames": [41, 50], "intent": "Left foot lowers to new placement; right sole remains planted"},
    {
        "frames": [51, 61],
        "intent": "Both feet planted; left foot is forward of its initial placement",
    },
]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_state(rig, skin):
    return {
        "rig_basis": {
            bone.name: [list(row) for row in bone.matrix_basis] for bone in rig.pose.bones
        },
        "rig_action": rig.animation_data.action.name
        if rig.animation_data and rig.animation_data.action
        else None,
        "weights": [[(g.group, g.weight) for g in vertex.groups] for vertex in skin.data.vertices],
        "shape_keys": {
            key.name: {"value": key.value, "coordinates": [list(point.co) for point in key.data]}
            for key in skin.data.shape_keys.key_blocks
        },
        "shape_drivers": [
            (
                curve.data_path,
                curve.driver.expression,
                [
                    (
                        variable.type,
                        [
                            (
                                target.id.name if target.id else None,
                                target.data_path,
                                target.bone_target,
                            )
                            for target in variable.targets
                        ],
                    )
                    for variable in curve.driver.variables
                ],
            )
            for curve in skin.data.shape_keys.animation_data.drivers
        ],
    }


def state_hash(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()


def mesh(name, vertices, faces, scene):
    data = bpy.data.meshes.new(name + "Mesh")
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    return obj


def evaluated(obj):
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = ev.to_mesh()
    try:
        data.calc_loop_triangles()
        return [ev.matrix_world @ vertex.co for vertex in data.vertices], [
            tuple(triangle.vertices) for triangle in data.loop_triangles
        ]
    finally:
        ev.to_mesh_clear()


def linear(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"


def author_scene(source_rig, source_skin):
    capture = secondary_motion.capture_pose(
        {"object_name": source_rig.name, "bones": ["foot_ik.L", "foot_ik.R"]}
    )
    copy = secondary_motion.apply_pose(
        {
            "object_name": source_rig.name,
            "pose": capture["pose"],
            "bone_map": {"foot_ik.L": "foot_ik.L", "foot_ik.R": "foot_ik.R"},
            "bound_mesh_names": [source_skin.name],
            "dry_run": False,
        }
    )
    rig = bpy.data.objects[copy["derivative"]]
    skin = bpy.data.objects[copy["bound_derivatives"][0]]
    rig.name = "FW_HumanContact_Rig"
    skin.name = "FW_HumanContact_Skin"
    scene = bpy.data.scenes.new("FW_HumanContact_Pilot")
    scene.frame_start, scene.frame_end = 1, 61
    scene.render.fps = 24
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    for obj in (rig, skin):
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        scene.collection.objects.link(obj)
        obj.hide_viewport = obj.hide_render = False
    bpy.context.window.scene = scene
    rig.location = (0, 0, 0)
    for bone in rig.pose.bones:
        if not bone.name.startswith(("ORG-", "DEF-", "MCH-")):
            bone.matrix_basis = Matrix.Identity(4)
    for side in ("L", "R"):
        parent = rig.pose.bones[f"thigh_parent.{side}"]
        parent["IK_FK"] = 0.0
        parent["IK_Stretch"] = 0.0
    rig.update_tag()
    skin.update_tag()
    scene.frame_set(1)
    bpy.context.view_layer.update()
    return scene, rig, skin


def author_markers(skin, folder):
    points, triangles = evaluated(skin)
    # Explicit authoring regions in the normalized pilot's world meters. These
    # are recorded candidate regions, not anatomical labels inferred by the API.
    regions = {
        "L": {"x": [0.05, 0.4], "y": [-0.3, 0.2], "z": [-0.12, 0.08]},
        "R": {"x": [-0.4, -0.05], "y": [-0.3, 0.2], "z": [-0.12, 0.08]},
    }
    candidates = {}
    for side, region in regions.items():
        found = [
            (index, point)
            for index, point in enumerate(points)
            if all(
                region[axis][0] <= point[axis_index] <= region[axis][1]
                for axis_index, axis in enumerate("xyz")
            )
        ]
        if not found:
            raise RuntimeError(f"No evaluated sole-region candidates on {side}")
        lowest = min(point.z for _, point in found)
        candidates[side] = [(index, point) for index, point in found if point.z <= lowest + 0.012]
    write(
        folder / "sole-candidates.json",
        {
            "regions": regions,
            "points": {
                side: [{"index": i, "world": list(p)} for i, p in values]
                for side, values in candidates.items()
            },
        },
    )
    definitions, authored = [], []
    for side, values in candidates.items():
        minx, maxx = min(p.x for _, p in values), max(p.x for _, p in values)
        miny, maxy = min(p.y for _, p in values), max(p.y for _, p in values)
        # +Y is heelward on this source; -Y is the toe direction. The nearest
        # actual skin vertices are retained verbatim and rendered for review.
        targets = {
            "heel_inner": (0.3, 0.85),
            "heel_outer": (0.7, 0.85),
            "ball_inner": (0.3, 0.35),
            "ball_outer": (0.7, 0.35),
            "toe": (0.5, 0.05),
        }
        chosen = set()
        for label, (u, v) in targets.items():
            if side == "R":
                u = 1 - u
            target = Vector(
                (minx + (maxx - minx) * u, miny + (maxy - miny) * v, min(p.z for _, p in values))
            )
            index, point = min(
                (item for item in values if item[0] not in chosen),
                key=lambda item: (item[1] - target).length_squared,
            )
            chosen.add(index)
            definition = {
                "id": f"{side}_{label}",
                "object_name": skin.name,
                "vertex_indices": [index],
                "weights": [1],
            }
            definitions.append(definition)
            authored.append(
                {
                    **definition,
                    "authoring_world_target": list(target),
                    "neutral_evaluated_world": list(point),
                    "scope": "Provisional authored sole point; requires visual/artist review",
                }
            )
    return definitions, authored, min(p.z for values in candidates.values() for _, p in values)


def author_clip(scene, rig):
    foot = rig.pose.bones["foot_ik.L"]
    base = foot.matrix.copy()
    world_to_rig = rig.matrix_world.inverted().to_3x3()
    keys = [
        (1, (0, 0, 0)),
        (15, (0, 0, 0)),
        (18, (0, 0, 0.04)),
        (30, (0, -0.12, 0.14)),
        (40, (0, -0.12, 0.14)),
        (50, (0, -0.12, 0)),
        (61, (0, -0.12, 0)),
    ]
    for frame, delta in keys:
        matrix = base.copy()
        matrix.translation += world_to_rig @ Vector(delta)
        foot.matrix = matrix
        foot.keyframe_insert("location", frame=frame)
        foot.keyframe_insert("rotation_quaternion", frame=frame)
    linear(rig.animation_data.action)
    rig.animation_data.action.name = "FW_Authored_LeftLiftPlant_61"
    scene.frame_set(1)
    return {
        "control": "foot_ik.L",
        "keys": [{"frame": frame, "world_offset_meters": list(delta)} for frame, delta in keys],
        "interpolation": "LINEAR",
        "fps": 24,
        "phases": PHASES,
    }


def public_report(params, request_id):
    response = dispatch(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "command": "animation.skin_contacts",
            "params": params,
        }
    )
    if not response["ok"]:
        raise RuntimeError(json.dumps(response))
    return response["result"]


def measure_phases(report):
    result = []
    for phase in PHASES:
        samples = [
            sample
            for sample in report["samples"]
            if phase["frames"][0] <= sample["frame"] + sample["subframe"] <= phase["frames"][1]
        ]
        sides = {}
        for side in ("L", "R"):
            values = [
                marker
                for sample in samples
                for marker in sample["markers"]
                if marker["id"].startswith(side + "_")
            ]
            distances = [
                marker["normal_distance_meters"]
                for marker in values
                if marker["normal_distance_meters"] is not None
            ]
            sides[side] = {
                "marker_samples": len(values),
                "contact_samples": sum(m["contact"] is True for m in values),
                "penetration_samples": sum(m["penetrating"] is True for m in values),
                "sliding_segments": sum(m["sliding"] is True for m in values),
                "minimum_distance_m": min(distances),
                "maximum_distance_m": max(distances),
            }
        result.append({**phase, "observed": sides})
    return result


def negative_controls(scene, rig, ground, params, folder):
    records = {}
    ground.location.z = 0.04
    penetration = public_report(params, "human-penetration-control")
    assert penetration["penetration_samples"] > 0
    records["raised_surface_penetration"] = {
        "offset_m": 0.04,
        "penetration_samples": penetration["penetration_samples"],
    }
    ground.location = (10, 0, 0)
    misses = public_report(params, "human-miss-control")
    assert misses["projection_misses"] == 121 * len(params["markers"])
    assert all(
        marker["contact"] is None for sample in misses["samples"] for marker in sample["markers"]
    )
    records["missing_surface"] = {
        "offset_m": [10, 0, 0],
        "projection_misses": misses["projection_misses"],
        "coverage": misses["coverage"],
        "contacts_unknown": True,
    }
    ground.location = (0, 0, 0)
    animation = rig.animation_data
    original_action, original_slot = animation.action, animation.action_slot
    copied_action = original_action.copy()
    copied_action.name = "FW_ContactNegativeControl"
    animation.action = copied_action
    animation.action_slot = copied_action.slots[original_slot.identifier]
    try:
        for frame, x in ((1, 0), (61, 0.12)):
            rig.location.x = x
            rig.keyframe_insert("location", frame=frame)
        linear(copied_action)
        slide = public_report(params, "human-slide-control")
        planted = [
            marker
            for sample in slide["samples"]
            for marker in sample["markers"]
            if marker["id"].startswith("R_")
        ]
        assert sum(marker["sliding"] is True for marker in planted) > 0
        records["injected_root_slide"] = {
            "root_translation_m": 0.12,
            "right_planted_sliding_segments": sum(marker["sliding"] is True for marker in planted),
        }
        for frame, x in ((1, 0), (61, 0.12)):
            ground.location.x = x
            ground.keyframe_insert("location", frame=frame)
        linear(ground.animation_data.action)
        platform = public_report(params, "human-platform-control")
        planted = [
            marker
            for sample in platform["samples"]
            for marker in sample["markers"]
            if marker["id"].startswith("R_")
        ]
        assert all(marker["sliding"] is not True for marker in planted)
        records["matching_rigid_platform"] = {
            "surface_and_root_translation_m": 0.12,
            "right_planted_sliding_segments": 0,
            "max_relative_tangent_speed_mps": max(
                marker["relative_tangent_speed_mps"] or 0 for marker in planted
            ),
        }
    finally:
        animation.action = original_action
        animation.action_slot = original_slot
        bpy.data.actions.remove(copied_action)
        if ground.animation_data and ground.animation_data.action:
            action = ground.animation_data.action
            ground.animation_data_clear()
            if action.users == 0:
                bpy.data.actions.remove(action)
        rig.location = (0, 0, 0)
        ground.location = (0, 0, 0)
        scene.frame_set(1)
    write(folder / "negative-controls.json", records)
    return records


def prop_case(scene, folder):
    table = mesh(
        "FW_PropContactTable",
        [(0.4, -0.5, 0.72), (0.8, -0.5, 0.72), (0.8, 0.2, 0.72), (0.4, 0.2, 0.72)],
        [(0, 1, 2), (0, 2, 3)],
        scene,
    )
    prop = mesh(
        "FW_ContactProp",
        [
            (-0.06, -0.04, -0.04),
            (0.06, -0.04, -0.04),
            (0.06, 0.04, -0.04),
            (-0.06, 0.04, -0.04),
            (-0.06, -0.04, 0.04),
            (0.06, -0.04, 0.04),
            (0.06, 0.04, 0.04),
            (-0.06, 0.04, 0.04),
        ],
        [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)],
        scene,
    )
    for frame, position in (
        (1, (0.6, 0, 0.76)),
        (15, (0.6, 0, 0.76)),
        (18, (0.6, 0, 0.8)),
        (30, (0.6, -0.2, 1.0)),
        (40, (0.6, -0.2, 1.0)),
        (50, (0.6, -0.2, 0.76)),
        (61, (0.6, -0.2, 0.76)),
    ):
        prop.location = position
        prop.keyframe_insert("location", frame=frame)
    linear(prop.animation_data.action)
    params = {
        "surface_name": table.name,
        "markers": [
            {
                "id": f"prop_bottom_{index}",
                "object_name": prop.name,
                "vertex_indices": [index],
                "weights": [1],
            }
            for index in range(4)
        ],
        "frame_start": 1,
        "frame_end": 61,
        "substeps": 2,
        "max_samples": 121,
        "contact_tolerance": 0.012,
        "penetration_tolerance": 0.005,
        "sliding_speed": 0.03,
        "search_distance": 0.5,
    }
    write(folder / "prop-request.json", params)
    report = public_report(params, "prop-lift-place")
    assert report["projection_misses"] == 0 and report["penetration_samples"] == 0
    for sample in report["samples"]:
        time = sample["frame"] + sample["subframe"]
        if time <= 15 or time >= 51:
            assert all(marker["contact"] is True for marker in sample["markers"])
        if 31 <= time <= 40:
            assert all(marker["contact"] is False for marker in sample["markers"])
    write(folder / "prop-report.json", report)
    write(
        folder / "prop-scope.json",
        {
            "type": "Independently authored rigid box lift/place fixture",
            "hand_attached": False,
            "grip_reviewed": False,
            "table_height_m": 0.72,
            "box_dimensions_m": [0.12, 0.08, 0.08],
            "samples": 121,
            "phases": PHASES,
        },
    )
    return prop, table


def matte(name, color):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = 0.7
    return material


def point_camera(camera, position, target, scale):
    camera.location = position
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = scale


def setup_review(scene, skin, ground, prop, table, report):
    world = bpy.data.worlds.new("FW_ContactReviewWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.16, 0.18, 0.22, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.4
    scene.world = world
    ground.data.materials.append(matte("FW_ContactGroundMaterial", (0.16, 0.18, 0.20)))
    table.data.materials.append(matte("FW_ContactTableMaterial", (0.12, 0.16, 0.20)))
    prop.data.materials.append(matte("FW_ContactPropMaterial", (0.25, 0.08, 0.015)))
    for name, position, power, size in (
        ("Key", (2, -3, 4), 550, 3),
        ("Fill", (-2, -1, 2), 250, 2),
        ("Rim", (0, 3, 3), 400, 2),
    ):
        data = bpy.data.lights.new("FW_Contact" + name, "AREA")
        data.energy, data.shape, data.size = power, "DISK", size
        light = bpy.data.objects.new("FW_Contact" + name, data)
        scene.collection.objects.link(light)
        light.location = position
        light.rotation_euler = (
            (Vector((0, 0, 0.8)) - light.location).to_track_quat("-Z", "Y").to_euler()
        )
    data = bpy.data.cameras.new("FW_ContactCamera")
    camera = bpy.data.objects.new("FW_ContactCamera", data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    colors = {
        "L": matte("FW_LeftSoleMarker", (0.03, 0.65, 0.15)),
        "R": matte("FW_RightSoleMarker", (0.95, 0.25, 0.03)),
    }
    for index, definition in enumerate(report["marker_definitions"]):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.004)
        obj = bpy.context.object
        obj.name = "FW_Marker_" + definition["id"]
        obj.data.materials.append(colors[definition["id"][0]])
        for sample in report["samples"]:
            obj.location = sample["markers"][index]["position_meters"]
            obj.keyframe_insert("location", frame=sample["frame"] + sample["subframe"])
        linear(obj.animation_data.action)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0
    scene.render.film_transparent = False
    return camera


def render_review(scene, camera, skin, ground, folder):
    from bpy_extras.object_utils import world_to_camera_view

    images = folder / "review"
    images.mkdir()
    scene.render.resolution_x, scene.render.resolution_y = 320, 480
    point_camera(camera, (2.8, -4, 2.2), (0.15, -0.04, 0.82), 2.05)
    for frame in range(1, 62):
        scene.frame_set(frame)
        points, _ = evaluated(skin)
        projected = [world_to_camera_view(scene, camera, point) for point in points]
        assert all(point.z > 0 for point in projected), "Human behind review camera"
        assert max(point.y for point in projected) - min(point.y for point in projected) > 0.55, (
            "Human too small in review frame"
        )
        scene.render.filepath = str(images / f"motion-{frame:03d}.png")
        bpy.ops.render.render(write_still=True)
    scene.render.resolution_x = scene.render.resolution_y = 512
    point_camera(camera, (1.0, -1.4, 0.48), (0, -0.07, 0.12), 0.72)
    for frame in (1, 23, 35, 46, 61):
        scene.frame_set(frame)
        scene.render.filepath = str(images / f"feet-{frame:03d}.png")
        bpy.ops.render.render(write_still=True)
    ground.hide_render = True
    scene.frame_set(1)
    point_camera(camera, (0, -0.025, -1), (0, -0.025, 0), 0.72)
    scene.render.filepath = str(images / "sole-markers-underside.png")
    bpy.ops.render.render(write_still=True)
    ground.hide_render = False
    point_camera(camera, (2.8, -4, 2.2), (0.15, -0.04, 0.82), 2.05)
    scene.render.resolution_x, scene.render.resolution_y = 320, 480
    scene.frame_set(1)
    (folder / "review.html").write_text(
        """<!doctype html><meta charset="utf-8"><title>Framewright human contact pilot</title>
<style>body{font:16px system-ui;background:#17191e;color:#eee;max-width:1100px;margin:2em auto}img{max-width:48%;vertical-align:top}label{display:block;margin:1em}button{padding:.5em}p{max-width:850px}</style>
<h1>Authored sole and prop contact pilot</h1><p>Technical 61-frame lift/place fixture. Green/orange markers are explicit evaluated skin vertices. The box is an independent prop contact fixture, not a hand grip. Existing body deformation is provisional; no artistic or native acceptance.</p>
<button id="play">Play / pause</button><label>Frame <output id="label">1</output> <input id="frame" type="range" min="1" max="61" value="1"></label><img id="motion" src="review/motion-001.png"><img src="review/feet-035.png">
<p>Foot views: initial stance, lift, hold, lowering, planted. Contact is sampled every half-frame; these images show integer frames. No continuous collision guarantee.</p>
<img src="review/feet-001.png"><img src="review/feet-023.png"><img src="review/feet-046.png"><img src="review/feet-061.png"><img src="review/sole-markers-underside.png">
<script>let playing=false;const f=document.getElementById('frame');function show(){document.getElementById('label').value=f.value;document.getElementById('motion').src='review/motion-'+f.value.padStart(3,'0')+'.png'}f.oninput=show;document.getElementById('play').onclick=()=>playing=!playing;setInterval(()=>{if(playing){f.value=Number(f.value)%61+1;show()}},1000/24)</script>""",
        encoding="utf-8",
    )
    write(
        folder / "render-settings.json",
        {
            "engine": "Cycles CPU",
            "samples": 12,
            "view_transform": "AgX",
            "exposure": 0,
            "motion_frames": 61,
            "motion_resolution": [320, 480],
            "closeup_resolution": [512, 512],
            "markers": "Owned animated spheres at measured skin vertex positions",
            "human_screen_height_fraction_minimum": 0.55,
            "artist_accepted": False,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cold", type=Path)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.cold:
        params = json.loads((args.cold / "contact-request.json").read_text())
        report = public_report(params, "human-soles-cold")
        expected = json.loads((args.cold / "contact-report.json").read_text())
        assert report == expected, "Cold evaluated contact report differs"
        prop = public_report(json.loads((args.cold / "prop-request.json").read_text()), "prop-cold")
        assert prop == json.loads((args.cold / "prop-report.json").read_text()), (
            "Cold prop contact report differs"
        )
        write(
            args.cold / "cold-verification.json",
            {
                "sample_count": len(report["samples"]),
                "prop_sample_count": len(prop["samples"]),
                "exact_report_match": True,
                "autoexec_enabled": bpy.context.preferences.filepaths.use_scripts_auto_execute,
            },
        )
        return
    folder = args.output or ROOT / "artifacts/human-contact-pilot" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    source_hash = file_hash(SOURCE)
    source_rig, source_skin = bpy.data.objects[RIG], bpy.data.objects[SKIN]
    state_before = state_hash(source_state(source_rig, source_skin))
    scene, rig, skin = author_scene(source_rig, source_skin)
    markers, authored, floor_height = author_markers(skin, folder)
    ground = mesh(
        "FW_ContactGround",
        [
            (-2, -2, floor_height),
            (2, -2, floor_height),
            (2, 2, floor_height),
            (-2, 2, floor_height),
        ],
        [(0, 1, 2), (0, 2, 3)],
        scene,
    )
    clip = author_clip(scene, rig)
    write(
        folder / "authored-intent.json",
        {
            "clip": clip,
            "markers": authored,
            "surface_z_m": floor_height,
            "artist_accepted": False,
            "known_source_limits": [
                "Provisional fitting/weights",
                "Residual knee crease and hip/shoulder compression",
                "No native engine acceptance",
            ],
        },
    )
    params = {
        "surface_name": ground.name,
        "markers": markers,
        "frame_start": 1,
        "frame_end": 61,
        "substeps": 2,
        "max_samples": 121,
        "contact_tolerance": 0.012,
        "penetration_tolerance": 0.005,
        "sliding_speed": 0.03,
        "search_distance": 0.5,
    }
    write(folder / "contact-request.json", params)
    report = public_report(params, "human-soles-main")
    write(folder / "contact-report.json", report)
    write(folder / "phase-observations.json", measure_phases(report))
    assert len(report["samples"]) == 121 and report["temporal_coverage"]["every_integer_frame"]
    assert report["projection_misses"] == 0 and report["penetration_samples"] == 0
    negative_controls(scene, rig, ground, params, folder)
    assert public_report(params, "post-controls-baseline") == report, (
        "Negative controls changed baseline"
    )
    prop, table = prop_case(scene, folder)
    camera = setup_review(scene, skin, ground, prop, table, report)
    if args.render:
        render_review(scene, camera, skin, ground, folder)
    else:
        point_camera(camera, (2.8, -4, 2.2), (0.15, -0.04, 0.82), 2.05)
    assert state_hash(source_state(source_rig, source_skin)) == state_before, (
        "Source rig/keys/weights changed"
    )
    assert file_hash(SOURCE) == source_hash
    scene.frame_set(1)
    target = folder / "authored-human-contact.blend"
    preference = bpy.context.preferences.filepaths.save_version
    try:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True)
    finally:
        bpy.context.preferences.filepaths.save_version = preference
    child = subprocess.run(
        [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            str(target),
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold",
            str(folder),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    (folder / "cold.log").write_text(child.stdout + child.stderr, encoding="utf-8")
    assert child.returncode == 0, child.stdout + child.stderr
    write(
        folder / "receipt.json",
        {
            "source_path": str(SOURCE.relative_to(ROOT)),
            "source_sha256": source_hash,
            "source_unchanged": file_hash(SOURCE) == source_hash,
            "source_state_sha256": state_before,
            "owned_blend_sha256": file_hash(target),
            "sample_count": len(report["samples"]),
            "marker_count": len(markers),
            "artist_accepted": False,
            "blender": bpy.app.version_string,
        },
    )
    print("FRAMEWRIGHT_HUMAN_CONTACT_PILOT", folder)


if __name__ == "__main__":
    main()
