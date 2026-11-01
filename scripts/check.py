"""Repeatable local acceptance checks: uv run python scripts/check.py --blender <exe>."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER_SUITES = (
    "blender_smoke.py",
    "test_transactions.py",
    "test_diagnostics.py",
    "test_production_assets.py",
    "test_resource_geometry.py",
    "test_resource_geometry_review.py",
    "test_cabinet_construction.py",
    "test_construction_callbacks.py",
    "test_construction_units.py",
    "test_production_corpus.py",
    "test_rigging_animation.py",
    "test_rig_fit.py",
    "test_rig_binding.py",
    "test_full_human_rigify.py",
    "test_human_pose_targets.py",
    "test_knee_corrective_activation.py",
    "test_pose_correctives.py",
    "test_corrective_review_regressions.py",
    "test_surface_contacts.py",
    "test_skin_contacts.py",
    "test_skin_contact_review.py",
    "test_region_contacts.py",
    "test_region_contacts_review.py",
    "test_region_description.py",
    "test_region_description_review.py",
    "test_materials.py",
    "test_exr_materials.py",
    "test_exr_review.py",
    "test_material_assignment.py",
    "test_material_atlas.py",
    "test_material_atlas_review.py",
    "test_atlas_review_integration.py",
    "test_material_atlas_handoff.py",
    "inspect_material_atlas_maps.py",
    "test_secondary_motion.py",
    "test_cloth_simulation.py",
    "test_cloth_baking.py",
    "test_baking.py",
    "test_normal_inspection.py",
    "test_bake_units.py",
    "test_bake_preservation_review.py",
    "test_bake_dependency_review.py",
    "test_final_unit_review.py",
    "test_curved_bake.py",
    "test_lod.py",
    "test_interchange.py",
    "test_export_materials.py",
    "test_export_materials_review.py",
    "test_scalar_clamp.py",
    "test_animation_handoff.py",
    "test_bbone_baking.py",
    "test_bbone_review.py",
    "test_export_substeps.py",
    "test_export_sampling_review.py",
    "test_shape_baking.py",
    "test_shape_scope_review.py",
    "test_morph_handoff.py",
    "test_feature_api.py",
    "test_ui_tools.py",
    "test_review_regressions.py",
    "test_benchmark_fixtures.py",
    "test_evaluation_blender.py",
    "test_surface_render_parity.py",
    "test_pbr_map_handoff.py",
    "test_color_pipeline.py",
    "test_light_review.py",
    "test_light_review_independent.py",
    "test_interior_render.py",
    "test_final_regressions.py",
)
RESULTS = []
LOG = []


def source_snapshot(root):
    """Pin tested code/config independently of generated caches and artifacts."""
    root = Path(root)
    paths = [
        path
        for directory in ("framewright", "scripts", "tests", "benchmarks", "examples")
        for path in (root / directory).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.suffix in {".py", ".toml", ".json"} or path.name == "LICENSE")
    ]
    paths.extend(root / name for name in ("pyproject.toml", "uv.lock") if (root / name).is_file())
    files = []
    for path in sorted(paths):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append({"path": path.relative_to(root).as_posix(), "sha256": digest})
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def run(*arguments: str, environment=None):
    print("+ " + subprocess.list2cmdline(arguments), flush=True)
    start = time.perf_counter()
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900,
        check=False,
    )
    print(result.stdout, end="", flush=True)
    RESULTS.append(
        {
            "command": list(arguments),
            "exit_code": result.returncode,
            "seconds": round(time.perf_counter() - start, 3),
        }
    )
    LOG.append("+ " + subprocess.list2cmdline(arguments) + "\n" + result.stdout)
    result.check_returncode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", help="Blender 5.2 executable; omit for Python checks only")
    parser.add_argument(
        "--previous-zip",
        type=Path,
        help="Also verify upgrade and rollback against this prior release",
    )
    parser.add_argument(
        "--receipt", type=Path, help="Write actual check outcomes and a sibling log"
    )
    args = parser.parse_args()
    complete = False
    before = source_snapshot(ROOT)
    try:
        check(args, parser)
        if source_snapshot(ROOT) != before:
            raise RuntimeError(
                "Source/config files changed during verification; rerun on stable bytes"
            )
        complete = True
    finally:
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(
                json.dumps(
                    {
                        "recorded_at": datetime.now(UTC).isoformat(),
                        "python": sys.version,
                        "platform": sys.platform,
                        "checks": RESULTS,
                        "complete": complete,
                        "blender_requested": bool(args.blender),
                        "source_snapshot": before,
                        "source_unchanged": source_snapshot(ROOT) == before,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            args.receipt.with_suffix(".log").write_text("\n".join(LOG), encoding="utf-8")


def check(args, parser):
    blender = shutil.which(args.blender) if args.blender else None
    if args.blender and blender is None:
        parser.error("Blender executable was not found")
    environment = os.environ.copy()
    if blender:
        environment["FRAMEWRIGHT_BLENDER"] = blender
    run(sys.executable, "-m", "ruff", "check", ".")
    run(sys.executable, "-m", "ruff", "format", "--check", ".")
    run(
        sys.executable,
        "-m",
        "pytest",
        "--cov",
        "--cov-report=term-missing",
        environment=environment,
    )
    run(sys.executable, "scripts/test_process_performance.py")
    run(sys.executable, "scripts/test_color_pipeline.py", "--self-test")
    run(sys.executable, "scripts/pbr_8k_handoff.py", "--self-test")
    if blender:
        isolated = (
            blender,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
        )
        for script in BLENDER_SUITES:
            run(*isolated, "--python-exit-code", "1", "--python", "scripts/" + script)
        dist = ROOT / "dist"
        dist.mkdir(exist_ok=True)
        run(*isolated, "--command", "extension", "validate", "framewright")
        manifest = tomllib.loads((ROOT / "framewright/blender_manifest.toml").read_text())
        archive = dist / f"{manifest['id']}-{manifest['version']}.zip"
        run(
            *isolated,
            "--command",
            "extension",
            "build",
            "--source-dir",
            "framewright",
            "--output-dir",
            str(dist),
        )
        run(
            *isolated,
            "--command",
            "extension",
            "validate",
            str(archive),
        )
        run(
            sys.executable,
            "scripts/audit_release.py",
            "--zip",
            str(archive),
            "--receipt",
            str(archive.with_suffix(".receipt.json")),
        )
        previous = ["--previous-zip", str(args.previous_zip.resolve())] if args.previous_zip else []
        run(
            sys.executable,
            "scripts/test_release.py",
            "--blender",
            blender,
            "--zip",
            str(archive),
            *previous,
        )
        run(sys.executable, "scripts/test_jobs.py", "--blender", blender)
        run(sys.executable, "scripts/test_worker_blender.py", "--blender", blender)
    else:
        print("Blender integration and packaging not run (pass --blender to include them)")


if __name__ == "__main__":
    main()
