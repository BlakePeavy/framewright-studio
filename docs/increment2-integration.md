# Production integration work

The user's 2026-10-30 follow-up requires continuing through remaining tasks rather
than ending after each preview. This is an implementation/evidence log, not a claim
that independent art review, engine integration or AAA acceptance is complete.

## Test-first changes

- Production command registry: import-failure red, then 4 tests passed. Metadata
  exposes JSON schemas; unknown fields, types, bounds and commands are rejected
  before handler imports. Registered handlers are fixed by code, never supplied paths.
- Workflows: import-failure red, then 7 tests passed. Up to 32 sequential steps,
  prior-output bindings, whole-plan shape validation, default dry-run, cooperative
  cancellation, partial-failure receipts and process-local run-ID replay protection.
- Background workers: import-failure red, then 8 tests passed. Owned child processes,
  bounded concurrency, explicit cancellation and polled timeouts; no bpy threads.
- Real worker acceptance passed inspection, actual asset creation, saved derivative
  and source-file hash retention. Clients must poll the manager to enforce deadlines.
- Production sidebar: 4 red tests (missing operators/panel/properties), then 4 passed.
  Builders, diagnostics, review lighting, derivatives and structured JSON requests
  use the same public dispatcher. No arbitrary request code executes.
- Cross-feature API: real Blender tests cover manifest roundtrip, evaluated/surface
  diagnostics, plan/apply bindings and builder-to-review-scene bindings. All 4 passed
  after correcting the test to honor the manifest-validation response envelope.
- LOD/collision: real Blender import-failure red, then 5 passed. New static derivatives
  retain source geometry/selection and begin hidden. Surface comparison samples
  candidate vertices against the evaluated source surface; it is explicitly one-sided.

The batch runner now lives inside the package (`batch.py` and `job_entry.py`) so
installed extensions can launch owned workers. `scripts/blender_job.py` remains a
compatible CLI wrapper. Existing job tests target the packaged implementation.

## Current boundaries

Workflows retain successful earlier derivatives after a later error; they are not
atomic transactions. Rollback is explicit for supported owned repair transactions.
Replay protection and repair tokens are process-local. External jobs retain evidence
directories until their owner removes them. Large-scene scheduling and production
performance measurements need representative assets, not only small fixtures.

Procedural cabinets/facades are editable construction examples with genuine lighting
renders. They have not been approved as final AAA assets. The independent benchmark
candidate registry is in `benchmarks/candidates.json`; reference bytes stay in ignored
local artifacts. The official Blender Studio human base mesh ZIP is a CC0 anatomy
and topology reference, not a finished character or a replacement for art acceptance.
