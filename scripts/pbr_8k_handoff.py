"""Optional real-8K texture handoff pilot; host orchestration plus isolated Blender workers.

Not normal CI: requires an explicitly verified external three-map material pilot.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
ROLES = {"base_color": "Base Color", "roughness": "Roughness", "normal": "Normal"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def code_hashes():
    paths = list((ROOT / "framewright").rglob("*.py")) + [
        Path(__file__).resolve(),
        ROOT / "scripts/test_surface_render_parity.py",
        ROOT / "scripts/benchmark_process_performance.py",
    ]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in sorted(paths)}


def verify_inputs(kit):
    kit = Path(kit).resolve(strict=True)
    receipt_path = kit / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    blend = (kit / receipt["blend"]).resolve(strict=True)
    require(blend.parent == kit and blend.suffix == ".blend", "Blend must be inside explicit kit")
    require(digest(blend) == receipt["blend_sha256"], "Source blend hash changed")
    maps = receipt["recipe"]["maps"]
    require(
        len(maps) == 3 and {row["role"] for row in maps} == set(ROLES),
        "Expected exactly three map roles",
    )
    for row in maps:
        require((row["width"], row["height"]) == (8192, 8192), "Expected exact 8192-square maps")
        require(digest(row["path"]) == row["sha256"], "Source texture hash changed")
    return {
        "kit": str(kit),
        "receipt_sha256": digest(receipt_path),
        "blend": str(blend),
        "blend_sha256": receipt["blend_sha256"],
        "object": receipt["object"],
        "maps": maps,
        "source": receipt.get("source"),
        "license": receipt.get("license"),
        "credit": receipt.get("credit"),
        "proof_scope": "Current source bytes independently hashed; prior receipt claims are not native or artistic proof",
    }


def compare_pixels(source, actual):
    require(
        source.shape == actual.shape == (512, 512, 4), "Render dimensions differ from 512 square"
    )
    import numpy as np

    require(np.isfinite(source).all() and np.isfinite(actual).all(), "Render pixels must be finite")
    delta = np.abs(source[:, :, :3] - actual[:, :, :3])
    inner = delta[102:410, 102:410]
    return {
        "full_rgb_mae": float(delta.mean()),
        "full_rgb_maximum": float(delta.max()),
        "central_rgb_mae": float(inner.mean()),
        "central_roi_pixels": [102, 102, 410, 410],
        "space": "Blender Image.pixels PNG RGB readback; alpha excluded; no comparator color conversion",
    }


def worker(args):
    code_before_imports = code_hashes()
    import bpy
    import numpy as np
    import test_surface_render_parity as stage
    from benchmark_process_performance import process_memory

    from framewright import interchange

    require(bpy.app.background, "Pilot workers require background Blender")
    folder = args.run.resolve(strict=True)
    inputs = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
    require(code_before_imports == inputs["scripts"], "Pilot runtime changed before worker imports")
    stages = []
    started = time.perf_counter()

    def checkpoint(name):
        stages.append(
            {
                "stage": name,
                "elapsed_seconds": time.perf_counter() - started,
                "memory": process_memory(),
            }
        )

    def graph_bindings(obj):
        require(len(obj.material_slots) == 1, "Expected exactly one material slot")
        material = obj.material_slots[0].material
        require(material is not None and material.node_tree is not None, "PBR material missing")
        shaders = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        require(len(shaders) == 1, "Expected exactly one Principled shader")
        shader = shaders[0]
        outputs = [
            node
            for node in material.node_tree.nodes
            if node.type == "OUTPUT_MATERIAL" and node.is_active_output
        ]
        require(
            len(outputs) == 1 and outputs[0].inputs["Surface"].is_linked,
            "Active material output missing",
        )
        require(
            outputs[0].inputs["Surface"].links[0].from_node == shader,
            "Principled shader is not active output",
        )
        rows = []
        for role, socket_name in ROLES.items():
            socket = shader.inputs[socket_name]
            route = []
            for _ in range(5):
                require(socket.is_linked, f"Missing {role} image binding")
                link = socket.links[0]
                node = link.from_node
                route.append({"node_type": node.type, "output": link.from_socket.name})
                if node.type == "TEX_IMAGE":
                    image = node.image
                    require(image is not None, f"Missing {role} image")
                    require(
                        tuple(image.size) == (8192, 8192), f"{role} dimensions are not 8192 square"
                    )
                    expected_space = "sRGB" if role == "base_color" else "Non-Color"
                    require(
                        image.colorspace_settings.name == expected_space,
                        f"Wrong {role} color space",
                    )
                    rows.append(
                        {
                            "role": role,
                            "image": image.name,
                            "dimensions": list(image.size),
                            "color_space": image.colorspace_settings.name,
                            "path": image.filepath,
                            "packed": bool(image.packed_file),
                            "route": route,
                        }
                    )
                    break
                if node.type == "NORMAL_MAP" and role == "normal":
                    require(node.space == "TANGENT", "Normal map is not tangent-space")
                    socket = node.inputs["Color"]
                elif node.type in {"SEPARATE_COLOR", "SEPRGB"} and role == "roughness":
                    socket = node.inputs[0]
                else:
                    raise AssertionError(f"Unsupported {role} binding path: {node.type}")
            else:
                raise AssertionError(f"No image found for {role}")
        return rows, shader

    def source_fingerprint(obj):
        material = obj.material_slots[0].material
        nodes = []
        for node in material.node_tree.nodes:
            sockets = []
            for socket in node.inputs:
                if hasattr(socket, "default_value"):
                    value = socket.default_value
                    if not isinstance(value, (str, int, float, bool)):
                        try:
                            value = list(value)
                        except TypeError:
                            continue
                    sockets.append((socket.name, value))
            image = getattr(node, "image", None)
            nodes.append(
                {
                    "name": node.name,
                    "type": node.type,
                    "inputs": sockets,
                    "image": {
                        "name": image.name,
                        "path": image.filepath,
                        "space": image.colorspace_settings.name,
                        "size": list(image.size),
                    }
                    if image
                    else None,
                }
            )
        record = {
            "object": interchange._source_record([obj]),
            "material": material.name,
            "nodes": nodes,
            "links": [
                (link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name)
                for link in material.node_tree.links
            ],
        }
        return interchange._hash_json(record)

    stage.RESOLUTION = 512
    stage.SAMPLES = 32
    checkpoint("worker_start")
    output = {
        "schema_version": "1.0",
        "worker": args.worker,
        "blender": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(),
        "checkpoints": stages,
    }
    if args.worker in {"source", "export-glb", "export-fbx"}:
        require(
            digest(inputs["blend"]) == inputs["blend_sha256"], "Source blend changed before worker"
        )
        require(
            bpy.ops.wm.open_mainfile(filepath=inputs["blend"], load_ui=False, use_scripts=False)
            == {"FINISHED"},
            "Source open failed",
        )
        obj = bpy.data.objects.get(inputs["object"])
        require(obj is not None and obj.type == "MESH", "Source object missing")
        scenes = [scene for scene in bpy.data.scenes if obj.name in scene.objects]
        require(len(scenes) == 1, "Source object scene is ambiguous")
        bpy.context.window.scene = scenes[0]
        bpy.context.view_layer.update()
        bindings, _ = graph_bindings(obj)
        before = source_fingerprint(obj)
        checkpoint("source_open_and_map_validation")
        output["bindings"] = bindings
        if args.worker == "source":
            stage.render([obj], folder / "source.png")
            checkpoint("source_512_render")
        else:
            format_name = args.worker.split("-")[1].upper()
            exported = interchange.export_asset(
                {
                    "object_names": [obj.name],
                    "directory": str(folder),
                    "filename": "wooden_planks_8k_" + format_name.lower(),
                    "format": format_name,
                    "max_material_memory_mb": 4096,
                    "dry_run": False,
                }
            )
            require(
                exported["source_fingerprint_before"] == exported["source_fingerprint_after"],
                "Exporter source fingerprint changed",
            )
            checkpoint("export_complete")
            output["export"] = exported
            output["export_receipt_sha256"] = digest(exported["receipt_path"])
        output["source_fingerprint_before"] = before
        output["source_fingerprint_after"] = source_fingerprint(obj)
        require(
            output["source_fingerprint_after"] == before, "Source geometry/material graph changed"
        )
    else:
        format_name = args.worker.split("-")[1].upper()
        export_report = json.loads((folder / f"export-{format_name.lower()}.json").read_text())
        exported = export_report["export"]
        require(
            digest(exported["receipt_path"]) == export_report["export_receipt_sha256"],
            "Export receipt changed",
        )
        require(digest(exported["output_path"]) == exported["output_sha256"], "Export file changed")
        stage.clear_factory_scene()
        # Fresh process: no source blend/materials/images are opened in this branch.
        require(
            not [image for image in bpy.data.images if image.type == "IMAGE"],
            "Cold worker already has image data",
        )
        importer = bpy.ops.import_scene.gltf if format_name == "GLB" else bpy.ops.import_scene.fbx
        kwargs = {} if format_name == "GLB" else {"use_anim": False}
        require(
            importer(filepath=exported["output_path"], **kwargs) == {"FINISHED"},
            "Cold import failed",
        )
        objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        require(len(objects) == 1, "Cold mesh scope differs from one source plane")
        obj = objects[0]
        require(
            len(obj.data.vertices) == 4 and len(obj.data.uv_layers) == 1,
            "Cold plane geometry/UV scope changed",
        )
        bpy.context.view_layer.update()
        bindings, shader = graph_bindings(obj)
        checkpoint("cold_import_and_map_validation")
        output["bindings"] = bindings
        output["cold_scope"] = {
            "meshes": len(objects),
            "vertices": len(obj.data.vertices),
            "triangles": sum(len(face.vertices) - 2 for face in obj.data.polygons),
            "uv_layers": len(obj.data.uv_layers),
            "material_slots": len(obj.material_slots),
        }
        pixels = stage.render(objects, folder / f"{format_name.lower()}-cold.png")
        checkpoint("cold_512_render")
        source = np.asarray(stage.png_pixels(folder / "source.png")).reshape(512, 512, 4)
        output["render_comparison"] = compare_pixels(
            source, np.asarray(pixels).reshape(512, 512, 4)
        )
        # Measure first, then reject a deliberately disconnected roughness route.
        socket = shader.inputs["Roughness"]
        link = socket.links[0]
        from_socket = link.from_socket
        tree = shader.id_data
        tree.links.remove(link)
        rejected = False
        try:
            graph_bindings(obj)
        except AssertionError as error:
            rejected = "roughness" in str(error)
        finally:
            tree.links.new(from_socket, socket)
        require(rejected, "Disconnected-roughness negative control was not rejected")
        output["disconnected_roughness_control_rejected"] = True
        require(
            output["render_comparison"]["full_rgb_mae"] < 0.01,
            "8K fixture render difference exceeds this pilot's 0.01 engineering ceiling",
        )
        output["source_blend_loaded_in_cold_worker"] = False
    checkpoint("finished")
    code_after = code_hashes()
    output["code_hashes_before_imports"] = code_before_imports
    output["code_hashes_after"] = code_after
    require(code_after == code_before_imports, "Pilot runtime changed during worker")
    image_name = (
        "source.png"
        if args.worker == "source"
        else (args.worker.split("-")[1] + "-cold.png" if args.worker.startswith("cold-") else None)
    )
    if image_name:
        output["render"] = {"file": image_name, "sha256": digest(folder / image_name)}
    output["visual_acceptance"] = False
    write_json(folder / f"{args.worker}.json", output)
    print("FRAMEWRIGHT_8K_PBR_WORKER_OK " + args.worker)


class PilotUnitTests(unittest.TestCase):
    def test_new_json_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proof.json"
            write_json(path, {"a": 1})
            with self.assertRaises(FileExistsError):
                write_json(path, {"a": 2})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})

    def test_missing_kit_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                verify_inputs(Path(folder) / "missing")

    def test_stale_source_and_duplicate_role_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            kit = Path(folder)
            blend = kit / "source.blend"
            blend.write_bytes(b"fixture")
            receipt = {"blend": blend.name, "blend_sha256": "0" * 64, "recipe": {"maps": []}}
            (kit / "receipt.json").write_text(json.dumps(receipt))
            with self.assertRaisesRegex(AssertionError, "blend hash"):
                verify_inputs(kit)
            receipt["blend_sha256"] = digest(blend)
            receipt["recipe"]["maps"] = [{"role": "normal"}] * 3
            (kit / "receipt.json").write_text(json.dumps(receipt))
            with self.assertRaisesRegex(AssertionError, "exactly three"):
                verify_inputs(kit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender")
    parser.add_argument("--source-kit", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/pbr-8k-handoff")
    parser.add_argument(
        "--worker", choices=("source", "export-glb", "export-fbx", "cold-glb", "cold-fbx")
    )
    parser.add_argument("--run", type=Path)
    parser.add_argument("--self-test", action="store_true")
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(arguments)
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(PilotUnitTests)
        )
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if args.worker:
        worker(args)
        return
    require(args.blender and args.source_kit, "Host requires --blender and --source-kit")
    executable = shutil.which(args.blender)
    require(executable, "Blender executable missing")
    inputs = verify_inputs(args.source_kit)
    folder = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    require(not folder.is_relative_to(Path(inputs["kit"])), "Output must not be inside source kit")
    folder.mkdir(parents=True, exist_ok=False)
    inputs["scripts"] = code_hashes()
    write_json(folder / "inputs.json", inputs)
    runs = []
    try:
        for name in ("source", "export-glb", "cold-glb", "export-fbx", "cold-fbx"):
            with tempfile.TemporaryDirectory(prefix="framewright-8k-user-") as temporary:
                env = os.environ.copy()
                for key, subfolder in (
                    ("BLENDER_USER_CONFIG", "config"),
                    ("BLENDER_USER_SCRIPTS", "scripts"),
                    ("BLENDER_USER_EXTENSIONS", "extensions"),
                    ("BLENDER_USER_DATAFILES", "datafiles"),
                ):
                    path = Path(temporary) / subfolder
                    path.mkdir()
                    env[key] = str(path)
                command = [
                    executable,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--offline-mode",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(Path(__file__).resolve()),
                    "--",
                    "--worker",
                    name,
                    "--run",
                    str(folder),
                ]
                started = time.perf_counter()
                completed = subprocess.run(
                    command, env=env, capture_output=True, text=True, timeout=900, check=False
                )
                elapsed = time.perf_counter() - started
                log = folder / (name + ".log")
                log.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
                runs.append(
                    {
                        "worker": name,
                        "exit_code": completed.returncode,
                        "elapsed_seconds": elapsed,
                        "log": log.name,
                        "log_sha256": digest(log),
                    }
                )
                print(json.dumps(runs[-1]), flush=True)
                require(completed.returncode == 0, f"Worker {name} failed; inspect {log}")
        current = verify_inputs(args.source_kit)
        require(
            all(current[key] == inputs[key] for key in current),
            "Source inputs changed during handoff",
        )
        require(code_hashes() == inputs["scripts"], "Pilot runtime changed during complete run")
        report = {
            "schema_version": "1.0",
            "inputs_sha256": digest(folder / "inputs.json"),
            "runs": runs,
            "source_files_preserved": True,
            "code_hashes_preserved": True,
            "source_texture_resolution": [8192, 8192],
            "render_resolution": [512, 512],
            "render_settings": {
                "engine": "Cycles CPU",
                "samples": 32,
                "denoising": False,
                "adaptive_sampling": False,
                "seed": 0,
                "view": "Standard",
                "look": "None",
                "exposure": 0,
                "gamma": 1,
                "stage": "existing test_surface_render_parity render helper, orthographic camera and fixed sun/world",
            },
            "roundtrips": {
                name: json.loads((folder / f"cold-{name.lower()}.json").read_text())
                for name in ("GLB", "FBX")
            },
            "visual_acceptance": False,
            "native_engine_acceptance": False,
            "limits": [
                "Three actual 8K source maps, 512-pixel renders; not an 8K output render or artist approval",
                "Whole-process Windows memory counters are lifetime peaks; GPU memory and engine residency are unmeasured",
                "0.01 full-image mean absolute RGB difference is this fixture's engineering ceiling, not a universal quality standard",
                "Single flat UV plane/static view does not establish high-frequency detail, mipmaps, compression or arbitrary-material parity",
            ],
        }
        write_json(folder / "report.json", report)
        (folder / "index.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>8K texture handoff pilot</title><style>body{font:16px system-ui;background:#151719;color:#eee;margin:30px}figure{display:inline-block;margin:10px}img{width:512px;max-width:95vw}</style><h1>Actual 8K maps · 512-pixel handoff comparisons</h1><p>Source and independently reopened GLB/FBX. Artist and native-engine acceptance remain open.</p>'
            + "".join(
                f'<figure><img src="{name}.png"><figcaption>{html.escape(label)}</figcaption></figure>'
                for name, label in (
                    ("source", "Source"),
                    ("glb-cold", "GLB cold import"),
                    ("fbx-cold", "FBX cold import"),
                )
            )
            + '<p><a href="report.json">Measured report</a></p></html>',
            encoding="utf-8",
        )
        print("FRAMEWRIGHT_8K_PBR_HANDOFF_OK " + str(folder), flush=True)
    finally:
        write_json(
            folder / "execution.json",
            {"runs": runs, "finished_report": (folder / "report.json").is_file()},
        )


if __name__ == "__main__":
    main()
