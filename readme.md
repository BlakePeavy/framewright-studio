# Framewright Studio

AI-friendly **Blender plug-in** for modeling, rigging, animation, materials and
lighting, targeting independently reviewed AAA quality with flexible cinematic/8K
and real-time budgets. Sundown's unfinished art is not the quality benchmark.

**Current scope: Blender only.** Unreal and Sundown integration are deferred and
are not release requirements. Earlier engine experiments remain historical
evidence; do not launch or extend them without a new explicit request. Unreal is
not required to install or use the Blender extension.

## Verified delivery

[0.9.0 engineering preview ZIP](dist/framewright_studio-0.9.0.zip): 84 aggregate
stages, 71 Blender suites, all 830 standalone Python cases across the initial run
and focused setup rechecks, and installed upgrade/rollback checks pass.
The [verification record](docs/verification.md) preserves hashes and limitations.
Later checkout changes have focused evidence and are not part of this sealed ZIP.
The latest Blender fix builds [closed convex hulls](docs/native-derivative-handoff.md)
without internal source faces; its new regression and two affected checks pass.
[Blender character research](docs/blender-knee-backtracking.md) adds four focused
regressions and retains all affected fold checks. Blender verifies 11.9% lower
worst contact deficit; 20 contact failures still prevent character acceptance.

[Blue Horizon](artifacts/blue-horizon-20261030/readme.md) is a separate editable
30-second carrier launch scene, with 720p video and a 4K still. Blender scripts
authored it; Framewright inspected and validated it.

## Implemented and remaining

- Modeling: evaluated topology, UV/material diagnostics, cabinet/facade builders,
  LOD/collision derivatives, normal/atlas baking and flexible profiles.
- Rigging/animation: metarig fitting, stock Rigify, skin binding, weight/corrective
  tools, sampled deformation/contact checks, retargeting and animation cleanup.
- Scene workflows: review lighting/cameras, resource estimates, provenance,
  source-preserving repairs, GLB/FBX export and cold reimport in Blender.
- AI access: validated JSON commands, gated workflows, owned background jobs and
  optional local MCP. See [59-command inventory](docs/tool-inventory.md).

These are bounded production-assistance tools. Remaining Blender work includes
character deformation, representative motion/contacts, source material fidelity,
lighting calibration, performance and artistic review. 8K output and technical
checks do not establish finished art or studio parity. See the [roadmap](docs/roadmap.md).

## Develop and verify

Target: Windows / Blender 5.2.1 LTS and one standalone Python, currently 3.15.2.
Blender uses its own bundled Python. No standalone multi-version test matrix.

```powershell
uv sync --frozen --python 3.15.2
```

Use focused failing-then-passing tests while developing. Run the full aggregate
only for major milestones/releases:

```powershell
uv run --frozen python scripts/check.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

Blender checks use owned background processes and preserve source assets. Do not
replace environments while workers use them. Generated evidence stays outside the
install ZIP. Use uv 0.13.6 or newer for the pinned Python download.

Install the verified ZIP through Blender Preferences → Get Extensions → Install
from Disk, then open the 3D View sidebar → **Framewright**. Mutation defaults to
preview. See [AI API](docs/ai-api.md) and [MCP setup](docs/increment3-ai.md).

Keep this README brief and current. No remote publication or Sundown edits have
been made by this task. GPL-3.0-or-later.
