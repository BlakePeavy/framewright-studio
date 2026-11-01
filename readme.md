# Framewright Studio

AI-friendly Blender production tools targeting independently reviewed AAA quality,
with flexible cinematic/8K and real-time budgets. Sundown Run is an eventual integration
destination; its unfinished art does not define the benchmark.

**Verified engineering preview: [0.8.0 ZIP](dist/framewright_studio-0.8.0.zip).** All 82
verification stages passed on unchanged source bytes: 812 Python tests, 69 Blender
suites, packaging and actual 0.7→0.8→0.7→0.8 install/upgrade/rollback. Python 3.13
also passed all 812 tests. This increment adds shared PBR material-atlas baking,
preserves cold hidden-object review transforms and corrects exported atlas UV selection.
Actual 1024 and 8192 cabinet atlases pass cold Blender/GLB/FBX renders and map audits.
The 8K worker takes about 20 minutes and peaks at 16.39 GiB working memory.
A separate repaired adapter passes isolated Unreal 5.8.3 import/settings checks;
cold reload is in progress. The release runtime has not received those fixes.
Technical checks do not grant artistic or native-engine acceptance.
See [verification](docs/verification.md) for package/source checkpoint hashes, evidence and limits.

Completed artwork: [Blue Horizon](artifacts/blue-horizon-20261030/readme.md), a separate
editable carrier launch scene with a 30-second 720p video and 4K still. All 45 scene
checks and the full 720-frame video decode pass. Blender scripts authored the assets;
Framewright inspected/validated them. The original resource-reporting failure and
temporary workaround remain recorded; the [verified correction](docs/increment14-resource-accounting.md)
now inspects the original editable scene directly. Character refinement, Sundown
native pilots and production acceptance remain open.

## Implemented in the checkout

- Scene preflight, evaluated topology, UV/material diagnostics and configurable profiles.
- Hashed provenance, reference boards/landmarks, stale-plan protection and scoped rollback.
- Editable cabinet/facade builders, static LOD/collision derivatives, cage normal and shared PBR atlas baking, material assignment and measured texel density.
- Explicit metarig fitting, stock Rigify generation, source-preserving skin binding, weight/corrective tools, sampled deformation/contact checks, retarget/bake/cleanup and secondary bindings.
- Separate neutral/day/dusk review scenes, evaluated region authoring and sampled contacts, resource estimates, scoped GLB/FBX export and cold-reimport fixtures.
- Strict JSON commands, gated workflows, owned background jobs, optional local MCP stdio and measured repair ranking. No AI account or runtime dependency installation required.
- [Tool inventory](docs/tool-inventory.md): 59 commands, six profiles and six configured MCP wrappers. Native import utilities are separate and provisional.

These are bounded tools with documented limits. They do not generate finished assets
from text or establish artistic approval, studio parity, native engine parity or runtime
performance. [Local review kit](docs/benchmark-review.md) and [performance measurements](docs/performance-baseline.md)
provide inspectable evidence. Actual 8K output/maps and bounded rendered GLB/FBX material
fixtures are verified; the human stress pilot still needs deformation refinement and
artist approval.
An [actual 8K texture handoff](docs/8k-handoff.md) passed both cold GLB/FBX imports and
512px render comparisons; process memory is measured. Sundown native/runtime pilots,
remaining character art and full production acceptance stay open.

## Develop and verify

Tested environment: **Windows, Blender 5.2.1 LTS**. From this folder:

```powershell
uv sync --frozen --python 3.15.2
uv run --frozen python scripts/check.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

Omit `--blender` for Python checks. Blender fixtures use owned background processes;
tests do not attach to the shared editor or modify Sundown. The extension uses Python's
standard library and Blender-bundled modules. Generated assets and evidence remain in
ignored `artifacts/`, outside the install ZIP.
Use focused tests while developing; run the full command above at major milestones
or releases. The standalone development target is one latest-stable Python (3.15.2);
there is no host-version matrix. Python 3.15.2 passes all 830 current candidate
cases across the initial run and five focused environment rechecks; no full rerun.
Use uv 0.13.6 or newer for its managed download. Blender/Unreal checks use their bundled runtimes.
Do not replace an environment while an owned worker is using it.

Install a **verified** ZIP through Blender Preferences → Get Extensions → Install from
Disk, then open the 3D View sidebar → **Framewright**. The production tools and JSON
workflow operators are included; use the exact ZIP identified in the final
verification receipt. Mutation defaults to preview; supported derivatives retain their sources and
start hidden. See [AI API](docs/ai-api.md) and [MCP setup](docs/increment3-ai.md).

## Work order

- [Roadmap](docs/roadmap.md): implementation status, remaining engineering and acceptance gates.
- [Verification](docs/verification.md): suite results, release receipts and unverified boundaries.
- [Sundown contract](docs/sundown-integration.md): staging, identity and native pilot requirements.
- [Research](docs/research.md): gap register and official source basis.

Keep this README brief and update the roadmap/evidence when delivering an increment.
Local Git on `main`; verified source checkpoints retained, no author identity or remote configured.
No publication performed. GPL-3.0-or-later.
