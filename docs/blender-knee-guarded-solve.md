# Blender knee: guarded coupled solve

The [subsequent contact diagnosis](blender-knee-contact-anchors.md) now traces
the exact rows and localizes opposing constraints on a connected source patch.

The [receipt](../artifacts/verification/blender-knee-guarded-solve-20261101.json)
records a completed solve using the existing 25-pose polynomial calibration.
No corrected character or public plug-in behavior is accepted.

The solver builds 517,335 inequalities across base and subdivided surfaces.
Polynomial displacement bounds cover contacts against the whole human; nonlinear
remainder guards retain 8 µm clearance within the measured ±2.5 mm box. Folds
use polynomial coordinates and derivatives. Seven focused numerical tests pass.

Removing exact duplicates and rows satisfied everywhere in the box reduces the
system to 19,921 rows. The 335.8-second worker finds no accepted point after 600
sweeps; the complete original system rejects its last iterate. Every individual
inequality is achievable in the box, but that does not establish joint feasibility.

A 3.5-second follow-up reuses the saved matrix and certifies a joint conflict
after 22 sweeps. A nonnegative weighted sum of 109 inequalities requires a value
below the minimum possible in the box: the gap is 8.68e-8, exceeding the 1e-10
roundoff guard. The witness is independently rechecked against the original rows
and retained in [joint-result.json](../artifacts/blender-knee-guarded-solve-20261101/joint-result.json).
More iterations of this same system cannot resolve that conflict.

This excludes only the chosen guarded separating axes and linearized fold
constraints in the measured box. It does not prove that arbitrary actual Blender
corrections are impossible. Next, trace the witness to exact pose/contact/fold
identities and revise the axes, support or fold approximation based on evidence.
Reuse these maps and matrices. A passing revised solve would still need actual
Blender geometry, full73 contact/stretch/protected checks, fresh influence
coverage, cold reopening, matched visual review and public implementation.

Both owned numeric workers exited. Source/input hashes are unchanged. No geometry
calibration, full suite, bake, render, Unreal process or Sundown write ran. The
sealed release, runtime code and character assets are unchanged. Large matrices
remain in the task workspace at paths pinned by the receipt.
