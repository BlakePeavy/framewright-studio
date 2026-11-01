# Isolated evaluated-skin contacts and authored human pilot

Version 0.4 adds `animation.skin_contacts`. It measures explicit
evaluated mesh vertices or barycentric triangle points against one named mesh
surface. Unlike object/bone-local approximations, these points include supported
skin deformation and shape keys. It does not infer anatomy, approve motion or
perform continuous/full-body collision detection. The existing
`animation.surface_contacts` command retains its original contract.

## Request and sampling boundary

```json
{
  "schema_version": "1.0",
  "request_id": "sole-review",
  "command": "animation.skin_contacts",
  "params": {
    "surface_name": "Ground",
    "markers": [
      {"id": "heel_L", "object_name": "Skin", "vertex_indices": [123], "weights": [1]},
      {"id": "ball_L", "object_name": "Skin", "vertex_indices": [200, 201, 202], "weights": [0.2, 0.3, 0.5]}
    ],
    "frame_start": 1,
    "frame_end": 61,
    "substeps": 2,
    "max_samples": 121
  }
}
```

Indices are illustrative: the caller must inspect the actual evaluated mesh.
Each of 1–32 uniquely named markers selects exactly one vertex or three distinct
vertices forming an actual evaluated triangle. Weights must be finite, between
zero and one, match the indices and sum to one. Triangle order follows the supplied
index/weight pairs. Evaluated topology, including tessellation, must remain
identical across the entire requested interval; changing topology fails the
request rather than returning a partial pass.
All copied mesh dependencies enter these checks. Invalid sampled native drivers
also reject the request; see the [independent follow-up](increment10-contact-review.md)
for the reproduced failures and selected post-fix human pilot.

Every integer frame is sampled. `substeps` adds 1–8 samples per frame interval;
there is no skipping `step` parameter. Frame bounds are ±1,000,000. `max_samples`
defaults to 512 and is capped at 4096; oversized requests fail without truncation.
Distances use scene units converted to meters, and speed uses effective FPS,
including `fps_base`. Surface transforms compensate rigid moving platforms.
Changing local surface geometry is unsupported.

The projection controls match the rigid-marker command: `search_distance` defaults
to 0.5 m, `contact_tolerance` to 0.03 m, `penetration_tolerance` to 0.01 m,
`sliding_speed` to 0.05 m/s and `minimum_up_dot` to 0.5. A missed downward ray or a
steep hit is unknown contact, never proof of clearance. Surface choice, winding,
overlapping layers and the first downward hit remain explicit limitations.

Admission limits include 64 local dependency objects, 4096 bones, 128 keys per
mesh, two million copied key points, a 200-million geometry/sample work budget,
and configurable `max_evaluated_vertices` (250,000 default; one million maximum).
Source vertex/topology work is checked before copying; produced evaluated
geometry is checked again. `max_surface_triangles` defaults to 100,000 and caps at
500,000. These are admission checks, not OS memory limits or interruptible
evaluation/time guarantees.

## Preservation and supported dependencies

The command copies its bounded local mesh/armature/empty dependency graph into a
temporary scene and changes only that scene's time. Parents, armature modifiers,
supported constraint pointers and native driver IDs are remapped to those copies.
Copied material slots and rig widget references are removed; source materials,
lights, node graphs and world are not part of sampling. Temporary objects, data,
shape keys and the scene are disposed on success and failure. No file or network
write is performed by the command.

Supported geometry modifiers are Armature, Subdivision and embedded Multires
(at most level three). Local active actions and bounded native simple-expression
or aggregation drivers are supported, including stock Rigify parent-switch
weights, numeric custom enums and polynomial generators. NLA, simulations,
instances, external Multires data, arbitrary scripted drivers, linked/override
data, shared dependency data and registered frame/depsgraph handlers are refused.
This is a supported-graph preservation boundary, not a claim that arbitrary
Blender scenes can be sampled safely.

The preceding `pose.apply` / `secondary_motion.apply_pose` copy path also had a reproduced defect:
copied corrective shape drivers still referenced the original rig or skin.
Driver targets now remap across the owned rig, mesh, mesh data and shape-key copies.
Changing copied control values changes copied correctives while retaining the
original driver IDs, action and weights.

## Test-first evidence

