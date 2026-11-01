"""Build a persistent, local-only asset/review kit in an owned background process."""

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
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from framewright import interchange, production_assets  # noqa: E402

REFERENCE_SHA256 = "811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515"
REFERENCE_MEMBER = "human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend"
REFERENCE_PAGE = "https://www.blender.org/download/demo-files/"
REFERENCE_DOWNLOAD = "https://download.blender.org/demo/asset-bundles/human-base-meshes/human-base-meshes-bundle-v1.4.1.zip"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_extract_member(archive, member, destination, expected_sha256):
    normalized = PurePosixPath(member)
    if normalized.is_absolute() or ".." in normalized.parts or "\\" in member:
        raise ValueError("Unsafe archive member")
    if sha256(archive) != expected_sha256:
        raise ValueError("Reference archive hash does not match the pinned version")
    with zipfile.ZipFile(archive) as bundle:
        entry = bundle.getinfo(member)
        if (
            entry.is_dir()
            or entry.file_size > 200 * 1024 * 1024
            or (entry.external_attr >> 16) & 0o170000 == 0o120000
        ):
            raise ValueError("Reference member is not a bounded regular file")
        with bundle.open(entry) as incoming, Path(destination).open("xb") as output:
            shutil.copyfileobj(incoming, output)


class ExtractionTests(unittest.TestCase):
    def test_hash_path_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="framewright-extract-test-") as temporary:
            folder = Path(temporary)
            archive = folder / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("asset/source.blend", b"fixture bytes")
                bundle.writestr("../unsafe.blend", b"unsafe")
            digest = sha256(archive)
            with self.assertRaises(ValueError):
                safe_extract_member(archive, "../unsafe.blend", folder / "unsafe.blend", digest)
            with self.assertRaises(ValueError):
                safe_extract_member(archive, "asset/source.blend", folder / "wrong.blend", "0" * 64)
            safe_extract_member(archive, "asset/source.blend", folder / "safe.blend", digest)
            self.assertEqual((folder / "safe.blend").read_bytes(), b"fixture bytes")
            with self.assertRaises(FileExistsError):
                safe_extract_member(archive, "asset/source.blend", folder / "safe.blend", digest)
            self.assertFalse((folder / "unsafe.blend").exists())


def render(scene, camera_name, destination, samples):
    scene.camera = bpy.data.objects[camera_name]
    scene.cycles.samples = samples
    scene.cycles.device = "CPU"
    scene.render.filepath = str(destination)
    bpy.ops.render.render(scene=scene.name, write_still=True)
    if not destination.is_file():
        raise RuntimeError("Review render was not written")
    return {
        "path": str(destination),
        "sha256": sha256(destination),
        "camera": camera_name,
        "scene": scene.name,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "samples": samples,
        "engine": "CYCLES",
        "device": "CPU",
        "color_transform": scene.view_settings.view_transform,
        "art_accepted": False,
    }


