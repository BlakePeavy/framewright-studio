"""Deterministic, host-independent preflight checks.

These checks identify structural facts and review work. A passing report does not
establish appearance, animation quality, performance, or production acceptance.
All resource budgets are provisional policy values that callers can override.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose, isfinite
from types import MappingProxyType


@dataclass(frozen=True)
class ObjectSnapshot:
    name: str
    type: str
    vertex_count: int = 0
    edge_count: int = 0
    polygon_count: int = 0
    triangle_count: int = 0
    nonmanifold_edges: int = 0
    loose_vertices: int = 0
    degenerate_faces: int = 0
    uv_layer_count: int = 0
    material_slot_count: int = 0
    missing_material_slots: int = 0
    scale: tuple[float, float, float] = (1, 1, 1)
    modifier_types: tuple[str, ...] = ()
    vertex_group_count: int = 0
    armature_target: str | None = None
    bone_count: int = 0
    root_bone_count: int = 0
    unweighted_vertices: int = 0
    max_vertex_influences: int = 0
    has_animation: bool = False
    animation_range: tuple[float, float] | None = None


def _integer_at_least(value: int, minimum: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class TextureSnapshot:
    name: str
    width: int
    height: int
    source: str = "FILE"
    color_space: str = ""

    def __post_init__(self) -> None:
        _integer_at_least(self.width, 0, "width")
        _integer_at_least(self.height, 0, "height")


@dataclass(frozen=True)
class SceneSnapshot:
    name: str
    objects: tuple[ObjectSnapshot, ...] = ()
    unit_system: str = "METRIC"
    unit_scale: float = 1.0
    fps: float = 24.0
    frame_start: int = 1
    frame_end: int = 250
    camera_name: str | None = None
    light_count: int = 0
    world_present: bool = False
    missing_images: tuple[str, ...] = ()
    textures: tuple[TextureSnapshot, ...] = ()


@dataclass(frozen=True)
class QualityProfile:
    id: str = "studio_static"
    max_triangles: int = 100000
    max_bone_influences: int = 4
    require_uvs: bool = True
    require_materials: bool = True
    require_camera: bool = False
    require_lighting: bool = False
    texture_target: int = 0
    max_texture_resolution: int = 16384

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("id must be a nonempty string")
        for field_name in ("max_triangles", "max_bone_influences", "max_texture_resolution"):
            _integer_at_least(getattr(self, field_name), 1, field_name)
        _integer_at_least(self.texture_target, 0, "texture_target")
        if self.texture_target > self.max_texture_resolution:
            raise ValueError("texture_target cannot exceed max_texture_resolution")
        for field_name in (
            "require_uvs",
            "require_materials",
            "require_camera",
            "require_lighting",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    category: str
    object_name: str | None
    message: str
    remediation: str
    fix_id: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    profile_id: str
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        """No ERROR findings; this is not visual or production acceptance."""
        return not any(finding.severity == "ERROR" for finding in self.findings)

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "profile_id": self.profile_id,
            "passed": self.passed,
            "counts": {
                severity: sum(f.severity == severity for f in self.findings)
                for severity in ("ERROR", "WARNING", "INFO")
            },
            "findings": [asdict(finding) for finding in self.findings],
        }


# Explicit starting policies, not universal AAA budgets or Sundown acceptance.
PROFILES = MappingProxyType(
    {
        "studio_static": QualityProfile(),
        "sundown_static": QualityProfile(id="sundown_static"),
        "animation_scene": QualityProfile(id="animation_scene", require_camera=True),
        "lookdev_scene": QualityProfile(
            id="lookdev_scene", require_camera=True, require_lighting=True
        ),
        "cinematic_8k": QualityProfile(
            id="cinematic_8k",
            max_triangles=2000000,
            max_bone_influences=8,
            require_camera=True,
            require_lighting=True,
            texture_target=8192,
        ),
        "realtime_high": QualityProfile(id="realtime_high", max_texture_resolution=8192),
    }
)


def validate_scene(snapshot: SceneSnapshot, profile: QualityProfile) -> ValidationReport:
    """Inspect captured facts without touching Blender or changing the input."""
    findings: list[Finding] = []

    def add(rule, severity, category, name, message, remediation, fix_id=None):
        findings.append(Finding(rule, severity, category, name, message, remediation, fix_id))

    if not snapshot.objects:
        add(
            "EMPTY_SCENE",
            "WARNING",
            "scene",
            None,
            "Scene has no objects.",
            "Choose the asset scene to inspect or add the intended assets.",
        )

    if not isfinite(snapshot.unit_scale) or snapshot.unit_scale <= 0:
        add(
            "INVALID_UNITS",
            "ERROR",
            "scene",
            None,
            "Unit scale is not finite and positive.",
            "Set a finite positive unit scale and verify actual asset dimensions.",
        )
    elif snapshot.unit_system != "METRIC" or not isclose(snapshot.unit_scale, 1.0, abs_tol=1e-6):
        add(
            "INVALID_UNITS",
            "WARNING",
            "scene",
            None,
            "Scene differs from the provisional meter-based authoring convention.",
            "Verify dimensions and the destination's export unit conversion before changing units.",
        )

    if not isfinite(snapshot.fps) or snapshot.fps <= 0:
        add(
            "FRAME_RATE",
            "ERROR",
            "animation",
            None,
            "Frame rate must be finite and positive.",
            "Set the intended positive frame rate before animation export.",
        )
    if snapshot.frame_start > snapshot.frame_end:
        add(
            "FRAME_RANGE",
            "ERROR",
            "animation",
            None,
            "Scene start frame exceeds its end frame.",
            "Set an ordered scene frame range covering the intended shot or clip.",
        )
    if profile.require_camera and not snapshot.camera_name:
        add(
            "MISSING_CAMERA",
            "WARNING",
            "lighting",
            None,
            "Scene has no active render camera.",
            "Assign a camera and inspect framing at the intended output resolution.",
        )
    if profile.require_lighting and not snapshot.light_count and not snapshot.world_present:
        add(
            "MISSING_LIGHTING",
            "WARNING",
            "lighting",
            None,
            "Scene has no lights or world datablock.",
            "Set up lighting and review exposure, materials and contrast in a rendered view.",
        )
    for name in sorted(set(snapshot.missing_images)):
        add(
            "MISSING_TEXTURES",
            "ERROR",
            "modeling",
            None,
            f"Image '{name}' has missing file data.",
            "Relink or pack the intended source image, then inspect the material in Blender.",
        )

    armatures = {obj.name for obj in snapshot.objects if obj.type == "ARMATURE"}
    for obj in snapshot.objects:
        if obj.type in {"MESH", "ARMATURE"}:
            if any(not isfinite(value) or value == 0 for value in obj.scale):
                add(
                    "INVALID_SCALE",
                    "ERROR",
                    "modeling",
                    obj.name,
                    "Object has zero or nonfinite scale.",
                    "Inspect transforms and recover a valid scale without collapsing geometry.",
                )
            else:
                if any(value < 0 for value in obj.scale):
                    add(
                        "NEGATIVE_SCALE",
                        "WARNING",
                        "modeling",
                        obj.name,
                        "Object has a reflected scale component.",
                        "Review winding, normals, rig behavior and the destination's export conventions.",
                    )
                if any(not isclose(value, 1.0, rel_tol=1e-6, abs_tol=1e-6) for value in obj.scale):
                    add(
                        "UNAPPLIED_SCALE",
                        "WARNING",
                        "modeling",
                        obj.name,
                        "Object scale differs from identity.",
                        "Verify the intended transform; test on a derivative before applying scale.",
                    )

        if obj.type == "MESH":
            if not obj.vertex_count or not obj.polygon_count:
                add(
                    "EMPTY_MESH",
                    "ERROR",
                    "modeling",
                    obj.name,
                    "Mesh has no surface geometry.",
                    "Model the intended surface or exclude this helper object from the deliverable.",
                )
            if profile.require_uvs and not obj.uv_layer_count:
                add(
                    "MISSING_UVS",
                    "WARNING",
                    "modeling",
                    obj.name,
                    "Mesh has no UV layer.",
                    "Author UVs where needed; inspect coverage, overlap and texel density.",
                )
            if profile.require_materials and not obj.material_slot_count:
                add(
                    "MISSING_MATERIALS",
                    "WARNING",
                    "modeling",
                    obj.name,
                    "Mesh has no material slots.",
                    "Assign the intended material and inspect it under representative lighting.",
                )
            if obj.missing_material_slots:
                add(
                    "EMPTY_MATERIAL_SLOTS",
                    "WARNING",
                    "modeling",
                    obj.name,
                    f"Mesh has {obj.missing_material_slots} empty material slots.",
                    "Assign or intentionally remove empty slots while preserving face assignments.",
                )
            if obj.nonmanifold_edges:
                add(
                    "NONMANIFOLD_EDGES",
                    "WARNING",
                    "modeling",
                    obj.name,
                    f"Mesh has {obj.nonmanifold_edges} edges without exactly two incident faces.",
                    "Inspect open boundaries and intersections; open sheets can be intentional.",
                )
            if obj.loose_vertices:
                add(
                    "LOOSE_VERTICES",
                    "WARNING",
                    "modeling",
                    obj.name,
                    f"Mesh has {obj.loose_vertices} isolated vertices.",
                    "Preview removal on a derivative and preserve the original editable source.",
                    "mesh.remove_loose_vertices",
                )
            if obj.degenerate_faces:
                add(
                    "DEGENERATE_FACES",
                    "ERROR",
                    "modeling",
                    obj.name,
                    f"Mesh has {obj.degenerate_faces} zero-area or near-zero-area faces.",
                    "Inspect and repair collapsed faces on a derivative before export.",
                )
            if obj.triangle_count > profile.max_triangles:
                add(
                    "TRIANGLE_BUDGET",
                    "WARNING",
                    "modeling",
                    obj.name,
                    f"Mesh has {obj.triangle_count} triangles; provisional per-mesh budget is {profile.max_triangles}.",
                    "Review camera coverage and measured performance; configure the budget or author verified LODs.",
                )
            if obj.armature_target or "ARMATURE" in obj.modifier_types:
                if obj.armature_target not in armatures:
                    add(
                        "MISSING_ARMATURE",
                        "ERROR",
                        "rigging",
                        obj.name,
                        "Armature modifier has no matching armature in the captured scene.",
                        "Bind to the intended armature and include it in the asset scene.",
                    )
                if obj.unweighted_vertices:
                    add(
                        "UNWEIGHTED_VERTICES",
                        "ERROR",
                        "rigging",
                        obj.name,
                        f"Skinned mesh has {obj.unweighted_vertices} vertices without deform-bone weights.",
                        "Assign and normalize intended deform weights, then inspect representative poses.",
                    )
                if obj.max_vertex_influences > profile.max_bone_influences:
                    add(
                        "BONE_INFLUENCES",
                        "WARNING",
                        "rigging",
                        obj.name,
                        f"A vertex has {obj.max_vertex_influences} influences; provisional limit is {profile.max_bone_influences}.",
                        "Verify destination limits before pruning weights; compare deformation before and after.",
                    )

        if obj.type == "ARMATURE":
            if not obj.bone_count:
                add(
                    "EMPTY_ARMATURE",
                    "ERROR",
                    "rigging",
                    obj.name,
                    "Armature has no bones.",
                    "Create the intended skeleton or exclude this empty helper.",
                )
            elif obj.root_bone_count > 1:
                add(
                    "MULTIPLE_ROOT_BONES",
                    "WARNING",
                    "rigging",
                    obj.name,
                    f"Armature has {obj.root_bone_count} root bones.",
                    "Check the target skeleton contract; multiple roots may be intentional in control rigs.",
                )

        if obj.has_animation:
            if obj.animation_range is None:
                add(
                    "ANIMATION_RANGE_UNKNOWN",
                    "INFO",
                    "animation",
                    obj.name,
                    "Animation is present but no bounded action or strip range was captured.",
                    "Review drivers, constraints and procedural animation over the intended scene range.",
                )
            elif (
                any(not isfinite(frame) for frame in obj.animation_range)
                or obj.animation_range[0] > obj.animation_range[1]
            ):
                add(
                    "INVALID_ANIMATION_RANGE",
                    "ERROR",
                    "animation",
                    obj.name,
                    "Animation range is nonfinite or reversed.",
                    "Inspect the active action and strips, then set a valid export range.",
                )
            elif (
                obj.animation_range[0] < snapshot.frame_start
                or obj.animation_range[1] > snapshot.frame_end
            ):
                add(
                    "ANIMATION_RANGE",
                    "WARNING",
                    "animation",
                    obj.name,
                    "Captured animation extends outside the scene frame range.",
                    "Choose the intended clip range and verify whether trimming is deliberate.",
                )

    for texture in snapshot.textures:
        if not texture.width or not texture.height:
            add(
                "TEXTURE_DIMENSIONS_UNKNOWN",
                "INFO",
                "modeling",
                None,
                f"Image '{texture.name}' has unavailable dimensions.",
                "Load the image or inspect its source before judging resolution.",
            )
            continue
        if profile.texture_target and min(texture.width, texture.height) < profile.texture_target:
            add(
                "TEXTURE_BELOW_TARGET",
                "INFO",
                "modeling",
                None,
                f"Image '{texture.name}' is {texture.width}x{texture.height}; requested short-edge target is {profile.texture_target}.",
                "Inspect texel density and camera coverage; do not upscale indiscriminately or treat resolution as quality.",
            )
        if max(texture.width, texture.height) > profile.max_texture_resolution:
            add(
                "TEXTURE_OVER_BUDGET",
                "WARNING",
                "modeling",
                None,
                f"Image '{texture.name}' exceeds the provisional {profile.max_texture_resolution}-pixel long-edge budget.",
                "Measure memory and streaming cost; configure the budget or author an appropriate derivative.",
            )

    severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    findings.sort(
        key=lambda f: (
            severity_order[f.severity],
            f.category,
            f.object_name or "",
            f.rule_id,
            f.message,
        )
    )
    return ValidationReport(profile.id, tuple(findings))
