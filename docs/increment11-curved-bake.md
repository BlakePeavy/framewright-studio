# Curved normal baking and source-preservation review

The 0.5 development work adds a curved, single-atlas bake fixture with an explicit
matching cage and a UV seam facing the review camera. This extends the prior
shallow-plane evidence; it does not certify arbitrary cages, all texels, silhouettes
or native rendering.

## Source-preservation fix

Independent tests reproduced an unrelated authored light energy changing from
123.456001 to its keyed value 12.319336 after both successful baking and an injected
bake failure. The original scene stayed at frame 2.25 throughout; the final
unconditional `frame_set` unnecessarily reevaluated it. The baker now refreshes
source time only if it actually changed.

The same review showed a registered dependency-graph callback changing the light
to 999 even during preview. Both preview and apply evaluate geometry, so both now
reject active frame/dependency-graph callbacks before evaluation. Registered
callbacks remain installed and untouched. These limits do not promise restoration
of arbitrary third-party effects.

`scripts/test_bake_preservation_review.py` first failed all three tests (four
assertions including preview/apply subcases), then passed. The nine existing
baking tests also pass, including cage topology, projection, memory and UV guards.
Logs: `artifacts/bake-preservation-red.log`, `bake-preservation-green.log`, and
`bake-existing-0.5.log`.

## Curvature, seam and cold image evidence

The final 0.5 aggregate [review](../artifacts/curved-bake/20261030T200225Z-f622e817/index.html)
contains the detailed cylinder, baked low cylinder, removed-normal control and
cold-reopened baked low, plus a separately damaged seam. The high sidewall has 256 circumferential segments and
64 height divisions with periodic radial detail. The low/cage share ordered
64-segment, two-division topology. The two end boundaries are intentionally open.
The bake is 256² tangent +X/+Y/+Z, with an explicit outward cage. All 256 sampled
centroid projection rays hit, and more than 99% of pixels pass the normal-length
check; those counts do not prove intended per-texel correspondence.

All five views use 256² CPU Cycles, 48 samples, seed 0 and Standard/None exposure 0.
The central 20–80% region excludes silhouette/parallax and cylinder ends. A second
47–53% horizontal strip crosses the UV seam.

| Region | High → baked low RGB MAE | High → removed normal RGB MAE |
|---|---:|---:|
| Interior | 0.00191530 | 0.0283432 |
| Seam strip | 0.000493827 | 0.0223965 |

Both healthy comparisons pass the fixed fixture ceiling and relative removed-normal
limit. The deliberately damaged comparison is rejected by the same assertion.
An additional control reverses tangent X only in the first/last eight texture
columns on disposable image/material/mesh copies. Its seam-strip MAE is 0.038158,
above the 0.015 fixture limit; the correct bake remains at 0.000493827. Its actual
render shows the changed seam shading, and the same assertion rejects it.
Source/low/control images were inspected: the bake retains the broad curved detail
and the control loses it. The high silhouette differs, as expected for geometry
detail represented only by normals; it is explicitly outside the comparison.

The editable `.blend` retains the packed normal map. A fresh factory-startup process
with auto-execution disabled reproduced the central rendered pixels exactly (MAE
and maximum difference 0), and source geometry/UV/material fingerprints match.
The receipt retains source/code/image hashes, parameters, projection and pixel
evidence. Selected blend SHA256 is
`7bb90b98d3c6e5bc6211f1e687cdec450bf6d9075bc59d714ca6fb0b37a82bef`.
All five selected images were inspected. This run uses the final
[physical-unit, material-assignment and dependency corrections](increment11-bake-units.md).
These are fixture observations, not physical calibration or AAA approval.

```powershell
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_bake_preservation_review.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_curved_bake.py
```

Append `-- --inject-removed-normal` for an intentionally failing candidate. Its
separate execution exited 1 at the same interior assertion (MAE 0.0283432 exceeds
0.015); `artifacts/curved-bake-negative-0.5-final.log` retains the rerun against
the final unit-corrected baker. The healthy test
also asserts rejection of the measured negative control in both regions.
