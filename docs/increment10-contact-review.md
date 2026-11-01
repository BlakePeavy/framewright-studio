# Contact dependency and pose-copy review — 2026-10-30

Independent review reproduced four failures before the fixes: a subdivided
constraint-target mesh escaped the evaluated vertex budget; changing topology on
that extra dependency was ignored; a division-by-zero native driver at the middle
sample still produced a successful report; and two bound objects sharing one Mesh
datablock were copied with an ambiguous driver target remap.

`animation.skin_contacts` now evaluates every copied mesh dependency, including
meshes used only by constraints or drivers. They enter the same evaluated vertex
and sampling-work admission checks, finite-coordinate checks, and full-interval
topology fingerprint checks as marker meshes. The surface continues through its
existing geometry and topology checks and is counted once. Marker definitions,
projection rules, and output samples retain their existing meaning.

At every sample, copied object, data, and shape-key driver collections must have
valid FCurves **and valid Drivers**. The latter matters: Blender retained
`FCurve.is_valid == True` while `Driver.is_valid == False` after the reproduced
division by zero. Finite fallback coordinates are not treated as valid evaluated
motion. Failure disposes the owned isolated scene and returns no successful
partial contact report.

`pose.apply` rejects multiple requested bound mesh objects sharing a
Mesh datablock, in both preview and apply paths, before creating derivatives.
This removes an ambiguous source-data-to-derivative mapping; callers must author
independent mesh data when requesting multiple bound copies. Other pose and
contact API semantics are unchanged.

## Verification

Blender 5.2.1 LTS (`9e2066aef7ef`) background, factory startup, offline mode, and
auto-execution disabled:

- `scripts/test_skin_contact_review.py`: **9 passed**. Includes the four original
  red-to-green cases, failures on mesh data, shape-key and non-marker dependency
  drivers, negative-frame/subframe full coverage and sample limits, foreign-scene
  dependency refusal, and exact source state/allocation checks.
- Existing `scripts/test_skin_contacts.py`: **11 passed**.
- Existing `scripts/test_secondary_motion.py`: **9 passed**.
- Existing `scripts/test_surface_contacts.py`: **13 passed**.
- Host `tests/test_skin_contacts.py`: **8 passed**. Ruff checks passed for the
  changed runtime and new test script.

The intentional driver failures print Blender division-by-zero diagnostics; the
tests require the API to reject those samples. These are negative controls, not
successful motion observations. Evaluated geometry checks are admission checks,
not hard operating-system memory or execution-time caps.

## Human and prop pilot after the fixes

The fresh retained run is
[`artifacts/human-contact-pilot/20261030T190254Z-94a0cdfa/`](../artifacts/human-contact-pilot/20261030T190254Z-94a0cdfa/),
including an [editable file and rendered review](../artifacts/human-contact-pilot/20261030T190254Z-94a0cdfa/review.html).
The original run remains historical evidence in
[the skin-contact increment](increment10-skin-contacts.md); no earlier receipt was
overwritten.

Both the human and separate prop reports again match exactly in a new Blender
process after reopening the saved file with script auto-execution disabled. Each
contains 121 half-frame samples. The ten human markers yield 871 contact
observations, zero penetrations, zero sliding segments and zero projection misses.
Sampled geometry work remains 19,208,992 elements for this particular dependency
closure. The raised-ground control produces 902 penetrations; moving the surface
away produces 1,210 unknown-contact misses; injected root translation produces
600 planted-right-foot sliding segments; matching platform motion removes those
segments, with maximum residual tangent speed 1.5745e-5 m/s.

All 61 integer-frame 320×480 renders and six 512×512 closeups completed. The lift,
hold-foot and underside-marker images were inspected: the intended lifted versus
planted foot and the explicitly authored sole markers are visible. They do not
establish complete foot-surface clearance or validate the character's existing
deformation quality. Source file SHA256 remains
`2a661e2015caa97a239773138e79839d912a120c87bfbe60833a8175412087a8`;
the pilot also asserts its original rig/skin state fingerprint is unchanged.

Human art quality, broader motion quality, full-body or continuous collision, and
native-engine playback remain separate acceptance gates. Sundown was not opened
or modified.
