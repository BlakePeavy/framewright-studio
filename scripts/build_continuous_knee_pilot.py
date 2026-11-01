"""Build and measure an independent bilateral angle-driven knee corrective pilot."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from build_human_rig_pilot import _aim_control, _flexed_direction, sha256, source_hash  # noqa: E402
from knee_corrective_activation import install_knee_activation  # noqa: E402
from mathutils import Vector  # noqa: E402
from refine_human_rig_pilot import assert_subject_visible, regional_metrics, sample_geometry  # noqa: E402

from framewright import rigging, secondary_motion  # noqa: E402


def measured_angle(rig, side):
    points = [
        rig.matrix_world @ rig.pose.bones[f"ORG-{name}.{side}"].head
        for name in ("thigh", "shin", "foot")
    ]
    proximal, distal = (points[1] - points[0]).normalized(), (points[2] - points[1]).normalized()
    return math.degrees(math.atan2(proximal.cross(distal).length, proximal.dot(distal)))


def knee_clip(rig):
    angles = [0, 10, 20, 30, 45, 60, 75, 90, 100, 110, 120, 130, 110, 90, 60, 30, 0]
    poses = {index + 1: (angle, angle) for index, angle in enumerate(angles)}
    poses.update({18: (110, 0), 19: (0, 110), 20: (75, 45)})
    rig.animation_data.action = None
    controls = [name for name in rig.pose.bones.keys() if "_fk." in name] + ["head"]
    for side in ("L", "R"):
        rig.pose.bones[f"thigh_parent.{side}"]["IK_FK"] = 1.0
    for frame, pair in poses.items():
        bpy.context.scene.frame_set(frame)
        for name in controls:
            bone = rig.pose.bones[name]
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.location = (0, 0, 0)
            bone.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        for side, angle in zip(("L", "R"), pair, strict=True):
            thigh = rig.data.bones[f"thigh_fk.{side}"]
            direction = _flexed_direction(thigh.tail_local - thigh.head_local, (0, 1, 0), angle)
            _aim_control(rig, f"shin_fk.{side}", direction)
        for name in controls:
            rig.pose.bones[name].keyframe_insert("rotation_quaternion", frame=frame)
    action = rig.animation_data.action
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"
    bpy.context.scene.frame_set(1)
    return poses


def evaluate_continuous(rig, baseline, candidate, affected):
    rows = []
    rest = [vertex.co.copy() for vertex in baseline.data.vertices]
    both = set(affected["L"]) | set(affected["R"])
    for half_frame in range(2, 41):
        time = half_frame / 2
        bpy.context.scene.frame_set(int(time), subframe=time - int(time))
        bpy.context.view_layer.update()
        before, edges, before_triangles = sample_geometry(baseline)
        after, _, triangles = sample_geometry(candidate)
        outside = max(
            (after[index] - before[index]).length
            for index in range(len(before))
            if index not in both
        )
        if outside > 1e-6:
            raise AssertionError(
                f"Corrective moved protected outside-knee vertex at {time}: {outside}"
            )
        row = {"time": time, "outside_patch_max_displacement": outside, "joints": {}}
        for side in ("L", "R"):
            angle = measured_angle(rig, side)
            fraction = max(0, min(1, (angle - 20) / 90))
            expected = (1 - math.cos(math.pi * fraction)) / 2
            key = candidate.data.shape_keys.key_blocks["FW_ContinuousKnee." + side]
            actual = key.value
            if abs(actual - expected) > 2e-5:
                raise AssertionError((time, side, angle, actual, expected))
            displacement = max((after[index] - before[index]).length for index in affected[side])
            if expected < 1e-7 and displacement > 1e-6:
                raise AssertionError("Inactive side received corrective displacement")
            row["joints"][side] = {
                "measured_angle": angle,
                "activation": actual,
                "expected_activation": expected,
                "maximum_corrective_displacement": displacement,
            }
        if half_frame in (12, 16, 20, 24, 36, 38):
            row["baseline_regions"] = regional_metrics(rest, before, edges, before_triangles)
            row["corrected_regions"] = regional_metrics(rest, after, edges, triangles)
        rows.append(row)
    bpy.context.scene.frame_set(1)
    return rows


def render_knees(rig, baseline, candidate, folder):
    scene = bpy.context.scene
    camera = scene.camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 0.48
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.cycles.samples = 64
    scene.cycles.device = "CPU"
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = True
    rows = []
    for frame, label in (
        (6, "60deg"),
        (8, "90deg"),
        (10, "110deg"),
        (12, "130deg"),
        (18, "left110_right0"),
    ):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        target = rig.matrix_world @ rig.pose.bones["DEF-shin.L"].head
        camera.location = target + Vector((4, 0, 0.15))
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        for variant, skin in (("baseline", baseline), ("angle_driven", candidate)):
            skin.hide_render = False
            path = folder / f"{variant}_{label}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            rows.append(
                {
                    "variant": variant,
                    "frame": frame,
                    "pose": label,
                    "path": path.name,
                    "subject_coverage": assert_subject_visible(path),
                }
            )
            skin.hide_render = True
    candidate.hide_render = False
    scene.frame_set(1)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    source = args.candidate.resolve(strict=True)
    original = json.loads((source.parent / "report.json").read_text())
    source_digest = sha256(source)
    folder = args.output or ROOT / "artifacts/knee-refinement" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    bpy.context.scene.frame_set(1)
    source_rig = bpy.data.objects[original["rig"]]
    source_skin = bpy.data.objects[original["skins"]["linear"]]
    source_corrective = bpy.data.objects[original["skins"]["pose_corrected_linear"]]
    source_skin.hide_viewport = False
    bpy.context.view_layer.update()
    before = source_hash([source_skin])
    pose = secondary_motion.capture_pose({"object_name": source_rig.name, "bones": ["root"]})[
        "pose"
    ]
    receipt = secondary_motion.apply_pose(
        {
            "object_name": source_rig.name,
            "pose": pose,
            "bone_map": {"root": "root"},
            "bound_mesh_names": [source_skin.name],
            "dry_run": False,
        }
    )
    rig = bpy.data.objects[receipt["derivative"]]
    baseline = bpy.data.objects[receipt["bound_derivatives"][0]]
    rig.hide_viewport = baseline.hide_viewport = False
    rig.hide_render = True
    key = source_corrective.data.shape_keys.key_blocks["FW_knee_flexion_110"]
    basis = source_corrective.data.shape_keys.key_blocks[0]
    candidate = baseline
    affected = {}
    for side, sign in (("L", 1), ("R", -1)):
        offsets = [
            {"vertex": index, "offset": list(point.co - basis.data[index].co)}
            for index, point in enumerate(key.data)
            if basis.data[index].co.x * sign > 0 and (point.co - basis.data[index].co).length > 1e-8
        ]
        affected[side] = [item["vertex"] for item in offsets]
        protected = sorted(set(range(len(basis.data))) - set(affected[side]))
        result = rigging.corrective_shape(
            {
                "object_name": candidate.name,
                "name": "FW_ContinuousKnee." + side,
                "offsets": offsets,
                "protected_vertices": protected,
                "dry_run": False,
            }
        )
        candidate = bpy.data.objects[result["derivative"]]
        candidate.hide_viewport = False
    driver_receipts = {
        side: install_knee_activation(
            candidate.data.shape_keys.key_blocks["FW_ContinuousKnee." + side], rig, side
        )
        for side in ("L", "R")
    }
    poses = knee_clip(rig)
    samples = evaluate_continuous(rig, baseline, candidate, affected)
    renders = render_knees(rig, baseline, candidate, folder)
    if source_hash([source_skin]) != before or sha256(source) != source_digest:
        raise AssertionError("Retained input candidate changed")
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 20
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "continuous-knee-candidate.blend"))
    report = {
        "schema_version": "1.0",
        "status": "continuous_activation_verified_provisional_shape",
        "art_accepted": False,
        "knee_crease_resolved": False,
        "source": str(source),
        "source_sha256": source_digest,
        "source_skin": source_skin.name,
        "source_skin_sha256": before,
        "source_preserved": True,
        "rig": rig.name,
        "baseline": baseline.name,
        "candidate": candidate.name,
        "affected_vertices": affected,
        "drivers": driver_receipts,
        "poses": poses,
        "samples": samples,
        "renders": renders,
        "limits": [
            "Reuses the bounded knee corrective; does not claim a new anatomical shape fix",
            "Native driver activation is verified, native game driver/morph portability is not",
            "Continuous activation does not establish all-angle visual or collision acceptance",
            "No whole-body DQ change; original weights and outside-knee vertices retained",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("FRAMEWRIGHT_CONTINUOUS_KNEE " + str(folder))


if __name__ == "__main__":
    main()
