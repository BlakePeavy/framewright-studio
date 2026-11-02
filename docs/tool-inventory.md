# Tool inventory

The verified **0.8 engineering preview exposes 59 API commands**. The retained
**0.7 preview exposes 58**; `surfaces.bake_material_atlas` is the added command.
There are also **six quality profiles** and **six MCP wrappers when a Blender
worker is configured**, or **three wrappers in pure-only mode**. MCP wrappers
provide access to the API; they are not additional modeling or animation commands.

The 0.8 aggregate passes all 82 stages, with 812 tests on each Python version and
69 Blender suites. Actual 1K/8K atlas and cold Blender/GLB/FBX material handoffs pass
their declared checks. These are bounded engineering results, not AAA artistic acceptance.
The native import compiler/entrypoint are separate offline/editor utilities with
passing contract tests; their actual Unreal execution remains unverified.
Use the exact package identified in the [README](../readme.md).

## Commands by workflow — verified 0.8 preview

| Workflow | Count | Exact command names |
|---|---:|---|
| Discovery, settings and orchestration | 3 | `capabilities`, `settings.migrate`, `workflow.run` |
| Scene inspection and budgets | 3 | `scene.inspect`, `scene.validate`, `scene.resources` |
| Mesh diagnostics and repair | 3 | `mesh.inspect_evaluated`, `mesh.compare_surface`, `mesh.remove_loose_vertices` |
| Modeling derivatives and construction | 4 | `model.create_lod`, `model.create_collision`, `model.build_prop`, `model.build_facade` |
| Materials and baking | 5 | `surfaces.inspect`, `surfaces.create_pbr_material`, `surfaces.assign_material`, `surfaces.bake_normal`, `surfaces.bake_material_atlas` |
| Planned repair and rollback | 4 | `repair.plan_remove_loose`, `repair.apply_plan`, `repair.cancel_plan`, `repair.rollback` |
| References, provenance and export | 9 | `asset.reference_create`, `asset.reference_add`, `asset.reference_intake`, `asset.reference_board`, `asset.manifest_create`, `asset.manifest_validate`, `asset.manifest_derive`, `asset.verification_record`, `asset.export` |
| Rigging, weights and correctives | 8 | `rig.inspect`, `rig.fit_metarig`, `rig.generate`, `rig.bind_mesh`, `rig.normalize_weights`, `rig.sample_deformation`, `rig.corrective_shape`, `rig.activate_corrective` |
| Animation and sampled contacts | 9 | `animation.inspect`, `animation.retarget`, `animation.cleanup`, `animation.bake`, `animation.bake_shape_keys`, `animation.bake_bbone_skin`, `animation.contacts`, `animation.surface_contacts`, `animation.skin_contacts` |
| Explicit triangle regions | 2 | `contacts.describe_region`, `contacts.inspect_regions` |
| Poses, shapes and secondary motion | 7 | `pose.capture`, `pose.apply`, `shapes.apply_values`, `secondary.inspect_bindings`, `secondary.attach_rigid`, `secondary.create_cloth_proxy`, `secondary.bake_cloth` |
| Lighting and review scenes | 2 | `lighting.create_review`, `lighting.create_interior_fixture` |
| **Total** | **59** | |

See the [AI API guide](ai-api.md) for requests, previews, output bindings, worker
setup and limitations. `capabilities` returns each command's current input schema,
effects and Blender requirement. Commands have explicit supported subsets; their
presence does not mean arbitrary production assets or every Blender feature are supported.

## Profiles and MCP access

The six profiles are `studio_static`, `sundown_static`, `animation_scene`,
`lookdev_scene`, `cinematic_8k` and `realtime_high`. They are configurable validation
presets, not independent tools or artistic quality certifications.

Pure-only MCP exposes `framewright_capabilities`, `framewright_manifest_validate`
and `framewright_workflow_validate`. Configured worker mode adds
`framewright_submit_job`, `framewright_poll_job` and `framewright_cancel_job`.
Blender work runs in owned background jobs with explicit inputs and output locations.

## Remaining development

The isolated **0.9 candidate still exposes 59 commands**. It adds configurable
atlas spatial sampling (default 16), preserves long FBX object identities and
fixes cold-hidden static export transforms. Its 84-stage aggregate and both
830-test Python matrices pass. New 8K validation and promotion remain open;
this inventory's released counts and install recommendation remain 0.8.
See [sampling](atlas-sampling.md) and [export scope](export-preservation.md).

The [roadmap](roadmap.md) tracks production outcomes, so remaining work does not
translate into a fixed count of additional commands. The main open areas are:

- **Asset and motion quality:** refine human shoulder, hip and knee deformation;
  broaden reviewed facial, hand, secondary-motion, environment and lighting evidence.
  Numeric checks and rendered fixtures still need independent artistic acceptance.
- **Broader handoff coverage:** verify more production rigs, materials, clips,
  simulations and export combinations against their declared tolerances and limits.
- **Native Sundown integration:** validate the provisional native import/staging adapter in Unreal, then
  complete static and character pilots in the game with matched visual and motion review.
- **Production performance and support:** measure native CPU/GPU time, residency,
  draw calls and streaming on pinned game builds/hardware; broaden representative
  workloads and supported environments, and complete release/acceptance checkpoints.

Framewright supplies editable, bounded production operations and AI-readable
workflows. It does not currently turn a text prompt into a finished AAA asset,
scene or animation. The carrier cinematic was authored with Blender scripts;
Framewright supplied inspection, validation and resource reporting.

The unreleased native adapter additionally requires the editor-only
[FramewrightNativeBridge](native-texture-readiness.md) for owned texture
compilation readiness and version 0.2.0's [full-precision import helper](native-uv-precision.md).
It adds no AI commands and is separate from the Blender ZIP.
