# Baseline research and gap register

Reviewed 2026-10-30. Development baseline: installed Blender 5.2.1 LTS on Windows. Pin tested releases in the compatibility record; do not infer full compatibility from a manifest minimum or an API page's moving `current` alias.

The user clarified that Sundown art remains in development and must not set the quality bar. Framewright therefore targets independent AAA-level references and review, with configurable cinematic 8K and realtime profiles. There is no single universal AAA polygon, texture or resolution standard. These profiles organize checks; artist approval, reference fidelity and measured shot/runtime performance remain separate.

## Supported design choices

| Official source | Finding | Framewright consequence |
|---|---|---|
| [Blender 5.2 extension creation](https://docs.blender.org/manual/en/5.2/advanced/extensions/getting_started.html) | Extensions package an add-on with a TOML manifest and explicit metadata/permissions | Produce and validate an extension ZIP; keep packaged runtime dependencies minimal; add permissions only for implemented needs |
| [Blender Python threading guidance](https://docs.blender.org/api/current/info_gotchas_threading.html) | Blender's Python integration is not generally thread safe | Keep `bpy` access on the Blender main thread; design future network/inference jobs as isolated workers and pass structured results back |
| [Blender 5.2 Rigify introduction](https://docs.blender.org/manual/en/5.2/addons/rigify/introduction.html) | Rigify automates controls/bones; skinning still requires a separate workflow | Integrate established rig tools; focus added work on fitting, skinning, compatibility and deformation evidence |
| [Blender 5.2 Rigify index](https://docs.blender.org/manual/en/5.2/addons/rigify/index.html) | Rigify provides modular components and extension points | Prefer an adapter over a second competing rig generator |
| [Blender simulation nodes](https://docs.blender.org/manual/en/latest/physics/simulation_nodes.html) | Geometry Nodes simulations have timeline caches and disk-bake workflows | Future simulation delivery must track cache dependencies and bake/replay state; do not present a viewport result as portable game simulation |
| [Blender glTF documentation, historical 3.6 reference](https://docs.blender.org/manual/en/3.6/addons/import_export/scene_gltf2.html) | glTF triangulates meshes and has defined material/animation representations | Treat interchange as an explicitly tested conversion; recheck behavior/settings against installed 5.2 before implementing export |

Extension, threading and Rigify 5.2 pages were fetched directly after the web reader could not open them. The glTF source above is explicitly historical: its settings are not the current implementation contract. Actual installed API behavior and fresh-process fixtures take precedence for development.

## Gaps to address

This register identifies production workflow gaps and documented Sundown failure modes. It is not a claim that Blender lacks modeling, rendering, rigging or animation capabilities, or that other studios' proprietary tools have been benchmarked.

| Domain | Gap / evidence | Add-on response | Proof required |
|---|---|---|---|
| AI operation | GUI operations and arbitrary scripts offer weak machine-readable intent, scope and recovery | Versioned typed capabilities, stable diagnostics and explicit plans; later bounded transport | Contract tests, malformed request tests, source preservation and replay |
| Modeling | Valid geometry can still have wrong silhouette, missing construction, fused anatomy or bad surface topology | Separate mechanical preflight from reference/landmark and rendered comparison workflows | Original/derivative comparisons tied to exact source hashes |
| UV/materials | Successful bake/export can lose UV semantics, layer thickness, channel mapping or color/data encoding | Portability diagnostics, scoped baking and cold roundtrip checks | Exact mapping evidence plus neutral-light appearance review |
| Rigging | Normalized weights can still create spikes, pinching, broken accessory binding or poor joint placement | Rig-profile contracts and evaluated pose harness with bounded repairs | Whole required pose range and protected-region invariants |
| Animation | A copied/retargeted action can preserve foot sliding, bad contacts or discontinuities | Clip/time metadata, contact diagnostics and portable bake tests | Full relevant clips in Blender and native playback |
| Lighting | Extra lights/bloom do not guarantee material separation, readable exposure or stable reflections | Repeatable neutral/art-light recipes with matching cameras and render metadata | Day/dusk, interior/exterior and motion review |
| Scene scale/performance | Object/triangle counts alone do not measure draw sections, texture residency or GPU time | Content accounting and explicit native performance handoff | Matching-build CPU/GPU/memory/temporal evidence |
| Pipeline | Export/import success is often mistaken for finished in-world quality | Independent status gates and reproducible source/export/native records | Fresh-process reimport plus actual game placement review |
| Quality targeting | Source texture resolution can be mistaken for visible production quality | Flexible 8K/source-resolution advice tied to asset class, texel density, shot coverage and independent benchmarks | Actual silhouette/anatomy/deformation, physically credible surfaces, calibrated light/color, composition and motion review |

## Baseline limits and investigation rules

- The first increment contains deterministic assistance, not a trained generative model, cloud provider, autonomous art director or full studio pipeline.
- Use native Blender features where appropriate. Build an adapter or quality guard only after a reproducible workflow gap is identified.
- Unsupported checks must be reported as unsupported/unknown rather than silently treated as passing. Sampling limits and intentional open surfaces need explicit policy.
- Treat model generation output as a candidate. Keep reference provenance, license terms, anatomy/topology review, UV/material checks and artist acceptance separate.
- Never force every map to 8K or upscale low-detail inputs to satisfy a dimension check. Preserve useful high-detail source maps and derive runtime formats from coverage and measured budgets; record resolution and quality independently.
- Add performance budgets only after representative scenes and target hardware are measured. Future acceleration should preserve correctness and cancellation before optimizing throughput.
- Revisit version-dependent APIs when implementing each story, especially layered actions, extension packaging, export options, render settings and Geometry Nodes. Maintain small Blender fixtures that exercise the real APIs.

The detailed work order and completion gates are in [roadmap.md](roadmap.md). Game-specific evidence and constraints are in [sundown-integration.md](sundown-integration.md).