def reference_candidate(run, archive, resolution, samples):
    folder = run / "reference"
    folder.mkdir()
    source = folder / "human_base_meshes_bundle.blend"
    safe_extract_member(archive, REFERENCE_MEMBER, source, REFERENCE_SHA256)
    with bpy.data.libraries.load(str(source), link=False) as (available, requested):
        inventory = {
            "collections": list(available.collections),
            "objects": list(available.objects),
            "texts": list(available.texts),
        }
        if "Body Male - Realistic" not in available.collections:
            raise RuntimeError("Pinned reference collection is missing")
        requested.collections = ["Body Male - Realistic"]
        requested.texts = [name for name in ("README", "License") if name in available.texts]
    collection = requested.collections[0]
    bpy.context.scene.collection.children.link(collection)
    # Appended inspection copies belong to this task; original bundle bytes stay
    # unchanged and the authorship/license remain attached separately.
    collection["framewright_owner"] = "production_assets"
    for obj in collection.all_objects:
        obj["framewright_owner"] = "production_assets"
        obj["reference_origin"] = "Blender Studio and community Human Base Meshes v1.4.1"
    text_evidence = {}
    for text in requested.texts:
        destination = folder / ("embedded-" + text.name.replace(".", "_") + ".txt")
        destination.write_text(text.as_string(), encoding="utf-8")
        text_evidence[text.name] = {"path": str(destination), "text": text.as_string()}
    (folder / "datablock-inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )
    bpy.context.view_layer.update()
    source_objects = [
        {
            "name": obj.name,
            "vertices": len(obj.data.vertices),
            "polygons": len(obj.data.polygons),
            "dimensions_m": list(obj.dimensions),
            "modifiers": [
                {
                    "type": modifier.type,
                    "levels": getattr(modifier, "levels", None),
                    "render_levels": getattr(modifier, "render_levels", None),
                }
                for modifier in obj.modifiers
            ],
        }
        for obj in collection.all_objects
        if obj.type == "MESH"
    ]
    review = production_assets.setup_review_scene(
        {
            "collection_name": collection.name,
            "name": "Reference_Anatomy",
            "resolution": resolution,
            "lighting": "neutral",
            "dry_run": False,
        }
    )
    scene = bpy.data.scenes[review["scene"]]
    clay = bpy.data.materials.new("Reference_Inspection_Clay")
    clay.use_nodes = True
    shader = clay.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.18, 0.18, 0.18, 1)
    shader.inputs["Roughness"].default_value = 0.7
    scene.view_layers[0].material_override = clay
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.05
    for obj in scene.objects:
        if obj.type == "CAMERA":
            obj.data.lens = 70
        elif obj.type == "LIGHT":
            obj.data.energy *= 0.18 if obj.name.endswith("_Fill") else 0.3
    renders = [
        dict(
            render(scene, review["cameras"][view], folder / (view + ".png"), samples),
            view=view,
            lighting="neutral",
        )
        for view in ("front", "side", "back", "three_quarter")
    ]
    return {
        "role": "Independent anatomy/topology reference candidate; not a generated or accepted final character",
        "source_page": REFERENCE_PAGE,
        "download_url": REFERENCE_DOWNLOAD,
        "archive_path": str(archive),
        "archive_sha256": REFERENCE_SHA256,
        "member": REFERENCE_MEMBER,
        "extracted_blend_sha256": sha256(source),
        "selected_collection": collection.name,
        "license": "CC0-1.0 per bundle README and official demo-files listing",
        "license_discrepancy": "An unrelated embedded License text names the Rain Rig and CC-BY 4.0; both source texts are retained for review",
        "text_evidence": text_evidence,
        "objects": source_objects,
        "review": review,
        "renders": renders,
        "artist_accepted": False,
    }


def build(run, args):
    source_scene = bpy.context.scene
    source_scene.name = "Framewright_EditableSources"
    # This process owns its factory scene; keep the kit free of default objects.
    for obj in list(source_scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    source_scene.unit_settings.system = "METRIC"
    source_scene.unit_settings.scale_length = 1
    (run / "exports").mkdir()
    (run / "renders").mkdir()
    record = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "blender_version": bpy.app.version_string,
        "script_sha256": sha256(__file__),
        "assets": [],
        "status": {
            "technical_review_kit_built": False,
            "independent_AAA_benchmark_accepted": False,
            "native_engine_imported": False,
            "artist_accepted": False,
        },
    }
    for label, builder in (
        ("WorkshopCabinet", production_assets.build_prop),
        ("PeriodFacade", production_assets.build_facade),
    ):
        asset = builder({"name": label, "dry_run": False})
        entry = {"label": label, "builder": asset, "renders": [], "exports": []}
        for format_name in ("GLB", "FBX"):
            receipt = interchange.export_asset(
                {
                    "object_names": asset["objects"],
                    "directory": str(run / "exports"),
                    "filename": label + "_" + format_name.lower(),
                    "format": format_name,
                    "profile": "sundown",
                    "dry_run": False,
                }
            )
            entry["exports"].append(receipt)
        for lighting in ("neutral", "day", "dusk"):
            review = production_assets.setup_review_scene(
                {
                    "collection_name": asset["collection"],
                    "name": label + "_" + lighting,
                    "lighting": lighting,
                    "resolution": args.resolution,
                    "dry_run": False,
                }
            )
            scene = bpy.data.scenes[review["scene"]]
            for view in ("front", "three_quarter"):
                entry["renders"].append(
                    dict(
                        render(
                            scene,
                            review["cameras"][view],
                            run / "renders" / (label + "_" + lighting + "_" + view + ".png"),
                            args.samples,
                        ),
                        view=view,
                        lighting=lighting,
                    )
                )
            entry.setdefault("review_scenes", []).append(review)
            entry.setdefault("resource_reports", []).append(
                production_assets.scene_resources({"scene_name": scene.name})
            )
        record["assets"].append(entry)
    record["reference_candidate"] = reference_candidate(
        run, args.reference_zip.resolve(), args.resolution, args.samples
    )
    record["editable_blend"] = str(run / "framewright-review-kit.blend")
    bpy.context.window.scene = source_scene
    outcome = bpy.ops.wm.save_as_mainfile(filepath=record["editable_blend"], check_existing=True)
    if outcome != {"FINISHED"}:
        raise RuntimeError("Full-file review kit save failed")
    record["editable_blend_sha256"] = sha256(record["editable_blend"])
    record["source_scene"] = source_scene.name
    record["status"]["technical_review_kit_built"] = True
    (run / "manifest.json").write_text(
        json.dumps(record, indent=2, allow_nan=False), encoding="utf-8"
    )
    return record


