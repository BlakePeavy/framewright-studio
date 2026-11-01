"""Caller-selected native admission budgets; pure parsing, no engine execution."""

# Imported pytest fixture is intentionally reused as injected parameter names.
# ruff: noqa: F811

import copy
import hashlib
import io
import json
import struct
import tracemalloc
import zlib
from pathlib import Path

import pytest
from test_native_handoff import digest, glb, handoff, pbr_glb, png  # noqa: F401

from framewright import native_handoff as native
from scripts.prepare_native_import import main


def compile_fixture(fixture, **budgets):
    path, game, kit, _ = fixture
    return native.compile_plan(path, project_root=game, source_root=kit, **budgets)


def with_pbr(fixture):
    path, _, kit, document = fixture
    payload = pbr_glb()
    source = kit / "part.glb"
    source.write_bytes(payload)
    record = {"path": str(source), "bytes": len(payload), "sha256": digest(payload)}
    document["exports"][0]["file"] = record
    document["verified_now"]["files"][-1] = record
    path.write_text(json.dumps(document))
    return fixture


def reseal(plan):
    plan["plan_sha256"] = native._hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def test_default_budgets_remain_conservative_and_recorded(handoff):
    plan = compile_fixture(handoff)
    assert plan["schema_version"] == "1.1"
    assert plan["admission_budgets"] == {
        "max_glb_bytes": 64 * 1024**2,
        "max_total_image_pixels": 2 * 8192**2,
    }
    assert native.verify_plan(plan) == plan


def test_explicit_budgets_are_deterministic_and_verified_without_changing_defaults(handoff):
    limits = {"max_glb_bytes": 512 * 1024**2, "max_total_image_pixels": 3 * 8192**2}
    plan = compile_fixture(handoff, **limits)
    assert plan["admission_budgets"] == limits
    assert compile_fixture(handoff, **limits) == plan
    assert native.verify_plan(plan) == plan
    assert compile_fixture(handoff)["admission_budgets"]["max_glb_bytes"] == 64 * 1024**2


def test_actual_small_glb_byte_boundary_and_zero_image_allowance():
    payload = glb()
    assert (
        native.inspect_glb(payload, max_glb_bytes=len(payload), max_total_image_pixels=0)[
            "triangles"
        ]
        == 1
    )
    with pytest.raises(ValueError, match="GLB byte budget"):
        native.inspect_glb(payload, max_glb_bytes=len(payload) - 1)


def test_aggregate_pixel_budget_counts_all_actual_images_and_exact_boundary():
    payload = pbr_glb()
    assert native.inspect_glb(payload, max_total_image_pixels=18)["images"] == 3
    with pytest.raises(ValueError, match="Aggregate image pixel budget"):
        native.inspect_glb(payload, max_total_image_pixels=17)
    with pytest.raises(ValueError, match="Aggregate image pixel budget"):
        native.inspect_glb(payload, max_total_image_pixels=0)


def test_png_budget_refuses_at_dimensions_before_decompression(monkeypatch):
    def unexpected_decode():
        raise AssertionError("Out-of-budget PNG must not be decompressed")

    payload = pbr_glb()  # JPEG 6 pixels, then two PNGs of 6 pixels each.
    monkeypatch.setattr(native.zlib, "decompressobj", unexpected_decode)
    with pytest.raises(ValueError, match="Aggregate image pixel budget"):
        native.inspect_glb(payload, max_total_image_pixels=6)


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_glb_bytes", value)
        for value in (None, True, False, 27, -1, 512 * 1024**2 + 1, 64.0, "67108864")
    ]
    + [
        ("max_total_image_pixels", value)
        for value in (None, True, False, -1, 8 * 8192**2 + 1, 18.0, "18")
    ],
)
def test_typed_bounded_budgets_reject_before_parsing_or_filesystem(key, value, monkeypatch):
    with pytest.raises(ValueError, match="budget"):
        native.inspect_glb(glb(), **{key: value})

    def unexpected_path(*args, **kwargs):
        raise AssertionError("Invalid budgets must fail before path resolution")

    monkeypatch.setattr(native, "_path", unexpected_path)
    with pytest.raises(ValueError, match="budget"):
        native.compile_plan("unused", project_root="unused", source_root="unused", **{key: value})


def test_hard_ceiling_values_are_accepted_without_allocating_large_fixture():
    assert (
        native.inspect_glb(glb(), max_glb_bytes=512 * 1024**2, max_total_image_pixels=8 * 8192**2)[
            "triangles"
        ]
        == 1
    )


def test_compiler_enforces_selected_file_and_image_budgets(handoff):
    with pytest.raises(ValueError, match="budget"):
        compile_fixture(handoff, max_glb_bytes=len(glb()) - 1)
    fixture = with_pbr(handoff)
    with pytest.raises(ValueError, match="Aggregate image pixel budget"):
        compile_fixture(fixture, max_total_image_pixels=17)
    assert (
        native.verify_plan(compile_fixture(fixture, max_total_image_pixels=18))["geometry"][
            "images"
        ]
        == 3
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"max_glb_bytes": True, "max_total_image_pixels": 18},
        {"max_glb_bytes": 512 * 1024**2 + 1, "max_total_image_pixels": 18},
        {"max_glb_bytes": 64 * 1024**2, "max_total_image_pixels": 18, "unbounded": True},
    ],
)
def test_resealed_plan_cannot_smuggle_invalid_budget_shape_or_values(handoff, value):
    plan = compile_fixture(handoff)
    plan["admission_budgets"] = value
    with pytest.raises(ValueError, match="budget"):
        native.verify_plan(reseal(plan))


