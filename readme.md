# Framewright Studio

A Blender extension for asset checks, source-preserving workflows, isolated jobs,
and export and baking utilities. Use it from Blender or automate supported
operations through a validated JSON API and optional local MCP server.

**Status:** 0.9 engineering preview. Tested on Windows with Blender 5.2.1 LTS;
the extension targets Blender 5.2.x. See [supported scope and limitations](docs/limitations.md).

## Features

- **Asset checks:** geometry, UV, material, rig and animation diagnostics with
  configurable budgets and JSON reports.
- **Source protection:** preview supported changes, create separate derivatives,
  and reject stale or unsafe repair operations.
- **Isolated jobs:** run saved-file workflows in owned Blender processes with
  explicit inputs and outputs, timeouts and cancellation.
- **Export and baking:** GLB/FBX export, normal and material-atlas baking,
  source-preservation checks and Blender reimport verification.

## Install

Clone this repository and build the extension from its root. Set `$blenderExe`
to Blender 5.2.1 or later in the 5.2 series:

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
New-Item -ItemType Directory -Force dist/source-build | Out-Null
& $blenderExe --background --factory-startup --disable-autoexec --offline-mode --command extension build --source-dir framewright --output-dir dist/source-build
```

In Blender, open **Preferences → Get Extensions → Install from Disk** and select
`dist/source-build/framewright_studio-0.9.0.zip`. Enable the extension, then open
the 3D View sidebar (**N**) → **Framewright**.

Select a validation profile and choose **Validate Scene**. Review the findings
and use **Export JSON Report** to save them. Repairs and exports have explicit
preview and output controls; check each operation's supported inputs before applying it.

## Automation and documentation

- [Command inventory](docs/tool-inventory.md) — available operations and profiles.
- [JSON API](docs/ai-api.md) — requests, workflows, previews and result handling.
- [MCP setup](docs/increment3-ai.md#mcp-endpoint) — local stdio server and isolated workers.
- [Supported scope and limitations](docs/limitations.md) — preservation, recovery and asset coverage.

The MCP server exposes validated operations; it does not execute arbitrary code
from requests. An AI client is optional, and the extension does not require a
cloud model or API key.

## Development

Use Python 3.15.2 and uv 0.13.6 or newer for standalone development. The extension
runs with Blender's bundled Python.

```powershell
uv sync --frozen --python 3.15.2
uv run --frozen python -m pytest tests/test_worker.py
```

The example runs the worker tests. Run the tests relevant to your change and add
regressions for fixes. Blender-dependent behavior requires checks in Blender.
For a release or major milestone, run the full verification pipeline:

```powershell
uv run --frozen python scripts/check.py --blender $blenderExe
```

Keep changes focused and document supported inputs and limitations. See the
[roadmap](docs/roadmap.md) for scope and the [verification record](docs/verification.md)
for historical release evidence. A source build includes checkout changes and
is not necessarily identical to a previously verified package.

## License

[GNU General Public License v3.0 or later](LICENSE).
