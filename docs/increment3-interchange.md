# Scoped GLB/FBX handoff

`framewright/interchange.py` provides `export_asset(params, context=None)` for a bounded FW-050/FW-070 foundation. Tested locally on Blender 5.2.1 LTS/Windows. Both GLB and FBX exports were reimported in separate clean Blender processes. No Unreal/game files or live Blender sessions were changed.

## Contract

```json
{"object_names":["AssetRoot","AssetRig","AssetMesh"],"directory":"existing staging directory","filename":"asset_v01","format":"GLB","include_animation":true,"profile":"generic","dry_run":true}
```

`directory` and nonempty `object_names` are required; other defaults are `filename="asset"`, `format="GLB"`, `include_animation=false`, `profile="generic"`, `dry_run=true`. `format` also accepts `FBX`; `profile` also accepts `sundown`. The Sundown profile records the intended Unreal destination without applying the legacy Unity coordinate conversion or importing native content.

Names must refer to meshes, empties or armatures in the current scene. Parent and armature dependencies must be explicitly included. Skinned meshes must be parented to their selected armature. Constraint rigs, drivers, instances and modifiers outside the supported whitelist must be baked/realized separately before export. Supported modifiers: Armature, Bevel, Weighted Normal, Subdivision Surface, Decimate, Triangulate, Solidify and Smooth. These restrictions keep the initial handoff scope explicit; they do not imply all Blender export features are implemented.

Preview returns source facts/settings/proposed output paths without writing. Apply duplicates objects and mesh/armature data into a disposable scene, remaps parents/skin targets, uses explicit selection plus active-scene scope for GLB, and restores scene, view layer, frame/subframe, selection and active object. Exported nodes carry `framewright_source_name`; their temporary names are mapped in the receipt.

The destination must already exist. Filenames are safe basenames without extension. Existing output or receipt files are refused. Export occurs inside a temporary staging directory before exclusive creation of `<filename>.glb` or `.fbx` and `<filename>.receipt.json`. Failure removes only newly created owned output and temporary data. The receipt records source geometry/UV/weights/pivots/skeleton facts and fingerprints, format/settings, output SHA-256, Blender version, timing/units and sampled normalized-time world bounds.

Export generation, cold reimport, native import, world placement and visual acceptance are independent status fields. The function marks only export generation. Procedural material graphs generate a bake/review warning. Texture/render parity, exact topology when exporters split/triangulate vertices, complex morph/NLA/rig cases, full surface comparison and native Unreal acceptance remain separate.

## TDD and evidence

- Initial red: tests failed because the module did not exist.
- The first implementation passed both format roundtrips for asymmetric geometry, two material slots, UV data, two-bone skin and one second of bone motion.
- A selected-object fixture in another scene exposed exporter changes to `Window.scene` despite a context override. The regression failed source-context preservation. The exporter now explicitly restores the original window scene/view layer before deleting staging data.
- Cold GLB import creates bone-display helper meshes and can change local mesh coordinates while preserving world geometry. Checks identify helpers through actual pose-bone custom-shape references and verify UV-to-world-surface mapping, rather than assuming unchanged local storage.
- Final: **5 tests pass**, including both independent GLB/FBX import processes, exact exported asset scope with the other scene excluded, parent pivot matrix, asymmetric normalized-time bounds, actual UV coordinates/material usage, skeleton hierarchy/weights, source preservation, overwrite refusal and injected-failure cleanup. Lint/format checks pass.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_interchange.py
```

The cold processes emit `FRAMEWRIGHT_COLD_ROUNDTRIP_OK` receipts per format. Tests use temporary preferences/directories and remove fixture files. Bounds comparisons allow 0.2 mm tolerance; that is fixture precision evidence, not a universal production tolerance or proof of visual quality. Native-engine import and reference-based art approval remain open.
