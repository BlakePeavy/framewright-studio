"""Compare explicit anatomical poses and source-preserving skinning candidates."""

from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from build_human_rig_pilot import authored_sweep, measure_pose_targets, sha256, source_hash  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

from framewright import rigging, secondary_motion  # noqa: E402
from framewright.mesh_diagnostics import triangles_intersect_3d  # noqa: E402

REGIONS = {
    "shoulder.L": ((0.19, 0.005, 1.325), 0.16),
    "elbow.L": ((0.285, 0.015, 1.105), 0.10),
    "hip.L": ((0.095, 0.015, 0.86), 0.16),
    "knee.L": ((0.135, -0.005, 0.465), 0.13),
}


def smooth_patch_weights(source, rig, iterations=12, strength=0.6):
    """Author a derivative weight proposal within explicit symmetric joint patches."""
    copy = rigging.hidden_derivative(source, bpy.context, "JointWeightRefinement")
    copy.hide_viewport = False
    deform_names = {bone.name for bone in rig.data.bones if bone.use_deform}
    groups = {group.index: group for group in copy.vertex_groups if group.name in deform_names}
    if any(group.lock_weight for group in groups.values()):
        raise ValueError("Pilot smoothing must not modify locked groups")
    adjacency = [set() for _ in copy.data.vertices]
    for edge in copy.data.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
    patches = [
        (Vector((center[0] * side, center[1], center[2])), radius)
        for center, radius in REGIONS.values()
        for side in (1, -1)
    ]
    factors = {}
    for vertex in copy.data.vertices:
        falloff = max(
            max(0.0, 1.0 - ((vertex.co - center).length / radius) ** 2) ** 2
            for center, radius in patches
        )
        if falloff > 1e-6:
            factors[vertex.index] = strength * falloff
    before = [
        [(group.group, group.weight) for group in vertex.groups] for vertex in copy.data.vertices
    ]
    weights = [{index: dict(row).get(index, 0.0) for index in groups} for row in before]
    for _ in range(iterations):
        proposed = list(weights)
        for index, factor in factors.items():
            neighbors = adjacency[index]
            if not neighbors:
                continue
            row = {
                group: (1 - factor) * weights[index][group]
                + factor * sum(weights[neighbor][group] for neighbor in neighbors) / len(neighbors)
                for group in groups
            }
            total = sum(row.values())
            if total <= 1e-8:
                raise AssertionError("Smoothing would unweight a vertex")
            proposed[index] = {group: value / total for group, value in row.items()}
        weights = proposed
    for index in factors:
        for group, value in weights[index].items():
            if value > 1e-8:
                groups[group].add([index], value, "REPLACE")
            else:
                groups[group].remove([index])
    for vertex in copy.data.vertices:
        if (
            vertex.index not in factors
            and [(group.group, group.weight) for group in vertex.groups] != before[vertex.index]
        ):
            raise AssertionError("Protected outside-patch weights changed")
    return copy, {
        "iterations": iterations,
        "strength": strength,
        "affected_vertices": len(factors),
        "protected_vertices": len(before) - len(factors),
        "protection": "all weights outside explicit symmetric spherical patches retained exactly",
        "patches": REGIONS,
    }


def posed_smoothing_target(source, posed, labels, iterations):
    adjacency = [set() for _ in source.data.vertices]
    for edge in source.data.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
    patches = []
    for label, mirror in labels:
        center, radius = REGIONS[label]
        for sign in (1, -1) if mirror else (1,):
            patches.append((Vector((center[0] * sign, center[1], center[2])), radius))
    factors = {}
    for vertex in source.data.vertices:
        factor = max(
            max(0.0, 1.0 - ((vertex.co - center).length / radius) ** 2) ** 2
            for center, radius in patches
        )
        if factor > 1e-6:
            factors[vertex.index] = factor
    target = [co.copy() for co in posed]
    for _ in range(iterations):
        # Bounded posed-space relaxation trades local volume for removing sharp
        # folds. Volume and edge changes remain explicit comparison evidence.
        for coefficient in (0.5,):
            updated = list(target)
            for index, factor in factors.items():
                neighbors = adjacency[index]
                average = sum((target[neighbor] for neighbor in neighbors), Vector()) / len(
                    neighbors
                )
                updated[index] = target[index] + (average - target[index]) * coefficient * factor
            target = updated
    return target, sorted(factors)


