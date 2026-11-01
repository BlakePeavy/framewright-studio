"""Actual authored cabinet: explicit static freeze, EXR recipe and cold GLB/FBX views."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import bpy  # noqa: E402
from build_cabinet_reference_pilot import digest, fingerprint, pixels, verify_files  # noqa: E402

from framewright import interchange, production_assets  # noqa: E402


def bounds(obj):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return [
        [min(point[axis] for point in points) for axis in range(3)],
        [max(point[axis] for point in points) for axis in range(3)],
    ]


def render_views(objects, output, prefix):
    for obj in objects:
        obj["framewright_owner"] = production_assets.OWNER
    review = production_assets.setup_review_scene(
        {
            "name": "CabinetHandoff_" + prefix,
            "object_names": [obj.name for obj in objects],
            "lighting": "neutral",
            "resolution": 512,
            "dry_run": False,
        }
    )
    scene = bpy.data.scenes[review["scene"]]
    scene.render.threads_mode, scene.render.threads = "FIXED", 8
    scene.cycles.device = "CPU"
    scene.cycles.samples, scene.cycles.seed = 64, 0
    scene.cycles.use_denoising = scene.cycles.use_adaptive_sampling = False
    rows = []
    for label, name in review["cameras"].items():
        scene.camera = bpy.data.objects[name]
        path = output / f"{prefix}-{label}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
        rows.append({"view": label, "file": path.name, "sha256": digest(path)})
    return rows


def cold_import(path, format_name, output, expected):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    outcome = (
        bpy.ops.import_scene.gltf(filepath=str(path))
        if format_name == "GLB"
        else bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    )
    if outcome != {"FINISHED"}:
        raise AssertionError("Cabinet cold import failed")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    actual = {obj.get("framewright_source_name"): obj for obj in meshes}
    if len(meshes) != 5 or set(actual) != set(expected):
        raise AssertionError("Cabinet cold import object scope differs")
    bpy.context.view_layer.update()
    errors, bindings = {}, []
    for name, obj in actual.items():
        measured = bounds(obj)
        error = max(
            abs(a - b)
            for first, second in zip(measured, expected[name]["bounds"], strict=True)
            for a, b in zip(first, second, strict=True)
        )
        if error > 1e-5 or len(obj.data.uv_layers) != 1 or len(obj.material_slots) != 1:
            raise AssertionError("Cabinet bound/UV/slot evidence differs")
        errors[name] = error
        material = obj.material_slots[0].material
        shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        linked = {
            field: shader.inputs[field].is_linked
            for field in ("Base Color", "Roughness", "Metallic", "Normal")
        }
        if not all(linked.values()):
            raise AssertionError("Cabinet cold material binding lost")
        images = [
            node.image
            for node in material.node_tree.nodes
            if node.type == "TEX_IMAGE" and node.image
        ]
        if not images or any(tuple(image.size) != (4096, 4096) for image in images):
            raise AssertionError("Cabinet cold texture dimensions changed")
        bindings.append(
            {
                "object": name,
                "linked": linked,
                "images": [
                    {
                        "name": image.name,
                        "dimensions": list(image.size),
                        "color_space": image.colorspace_settings.name,
                    }
                    for image in images
                ],
            }
        )
    renders = render_views(meshes, output, format_name.lower())
    result = {
        "format": format_name,
        "maximum_bounds_error": max(errors.values()),
        "object_scope_preserved": True,
        "uv_and_slot_counts_preserved": True,
        "bindings": bindings,
        "renders": renders,
    }
    (output / (format_name.lower() + "-cold.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-review", type=Path)
    parser.add_argument("--cold-import", type=Path)
    parser.add_argument("--format", choices=("GLB", "FBX"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        raise RuntimeError("Use an owned background process")
    if args.cold_import:
        if args.output is None or args.format is None:
            parser.error("--cold-import requires --output and --format")
        expected = json.loads((args.output / "frozen-geometry.json").read_text(encoding="utf-8"))
        cold_import(args.cold_import, args.format, args.output, expected)
        return
    if args.source_review is None:
        parser.error("--source-review is required for a new handoff")
    source_review = args.source_review.resolve()
    report = json.loads((source_review / "report.json").read_text(encoding="utf-8"))
    blend = source_review / report["blend"]["file"]
    if digest(blend) != report["blend"]["sha256"]:
        raise AssertionError("Source review .blend changed")
    verify_files(report)
    runtime_paths = [
        *sorted((ROOT / "framewright").glob("*.py")),
        Path(__file__).resolve(),
        ROOT / "scripts/build_cabinet_reference_pilot.py",
    ]
    runtime_before = {str(path.relative_to(ROOT)): digest(path) for path in runtime_paths}
    bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False, use_scripts=False)
    source_objects = [bpy.data.objects[name] for name in report["source_objects"]]
    before = fingerprint(source_objects)
    reviewed = report["reviews"]["recipe"]
    review_scene = bpy.data.scenes[reviewed["scene"]]
    sources = [bpy.data.objects[name] for name in reviewed["copies"].values()]
    bpy.context.window.scene = review_scene
    bpy.context.view_layer.update()
    scene = bpy.data.scenes.new("FW_CabinetFrozenExport")
    scene.unit_settings.system = "METRIC"
    frozen, geometry = [], {}
    with bpy.context.temp_override(scene=review_scene, view_layer=review_scene.view_layers[0]):
        graph = bpy.context.evaluated_depsgraph_get()
        for index, source in enumerate(sources):
            mesh = bpy.data.meshes.new_from_object(
                source.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph
            )
            obj = bpy.data.objects.new(f"CabinetPart_{index}", mesh)
            scene.collection.objects.link(obj)
            obj.matrix_world = source.matrix_world.copy()
            obj["reference_review_object"] = source.name
            frozen.append(obj)
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    for obj in frozen:
        obj.data.calc_loop_triangles()
        geometry[obj.name] = {
            "bounds": bounds(obj),
            "vertices": len(obj.data.vertices),
            "triangles": len(obj.data.loop_triangles),
            "uv_layers": len(obj.data.uv_layers),
            "source": obj["reference_review_object"],
        }
    output = args.output or ROOT / "artifacts" / "cabinet-handoff" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "frozen-geometry.json").write_text(
        json.dumps(geometry, indent=2) + "\n", encoding="utf-8"
    )
    source_renders = render_views(frozen, output, "source")
    params = {
        "object_names": [obj.name for obj in frozen],
        "directory": str(output),
        "format": "FBX",
        "filename": "default_rejected",
        "max_material_memory_mb": 2048,
        "dry_run": False,
    }
    try:
        interchange.export_asset(params)
    except ValueError as error:
        if "[0, 1]" not in str(error) and "[0,1]" not in str(error):
            raise
    else:
        raise AssertionError("Default conversion must reject the observed EXR overshoot")
    results = {}
    for format_name in ("GLB", "FBX"):
        receipt = interchange.export_asset(
            dict(
                params,
                format=format_name,
                filename="cabinet_" + format_name.lower(),
                clamp_scalar_textures=format_name == "FBX",
            )
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
            receipt["output_path"],
            "--format",
            format_name,
            "--output",
            str(output),
        ]
        done = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        (output / (format_name.lower() + "-cold.log")).write_text(
            done.stdout + "\n" + done.stderr, encoding="utf-8"
        )
        if done.returncode:
            raise RuntimeError("Cold cabinet handoff failed; inspect format log")
        comparisons = {}
        for row in source_renders:
            a, b = (
                pixels(output / row["file"]),
                pixels(output / (format_name.lower() + "-" + row["view"] + ".png")),
            )
            differences = [
                abs(x - y) for index, (x, y) in enumerate(zip(a, b, strict=True)) if index % 4 != 3
            ]
            comparisons[row["view"]] = {
                "rgb_mae": sum(differences) / len(differences),
                "maximum": max(differences),
            }
        results[format_name] = {
            "export": receipt,
            "cold": json.loads(
                (output / (format_name.lower() + "-cold.json")).read_text(encoding="utf-8")
            ),
            "comparisons": comparisons,
        }
    verify_files(report)
    if fingerprint(source_objects) != before or digest(blend) != report["blend"]["sha256"]:
        raise AssertionError("Original reference/review state changed")
    runtime_after = {str(path.relative_to(ROOT)): digest(path) for path in runtime_paths}
    if runtime_before != runtime_after:
        raise RuntimeError(
            "Runtime changed during pilot; outputs retained but repeat on stable sources"
        )
    result = {
        "schema_version": "1.0",
        "source_review": str(source_review),
        "source_blend_sha256": digest(blend),
        "source_files_preserved": True,
        "source_graph_geometry_preserved": True,
        "runtime_hashes": runtime_before,
        "runtime_unchanged": True,
        "default_out_of_range_rejected": True,
        "source_renders": source_renders,
        "formats": results,
        "limits": [
            "Explicit pilot-only static evaluation freezes Geometry Nodes/weighted normals on owned copies; no general modifier-bake API claimed",
            "Five parts, bounds, UV/slot counts, image sizes and rendered views verified; arbitrary hidden/interior topology not certified",
            "FBX scalar clipping explicitly requested only on staged images; original EXR samples retained",
            "Fixed512pxCPU64sampleAgX comparisons, no artist/native/full4K-frequency acceptance",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    sections = []
    for row in source_renders:
        sections.append("<h2>" + html.escape(row["view"].replace("_", " ")) + "</h2><div>")
        for label in ("source", "glb", "fbx"):
            filename = label + "-" + row["view"] + ".png"
            sections.append(
                '<figure><img src="'
                + filename
                + '" alt="'
                + html.escape(label)
                + '"><figcaption>'
                + html.escape(label.upper())
                + "</figcaption></figure>"
            )
        sections.append("</div>")
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Cabinet handoff review</title>'
        "<style>body{background:#202328;color:#eee;font:16px system-ui;max-width:1600px;"
        "margin:24px auto}div{display:flex}figure{margin:4px;flex:1}img{width:100%}</style>"
        "<h1>Authored cabinet: source / cold GLB / cold FBX</h1>"
        "<p>Powered by Poly Haven. Kirill Sannikov, CC0. Fixed 512px views; "
        "reported comparisons do not grant artistic or native acceptance. "
        '<a href="report.json">Measurement receipt</a>.</p>' + "".join(sections),
        encoding="utf-8",
    )
    print("FRAMEWRIGHT_CABINET_HANDOFF_OK " + str(output))


if __name__ == "__main__":
    main()
