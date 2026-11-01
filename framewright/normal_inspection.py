"""Chunked tangent-normal observations with the frozen 0.5 scalar semantics.

NumPy is bundled with the supported Blender runtime. There is one full float32
pixel readback; float64 arithmetic and accepted-pixel copies are chunk bounded.
"""

import numpy as np

CHUNK_PIXELS = 65536


def _chunk_summary(pixels):
    # Python's scalar oracle computes with double precision after float32 image
    # readback. Float32 vector arithmetic would change boundary classifications.
    rgb = pixels[:, :3].astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        normal = rgb * 2 - 1
        squared = normal[:, 0] ** 2 + normal[:, 1] ** 2 + normal[:, 2] ** 2
        valid = (rgb[:, 2] > 0.1) & (squared >= 0.8) & (squared <= 1.2)
    count = int(np.count_nonzero(valid))
    if not count:
        return 0, None, None
    accepted = rgb[valid]
    return count, accepted.min(axis=0), accepted.max(axis=0)


def inspect_normal_image(image):
    values = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(values)
    pixels = values.reshape(-1, 4)
    # Keep these initial values: the legacy algorithm's range observation is
    # clamped against 1/0 even for accepted components just outside that range.
    minimum, maximum = np.ones(3, dtype=np.float64), np.zeros(3, dtype=np.float64)
    valid = 0
    for start in range(0, len(pixels), CHUNK_PIXELS):
        count, low, high = _chunk_summary(pixels[start : start + CHUNK_PIXELS])
        valid += count
        if count:
            minimum = np.minimum(minimum, low)
            maximum = np.maximum(maximum, high)
    if not valid:
        raise RuntimeError("Bake produced no valid tangent normals")
    ranges = (maximum - minimum).tolist()
    return {
        "valid_normal_pixels": valid,
        "valid_normal_fraction": valid / len(pixels),
        "channel_ranges": ranges,
        "detail_present": max(ranges[:2]) > 0.001,
    }
