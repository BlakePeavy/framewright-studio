# AI API and unattended jobs

The development API uses a local, provider-neutral Python dispatcher and a JSON batch runner.
It does not start a network service, invoke an LLM, spend provider credits, or execute
code supplied in requests. Optional external MCP stdio and supplied-plan providers
are implemented; see [transport, path policy and evaluation](increment3-ai.md).
Call `capabilities` for every current command and its input schema. The table below
describes the baseline commands; production families are documented in
[diagnostics](increment2-diagnostics.md), [provenance/transactions](increment2-provenance.md),
[construction/lighting](increment2-assets.md), [rigging/animation](increment3-rigging.md),
[secondary adapters](increment4-secondary.md), [baking](increment3-baking.md) and
[GLB/FBX handoff](increment3-interchange.md).
New bounded additions include [explicit metarig fitting](increment5-rig-fit.md),
[skin binding](increment6-rig-binding.md), [surface contacts](increment6-contacts.md),
[PBR texture recipes](increment5-materials.md),
[source-preserving material assignment](increment7-material-assignment.md) and
[reference boards/workflow gates](increment5-board-gates-release.md).
The API also includes [shape-key bake and coupled morph handoff](increment8-morph-handoff.md),
[evaluated skin contacts](increment10-skin-contacts.md),
[interior/glass review fixtures](increment10-interior-glass.md), and
[EXR data-map intake](increment10-exr-intake.md). These remain bounded commands;
use the **verified 0.9.0 ZIP in [verification](verification.md)** for installation.
The [tool inventory](tool-inventory.md) lists 59 commands, six profiles and the
configured/pure-only MCP wrappers. The recorded release checks are historical;
ongoing standalone development targets Python 3.15.2 only, alongside Blender's
bundled runtime. Later checkout changes do not alter the sealed release ZIP.
The [usefulness audit](library-value-audit-20261105.md) distinguishes actual
workflow value from unproven artistic capabilities; development remains paused.
The [editable-geometry resource correction](increment14-resource-accounting.md)
is now verified; [pause findings](paused-scene-findings.md) preserve the original
failure and temporary converted-scene workaround as historical evidence.
The 0.5 additions are [B-Bone endpoint baking and explicit fractional
export sampling](increment9-bbone-handoff.md), with [independent source-preservation
checks](increment11-animation-review.md). [Construction](increment11-cabinet-construction.md)
and [normal-bake distances](increment11-bake-units.md) honor physical scene units.

`scene.resources` accepts optional `scene_name` and reports current-frame evaluated
mesh components from the first view layer, including converted editable sources and
instances. Original mesh counts remain separate; conversion-eligible source counts
can include hidden objects. Mixed non-mesh components are explicitly unmeasured,
and referenced material/image counts are not native draw calls or GPU residency.
See the [resource output contract](increment14-resource-accounting.md).

## Request and response

Every request has exactly four fields:

```json
{"schema_version":"1.0","request_id":"review-001","command":"scene.validate","params":{"profile":"cinematic_8k","overrides":{"texture_target":8192}}}
```

| Command | Parameters | Effect |
|---|---|---|
| `capabilities` | `{}` | Commands, profiles, override limits and limitations; works outside Blender |
| `scene.inspect` | `{}` | Current-scene snapshot of base mesh, skeleton, image and scene facts |
| `scene.validate` | Optional `profile` (default `realtime_high`) and `overrides` | Findings, counts, structural `passed` and effective settings |
| `mesh.remove_loose_vertices` | Required `object_name`; optional `dry_run` (default `true`) | Preview, or create a hidden derivative of a supported static mesh |

Overrides: integer `max_triangles` (1–100,000,000), `max_bone_influences` (1–32),
`texture_target` (0–65,536; 0 disables target advice), `max_texture_resolution` (1–65,536);
boolean `require_uvs`, `require_materials`, `require_camera`, `require_lighting`.
Target cannot exceed maximum resolution. Profile defaults are provisional policies,
not universal AAA standards. The API permits budgets above 8K when a workflow needs them.

