# Blender integration evidence

Verified 2026-10-30 using installed Blender **5.2.1 LTS**, build `9e2066aef7ef`, in a separate `--background --factory-startup` process. No live session, game asset, user startup file or Blender preferences were changed.

Run from the repository root, substituting your Blender executable path:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python scripts/blender_smoke.py
```

## Red → green

1. Wrote integration fixture/tests before the adapter. Initial execution exited **1** with `ImportError: cannot import name 'blender_adapter' from 'framewright'`.
2. Implemented adapter and panel. **13 integration tests passed**; runner emitted `FRAMEWRIGHT_BLENDER_TESTS_OK tests=13 version=5.2.1 LTS` and exited **0**.
3. Added a regression requiring reports to retain effective budget/texture overrides. It failed with `KeyError: 'settings'` and exit **1**.
4. Recorded the effective profile in exported reports. **13 tests passed** again, exit **0**. Refactored repair preview to count edge participation without constructing a BMesh; tests remained green.
5. Added review regressions for hidden derivatives and explicit texture target disable/maximum controls. These failed with missing `hidden` result and missing `framewright_texture_max` property. Implemented the controls and hidden-by-default derivatives; **13 tests passed** again, exit **0**.
6. `ruff check` and `ruff format` passed for the adapter, UI and integration runner.

The tests cover base mesh/UV/material facts, fractional frame rate, actual deform bone weights, scene-referenced texture dimensions/color spaces/missing files, explicit main-thread and Object Mode guards, foreign-scene/no-op/unsupported-source refusal, source-preserving repair, unchanged selection, UI registration/cleanup and profile override reporting. Blender reported 0.018 seconds for the fixture tests; full process time was about 1.7 seconds. This is a small synthetic fixture measurement, **not a production asset performance benchmark**.

## Delivered boundary

The 3D View sidebar's **Framewright** tab provides profile selection, optional triangle/texture targets and maximum texture size, structural validation, an explicit JSON export file picker, repair preview and an undoable clean-derivative operator. Triangle/maximum overrides use `0` for the profile setting; the texture target uses `-1` for the profile setting, `0` to disable and a positive pixel count to override. Effective settings are retained in reports. Reports are labeled as the last validation snapshot; rerun after edits.

The adapter inspects each unique source mesh once per capture. Its triangle count uses ordinary polygon `n-2` tessellation, and modifier types are reported separately. It neither evaluates modifiers nor renders beauty frames. Texture metadata comes from images referenced by scene material/world node graphs; absent paths are reported by image name. A sequence's current file is checked, not every animation frame; UDIM missing-file checks cover listed tiles, while dimensions describe Blender's exposed image size rather than a complete per-tile budget.

Repair removes only isolated vertices with no incident edges. It creates a separate object and mesh, leaves source data/selection/visibility unchanged, and refuses linked/override, non-mesh, shape-keyed, animated, modified, parented, constrained or weighted/grouped sources. The derivative starts disabled in viewports and renders to prevent overlapping geometry; use the Outliner's viewport/render restrictions to reveal it for comparison. Preview allocates only edge-participation flags. API edits run in-process; Blender UI repair additionally uses Blender's undo system.

At this initial increment, no graphical panel screenshot, interactive undo roundtrip,
linked-library fixture, production benchmark, render/deformation review, exported
asset roundtrip or Unreal acceptance had been performed. The fixture emitted Blender
6.0 deprecation notices for `Material.use_nodes`; the initial adapter did not use
that setter. Later production modules do. Current evidence and remaining gates are
in [verification](verification.md), including [retained-asset measurements](increment11-production-corpus.md)
and [rendered handoff](increment10-exr-intake.md).
