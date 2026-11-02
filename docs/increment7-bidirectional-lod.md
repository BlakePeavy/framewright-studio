# FW-023: bidirectional LOD surface evidence

On 2026-10-30, a deliberately missing thin fin reproduced a gap in the original comparison: every remaining candidate vertex lay on the source, so candidate-to-source distance was zero. The retained foot and body also kept the same bounding box. Reverse source-to-candidate queries detected the missing feature. This increment improves geometric evidence; it does not approve a LOD or complete native runtime review.

## Contract and compatibility

The public `mesh.compare_surface` command (`framewright.lod.compare_surface` in code) keeps the same request (`source_name`, `candidate_name`, optional `max_samples`). The response now identifies schema `1.1` and contains:

- `candidate_to_source` and `source_to_candidate`: maximum and mean distance, sampled/omitted vertex counts, target triangle count, deterministic sampling rule, and the largest measured sample with its nearest surface point.
- `bidirectional`: the greater directional maximum and a combined mean weighted by sampled vertex count. This mean is not weighted by surface area.
- `bounds`: both complete evaluated world-space axis-aligned bounds and their largest component difference.
- `geometry`: valid triangle counts and degenerate triangles excluded from each target surface.

The original top-level `samples`, `candidate_vertices`, `coverage`, `maximum_distance`, `mean_distance`, and `direction` retain their candidate-to-source meanings. Consumers should explicitly select `bidirectional` for the combined measurement. Units remain Blender world units, without silently applying a scene unit conversion.

`max_samples` is a **per-direction** integer budget, default 10,000 and maximum 100,000. Each direction takes evenly distributed vertex indices against the other mesh's complete evaluated triangle surface. The BVHs and bounds still process complete geometry, so this bounds the query count, not total memory or elapsed time. Both evaluated object transforms are used, including different rotations and nonuniform scales. Empty, nonfinite or entirely degenerate world-space surfaces are refused; temporary evaluated meshes are removed on success and failure.

Even querying every vertex is not a continuous Hausdorff measurement: no face-interior query samples are taken, and details between samples can be missed. Loose vertices may contribute queries. Results describe the current evaluated frame/view layer; topology, UVs, material continuity, moving LOD transitions, shadows, and engine behavior need separate assessment. There is no universal distance threshold and `visual_acceptance` remains false.

## Test-first evidence

The new real-Blender tests first failed against the one-sided implementation because the reverse and combined fields were absent. After implementation, all **12 LOD tests** pass in Blender 5.2.1 LTS (`9e2066aef7ef`), along with **8 adjacent release-regression tests**. Ruff lint and formatting checks pass.

The synthetic source consists of a box, retained foot and 0.05-unit-thick fin. The candidate omits only the fin. It is an explicit construction fixture with touching components, not accepted production topology.

| Control | Observed result |
| --- | --- |
| Missing fin, unchanged bounds | Candidate → source maximum 0; source → candidate maximum 0.600000024; bounds difference 0 |
| Distinct asymmetric object transforms and nonuniform scale | Remaining surfaces still match; reverse maximum 1.2 within floating-point tolerance |
| Three samples per direction | Six queries total; separate omitted counts and partial-coverage disclosure |
| Source compared with itself | Both maxima zero within floating-point tolerance; identical bounds |
| Candidate shifted upward by 0.2 | Bounds difference 0.2 within floating-point tolerance |
| Evaluated source Array modifier | Actual evaluated vertex count reported, with a zero self-comparison |
| Invalid budget, nonfinite vertex, collapsed surface | Refused without leaking temporary meshes |

Tests also compare source/candidate coordinates, faces, UVs, transforms, selection, active object, frame and mesh identities before and after inspection. Existing derivative LOD/collision, source preservation and skinned-source refusal coverage remains intact.

## Retained silhouette and shadow review

The rendered evidence is [the local review sheet](../artifacts/lod-review/20261030T180732Z-5eba7601/index.html), with a [JSON report](../artifacts/lod-review/20261030T180732Z-5eba7601/report.json) and [editable Blender fixture](../artifacts/lod-review/20261030T180732Z-5eba7601/thin-feature-review.blend). This unique run contains 12 source/candidate PNGs across front, side and three-quarter views, plus one repeat-render control. Settings are 384 × 384, Cycles CPU, 32 samples, fixed seed 0, four threads, no adaptive sampling or denoising, Standard/None, exposure 0, gamma 1 and dither 0. File hashes and camera positions are in the report.

Inspection of the actual front silhouettes shows the fin plainly present on the source and absent on the candidate. The three-quarter clay/shadow images show the missing vertical panel and its changed shadow. The side silhouettes are pixel-identical because the body occludes the fin: a single view would miss this defect. Front silhouettes differ at 6,416 pixels by more than one encoded RGB code value; three-quarter silhouettes differ at 2,723. The repeated unchanged front silhouette has zero pixel difference. These pixel counts demonstrate this fixture's view dependence and are not quality thresholds. Shadow-image differences also include shaded surfaces and render sampling; they are not an isolated shadow-error metric.

The retained source/candidate fingerprint is identical before and after rendering (`02bad2cfaa32b775f2430b922fbe3b990a4e50698893b12f81b195c44a91875d`). Review scenes use separate copies. The saved fixture SHA-256 is `2b986767c3d85750d2c6754da40011ea63cc6e516f6102a149c7d4a72c562a75`. No game files, package receipts, or existing assets were changed.

Run the normal tests with:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_lod.py
```

Append `-- --render-review` to create another uniquely named review folder under `artifacts/lod-review`, or add `--output-dir <folder>` to select its parent. Rendering is optional; the 12 automated regressions run without it. Static synthetic views do not establish artist acceptance, temporal stability, or a native-engine pass.

The later [convex hull correction](native-derivative-handoff.md) adds a disconnected-part
regression and removes internal faces from collision derivatives. The retained native
probe still fails explicit LOD/collision assignment; the original art/runtime limits remain.