Success returns `schema_version`, `request_id`, `ok: true` and `result`. Validation
success means the command ran; `result.passed` is independently false when ERROR
findings exist. WARNING/INFO findings still need review. Failures return `ok: false`
and `error: {code, message}`. Codes: `INVALID_REQUEST`, `BLENDER_REQUIRED`,
`OPERATION_REJECTED`, `INTERNAL_ERROR`. Unknown fields, commands, invalid values and
implicit nonboolean mutation flags fail before adapter access.

`request_id` is a correlation label, not an idempotency key. Retrying an applied repair
creates another derivative; inspect the previous result first. For stale-source
checks use `repair.plan_remove_loose` followed by `repair.apply_plan`; cancellation
and owned rollback are available. Transaction tokens and workflow replay caches are
process-local. A legacy repair preview alone is not a locked plan.

## Multi-step workflows

`workflow.run` accepts `run_id`, 1–32 `steps` and optional `dry_run` (default true).
Each step contains `id`, `command`, `params` and optional `require`. Preview validates
all steps without executing any. In an applied workflow, mutations default to apply
unless the step explicitly sets `dry_run: true`. Baseline and production API commands
are supported; recursive workflows and worker/transport operations are rejected.

Bind earlier result fields with `{"$ref":"build.result.collection"}`. Bindings only
traverse dictionary fields, with no code or expression evaluation. Add up to eight
strict scalar equality gates per step:

```json
{"id":"check","command":"scene.validate","params":{"profile":"studio_static"},"require":[{"path":"result.passed","equals":true}]}
```

Missing fields, type mismatches and unequal values stop before the next step and
record `gate_failure`. Check workflow `result.status`, independently of outer `ok`.
Workflows are non-atomic: earlier successful derivatives remain after a later failure.
Identical run-ID retries return cached results; changing that plan is rejected.
Replay protection lasts for the process, up to 128 cached runs. Preview reserves no ID.
See [the preview-by-default example](../examples/build-check-review.json).

## Calling from Python

The verified 0.6 command `contacts.inspect_regions` accepts exact object names,
ordered triangle identities and an evaluated-topology digest. It measures sampled
triangle relations against an explicit surface, with bounded work and no partial
success when a budget is exhausted. See [regional contacts](increment12-regional-contacts.md)
for coverage, units, time sampling and unsupported cases. In the retained 0.6 ZIP,
the caller authors the triangle manifest; neither version infers anatomical regions.
The [normal inspection optimization](increment12-normal-inspection.md) preserves
the existing bake request and result fields.

In verified 0.7, `contacts.describe_region` prepares that manifest
from explicit evaluated vertex indices or an exact named vertex group at a specified
time. The [description/contact workflow](../examples/describe-and-check-region.json)
passes the complete region through a result binding. Replace its object/group names;
`dry_run: true` validates the plan only, while `false` executes its two read-only
steps. Named groups use actual positive evaluated weights, including interpolated
subdivision vertices. No anatomical region is inferred. Targeted tests pass; the
retained human's four descriptions and both complete 121-sample inspections also
reproduce after cold reopening. The final resource-qualified 0.7 aggregate covers
these commands. See [authoring evidence and limits](increment13-region-authoring.md)
and [verification](verification.md). Complete result transport is bounded for one
command; arbitrary multi-step aggregate responses can still exceed the MCP limit.

The 0.3 commands include [continuous authored corrective activation](increment7-corrective-activation.md),
owned [cloth baking](increment9-cloth-bake-command.md), and
[FBX scalar-map staging with an explicit memory budget](increment9-material-handoff.md).
LOD comparison now reports [both sampled directions](increment7-bidirectional-lod.md)
while retaining its prior forward fields. These technical results grant no artistic
or native-engine acceptance.

