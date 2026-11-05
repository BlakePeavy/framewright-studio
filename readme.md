# Framewright Studio

AI-friendly **Blender utility toolkit**. Retained scope, agreed November 5, 2026:

- Asset checks and diagnostics.
- Source protection and isolated jobs.
- Export and baking utilities.

Broader modeling, character and studio-parity work remains inactive. Existing
implementations and evidence are preserved; this scope decision does not remove
code or change the sealed release. Further work should serve these utilities.

**Current scope: Blender only.** Unreal and Sundown integration are deferred and
are not release requirements. Earlier engine experiments remain historical
evidence; do not launch or extend them without a new explicit request. Unreal is
not required to install or use the Blender extension.

## Verified delivery

Artifact and package links below refer to the populated local checkout.
`artifacts/` and `dist/` are ignored by Git and are not included in source pushes.

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

**Plug-in development remains paused.** The current art delivery is the
[30-second Nimitz launch animation](artifacts/carrier-animation-20261104/README.md):
a verified 1920x1080, 24 fps H.264 video, packed Blender scene and review stills.
The user accepted c22 quality for animation; **photographic acceptance remains
false**. Two sequential bow launches use the complete N4 aircraft; the detailed
Hornet forebody remains a separate still asset. The
[heading audit](artifacts/carrier-animation-20261104/heading-audit.md) records
alignment and layout limits, and the
[animation audit](artifacts/carrier-animation-20261104/animation-audit.md) records
Framewright gaps and rendering costs. Source PNGs remain in the workspace.
The [carrier/Hornet detail files](artifacts/carrier-detail-20261104/README.md),
[h16 study](artifacts/hornet-hero-20261104/README.md), earlier Nimitz and Blue
Horizon II scenes, and sealed 0.9 release remain preserved. Blender only;
no Unreal or Sundown changes or aggregate plug-in suite.

The [crew and tractor revision](artifacts/carrier-crew-20261104/README.md)
adds one rigged character master, seven independently posed role variants
and three detailed support tractors. Scene and still previews are saved;
the existing MP4 is unchanged. Close-up clothing fidelity remains below
the approved photorealistic concept. Focused native checks and Framewright
gaps are recorded with the assets; no aggregate plug-in suite was run.

The [refined crew checkpoint](artifacts/crew-hero-20261104/README.md) adds a rebuilt
master and seven carrier crew sharing geometry with independent rigs and colors.
All three native scenes reopen, and focused geometry, binding, contact and
instance checks pass; photographic fidelity remains below the concept.
Actual stills, packed CC0 textures and Framewright gaps accompany the scenes.
Crew poses remain static, the MP4 is unchanged, and plug-in development is paused.

The [usefulness audit](docs/library-value-audit-20261105.md) finds real value in
bounded asset checks, source protection and handoff tools, but no demonstrated
benefit for the latest crew modeling or photographic quality. Those edits and
checks used custom Blender scripts. Keep broad development paused until an
equivalent-task comparison demonstrates practical savings; no code is removed.

## Existing implementation inventory

- Modeling: evaluated topology, UV/material diagnostics, cabinet/facade builders,
  LOD/collision derivatives, normal/atlas baking and flexible profiles.
- Rigging/animation: metarig fitting, stock Rigify, skin binding, weight/corrective
  tools, sampled deformation/contact checks, retargeting and animation cleanup.
- Scene workflows: review lighting/cameras, resource estimates, provenance,
  source-preserving repairs, GLB/FBX export and cold reimport in Blender.
- AI access: validated JSON commands, gated workflows, owned background jobs and
  optional local MCP. See [59-command inventory](docs/tool-inventory.md).

This inventory includes preserved functionality outside the retained scope.
Unfinished character, modeling and artistic-quality work is historical backlog,
not a completion requirement for the utility toolkit. Technical checks and 8K
output do not certify finished art. See the [roadmap](docs/roadmap.md).

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

Keep this README brief and current. Sundown remains unchanged. GPL-3.0-or-later.