def inverse_deformation_offsets(source, posed, target, indices):
    """Measure the local deformation Jacobian on an owned disposable probe."""
    probe = rigging.hidden_derivative(source, bpy.context, "JacobianProbe")
    probe.hide_viewport = False
    if probe.data.shape_keys:
        probe.shape_key_clear()
    original = [vertex.co.copy() for vertex in probe.data.vertices]
    epsilon = 0.0001
    columns = []
    try:
        baseline, _, _ = sample_geometry(probe)
        if max((baseline[index] - posed[index]).length for index in indices) > 1e-5:
            raise AssertionError("Probe does not reproduce the zero-corrective candidate")
        for axis in range(3):
            for index in indices:
                probe.data.vertices[index].co = original[index]
                probe.data.vertices[index].co[axis] += epsilon
            probe.data.update()
            measured, _, _ = sample_geometry(probe)
            columns.append(
                {index: (measured[index] - baseline[index]) / epsilon for index in indices}
            )
            for index in indices:
                probe.data.vertices[index].co = original[index]
            probe.data.update()
        offsets = []
        maximum = 0.0
        for index in indices:
            jacobian = Matrix([columns[axis][index] for axis in range(3)]).transposed()
            if abs(jacobian.determinant()) < 1e-6:
                raise ValueError("Corrective inverse is singular at this pose")
            offset = jacobian.inverted() @ (target[index] - posed[index])
            if offset.length > 0.035:
                offset *= 0.035 / offset.length
            maximum = max(maximum, offset.length)
            if offset.length > 1e-8:
                offsets.append({"vertex": index, "offset": list(offset)})
        return offsets, maximum
    finally:
        rigging.discard_derivative(probe)


def contact_projection_target(source, posed, triangles, labels, iterations):
    """Resolve intersecting local surface patches with bounded contact projections."""
    target, indices = posed_smoothing_target(source, posed, labels, 0)
    ids = set(indices)
    selected = [
        (vertices, face) for vertices, face in triangles if all(index in ids for index in vertices)
    ]
    history = []
    for _ in range(iterations):
        tree = BVHTree.FromPolygons(
            target, [vertices for vertices, _ in selected], all_triangles=True
        )
        pairs = sorted({tuple(sorted(pair)) for pair in tree.overlap(tree) if pair[0] != pair[1]})
        changes = {}
        found = 0
        for a, b in pairs:
            va, fa = selected[a]
            vb, fb = selected[b]
            if fa == fb or set(va) & set(vb):
                continue
            if not triangles_intersect_3d(
                [target[index] for index in va], [target[index] for index in vb]
            ):
                continue
            found += 1
            for vertices, other in ((va, vb), (vb, va)):
                origin = target[other[0]]
                normal = (target[other[1]] - origin).cross(target[other[2]] - origin).normalized()
                for index in vertices:
                    distance = (target[index] - origin).dot(normal)
                    if distance < 0:
                        correction = normal * min(-distance + 0.0002, 0.004)
                        changes.setdefault(index, []).append(correction)
        history.append(found)
        if found == 0 or not changes:
            break
        for index, vectors in changes.items():
            shift = sum(vectors, Vector()) / len(vectors) * 0.75
            target[index] += shift
    return target, indices, history


