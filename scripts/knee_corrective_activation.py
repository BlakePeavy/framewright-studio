"""Pilot-only continuous knee activation using Blender's native simple drivers.

Call only on an owned corrective derivative. This is not a public extension command.
"""

from __future__ import annotations

import math
import threading


def install_knee_activation(shape_key, rig, side, start_degrees=20.0, full_degrees=110.0):
    """Ease a key from zero to one using measured hip/knee/ankle world distances."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Corrective driver authoring must run on the main thread")
    if side not in {"L", "R"}:
        raise ValueError("side must be L or R")
    if (
        any(
            type(value) not in {int, float} or not math.isfinite(value)
            for value in (start_degrees, full_degrees)
        )
        or not 0 <= start_degrees < full_degrees <= 170
    ):
        raise ValueError("Activation angles must be finite and 0 <= start < full <= 170")
    if rig.type != "ARMATURE" or rig.library or rig.data.library or shape_key.id_data.library:
        raise ValueError("Activation requires local armature and shape-key data")
    names = {
        label: f"ORG-{bone}.{side}"
        for label, bone in (("hip", "thigh"), ("knee", "shin"), ("ankle", "foot"))
    }
    if any(name not in rig.pose.bones for name in names.values()):
        raise ValueError("Explicit stock Rigify thigh/shin/foot bones are required")
    if any(rig.data.bones[names[label]].length <= 1e-8 for label in ("hip", "knee")):
        raise ValueError("Knee driver needs nonzero authored bone lengths")
    if shape_key.relative_key == shape_key or shape_key.slider_min > 0 or shape_key.slider_max < 1:
        raise ValueError("Requires a relative corrective key supporting values zero through one")
    path = shape_key.path_from_id("value")
    data = shape_key.id_data.animation_data
    if data:
        if any(curve.data_path == path for curve in data.drivers):
            raise ValueError("The corrective already has a driver")
        if data.action and any(
            curve.data_path == path
            for layer in data.action.layers
            for strip in layer.strips
            for bag in strip.channelbags
            for curve in bag.fcurves
        ):
            raise ValueError("The corrective already has authored animation")
    curve = shape_key.driver_add("value")
    try:
        driver = curve.driver
        driver.type = "SCRIPTED"
        for label, first, second in (
            ("d", "hip", "ankle"),
            ("h", "hip", "knee"),
            ("s", "knee", "ankle"),
        ):
            variable = driver.variables.new()
            variable.name = label
            variable.type = "LOC_DIFF"
            for target, bone in zip(variable.targets, (first, second), strict=True):
                target.id = rig
                target.bone_target = names[bone]
                target.transform_space = "WORLD_SPACE"
        start = math.radians(start_degrees)
        span = math.radians(full_degrees - start_degrees)
        angle = "acos(min(1,max(-1,(d*d-h*h-s*s)/max(2*h*s,1e-12))))"
        fraction = f"min(1,max(0,({angle}-{start:.17g})/{span:.17g}))"
        driver.expression = f"(1-cos(pi*({fraction})))/2"
        if not driver.is_simple_expression:
            raise RuntimeError(
                "Driver did not compile to Blender's native simple-expression subset"
            )
        return {
            "measurement": "world_joint_distances_law_of_cosines",
            "side": side,
            "start_degrees": start_degrees,
            "full_degrees": full_degrees,
            "interpolation": "clamped half-cosine, continuous with zero endpoint slope",
            "expression": driver.expression,
            "native_simple_expression": True,
            "autoexecution_required": False,
            "art_accepted": False,
        }
    except Exception:
        shape_key.driver_remove("value")
        raise
