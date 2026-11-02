# Atlas spatial sampling

`surfaces.bake_material_atlas` now accepts integer `bake_samples` from 1 through 64,
default **16**. The previous implementation baked one sample. Use explicit
`"bake_samples":1` when that speed/aliasing tradeoff is appropriate. Booleans,
floating-point numbers and out-of-range values fail before loading the backend.
This affects shared material atlases only; `surfaces.bake_normal` is unchanged.

The owned CPU bake scene uses the requested Cycles sample count, seed zero,
animated seed off, adaptive sampling off and denoising off. Applied results include
`effective_sampling`, read from that scene. Preview reports the requested/default
count without claiming execution. Source scene settings, geometry, UVs, materials,
images, pivots, budgets and failure cleanup retain their existing contract.

More samples increase shading work. The existing image-memory estimate is neither
a runtime bound nor an OS/GPU memory cap. Sixteen is a bounded default supported by
the fixtures below, not a universally optimal setting or AAA-quality certification.
Higher texture resolution, sample count and artistic fidelity remain separate.

The [combined public 1K/8K handoff](../artifacts/verification/public-8k-default16-0.9.json)
now passes with refined editable wood. Default16 8K takes 41.26 minutes for the
whole flow, including 37.45 minutes baking; peak working set is 15.49 GiB.
All six cold/render/map workers pass the unchanged 384px review gates. These
measurements establish transport at those views, not full-resolution art acceptance.

## Evidence

The installed Blender build's [bake initialization](https://github.com/blender/blender/blob/9e2066aef7ef/intern/cycles/kernel/integrator/init_from_bake.h)
jitters samples inside a texel after the first sample, with triangle-boundary limits.
The [independent small probe](../artifacts/development09/atlas-aa/artifacts/supporting-proof/installed-build-probe.json)
measured both EMIT and NORMAL responses. The public-command regression adds actual
Smart Project/packing and checks a sine pattern against analytically integrated
source-UV colors over each output texel, excluding triangle boundaries.

The old public default genuinely failed its aliasing gate (MAE 0.288501). The new
default gives 0.025322 over 3,136 interior texels; explicit one sample reproduces
the old PNG hashes. Repeated default bakes produce identical four-map PNG bytes.
Samples 1/64, actual per-pass settings, nontrivial bump-normal changes, preview,
source-scene preservation and a second-map packing failure are also checked.
The [public test report](../artifacts/development09/atlas-aa/artifacts/atlas-sampling/report.json) retains maps,
analytic arrays and hashes. Changed normal samples do not prove angular accuracy.

An earlier controlled 1K refined-wood experiment held camera, exposure and image
gates fixed while overriding sampling on an owned temporary scene:

| Samples | Grain-detail RGB MAE | P95 | Bake/pack time | Existing gate |
|---|---:|---:|---:|---|
| [1](../artifacts/development09/atlas-aa/artifacts/supporting-proof/samples1/report.json) | 0.009665 | 0.023529 | 24.10 s | Fail |
| [16](../artifacts/development09/atlas-aa/artifacts/supporting-proof/samples16/report.json) | 0.004153 | 0.011765 | 33.95 s | Pass |

Those timings are fixture observations, not guaranteed cost multipliers. The
experiment motivates the default; it is not a public-path refined-cabinet cold
handoff. That integration follows the separate exported-name repair. No image
threshold was relaxed, general joining optimization introduced, source artwork
promoted or native engine launched.

Run `scripts/test_atlas_sampling.py` in a fresh four-thread background Blender
worker with owned TEMP/TMP. It is included in `scripts/check.py`; related atlas,
schema, image-packing, review and cold-handoff results are recorded in this
candidate's final sampling receipt.

The unchanged original-cabinet 1K harness passed with default 16: source-to-atlas
RGB MAE 0.000170/0.001049, all cold Blender/GLB/FBX checks and the white-loss control
passed at their existing gates ([report](../artifacts/development09/atlas-aa/artifacts/material-atlas/20261101T172218Z-089b468f/report.json)).
The 33 targeted Blender tests and 92 pure/API tests pass. A broader Python run
passed 825 tests and encountered three sandbox hard-link denials; all three passed
unchanged in a host-permission rerun. Two optional Blender-worker smoke tests were
skipped because their environment variable was unset. This is targeted candidate
verification, not a complete release aggregate or new artistic acceptance.

[Final receipt](../artifacts/development09/atlas-aa/artifacts/sampling-development-receipt-final.json) pins the exact
baseline, changed-file manifest, runtime, scripts, tests and retained evidence.

These closed-study records are copied byte-for-byte under `artifacts/development09`.
The [retention receipt](../artifacts/evidence-retention-0.9.json) distinguishes
copied evidence from hashed external reproduction inputs; this is not a standalone
reproduction archive. The combined 0.9 aggregate and both Python matrices now pass
as recorded in [verification](verification.md); actual 8K default-16 validation also passes.