def make_pose_correctives(source, poses, iterations=12):
    candidate = source
    recipes = []
    for frame, labels in (
        (20, [("shoulder.L", True)]),
        (30, [("elbow.L", True)]),
        (40, [("knee.L", True)]),
        (50, [("hip.L", False), ("knee.L", False)]),
    ):
        bpy.context.scene.frame_set(frame)
        if candidate.data.shape_keys:
            for key in candidate.data.shape_keys.key_blocks:
                key.value = 0
        posed, _, triangles = sample_geometry(candidate)
        target, indices, history = authored_separation_target(candidate, posed, triangles, frame)
        offsets, maximum = inverse_deformation_offsets(candidate, posed, target, indices)
        if not offsets:
            recipes.append(
                {
                    "frame": frame,
                    "name": None,
                    "status": "no_improvement_selected",
                    "separation_trials": history,
                }
            )
            continue
        protected = sorted(set(range(len(candidate.data.vertices))) - set(indices))
        name = "FW_" + poses[frame]["label"]
        result = rigging.corrective_shape(
            {
                "object_name": candidate.name,
                "name": name,
                "offsets": offsets,
                "protected_vertices": protected,
                "dry_run": False,
            }
        )
        candidate = bpy.data.objects[result["derivative"]]
        candidate.hide_viewport = False
        recipes.append(
            {
                "frame": frame,
                "name": name,
                "patches": labels,
                "affected_vertices": len(offsets),
                "affected_vertex_indices": [item["vertex"] for item in offsets],
                "protected_vertices": len(protected),
                "maximum_basis_offset_meters": maximum,
                "iterations": iterations,
                "separation_trials": history,
                "recipe": "explicit authored distal-surface separation field, finite-difference inverse deformation, basis-relative key",
            }
        )
    keys = candidate.data.shape_keys
    if keys is None:
        return candidate, recipes
    keys.animation_data_clear()
    for frame in poses:
        for recipe in recipes:
            if recipe["name"] is None:
                continue
            key = keys.key_blocks[recipe["name"]]
            key.value = 1.0 if frame == recipe["frame"] else 0.0
            key.keyframe_insert("value", frame=frame)
    bpy.context.scene.frame_set(1)
    return candidate, recipes


