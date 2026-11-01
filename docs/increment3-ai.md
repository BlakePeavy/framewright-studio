# Increment 3: local AI transport and evaluation

Implemented 2026-10-30 for the bounded local scope of FW-061/FW-062/FW-063. This adds an optional MCP endpoint, supplied-plan providers and technical evaluation. It does not call a cloud model, spend credits, load credentials or certify artistic quality.

## MCP endpoint

`framewright/mcp_stdio.py` runs as an external Python process. It uses newline-delimited UTF-8 JSON-RPC on stdin/stdout; operational messages go to stderr. There is no network listener or arbitrary Python/shell tool. Each input message is limited to 1 MiB; duplicate keys, nonfinite values, malformed envelopes and unknown tool arguments are rejected. These framing rules follow the official [MCP stdio specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio).

Two protocol revisions are implemented:

- `2026-07-28`: `server/discover`, required per-request version/client-capabilities metadata, complete result envelopes and tools. No preceding handshake is required. See official [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), [discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover) and [request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic/index).
- `2025-11-25`: `initialize`, `notifications/initialized`, ping and tools for legacy clients, following the official [legacy lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).

The tools subset supports discovery and calls with JSON schemas, structured results and text fallbacks, as described by the official [tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools). HTTP, resources, prompts, sampling, task extensions and subscriptions are not advertised or implemented. Protocol tests are local; this is not a formal third-party MCP conformance certification.

Pure mode:

```powershell
uv run python -m framewright.mcp_stdio --pure-only
```

Worker mode uses paths explicitly chosen at process startup:

```powershell
uv run python -m framewright.mcp_stdio --blender "<Blender executable>" --asset-root "<existing input root>" --job-root "<existing output root>"
```

Add `--enable-rigify` to load bundled Rigify inside owned background jobs when fitting
or generating stock rigs. It is off by default and never saves an artist's preferences.
Reference-board outputs are scoped to `job-root`; their local references and all four
PBR texture paths are scoped to `asset-root`. Dynamic file-bearing bindings are refused.
Both input and response messages are limited to 1 MiB; an oversized response returns a
bounded error without claiming that completed work was undone.

For a host that starts in another directory, set its command to the project's Python executable and its first argument to the absolute `framewright/mcp_stdio.py` path. Both absolute-file and module entry modes are tested. Configure the remaining paths as above; tool arguments cannot replace the executable or packaged job script.

The 0.7 follow-up also tests an absolute entry under Blender's installed
`framewright_studio` package name. The entry derives its package from its own
resolved directory, as the worker entry already does. The retained 0.6 package
failed this renamed-folder probe; source-checkout entry still worked. Two new
tests verify packaged discovery/version and an actual owned Blender inspection
from an unrelated directory, including input hashing and EOF cleanup. Server
metadata now reports the package version in both supported protocol revisions.

Pure tools are `framewright_capabilities`, `framewright_manifest_validate` and `framewright_workflow_validate`. Worker mode additionally exposes `framewright_submit_job`, `framewright_poll_job` and `framewright_cancel_job`. Submit returns an owned `job_id` immediately; poll obtains completion/error evidence and enforces deadlines. The controller must keep polling while work runs: there is no autonomous polling thread while stdin is idle. Closing stdin closes the transport and cancels only its owned running workers. RPC cancellation notifications do not cancel already-returned asynchronous jobs; use `framewright_cancel_job` with the returned ID.

All MCP input `.blend`, reference-intake and export-directory paths must be absolute, so changing the worker's working directory cannot change their meaning. Input `.blend` and reference paths must resolve under `asset-root`. Export directories must resolve under `job-root`, and export filenames must be plain basenames. The same checks traverse workflow steps; dynamic bindings for file destinations are rejected. New file-writing commands are unavailable through this transport until they have an explicit path policy. This is **not a filesystem sandbox**: the local process retains its caller's OS permissions, and Blender files may reference external linked resources. No assets are sent over a network by this endpoint; it offers no arbitrary script execution or network listener.

Structured region-result bindings are supported. Filesystem commands require an
explicit parameter object before submission: binding that whole object cannot
hide paths from the pre-submit checks. The first 0.7 aggregate caught a material
parameter-binding regression; the fixed guard rejects it before a worker starts.

## Providers and technical evaluation

