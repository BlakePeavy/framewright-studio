# Explicit PBR materials and 8K source pilot

Implemented a bounded FW-052 material recipe on 2026-10-30. It creates independent
Blender material/image datablocks from explicit existing textures. It does not infer
materials, download assets, assign source objects or claim rendered/native parity.

## API

`surfaces.create_pbr_material` dispatches to
`framewright.materials.create_pbr_material(params, context=None)`:

```json
{
  "name": "FW_PBR",
  "base_color_path": "<absolute local PNG/JPEG path>",
  "roughness_path": "<optional absolute local path>",
  "metallic_path": "<optional absolute local path>",
  "normal_path": "<optional absolute local path>",
  "normal_convention": "OPENGL",
  "max_memory_mb": 512,
  "dry_run": true
}
```

Base color is required; omit unused optional map fields. Names are 1–48 printable
characters. Paths must be absolute local files; explicit or resolved UNC paths are
rejected. PNG and 8-bit grayscale/RGB baseline/progressive JPEG are supported. Files
are limited to 1 GiB and dimensions to 65,536 pixels per axis. Inputs are never copied,
rewritten or packed by this function. MCP additionally scopes the four paths to its
configured asset root.

The pure preflight parses image dimensions from a bounded 1 MiB header, verifies PNG
IHDR shape/checksum, streams a complete SHA256 and detects ordinary changes during
inspection. A valid header is not a full image-decoder certification. Actual creation
requires Blender's main thread/Object Mode, verifies decoded dimensions/data, and
checks file hashes again after loading. Changed, undecodable or partially loaded
input fails with cleanup of only newly owned material/images.

The memory guard estimates **width × height × 4 channels × 4 bytes per map** before
any Blender allocation. `max_memory_mb` is 1–32,768, default 512. Each image is loaded
independently even if paths repeat, so each role counts separately. One 8192² map has
a 1 GiB RGBA-float estimate; the three-map pilot uses 3 GiB and explicitly requests
4096 MiB. This is decoded image-buffer accounting, not a cap on total process, decoder
temporaries, Cycles/GPU memory, caches or runtime residency.

## Material semantics and preservation

- Base color uses sRGB and feeds Principled Base Color. Alpha remains unconnected/opaque.
- Roughness and metallic use Non-Color images and explicit red-channel extraction.
- OpenGL tangent normals use Non-Color through a Tangent Normal Map node.
- DirectX normals are rejected. No unverified procedural Y-flip graph is silently exported.
- Every role owns a fresh image datablock; existing shared images are never recolored.
- The standalone material has a fake user so it survives save/reopen without object assignment.
  Ownership/UUID and the JSON recipe retain source paths, hashes, dimensions and color spaces.
- Mutating creation requires `dry_run:false`. Preview returns metadata/estimates without
  allocating Blender images/materials. Source objects, slots, materials and image files stay unchanged.

A real scoped GLB test finds embedded base-color, metallic/roughness and normal texture
bindings. The exporter combines separate scalar maps into its portable packing. This
establishes presence of the explicit glTF bindings; full pixel/render comparison,
FBX texture semantics, tangent seams and native Unreal material acceptance remain open.

## Test-first evidence

The first Python and background-Blender runs failed importing the missing materials
module. After implementation, **8 pure Python tests** and **7 real Blender tests** pass.
They cover PNG/JPEG dimensions, bounded/truncated headers, CRC, zero dimensions,
absolute-path/type restrictions, 8K budget boundaries, shared-image color preservation,
independent role images, exact source slots, unique names, actual JPEG decode, corrupted
full-image decode, a changed file during load, partial-load cleanup and GLB bindings.

A file-change test initially expected only a hash-mismatch message; Blender's lazy
loading correctly detected changed dimensions sooner. The fixture was changed to a
valid same-size image with different pixels so it explicitly exercises the hash gate.
Scoped Ruff lint/format passes. Local logs are `artifacts/materials-*.log`.

## Actual licensed 8K pilot

Selected evidence is in
[the rendered pilot folder](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/receipt.json):

- [Editable Blender file](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/wooden-planks-8k.blend).
- [512px neutral render](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/wooden-planks-neutral-512.png).
- [Independent cold verification](../artifacts/materials-pilot/20261030T165853Z-ba8f227a/cold-verification.json).

The supplied download receipt identifies Poly Haven `wooden_planks`, CC0-1.0, and
credits **Powered by Poly Haven**. Its source URLs and pinned hashes are retained in
`artifacts/reference-candidates/wooden_planks-8k/download-receipt.json`. The pilot loads
one diffuse JPEG and OpenGL-normal/roughness PNGs, all 8192×8192. Source SHA256 values
match the receipt after load, save and separate-process reopen; all images remain
external/unpacked. No reference texture bytes enter the release ZIP.

The material is assigned only to an owned 2 m UV test plane. That plane is an authoring
fixture matching the publisher's [reported 2m width](https://polyhaven.com/a/wooden_planks);
physical scan coverage has not been independently calibrated. Rendering uses Cycles CPU, 512×512,
32 samples, denoising, fixed seed 0, AgX/exposure 0/gamma 1, a 50 mm camera and two neutral
area lights. Exact settings and render/file hashes are in the receipt. Visual inspection
confirmed readable plank seams and surface variation without missing-texture colors.
This demonstrates shader use of the actual 8K sources; a 512px image does not resolve
all 8K detail or establish physical scale, calibrated appearance, AAA approval or engine parity.

## Reproduce

```powershell
uv run python -m unittest discover -s tests -p test_materials.py -v
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_materials.py
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_materials.py -- --pilot-source artifacts/reference-candidates/wooden_planks-8k --pilot-output artifacts/materials-pilot
```

Pilot mode uses the already-downloaded receipt/maps, creates a fresh UTC/UUID output
folder, renders/saves normally and cold-verifies the saved file. It makes no network
request and does not attach to a live editor or modify game content.
