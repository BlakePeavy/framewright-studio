"""Retain an authored cabinet reference and compare fresh EXR PBR recipe derivatives."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
import sys
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import material_assignment, materials, production_assets  # noqa: E402


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        result = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(result)
        return result
    finally:
        bpy.data.images.remove(image)


def fingerprint(objects):
    geometry = [
        {
            "name": obj.name,
            "matrix": [list(row) for row in obj.matrix_world],
            "parent": obj.parent.name if obj.parent else None,
            "vertices": [list(vertex.co) for vertex in obj.data.vertices],
            "polygons": [(list(face.vertices), face.material_index) for face in obj.data.polygons],
            "uv": [[list(loop.uv) for loop in layer.data] for layer in obj.data.uv_layers],
            "materials": [
                slot.material.name if slot.material else None for slot in obj.material_slots
            ],
            "modifiers": [(modifier.name, modifier.type) for modifier in obj.modifiers],
        }
        for obj in objects
    ]
    graphs = []
    for material in sorted(
        {slot.material for obj in objects for slot in obj.material_slots if slot.material},
        key=lambda item: item.name,
    ):
        nodes = []
        for node in material.node_tree.nodes:
            inputs = []
            for socket in node.inputs:
                if hasattr(socket, "default_value"):
                    value = socket.default_value
                    if not isinstance(value, (str, int, float, bool)):
                        try:
                            value = list(value)
                        except TypeError:
                            continue
                    inputs.append((socket.name, value))
            nodes.append(
                (
                    node.name,
                    node.type,
                    node.mute,
                    inputs,
                    node.image.name if node.type == "TEX_IMAGE" and node.image else None,
                )
            )
        graphs.append(
            (
                material.name,
                nodes,
                [
                    (
                        link.from_node.name,
                        link.from_socket.name,
                        link.to_node.name,
                        link.to_socket.name,
                    )
                    for link in material.node_tree.links
                ],
            )
        )
    return hashlib.sha256(
        json.dumps(
            {"geometry": geometry, "graphs": graphs}, sort_keys=True, allow_nan=False
        ).encode()
    ).hexdigest()


def verify_files(receipt):
    for item in receipt["source_files"]:
        if digest(item["path"]) != item["sha256"]:
            raise AssertionError("Reference file bytes changed")


def cold_verify(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    verify_files(report)
    source = [bpy.data.objects[name] for name in report["source_objects"]]
    if fingerprint(source) != report["source_fingerprint"]:
        raise AssertionError("Cold reference geometry/graph differs")
    material = bpy.data.materials[report["recipe"]["material"]]
    shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    for name in ("Base Color", "Roughness", "Metallic", "Normal"):
        if not shader.inputs[name].is_linked:
            raise AssertionError("Cold recipe route missing")
    for item in report["recipe"]["maps"]:
        image = bpy.data.images[item["image"]]
        if (
            tuple(image.size) != (4096, 4096)
            or image.colorspace_settings.name != item["color_space"]
        ):
            raise AssertionError("Cold source map dimensions/encoding changed")
    (path.parent / "cold-verification.json").write_text(
        json.dumps(
            {
                "passed": True,
                "source_fingerprint": report["source_fingerprint"],
                "source_files_preserved": True,
                "three_exr_maps_and_color_retained": True,
                "artist_accepted": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-kit", type=Path)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts" / "cabinet-reference-pilot"
    )
    parser.add_argument("--cold-verify", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.cold_verify:
        cold_verify(args.cold_verify)
        return
    if not bpy.app.background or args.source_kit is None:
        raise RuntimeError("Use an owned background process and explicit source-kit")
    kit = args.source_kit.resolve()
    download = json.loads((kit / "download-receipt.json").read_text(encoding="utf-8-sig"))
    files = download["files"]
    if len(files) != 5 or any(
        not Path(item["path"]).resolve().is_relative_to(kit)
        or digest(item["path"]) != item["sha256"]
        for item in files
    ):
        raise ValueError("Expected five unchanged reference files inside the source kit")
    blend = next(item for item in files if Path(item["path"]).suffix == ".blend")
    bpy.ops.wm.open_mainfile(filepath=blend["path"], load_ui=False, use_scripts=False)
    sources = sorted(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"), key=lambda obj: obj.name
    )
    if len(sources) != 5 or any(
        len(obj.material_slots) != 1 or obj.animation_data or obj.constraints for obj in sources
    ):
        raise ValueError("Reference topology/scope differs from reviewed five-part static cabinet")
    before = fingerprint(sources)
    output = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    output.mkdir(parents=True, exist_ok=False)
    params = {"name": "FW_CabinetReferencePBR", "max_memory_mb": 2048, "dry_run": False}
    for role, token in (
        ("base_color", "_diff_"),
        ("roughness", "_rough_"),
        ("metallic", "_metal_"),
        ("normal", "_nor_gl_"),
    ):
        params[role + "_path"] = next(
            item["path"] for item in files if token in item["relative_path"]
        )
    recipe = materials.create_pbr_material(params)
    original_scene = bpy.context.scene
    source_copies, derivatives = [], []
    for source in sources:
        copy = source.copy()
        copy.data = source.data.copy()
        copy.name = "FW_Reference_" + source.name
        original_scene.collection.objects.link(copy)
        copy["framewright_owner"] = production_assets.OWNER
        copy["framewright_reference_source"] = source.name
        source_copies.append(copy)
        assigned = material_assignment.assign_material(
            {
                "object_name": copy.name,
                "material_name": recipe["material"],
                "slot_indices": [0],
                "dry_run": False,
            }
        )
        derivatives.append(bpy.data.objects[assigned["derivative"]])
    bpy.context.view_layer.update()
    renders, reviews, comparisons = [], {}, {}
    for group, subjects in (("reference", source_copies), ("recipe", derivatives)):
        review = production_assets.setup_review_scene(
            {
                "name": "Cabinet_" + group,
                "object_names": [obj.name for obj in subjects],
                "lighting": "neutral",
                "resolution": 512,
                "dry_run": False,
            }
        )
        reviews[group] = review
        scene = bpy.data.scenes[review["scene"]]
        scene.render.threads_mode, scene.render.threads = "FIXED", 8
        scene.cycles.samples, scene.cycles.seed = 64, 0
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
        for label, camera in review["cameras"].items():
            scene.camera = bpy.data.objects[camera]
            path = output / f"{group}-{label}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True, scene=scene.name)
            renders.append(
                {"file": path.name, "sha256": digest(path), "group": group, "view": label}
            )
    for label in reviews["reference"]["cameras"]:
        a, b = pixels(output / f"reference-{label}.png"), pixels(output / f"recipe-{label}.png")
        difference = [
            abs(x - y) for index, (x, y) in enumerate(zip(a, b, strict=True)) if index % 4 != 3
        ]
        comparisons[label] = {
            "rgb_mae": sum(difference) / len(difference),
            "maximum": max(difference),
        }
    if fingerprint(sources) != before:
        raise AssertionError("Reference source geometry/material graph changed")
    report = {
        "schema_version": "1.0",
        "source": download["source"],
        "credit": download["credit"],
        "license": download["license"],
        "source_files": files,
        "source_objects": [obj.name for obj in sources],
        "source_fingerprint": before,
        "source_preserved": True,
        "recipe": recipe,
        "reviews": reviews,
        "renders": renders,
        "comparisons": comparisons,
        "artist_accepted": False,
        "native_verified": False,
        "limits": [
            "External authored reference, not a Framewright-generated cabinet or final AAA benchmark",
            "Source shader versus fresh recipe comparison; differences are reported, not hidden by a universal tolerance",
            "4096px source maps; fixed512px64sample Cycles CPU/AgX views; no native or original-frequency acceptance",
            "Source-file hashes and in-memory geometry/UV/material graphs checked; arbitrary modifier internals are not a universal snapshot",
        ],
    }
    verify_files(report)
    bpy.context.window.scene = original_scene
    saved = output / "editable-reference-and-recipe.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(saved), check_existing=False)
    report["blend"] = {"file": saved.name, "sha256": digest(saved)}
    receipt = output / "report.json"
    receipt.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        str(saved),
        "--python-exit-code",
        "1",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--cold-verify",
        str(receipt),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    (output / "cold.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Cold cabinet verification failed; inspect cold.log")
    figures = "".join(
        f'<figure><img src="{html.escape(item["file"])}" width="512"><figcaption>{html.escape(item["group"] + " / " + item["view"])}</figcaption></figure>'
        for item in renders
    )
    (output / "index.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src 'self'; style-src 'unsafe-inline'\"><title>Cabinet reference and EXR recipe</title><style>body{background:#1c2026;color:#eee;font-family:system-ui}figure{display:inline-block;margin:8px}</style><h1>Cabinet reference and EXR recipe</h1><p>Powered by Poly Haven — authored CC0 reference by Kirill Sannikov. Technical comparisons; artistic/native acceptance pending.</p>"
        + figures
        + '<p><a href="report.json">Measurements</a> · <a href="cold-verification.json">Cold verification</a></p>',
        encoding="utf-8",
    )
    print("FRAMEWRIGHT_CABINET_REFERENCE_OK " + str(output))


if __name__ == "__main__":
    main()
