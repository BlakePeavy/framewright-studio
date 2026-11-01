"""Isolated Blender regression tests for LOD, collision and surface comparison."""

import argparse
import hashlib
import html
import json
import sys
import unittest
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy  # noqa:E402

from framewright import lod  # noqa:E402


def thin_feature_fixture(scene):
    """Two retained cuboids share the source bounds; only source has a thin fin."""

    def mesh_parts(name, boxes):
        vertices, faces = [], []
        quads = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        for lower, upper in boxes:
            x, y, z = lower
            a, b, c = upper
            offset = len(vertices)
            vertices.extend(
                (
                    (x, y, z),
                    (a, y, z),
                    (a, b, z),
                    (x, b, z),
                    (x, y, c),
                    (a, y, c),
                    (a, b, c),
                    (x, b, c),
                )
            )
            faces.extend(tuple(offset + i for i in face) for face in quads)
        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        uv = mesh.uv_layers.new(name="PreservedUV")
        for i, loop in enumerate(uv.data):
            loop.uv = (i % 2, (i // 2) % 2)
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return obj

    body = ((-0.5, -0.5, 0), (0.5, 0.5, 1))
    foot = ((0.5, -0.35, 0), (1.2, 0.35, 0.1))
    fin = ((0.5, -0.025, 0.35), (1.1, 0.025, 0.98))
    return mesh_parts("WithThinFin", [body, foot, fin]), mesh_parts("MissingThinFin", [body, foot])


class SurfaceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new("BidirectionalSurfaceFixture")
        bpy.context.window.scene = self.scene
        self.source, self.candidate = thin_feature_fixture(self.scene)
        self.source.select_set(True)
        bpy.context.view_layer.objects.active = self.source
        self.scene.frame_set(9)
        bpy.context.view_layer.update()

    def tearDown(self):
        bpy.context.window.scene = self.previous
        for obj in list(self.scene.objects):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(self.scene)

    def state(self):
        return {
            "objects": [
                {
                    "name": o.name,
                    "vertices": [tuple(v.co) for v in o.data.vertices],
                    "faces": [tuple(p.vertices) for p in o.data.polygons],
                    "uvs": [tuple(v.uv) for v in o.data.uv_layers[0].data],
                    "matrix": [tuple(row) for row in o.matrix_world],
                    "selected": o.select_get(),
                }
                for o in (self.source, self.candidate)
            ],
            "active": bpy.context.view_layer.objects.active.name,
            "frame": self.scene.frame_current,
            "meshes": set(m.as_pointer() for m in bpy.data.meshes),
        }

    def compare(self, **extra):
        return lod.compare_surface(
            {"source_name": self.source.name, "candidate_name": self.candidate.name, **extra}
        )

    def test_missing_thin_fin_is_detected_despite_zero_forward_error_and_same_bounds(self):
        before = self.state()
        result = self.compare()
        self.assertLess(result["maximum_distance"], 1e-6)  # Existing one-sided result.
        self.assertAlmostEqual(result["source_to_candidate"]["maximum_distance"], 0.6, places=5)
        self.assertAlmostEqual(result["bidirectional"]["maximum_distance"], 0.6, places=5)
        self.assertEqual(
            result["maximum_distance"], result["candidate_to_source"]["maximum_distance"]
        )
        self.assertLess(result["bounds"]["maximum_component_difference"], 1e-6)
        self.assertFalse(result["visual_acceptance"])
        self.assertEqual(self.state(), before)

    def test_distinct_asymmetric_nonuniform_object_transforms_use_actual_world_geometry(self):
        from mathutils import Matrix

        self.source.location = (2.4, -1.1, 0.8)
        self.source.rotation_euler.z = 0.33
        self.source.scale = (2, 0.5, 1.5)
        self.candidate.location = (-3, 0.7, -0.4)
        self.candidate.rotation_euler.y = -0.27
        self.candidate.scale = (0.5, 2, 0.8)
        bpy.context.view_layer.update()
        mapping = self.candidate.matrix_world.inverted() @ self.source.matrix_world
        for vertex in self.candidate.data.vertices:
            vertex.co = mapping @ vertex.co
        self.candidate.data.update()
        bpy.context.view_layer.update()
        before = self.state()
        result = self.compare()
        self.assertLess(result["maximum_distance"], 2e-6)
        self.assertAlmostEqual(result["source_to_candidate"]["maximum_distance"], 1.2, places=5)
        self.assertLess(result["bounds"]["maximum_component_difference"], 2e-6)
        self.assertNotEqual(self.source.matrix_world, Matrix.Identity(4))
        self.assertEqual(self.state(), before)

    def test_each_direction_discloses_its_bounded_vertex_coverage(self):
        result = self.compare(max_samples=3)
        self.assertEqual(result["bidirectional"]["samples"], 6)
        self.assertEqual(result["sample_budget_per_direction"], 3)
        for key, count in (("source_to_candidate", 24), ("candidate_to_source", 16)):
            self.assertEqual(result[key]["samples"], 3)
            self.assertEqual(result[key]["query_vertices"], count)
            self.assertEqual(result[key]["omitted_vertices"], count - 3)
            self.assertEqual(result[key]["coverage"], "sampled_vertices")
        self.assertEqual(result, self.compare(max_samples=3))

    def test_noop_both_directions_are_zero_and_bounds_match(self):
        result = lod.compare_surface(
            {"source_name": self.source.name, "candidate_name": self.source.name}
        )
        self.assertLess(result["candidate_to_source"]["maximum_distance"], 1e-6)
        self.assertLess(result["source_to_candidate"]["maximum_distance"], 1e-6)
        self.assertLess(result["bidirectional"]["maximum_distance"], 1e-6)
        self.assertEqual(result["bidirectional"]["coverage"], "all_vertices_both_meshes")
        self.assertEqual(result["bounds"]["maximum_component_difference"], 0)

    def test_invalid_sample_budget_rejected_before_mutation(self):
        before = self.state()
        for value in (0, True, 100001, 1.5):
            with self.assertRaises(ValueError):
                self.compare(max_samples=value)
        self.assertEqual(self.state(), before)

    def test_changed_world_bounds_and_evaluated_modifier_counts_are_explicit(self):
        self.candidate.location.z = 0.2
        bpy.context.view_layer.update()
        result = self.compare()
        self.assertAlmostEqual(result["bounds"]["maximum_component_difference"], 0.2, places=5)
        modifier = self.source.modifiers.new("EvaluatedArray", "ARRAY")
        modifier.count = 2
        modifier.relative_offset_displace = (2, 0, 0)
        result = lod.compare_surface(
            {"source_name": self.source.name, "candidate_name": self.source.name}
        )
        self.assertEqual(result["source_to_candidate"]["query_vertices"], 48)
        self.assertLess(result["bidirectional"]["maximum_distance"], 1e-5)

    def test_nonfinite_and_collapsed_world_surfaces_fail_without_temporary_mesh_leaks(self):
        before_meshes = set(m.as_pointer() for m in bpy.data.meshes)
        coordinate = self.candidate.data.vertices[0].co.copy()
        self.candidate.data.vertices[0].co.x = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            self.compare()
        self.candidate.data.vertices[0].co = coordinate
        self.candidate.scale = (0, 0, 0)
        bpy.context.view_layer.update()
        with self.assertRaisesRegex(ValueError, "non-degenerate"):
            self.compare()
        self.assertEqual(set(m.as_pointer() for m in bpy.data.meshes), before_meshes)


class LODTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
        self.source = bpy.context.object
        self.source.name = "LOD_Source"
        self.before = [tuple(v.co) for v in self.source.data.vertices]
        self.selection = list(bpy.context.selected_objects)

    def tearDown(self):
        for obj in list(bpy.context.scene.objects):
            if obj is self.source or obj.get("framewright_source") == self.source.name:
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)

    def test_preview_leaves_scene_unchanged(self):
        before = len(bpy.data.objects)
        result = lod.create_lod({"object_name": self.source.name, "ratio": 0.4})
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(bpy.data.objects), before)

    def test_lod_reduces_and_preserves_source_uvs_selection(self):
        self.source.data.uv_layers.new(name="UVMap")
        result = lod.create_lod({"object_name": self.source.name, "ratio": 0.4, "dry_run": False})
        derivative = bpy.data.objects[result["derivative"]]
        self.assertEqual(derivative["framewright_lod_level"], 1)
        self.assertEqual(derivative["framewright_source"], self.source.name)
        self.assertLess(len(derivative.data.polygons), len(self.source.data.polygons))
        self.assertTrue(derivative.hide_render)
        self.assertTrue(derivative.data.uv_layers)
        self.assertEqual(self.before, [tuple(v.co) for v in self.source.data.vertices])
        self.assertEqual(self.selection, list(bpy.context.selected_objects))
        comparison = lod.compare_surface(
            {"source_name": self.source.name, "candidate_name": derivative.name, "max_samples": 50}
        )
        self.assertGreaterEqual(comparison["maximum_distance"], 0)
        self.assertEqual(comparison["samples"], 50)
        self.assertFalse(comparison["visual_acceptance"])

    def test_collision_separate_and_bounded(self):
        result = lod.create_collision({"object_name": self.source.name, "dry_run": False})
        derivative = bpy.data.objects[result["derivative"]]
        self.assertTrue(derivative.name.startswith("UCX_"))
        self.assertEqual(derivative["framewright_role"], "collision")
        self.assertEqual(self.before, [tuple(v.co) for v in self.source.data.vertices])

    def test_skinned_mesh_refused(self):
        self.source.vertex_groups.new(name="Bone")
        with self.assertRaises(ValueError):
            lod.create_lod({"object_name": self.source.name, "dry_run": False})

    def test_noop_comparison_is_zero(self):
        result = lod.compare_surface(
            {"source_name": self.source.name, "candidate_name": self.source.name}
        )
        self.assertAlmostEqual(result["maximum_distance"], 0, places=5)