`framewright.providers.PlanProvider` is an application protocol returning an allowlisted workflow. `SuppliedPlanProvider` validates an explicit mapping of task IDs to workflows and returns detached copies. `FileReplayProvider` loads a bounded schema `1.0` JSON corpus once, records its SHA256 and can require an expected hash. It never executes strings or silently reloads a changed file. Both use the workflow validator; invalid or recursive commands fail before execution.

```python
from framewright.providers import SuppliedPlanProvider, evaluate
from framewright.workflows import run_workflow

provider = SuppliedPlanProvider(
    {
        "manifest_case": {
            "run_id": "manifest-evaluation-1",
            "dry_run": False,
            "steps": [
                {
                    "id": "asset",
                    "command": "asset.manifest_create",
                    "params": {"name": "Evaluation fixture"},
                }
            ],
        },
    }
)
report = evaluate(
    provider,
    [
        {
            "id": "manifest_case",
            "expected_status": "completed",
            "required_commands": ["asset.manifest_create"],
        }
    ],
    run_workflow,
)
```

Evaluation requires a trusted runner function. Corpus expectations cover workflow status, required commands/rule IDs, maximum ERROR findings and optional elapsed-time budgets. Applied mutating steps require explicit `allow_mutation=True`; literal per-step previews do not. Results record plan/result hashes, elapsed time, successes, regressions, improvements and removed baseline cases. Removing a prior case cannot silently produce a passing report. `artist_approval` remains `not_evaluated`. These metrics measure the supplied technical corpus, not general model intelligence, studio parity or human approval. File providers do not infer new plans; a future model adapter must implement the same protocol and retain validation.

## TDD and verification

- Wrote provider and MCP tests first; both failed because their implementation modules were absent.
- Implemented local replay/evaluation and protocol tools. Further failing regressions covered malformed expectation types and explicit per-step previews; both were fixed.
- An actual stdio subprocess launched from an unrelated working directory initially failed on relative imports. Added the trusted absolute-entry bootstrap and verified it.
- Final owned suites: 14 provider/evaluation tests and 16 MCP tests pass when `FRAMEWRIGHT_BLENDER` names Blender 5.2.1. The MCP suite includes real external stdio processes and a full stdio-to-owned-Blender job with source-file SHA256 preservation. Fake-worker tests cover scope rejection, injected executable fields, dynamic output bindings, cancellation and EOF cleanup.

Run `uv run python -m unittest discover -s tests -p test_providers.py -v`. For all MCP tests, set `$env:FRAMEWRIGHT_BLENDER` to the installed Blender executable, then run `uv run python -m unittest discover -s tests -p test_mcp_stdio.py -v`. Without that environment setting, only the real Blender-worker test is skipped; all protocol/process tests still run. All Blender fixtures and worker artifacts are temporary and isolated; the live scene and game project are untouched.

## Integration review corrections

The independent release review added `tests/test_integration_review.py` and
`scripts/test_review_regressions.py`: nine tests pass on Python 3.11 and eight pass
on Blender 5.2.1 respectively. Regressions were observed before each fix:

- A workflow binding resolving to `dry_run=False` was missing the save requirement.
  Worker and batch now share a conservative persistence guard: only literal `True`
  proves a scene-writing step is a preview. Actual Blender tests reject missing
  destinations before mutation, save applied output, and replay without duplicates.
- Frame bounds, sampling steps and normal-bake ranges now match handler requirements
  in capability schemas. Missing or out-of-range fields fail before Blender import.
  The optional export filename default is accepted by both API and MCP path policy.
- Relative reference/export paths could pass MCP root checks yet resolve elsewhere
  from a worker's distinct directory. The transport now requires absolute paths;
  a regression changes the server cwd and proves rejection before job submission.
- Local and linked objects can share an exact name. Repair, bake and export now
  reject this ambiguity before mutation; library-backed fixtures reproduce it.
- Empty LOD sources and point-only comparison candidates are rejected. Injecting a
  collection-link failure leaves no owned collision object or mesh behind.

Local red/green logs are under `artifacts/review-*`; they contain generated fixtures,
not user asset data. Existing command/workflow/worker, MCP, repair, baking and cold
GLB/FBX reimport checks also pass after these corrections. These checks establish
bounded execution and source preservation; they do not grant visual acceptance or
make multi-file output atomic.
