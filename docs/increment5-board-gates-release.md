# Reference boards, workflow gates and release hardening

Implemented/tested 2026-10-30 on Blender 5.2.1 and Python 3.11. These features preserve
the separation between technical evidence and artistic/native approval.

## Workflow and UI corrections

Baseline commands now participate in workflows alongside production commands. Their
discovery schemas share the dispatcher profile limits. Three new tests first exposed
the baseline exclusion; all baseline and production workflow tests pass after the fix.
`require` adds bounded strict equality gates on response fields. Two failing tests
established stop-before-next-step behavior, missing-field handling and boolean/type
distinctions before implementation. The real build → validate → review Blender fixture
passes through the public dispatcher.

The UI JSON operator now shares the bounded UTF-8/duplicate-key/nonfinite parser with
batch jobs. A duplicate `dry_run` key previously allowed an unintended application;
the regression now rejects it before creating objects. A failed workflow previously
returned FINISHED; it now reports cancellation and retains the detailed partial result.
All six production-UI tests and eleven batch boundary tests pass in the scoped run.

The independent release review additionally reproduced partial class registration
after an enable failure. Base and production panels now preflight identifier/property
collisions, track owned registrations and unwind partial registration. Tests verify
retry and preserve foreign classes/properties rather than unregistering them.

## Reference-board API

`asset.reference_board` accepts `manifest`, an absolute new `.html` `output`, and
optional `dry_run` (true by default). It validates provenance, limits boards to 64
references, lists missing view labels and links existing local images without copying
the source library. HTTP(S) references are links only; remote images/scripts are not
loaded. Metadata is HTML-escaped, active URL schemes/UNC paths are rejected, and a
restrictive content policy disables scripts and remote content. File availability,
recorded license/status and artistic acceptance remain distinct.

MCP scopes the output to its job root and local image references to its asset root;
dynamic file-bearing bindings are rejected. Four pure tests cover preview, preservation,
escaping, overwrite protection and missing evidence. An additional MCP test checks
both roots. An injected partial write exposed an HTML stub; cleanup now removes only
the same owned file with unchanged intended bytes and preserves replacement content.

The actual [cabinet board](../artifacts/reference-board/cabinet-study.html) links two
retained neutral renders and explicitly lists absent side/back views. It does not
promote those development studies to approved reference art.

## Bake guards and cages

The low mesh now needs a complete bounded evaluated-UV check with no zero-area or
overlapping triangles and a single 0..1 atlas. Positive total UV area previously let
collapsed individual faces, stacks and out-of-tile coordinates pass. All three failing
controls are now refused before image allocation. Other UV layouts remain unsupported
by this single-image bake command.

Optional `cage_object` selects a separate local static cage with the low mesh's exact
ordered topology. Low/cage modifiers must be applied on retained derivatives first.
The cage is copied into the bake scene; originals are preserved. Cycles performs the
actual cage bake. An independent far-cage regression found mismatched preflight and
Cycles ray lengths; both now use the same bounded distance, preventing a misleading
flat result. These constraints follow the [Blender baking manual](https://docs.blender.org/manual/en/latest/render/cycles/baking.html).
Nine bake tests pass, including actual projection/image variation, UV guards, matching
cage, wrong topology, failed bake cleanup and source retention. Rendered seam/native
convention acceptance is separate from these mechanical checks.

## Owned workers and transport

`JobManager(..., enable_rigify=True)`, batch `--enable-rigify`, and MCP startup
`--enable-rigify` explicitly load bundled Rigify in owned background jobs. The flag is
off by default and is not a tool-supplied executable/add-on path. No live preference
is changed or saved. Real testing first exposed Rigify's requirement for an in-memory
preference entry; initialization now creates that entry only in the background process.
The actual worker test generates a stock human rig, persists its derivative, preserves
the source file hash and confirms no `userpref.blend` was saved.

MCP responses are also limited to 1 MiB. Oversized replies produce a bounded error that
explicitly does not imply rollback; inspect owned job files for retained output.
The regression first emitted an oversized response and now passes. Input and output
bounds do not turn the process into an OS filesystem sandbox.

## Actual full-frame 8K probe

`scripts/render_resolution_probe.py` rendered the retained cabinet review scene to an
actual **8192×8192 PNG (67,108,864 pixels)**. CPU Cycles used eight threads, 16 samples,
denoising and AgX; the observed render/save took 447.577 s. The output was 61,819,181 bytes.
PNG signature/IHDR and source-file SHA256 were checked after saving.

- [Full-resolution image](../artifacts/resolution-probe/20261030T164444Z-2bb30280/cabinet-8192.png).
- [Exact receipt](../artifacts/resolution-probe/20261030T164444Z-2bb30280/receipt.json).
- Image SHA256: `a0cfe1d4da44272fab9b422978ee90adaf9596a9570a6438705fdd06fbf45cdc`.

This is resolution/output evidence, not an 8K-texture or AAA-quality certificate.
The smaller source review views were inspected. Model-side display of this 61 MB PNG
hit an image-transport limit; browser inspection was unavailable because local browser
use is disabled. The full file was queued in Codex for user inspection. No setting
was changed to bypass that restriction. The temporary local preview server was stopped.

A later independent Pillow 12.3.0 check verified all PNG chunks and decoded the entire
8192×8192 RGBA image, with unchanged SHA256; see
[decode receipt](../artifacts/resolution-probe/20261030T164444Z-2bb30280/decode-verification.json).
This checks file integrity, not appearance. A native viewer attempt could not activate
because the Windows desktop was locked, so full-resolution visual review remains open.

## Licensed surface reference

The separate [8K material pilot](increment5-materials.md) uses downloaded source maps
from [Poly Haven Wooden Planks](https://polyhaven.com/a/wooden_planks), whose assets are
[CC0](https://polyhaven.com/license). The publisher credits Charlotte Baglioni for
photography and Dario Barresi for processing, and reports a 2 m width (about 41 px/cm at 8K).
The pilot's 2 m plane matches that published scale; independent physical calibration
remains unverified. Download sizes/publisher MD5 and locally computed SHA256 are retained
in the ignored source receipt. **Powered by Poly Haven**; its public API supplied the
download metadata. Reference images and Blender artifacts are excluded from the ZIP.

Final aggregate, install/upgrade/rollback and archive receipts are recorded in
[verification](verification.md) only after those checks run.

## Export publication failures

Two further failing Blender regressions exposed export cleanup deleting changed
output bytes after a partial write or receipt failure. Publication now uses exclusive
binary writes, keeps file identities and removes a partial file only when its bytes
match the intended prefix. Rollback of a completed asset/receipt additionally requires
its full size and SHA256. Changed, replaced or ambiguous files remain for inspection;
cleanup errors preserve the original failure. This is defensive cooperative-writer
handling, not an atomic multi-file transaction or an OS sandbox.

The eight final regressions and five independent GLB/FBX interchange checks pass after
the fix. Normal export source hashes, scoped output and cold geometry/skin/motion
comparisons remain verified.

The aggregate runner now fingerprints runtime code, test/scripts, benchmark/example
inputs and dependency configuration before running. A changed input prevents a complete
receipt; three tests cover changes, new modules and exclusion of generated files.
Final receipts record the exact source snapshot. CI actions use immutable revisions
resolved from their existing official release tags, minimal read permission and a
15-minute job limit. CI configuration is not evidence that remote jobs have run.
