"""Real cold GLB/FBX name identity and geometry/material preservation controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from test_material_atlas import source_state  # noqa: E402

from framewright import interchange  # noqa: E402


def surface(obj):
    obj.data.calc_loop_triangles()
    triangles = []
    for triangle in obj.data.loop_triangles:
        mat = obj.material_slots[triangle.material_index].material
        rgb = mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value[:3]
        corners = []
        for loop_index in triangle.loops:
            loop = obj.data.loops[loop_index]
            position = obj.matrix_world @ obj.data.vertices[loop.vertex_index].co
            uv = obj.data.uv_layers[0].data[loop_index].uv
            corners.append([*position, *uv])
        triangles.append({"corners": sorted(corners), "color": list(rgb)})
    return sorted(triangles, key=lambda row: row["corners"])


def fixture():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    root = bpy.data.objects.new("FW_MaterialAtlas_RefinedAtlasCabinet_AtlasCabinet_Pivot", None)
    bpy.context.scene.collection.objects.link(root)
    root.location = (1.25, -0.5, 0.25)
    names = [
        "FW_MaterialAtlas_RefinedAtlasCabinet_AtlasCabinet_Side-1",
        "FW_MaterialAtlas_RefinedAtlasCabinet_AtlasCabinet_Side1",
        "\u6728\u6750\u4fa7\u677f" * 12 + "_A",
        "\u6728\u6750\u4fa7\u677f" * 12 + "_B",
        "A" * 53,
        "A" * 54,
    ]
    objects = [root]
    materials = []
    for index, color in enumerate(((0.17, 0.27, 0.36, 1), (0.62, 0.13, 0.22, 1))):
        mat = bpy.data.materials.new("NameControlMaterial" + str(index))
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
        materials.append(mat)
    for index, name in enumerate(names):
        mesh = bpy.data.meshes.new("Asymmetric" + str(index))
        mesh.from_pydata(
            [(0, 0, 0), (1.5, 0, 0), (1.5, 0.5, 0), (0, 0.5, 0), (0.25, 0.125, 1)],
            [],
            [(0, 1, 2), (0, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)],
        )
        mesh.update()
        uv = mesh.uv_layers.new(name="NameControlUV")
        uv.active_render = True
        for loop in mesh.loops:
            vertex = mesh.vertices[loop.vertex_index].co
            uv.data[loop.index].uv = (vertex.x / 2 + vertex.z / 16, vertex.y + vertex.z / 8)
        for mat in materials:
            mesh.materials.append(mat)
        for poly in mesh.polygons:
            poly.material_index = poly.index % 2
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = root
        obj.location = (index * 2, 0.25, 0)
        objects.append(obj)
    bpy.context.view_layer.update()
    return objects


def verify(path):
    evidence = json.loads(path.read_text(encoding="utf-8"))
    receipt = evidence["receipt"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if receipt["format"] == "FBX":
        bpy.ops.import_scene.fbx(filepath=receipt["output_path"])
    else:
        bpy.ops.import_scene.gltf(filepath=receipt["output_path"])
    objects = list(bpy.context.scene.objects)
    imported = {obj.get("framewright_source_name"): obj for obj in objects}
    aliases = receipt["staged_names"]
    result = {
        "aliases": aliases,
        "actual": {key: obj.name for key, obj in imported.items()},
        "checks_passed": False,
    }
    result_path = path.with_suffix(".cold.json")
    try:
        assert len(objects) == len(imported) == len(aliases)
        assert set(imported) == set(aliases), "Source properties changed"
        assert {obj.name for obj in objects} == set(aliases.values()), (
            "Cold names differ from exact receipt bijection"
        )
        for row in evidence.get("authored_source", receipt["source"]):
            obj = imported[row["name"]]
            assert obj.name == aliases[row["name"]]
            assert obj.type == row["type"]
            assert (obj.parent.name if obj.parent else None) == (
                aliases[row["parent"]] if row["parent"] else None
            )
            np.testing.assert_allclose(
                np.array(obj.matrix_world), row["matrix_world"], atol=2e-5, rtol=0
            )
            if obj.type == "MESH":
                actual = surface(obj)
                expected = evidence["surfaces"][row["name"]]
                assert len(actual) == len(expected) == 6
                for a, b in zip(actual, expected, strict=True):
                    np.testing.assert_allclose(a["corners"], b["corners"], atol=2e-5, rtol=0)
                    np.testing.assert_allclose(a["color"], b["color"], atol=2e-6, rtol=0)
        result["checks_passed"] = True
    finally:
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def cold_export(path):
    evidence = json.loads(path.read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(path.with_suffix(".blend")))
    objects = [bpy.data.objects[row["name"]] for row in evidence["authored_source"]]
    before = source_state(objects)
    authored_channels = [
        (
            list(obj.location),
            list(obj.rotation_euler),
            list(obj.scale),
            [list(row) for row in obj.matrix_basis],
        )
        for obj in objects
    ]
    cached_world = [list(obj.matrix_world.translation) for obj in objects]
    expected_world = [
        list(np.array(row["matrix_world"])[:3, 3]) for row in evidence["authored_source"]
    ]
    assert cached_world != expected_world, "Fixture did not reproduce cold stale caches"
    receipt = interchange.export_asset(
        {
            "object_names": [obj.name for obj in objects],
            "directory": str(path.parent),
            "filename": "ColdNames",
            "format": evidence["format"],
            "dry_run": False,
        }
    )
    assert before == source_state(objects), "Export changed hidden source caches or data"
    assert authored_channels == [
        (
            list(obj.location),
            list(obj.rotation_euler),
            list(obj.scale),
            [list(row) for row in obj.matrix_basis],
        )
        for obj in objects
    ]
    assert receipt["source_transform_semantics"] == "authored_static_hierarchy"
    authored = {row["name"]: row for row in evidence["authored_source"]}
    for row in receipt["source"]:
        np.testing.assert_allclose(
            row["matrix_world"], authored[row["name"]]["matrix_world"], atol=2e-6, rtol=0
        )
    evidence["receipt"] = receipt
    evidence["source_preserved"] = True
    evidence["cached_world_before"] = cached_world
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    verify(path)


class ExportNameTests(unittest.TestCase):
    def test_existing_global_object_alias_collision_preserves_source_and_cleanup(self):
        objects = fixture()
        occupied = bpy.data.objects.new("FW_Export_" + "A" * 53, None)
        bpy.context.scene.collection.objects.link(occupied)
        all_objects = objects + [occupied]
        before = source_state(all_objects)
        inventory = {obj.as_pointer() for obj in bpy.data.objects}
        with interchange._staging(objects, bpy.context, fbx_names=True) as (_, copies):
            aliases = [copy.name for copy in copies.values()]
            self.assertEqual(len(set(aliases)), len(objects))
            self.assertNotIn(occupied.name, aliases)
            self.assertTrue(all(len(name.encode()) <= 63 for name in aliases))
        self.assertEqual(source_state(all_objects), before)
        self.assertEqual({obj.as_pointer() for obj in bpy.data.objects}, inventory)

    def test_static_transform_scope_excludes_animation_and_armatures(self):
        objects = fixture()
        self.assertIsNotNone(interchange._static_export_matrices(objects))
        objects[0].keyframe_insert("location", frame=1)
        self.assertIsNone(interchange._static_export_matrices(objects))
        objects[0].animation_data_clear()
        rig = bpy.data.objects.new("ScopeRig", bpy.data.armatures.new("ScopeSkeleton"))
        bpy.context.scene.collection.objects.link(rig)
        self.assertIsNone(interchange._static_export_matrices(objects + [rig]))
        with self.assertRaisesRegex(ValueError, "complete parent"):
            interchange._static_export_matrices(objects[1:])

    def test_cold_hidden_static_hierarchy_preserves_authored_transforms_and_caches(self):
        for fmt in ("GLB", "FBX"):
            with self.subTest(format=fmt):
                objects = fixture()
                root = objects[0]
                root.rotation_euler = (0.125, -0.25, 0.375)
                root.scale = (1.25, 0.75, 1.5)
                objects[-2].rotation_euler = (0.125, 0.25, 0.65)
                objects[-2].scale = (0.5, 2, 0.75)
                objects[-1].parent = objects[-2]
                objects[-1].matrix_parent_inverse.translation = (0.125, -0.25, 0.5)
                bpy.context.view_layer.update()
                authored = interchange._source_record(objects)
                surfaces = {obj.name: surface(obj) for obj in objects if obj.type == "MESH"}
                for obj in objects:
                    obj.hide_viewport = obj.hide_render = True
                folder = (
                    ROOT
                    / "artifacts"
                    / (
                        "cold-"
                        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                        + "-"
                        + uuid4().hex[:8]
                    )
                )
                folder.mkdir(parents=True)
                path = folder / "evidence.json"
                path.write_text(
                    json.dumps(
                        {"format": fmt, "authored_source": authored, "surfaces": surfaces}, indent=2
                    )
                    + "\n",
                    encoding="utf-8",
                )
                bpy.ops.wm.save_as_mainfile(filepath=str(path.with_suffix(".blend")))
                child = subprocess.run(
                    [
                        bpy.app.binary_path,
                        "--background",
                        "--factory-startup",
                        "--disable-autoexec",
                        "--threads",
                        "4",
                        "--python-exit-code",
                        "1",
                        "--python",
                        str(Path(__file__).resolve()),
                        "--",
                        "--cold-export",
                        str(path),
                    ],
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                (folder / "cold.log").write_text(child.stdout + child.stderr, encoding="utf-8")
                print("COLD_EXPORT_EVIDENCE", path, flush=True)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)

    def test_alias_utf8_boundaries_and_order_independence(self):
        names = ["A" * 53, "A" * 54, "\u6728" * 18, "\u6728" * 17 + "AB", "\U0001f680" * 40]
        aliases = interchange._fbx_object_aliases(names, set())
        self.assertEqual(aliases, interchange._fbx_object_aliases(list(reversed(names)), set()))
        self.assertEqual(aliases["A" * 53], "FW_Export_" + "A" * 53)
        self.assertEqual(aliases["\u6728" * 17 + "AB"], "FW_Export_" + "\u6728" * 17 + "AB")
        self.assertEqual(len(set(aliases.values())), len(names))
        for alias in aliases.values():
            self.assertLessEqual(len(alias.encode("utf-8")), 63)
            self.assertNotIn("\ufffd", alias)

    def test_alias_digest_and_existing_name_collision_resolution(self):
        names = ["LongCommonPrefix" * 8 + suffix for suffix in ("A", "B", "C")]
        with patch.object(interchange, "_fbx_name_digest", return_value="0" * 16):
            first = interchange._fbx_object_aliases(names, set())
            occupied = set(first.values())
            second = interchange._fbx_object_aliases(names, occupied)
            self.assertTrue(set(second.values()).isdisjoint(occupied))
            self.assertEqual(len(set(second.values())), len(names))
            self.assertEqual(second, interchange._fbx_object_aliases(names[::-1], occupied))
            self.assertTrue(all(len(alias.encode()) <= 63 for alias in second.values()))

    def test_short_alias_existing_object_collision_is_bounded(self):
        name = "A" * 53
        occupied = {"FW_Export_" + name}
        aliases = interchange._fbx_object_aliases([name], occupied)
        self.assertNotIn(aliases[name], occupied)
        self.assertLessEqual(len(aliases[name].encode()), 63)

    def test_actual_long_unicode_boundary_names_cold_roundtrip(self):
        objects = fixture()
        before = interchange._source_record(objects)
        source_names = [obj.name for obj in objects]
        surfaces = {obj.name: surface(obj) for obj in objects if obj.type == "MESH"}
        for fmt in ("GLB", "FBX"):
            with self.subTest(format=fmt):
                folder = (
                    ROOT
                    / "artifacts"
                    / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
                )
                folder.mkdir(parents=True)
                receipt = interchange.export_asset(
                    {
                        "object_names": source_names,
                        "directory": str(folder),
                        "filename": "Names",
                        "format": fmt,
                        "dry_run": False,
                    }
                )
                self.assertEqual(interchange._source_record(objects), before)
                self.assertEqual(
                    receipt["source_fingerprint_before"], receipt["source_fingerprint_after"]
                )
                self.assertEqual(set(receipt["staged_names"]), set(source_names))
                self.assertEqual(len(set(receipt["staged_names"].values())), len(source_names))
                if fmt == "FBX":
                    self.assertTrue(
                        all(len(name.encode()) <= 63 for name in receipt["staged_names"].values())
                    )
                else:
                    self.assertEqual(
                        receipt["staged_names"],
                        {name: "FW_Export_" + name for name in source_names},
                    )
                path = folder / "evidence.json"
                path.write_text(
                    json.dumps(
                        {
                            "receipt": receipt,
                            "surfaces": surfaces,
                            "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                child = subprocess.run(
                    [
                        bpy.app.binary_path,
                        "--background",
                        "--factory-startup",
                        "--disable-autoexec",
                        "--threads",
                        "4",
                        "--python-exit-code",
                        "1",
                        "--python",
                        str(Path(__file__).resolve()),
                        "--",
                        "--verify",
                        str(path),
                    ],
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                (folder / "cold.log").write_text(child.stdout + child.stderr, encoding="utf-8")
                print("EXPORT_NAME_EVIDENCE", path, flush=True)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--cold-export", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    if args.cold_export:
        cold_export(args.cold_export)
    elif args.verify:
        verify(args.verify)
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
