"""Spatial four-map PBR handoff: cold renders and independent missing-map controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
from test_surface_render_parity import (  # noqa: E402
    clear_factory_scene,
    metrics,
    png_pixels,
    render,
    require,
    source_hash,
)

from framewright import interchange, materials  # noqa: E402


def fixture(folder):
    paths = {}
    for role in ("base_color", "roughness", "metallic", "normal"):
        image = bpy.data.images.new("MapFixture_" + role, 64, 64, alpha=True)
        image.colorspace_settings.name = "sRGB" if role == "base_color" else "Non-Color"
        pixels = []
        for y in range(64):
            for x in range(64):
                if role == "base_color":
                    value = (0.55, 0.15, 0.035, 1) if x // 8 % 2 else (0.035, 0.22, 0.55, 1)
                elif role == "roughness":
                    # G/B deliberately disagree: scalar semantics must remain red, not luma.
                    value = (0.08 if y // 8 % 2 else 0.85, 0.19, 0.64, 1)
                elif role == "metallic":
                    value = (0.05 if (x // 16 + y // 16) % 2 else 0.95, 0.75, 0.1, 1)
                else:
                    nx, ny = 0.4 * math.sin(x * math.pi / 8), 0.3 * math.cos(y * math.pi / 8)
                    value = (
                        (nx + 1) / 2,
                        (ny + 1) / 2,
                        (math.sqrt(1 - nx * nx - ny * ny) + 1) / 2,
                        1,
                    )
                pixels.extend(value)
        image.pixels.foreach_set(pixels)
        path = folder / f"source_{role}.png"
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
        paths[role + "_path"] = str(path)
    recipe = materials.create_pbr_material({**paths, "name": "FourMapPBR", "dry_run": False})
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
    sphere = bpy.context.active_object
    sphere.name = "SpatialFourMapSphere"
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True
    sphere.data.materials.append(bpy.data.materials[recipe["material"]])
    bpy.context.view_layer.update()
    return sphere, recipe


def bindings(objects):
    results = []
    for obj in objects:
        for slot in obj.material_slots:
            shader = next(
                node for node in slot.material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
            )
            results.append(
                {
                    name: bool(shader.inputs[name].is_linked)
                    for name in ("Base Color", "Roughness", "Metallic", "Normal")
                }
            )
    return results


def cold_import(path, folder, format_name):
    clear_factory_scene()
    importer = bpy.ops.import_scene.gltf if format_name == "GLB" else bpy.ops.import_scene.fbx
    kwargs = {} if format_name == "GLB" else {"use_anim": False}
    require(importer(filepath=str(path), **kwargs) == {"FINISHED"}, "Cold import failed")
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    require(objects, "Imported mesh is missing")
    bpy.context.view_layer.update()
    linked = bindings(objects)
    (folder / f"{format_name.lower()}-bindings.json").write_text(
        json.dumps(linked, indent=2) + "\n", encoding="utf-8"
    )
    require(
        all(all(row.values()) for row in linked),
        f"Cold {format_name} dropped map bindings: {linked}",
    )
    render(objects, folder / f"{format_name.lower()}-cold.png")


def control(sphere, folder, role):
    # Own the material so the source recipe graph and image data remain unchanged.
    original = sphere.data.materials[0]
    copied = original.copy()
    sphere.data.materials[0] = copied
    try:
        shader = next(node for node in copied.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        socket = shader.inputs[role]
        for link in list(socket.links):
            copied.node_tree.links.remove(link)
        if role == "Roughness":
            socket.default_value = 0.5
        elif role == "Metallic":
            socket.default_value = 0.0
        return render([sphere], folder / (role.lower().replace(" ", "_") + "-removed.png"))
    finally:
        sphere.data.materials[0] = original
        bpy.data.materials.remove(copied)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-import", type=Path)
    parser.add_argument("--format", choices=("GLB", "FBX"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inject-missing", choices=("roughness", "metallic", "normal"))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.cold_import:
        cold_import(args.cold_import, args.output, args.format)
        return
    folder = args.output or ROOT / "artifacts" / "pbr-map-handoff" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    clear_factory_scene()
    sphere, recipe = fixture(folder)
    before = source_hash([sphere])
    file_hashes = {item["path"]: item["sha256"] for item in recipe["maps"]}
    source = render([sphere], folder / "source.png")
    controls = {
        role.lower(): metrics(source, control(sphere, folder, role))
        for role in ("Roughness", "Metallic", "Normal")
    }
    require(
        all(row["mae"] > 0.002 for row in controls.values()),
        f"Missing-map controls are not measurable: {controls}",
    )
    tolerance = min(0.01, min(row["mae"] for row in controls.values()) * 0.35)
    roundtrips = {}
    for format_name in ("GLB", "FBX"):
        exported = interchange.export_asset(
            {
                "object_names": [sphere.name],
                "directory": str(folder),
                "filename": "four_map_" + format_name.lower(),
                "format": format_name,
                "dry_run": False,
            }
        )
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            "--",
            "--cold-import",
            exported["output_path"],
            "--format",
            format_name,
            "--output",
            str(folder),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        (folder / (format_name.lower() + "-cold.log")).write_text(
            completed.stdout + "\n" + completed.stderr, encoding="utf-8"
        )
        require(
            completed.returncode == 0,
            f"Cold {format_name} failed: {completed.stdout[-1000:]}\n{completed.stderr[-2500:]}",
        )
        measured = metrics(source, png_pixels(folder / (format_name.lower() + "-cold.png")))
        if args.inject_missing:
            measured = controls[args.inject_missing]
        require(
            measured["mae"] <= tolerance,
            f"{format_name} spatial PBR parity failed (ceiling {tolerance}): {measured}",
        )
        roundtrips[format_name] = {
            "metrics": measured,
            "receipt": exported["receipt_path"],
            "bindings": json.loads(
                (folder / (format_name.lower() + "-bindings.json")).read_text(encoding="utf-8")
            ),
        }
    require(source_hash([sphere]) == before, "Source geometry/material/image content changed")
    require(
        all(
            hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
            for path, digest in file_hashes.items()
        ),
        "Input texture file changed",
    )
    report = {
        "schema_version": "1.0",
        "blender": bpy.app.version_string,
        "maps": recipe["maps"],
        "source_sha256": before,
        "source_preserved": True,
        "input_files_preserved": True,
        "missing_map_controls": controls,
        "mae_tolerance": tolerance,
        "roundtrips": roundtrips,
        "limits": [
            "64-pixel spatial maps and 128-pixel fixed Cycles CPU renders; no universal artistic tolerance",
            "Roughness/metallic have non-gray G/B data to detect changed red-channel semantics",
            "No native Unreal, texture compression, mipmapping, temporal or 8K render acceptance",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("FRAMEWRIGHT_PBR_MAP_HANDOFF_OK " + str(folder))


if __name__ == "__main__":
    main()
