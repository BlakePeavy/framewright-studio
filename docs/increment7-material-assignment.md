# Material assignment and visible review copies

`surfaces.assign_material` connects standalone PBR creation to an editable mesh derivative. It accepts required `object_name`, `material_name`, and `slot_indices`, plus optional `dry_run` (default `true`). The slot list contains 1–128 unique integers from 0 to 127. Names resolve exactly; the mesh must be unique in the active scene and the material unique among loaded material datablocks. Object Mode and Blender's main thread are required.

Preview validates without allocating objects, meshes or materials. Application creates a separate object and mesh, retains the source parent/inverse, transforms, vertex groups, armature modifiers, shape geometry, UVs and polygon indices, and changes only the selected material pointers. The derivative starts hidden in viewport/render. Existing `OBJECT` versus `DATA` slot links remain intact: an object-linked override changes only on the copied object, and a data-linked pointer changes only on the copied mesh. Other slots and shared source-mesh users retain their original pointers. Empty slots allow only `[0]`, which appends one material slot. Out-of-range selections, inconsistent polygon indices, linked source object/data and library overrides reject before allocation.

The existing material is referenced, not edited or cloned. Its nodes, texture images and shader settings remain untouched; normal Blender reference counts increase. Skin/parent/action references are retained rather than copied into a new rig, and modifiers may influence evaluated material use. This command does not unwrap UVs, guess assignments or claim shader/visual suitability. It performs no file or network I/O. Failed assignments remove only the new derivative, including after a partial slot replacement; existing sources and prior derivatives remain.

The command is registered as a scene mutation, so applied background jobs require saved derivative output under the existing worker/batch rules. Results include selected slot changes, `source`, `material`, and, after application, `derivative` and an assignment UUID. Repeating a request allocates a distinct Blender name; it does not overwrite an earlier derivative. Workflow replay behavior remains governed by the existing workflow run ID.

## Workflow boundary

An actual background-Blender test executes `model.build_prop → surfaces.create_pbr_material → surfaces.assign_material → lighting.create_review`. Material and derivative names are bound from earlier command results. The source cabinet material remains unchanged; the review copy uses the actual decoded texture material.

This exposed a prior review issue: `lighting.create_review` inherited hidden viewport/render flags from a hidden derivative. The owned copies now explicitly clear `hide_viewport`, `hide_render` and per-view-layer hiding in the new review scene, including explicitly selected parent/dependency empties. Originals retain their hidden state. The existing review tool remains restricted to owned static meshes/empties; material assignment itself also supports meshes with retained skin state, but does not broaden that static-review subset.

## Test-first evidence

- Initial command test failed with missing `surfaces.assign_material`; initial Blender test failed with missing `material_assignment` module. Logs: `artifacts/material-assignment-python-red.log`, `material-assignment-blender-red.log`.
- The real workflow and hidden-parent review tests then failed because review copies stayed hidden. `material-assignment-review-red.log` records both failures before the visibility fix.
- **15 Python command/schema tests** and **10 actual Blender 5.2.1 LTS tests** pass. Logs: `material-assignment-python-green.log`, `material-assignment-blender-green.log`.
- Blender coverage includes mixed data/object links, shared meshes, parent inverse, armature/weight and shape retention, invalid/empty slots, partial-failure cleanup, unique repeated derivatives, actual local/linked name ambiguity, linked object/data and overrides, review visibility, and the complete command workflow.
- Final affected regressions passed **41 Python tests with 32 subtests**, plus **10 material-assignment and 16 existing production-asset Blender tests**. Logs: `artifacts/material-assignment-python-regression.log`, `material-assignment-regression-test_material_assignment.log`, and `material-assignment-regression-test_production_assets.log`. Ruff formatting and lint passed for the changed files.

These are technical fixtures. Material appearance, UV scale, native parity and artistic acceptance remain independent review work. No live editor or Sundown asset was changed.
