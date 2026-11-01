"""Behavioral contracts for the host-independent quality checks."""

import json
import math
import unittest
from dataclasses import FrozenInstanceError, replace

from framewright.core import (
    PROFILES,
    Finding,
    ObjectSnapshot,
    QualityProfile,
    SceneSnapshot,
    TextureSnapshot,
    ValidationReport,
    validate_scene,
)


def mesh(**changes):
    source = ObjectSnapshot(
        name="Prop",
        type="MESH",
        vertex_count=8,
        edge_count=12,
        polygon_count=6,
        triangle_count=12,
        uv_layer_count=1,
        material_slot_count=1,
    )
    return replace(source, **changes)


def scene(*objects, **changes):
    return SceneSnapshot(name="Test", objects=objects, **changes)


def rules(snapshot, profile=None):
    return {
        finding.rule_id
        for finding in validate_scene(snapshot, profile or QualityProfile()).findings
    }


class CoreContractTests(unittest.TestCase):
    def test_clean_static_prop_passes_without_findings(self):
        report = validate_scene(scene(mesh()), PROFILES["studio_static"])
        self.assertTrue(report.passed)
        self.assertEqual(report.findings, ())

    def test_snapshots_and_profiles_are_immutable(self):
        for value, attribute in [(mesh(), "name"), (scene(), "name"), (QualityProfile(), "id")]:
            with self.subTest(value=value), self.assertRaises(FrozenInstanceError):
                setattr(value, attribute, "changed")

    def test_all_profiles_are_available_and_match_keys(self):
        self.assertEqual(
            set(PROFILES),
            {
                "studio_static",
                "sundown_static",
                "animation_scene",
                "lookdev_scene",
                "cinematic_8k",
                "realtime_high",
            },
        )
        for key, profile in PROFILES.items():
            self.assertEqual(key, profile.id)

    def test_profile_rejects_invalid_budgets(self):
        for values in [dict(max_triangles=0), dict(max_triangles=-1), dict(max_bone_influences=0)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                QualityProfile(**values)

    def test_empty_scene_is_reported(self):
        self.assertIn("EMPTY_SCENE", rules(scene()))

    def test_empty_mesh_blocks_structural_pass(self):
        report = validate_scene(scene(ObjectSnapshot(name="Empty", type="MESH")), QualityProfile())
        self.assertFalse(report.passed)
        self.assertIn("EMPTY_MESH", {f.rule_id for f in report.findings})

    def test_missing_uvs_and_materials_are_actionable(self):
        report = validate_scene(
            scene(mesh(uv_layer_count=0, material_slot_count=0)), QualityProfile()
        )
        findings = {f.rule_id: f for f in report.findings}
        self.assertIn("MISSING_UVS", findings)
        self.assertIn("MISSING_MATERIALS", findings)
        self.assertTrue(all(f.remediation for f in report.findings))
        self.assertTrue(all(f.object_name == "Prop" for f in report.findings))

    def test_profile_can_allow_untextured_meshes(self):
        profile = QualityProfile(require_uvs=False, require_materials=False)
        self.assertNotIn("MISSING_UVS", rules(scene(mesh(uv_layer_count=0)), profile))
        self.assertNotIn("MISSING_MATERIALS", rules(scene(mesh(material_slot_count=0)), profile))

    def test_unassigned_material_slots_are_separate_from_no_slots(self):
        found = rules(scene(mesh(material_slot_count=2, missing_material_slots=1)))
        self.assertIn("EMPTY_MATERIAL_SLOTS", found)
        self.assertNotIn("MISSING_MATERIALS", found)

    def test_open_geometry_is_a_warning_not_automatic_failure(self):
        report = validate_scene(scene(mesh(nonmanifold_edges=4)), QualityProfile())
        finding = next(f for f in report.findings if f.rule_id == "NONMANIFOLD_EDGES")
        self.assertEqual(finding.severity, "WARNING")
        self.assertTrue(report.passed)

    def test_loose_vertices_advertise_only_supported_fix(self):
        report = validate_scene(scene(mesh(loose_vertices=1)), QualityProfile())
        finding = next(f for f in report.findings if f.rule_id == "LOOSE_VERTICES")
        self.assertEqual(finding.fix_id, "mesh.remove_loose_vertices")
        self.assertEqual(finding.severity, "WARNING")

    def test_degenerate_faces_block_structural_pass(self):
        report = validate_scene(scene(mesh(degenerate_faces=1)), QualityProfile())
        self.assertFalse(report.passed)
        self.assertIn("DEGENERATE_FACES", {f.rule_id for f in report.findings})

    def test_triangle_budget_accepts_boundary_and_reports_excess(self):
        profile = QualityProfile(max_triangles=12)
        self.assertNotIn("TRIANGLE_BUDGET", rules(scene(mesh()), profile))
        self.assertIn("TRIANGLE_BUDGET", rules(scene(mesh(triangle_count=13)), profile))

    def test_triangle_budget_is_per_mesh_not_scene_sum(self):
        profile = QualityProfile(max_triangles=12)
        self.assertNotIn("TRIANGLE_BUDGET", rules(scene(mesh(), mesh(name="Other")), profile))

    def test_unapplied_and_reflected_scale_are_distinct(self):
        self.assertIn("UNAPPLIED_SCALE", rules(scene(mesh(scale=(2, 1, 1)))))
        self.assertIn("NEGATIVE_SCALE", rules(scene(mesh(scale=(-1, 1, 1)))))
        self.assertNotIn("NEGATIVE_SCALE", rules(scene(mesh(scale=(2, 1, 1)))))

    def test_scale_uses_float_tolerance(self):
        self.assertNotIn("UNAPPLIED_SCALE", rules(scene(mesh(scale=(1.0000001, 1, 1)))))

    def test_singular_and_nonfinite_scale_are_errors(self):
        for scale in [(0, 1, 1), (math.nan, 1, 1), (math.inf, 1, 1)]:
            with self.subTest(scale=scale):
                report = validate_scene(scene(mesh(scale=scale)), QualityProfile())
                self.assertIn("INVALID_SCALE", {f.rule_id for f in report.findings})
                self.assertFalse(report.passed)

    def test_nonmetric_or_scaled_units_need_review(self):
        for changes in [
            dict(unit_system="NONE"),
            dict(unit_system="IMPERIAL"),
            dict(unit_scale=0.01),
        ]:
            with self.subTest(changes=changes):
                self.assertIn("INVALID_UNITS", rules(scene(mesh(), **changes)))

    def test_invalid_fps_and_frame_range_are_errors(self):
        for changes, rule in [
            (dict(fps=0), "FRAME_RATE"),
            (dict(fps=math.nan), "FRAME_RATE"),
            (dict(frame_start=20, frame_end=10), "FRAME_RANGE"),
        ]:
            with self.subTest(changes=changes):
                report = validate_scene(scene(mesh(), **changes), QualityProfile())
                self.assertIn(rule, {f.rule_id for f in report.findings})
                self.assertFalse(report.passed)

    def test_equal_scene_frame_endpoints_are_valid(self):
        self.assertNotIn("FRAME_RANGE", rules(scene(mesh(), frame_start=1, frame_end=1)))

    def test_lookdev_requires_camera_and_lighting_but_static_does_not(self):
        snapshot = scene(mesh())
        self.assertNotIn("MISSING_CAMERA", rules(snapshot))
        self.assertNotIn("MISSING_LIGHTING", rules(snapshot))
        self.assertTrue(
            {"MISSING_CAMERA", "MISSING_LIGHTING"} <= rules(snapshot, PROFILES["lookdev_scene"])
        )

    def test_world_or_light_satisfies_basic_lighting_presence(self):
        profile = PROFILES["lookdev_scene"]
        for changes in [dict(light_count=1), dict(world_present=True)]:
            with self.subTest(changes=changes):
                found = rules(scene(mesh(), camera_name="Camera", **changes), profile)
                self.assertNotIn("MISSING_CAMERA", found)
                self.assertNotIn("MISSING_LIGHTING", found)

    def test_missing_image_names_are_deduplicated(self):
        report = validate_scene(scene(mesh(), missing_images=("A", "B", "A")), QualityProfile())
        missing = [f for f in report.findings if f.rule_id == "MISSING_TEXTURES"]
        self.assertEqual(len(missing), 2)
        self.assertFalse(report.passed)

    def test_empty_armature_is_an_error(self):
        report = validate_scene(
            scene(ObjectSnapshot(name="Rig", type="ARMATURE")), QualityProfile()
        )
        self.assertIn("EMPTY_ARMATURE", {f.rule_id for f in report.findings})
        self.assertFalse(report.passed)

    def test_multiple_roots_are_reviewable_not_always_invalid(self):
        rig = ObjectSnapshot(name="Rig", type="ARMATURE", bone_count=4, root_bone_count=2)
        report = validate_scene(scene(rig), QualityProfile())
        finding = next(f for f in report.findings if f.rule_id == "MULTIPLE_ROOT_BONES")
        self.assertEqual(finding.severity, "WARNING")

    def test_armature_target_must_exist_and_be_an_armature(self):
        for target in [(), (mesh(name="Rig"),)]:
            with self.subTest(target=target):
                self.assertIn(
                    "MISSING_ARMATURE", rules(scene(mesh(armature_target="Rig"), *target))
                )

    def test_valid_shared_armature_is_resolved_by_name(self):
        rig = ObjectSnapshot(name="Rig", type="ARMATURE", bone_count=3, root_bone_count=1)
        snapshot = scene(mesh(armature_target="Rig"), mesh(name="Body", armature_target="Rig"), rig)
        self.assertNotIn("MISSING_ARMATURE", rules(snapshot))

    def test_skinned_vertices_require_weights_and_bounded_influences(self):
        rig = ObjectSnapshot(name="Rig", type="ARMATURE", bone_count=6, root_bone_count=1)
        skinned = mesh(armature_target="Rig", unweighted_vertices=1, max_vertex_influences=5)
        self.assertTrue({"UNWEIGHTED_VERTICES", "BONE_INFLUENCES"} <= rules(scene(skinned, rig)))
        self.assertNotIn(
            "BONE_INFLUENCES", rules(scene(replace(skinned, max_vertex_influences=4), rig))
        )

    def test_static_mesh_does_not_require_weights(self):
        self.assertNotIn("UNWEIGHTED_VERTICES", rules(scene(mesh(unweighted_vertices=8))))

    def test_animation_range_outside_scene_requires_review(self):
        animated = mesh(has_animation=True, animation_range=(0, 251))
        self.assertIn("ANIMATION_RANGE", rules(scene(animated)))
        self.assertNotIn(
            "ANIMATION_RANGE", rules(scene(replace(animated, animation_range=(1, 250))))
        )

    def test_reversed_and_nonfinite_animation_ranges_are_errors(self):
        for bounds in [(2, 1), (math.nan, 1)]:
            with self.subTest(bounds=bounds):
                report = validate_scene(
                    scene(mesh(has_animation=True, animation_range=bounds)), QualityProfile()
                )
                self.assertFalse(report.passed)
                self.assertIn("INVALID_ANIMATION_RANGE", {f.rule_id for f in report.findings})

    def test_animation_without_known_range_is_not_claimed_checked(self):
        self.assertIn("ANIMATION_RANGE_UNKNOWN", rules(scene(mesh(has_animation=True))))

    def test_report_is_deterministic_under_object_and_image_order(self):
        first = mesh(name="B", uv_layer_count=0)
        second = mesh(name="A", nonmanifold_edges=3)
        one = validate_scene(scene(first, second, missing_images=("z", "a")), QualityProfile())
        two = validate_scene(scene(second, first, missing_images=("a", "z")), QualityProfile())
        self.assertEqual(one, two)
        self.assertEqual(
            json.dumps(one.to_dict(), sort_keys=True), json.dumps(two.to_dict(), sort_keys=True)
        )

    def test_report_has_json_contract_and_uppercase_severity_counts(self):
        report = validate_scene(
            scene(mesh(nonmanifold_edges=1, degenerate_faces=1)), QualityProfile()
        )
        data = report.to_dict()
        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(data["profile_id"], "studio_static")
        self.assertEqual(data["counts"], {"ERROR": 1, "WARNING": 1, "INFO": 0})
        self.assertFalse(data["passed"])
        self.assertIsInstance(data["findings"], list)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_report_passed_only_means_no_errors(self):
        warning = Finding("REVIEW", "WARNING", "modeling", None, "Review", "Inspect")
        self.assertTrue(ValidationReport("test", (warning,)).passed)
        self.assertFalse(ValidationReport("test", (replace(warning, severity="ERROR"),)).passed)

    def test_validation_does_not_change_snapshot(self):
        snapshot = scene(mesh(loose_vertices=1))
        original = repr(snapshot)
        validate_scene(snapshot, QualityProfile())
        self.assertEqual(repr(snapshot), original)

    def test_texture_target_zero_does_not_impose_a_minimum(self):
        snapshot = scene(mesh(), textures=(TextureSnapshot("Detail", 512, 512),))
        self.assertNotIn("TEXTURE_BELOW_TARGET", rules(snapshot))

    def test_low_resolution_advice_is_info_not_quality_failure(self):
        profile = replace(QualityProfile(), texture_target=8192)
        snapshot = scene(mesh(), textures=(TextureSnapshot("Surface", 4096, 4096),))
        report = validate_scene(snapshot, profile)
        finding = next(f for f in report.findings if f.rule_id == "TEXTURE_BELOW_TARGET")
        self.assertEqual(finding.severity, "INFO")
        self.assertIn("texel density", finding.remediation)
        self.assertIn("upscale", finding.remediation)
        self.assertTrue(report.passed)

    def test_texture_target_uses_shorter_dimension_and_accepts_boundary(self):
        profile = replace(QualityProfile(), texture_target=8192)
        at_target = scene(mesh(), textures=(TextureSnapshot("Surface", 8192, 8192),))
        below_target = scene(mesh(), textures=(TextureSnapshot("Surface", 8192, 4096),))
        self.assertNotIn("TEXTURE_BELOW_TARGET", rules(at_target, profile))
        self.assertIn("TEXTURE_BELOW_TARGET", rules(below_target, profile))

    def test_texture_maximum_warns_on_longer_dimension(self):
        profile = replace(QualityProfile(), max_texture_resolution=8192)
        snapshot = scene(mesh(), textures=(TextureSnapshot("Surface", 16384, 4096),))
        report = validate_scene(snapshot, profile)
        finding = next(f for f in report.findings if f.rule_id == "TEXTURE_OVER_BUDGET")
        self.assertEqual(finding.severity, "WARNING")

    def test_unknown_texture_dimensions_do_not_trigger_low_resolution_advice(self):
        profile = replace(QualityProfile(), texture_target=8192)
        snapshot = scene(mesh(), textures=(TextureSnapshot("Unloaded", 0, 0),))
        found = rules(snapshot, profile)
        self.assertIn("TEXTURE_DIMENSIONS_UNKNOWN", found)
        self.assertNotIn("TEXTURE_BELOW_TARGET", found)

    def test_texture_dimensions_reject_invalid_values(self):
        for dimensions in [(-1, 1), (1, -1), (math.nan, 1), (1.5, 1), (True, 1)]:
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                TextureSnapshot("Invalid", *dimensions)

    def test_texture_profile_limits_are_coherent(self):
        for changes in [
            dict(texture_target=-1),
            dict(max_texture_resolution=0),
            dict(texture_target=16384, max_texture_resolution=8192),
            dict(texture_target=8192.5),
            dict(max_texture_resolution=math.inf),
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(QualityProfile(), **changes)

    def test_8k_profile_is_a_starting_point_that_can_be_overridden(self):
        profile = PROFILES["cinematic_8k"]
        self.assertEqual(profile.texture_target, 8192)
        self.assertEqual(replace(profile, texture_target=4096).texture_target, 4096)

    def test_texture_order_does_not_affect_report(self):
        low = TextureSnapshot("Low", 1024, 1024)
        high = TextureSnapshot("High", 32768, 32768)
        profile = PROFILES["cinematic_8k"]
        one = validate_scene(scene(mesh(), textures=(low, high)), profile)
        two = validate_scene(scene(mesh(), textures=(high, low)), profile)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