def _fixture_hash(objects):
    record = [
        {
            "name": obj.name,
            "vertices": [list(v.co) for v in obj.data.vertices],
            "faces": [list(p.vertices) for p in obj.data.polygons],
            "uvs": [list(v.uv) for v in obj.data.uv_layers[0].data],
            "matrix": [list(row) for row in obj.matrix_world],
            "materials": [
                slot.material.name if slot.material else None for slot in obj.material_slots
            ],
        }
        for obj in objects
    ]
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def _image_values(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        values = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(values)
        return values
    finally:
        bpy.data.images.remove(image)


def _image_difference(left, right):
    a, b = _image_values(left), _image_values(right)
    if len(a) != len(b):
        raise AssertionError("Review image size mismatch")
    differences = [
        max(abs(a[i + channel] - b[i + channel]) for channel in range(3))
        for i in range(0, len(a), 4)
    ]
    return {
        "pixels_changed_more_than_one_code_value": sum(v > 1 / 255 + 1e-6 for v in differences),
        "maximum_rgb_channel_difference": max(differences),
        "mean_max_rgb_channel_difference": sum(differences) / len(differences),
        "interpretation": "encoded PNG pixel differences; not an artistic score or universal acceptance threshold",
    }


def render_thin_feature_review(output_root):
    from mathutils import Vector

    if not bpy.app.background:
        raise RuntimeError("Use isolated background Blender for rendered review fixtures")
    folder = output_root.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    previous = bpy.context.window.scene
    source_scene = bpy.data.scenes.new("ThinFeature_RetainedSources")
    source_scene.unit_settings.system = "METRIC"
    source_scene.unit_settings.scale_length = 1
    bpy.context.window.scene = source_scene
    source, candidate = thin_feature_fixture(source_scene)
    bpy.context.view_layer.update()
    before = _fixture_hash([source, candidate])
    comparison = lod.compare_surface({"source_name": source.name, "candidate_name": candidate.name})
    cameras = {"front": (0.3, -6, 1.8), "side": (6, 0, 1.8), "three_quarter": (3.5, -5, 2.6)}
    target = Vector((0.3, 0, 0.5))
    records = []
    for variant, original in (("source", source), ("candidate", candidate)):
        stage = bpy.data.scenes.new("ThinFeature_" + variant)
        bpy.context.window.scene = stage
        stage.render.engine = "CYCLES"
        stage.cycles.device = "CPU"
        stage.cycles.samples = 32
        stage.cycles.seed = 0
        stage.cycles.use_adaptive_sampling = False
        stage.cycles.use_denoising = False
        stage.render.threads_mode, stage.render.threads = "FIXED", 4
        stage.render.resolution_x = stage.render.resolution_y = 384
        stage.render.resolution_percentage = 100
        stage.render.image_settings.file_format = "PNG"
        stage.render.image_settings.color_mode = "RGBA"
        stage.render.dither_intensity = 0
        stage.view_settings.view_transform = "Standard"
        stage.view_settings.look = "None"
        stage.view_settings.exposure, stage.view_settings.gamma = 0, 1
        stage.world = bpy.data.worlds.new("ThinFeatureWorld_" + variant)
        background = next(n for n in stage.world.node_tree.nodes if n.type == "BACKGROUND")
        model = original.copy()
        model.data = original.data.copy()
        stage.collection.objects.link(model)
        clay = bpy.data.materials.new("ThinFeatureClay_" + variant)
        shader = next(n for n in clay.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        shader.inputs["Base Color"].default_value = (0.35, 0.35, 0.35, 1)
        shader.inputs["Roughness"].default_value = 0.7
        silhouette = bpy.data.materials.new("ThinFeatureSilhouette_" + variant)
        silhouette.node_tree.nodes.clear()
        emission = silhouette.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (0, 0, 0, 1)
        output = silhouette.node_tree.nodes.new("ShaderNodeOutputMaterial")
        silhouette.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
        floor_mesh = bpy.data.meshes.new("ThinFeatureFloorMesh_" + variant)
        floor_mesh.from_pydata(
            [(-4, -4, -0.002), (4, -4, -0.002), (4, 4, -0.002), (-4, 4, -0.002)], [], [(0, 1, 2, 3)]
        )
        floor = bpy.data.objects.new("ThinFeatureFloor_" + variant, floor_mesh)
        stage.collection.objects.link(floor)
        floor_material = bpy.data.materials.new("ThinFeatureFloorMat_" + variant)
        floor_shader = next(
            n for n in floor_material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"
        )
        floor_shader.inputs["Base Color"].default_value = (0.65, 0.65, 0.65, 1)
        floor_shader.inputs["Roughness"].default_value = 1
        floor.data.materials.append(floor_material)
        light = bpy.data.objects.new(
            "ThinFeatureSun_" + variant, bpy.data.lights.new("ThinFeatureSunData_" + variant, "SUN")
        )
        stage.collection.objects.link(light)
        light.data.energy, light.data.angle = 2.5, 0.015
        light.rotation_euler = Vector((-0.4, 1, -1.2)).to_track_quat("-Z", "Y").to_euler()
        camera = bpy.data.objects.new(
            "ThinFeatureCamera_" + variant, bpy.data.cameras.new("ThinFeatureCameraData_" + variant)
        )
        stage.collection.objects.link(camera)
        camera.data.type, camera.data.ortho_scale = "ORTHO", 3.0
        stage.camera = camera
        for kind in ("silhouette", "shadow"):
            model.data.materials.clear()
            model.data.materials.append(silhouette if kind == "silhouette" else clay)
            floor.hide_render = light.hide_render = kind == "silhouette"
            background.inputs["Color"].default_value = (
                (1, 1, 1, 1) if kind == "silhouette" else (0.12, 0.12, 0.12, 1)
            )
            background.inputs["Strength"].default_value = 1 if kind == "silhouette" else 0.2
            for view, position in cameras.items():
                camera.location = position
                camera.rotation_euler = (
                    (target - camera.location).to_track_quat("-Z", "Y").to_euler()
                )
                stage.render.filepath = str(folder / f"{variant}_{kind}_{view}.png")
                bpy.ops.render.render(scene=stage.name, write_still=True)
                path = Path(stage.render.filepath)
                records.append(
                    {
                        "variant": variant,
                        "kind": kind,
                        "view": view,
                        "file": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "camera_position": position,
                        "camera_target": list(target),
                    }
                )
                if variant == "source" and kind == "silhouette" and view == "front":
                    stage.render.filepath = str(folder / "source_silhouette_front_repeat.png")
                    bpy.ops.render.render(scene=stage.name, write_still=True)
    bpy.context.window.scene = source_scene
    if _fixture_hash([source, candidate]) != before:
        raise AssertionError(
            "Review changed retained source/candidate geometry, UVs, transforms or materials"
        )
    differences = {
        f"{kind}_{view}": _image_difference(
            folder / f"source_{kind}_{view}.png", folder / f"candidate_{kind}_{view}.png"
        )
        for kind in ("silhouette", "shadow")
        for view in cameras
    }
    control = _image_difference(
        folder / "source_silhouette_front.png", folder / "source_silhouette_front_repeat.png"
    )
    if control["maximum_rgb_channel_difference"] > 1 / 255 + 1e-6:
        raise AssertionError("Repeated no-op silhouette control differs")
    if differences["silhouette_front"]["pixels_changed_more_than_one_code_value"] == 0:
        raise AssertionError("Rendered front view failed to reveal the deliberately missing fin")
    blend = folder / "thin-feature-review.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
    report = {
        "schema_version": "1.0",
        "blender": bpy.app.version_string,
        "blender_build_hash": bpy.app.build_hash.decode(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "lod_sha256": hashlib.sha256(Path(lod.__file__).read_bytes()).hexdigest(),
        "source_fingerprint_before": before,
        "source_fingerprint_after": _fixture_hash([source, candidate]),
        "blend": {"file": blend.name, "sha256": hashlib.sha256(blend.read_bytes()).hexdigest()},
        "fixture": "Retained box/foot plus a 0.05 m thick fin; candidate deliberately omits fin but retains identical AABB",
        "renderer": "Cycles CPU, 32 samples, seed 0, 4 threads, no adaptive sampling or denoising",
        "color": {"view": "Standard", "look": "None", "exposure": 0, "gamma": 1, "dither": 0},
        "resolution": [384, 384],
        "comparison": comparison,
        "images": records,
        "differences": differences,
        "noop_render_control": control,
        "visual_acceptance": False,
        "limits": [
            "Synthetic construction fixture, not an approved asset or automatic LOD acceptance",
            "Pixel changes depend on view, lighting and sampling; no universal threshold",
            "Static stills do not establish moving LOD transitions, temporal shadows or native runtime behavior",
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    rows = "".join(
        f'<section><h2>{html.escape(kind)} · {html.escape(view)}</h2><figure><img src="source_{kind}_{view}.png"><figcaption>Retained source</figcaption></figure><figure><img src="candidate_{kind}_{view}.png"><figcaption>Missing fin candidate</figcaption></figure></section>'
        for kind in ("silhouette", "shadow")
        for view in cameras
    )
    (folder / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Thin-feature LOD evidence</title><style>body{font:16px system-ui;background:#17191b;color:#eee;max-width:1000px;margin:35px auto}figure{display:inline-block;margin:8px}img{width:384px;max-width:100%}section{margin-bottom:30px}</style><h1>Missing thin feature: retained source / candidate</h1><p>Equal bounds and zero candidate→source vertex error conceal the lost fin. Reverse vertex→surface distance detects it. This is a deliberate failed candidate, not accepted art.</p>'
        + rows
        + '<p><a href="report.json">Measurements and settings</a> · <a href="thin-feature-review.blend">Editable fixture</a></p></html>',
        encoding="utf-8",
    )
    bpy.context.window.scene = previous
    print("FRAMEWRIGHT_LOD_REVIEW_OK " + str(folder))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-review", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts/lod-review",
    )
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    )
    if not result.wasSuccessful():
        raise RuntimeError("LOD tests failed")
    if args.render_review:
        render_thin_feature_review(args.output_dir)
