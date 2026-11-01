# Independent EXR intake review: truncated scanline repair

The independent 2026-10-30 review reproduced a real completeness defect. A valid 3 × 2 RGB FLOAT, uncompressed scanline EXR was truncated by seven bytes at the final payload. Blender still returned a full-sized finite buffer, and the initial intake marked its decoding as verified. Buffer length and finiteness alone did not detect the missing payload. `scripts/test_exr_review.py` first failed on this real file before the fix.

Applied material recipes now validate the complete scanline container **before creating any Blender images or materials**. Metadata-only `inspect_texture_file` and recipe previews still accept complete supported headers without claiming a usable pixel container. The optional internal inspection flag `verify_exr_structure=True` performs the additional container check against the actual open file size and retains the existing file-identity/hash checks.

The validator checks the expected number of offset entries, row coverage and chunk-count consistency, offset bounds, chunk headers, declared payload extents, uncompressed byte counts and non-overlapping chunks. Offset entries are interpreted in increasing scanline order even when the physical chunks are stored in decreasing order; the supported compression modes determine rows per block. This follows the [official OpenEXR file layout](https://openexr.com/en/latest/OpenEXRFileLayout.html).

Work is bounded to a 1 MiB header, at most 65,536 offset entries and one eight-byte header read per chunk. The structure validator does not read or decompress pixel payloads. A maximum-row test measures exactly 1,048,576 bytes of table/chunk-header reads. Native Blender decoding and its finite-buffer check remain required afterward. Compressed payload semantics, decoder internals and intended source pixel values are not independently certified by the structural check.

The unreleased ambiguous `pixel_decode_verified` field has been replaced by three separate receipt fields:

| Field | Header preview | Structurally checked file | Successfully applied material |
| --- | --- | --- | --- |
| `container_structure_verified` | false | true | true |
| `finite_decoded_buffer_verified` | false | false | true |
| `codec_semantics_verified` | false | false | false |

The container report also includes chunk count, rows per chunk, covered rows, offset-table bytes and referenced payload bytes. Applying a recipe preserves the original texture bytes and existing/shared image data. Failed container admission allocates no Blender data; later load/finite-validation failure still removes only owned images/materials.

The separate EXR working-buffer estimate remains 36 bytes per pixel: 16 for decoded RGBA floats, 16 for the validation copy and 4 for a boolean finite mask. NumPy views do not add a second float copy. Decoder temporaries, metadata/Python overhead and GPU/runtime storage remain outside that estimate. Finite HDR ranges are reported without clamping. Base-color EXR remains refused pending an explicit linear-color workflow; this increment admits data maps only.

Independent real-file tests additionally verify HALF and FLOAT `Y` decoding, RGBA FLOAT values with alpha 0 and 0.2, and a Cycles emission readback of RGB data with alpha 0.25. The alpha cases preserve their RGB values; no alpha-mode runtime change was needed. These tests use tiny uncompressed files written from explicit known scanline bytes, independently of Blender's EXR writer.

Validation: **33 new pure structure cases**, **36 existing EXR intake cases**, and the **8 existing material tests** pass (77 tests plus 19 material subtests). The **6 original Blender EXR tests** and **4 independent Blender review tests** pass. Ruff checks pass. The three actual 4K cabinet DWAA data maps also pass the read-only container check: 128 chunks covering all 4,096 rows each. This is structural evidence for those source files, not a new rendered cabinet or native-engine acceptance claim.

Run the independent checks with:

```powershell
uv run --frozen python -m pytest tests/test_exr_intake.py tests/test_exr_structure.py tests/test_materials.py -q
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_exr_review.py
```