Introduced in 0.8, `surfaces.bake_material_atlas` handles supported
static opaque Principled materials. The [build→atlas→review example](../examples/build-atlas-review.json)
binds exact part names between steps and defaults to whole-workflow preview. Setting
the workflow's `dry_run` to `false` creates an editable cabinet, hidden atlas derivatives
and a separate review scene; export is a separate explicit action. The [atlas contract](increment16-material-atlas.md)
documents image budgets, unsupported semantics and cold-handoff evidence. The
[sampling extension](atlas-sampling.md) adds integer `bake_samples` (1–64, default 16);
explicit 1 selects the faster single-sample behavior. Applied results expose actual
`effective_sampling`; preview does not claim execution. Extra samples increase work
without changing image budgets or guaranteeing visual acceptance. See
[verification](verification.md) for the sealed 0.9 release evidence and limits.

In a source checkout, on Blender's main thread:

```python
from framewright.api import dispatch

reply = dispatch(
    {
        "schema_version": "1.0",
        "request_id": "inspect-001",
        "command": "scene.inspect",
        "params": {},
    }
)
```

Installed extensions use Blender's namespace:
`bl_ext.<repository_module>.framewright_studio.api`. The repository module depends on
the selected extension repository (typically `user_default` for disk installs).
The dispatcher is an API boundary, not a sandbox for arbitrary Python already running
inside Blender. All adapter calls require the main thread and Object Mode.

## Headless execution

Run from the project root. Use a new report filename for every run; parent directories
must exist. Example using a caller-owned `.blend` file:

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
& $blenderExe --background --factory-startup --disable-autoexec --offline-mode 'C:\assets\owned-prop.blend' --python-exit-code 1 --python scripts/blender_job.py -- --request examples/validate-cinematic.json --output 'C:\assets\review-001.json'
```

Keep factory startup before the input file. `--disable-autoexec` prevents automatic
embedded Python execution on load. The batch script does not change preferences.
An applied repair requires `dry_run: false` and `--save-as` naming a **new** `.blend`
file; it refuses the source filepath and existing destinations. The saved file retains
the source and hidden derivative. Inspection/preview never save a blend file.

JSON input is limited to 1 MiB. Duplicate object keys and nonfinite JSON numbers are
rejected. Reports use exclusive creation; existing report files are preserved.
The report destination is reserved before applying changes. A blend file and a JSON
report cannot be committed as one filesystem transaction: if saving succeeds but
report I/O fails, stderr identifies the already-saved derivative. Inspect it before retrying.
Exit codes: 0 for successful command (including warning-only validation), 2 for request,
file, operation or workflow failure, 3 for completed standalone validation with ERROR findings; an uncaught
Python exception uses Blender's `--python-exit-code 1`. Treat a missing JSON report as
a job failure and inspect process output before retrying a mutation.

## Baseline command limits

The following limits describe `scene.inspect`, `scene.validate` and the legacy
loose-vertex repair. Dedicated production commands extend these capabilities with
their own documented bounds; no command grants artistic or production approval.

- Inspects base meshes, not evaluated modifiers/Geometry Nodes, render instances or full animation motion. Linked mesh facts are inspectable; repairs reject linked/override sources.
- Repair removes isolated vertices with no edges/faces only. Shape keys, modifiers, weights/groups, parents, animation and constraints are rejected; no welding, retopology or artistic edits are implied.
- Texture inspection follows scene material/world node trees. It checks known paths/dimensions, not all image-sequence frames, every UDIM tile's dimensions, actual texel density, PBR encodings or rendered material fidelity.
- Rig checks use deform-bone weight groups; they do not establish normalized weights, correct anatomy, usable controls or pose quality. Animation checks inspect ranges, not motion quality.
- Camera/light/world presence is only a setup hint; there is no illumination, exposure or color calibration evaluation yet.
- Extraction is synchronous and may be costly for very large meshes; a single mesh uses a temporary BMesh. Shared facts are deduplicated within one snapshot. External owned workers provide bounded concurrency, cancellation and polling-based timeouts; no Blender operations run on a background Python thread.
- No paths, raw geometry, pixels or credentials are sent to external services. Reports contain asset/image names and may still be project-sensitive.