def test_resealed_plan_with_tighter_budget_rechecks_actual_source(handoff):
    plan = compile_fixture(with_pbr(handoff), max_total_image_pixels=18)
    plan["admission_budgets"]["max_total_image_pixels"] = 17
    with pytest.raises(ValueError, match="Aggregate image pixel budget"):
        native.verify_plan(reseal(plan))


def test_changed_budget_digest_and_missing_legacy_budget_refuse(handoff):
    plan = compile_fixture(handoff)
    changed = copy.deepcopy(plan)
    changed["admission_budgets"]["max_glb_bytes"] += 1
    with pytest.raises(ValueError, match="digest"):
        native.verify_plan(changed)
    del plan["admission_budgets"]
    with pytest.raises(ValueError, match="fields"):
        native.verify_plan(reseal(plan))


def test_nondefault_plan_still_rejects_stale_source_bytes(handoff):
    plan = compile_fixture(handoff, max_glb_bytes=512 * 1024**2, max_total_image_pixels=3 * 8192**2)
    (handoff[2] / "part.glb").write_bytes(glb() + b"stale")
    with pytest.raises(ValueError, match="receipt"):
        native.verify_plan(plan)


def test_hash_read_stops_at_selected_budget_even_if_stream_grows_after_stat(handoff, monkeypatch):
    source = handoff[2] / "part.glb"
    payload = source.read_bytes()
    calls = []

    class GrowingStream(io.BytesIO):
        def read(self, size=-1):
            calls.append(size)
            return super().read(size)

    original = Path.open

    def opening(path, *args, **kwargs):
        if path == source:
            return GrowingStream(payload + b"grew after stat")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(ValueError, match="budget"):
        native._record(source, maximum=len(payload))
    assert calls and all(0 < size <= len(payload) + 1 for size in calls)


def test_compile_uses_bounded_source_read_after_hash_preflight(handoff, monkeypatch):
    source = handoff[2] / "part.glb"
    original = Path.read_bytes

    def reading(path):
        if path == source:
            raise AssertionError("Source parsing must use a bounded stream read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", reading)
    assert compile_fixture(handoff, max_glb_bytes=len(glb()))["geometry"]["triangles"] == 1


def test_large_png_idat_is_fed_to_decoder_in_bounded_input_chunks(monkeypatch):
    # One valid incompressible IDAT reproduces the actual 8K export's layout
    # at <200 KiB, without a giant synthetic texture or a timing assertion.
    pixels = hashlib.shake_256(b"bounded PNG decoder input").digest(256 * 256 * 3)
    rows = b"".join(b"\0" + pixels[i : i + 768] for i in range(0, len(pixels), 768))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
    image += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    payload = pbr_glb(image_change=lambda images: images.__setitem__(1, image))
    original = zlib.decompressobj

    class BoundedDecoder:
        def __init__(self):
            self.decoder = original()

        def __getattr__(self, name):
            return getattr(self.decoder, name)

        def decompress(self, data, maximum):
            assert len(data) <= 65536, "Large IDAT causes repeated full-tail allocations"
            return self.decoder.decompress(data, maximum)

    monkeypatch.setattr(native.zlib, "decompressobj", BoundedDecoder)
    assert native.inspect_glb(payload)["images"] == 3


def test_many_empty_png_chunks_do_not_accumulate_retained_views():
    # Valid consecutive empty IDAT chunks need no retained per-chunk objects.
    # The 144 KB input is allocated before tracing; allow ample decoder scratch.
    base = png()
    empty = struct.pack(">I4sI", 0, b"IDAT", zlib.crc32(b"IDAT"))
    payload = base[:33] + empty * 12_000 + base[33:]
    tracemalloc.start()
    try:
        assert native._image_size(payload, "image/png", remaining_pixels=6) == (2, 3)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024**2, "PNG metadata chunk count amplified retained memory"


def cli_args(fixture, output):
    path, game, kit, _ = fixture
    return [
        "--handoff",
        str(path),
        "--project-root",
        str(game),
        "--source-root",
        str(kit),
        "--output",
        str(output),
    ]


def test_cli_explicit_budget_flags_publish_exact_validated_limits(handoff, tmp_path):
    output = tmp_path / "budget-plan.json"
    assert (
        main(
            cli_args(handoff, output)
            + ["--max-glb-bytes", str(512 * 1024**2), "--max-total-image-pixels", str(3 * 8192**2)]
        )
        == 0
    )
    plan = json.loads(output.read_text())
    assert plan["admission_budgets"] == {
        "max_glb_bytes": 512 * 1024**2,
        "max_total_image_pixels": 3 * 8192**2,
    }
    native.verify_plan(plan)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--max-glb-bytes", "536870913"),
        ("--max-total-image-pixels", "536870913"),
        ("--max-glb-bytes", "true"),
        ("--max-total-image-pixels", "18.0"),
    ],
)
def test_cli_invalid_budget_never_publishes_output(handoff, tmp_path, flag, value):
    output = tmp_path / "no-plan.json"
    with pytest.raises((ValueError, SystemExit)):
        main(cli_args(handoff, output) + [flag, value])
    assert not output.exists()