- `tests/test_skin_contacts.py`: **8** pure request/native-path tests passed.
- `scripts/test_skin_contacts.py`: **11** actual Blender tests passed, including
  shape deformation, armature/native corrective evaluation, vertex and triangle
  markers, changing topology, slope/nonuniform scale, units, moving platforms,
  miss/penetration distinction, pre-copy work admission, handler refusal,
  temporary-data cleanup and exact cold report reproduction.
- Dirty animated light energy, material roughness, constraint influence and
  shape-key values remain exact after both successful sampling and an injected
  mid-interval failure. The original scene's frame/subframe never changes.
- Existing regressions passed: **7** pure contact tests, **13** rigid-contact
  Blender tests and **9** secondary-motion tests, including the new copy-driver
  regression.
- Ruff formatting and checks passed on the changed files.

Genuine red evidence is retained in `artifacts/skin-contact-remap-red.log`,
`skin-contacts-python-red.log`, `skin-contacts-blender-red.log`,
`skin-contacts-rigify-path-red.log`, `skin-contacts-rigify-enum-red.log` and
`skin-contacts-admission-red.log`. Final focused logs use
`skin-contacts-*-final.log`, `skin-contacts-rigid-regression.log`,
`skin-contacts-secondary-regression.log` and `skin-contacts-legacy-python.log`.
These focused checks do not replace the next complete release receipt.

## Retained human and prop pilot

Selected evidence:
[`artifacts/human-contact-pilot/20261030T184521Z-fa688a05/`](../artifacts/human-contact-pilot/20261030T184521Z-fa688a05/).
Open [the local rendered review](../artifacts/human-contact-pilot/20261030T184521Z-fa688a05/review.html)
for the 61-frame sequence, five foot closeups and an underside marker view.

The source is the retained public knee-corrective candidate, SHA256
`2a661e2015caa97a239773138e79839d912a120c87bfbe60833a8175412087a8`.
Its file bytes and the original rig basis/action identity, weights, key geometry,
key values and driver IDs are preserved. The pilot uses new rig/skin/action copies.
The owned `.blend` SHA256 is
`321347cc6a5ed765936afe25d5dc0d9f1f847bf01fa1ba705f271896556dd025`.

Ten sole vertices were selected from explicit, recorded left/right foot regions
and low sole candidates in a neutral pose. Their exact indices, authoring targets
and evaluated world positions are in `authored-intent.json` and
`sole-candidates.json`. Labels such as heel/ball/toe are provisional authoring
choices, not inferred or artist-approved anatomical truth. Actual underside and
side renders show the points on the sole surfaces.

The authored 61-frame clip at 24 FPS declares stance → lift/forward motion → hold
→ lower → plant before measurement. Half-frame sampling produces **121 samples**,
1,210 human marker observations, with **871 contact observations, zero measured
penetrations, zero sliding segments and zero ray misses**. During the hold, the
left marker clearance is 0.142–0.151 m while the right markers remain planted.
The technical contact tolerance is 12 mm, penetration tolerance 5 mm, and sliding
threshold 0.03 m/s; these are recorded fixture choices, not production standards.
Sampled geometry work is 19,208,992 elements.

Declared controls distinguish the outcomes:

| Control | Observed result |
|---|---|
| Ground raised 40 mm | 902 penetration observations |
| Surface translated away | 1,210 misses, all contact values unknown |
| Root translated 120 mm across the clip | 600 right-foot sliding segments |
| Matching rigid platform translation | Zero right-foot sliding segments; maximum relative tangent speed 1.57e-5 m/s |

A separate authored box lift/place fixture samples four actual bottom vertices
against a 0.72 m table at the same 121 times. It records 216 contact observations,
zero penetrations/sliding/misses, intended planted endpoints and clearance during
the hold. It is **not attached to a hand and does not verify a grip**.

Both full reports reproduce exactly after cold reopening with auto-execution
disabled. The review contains 61 integer-frame 320×480 CPU Cycles renders plus
six 512×512 closeups, with recorded AgX/exposure/sample settings. Selected stance,
lift and underside images were inspected. This demonstrates a repeatable technical
contact workflow, not physically balanced performance, full-foot/continuous
collision, final character quality or native-engine playback. Existing knee
creases, hip/underarm compression, broader motion and artist acceptance remain
open. Sundown was not opened or changed.
