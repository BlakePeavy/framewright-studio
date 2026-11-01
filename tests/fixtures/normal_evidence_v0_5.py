"""Test-only oracle copied from the verified Framewright 0.5 baking.py.

Archive SHA256: 87a8d969a3cd0c40c3373b1803da466bd3ea031abb3c57682fc46809ca36aed0.
Do not optimize this historical scalar reference alongside the candidate.
"""

from array import array


def _image_evidence(image):
    values = array("f", [0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    minimum, maximum = [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]
    valid = 0
    for index in range(0, len(values), 4):
        r, g, b = values[index : index + 3]
        length_squared = (r * 2 - 1) ** 2 + (g * 2 - 1) ** 2 + (b * 2 - 1) ** 2
        if b > 0.1 and 0.8 <= length_squared <= 1.2:
            valid += 1
            for channel, value in enumerate((r, g, b)):
                minimum[channel] = min(minimum[channel], value)
                maximum[channel] = max(maximum[channel], value)
    if not valid:
        raise RuntimeError("Bake produced no valid tangent normals")
    ranges = [high - low for low, high in zip(minimum, maximum, strict=True)]
    return {
        "valid_normal_pixels": valid,
        "valid_normal_fraction": valid / (len(values) / 4),
        "channel_ranges": ranges,
        "detail_present": max(ranges[:2]) > 0.001,
    }
