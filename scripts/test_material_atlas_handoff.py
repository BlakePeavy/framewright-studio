"""Actual multipart cabinet appearance -> shared atlas -> cold native/GLB/FBX.

Writes a fresh review artifact, never a source asset. Quantities are fixture-specific
engineering measurements; rendered comparison is not an artistic quality approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from benchmark_process_performance import process_memory  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from test_material_atlas import source_state  # noqa: E402

from framewright import interchange, material_atlas, production_assets  # noqa: E402

RUNTIME_FILES = ("material_atlas.py", "atlas_plan.py", "interchange.py", "production_assets.py")
SOURCE_LIMITS = {"three_quarter": 0.003, "grain_detail": 0.01}
COLD_LIMITS = {"three_quarter": 0.002, "grain_detail": 0.005}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_review(objects, folder, label, cameras=None):
    result = production_assets.setup_review_scene(
        {
            "name": label + "_Review",
            "object_names": [obj.name for obj in objects],
            "lighting": "neutral",
            "resolution": 384,
            "dry_run": False,
        }
    )
    scene = bpy.data.scenes[result["scene"]]
    scene.cycles.device = "CPU"
    scene.cycles.samples = 48
    scene.cycles.seed = 0
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    scene.render.dither_intensity = 0
    detail_data = bpy.data.cameras.new(label + "_GrainDetailData")
    detail = bpy.data.objects.new(label + "_GrainDetail", detail_data)
    scene.collection.objects.link(detail)
    detail_data.type = "ORTHO"
    detail_data.ortho_scale = 0.52
    detail.location = (0, -2, 0.6538)
    detail.rotation_euler = Vector((0, 1, 0)).to_track_quat("-Z", "Y").to_euler()
    result["cameras"]["grain_detail"] = detail.name
    records = {}
    for view in ("three_quarter", "grain_detail"):
        camera = bpy.data.objects[result["cameras"][view]]
        if cameras:
            camera.matrix_world = Matrix(cameras[view]["matrix"])
            camera.data.type = cameras[view]["type"]
            camera.data.lens = cameras[view]["lens"]
            camera.data.ortho_scale = cameras[view]["ortho_scale"]
        scene.camera = camera
        scene.view_layers[0].update()
        path = folder / (label + "_" + view + ".png")
        scene.render.filepath = str(path)
        bpy.ops.render.render(scene=scene.name, write_still=True)
        values = pixels(path)
        if view == "three_quarter":
            assert float(values.std()) > 0.03, (
                "Review render is blank or lacks measurable subject variation"
            )
        records[view] = {
            "file": path.name,
            "sha256": sha(path),
            "matrix": [list(row) for row in camera.matrix_world],
            "type": camera.data.type,
            "lens": camera.data.lens,
            "ortho_scale": camera.data.ortho_scale,
        }
    return records


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape((image.size[1], image.size[0], 4))[:, :, :3]
    finally:
        bpy.data.images.remove(image)


def comparisons(folder, first, second):
    result = {}
    for view in first:
        a, b = pixels(folder / first[view]["file"]), pixels(folder / second[view]["file"])
        delta = np.abs(a - b)
        result[view] = {
            "rgb_mae": float(delta.mean()),
            "p95_absolute_error": float(np.quantile(delta, 0.95)),
            "maximum_absolute_error": float(delta.max()),
            "pixels_over_2_codes": int(np.count_nonzero(delta.max(axis=2) > 2 / 255)),
        }
    return result


def structure(objects):
    """Static authored matrices remain valid when saved objects start hidden."""

    def world(obj):
        return (
            world(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis
            if obj.parent
            else obj.matrix_basis.copy()
        )

    rows = {}
    for obj in objects:
        matrix = world(obj)
        row = {
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "world": [list(item) for item in matrix],
        }
        if obj.type == "MESH":
            obj.data.calc_loop_triangles()
            points = np.array([tuple(matrix @ vertex.co) for vertex in obj.data.vertices])
            row.update(
                triangles=len(obj.data.loop_triangles),
                bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()],
                material_slots=len(obj.material_slots),
            )
        rows[obj.name] = row
    return rows


def verify_structure(expected, actual):
    assert set(expected) == set(actual), "Cold import changed logical object identities"
    for name, before in expected.items():
        after = actual[name]
        assert before["type"] == after["type"], name
        assert before["parent"] == after["parent"], name
        np.testing.assert_allclose(
            before["world"], after["world"], rtol=0, atol=2e-5, err_msg=name + " world transform"
        )
        if before["type"] == "MESH":
            assert before["triangles"] == after["triangles"], name
            assert before["material_slots"] == after["material_slots"] == 1, name
            np.testing.assert_allclose(
                before["bounds"],
                after["bounds"],
                rtol=0,
                atol=2e-5,
                err_msg=name + " surface bounds",
            )


def verify_comparison(values, limits, label):
    for view, threshold in limits.items():
        row = values[view]
        assert np.isfinite(
            [row["rgb_mae"], row["p95_absolute_error"], row["maximum_absolute_error"]]
        ).all(), label
        assert row["rgb_mae"] <= threshold, (label, view, row, threshold)
        assert row["p95_absolute_error"] <= 0.02, (label, view, row)


def main(args):
    started = time.perf_counter()
    memory_before = process_memory()
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if args.cold:
        folder = args.folder.resolve()
        record = json.loads((folder / "report.json").read_text())
        if args.cold == "native":
            bpy.ops.wm.open_mainfile(filepath=str(folder / "atlas.blend"))
            objects = [bpy.data.objects[name] for name in record["atlas"]["objects"]]
            for row in record["atlas"]["maps"].values():
                image = bpy.data.images[row["image"]]
                assert (
                    image.packed_file
                    and hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
                    == row["packed_sha256"]
                )
        else:
            if args.cold == "GLB":
                bpy.ops.import_scene.gltf(filepath=str(folder / "CabinetGLB.glb"))
            else:
                bpy.ops.import_scene.fbx(filepath=str(folder / "CabinetFBX.fbx"))
            objects = list(bpy.context.scene.objects)
            for obj in objects:
                obj["framewright_owner"] = "material_atlas"
        assert sum(obj.type == "MESH" for obj in objects) == 29
        assert sum(obj.type == "EMPTY" for obj in objects) == 1
        actual_structure = structure(objects)
        expected_structure = record["structure"]
        if args.cold != "native":
            # Scoped export deliberately gives staging copies distinct names;
            # compare against its explicit bijection, never infer/drop prefixes.
            aliases = record["exports"][args.cold]["staged_names"]
            assert set(aliases) == set(expected_structure)
            assert len(set(aliases.values())) == len(aliases)
            expected_structure = {
                aliases[name]: dict(row, parent=aliases[row["parent"]] if row["parent"] else None)
                for name, row in expected_structure.items()
            }
        verify_structure(expected_structure, actual_structure)
        renders = render_review(
            objects, folder, "cold_" + args.cold.lower(), record["source_renders"]
        )
        cold = {
            "renders": renders,
            "atlas_to_cold": comparisons(folder, record["atlas_renders"], renders),
            "source_to_cold": comparisons(folder, record["source_renders"], renders),
            "mesh_count": 29,
            "empty_count": 1,
            "structure": actual_structure,
            "structure_passed": True,
            "appearance_passed": False,
            "memory_before": memory_before,
            "memory_after": process_memory(),
            "elapsed_seconds": time.perf_counter() - started,
        }
        (folder / ("cold_" + args.cold.lower() + ".json")).write_text(json.dumps(cold, indent=2))
        verify_comparison(cold["atlas_to_cold"], COLD_LIMITS, "atlas to cold " + args.cold)
        verify_comparison(
            cold["source_to_cold"],
            {view: SOURCE_LIMITS[view] + COLD_LIMITS[view] for view in SOURCE_LIMITS},
            "source to cold " + args.cold,
        )
        cold["appearance_passed"] = True
        (folder / ("cold_" + args.cold.lower() + ".json")).write_text(json.dumps(cold, indent=2))
        print("COLD", args.cold, json.dumps(cold["atlas_to_cold"]))
        return
    folder = (
        ROOT
        / "artifacts"
        / "material-atlas"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    )
    folder.mkdir(parents=True)
    measurements = []

    def measured_stage(name):
        row = {
            "stage": name,
            "elapsed_seconds": time.perf_counter() - started,
            "memory": process_memory(),
        }
        measurements.append(row)
        (folder / "performance.json").write_text(
            json.dumps(
                {
                    "stages": measurements,
                    "scope": "whole-process Windows lifetime high-water marks; stage timing is cumulative; GPU memory unmeasured",
                },
                indent=2,
            )
        )
        print("ATLAS_STAGE", json.dumps(row), flush=True)

    measured_stage("started")
    runtime_before = {name: sha(ROOT / "framewright" / name) for name in RUNTIME_FILES}
    built = production_assets.build_prop({"name": "AtlasCabinet", "dry_run": False})
    sources = [bpy.data.objects[name] for name in built["objects"]]
    source_before = source_state(sources)
    source_renders = render_review(sources, folder, "source")
    assert source_state(sources) == source_before
    measured_stage("source_rendered")
    atlas = material_atlas.bake_material_atlas(
        {
            "object_names": built["objects"],
            "resolution": args.resolution,
            "max_memory_mb": args.max_memory_mb,
            "margin": 4,
            "dry_run": False,
        }
    )
    assert source_state(sources) == source_before
    measured_stage("atlas_baked_and_packed")
    objects = [bpy.data.objects[name] for name in atlas["objects"]]
    atlas_renders = render_review(objects, folder, "atlas", source_renders)
    assert source_state(sources) == source_before
    measured_stage("atlas_rendered")
    for row in atlas["maps"].values():
        image = bpy.data.images[row["image"]]
        row["packed_sha256"] = hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
    # Corrupt the owned atlas material temporarily: this reproduces the discovered
    # procedural-to-export white-material loss as an explicit negative control.
    mat = bpy.data.materials[atlas["material"]]
    shader = mat.node_tree.nodes.get("Principled BSDF")
    socket = shader.inputs["Base Color"]
    original = socket.links[0].from_socket
    mat.node_tree.links.remove(socket.links[0])
    socket.default_value = (0.8, 0.8, 0.8, 1)
    bad_renders = render_review(objects, folder, "bad_white", source_renders)
    mat.node_tree.links.new(original, socket)
    exports = {}
    for fmt in ("GLB", "FBX"):
        exports[fmt] = interchange.export_asset(
            {
                "object_names": atlas["objects"],
                "directory": str(folder),
                "filename": "Cabinet" + fmt,
                "format": fmt,
                "dry_run": False,
            }
        )
        assert source_state(sources) == source_before
        measured_stage(fmt.lower() + "_exported")
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "atlas.blend"))
    measured_stage("blend_saved")
    record = {
        "status": "cold_checks_pending",
        "atlas": atlas,
        "source_renders": source_renders,
        "atlas_renders": atlas_renders,
        "bad_white_renders": bad_renders,
        "source_to_atlas": comparisons(folder, source_renders, atlas_renders),
        "source_to_bad_white": comparisons(folder, source_renders, bad_renders),
        "source_state_sha256": hashlib.sha256(source_before.encode()).hexdigest(),
        "source_preserved": source_before == source_state(sources),
        "structure": structure(objects),
        "exports": exports,
        "blend_sha256": sha(folder / "atlas.blend"),
        "runtime_sha256": runtime_before,
        "harness_sha256": sha(__file__),
        "thresholds": {
            "source_to_atlas_rgb_mae": SOURCE_LIMITS,
            "atlas_to_cold_rgb_mae": COLD_LIMITS,
            "p95_absolute_error": 0.02,
            "scope": "384px 48-sample neutral cabinet fixture; not general visual or artistic acceptance",
        },
        "acceptance": "measured fixture appearance, no artist/native-game approval",
    }
    (folder / "report.json").write_text(json.dumps(record, indent=2))
    verify_comparison(record["source_to_atlas"], SOURCE_LIMITS, "source to atlas")
    for view, minimum in (("three_quarter", 0.03), ("grain_detail", 0.10)):
        assert record["source_to_bad_white"][view]["rgb_mae"] > max(
            minimum, 10 * record["source_to_atlas"][view]["rgb_mae"]
        ), "White-material loss negative control did not fail strongly"
    record["negative_control_rejected"] = True
    for mode in ("native", "GLB", "FBX"):
        result = subprocess.run(
            [
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
                "--cold",
                mode,
                "--folder",
                str(folder),
            ],
            capture_output=True,
            timeout=600,
        )
        (folder / ("cold_" + mode.lower() + ".log")).write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")[
            -2000:
        ]
        assert sha(folder / "atlas.blend") == record["blend_sha256"]
    assert runtime_before == {name: sha(ROOT / "framewright" / name) for name in RUNTIME_FILES}, (
        "Runtime changed during measured pilot"
    )
    assert source_before == source_state(sources)
    record["status"] = "passed"
    measured_stage("all_cold_checks_passed")
    record["memory_stages"] = measurements
    record["memory_before"] = memory_before
    record["elapsed_seconds"] = time.perf_counter() - started
    record["cold_checks"] = {
        mode: json.loads((folder / ("cold_" + mode + ".json")).read_text())
        for mode in ("native", "glb", "fbx")
    }
    (folder / "report.json").write_text(json.dumps(record, indent=2))
    print("ATLAS_FOLDER", str(folder))
    print("SOURCE_TO_ATLAS", json.dumps(record["source_to_atlas"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold", choices=("native", "GLB", "FBX"))
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--max-memory-mb", type=int, default=1024)
    main(parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []))
