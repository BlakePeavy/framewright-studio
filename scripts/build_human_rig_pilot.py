"""Build an explicitly authored, provisional CC0 human rig and rendered pose sweep.

Run only in an owned factory-startup Blender process, supplying the pinned source bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import addon_utils  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402

from framewright import rig_binding, rig_fit, rigging, secondary_motion  # noqa: E402

SOURCE_SHA256 = "3c121505651140ceb4d69fd1d8923f7788ffadd81672f5be14845a5f2c75c137"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_hash(objects):
    values = []
    for obj in objects:
        values.append(
            {
                "name": obj.name,
                "matrix": [list(row) for row in obj.matrix_world],
                "vertices": [list(vertex.co) for vertex in obj.data.vertices],
                "faces": [list(face.vertices) for face in obj.data.polygons],
                "groups": [(group.name, group.lock_weight) for group in obj.vertex_groups],
                "weights": [
                    [(group.group, group.weight) for group in vertex.groups]
                    for vertex in obj.data.vertices
                ],
                "modifiers": [
                    (
                        modifier.type,
                        getattr(modifier, "levels", None),
                        getattr(modifier, "render_levels", None),
                    )
                    for modifier in obj.modifiers
                ],
            }
        )
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def authored_fit(metarig):
    # Authored from the source's neutral front/side views and inspected coordinates.
    # All values are explicit local meters; no bounds-driven anatomical fitting.
    spine = [
        (0, 0.025, 0.88),
        (0, 0.015, 0.98),
        (0, 0.005, 1.10),
        (0, 0.015, 1.23),
        (0, 0.015, 1.36),
        (0, 0.0, 1.425),
        (0, -0.025, 1.49),
        (0, -0.03, 1.675),
    ]
    points = {f"spine_{index}": list(point) for index, point in enumerate(spine)}
    mapping = {}
    for index in range(7):
        name = "spine" if index == 0 else f"spine.{index:03d}"
        mapping[name] = {"head": f"spine_{index}", "tail": f"spine_{index + 1}"}
    for side, sign in (("L", 1), ("R", -1)):
        local = {
            "clavicle_inner": (0.022, -0.01, 1.335),
            "clavicle_outer": (0.155, 0.005, 1.335),
            "shoulder": (0.19, 0.005, 1.325),
            "elbow": (0.285, 0.015, 1.105),
            "wrist": (0.37, -0.015, 0.91),
            "hand_end": (0.41, -0.04, 0.82),
            "chest_inner": (0.09, 0.025, 1.26),
            "chest_outer": (0.09, -0.085, 1.26),
            "pelvis_side": (0.09, -0.025, 0.96),
            "hip": (0.095, 0.015, 0.86),
            "knee": (0.135, -0.005, 0.465),
            "ankle": (0.18, 0.055, 0.095),
            "ball": (0.20, -0.025, 0.035),
            "toe": (0.225, -0.065, 0.028),
            "heel_inner": (0.15, 0.09, 0.025),
            "heel_outer": (0.205, 0.09, 0.025),
        }
        for name, (x, y, z) in local.items():
            points[f"{name}.{side}"] = [x * sign, y, z]
        for bone, head, tail in (
            ("shoulder", "clavicle_inner", "clavicle_outer"),
            ("upper_arm", "shoulder", "elbow"),
            ("forearm", "elbow", "wrist"),
            ("hand", "wrist", "hand_end"),
            ("breast", "chest_inner", "chest_outer"),
            ("thigh", "hip", "knee"),
            ("shin", "knee", "ankle"),
            ("foot", "ankle", "ball"),
            ("toe", "ball", "toe"),
            ("heel.02", "heel_inner", "heel_outer"),
        ):
            mapping[f"{bone}.{side}"] = {"head": f"{head}.{side}", "tail": f"{tail}.{side}"}
        mapping[f"pelvis.{side}"] = {"head": "spine_0", "tail": f"pelvis_side.{side}"}
    if set(mapping) != set(metarig.data.bones.keys()):
        raise RuntimeError("Installed Basic Human anatomy changed; authored map requires review")
    return {
        "object_name": metarig.name,
        "landmarks": points,
        "bone_map": mapping,
        "units": "meters",
        "coordinate_space": "armature_local",
        "dry_run": False,
    }


def stage(center, resolution, samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.world = bpy.data.worlds.new("PilotWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.3, 0.3, 0.3, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.15
    cameras = {}
    for label, offset in {
        "front": (0, -4.8, 0.15),
        "side": (4.8, 0, 0.15),
        "three_quarter": (3.3, -4.0, 1.0),
    }.items():
        data = bpy.data.cameras.new("Pilot_" + label)
        camera = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(camera)
        camera.location = center + Vector(offset)
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        data.type, data.ortho_scale = "ORTHO", 2.25
        cameras[label] = camera
    for name, offset, energy, size in (
        ("Key", (-2.5, -3, 3), 450, 3),
        ("Fill", (3, -2, 1.3), 180, 3),
        ("Rim", (0, 2, 2), 250, 2),
    ):
        data = bpy.data.lights.new("Pilot_" + name, "AREA")
        data.energy, data.shape, data.size = energy, "DISK", size
        light = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset)
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
    return cameras


def _aim_control(rig, name, direction):
    """Aim the authored FK bone in body coordinates, accounting for posed parents."""
    bone = rig.pose.bones[name]
    rest = bone.bone.matrix_local.to_quaternion()
    original = rest @ Vector((0, 1, 0))
    rotation = original.rotation_difference(Vector(direction).normalized()) @ rest
    bone.matrix = Matrix.LocRotScale(bone.head, rotation, Vector((1, 1, 1)))
    # These FK controls are rotational tests: never introduce translations/scales.
    bone.location = (0, 0, 0)
    bone.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def _flexed_direction(proximal, toward, angle):
    proximal, toward = Vector(proximal).normalized(), Vector(toward).normalized()
    toward = (toward - proximal * proximal.dot(toward)).normalized()
    radians = math.radians(angle)
    return list(proximal * math.cos(radians) + toward * math.sin(radians))


def authored_sweep(rig):
    """Author explicit body-frame anatomical directions, never guessed Euler axes."""
    poses = {
        1: {"label": "neutral", "directions_body": {}},
        10: {"label": "shoulder_abduction_90", "directions_body": {}},
        20: {"label": "shoulder_flexion_90", "directions_body": {}},
        30: {"label": "elbow_flexion_110", "directions_body": {}},
        40: {"label": "knee_flexion_110", "directions_body": {}},
        50: {
            "label": "hip_flexion_90_knee_90",
            "directions_body": {
                "thigh_fk.L": [0, -1, 0],
                "shin_fk.L": [0, 0, -1],
            },
        },
        60: {"label": "head_yaw_45", "directions_body": {}},
    }
    for side, sign in (("L", 1), ("R", -1)):
        poses[10]["directions_body"][f"upper_arm_fk.{side}"] = [sign, 0, 0]
        poses[20]["directions_body"][f"upper_arm_fk.{side}"] = [0, -1, 0]
        upper = rig.data.bones[f"upper_arm_fk.{side}"]
        thigh = rig.data.bones[f"thigh_fk.{side}"]
        poses[30]["directions_body"][f"forearm_fk.{side}"] = _flexed_direction(
            upper.tail_local - upper.head_local, (0, -1, 0), 110
        )
        poses[40]["directions_body"][f"shin_fk.{side}"] = _flexed_direction(
            thigh.tail_local - thigh.head_local, (0, 1, 0), 110
        )
    for side in ("L", "R"):
        for limb in ("upper_arm", "thigh"):
            control = rig.pose.bones[f"{limb}_parent.{side}"]
            if "IK_FK" not in control:
                raise RuntimeError("Required explicit Rigify FK switch is missing")
            control["IK_FK"] = 1.0
    controls = {name for pose in poses.values() for name in pose["directions_body"]} | {"head"}
    for frame, pose in poses.items():
        bpy.context.scene.frame_set(frame)
        for name in controls:
            bone = rig.pose.bones[name]
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.location = (0, 0, 0)
            bone.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        for name, direction in pose["directions_body"].items():
            _aim_control(rig, name, direction)
        if frame == 60:
            bone = rig.pose.bones["head"]
            rest = bone.bone.matrix_local.to_quaternion()
            bone.rotation_quaternion = (
                rest.inverted() @ Quaternion((0, 0, 1), math.radians(45)) @ rest
            )
        for name in controls:
            rig.pose.bones[name].keyframe_insert("rotation_quaternion", frame=frame)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    return poses


def measure_pose_targets(rig, poses):
    """Record actual world joints and independent direction/angle checks."""
    rows = {}
    frame, subframe = bpy.context.scene.frame_current, bpy.context.scene.frame_subframe
    try:
        for at, pose in poses.items():
            bpy.context.scene.frame_set(int(at))
            bpy.context.view_layer.update()
            world = rig.matrix_world
            directions, angles, maximum = {}, {}, 0.0
            for name, target in pose["directions_body"].items():
                bone = rig.pose.bones[name]
                actual = (world @ bone.tail - world @ bone.head).normalized()
                expected = (world.to_3x3() @ Vector(target)).normalized()
                error = math.degrees(
                    math.atan2(actual.cross(expected).length, actual.dot(expected))
                )
                maximum = max(maximum, error)
                directions[name] = {
                    "head_world": list(world @ bone.head),
                    "tail_world": list(world @ bone.tail),
                    "target_world": list(expected),
                    "actual_world": list(actual),
                    "error_degrees": error,
                }
            for side in ("L", "R"):
                for label, names in (
                    ("knee", ("thigh", "shin", "foot")),
                    ("elbow", ("upper_arm", "forearm", "hand")),
                ):
                    a, b, c = [rig.pose.bones[f"ORG-{name}.{side}"].head for name in names]
                    proximal, distal = (b - a).normalized(), (c - b).normalized()
                    degrees = math.degrees(
                        math.atan2(proximal.cross(distal).length, proximal.dot(distal))
                    )
                    angles[f"{label}.{side}"] = {
                        "degrees": degrees,
                        "distal_direction_body": list(distal),
                        "proximal_joint_world": list(world @ a),
                        "joint_world": list(world @ b),
                        "distal_joint_world": list(world @ c),
                    }
            rows[str(at)] = {
                "label": pose["label"],
                "maximum_direction_error_degrees": maximum,
                "directions": directions,
                "joint_angles": angles,
            }
    finally:
        bpy.context.scene.frame_set(frame, subframe=subframe)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resolution", type=int, default=384)
    parser.add_argument("--samples", type=int, default=32)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    args.source = args.source.resolve(strict=True)
    if args.output:
        args.output = args.output.resolve()
    if sha256(args.source) != SOURCE_SHA256:
        raise ValueError("Source must match the independently retained v1.4.1 bundle member hash")
    if not 128 <= args.resolution <= 1024 or not 8 <= args.samples <= 128:
        raise ValueError("Bounded pilot resolution/samples exceeded")
    folder = args.output or ROOT / "artifacts/human-rig-pilot" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    with bpy.data.libraries.load(str(args.source), link=False) as (available, requested):
        requested.collections = ["Body Male - Realistic"]
    bpy.context.scene.collection.children.link(requested.collections[0])
    sources = sorted(requested.collections[0].all_objects, key=lambda obj: obj.name)
    body = bpy.data.objects["GEO-body_male_realistic"]
    bpy.context.view_layer.update()
    before = source_hash(sources)
    addon_utils.enable("rigify", default_set=True, persistent=False)
    if not addon_utils.check("rigify")[1]:
        raise RuntimeError("Bundled Rigify could not be enabled in this isolated process")
    bpy.ops.object.armature_basic_human_metarig_add()
    metarig = bpy.context.active_object
    metarig.name = "Provisional_Human_Basic_Metarig_Source"
    metarig.matrix_world = body.matrix_world.copy()
    fit_params = authored_fit(metarig)
    (folder / "authored_landmarks.json").write_text(json.dumps(fit_params, indent=2) + "\n")
    fit = rig_fit.fit_metarig(fit_params)
    generated = rigging.generate_rig({"object_name": fit["derivative"], "dry_run": False})
    rig = bpy.data.objects[generated["derivative"]]
    rig.hide_viewport = False
    rig.hide_render = True
    bpy.context.view_layer.update()
    binding = rig_binding.bind_mesh(
        {"object_name": body.name, "armature_name": rig.name, "dry_run": False}
    )
    skin = bpy.data.objects[binding["derivative"]]
    for modifier in skin.modifiers:
        if modifier.type == "MULTIRES":
            modifier.levels, modifier.render_levels = 0, 1
    skin.hide_viewport = skin.hide_render = False
    eyes = []
    for source in sources:
        if source == body:
            continue
        receipt = secondary_motion.attach_rigid(
            {
                "object_name": source.name,
                "armature_name": rig.name,
                "bone": "DEF-spine.006",
                "dry_run": False,
            }
        )
        derivative = bpy.data.objects[receipt["derivative"]]
        derivative.hide_viewport = derivative.hide_render = False
        eyes.append(receipt)
    if source_hash(sources) != before:
        raise AssertionError("Fit/generate/bind changed the appended source geometry or rig inputs")
    for source in sources:
        source.hide_viewport = source.hide_render = True
    metarig.hide_viewport = metarig.hide_render = True
    for polygon in skin.data.polygons:
        polygon.use_smooth = True
    clay = bpy.data.materials.new("PilotClay")
    shader = next(node for node in clay.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (0.4, 0.4, 0.4, 1)
    shader.inputs["Roughness"].default_value = 0.55
    skin.data.materials.clear()
    skin.data.materials.append(clay)
    poses = authored_sweep(rig)
    pose_targets = measure_pose_targets(rig, poses)
    if any(row["maximum_direction_error_degrees"] > 0.01 for row in pose_targets.values()):
        raise AssertionError("Authored pose did not reach its explicit anatomical direction")
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    deformation = rigging.sample_deformation(
        {
            "object_name": skin.name,
            "frame_start": 1,
            "frame_end": 60,
            "step": 1,
            "max_samples": 60,
            "max_vertices": 20000,
        }
    )
    cameras = stage(
        body.matrix_world.translation + Vector((0, 0, 0.85)), args.resolution, args.samples
    )
    renders = []
    for frame, pose in poses.items():
        bpy.context.scene.frame_set(frame)
        for view in ("front", "side", "three_quarter"):
            path = folder / f"{pose['label']}_{view}.png"
            bpy.context.scene.camera = cameras[view]
            bpy.context.scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            renders.append(
                {
                    "frame": frame,
                    "pose": pose["label"],
                    "view": view,
                    "path": path.name,
                    "sha256": sha256(path),
                }
            )
    bpy.context.scene.frame_set(1)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 60
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "provisional-human-rig.blend"))
    if sha256(args.source) != SOURCE_SHA256 or source_hash(sources) != before:
        raise AssertionError("Source library or original appended geometry changed")
    report = {
        "schema_version": "1.0",
        "status": "provisional_needs_artist_review",
        "art_accepted": False,
        "source": str(args.source),
        "source_sha256": SOURCE_SHA256,
        "source_objects_sha256": before,
        "source_preserved": True,
        "blender": bpy.app.version_string,
        "fit": fit,
        "binding": binding,
        "rig": rig.name,
        "skin": skin.name,
        "eyes": eyes,
        "poses": poses,
        "pose_targets": pose_targets,
        "deformation": deformation,
        "renders": renders,
        "render_settings": {
            "resolution": args.resolution,
            "samples": args.samples,
            "device": "CPU",
            "view_transform": "AgX",
            "derivative_multires_viewport": 0,
            "derivative_multires_render": 1,
        },
        "assumptions": [
            "Explicit provisional landmark coordinates authored from source views and inspected local geometry; no bounding-box fitting",
            "Bilateral landmarks intentionally symmetric; source asymmetry is not fitted",
            "Stock Basic Human with default bone rolls retained",
            "Automatic heat is an initial proposal; no artist weight painting or corrective sculpt",
            "Eyes attach rigidly to the head deform bone; no gaze or blink controls",
            "Hands have one hand bone per side; fingers and facial rigging remain unauthored",
            "Explicit body-frame shoulder directions and measured elbow/knee angles are diagnostic poses, not a performance clip",
            "No anatomy, deformation, native game or AAA acceptance",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("FRAMEWRIGHT_HUMAN_RIG_PILOT " + str(folder))


if __name__ == "__main__":
    main()
