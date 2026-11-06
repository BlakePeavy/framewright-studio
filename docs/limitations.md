# Supported scope and limitations

Framewright focuses on asset checks, source protection, isolated jobs, export and
baking. Version 0.9 is an engineering preview. Development is currently paused;
broader modeling and character-authoring features are retained but are outside
the active scope. Engine integration is not required to use the Blender extension.

## Compatibility

The extension manifest admits Blender 5.2.1 through 5.2.x. Recorded validation is
on Windows with Blender 5.2.1 LTS. Other platforms require their own verification.
Standalone development targets Python 3.15.2; extension code uses Blender's
bundled runtime. Query `capabilities` for the current command schemas and effects.

## Preservation and recovery

- Transactional repair is limited to supported loose-vertex repairs on local
  static meshes. Fingerprints and owned derivatives protect those operations;
  they do not protect arbitrary external scripts or every Blender edit.
- Repair plans and rollback authority are process-local. Reopening a file does
  not restore a previous process's repair authority.
- Workflows are non-atomic: earlier successful output can remain after a later
  failure. Retry protection is process-local and retains up to 128 cached runs.
- Worker isolation provides separate processes and explicit file paths, not an
  operating-system security sandbox. Linked resources can still be read with
  the caller's permissions. MCP clients must poll running jobs for completion.

See [transactions](increment2-provenance.md), [workflows](ai-api.md) and
[worker transport](increment3-ai.md) for the exact contracts.

## Asset coverage and quality

- Export and baking commands accept defined subsets of geometry and materials.
  Inspect their schemas and limits before running them on an asset. Higher
  resolution and sample counts increase cost without guaranteeing better results.
- Structural checks and sampled deformation/contact tests do not certify
  appearance, continuous motion, reference fidelity or production readiness.
- Retained builders are specific cabinet and shop-bay recipes. Rig generation
  uses Rigify and Blender weighting; correctives require caller-authored offsets.
- Review lighting accepts supported owned static mesh/empty sources, up to 500
  objects. Rigged or animated objects are outside that command's supported input.

See [baking](increment3-baking.md), [material atlases](increment16-material-atlas.md),
[export preservation](export-preservation.md) and the [command inventory](tool-inventory.md).
Choose a workflow for a concrete task and measure setup, rework and runtime;
command counts and passing tests alone do not establish productivity gains.
