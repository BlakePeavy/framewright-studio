# Rendered surface and material fixtures

`scripts/test_surface_render_parity.py` measures actual saved render pixels for
FW-022/050/052. It exercises the production normal baker and scoped exporter,
then imports each exported asset in a separate factory-startup Blender process.
It never opens a live editor, the reference-human library or the game project.

## Reproduce

```powershell
& $Blender --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_surface_render_parity.py
```

The default creates a unique `artifacts/surface-render-parity/<UTC-UUID>/` run.
An explicit `-- --output <new-directory>` must also name a new directory.
The folder contains seven rendered PNGs, the real baked normal EXR, the portable
color PNG, exported GLB/FBX files and receipts, cold-process logs, imported
material metadata and `report.json`. Cold processes have 60-second deadlines.

## Measurements and controls

The normal fixture compares a smooth 4,608-triangle shallow wave with a
two-triangle plane using its actual 128-pixel tangent-normal bake. Each is
rendered independently with matching orthographic camera, sun and world light.
The material fixture is a smooth UV sphere with a portable file-backed color
texture, scalar roughness 0.28 and scalar metallic 0.65. GLB and FBX imports are
rendered in fresh processes using the same stage.

All renders use 128 × 128 pixels, Cycles CPU, 48 samples, seed 0, no adaptive
sampling or denoising, Standard view, None look, exposure 0 and gamma 1.
Differences are computed from saved RGBA8 PNG RGB values in the fixed central
20–80% region. This is an encoded-image measurement; it is not a linear-radiance
or perceptual color-difference metric. The region excludes the wave boundary,
where a normal map cannot reproduce the high mesh's silhouette or parallax.

Two deliberate negative controls pass through the same renderer and metrics:

- Remove the baked Normal connection on a copied material.
- Remove the color texture connection and substitute a bright green color.

Both controls must create a minimum measurable error and must be rejected by
the same assertion used for the candidate. The normal limit is the smaller of
0.01 MAE and 65% of removed-normal error. The portable-material limit is the
smaller of 0.03 MAE and 20% of wrong-color error. These fixture-specific bounds
are intentionally not an arbitrary asset quality score.

Both GLB and FBX exceeding their calibrated limit fail this portable-fixture
test. Each format reports its status, measurements and imported
roughness/metallic/base-color linkage. Source geometry, transforms, smoothing,
UVs, material graphs/defaults and image pixels/color spaces are hashed before
and after processing; source changes fail the test.

## Observed evidence

Blender 5.2.1 LTS on 2026-10-30:

| Comparison | Mean absolute RGB error | Result |
|---|---:|---|
| Wave high → baked low | 0.000299624 | Below 0.00998670 calibrated limit |
| Wave high → removed normal | 0.0153642 | Rejected negative control |
| Source PBR → cold GLB | 0.000000441 | Within fixture tolerance |
| Source PBR → cold FBX | 0.000004850 | Within fixture tolerance |
| Source PBR → wrong color | 0.200419 | Rejected negative control |

Both imports retained the fixture's scalar roughness/metallic and linked base
color. Exact source hashes matched. The final rendered PNGs were visually
inspected: wave shading is visible on the bake and missing in the negative
control; the imported patterned metallic sphere matches the source, while the
color control is visibly green.

Retained passing run: `artifacts/surface-render-parity/20261030T165230Z-f473e445/`.
The strengthened assertion requiring both formats was reverified in
`artifacts/surface-render-parity/20261030T170557Z-4d711510/`.
Independent negative executions with `-- --inject-corruption normal` and
`-- --inject-corruption color` both exited 1 at their respective parity
assertions before the healthy execution exited 0. Their logs are
`artifacts/surface-render-parity/red-normal.log` and `red-color.log`; the healthy
execution is `green.log`. Negative modes deliberately substitute the saved
corrupt measurement as the candidate and never relax the acceptance check.

## Boundaries

This is bounded Blender-to-Blender evidence for a shallow single-atlas normal
fixture and portable opaque Principled material subset. It does not cover
normal seams, texture-driven roughness/metallic, glass/transmission, displacement,
UDIMs, custom node graphs, 8K renders, texture compression/mips, temporal
stability, Unreal rendering or independent artistic acceptance. Existing bake
preflight and cage tests cover their separately documented geometric limits.
The result does not certify AAA quality or universal FBX/glTF material fidelity.