def cold_verify(manifest_path):
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sha256(record["editable_blend"]) == record["editable_blend_sha256"]
    bpy.ops.wm.open_mainfile(filepath=record["editable_blend"], load_ui=False)
    for asset in record["assets"]:
        collection = bpy.data.collections[asset["builder"]["collection"]]
        assert sorted(obj.name for obj in collection.objects) == asset["builder"]["objects"]
        assert all(obj.data.uv_layers for obj in collection.objects if obj.type == "MESH")
    results = []
    for asset in record["assets"]:
        for receipt in asset["exports"]:
            assert sha256(receipt["output_path"]) == receipt["output_sha256"]
            # This disposable verifier owns everything it opened. Import each
            # file into a clean scene to avoid name collisions or inherited data.
            for obj in list(bpy.data.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            if receipt["format"] == "GLB":
                bpy.ops.import_scene.gltf(filepath=receipt["output_path"])
            else:
                bpy.ops.import_scene.fbx(filepath=receipt["output_path"])
            actual = {
                obj.get("framewright_source_name"): obj
                for obj in bpy.context.scene.objects
                if obj.get("framewright_source_name")
            }
            expected = {item["name"] for item in receipt["source"]}
            assert set(actual) == expected, (set(actual), expected)
            assert len(bpy.context.scene.objects) == len(expected)
            bpy.context.view_layer.update()
            for name, samples in receipt["verification_reference"][
                "normalized_mesh_bounds"
            ].items():
                obj = actual[name]
                points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
                bounds = [
                    [min(point[axis] for point in points) for axis in range(3)],
                    [max(point[axis] for point in points) for axis in range(3)],
                ]
                deviation = max(
                    abs(a - b)
                    for actual_vector, expected_vector in zip(bounds, samples[0], strict=True)
                    for a, b in zip(actual_vector, expected_vector, strict=True)
                )
                assert deviation < 0.0002, (name, deviation)
                assert obj.data.uv_layers
            results.append(
                {
                    "asset": asset["label"],
                    "format": receipt["format"],
                    "scope": "Saved editable source, exact object set, UV presence and evaluated world bounds within 0.2 mm",
                    "passed": True,
                }
            )
    destination = manifest_path.parent / "cold-verification.json"
    destination.write_text(
        json.dumps(
            {
                "blender": bpy.app.version_string,
                "results": results,
                "art_accepted": False,
                "material_render_parity": "not_verified",
                "native_import": "not_run",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("FRAMEWRIGHT_REVIEW_KIT_COLD_OK " + str(destination), flush=True)


def html_sheet(run, record):
    def local(path):
        return html.escape(Path(path).relative_to(run).as_posix(), quote=True)

    cards = []
    for asset in record["assets"]:
        pictures = "".join(
            f'<figure><a href="{local(item["path"])}"><img src="{local(item["path"])}" alt="{html.escape(asset["label"])} {item["lighting"]} {item["view"]}"></a><figcaption>{item["lighting"].title()} · {item["view"].replace("_", " ")}</figcaption></figure>'
            for item in asset["renders"]
        )
        links = " · ".join(
            f'<a href="{local(item["output_path"])}">{item["format"]} export</a> / <a href="{local(item["receipt_path"])}">receipt</a>'
            for item in asset["exports"]
        )
        resources = asset["resource_reports"][0]
        cards.append(
            f'<section><h2>{html.escape(asset["label"])}</h2><p>Editable procedural construction fixture. {len(asset["builder"]["objects"])} source parts. Neutral review scene: {resources["evaluated_triangles_objects"]:,} evaluated triangles including floor. {links}</p><div class="grid">{pictures}</div><p class="note">Pending: licensed period-reference comparison, material refinement, calibrated lighting and artist acceptance. Procedural wood is not preserved as an equivalent exported material without baking.</p></section>'
        )
    reference = record["reference_candidate"]
    pictures = "".join(
        f'<figure><a href="{local(item["path"])}"><img src="{local(item["path"])}" alt="Adult anatomy reference {item["view"]}"></a><figcaption>{item["view"].replace("_", " ")}</figcaption></figure>'
        for item in reference["renders"]
    )
    reference_html = f'<section><h2>Independent anatomy/topology reference candidate</h2><p>Blender Studio/community Human Base Meshes v1.4.1, “Body Male – Realistic.” Neutral clay inspection of appended source geometry, with original multiresolution detail retained. This is an educational adult anatomy base, not a finished or generated character.</p><div class="grid">{pictures}</div><p><a href="{REFERENCE_PAGE}">Official source and CC0 listing</a> · <a href="reference/datablock-inventory.json">Actual source datablocks</a></p><p class="note">Archive SHA-256: <code>{REFERENCE_SHA256}</code>. Bundle README and official listing state CC0. A separate embedded License text refers to the Rain Rig and CC-BY; both source texts are retained in the reference folder. Character materials, hair, clothing, rigging, motion and AAA approval remain open.</p></section>'
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Framewright Studio · review kit</title><style>body{{font:16px/1.55 system-ui,sans-serif;margin:0;background:#101519;color:#e6edf0}}main{{max-width:1400px;margin:auto;padding:44px 28px}}h1{{font-size:38px;margin:8px 0}}h2{{font-size:26px}}a{{color:#8fd5db}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;color:#8fd5db}}section{{margin-top:42px;padding-top:20px;border-top:1px solid #344149}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}figure{{margin:0;background:#1c252b;border:1px solid #344149;border-radius:10px;overflow:hidden}}img{{display:block;width:100%;height:auto}}figcaption{{padding:10px 14px;color:#bfd0d8}}.note{{color:#b4c2c8;font-size:14px}}code{{overflow-wrap:anywhere}}.status{{padding:15px 18px;border:1px solid #8a6c36;background:#30291e;border-radius:8px}}@media(max-width:850px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:550px){{.grid{{grid-template-columns:1fr}}main{{padding:25px 15px}}}}</style><main><div class="eyebrow">Framewright Studio / local review</div><h1>Editable sources, measured handoff, visible evidence</h1><p class="status">Technical fixture review is complete for the recorded checks. AAA benchmark selection and artistic acceptance are pending user review. Sundown work-in-progress art is not the quality authority.</p><p><a href="framewright-review-kit.blend">Open editable Blender kit</a> · <a href="manifest.json">Manifest and hashes</a> · <a href="cold-verification.json">Cold reload/export evidence</a></p><p>{record["blender_version"]}; {record["created_utc"]}. Every image is an actual Cycles render with its camera, samples, source and SHA-256 recorded. Lighting variants use matching camera geometry. Preview resolution is deliberately small; output resolution alone is not a quality measure.</p>{"".join(cards)}{reference_html}<section><h2>Review gates</h2><p>Assess construction and silhouette, material separation, reference fidelity, useful editability, and lighting readability. This kit supports a concrete review; it does not certify native engine materials, animation, runtime budgets or studio parity.</p></section></main></html>"""
    (run / "index.html").write_text(document, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/review-kit")
    parser.add_argument(
        "--reference-zip",
        type=Path,
        default=ROOT / "artifacts/reference-candidates/human-base-meshes-v1.4.1.zip",
    )
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--verify-cold", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if not bpy.app.background:
        parser.error(
            "Use a dedicated background Blender process; this script saves an owned full file"
        )
    if args.self_test:
        outcome = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ExtractionTests)
        )
        if not outcome.wasSuccessful():
            raise RuntimeError("Review kit extraction tests failed")
        return
    if args.verify_cold:
        cold_verify(args.verify_cold.resolve())
        return
    if not 64 <= args.resolution <= 1024 or not 1 <= args.samples <= 128:
        parser.error("Use preview resolution 64–1024 and samples 1–128")
    run = args.output_dir.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run.mkdir(parents=True, exist_ok=False)
    record = build(run, args)
    with tempfile.TemporaryDirectory(prefix="framewright-kit-verify-") as temporary:
        environment = os.environ.copy()
        for variable in (
            "BLENDER_USER_CONFIG",
            "BLENDER_USER_SCRIPTS",
            "BLENDER_USER_EXTENSIONS",
            "BLENDER_USER_DATAFILES",
        ):
            directory = Path(temporary) / variable.lower()
            directory.mkdir()
            environment[variable] = str(directory)
        outcome = subprocess.run(
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
                "--verify-cold",
                str(run / "manifest.json"),
            ],
            cwd=temporary,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
        )
        print(outcome.stdout, flush=True)
        print(outcome.stderr, flush=True)
        outcome.check_returncode()
    html_sheet(run, record)
    print("FRAMEWRIGHT_REVIEW_KIT " + str(run / "index.html"), flush=True)


if __name__ == "__main__":
    main()
