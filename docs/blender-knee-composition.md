# Blender knee composition: measured scope and refusal

The [research receipt](../artifacts/verification/blender-knee-composition-20261101.json)
records a Blender-only follow-up to the retained character deformation study.
The previous saved correction improved the base mesh but introduced contacts in
the actual subdivided surface. It remains rejected.

The revised method preserves the source's stored Multires detail and adds the
difference between corrected and source plain subdivision. This is currently a
measured mathematical composition, not a public plug-in feature or accepted asset.

## Evidence

- 23 fresh poses plus two retained measured poses cover all previous failure states.
- One Blender worker: 920 captures, 231 seconds, four threads; no bake/render.
- Nine mixed controls per fresh pose pass the existing 1 micrometre limit. Maximum
  base error is 0.5485 micrometres; composed-surface error is 0.2802 micrometres.
- Outside-region movement is exactly zero. Source fingerprints, owned inventory
  and 106 dependency pins are preserved.
- Two new bundled-Python and four latest-host tests pass. No full suite ran.

## Why the correction is still rejected

The combined 25-pose system has 186,036 constraints. Two rows for one near-contact
pair at time 117 (polygons 34945/36213) cannot satisfy the unchanged 8 micrometre
clearance within the calibrated 0.4 mm movement range. Source separation is only
0.3414 micrometres. The system was rejected before optimization or a new candidate.

An audit of 46 standard triangle separation directions also refuses that local
range. The best direction needs at least 1.9107 mm by its individual linear-row
bounds. This is not evidence that the larger step is valid or that a general
correction is impossible.

The [wider-response follow-up](blender-knee-wide-response.md) now passes all25
poses at±2.5mm per coordinate. The full guarded coupled solve is next. Reuse the completed measurements; retain both accuracy and contact
thresholds. Any actual correction still requires the complete 73-state geometry,
contact/stretch/protected checks, fresh influence coverage, cold reopening,
matched visual review and public implementation. Artistic acceptance remains open.

The [small research record](../artifacts/blender-knee-composition-20261101/README.md)
describes the harness fixes and next step. Large measurements remain at the pinned
absolute paths in the receipt; they are excluded from the plug-in and release ZIP.
No Unreal process, Sundown write or runtime plug-in change occurred in this increment.
