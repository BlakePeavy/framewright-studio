# Framewright Studio

Build an AI-friendly Blender extension for production asset workflows. Read `readme.md` and `docs/roadmap.md` first. Keep `readme.md` brief and current with each delivered increment.

- Use test-driven development: reproduce with a failing test, implement the smallest change, refactor, run relevant checks.
- During development run focused failing-then-passing regressions for the changed behavior. Run the full aggregate only at a major milestone or release after batching changes; repeat only affected checks unless new changes or failures justify a broader run. Avoid duplicate renders, bakes and research sweeps.
- Use one latest-stable standalone development Python (currently 3.15.2); do not maintain a multi-version host matrix. Verify Blender features in its actual bundled runtime and keep extension code compatible with that runtime. Never replace or resync an environment while an owned worker uses it; migrate after the current checkpoint.
- Keep the pure Python core independent of `bpy`; Blender access belongs in the adapter and runs on the main thread.
- Never execute code from AI requests. Use versioned, validated commands and explicit capabilities.
- Inspect before changing; edits must preserve source assets. No automatic writes to Sundown or live Blender sessions.
- Do not claim visual acceptance, engine parity, or compatibility without corresponding evidence.
- Current scope is strictly the Blender plug-in. Target Blender 5.2 LTS. Unreal/Sundown integration and engine acceptance are deferred, not completion gates. Do not launch or extend engine checks under the earlier isolated-validation approval; a new explicit request is required. Retain previous code/evidence without promoting the unfinished native derivative candidate.
- Record completed work and remaining limits in the backlog. Keep machine-specific paths out of shipped code.
