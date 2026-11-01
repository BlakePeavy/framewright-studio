# Increment 1 implementation contract

Package `framewright`. Core is pure Python; no runtime dependencies.

`core.py` exports frozen dataclasses:

- `ObjectSnapshot(name: str, type: str, vertex_count: int = 0, edge_count: int = 0, polygon_count: int = 0, triangle_count: int = 0, nonmanifold_edges: int = 0, loose_vertices: int = 0, degenerate_faces: int = 0, uv_layer_count: int = 0, material_slot_count: int = 0, missing_material_slots: int = 0, scale: tuple[float,float,float] = (1,1,1), modifier_types: tuple[str,...] = (), vertex_group_count: int = 0, armature_target: str | None = None, bone_count: int = 0, root_bone_count: int = 0, unweighted_vertices: int = 0, max_vertex_influences: int = 0, has_animation: bool = False, animation_range: tuple[float,float] | None = None)`
- `SceneSnapshot(name: str, objects: tuple[ObjectSnapshot,...] = (), unit_system: str = 'METRIC', unit_scale: float = 1.0, fps: float = 24.0, frame_start: int = 1, frame_end: int = 250, camera_name: str | None = None, light_count: int = 0, world_present: bool = False, missing_images: tuple[str,...] = ())`
- `TextureSnapshot(name: str, width: int, height: int, source: str = 'FILE', color_space: str = '')`; `SceneSnapshot` also has `textures: tuple[TextureSnapshot,...] = ()`.
- `QualityProfile(id: str = 'studio_static', max_triangles: int = 100000, max_bone_influences: int = 4, require_uvs: bool = True, require_materials: bool = True, require_camera: bool = False, require_lighting: bool = False)`
- `QualityProfile` also has `texture_target: int = 0` (disable lower-resolution advice), `max_texture_resolution: int = 16384`. These are editable policy knobs, not proof of visual quality.
- `Finding(rule_id: str, severity: str, category: str, object_name: str | None, message: str, remediation: str, fix_id: str | None = None)`
- `ValidationReport(profile_id: str, findings: tuple[Finding,...])`, property `passed` means no ERROR findings, method `to_dict()` returns JSON-compatible dict including schema_version='1.0', profile_id, passed, counts, findings.
- `PROFILES` maps `studio_static`, `sundown_static`, `animation_scene`, `lookdev_scene` to QualityProfile. Budgets provisional.
- Additional provisional profiles: `cinematic_8k` and `realtime_high`. Sundown is an integration destination, not the visual quality authority.
- `validate_scene(snapshot, profile) -> ValidationReport`. Findings deterministically sorted; rules identified by stable uppercase IDs. Loose vertices finding fix_id is `mesh.remove_loose_vertices`.

`blender_adapter.py` exports `capture_scene(context=None) -> SceneSnapshot` using current scene if no context; `preview_remove_loose_vertices(object_name: str, context=None) -> dict`; `apply_remove_loose_vertices(object_name: str, context=None) -> dict`. Preview is read-only. Apply duplicates object and mesh into current scene, removes loose vertices on the derivative only, leaves originals/selection/active object intact. Return source, derivative (apply only), removed_vertices, dry_run, and hidden=true (apply only). Derivatives start hidden in viewport and render so retained sources do not overlap. Reject linked, non-mesh, shape-keyed, animated, modified, parented, constrained or grouped (rig/weights) sources; reject no-op; source lookups restricted to active scene. No filesystem or network writes. Use bpy/bmesh only inside Blender.

`api.py` owned by root exports `dispatch(request: dict, adapter=None) -> dict`. Commands: `capabilities`, `scene.inspect`, `scene.validate`, `mesh.remove_loose_vertices`. Requests contain `schema_version='1.0'`, `request_id`, `command`, `params`. Unknown fields and invalid inputs fail closed; no eval/exec. Mutating command defaults dry_run=True. Results include ok, request_id, result or structured error. Blender adapter optional lazy import; plain Python capabilities work without bpy. Source geometry path is metadata-free: no private filesystem paths in snapshots.

UI owned by adapter worker in `ui.py`: validate profile, report summary, export report via explicit file picker, loose vertex derivative repair with undo and preview counts. Root owns package `__init__.py`, manifest, API/CLI, tooling/CI, README. Adapter worker owns `scripts/blender_smoke.py` and Blender adapter/UI integration tests. Core worker owns core and `tests/test_core.py`. Documentation worker owns roadmap/research/Sundown docs.
