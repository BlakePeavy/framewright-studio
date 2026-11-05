# Framewright usefulness audit — November 5, 2026

## Verdict

Framewright has real, bounded value as an optional asset-checking and handoff
toolkit. It has not demonstrated the original promise of making AAA-quality
modeling, characters, lighting and animation substantially easier or better.
For the recent crew rebuild, its direct contribution was negligible: the saved
authoring and validation scripts did the work through Blender's Python API.

Recommendation: keep development paused, preserve the useful utilities and
existing evidence, and stop treating command counts or passing tests as proof of
production value. Do not expand the general character/AAA roadmap until a
representative task demonstrates a benefit over direct Blender/MCP. This audit
does not delete code, change the sealed release, or authorize engine work.

## What actually contributed

| Work | Evidence | Attribution |
|---|---|---|
| Latest crew geometry, clothing, hands, PPE, poses and seven copies | 27 top-level workspace Python files: no Framewright imports; 23 import `bpy`. Preserved [instance authoring](../artifacts/crew-hero-20261104/source/hero_instances.py), [pose authoring](../artifacts/crew-hero-20261104/source/hero_concept_pose.py), [carrier placement](../artifacts/crew-hero-20261104/source/hero_carrier.py). | Custom scene-specific code executed through Blender MCP. These are not shipped Framewright capabilities. |
| Latest crew checks | [Character validator](../artifacts/crew-hero-20261104/source/validate_character.py) and [carrier checker](../artifacts/crew-hero-20261104/source/final_native_check.py). | Custom checks. Their passing results cannot be credited to Framewright's diagnostics. |
| Earlier Nimitz foundation | `work/nimitz-factual-20261104/stage.py` and its `framewright-evidence.json`: PBR creation, scene inspection and resource reporting. | Actual library use; original geometry, ocean, shader customization and scene assembly remained custom Blender authoring. The current carrier inherits that material foundation. |
| Detailed Hornet study | Reference intake, manifest, reference board and PBR creation in `work/hornet-hero-20261104/reference_setup.py` and `hero_surface_stage.py`; later diagnostic receipts. See the retained [carrier audit](../artifacts/carrier-detail-20261104/library-audit.md). | Actual reference/material/diagnostic assistance; no demonstrated aircraft-model generation. Copied receipts are not additional calls. |
| Animation delivery | [Animation audit](../artifacts/carrier-animation-20261104/animation-audit.md). | Native Blender render scripts and FFmpeg; resumable delivery was not a Framewright feature. |

Earlier Blue Horizon material assignments and animation inspections also used
Framewright. The audit does not claim it was never used. It distinguishes those
bounded contributions from the later character work.

## Useful code versus the advertised breadth

| Area | Actual capability | Assessment |
|---|---|---|
| Source protection | [Transactions](../framewright/blender_transactions.py) check fingerprints, retain owned derivatives and refuse unsafe rollback. | Worth retaining. The transaction implementation has a narrow loose-vertex repair scope; it does not protect arbitrary custom scripts. |
| Background execution | [Worker](../framewright/worker.py) provides isolated input/output files, timeout/cancel, bounded concurrency and separate Blender user directories. | Useful for repeatable saved-file jobs. The packaged MCP transport is worker-oriented; the Python API can also be called in a live session. |
| Atlas/export | [Atlas staging](../framewright/material_atlas.py) and [interchange](../framewright/interchange.py) add preservation checks, budgets and explicit export behavior. | Substantive engineering, useful when a deliverable needs it. It does not improve the source art. The recorded default-16 8K run took 41.26 minutes; an 8K label alone does not justify that work. |
| Rigging and correctives | [Rigging](../framewright/rigging.py) calls stock Rigify; [binding](../framewright/rig_binding.py) uses Blender heat weights. Corrective creation requires caller-authored vertex offsets. | Automation and guardrails, not a new anatomy, deformation or corrective-discovery solver. |
| Modeling and review | [Builders](../framewright/production_assets.py) provide a workshop cabinet and period shop bay. Review sources must be owned, static mesh/empty objects, with a 500-object limit. | Useful specific recipes. Generic command names can imply too much. The review command does not directly admit the rigged crew created here. |

Blender already supplies the underlying component-based rig-generation system;
see its [Rigify developer documentation](https://developer.blender.org/docs/features/animation/rigify/).
Framewright's incremental value must come from reliable automation and fewer
errors around those operations, rather than claiming the underlying operation
as a new capability. Some guarded wrappers are worth keeping even when Blender
provides the underlying operation.

## Additional findings to retain

- **FW-ART-F24 — attribution and cost evidence.** Record which library command
  was actually used, what it replaced, failures/rework and elapsed effort.
  The current record does not establish cumulative time or usage savings.
  Test counts establish covered behavior, not return on investment.
- **FW-ART-F25 — visual acceptance before propagation.** The latest master still
  failed the requested photographic bar when it was reused for seven crew.
  A saved, rig-valid asset and a reference-matched asset are different states.
  This was an authoring/review decision failure; duplicating it did not resolve
  the user's quality requirement. A workflow must preserve the failed art state.
- **FW-ART-F26 — practical asset compatibility.** Tools useful only on their own
  static fixtures do not cover the live, externally authored character workflow.
  Explicit source-preserving intake and target/dependency remapping would be
  candidates only after their practical value is shown; this is not a mandate
  to loosen ownership checks or build another broad system.
- **FW-ART-F27 — durable operation state.** [Workflow replay](../framewright/workflows.py)
  lasts only within the process, with 128 cached runs; workflows are non-atomic.
  Repair authority also remains process-local. The current toolkit should not
  be described as a durable, fully recoverable production pipeline.
- **FW-ART-F28 — promote proven helpers selectively.** Shared-character copying,
  pose feasibility and review-file checks exist in scene-specific scripts.
  They become library features only after a stable API and reuse on another
  representative asset, with preservation and outcome evidence. The disabled
  vest displacement experiment should not be promoted merely because it exists.

Existing confirmed interface issues remain in the [earlier audit](../artifacts/carrier-detail-20261104/library-audit.md):
an advertised surface-inspection flag is rejected, reference-origin categories
are under-specified, and review discovery disagrees with runtime limits/scope.
This turn corrected the stale release/command-count/engine guidance in the
tool inventory and AI API guide. It did not fix or retest runtime implementations.

The visible crew defects largely arose in the custom modeling/posing scripts,
not in Framewright commands. The library did not cause every defect; it also did
not supply the missing artistic solution. I invested in broad infrastructure
before proving the authoring workflow, and credited technical milestones too
readily against the much harder visual goal.

## Decision for further work

Keep the source-preservation, inspection and export/bake/job utilities available
when an actual task benefits from them. Freeze broad character generation,
general-purpose modeling and studio-parity expansion. Unreal/Sundown remains
deferred. No new implementation tasks are opened by this audit.

Before substantial further investment, compare one representative workflow on
identical source copies using direct Blender/MCP and the relevant Framewright
path. Use the same required output, visual acceptance and preservation criteria;
count setup, retries, operator effort and compute cost. Retain/expand only the
capability that shows a practical benefit without worse output. If it does not,
leave that capability archived rather than expanding the framework to defend it.

No controlled comparison currently supports a percentage saving, and the audit
does not invent one. No new render, bake, animation, full test suite or live
scene mutation was performed. Review covered selected source implementations,
saved scripts/receipts and a read-only capability query reporting 0.9.0 / 59 commands.
Saved scripts are not an exhaustive transcript of every historical ad-hoc call.
