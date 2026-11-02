# Sundown Run integration contract

> Scope update (2026-11-01): engine integration/testing is deferred. This record
> is historical, not an instruction to resume Unreal work. The Blender hull
> correction remains applicable; destination-specific follow-ups are outside scope.

Read-only discovery: 2026-10-30. No Sundown files, scene data, installed build, task records or preferences were changed while starting Framewright.

**Quality authority:** Framewright targets independently reviewed modern AAA studio quality, with flexible profiles including 8K. Sundown's current art is work in progress and is not the visual benchmark. The game evidence below supplies integration, preservation and historical workflow constraints; its existing quality documents do not cap this add-on's quality target.

## Confirmed destination

| Item | Observed project contract |
|---|---|
| Active repository | `D:\Projects\SouthwestAmericaGame` |
| Engine/project | Unreal Engine 5.8.3; `Source/SundownRunUnreal/SundownRun.uproject` |
| Native acceptance location | Connected `JourneyIntegration`; `MigrationReview` is staging |
| Active task source | `tasks/opentasks.md`; `Task.MD` points there |
| Preserved Unity baseline | `codex/unity-backup-2026-09-22`, commit `44a9cf9e`; historical measurements are not current Unreal evidence |
| Blender baseline verified locally | 5.2.1 LTS on Windows |

Resolve the destination from explicit configuration and current project instructions at integration time. Do not hard-code this machine's paths into the reusable add-on. Never read `tasks/closedtasks.md`; the game maintains it as an append-only archive.

The game's current workflow favors playable WIP and limits automated game test runs. The user's explicit TDD request governs this separate Framewright repository. This project can test its own fixtures without running Sundown suites, launching Unreal, packaging the game or changing `C:\Games`.

## Asset preservation and delivery

Retain the selected high-detail `.blend`, reference provenance, original meshes, construction UVs, material slots, rig identity and reproducible builders. Work on separately named, owned derivatives. A newer generated file does not automatically supersede the selected production source. Local-only reference libraries and large art assets must not be copied into this repo or uploaded implicitly.

The future handoff manifest should contain source/derivative hashes; tool/version/recipe; asset identity; dimensions and coordinate basis; material/texture mapping and encodings; skeleton/rest-pose identity; clip time basis; export settings; collision/LOD ownership; and separate verification states. Use `unknown`/`not_reviewed` for missing evidence. Proposed states are `source_reviewed`, `export_verified`, `native_imported`, `world_placed`, `cold_verified`, `runtime_bound` and `visually_accepted`; they are independent facts, not an automatic progression.

Validate transforms with an asymmetric measured fixture and explicit units. Sundown's Unity-to-Unreal migration permutation is a legacy bridge contract; do not apply it blindly to Blender/glTF output or convert axes/units twice. Retain meaningful pivots and named moving parts. Preserve simple gameplay collision separately from visible detail.

For textures, distinguish base-color sRGB from normal/roughness/metal/AO data, record OpenGL/DirectX normal convention and packed channel order, and verify actual export bindings. A supported Principled surface is not evidence that arbitrary Blender node graphs transfer. Preserve texture dimensions/source pixels when changing compression and measure native residency separately.

## Known Blender pitfalls from the game

| Evidence | Required treatment |
|---|---|
| The 12 October 2026 Blender 5.2.1 session crashed during `bpy.data.libraries.write` with a Scene ID | Do not reuse that isolated-save pattern or reset/save over a shared live session. Use owned background processes and normal full-file save/reopen for future handoff experiments |
| Multiscene GLB export included unwanted selected content | Future scoped exporter uses both active-scene and explicit selection scope, then inspects actual GLB contents |
| Successful topology/weight checks still preserved bad anatomy or deformation | Review silhouette, face/hands, pose extremes, full relevant motion and contact in rendered output |
| A copied skinned mesh retained conflicting vertex-group names | Match exact group-to-bone identities and verify evaluated motion, including accessories/hair |
| Shape keys created from an active mix inherited unrelated displacement | Start independent keys from Basis and check protected vertices as well as appearance |
| FBX clips may shift their start frame | Compare normalized clip times and duration; bake drivers/constraints for portable playback |
| LOD reduction passed distance checks while damaging thin parts or leg deformation | Preserve high-detail source; compare posed geometry, thin layers, silhouettes, transitions and shadows |
| Export and render workers can overwrite common evidence paths | Use owned output directories and serialize jobs that share source/capture paths |

These are documented project lessons, not a claim that Framewright already detects or repairs every case. The current add-on's implemented coverage is listed in its README/API, with remaining work in the roadmap.

## Pilot sequence

1. Select one owned static prop with established reference, source and game placement. Record the current production source and a bounded before view.
2. Inspect and preflight a derivative in Framewright. Review any repair plan before applying it; retain original bytes and detailed evidence.
3. Export to an owned staging directory and reimport in a clean Blender process. Compare actual geometry, asymmetric bounds, UV/material assignments and pivots.
4. Use the game's existing authorized native import workflow; preserve asset/actor identities and current shared-editor ownership. Native import success only closes the import stage.
5. Inspect actual Journey placement at appropriate 1 m / 5 m / 25 m coverage, neutral/daylight and dusk. Verify contact, access, interaction and temporal behavior.
6. Only after the static pilot succeeds, select one character/clip pilot preserving its established skeleton and runtime contracts. Exercise joints, hands/props, foot contacts and costume through required motion.
7. Measure native performance separately and review whether Framewright improves quality and iteration time enough to expand adoption.

The game's existing 4K review contract specifies 3840 × 2160 output with internal resolution, AA/reconstruction and capture mode recorded. It is an integration review setting, not Framewright's quality ceiling: the add-on also plans flexible 8K source/capture workflows according to asset class and shot coverage. Close stills do not establish motion, player acceptance or presented FPS. The game's historical texel-density suggestions are not adopted as universal Framewright gates. Minimum shipping hardware and a universal 4K/8K frame-rate target remain undecided; establish project-specific targets when the pilot begins.

## Local authority read

All paths below are relative to the observed Sundown repository; read the current versions before future integration:

- `AGENTS.md`, `Task.MD`, `tasks/README.md`, targeted active records in `tasks/opentasks.md`.
- `Docs/Migration/UnrealMigration.md` for active engine, import/coordinate and preservation contracts.
- `Docs/Production/34-engineering-and-graphics-standards.md` and `36-4k-visual-target.md` for evidence and quality requirements.
- `Tools/skills/sundown-art-quality/SKILL.md` and `references/blender-production.md` for production workflow and known failure cases (installed skill copy was also consulted).
- `Tools/blender_extension_rpc.py` as an existing local execution bridge. Framewright does not require, start or expose this bridge in its first increment.
