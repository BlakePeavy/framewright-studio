"""Render a full 8192 image from an owned review scene; verify actual PNG dimensions."""

import hashlib
import json
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import bpy

if not bpy.app.background or not bpy.data.filepath:
    raise RuntimeError("Open an owned review-kit file in isolated background Blender")
source = Path(bpy.data.filepath)
before = hashlib.sha256(source.read_bytes()).hexdigest()
scene = bpy.data.scenes.get("WorkshopCabinet_neutral")
if scene is None:
    raise RuntimeError("Expected the generated review-kit cabinet scene")
root = Path(__file__).resolve().parents[1] / "artifacts" / "resolution-probe"
output = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
output.mkdir(parents=True)
scene.camera = bpy.data.objects["WorkshopCabinet_neutral_three_quarter"]
scene.render.resolution_x = scene.render.resolution_y = 8192
scene.render.resolution_percentage = 100
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.threads_mode = "FIXED"
scene.render.threads = 8
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.render.image_settings.compression = 15
scene.render.filepath = str(output / "cabinet-8192.png")
start = time.perf_counter()
bpy.ops.render.render(write_still=True, scene=scene.name)
render_seconds = time.perf_counter() - start
image_path = Path(scene.render.filepath)
with image_path.open("rb") as image:
    header = image.read(24)
if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (8192, 8192):
    raise AssertionError("Actual saved render is not an 8192 x 8192 PNG")
if hashlib.sha256(source.read_bytes()).hexdigest() != before:
    raise AssertionError("Source review file changed")
receipt = {
    "blender": bpy.app.version_string,
    "source": str(source),
    "source_sha256": before,
    "image": str(image_path),
    "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
    "dimensions": [8192, 8192],
    "pixels": 8192**2,
    "bytes": image_path.stat().st_size,
    "seconds": round(render_seconds, 3),
    "engine": "CYCLES",
    "device": "CPU",
    "threads": 8,
    "samples": 16,
    "denoising": True,
    "view_transform": scene.view_settings.view_transform,
    "source_file_preserved": True,
    "artist_approval": "not_evaluated",
    "scope": "Actual full-frame resolution/output-path probe, not 8K source texture or AAA quality acceptance",
}
(output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print("FRAMEWRIGHT_8K_RENDER_OK " + json.dumps(receipt))