def authored_separation_target(source, posed, triangles, frame):
    fields = {
        20: ("shoulder.L", (0.215, 0.0, 1.285), (0.12, 0.13, 0.15), (1, 0, 0), True),
        30: ("elbow.L", (0.305, -0.025, 1.065), (0.09, 0.09, 0.12), (0, -1, 0), True),
        40: ("knee.L", (0.14, 0.025, 0.42), (0.085, 0.10, 0.14), (0, 1, 0), True),
        50: ("hip.L", (0.105, -0.055, 0.81), (0.13, 0.13, 0.15), (0, 0, -1), False),
    }
    label, center, radii, direction, mirror = fields[frame]
    weights = {}
    for vertex in source.data.vertices:
        sign = 1 if vertex.co.x >= 0 else -1
        if sign < 0 and not mirror:
            continue
        origin = Vector((center[0] * sign, center[1], center[2]))
        distance = sum(((vertex.co[axis] - origin[axis]) / radii[axis]) ** 2 for axis in range(3))
        factor = max(0, 1 - distance) ** 2
        if factor > 1e-6:
            weights[vertex.index] = (sign, factor)
    region_names = [label, label.replace(".L", ".R")] if mirror else [label]
    trials = []
    best = None
    rest = [vertex.co.copy() for vertex in source.data.vertices]
    edges = [tuple(edge.vertices) for edge in source.data.edges]
    baseline = regional_metrics(rest, posed, edges, triangles)
    proposals = [((0, 0, 0), 0)] + [
        (axis, amplitude)
        for axis in (direction, (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
        for amplitude in (0.005, 0.01, 0.02, 0.03)
    ]
    for direction, amplitude in proposals:
        target = [co.copy() for co in posed]
        for index, (sign, factor) in weights.items():
            target[index] += (
                Vector((direction[0] * sign, direction[1], direction[2])) * factor * amplitude
            )
        values = regional_metrics(rest, target, edges, triangles)
        pairs = sum(values[name]["nonadjacent_intersection_pairs"] for name in region_names)
        bounded = all(
            values[name]["mean_absolute_log_stretch"]
            <= baseline[name]["mean_absolute_log_stretch"] * 1.15
            and values[name]["p95_edge_ratio"] <= baseline[name]["p95_edge_ratio"] * 1.15
            for name in region_names
        )
        trials.append(
            {
                "direction_body": direction,
                "amplitude_meters": amplitude,
                "intersection_pairs": pairs,
                "stretch_guard_passed": bounded,
            }
        )
        if bounded and (best is None or pairs < best[0]):
            best = (pairs, target)
    return best[1], sorted(weights), trials


def sample_geometry(skin):
    bpy.context.view_layer.update()
    evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return (
            [vertex.co.copy() for vertex in mesh.vertices],
            [tuple(edge.vertices) for edge in mesh.edges],
            [
                (tuple(triangle.vertices), triangle.polygon_index)
                for triangle in mesh.loop_triangles
            ],
        )
    finally:
        evaluated.to_mesh_clear()


def regional_metrics(rest, posed, edges, triangles):
    rows = {}
    regions = dict(REGIONS)
    regions.update(
        {
            label.replace(".L", ".R"): ((-center[0], center[1], center[2]), radius)
            for label, (center, radius) in REGIONS.items()
        }
    )
    for label, (center, radius) in regions.items():
        ids = {
            index for index, point in enumerate(rest) if (point - Vector(center)).length < radius
        }
        ratios = sorted(
            (posed[b] - posed[a]).length / (rest[b] - rest[a]).length
            for a, b in edges
            if a in ids and b in ids and (rest[b] - rest[a]).length > 1e-9
        )
        selected = [
            (vertices, face)
            for vertices, face in triangles
            if all(index in ids for index in vertices)
        ]
        if len(selected) > 10000:
            raise ValueError("Regional triangle budget exceeded")
        tree = BVHTree.FromPolygons(
            posed, [vertices for vertices, _ in selected], all_triangles=True
        )
        pairs = sorted({tuple(sorted(pair)) for pair in tree.overlap(tree) if pair[0] != pair[1]})
        if len(pairs) > 100000:
            raise ValueError("Regional pair budget exceeded")
        intersections = []
        for a, b in pairs:
            va, fa = selected[a]
            vb, fb = selected[b]
            if fa == fb or set(va) & set(vb):
                continue
            if triangles_intersect_3d(
                [posed[index] for index in va], [posed[index] for index in vb]
            ):
                intersections.append((fa, fb))
        rows[label] = {
            "vertices": len(ids),
            "triangles": len(selected),
            "coverage": "complete_within_authored_patch",
            "nonadjacent_intersection_pairs": len(intersections),
            "pair_samples": intersections[:10],
            "minimum_edge_ratio": ratios[0],
            "p05_edge_ratio": ratios[int(len(ratios) * 0.05)],
            "p95_edge_ratio": ratios[int(len(ratios) * 0.95)],
            "maximum_edge_ratio": ratios[-1],
            "mean_absolute_log_stretch": sum(abs(math.log(value)) for value in ratios)
            / len(ratios),
        }
    return rows


def evaluate(skin, poses):
    bpy.context.scene.frame_set(1)
    rest, edges, triangles = sample_geometry(skin)
    rows = {}
    for frame, pose in poses.items():
        bpy.context.scene.frame_set(frame)
        posed, posed_edges, posed_triangles = sample_geometry(skin)
        if (
            edges != posed_edges
            or len(rest) != len(posed)
            or len(triangles) != len(posed_triangles)
        ):
            raise AssertionError("Pose changed topology")
        volume = sum(posed[a].dot(posed[b].cross(posed[c])) / 6 for (a, b, c), _ in posed_triangles)
        rows[str(frame)] = {
            "label": pose["label"],
            "signed_volume": volume,
            "changed_triangle_diagonals": sum(
                a != b for a, b in zip(triangles, posed_triangles, strict=True)
            ),
            "regions": regional_metrics(rest, posed, edges, posed_triangles),
        }
    bpy.context.scene.frame_set(1)
    return rows


def render_candidate(name, skin, rig, poses, folder, eyes):
    scene = bpy.context.scene
    skin.hide_render = False
    for eye in eyes:
        eye.hide_render = False
    camera = scene.camera
    renders = []
    for frame, pose in poses.items():
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        center = rig.matrix_world.translation + Vector((0, 0, 0.85))
        for view, offset in (("front", (0, -4, 0.15)), ("side", (4, 0, 0.15))):
            camera.location = center + Vector(offset)
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.ortho_scale = 2.25
            scene.render.resolution_x = scene.render.resolution_y = 384
            path = folder / f"{name}_{pose['label']}_{view}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            assert_subject_visible(path)
            renders.append(path.name)
        if frame in (10, 20, 30, 40, 50):
            bone = {
                10: "DEF-upper_arm.L",
                20: "DEF-upper_arm.L",
                30: "DEF-forearm.L",
                40: "DEF-shin.L",
                50: "DEF-thigh.L",
            }[frame]
            center = rig.matrix_world @ rig.pose.bones[bone].head
            camera.location = center + Vector((3, -4, 0.25))
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.ortho_scale = 0.6 if frame == 50 else 0.52
            scene.render.resolution_x = scene.render.resolution_y = 512
            path = folder / f"{name}_{pose['label']}_closeup.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            assert_subject_visible(path)
            renders.append(path.name)
    skin.hide_render = True
    return renders


def assert_subject_visible(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(values)
        luminance = [sum(values[index : index + 3]) / 3 for index in range(0, len(values), 16)]
        background = sum(values[:3]) / 3
        coverage = sum(value > background + 0.04 for value in luminance) / len(luminance)
        if coverage < 0.02 or max(luminance) - min(luminance) < 0.1:
            raise AssertionError(
                f"Rendered subject is missing or insufficiently visible: {path.name}, coverage={coverage}"
            )
        return coverage
    finally:
        bpy.data.images.remove(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-renders", action="store_true")
    parser.add_argument("--smoothing-iterations", type=int, default=12)
    parser.add_argument("--corrective-iterations", type=int, default=12)
    parser.add_argument(
        "--render-candidates", nargs="+", default=["linear", "pose_corrected_linear"]
    )
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    if not 1 <= args.smoothing_iterations <= 64 or not 1 <= args.corrective_iterations <= 64:
        raise ValueError("Smoothing/corrective iterations must be 1-64")
    source = args.candidate.resolve(strict=True)
    source_digest = sha256(source)
    original_report = json.loads((source.parent / "report.json").read_text())
    folder = args.output or ROOT / "artifacts/human-rig-refinement" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    scene.frame_set(1)
    old_rig = bpy.data.objects[original_report["rig"]]
    old_skin = bpy.data.objects[original_report["skin"]]
    before = source_hash([old_skin])
    captured = secondary_motion.capture_pose({"object_name": old_rig.name, "bones": ["root"]})
    copied = secondary_motion.apply_pose(
        {
            "object_name": old_rig.name,
            "pose": captured["pose"],
            "bone_map": {"root": "root"},
            "bound_mesh_names": [old_skin.name],
            "dry_run": False,
        }
    )
    rig = bpy.data.objects[copied["derivative"]]
    linear = bpy.data.objects[copied["bound_derivatives"][0]]
    rig.hide_viewport = linear.hide_viewport = False
    rig.hide_render = True
    poses = authored_sweep(rig)
    pose_targets = measure_pose_targets(rig, poses)
    if max(row["maximum_direction_error_degrees"] for row in pose_targets.values()) > 0.01:
        raise AssertionError("Anatomical pose target failed")
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = True
    eyes = []
    for original_eye in original_report["eyes"]:
        eye = secondary_motion.attach_rigid(
            {
                # The retained pilot eye derivatives are evaluated and bound.
                # Hidden original library objects can have stale world matrices
                # immediately after cold open, despite intact authored channels.
                "object_name": original_eye["derivative"],
                "armature_name": rig.name,
                "bone": "DEF-spine.006",
                "dry_run": False,
            }
        )
        obj = bpy.data.objects[eye["derivative"]]
        obj.hide_viewport = False
        eyes.append(obj)
    bpy.context.view_layer.update()
    head_center = rig.matrix_world @ rig.pose.bones["DEF-spine.006"].head
    for eye in eyes:
        centroid = sum(
            (eye.matrix_world @ vertex.co for vertex in eye.data.vertices), Vector()
        ) / len(eye.data.vertices)
        if (centroid - head_center).length > 0.25:
            raise AssertionError("Eye attachment is not located near the authored head")
    dq = rigging.hidden_derivative(linear, bpy.context, "PreserveVolume")
    dq.hide_viewport = False
    next(mod for mod in dq.modifiers if mod.type == "ARMATURE").use_deform_preserve_volume = True
    smoothed, smoothing = smooth_patch_weights(linear, rig, args.smoothing_iterations)
    smooth_dq = rigging.hidden_derivative(smoothed, bpy.context, "PreserveVolume")
    smooth_dq.hide_viewport = False
    next(
        mod for mod in smooth_dq.modifiers if mod.type == "ARMATURE"
    ).use_deform_preserve_volume = True
    candidates = {
        "linear": linear,
        "dual_quaternion": dq,
        "smoothed_linear": smoothed,
        "smoothed_dual_quaternion": smooth_dq,
    }
    for name, source_skin in (("corrective_smooth_linear", linear), ("corrective_smooth_dq", dq)):
        copy = rigging.hidden_derivative(source_skin, bpy.context, "CorrectiveSmooth")
        copy.hide_viewport = False
        modifier = copy.modifiers.new("FW_CorrectiveSmooth", "CORRECTIVE_SMOOTH")
        modifier.factor = 0.5
        modifier.iterations = 20
        modifier.smooth_type = "LENGTH_WEIGHTED"
        modifier.rest_source = "ORCO"
        copy.modifiers.move(len(copy.modifiers) - 1, 1)
        candidates[name] = copy
    corrected, correctives = make_pose_correctives(linear, poses, args.corrective_iterations)
    candidates["pose_corrected_linear"] = corrected
    measurements = {name: evaluate(skin, poses) for name, skin in candidates.items()}
    (folder / "measurements.json").write_text(json.dumps(measurements, indent=2) + "\n")
    scene.cycles.device = "CPU"
    scene.cycles.samples = 48
    renders = {}
    if not args.skip_renders:
        for name, skin in candidates.items():
            if name in args.render_candidates:
                renders[name] = render_candidate(name, skin, rig, poses, folder, eyes)
    scene.frame_set(1)
    corrected.hide_render = False
    scene.frame_start, scene.frame_end = 1, 60
    if source_hash([old_skin]) != before or sha256(source) != source_digest:
        raise AssertionError("Input candidate or retained source skin changed")
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "refined-human-rig.blend"))
    report = {
        "schema_version": "1.0",
        "art_accepted": False,
        "status": "measured_candidates_pending_review",
        "source_candidate": str(source),
        "source_sha256": source_digest,
        "source_skin_sha256": before,
        "source_preserved": True,
        "rig": rig.name,
        "skins": {name: skin.name for name, skin in candidates.items()},
        "smoothing": smoothing,
        "correctives": correctives,
        "poses": poses,
        "pose_targets": pose_targets,
        "measurements": measurements,
        "renders": renders,
        "limits": [
            "Authored patch checks exclude shared-vertex triangle pairs and triangles crossing patch boundaries",
            "Regional measurements are comparative evidence, not anatomical or artistic acceptance",
            "Outside-patch weights are protected; smoothed candidates change only new derivative weights inside explicit authored patches",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("FRAMEWRIGHT_HUMAN_REFINEMENT " + str(folder))


if __name__ == "__main__":
    main()
