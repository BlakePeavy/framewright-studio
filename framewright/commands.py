"""Auditable production command registry with dependency-free input schemas."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from importlib import import_module

from .core import PROFILES


def string(maximum=1024):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def number(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def array(items, minimum=0, maximum=1000):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def obj(properties=None, required=(), *, open_object=False):
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": open_object,
    }


BOOL = {"type": "boolean"}
DRY = {"type": "boolean", "default": True}
JSON_OBJECT = obj(open_object=True)
LOCATION = array(number(-1_000_000, 1_000_000), 3, 3)
PROFILE_LIMITS = {
    "max_triangles": (1, 100_000_000),
    "max_bone_influences": (1, 32),
    "texture_target": (0, 65536),
    "max_texture_resolution": (1, 65536),
}
PROFILE_FLAGS = ("require_uvs", "require_materials", "require_camera", "require_lighting")
BASELINE_SCHEMAS = {
    "capabilities": obj(),
    "scene.inspect": obj(),
    "scene.validate": obj(
        {
            "profile": {"type": "string", "enum": sorted(PROFILES)},
            "overrides": obj(
                {
                    **{key: integer(*bounds) for key, bounds in PROFILE_LIMITS.items()},
                    **{key: BOOL for key in PROFILE_FLAGS},
                }
            ),
        }
    ),
    "mesh.remove_loose_vertices": obj({"object_name": string(), "dry_run": DRY}, ["object_name"]),
}


def spec(module, function, schema, *, mutates=False, blender=True, effect="read"):
    return {
        "module": module,
        "function": function,
        "input_schema": schema,
        "mutates": mutates,
        "blender_required": blender,
        "effect": effect,
    }


_MESH = {
    "object_name": string(),
    "evaluated": BOOL,
    "max_triangles": integer(1, 200000),
    "max_pairs": integer(1, 2000000),
    "open_boundary_allowed": BOOL,
}
COMMANDS = {
    "contacts.describe_region": spec(
        "region_description",
        "describe_region",
        {
            **obj(
                {
                    "object_name": string(256),
                    "region_id": string(64),
                    "sample_time": number(-1_000_000, 1_000_000),
                    "vertex_indices": array(integer(0, 999_999), 3, 65_536),
                    "vertex_group": string(256),
                    "expected_topology_sha256": {**string(64), "minLength": 64},
                    "max_evaluated_vertices": integer(1, 1_000_000),
                    "max_evaluated_triangles": integer(1, 500_000),
                    "max_region_triangles": integer(1, 16_384),
                    "max_group_entries": integer(1, 2_000_000),
                },
                ["object_name", "region_id", "sample_time"],
            ),
            "description": (
                "Describe current evaluated triangle membership at an explicit time. "
                "Supply exactly one of vertex_indices or vertex_group; the adapter "
                "enforces this choice, unique indices and an optional topology digest. "
                "Membership selects a triangle only when all three vertices belong."
            ),
        },
    ),
    "contacts.inspect_regions": spec(
        "region_contacts",
        "inspect_regions",
        obj(
            {
                "surface_name": string(256),
                "regions": array(
                    obj(
                        {
                            "id": string(64),
                            "object_name": string(256),
                            "topology_sha256": {**string(64), "minLength": 64},
                            "triangles": array(
                                obj(
                                    {
                                        "index": integer(0, 9_999_999),
                                        "vertices": array(integer(0, 999_999), 3, 3),
                                    },
                                    ["index", "vertices"],
                                ),
                                1,
                                16_384,
                            ),
                        },
                        ["id", "object_name", "topology_sha256", "triangles"],
                    ),
                    1,
                    8,
                ),
                "frame_start": integer(-1_000_000, 1_000_000),
                "frame_end": integer(-1_000_000, 1_000_000),
                "substeps": integer(1, 8),
                "max_samples": integer(1, 4096),
                "max_evaluated_vertices": integer(1, 1_000_000),
                "max_surface_triangles": integer(1, 500_000),
                "max_region_triangles": integer(1, 16_384),
                "distance_epsilon_m": number(1e-9, 1e-3),
                "proximity_distance_m": number(1e-9, 1),
                "max_candidate_visits": integer(1, 50_000_000),
                "max_pair_checks": integer(1, 10_000_000),
                "max_examples": integer(0, 1000),
            },
            ["surface_name", "regions", "frame_start", "frame_end"],
        ),
    ),
    "animation.skin_contacts": spec(
        "skin_contacts",
        "inspect_skin_contacts",
        obj(
            {
                "surface_name": string(),
                "markers": array(
                    obj(
                        {
                            "id": string(128),
                            "object_name": string(),
                            "vertex_indices": array(integer(0, 999999), 1, 3),
                            "weights": array(number(0, 1), 1, 3),
                        },
                        ["id", "object_name", "vertex_indices", "weights"],
                    ),
                    1,
                    32,
                ),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "substeps": integer(1, 8),
                "max_samples": integer(1, 4096),
                "max_evaluated_vertices": integer(1, 1000000),
                "max_surface_triangles": integer(1, 500000),
                "search_distance": number(0.000001, 1000000),
                "contact_tolerance": number(0, 1000000),
                "penetration_tolerance": number(0, 1000000),
                "sliding_speed": number(0, 1000000),
                "minimum_up_dot": number(0, 1),
            },
            ["surface_name", "markers", "frame_start", "frame_end"],
        ),
    ),
    "animation.surface_contacts": spec(
        "contact_analysis",
        "inspect_surface_contacts",
        obj(
            {
                "surface_name": string(),
                "markers": array(
                    obj(
                        {
                            "id": string(128),
                            "object_name": string(),
                            "bone": string(),
                            "position": LOCATION,
                        },
                        ["id", "object_name", "position"],
                    ),
                    1,
                    32,
                ),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "step": integer(1, 1000),
                "substeps": integer(1, 8),
                "max_samples": integer(1, 4096),
                "max_surface_triangles": integer(1, 500000),
                "search_distance": number(0.000001, 1000000),
                "contact_tolerance": number(0, 1000000),
                "penetration_tolerance": number(0, 1000000),
                "sliding_speed": number(0, 1000000),
                "minimum_up_dot": number(0, 1),
            },
            ["surface_name", "markers", "frame_start", "frame_end"],
        ),
    ),
    "rig.bind_mesh": spec(
        "rig_binding",
        "bind_mesh",
        obj(
            {
                "object_name": string(),
                "armature_name": string(),
                "dry_run": DRY,
                "max_vertices": integer(1, 1000000),
                "max_deform_bones": integer(1, 1024),
                "require_complete_weights": BOOL,
            },
            ["object_name", "armature_name"],
        ),
        mutates=True,
        effect="scene",
    ),
    "surfaces.assign_material": spec(
        "material_assignment",
        "assign_material",
        obj(
            {
                "object_name": string(),
                "material_name": string(),
                "slot_indices": {**array(integer(0, 127), 1, 128), "uniqueItems": True},
                "dry_run": DRY,
            },
            ["object_name", "material_name", "slot_indices"],
        ),
        mutates=True,
        effect="scene",
    ),
    "surfaces.create_pbr_material": spec(
        "materials",
        "create_pbr_material",
        obj(
            {
                "name": string(48),
                "base_color_path": string(4096),
                "roughness_path": string(4096),
                "metallic_path": string(4096),
                "normal_path": string(4096),
                "normal_convention": {"type": "string", "enum": ["OPENGL"]},
                "max_memory_mb": integer(1, 32768),
                "dry_run": DRY,
            },
            ["base_color_path"],
        ),
        mutates=True,
        effect="scene",
    ),
    "asset.reference_board": spec(
        "reference_board",
        "create_board",
        obj(
            {"manifest": JSON_OBJECT, "output": string(4096), "dry_run": DRY},
            ["manifest", "output"],
        ),
        mutates=True,
        blender=False,
        effect="files",
    ),
    "rig.fit_metarig": spec(
        "rig_fit",
        "fit_metarig",
        obj(
            {
                "object_name": string(),
                "landmarks": JSON_OBJECT,
                "bone_map": JSON_OBJECT,
                "units": {"type": "string", "enum": ["meters", "centimeters", "blender_units"]},
                "coordinate_space": {"type": "string", "enum": ["world", "armature_local"]},
                "protected_bones": array(string(), 0, 512),
                "dry_run": DRY,
            },
            ["object_name", "landmarks", "bone_map"],
        ),
        mutates=True,
        effect="scene",
    ),
    "secondary.inspect_bindings": spec(
        "secondary_motion",
        "inspect_bindings",
        obj({"object_names": array(string(), 1, 64)}, ["object_names"]),
    ),
    "secondary.attach_rigid": spec(
        "secondary_motion",
        "attach_rigid",
        obj(
            {"object_name": string(), "armature_name": string(), "bone": string(), "dry_run": DRY},
            ["object_name", "armature_name", "bone"],
        ),
        mutates=True,
        effect="scene",
    ),
    "rig.activate_corrective": spec(
        "pose_correctives",
        "activate_corrective",
        obj(
            {
                "object_name": string(),
                "shape_key": string(),
                "armature_name": string(),
                "proximal_bone": string(),
                "joint_bone": string(),
                "distal_bone": string(),
                "onset_degrees": number(0, 170),
                "full_degrees": number(0, 170),
                "dry_run": DRY,
            },
            [
                "object_name",
                "shape_key",
                "armature_name",
                "proximal_bone",
                "joint_bone",
                "distal_bone",
            ],
        ),
        mutates=True,
        effect="scene",
    ),
    "secondary.bake_cloth": spec(
        "cloth_baking",
        "bake_cloth",
        obj(
            {
                "object_name": string(),
                "modifier_name": string(),
                "max_frames": integer(1, 512),
                "max_vertices": integer(1, 50000),
                "max_memory_mb": integer(1, 4096),
                "dry_run": DRY,
            },
            ["object_name", "modifier_name"],
        ),
        mutates=True,
        effect="scene",
    ),
    "secondary.create_cloth_proxy": spec(
        "secondary_motion",
        "create_cloth_proxy",
        obj(
            {
                "object_name": string(),
                "pin_group": string(),
                "frame_start": integer(1, 1000000),
                "frame_end": integer(1, 1000000),
                "quality": integer(1, 20),
                "collision_distance": number(0.0001, 1),
                "self_collision": BOOL,
                "collider_names": array(string(), 0, 8),
                "dry_run": DRY,
            },
            ["object_name", "pin_group"],
        ),
        mutates=True,
        effect="scene",
    ),
    "pose.capture": spec(
        "secondary_motion",
        "capture_pose",
        obj({"object_name": string(), "bones": array(string(), 1, 128)}, ["object_name", "bones"]),
    ),
    "pose.apply": spec(
        "secondary_motion",
        "apply_pose",
        obj(
            {
                "object_name": string(),
                "pose": JSON_OBJECT,
                "bone_map": JSON_OBJECT,
                "bound_mesh_names": array(string(), 0, 32),
                "dry_run": DRY,
            },
            ["object_name", "pose", "bone_map"],
        ),
        mutates=True,
        effect="scene",
    ),
    "shapes.apply_values": spec(
        "secondary_motion",
        "apply_shape_values",
        obj(
            {
                "object_name": string(),
                "values": JSON_OBJECT,
                "protected_keys": array(string(), 0, 128),
                "dry_run": DRY,
            },
            ["object_name", "values"],
        ),
        mutates=True,
        effect="scene",
    ),
    "settings.migrate": spec(
        "settings", "migrate_request", obj({"settings": JSON_OBJECT}, ["settings"]), blender=False
    ),
    "rig.generate": spec(
        "rigging",
        "generate_rig",
        obj({"object_name": string(), "dry_run": DRY}, ["object_name"]),
        mutates=True,
        effect="scene",
    ),
    "animation.retarget": spec(
        "animation",
        "retarget_animation",
        obj(
            {
                "object_name": string(),
                "source_name": string(),
                "bone_map": JSON_OBJECT,
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "step": integer(1, 1000),
                "max_samples": integer(1, 256),
                "root_bone": string(),
                "translation_scale": number(0.001, 1000),
                "dry_run": DRY,
            },
            ["object_name", "source_name", "bone_map", "frame_start", "frame_end"],
        ),
        mutates=True,
        effect="scene",
    ),
    "animation.cleanup": spec(
        "animation",
        "cleanup_animation",
        obj(
            {
                "object_name": string(),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "threshold": number(0, 10000),
                "strength": number(0, 1),
                "max_keys": integer(1, 1000000),
                "dry_run": DRY,
            },
            ["object_name", "frame_start", "frame_end"],
        ),
        mutates=True,
        effect="scene",
    ),
    "surfaces.bake_material_atlas": spec(
        "material_atlas",
        "bake_material_atlas",
        obj(
            {
                "object_names": {**array(string(), 1, 64), "uniqueItems": True},
                "name": string(48),
                "resolution": integer(64, 8192),
                "margin": integer(0, 64),
                "max_memory_mb": integer(1, 32768),
                "max_evaluated_vertices": integer(1, 1_000_000),
                "max_evaluated_triangles": integer(1, 500_000),
                "dry_run": DRY,
            },
            ["object_names"],
        ),
        mutates=True,
        effect="scene",
    ),
    "surfaces.bake_normal": spec(
        "baking",
        "bake_normal",
        obj(
            {
                "high_object": string(),
                "low_object": string(),
                "cage_object": string(),
                "resolution": integer(64, 8192),
                "ray_distance": number(0.0001, 10),
                "max_memory_mb": integer(1, 32768),
                "margin": integer(0, 64),
                "dry_run": DRY,
            },
            ["high_object", "low_object"],
        ),
        mutates=True,
        effect="scene",
    ),
    "rig.inspect": spec("rigging", "inspect_rig", obj({"object_name": string()}, ["object_name"])),
    "rig.normalize_weights": spec(
        "rigging",
        "normalize_weights",
        obj(
            {
                "object_name": string(),
                "dry_run": DRY,
                "protected_vertices": array(integer(0, 10000000), 0, 100000),
                "max_influences": integer(1, 32),
                "max_vertices": integer(1, 1000000),
            },
            ["object_name"],
        ),
        mutates=True,
        effect="scene",
    ),
    "rig.sample_deformation": spec(
        "rigging",
        "sample_deformation",
        obj(
            {
                "object_name": string(),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "step": integer(1, 1000),
                "max_samples": integer(1, 256),
                "max_vertices": integer(1, 200000),
            },
            ["object_name", "frame_start", "frame_end"],
        ),
    ),
    "rig.corrective_shape": spec(
        "rigging",
        "corrective_shape",
        obj(
            {
                "object_name": string(),
                "dry_run": DRY,
                "name": string(128),
                "offsets": array(
                    obj({"vertex": integer(0, 10000000), "offset": LOCATION}, ["vertex", "offset"]),
                    1,
                    10000,
                ),
                "protected_vertices": array(integer(0, 10000000), 0, 100000),
            },
            ["object_name", "name", "offsets"],
        ),
        mutates=True,
        effect="scene",
    ),
    "animation.inspect": spec(
        "animation", "inspect_animation", obj({"object_name": string()}, ["object_name"])
    ),
    "animation.contacts": spec(
        "animation",
        "inspect_contacts",
        obj(
            {
                "object_name": string(),
                "bones": array(string(), 1, 16),
                "root_bone": string(),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "step": integer(1, 1000),
                "max_samples": integer(1, 256),
                "ground_height": number(-10000, 10000),
                "contact_tolerance": number(0, 100),
                "sliding_speed": number(0, 100),
                "penetration_tolerance": number(0, 100),
            },
            ["object_name", "bones", "frame_start", "frame_end"],
        ),
    ),
    "animation.bake_bbone_skin": spec(
        "bbone_baking",
        "bake_bbone_skin",
        obj(
            {
                "object_name": string(256),
                "armature_name": string(256),
                "frame_start": integer(-1_000_000, 1_000_000),
                "frame_end": integer(-1_000_000, 1_000_000),
                "max_surface_error_m": number(1e-7, 1),
                "max_key_times": integer(1, 1025),
                "max_samples": integer(1, 4097),
                "max_vertex_samples": integer(1, 100_000_000),
                "max_joints": integer(1, 1024),
                "max_influences": integer(1, 32),
                "max_refinement_depth": integer(0, 6),
                "dry_run": DRY,
            },
            ["object_name", "armature_name", "frame_start", "frame_end", "max_surface_error_m"],
        ),
        mutates=True,
        effect="scene",
    ),
    "animation.bake_shape_keys": spec(
        "shape_baking",
        "bake_shape_keys",
        obj(
            {
                "object_name": string(),
                "armature_name": string(),
                "baked_armature_name": string(),
                "shape_keys": array(string(), 1, 32),
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "max_samples": integer(1, 256),
                "max_interpolation_error": number(0, 1),
                "dry_run": DRY,
            },
            [
                "object_name",
                "armature_name",
                "baked_armature_name",
                "shape_keys",
                "frame_start",
                "frame_end",
            ],
        ),
        mutates=True,
        effect="scene",
    ),
    "animation.bake": spec(
        "animation",
        "bake_animation",
        obj(
            {
                "object_name": string(),
                "dry_run": DRY,
                "frame_start": integer(-1000000, 1000000),
                "frame_end": integer(-1000000, 1000000),
                "step": integer(1, 1000),
                "max_samples": integer(1, 256),
            },
            ["object_name", "frame_start", "frame_end"],
        ),
        mutates=True,
        effect="scene",
    ),
    "model.create_lod": spec(
        "lod",
        "create_lod",
        obj(
            {
                "object_name": string(),
                "ratio": number(0.01, 0.99),
                "level": integer(1, 8),
                "dry_run": DRY,
            },
            ["object_name"],
        ),
        mutates=True,
        effect="scene",
    ),
    "model.create_collision": spec(
        "lod",
        "create_collision",
        obj({"object_name": string(), "dry_run": DRY}, ["object_name"]),
        mutates=True,
        effect="scene",
    ),
    "mesh.compare_surface": spec(
        "lod",
        "compare_surface",
        obj(
            {
                "source_name": string(),
                "candidate_name": string(),
                "max_samples": integer(1, 100000),
            },
            ["source_name", "candidate_name"],
        ),
    ),
    "repair.cancel_plan": spec(
        "blender_transactions", "cancel_plan", obj({"plan_token": string(128)}, ["plan_token"])
    ),
    "asset.reference_create": spec(
        "provenance",
        "create_reference",
        obj(
            {
                "label": string(),
                "origin": string(),
                "location": string(8192),
                "license": string(),
                "sha256": string(64),
                "views": array(string()),
                "landmarks": array(JSON_OBJECT),
            },
            ["label"],
        ),
        blender=False,
    ),
    "asset.export": spec(
        "interchange",
        "export_asset",
        obj(
            {
                "object_names": array(string(), 1, 500),
                "directory": string(32768),
                "filename": string(64),
                "format": {"type": "string", "enum": ["GLB", "FBX"]},
                "include_animation": BOOL,
                "animation_substeps": {**integer(1, 64), "default": 1},
                "max_animation_samples": {**integer(1, 65536), "default": 16384},
                "max_material_memory_mb": integer(1, 32768),
                "clamp_scalar_textures": {"type": "boolean", "default": False},
                "profile": {"type": "string", "enum": ["generic", "sundown"]},
                "dry_run": DRY,
            },
            ["object_names", "directory"],
        ),
        mutates=True,
        effect="files",
    ),
    "workflow.run": spec(
        "workflows",
        "run_workflow",
        obj(
            {"run_id": string(80), "steps": array(JSON_OBJECT, 1, 32), "dry_run": DRY},
            ["run_id", "steps"],
        ),
        mutates=True,
        blender=False,
        effect="scene",
    ),
    "mesh.inspect_evaluated": spec("mesh_diagnostics", "inspect_mesh", obj(_MESH, ["object_name"])),
    "surfaces.inspect": spec(
        "surface_diagnostics",
        "inspect_surfaces",
        obj({**_MESH, "allow_stacked_uvs": BOOL, "uv_layer": string()}, ["object_name"]),
    ),
    "repair.plan_remove_loose": spec(
        "blender_transactions", "plan_remove_loose", obj({"object_name": string()}, ["object_name"])
    ),
    "repair.apply_plan": spec(
        "blender_transactions",
        "apply_plan",
        obj(
            {"plan_token": string(128), "source_fingerprint": string(128), "dry_run": DRY},
            ["plan_token", "source_fingerprint"],
        ),
        mutates=True,
        effect="scene",
    ),
    "repair.rollback": spec(
        "blender_transactions",
        "rollback_plan",
        obj({"transaction_id": string(128), "dry_run": DRY}, ["transaction_id"]),
        mutates=True,
        effect="scene",
    ),
    "asset.manifest_create": spec(
        "provenance",
        "create_manifest",
        obj(
            {
                "name": string(),
                "asset_id": string(128),
                "source_sha256": string(64),
                "recipe": JSON_OBJECT,
                "references": array(JSON_OBJECT),
                "expected_views": array(string()),
            },
            ["name"],
        ),
        blender=False,
    ),
    "asset.manifest_validate": spec(
        "provenance",
        "validate_manifest",
        obj({"manifest": JSON_OBJECT}, ["manifest"]),
        blender=False,
    ),
    "asset.manifest_derive": spec(
        "provenance",
        "derive_manifest",
        obj(
            {
                "parent": JSON_OBJECT,
                "name": string(),
                "source_sha256": string(64),
                "recipe": JSON_OBJECT,
            },
            ["parent", "name"],
        ),
        blender=False,
    ),
    "asset.reference_add": spec(
        "provenance",
        "add_reference",
        obj({"manifest": JSON_OBJECT, "reference": JSON_OBJECT}, ["manifest", "reference"]),
        blender=False,
    ),
    "asset.verification_record": spec(
        "provenance",
        "record_verification",
        obj(
            {
                "manifest": JSON_OBJECT,
                "stage": string(80),
                "status": string(80),
                "evidence": array(string(4096)),
            },
            ["manifest", "stage", "status", "evidence"],
        ),
        blender=False,
    ),
    "asset.reference_intake": spec(
        "provenance",
        "intake_reference",
        obj(
            {
                "path": string(4096),
                "label": string(),
                "origin": string(8192),
                "license": string(),
                "views": array(string()),
                "landmarks": array(
                    obj(
                        {"name": string(), "view": string(), "position": array(number(0, 1), 2, 2)},
                        ["name", "view", "position"],
                    )
                ),
                "max_bytes": integer(1, 2**30),
            },
            ["path", "label"],
        ),
        blender=False,
    ),
    "model.build_prop": spec(
        "production_assets",
        "build_prop",
        obj(
            {
                "name": string(48),
                "width": number(0.1, 100),
                "depth": number(0.1, 100),
                "height": number(0.1, 100),
                "board_thickness": number(0.001, 5),
                "bevel": number(0, 1),
                "door_open_degrees": number(-180, 180),
                "location": LOCATION,
                "dry_run": DRY,
            }
        ),
        mutates=True,
        effect="scene",
    ),
    "model.build_facade": spec(
        "production_assets",
        "build_facade",
        obj(
            {
                "name": string(48),
                "width": number(0.5, 100),
                "height": number(0.5, 100),
                "depth": number(0.01, 10),
                "door_width": number(0.1, 20),
                "door_height": number(0.1, 20),
                "window_width": number(0.1, 20),
                "window_height": number(0.1, 20),
                "sill_height": number(0, 20),
                "bevel": number(0, 1),
                "location": LOCATION,
                "dry_run": DRY,
            }
        ),
        mutates=True,
        effect="scene",
    ),
    "lighting.create_interior_fixture": spec(
        "light_review",
        "create_interior_fixture",
        obj(
            {
                "name": string(48),
                "dry_run": DRY,
                "resolution": integer(64, 8192),
                "samples": integer(1, 512),
                "glass_thickness": number(0.005, 0.25),
                "ior": number(1, 2.5),
                "roughness": number(0, 0.3),
                "window_power": number(0, 20000),
                "fill_power": number(0, 5000),
                "exposure": number(-8, 8),
                "max_pixel_samples": integer(4096, 34359738368),
                "max_render_memory_mb": integer(16, 16384),
            }
        ),
        mutates=True,
        effect="scene",
    ),
    "lighting.create_review": spec(
        "production_assets",
        "setup_review_scene",
        obj(
            {
                "name": string(48),
                "object_names": array(string(), 1, 1000),
                "collection_name": string(),
                "lighting": {"type": "string", "enum": ["neutral", "day", "dusk"]},
                "resolution": integer(64, 8192),
                "dry_run": DRY,
            }
        ),
        mutates=True,
        effect="scene",
    ),
    "scene.resources": spec("production_assets", "scene_resources", obj({"scene_name": string()})),
}


def _validate(value, schema, path="params", depth=0):
    if depth > 24:
        raise ValueError("Input nesting exceeds 24 levels")
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path} must be a JSON object")
        properties = schema["properties"]
        if set(schema["required"]) - value.keys():
            raise ValueError(f"{path} is missing required fields")
        if not schema["additionalProperties"] and value.keys() - properties.keys():
            raise ValueError(f"{path} has unknown fields")
        for key, item in value.items():
            _validate(item, properties.get(key, {}), f"{path}.{key}", depth + 1)
    elif kind == "array":
        if (
            not isinstance(value, list)
            or not schema["minItems"] <= len(value) <= schema["maxItems"]
        ):
            raise ValueError(f"{path} has invalid array size or type")
        for i, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{i}]", depth + 1)
        if schema.get("uniqueItems") and any(item in value[:i] for i, item in enumerate(value)):
            raise ValueError(f"{path} requires unique items")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{path} must be a boolean")
    elif kind in {"number", "integer"}:
        allowed = (int,) if kind == "integer" else (int, float)
        if (
            type(value) not in allowed
            or not math.isfinite(value)
            or not schema["minimum"] <= value <= schema["maximum"]
        ):
            raise ValueError(f"{path} must be a finite {kind} in the documented range")
    elif kind == "string":
        if (
            not isinstance(value, str)
            or "\x00" in value
            or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 32768)
        ):
            raise ValueError(f"{path} has an invalid string")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} has an unsupported value")
    else:
        # Open JSON metadata may contain heterogeneous values, never Python objects.
        if isinstance(value, dict):
            _validate(value, JSON_OBJECT, path, depth + 1)
        elif isinstance(value, list):
            _validate(value, array({}, maximum=10000), path, depth + 1)
        elif not (value is None or type(value) in (str, bool, int, float)):
            raise ValueError(f"{path} must contain JSON data only")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")


def command_schema(command):
    if command in BASELINE_SCHEMAS:
        return BASELINE_SCHEMAS[command]
    return COMMANDS[command]["input_schema"]


def command_mutates(command):
    return command == "mesh.remove_loose_vertices" or COMMANDS.get(command, {}).get(
        "mutates", False
    )


def validate_params(command, params):
    _validate(params, command_schema(command))
    if len(json.dumps(params, allow_nan=False)) > 1024 * 1024:
        raise ValueError("Command params exceed 1 MiB")


def command_metadata():
    return [
        {
            "name": name,
            **deepcopy(
                {key: value for key, value in entry.items() if key not in {"module", "function"}}
            ),
        }
        for name, entry in sorted(COMMANDS.items())
    ]


def invoke(command, params):
    validate_params(command, params)
    entry = COMMANDS[command]
    module = import_module("." + entry["module"], __package__)
    return getattr(module, entry["function"])(params)


def effect(command):
    """Persistence classification for batch runners; inputs cannot invent effects."""
    if not isinstance(command, str):
        return "read"
    if command == "mesh.remove_loose_vertices":
        return "scene"
    return COMMANDS.get(command, {}).get("effect", "read")


def needs_scene_save(request):
    if not isinstance(request, dict) or not isinstance(request.get("params"), dict):
        return False
    params = request["params"]
    if params.get("dry_run", True) is not False:
        return False
    if request.get("command") == "workflow.run":
        steps = params.get("steps", [])
        if not isinstance(steps, list):
            return False
        return any(
            isinstance(s, dict)
            and effect(s.get("command")) == "scene"
            and isinstance(s.get("params"), dict)
            # A result binding may resolve to False at runtime. Only a literal
            # True proves a scene-effect step cannot need persisted output.
            and s["params"].get("dry_run", False) is not True
            for s in steps
        )
    return effect(request.get("command")) == "scene"
