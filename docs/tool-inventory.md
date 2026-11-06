# Tool inventory

The recommended **0.9.0 engineering preview exposes 59 API commands**. The current
checkout also reports 59 through `capabilities` (read-only check, November 5, 2026).
There are six quality profiles and six MCP wrappers with a configured Blender
worker, or three wrappers in pure-only mode. Wrappers and profiles are not
additional modeling or animation capabilities.

Use the sealed package and limits in [verification](verification.md) and the
[README](../readme.md). Its recorded aggregate has 84 stages, 71 Blender suites
and 830 standalone cases; these are historical correctness results, not art or
productivity scores. Development uses one standalone Python, currently 3.15.2;
Blender uses its bundled Python. Later checkout fixes are outside the sealed ZIP.

## Commands by workflow

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

## Scope and remaining work

The retained scope is asset checks, source protection, isolated jobs, export and
baking. Development is paused. See [supported scope and limitations](limitations.md).
A command's presence does not mean arbitrary production assets are supported.

- `model.build_prop` builds the supported workshop cabinet; `model.build_facade`
  builds the period shop bay. These are specific recipes, not general generators.
- Rig generation/binding wraps Rigify and native weighting with safeguards.
  Corrective shape creation requires caller-supplied vertex offsets.
- Review lighting currently accepts only supported owned static mesh/empty
  sources, up to 500 objects; rigged and animated objects are unsupported.
- Character deformation, reference fidelity, material/lighting quality and
  representative workload evidence remain incomplete. See the [roadmap](roadmap.md).
- Unreal/Sundown integration is deferred and excluded from Blender completion
  requirements. Earlier adapter/bridge work remains historical evidence.

Only operations in this inventory are exposed as Framewright commands. External
Blender scripts and client integrations are separate from the extension.
