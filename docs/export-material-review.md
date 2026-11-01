# Export material review and preservation fixes — 2026-10-30

Independent review of `export_materials.py`, `interchange.py`, scalar staging
tests and the four-map rendered handoff found three reproducible defects. The
review added `scripts/test_export_materials_review.py`; all **8 tests pass** after
the fixes. Source files were then released for the 0.3 aggregate freeze.

| Red evidence | Fix and observed green result |
|---|---|
| A keyed Principled IOR manually overridden to 1.375 became 1.876963 during a successful export; material names alone did not reveal the changed node value in the receipt fingerprint. | Animated material, node-tree/group and image dependencies are rejected before IDs/files are allocated. Both formats reject nested shader animation and movie/sequence images. The source value and complete fixture hash remain unchanged. |
| A muted Separate Color path was staged as its Red output instead of its effective muted routing. Actual 128px Cycles comparison gave MAE 0.0246316, p95 0.0862745 and maximum 0.639216. | FBX scalar staging rejects muted shader, separator and image nodes. The original unsupported graph remains unchanged and no export is published. |
| Unconditional source-scene `frame_set` reset an unrelated dirty light from 375 to 799.267 and reset a selected dirty animated object; the latter aborted only after detecting a changed source fingerprint. | An unchanged source frame/subframe is no longer reevaluated. Dirty light values survive successful and injected-failure exports, and selected object state remains exact. |

Removing that reevaluation exposed a separate static-output problem: a source at
authored x=9.25 exported around x=3.703704 because staging reevaluated its active
action at the integer frame. Static handoff now clears animation only on owned
object/data/shape copies, freezing their current authored values. The original
actions, NLA and keys are retained. Staging/reference evaluation preserves the
fractional frame, and receipts now include `source_subframe`. A dirty shape-key
fixture also retains its original action/value and exports the expected current
geometry. `include_animation=true` retains animated staging and still passes the
full cold animation handoff.

These changes avoid unnecessary reevaluation; they do not provide universal
rollback of arbitrary RNA changes by third-party exporter callbacks. Animated
materials are deliberately unsupported rather than implicitly baked. Unsupported
procedural material graphs still require explicit baking and independent rendered
comparison. The narrow scalar path remains file-backed, Non-Color, RGB Red,
default UV, flat/repeat/linear sampling.

## Precision, memory and cleanup review

The 16-bit grayscale writer copies red values without a color transform, rejects
nonfinite/out-of-range data before file creation, uses exclusive file creation,
flips Blender's bottom-up rows into PNG order and streams compressed scanlines.
The existing asymmetric 19×7 float-image fixture proves orientation and error below
one 16-bit code step after a real Blender PNG decode. Disagreeing source G/B values
in the rendered fixture detect accidental luminance conversion. No 8-bit precision
claim is substituted for the tested 16-bit output.

The budget is a conservative **64 bytes per unique source pixel** estimate for
temporary scalar staging. It is not an OS/GPU memory ceiling, does not cover all
geometry/exporter memory, and is not a universal texture residency measurement.
Maps shared across materials are staged once. Large-image measurements belong to
the separate [8K handoff record](8k-handoff.md).

Owned material/image IDs are removed and copied slots restored on exporter or
partial-PNG failure; the existing 10-test suite covers allocation/file cleanup,
shared/object-linked slots, budget rejection and byte-range/precision cases. This
review found no additional reproducible cleanup or PNG-precision failure within
that bounded scope. Original source file/material/pixel hashes remain unchanged
in the rendered handoff fixture.

## Final relevant checks

- `test_export_materials_review.py`: **8/8** independent regressions.
- `test_export_materials.py`: **10/10** staging, memory, cleanup and precision tests.
- `test_interchange.py`: **5/5**, including actual GLB/FBX cold imports.
- `test_animation_handoff.py`: **2/2**; both formats at 49 times, exact source hash
  `632e5c4075c3483d633696da539b7bfe8b4f272e8ef3265e8180e2621b698c36` retained.
- `test_pbr_map_handoff.py`: actual four-map cold renders pass in
  `artifacts/pbr-map-handoff/20261030T181935Z-b66f5005/`. GLB MAE is 1.10237e-6;
  FBX MAE is 3.96853e-6, against a missing-map-control-derived ceiling of 0.00852829.
- Ruff checks/formatting pass for the changed runtime and review script.

Red logs are `artifacts/export-materials-review-red.log`,
`export-materials-review-scope-red.log` and `export-materials-static-red.log`.
Green results are in `artifacts/export-materials-review-green.log` and
`artifacts/review-test_*.log`. The actual muted-graph counterexample renders and
measurement remain under `artifacts/muted-scalar-review/`. These are technical
fixtures, not broad material, artistic or native-engine acceptance.

## 0.4 follow-up: explicit scalar clipping

`asset.export` now accepts `clamp_scalar_textures`, default **false**. An explicit
true applies only to owned FBX red-channel staging; using true for GLB is rejected
so the request cannot imply a transformation that was not performed. The default
still rejects finite values outside [0,1]. NaN/Inf remain invalid under both modes.

Opt-in staging clips R to [0,1] while streaming each temporary 16-bit grayscale
PNG row. It does not resample or change source images/files. Applied receipts put
per-unique-image evidence in
`scalar_texture_staging.scalar_images[original_image_name]`: `source_red_min`,
`source_red_max`, `pixel_count`, `clipped_pixel_count`, `clamp_requested` and a
plain-language semantics description. Preview reports the requested policy and
memory estimate; pixel-range evidence is filled during actual staging.

The motivating case is finite overshoot in compressed data maps. Clipping is an
explicit derivative operation, not a claim that the input was lossless or that a
native shader interpretation is verified. The original strict policy remains
available by leaving the flag false.

`scripts/test_scalar_clamp.py` passes **4/4** actual Blender tests using a saved
float EXR with under/overshoot. Default rejection, explicit clipped export,
16-bit decoded output, original pixel/material hash and EXR byte preservation,
nonfinite rejection and the format/type boundary are verified.
`tests/test_scalar_clamp_schema.py` adds **2** schema tests. Red/green output is
retained at `artifacts/scalar-clamp-{red,green}.log`.
