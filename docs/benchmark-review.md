# Local review kit and benchmark candidates

The concrete review kit is [openable here](../artifacts/review-kit/20261030T162055Z-bfbd462d/index.html). It is local, ignored by Git, and was built in a dedicated background Blender 5.2.1 LTS process. It provides editable sources and technical evidence for review; independent AAA benchmark selection and artistic acceptance remain pending.

## Delivered artifacts

- [Editable full Blender kit](../artifacts/review-kit/20261030T162055Z-bfbd462d/framewright-review-kit.blend): cabinet, facade, original appended anatomy reference, separate lighting-review scenes and named cameras. Saved with normal full-file saving, then reopened in a separate Blender process.
- [Manifest](../artifacts/review-kit/20261030T162055Z-bfbd462d/manifest.json): 30 cabinet parts, 27 facade parts, builder parameters, reference source/hash/license evidence, export receipts and render hashes.
- Four staged exports: cabinet and facade in both GLB and FBX, each with a separate receipt. [Cold verification](../artifacts/review-kit/20261030T162055Z-bfbd462d/cold-verification.json) passed exact object scope, UV presence and evaluated world bounds within 0.2 mm for all four files. Rendered export materials and native engine import remain unverified.
- Six 512×512 Cycles/24-sample views per constructed asset: matching front/three-quarter cameras under neutral, day and dusk recipes.
- Four neutral clay anatomy-reference views: front, side, back and three-quarter. Source multiresolution detail is retained. These are reference inspection images, not a generated character or an accepted production character.

Editable kit SHA-256: `058244e80154be7a5c6382c7751763ead3b6a5c68913a26dd13ec109a3b784d0` (25,207,673 bytes).

The earlier run `20261030T161939Z-b317d357` is retained. Visual inspection found its anatomy framing too distant and clay highlights too bright. The selected run above uses closer 70 mm comparison cameras and reduced neutral light energy; the rendered anatomy is more readable. This is a review-presentation correction, not a geometry change or art approval.

## Independent reference provenance

The selected reference is `Body Male - Realistic` from Blender Studio/community **Human Base Meshes v1.4.1**, listed on the [official Blender demo-files page](https://www.blender.org/download/demo-files/) as CC0. The bundle's embedded README also states that all provided assets are public domain under CC0. A separate embedded `License` text refers to the unrelated Rain Rig and CC-BY 4.0; both source texts are retained under the kit's `reference/` directory rather than hiding that discrepancy.

- Original ZIP: `artifacts/reference-candidates/human-base-meshes-v1.4.1.zip`.
- Original ZIP SHA-256: `811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515`.
- Exact extracted member: `human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend`.
- Extracted `.blend` SHA-256: `3c121505651140ceb4d69fd1d8923f7788ffadd81672f5be14845a5f2c75c137`.
- Actual source inspection: body `GEO-body_male_realistic`, 10,582 base vertices, Multires level 3; two separate eye meshes, 546 vertices each. Original dimensions are approximately 0.883 × 0.292 × 1.690 m.
- The script extracts only the pinned member after checking the ZIP hash and member path/type/size. It appends selected datablocks with automatic script execution disabled. Original ZIP/extracted source bytes remain unchanged.

## What the images establish

The cabinet and facade have visible construction depth, separate hardware/opening parts and readable material regions. Their surfaces remain early procedural studies: wood grain/aging, physical joinery, facade interior/glass context and licensed period-reference matching need more work. Their current appearance is not the target quality authority.

The external anatomy asset supplies a useful independent body/topology reference. It does not establish finished skin, hair, costume, facial performance, rig/deformation, interaction or animation quality. A complete AAA benchmark kit still needs approved final-surface, motion and scene/lighting examples plus shot-specific acceptance. Sundown's unfinished art remains excluded as the visual benchmark.

All 45 local review-sheet links were checked; only the official source link leaves the local kit. No assets were imported into Sundown and no files were published.

## Reproduce

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/build_review_kit.py -- --self-test
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/build_review_kit.py -- --output-dir artifacts/review-kit --resolution 512 --samples 24
```

Each run creates a fresh UTC/UUID subdirectory without overwriting previous evidence. The extraction test covers traversal rejection, hash mismatch and no-overwrite behavior. The build performs the actual renders/full-file save and launches a separate cold verifier. It needs the already-downloaded pinned reference ZIP; no provider credits, network downloads or live editor state are used.
