# Explicit marker and surface contacts

`animation.surface_contacts` measures authored sole/prop points against an explicitly selected evaluated mesh. It extends the older bone-origin/flat-plane check without treating bone origins as soles or sampled motion as artistic acceptance. Implementation: `framewright/contact_analysis.py`; the command is read-only and requires Blender Object Mode on the main thread.

## Contract

Required parameters are `surface_name`, `frame_start`, `frame_end`, and `markers`. Each of 1–32 markers contains a unique `id`, exact `object_name`, and a three-number `position`; optional `bone` identifies a pose bone on that object. Position is in object-local Blender units, or bone-local Blender units when a bone is supplied. IDs contain 1–128 letters, digits, underscores or hyphens. Scene names allow up to 1024 printable characters; missing/ambiguous names fail. Linked objects are unsupported.

| Parameter | Default | Bounds / meaning |
|---|---|---|
| `frame_start`, `frame_end` | Required | Integer ±1,000,000; end must follow or equal start |
| `step`, `substeps` | 1, 1 | 1–1000 and 1–8; interval is `step / substeps` frames |
| `max_samples` | 512 | 1–4096; includes the requested endpoint; oversized ranges reject without truncation |
| `max_surface_triangles` | 100,000 | 1–500,000 evaluated triangles |
| `search_distance` | 0.5 m | 0.000001–1,000,000 m above and below each marker |
| `contact_tolerance` | 0.03 m | Absolute signed-normal distance; 0–1,000,000 m |
| `penetration_tolerance` | 0.01 m | Negative signed-normal distance; 0–1,000,000 m |
| `sliding_speed` | 0.05 m/s | Relative tangential speed threshold; 0–1,000,000 m/s |
| `minimum_up_dot` | 0.5 | 0–1; required upward component of the world surface normal |

Contact/penetration tolerances cannot exceed the search distance. Coordinates, transforms, units and FPS must be finite; the surface transform must be invertible at supported precision. Scene `scale_length` converts world coordinates to meters; effective FPS includes `fps_base`. A surface is also bounded to one million vertices and 200 million sampled vertex/index elements. Blender's evaluated mesh construction itself is synchronous and occurs before those evaluated-size checks.

The command samples the evaluated marker and surface at every requested time. A local geometry hash rejects changing surface coordinates/topology; object-level platform transforms are supported. The previous marker point is carried through the current platform transform before measuring tangential displacement. This compensates rigid platform motion and uses actual elapsed seconds.

Each sample reports projection status, surface point/normal, signed normal distance, contact, penetration and relative tangential speed. A ray miss or insufficiently upward normal yields **unknown** contact/penetration, with partial coverage. A valid hit outside the tolerance gives known non-contact at that sample. Sliding requires contact at both segment endpoints. Contact and penetration thresholds are independent; both can be true inside a generous contact tolerance.

Downward rays use world +Z and the **first hit** in the bounded interval. Select the intended contact layer: overhangs or overlapping mesh layers can obscure a lower floor. This is neither nearest-surface distance nor complete skin/volume collision. Authored heel/toe points approximate soles; the tool does not infer feet or fix animation. Returned temporal coverage states whether every integer frame was visited, and always leaves between-sample motion and visual acceptance unverified. Large reports can exceed the MCP response budget; request shorter intervals or fewer markers.

Original frame/subframe and local object/pose transform channels are restored exactly, including failure paths. The shared `rigging.preserve_time` helper also retains local shape-key value/mute/evaluation-time channels and top-level numeric scalar/array custom properties on scene objects, pose bones, local object data and local shape-key data. This includes manually adjusted animated values and shape values overwritten by driver evaluation. Restoration errors propagate; the tool never silently reports successful restoration after an error. The command does not assign materials, alter actions, add objects or save files. Temporary evaluated meshes are cleared.

This is a bounded character snapshot, **not an arbitrary scene-RNA transaction**. Other animated light/material/node/constraint properties, nested custom-property groups, custom frame handlers and external side effects are outside the restoration coverage. Frame evaluation can update those runtime values; the result includes explicit preservation coverage. The original animation curves, drivers and rig metadata are not edited. Evaluate unfamiliar production files in an owned background job with an intact source file, and do not equate the read-only command effect with universal preservation of every manually overridden scene property.

## Test-first evidence

- Initial pure and real-Blender suites failed because `contact_analysis` did not exist (`artifacts/surface-contacts-python-red.log`, `surface-contacts-blender-red.log`).
- Public-boundary regression then failed on a registry-valid 1024-character name before parser limits were aligned (`surface-contacts-schema-red.log`).
- A further preservation regression failed on both success and failure: authored shape value 0.123, pose control 0.234 and rig property 0.345 were replaced with the keyed value 0.68359375. `surface-contacts-authored-red.log` records the failure before extending the shared helper.
- Final targeted result: **17 pure/public-command tests with 17 subtests**, plus **13 tests in actual Blender 5.2.1 LTS**. Logs: `surface-contacts-python-green.log`, `surface-contacts-blender-green.log` under `artifacts/`.
- Fixtures cover bone-local heel offsets through the real dispatcher, nonuniformly scaled slopes, scene units, fractional FPS, moving platforms, sliding, misses/steep hits, sample bounds, animated surface rejection, geometry limits, exact failure restoration and a complete 24-frame interval with twelve planted then twelve raised-foot samples.
- Character restoration fixtures also cover unrelated animated and driven shape values, pose controls, object scalar/array properties and success/failure paths. Ruff formatting/lint passed on the new implementation/test files and changed shared helper. No shared editor, human pilot, Sundown assets or existing asset files were sampled or modified.
- After changing the shared restoration helper, the actual Blender regression run passed **13 contact + 12 rig/animation + 8 secondary-motion tests**. The rig/animation suite includes stock Rigify generation. Logs are `artifacts/contacts-regression-test_surface_contacts.log`, `contacts-regression-test_rigging_animation.log`, and `contacts-regression-test_secondary_motion.log`.

The 24-frame fixture is a known technical control, not whole-clip review of a production character. Human marker authoring, representative motion, artist review and native playback remain independent acceptance work.
