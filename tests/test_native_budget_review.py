"""Independent bounded-read, byte-binding and container-allocation controls."""

# Imported fixture names are intentionally reused for pytest injection.
# ruff: noqa: F811

import json
import struct
from pathlib import Path

import pytest
from test_native_handoff import document, glb, handoff  # noqa: F401

from framewright import native_handoff as native
from scripts import unreal_import_static as entry


class GuardedPayload(bytes):
    """Observe a container payload copy without allocating a pathological input."""

    def __new__(cls, data, forbidden_start):
        instance = super().__new__(cls, data)
        instance.forbidden_start = forbidden_start
        return instance

    def __getitem__(self, key):
        if isinstance(key, slice) and key.start == self.forbidden_start:
            raise AssertionError("Invalid container payload copied before admission")
        return super().__getitem__(key)


def test_glb_extra_chunk_refuses_before_copying_unbounded_chunk_list():
    valid = glb()
    extra = struct.pack("<II", 4, 0x004E4942) + b"xxxx"
    payload = struct.pack("<III", 0x46546C67, 2, len(valid) + len(extra)) + valid[12:] + extra
    observed = GuardedPayload(payload, len(valid) + 8)
    with pytest.raises(ValueError, match="chunk|JSON|BIN"):
        native.inspect_glb(observed)


def test_glb_json_budget_refuses_before_copying_json_payload(monkeypatch):
    valid = glb()
    json_length = struct.unpack_from("<I", valid, 12)[0]
    monkeypatch.setattr(native, "MAX_JSON", json_length - 4)
    observed = GuardedPayload(valid, 20)
    with pytest.raises(ValueError, match="JSON|budget"):
        native.inspect_glb(observed)


class ObservedReader:
    """Fail the test if a guarded reader consumes beyond its selected allowance."""

    def __init__(self, stream, allowance, consumed):
        self.stream = stream
        self.allowance = allowance
        self.consumed = consumed

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def count(self, size):
        self.consumed.append(size)
        assert sum(self.consumed) <= self.allowance + 1, (
            "Input consumed beyond selected byte budget"
        )

    def read(self, size=-1):
        data = self.stream.read(size)
        self.count(len(data))
        return data

    def readinto(self, data):
        size = self.stream.readinto(data)
        self.count(size)
        return size


@pytest.mark.parametrize("kind", ["handoff", "project"])
def test_json_growth_between_hash_and_parse_cannot_escape_json_budget(handoff, monkeypatch, kind):
    path, game, kit, document = handoff
    target = path if kind == "handoff" else Path(document["target_project"]["project"]["path"])
    limit = path.stat().st_size
    monkeypatch.setattr(native, "MAX_JSON", limit)
    original_open = Path.open
    reads, consumed = 0, []

    def opened(selected, *args, **kwargs):
        nonlocal reads
        mode = args[0] if args else kwargs.get("mode", "r")
        if selected == target and mode == "rb":
            reads += 1
            if reads == 2:
                # File was admitted/hashed, then grows before the parse read.
                with original_open(target, "ab") as stream:
                    stream.write(b" " * (limit + 4096))
                return ObservedReader(original_open(selected, *args, **kwargs), limit, consumed)
        return original_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="budget|changed|receipt"):
        native.compile_plan(path, project_root=game, source_root=kit)
    assert reads >= 2, "Concurrent-growth control was not reached"
    assert sum(consumed) <= limit + 1


def test_glb_growth_after_parse_does_not_relax_selected_budget_for_rehash(handoff, monkeypatch):
    path, game, kit, _ = handoff
    target = kit / "part.glb"
    limit = target.stat().st_size
    original_inspect = native.inspect_glb
    original_open = Path.open
    armed = False
    consumed = []

    def inspect_then_grow(data, **kwargs):
        nonlocal armed
        result = original_inspect(data, **kwargs)
        with original_open(target, "ab") as stream:
            stream.write(b"x" * (limit + 4096))
        armed = True
        return result

    def opened(selected, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        stream = original_open(selected, *args, **kwargs)
        if armed and selected == target and mode == "rb":
            return ObservedReader(stream, limit, consumed)
        return stream

    monkeypatch.setattr(native, "inspect_glb", inspect_then_grow)
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="budget|changed|receipt"):
        native.compile_plan(path, project_root=game, source_root=kit, max_glb_bytes=limit)
    assert armed, "Post-parse growth control was not reached"
    assert sum(consumed) <= limit + 1


def test_same_size_transient_glb_cannot_bind_other_geometry_to_original_hash(handoff, monkeypatch):
    path, game, kit, _ = handoff
    target = kit / "part.glb"
    original_bytes = target.read_bytes()
    changed = document()
    changed["nodes"][0]["translation"][0] = 4  # Original is 1: same encoded size.
    changed_bytes = glb(changed)
    assert len(changed_bytes) == len(original_bytes) and changed_bytes != original_bytes
    original_open = Path.open
    reads = 0
    restored = False

    class RestoringReader:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            nonlocal restored
            payload = self.stream.read(size)
            with original_open(target, "wb") as stream:
                stream.write(original_bytes)
            restored = True
            return payload

    def opened(selected, *args, **kwargs):
        nonlocal reads
        mode = args[0] if args else kwargs.get("mode", "r")
        if selected == target and mode == "rb":
            reads += 1
            if reads == 2:
                with original_open(target, "wb") as stream:
                    stream.write(changed_bytes)
                return RestoringReader(original_open(selected, *args, **kwargs))
        return original_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="receipt|changed|hash|digest"):
        native.compile_plan(path, project_root=game, source_root=kit)
    assert restored, "Same-size parse-read mutation was not reached"
    with original_open(target, "rb") as stream:
        assert stream.read() == original_bytes


def test_in_editor_plan_growth_refuses_before_unbounded_read_or_backend(
    handoff, tmp_path, monkeypatch
):
    path, game, kit, _ = handoff
    plan = native.compile_plan(path, project_root=game, source_root=kit)
    target = tmp_path / "native-plan.json"
    target.write_text(json.dumps(plan))
    limit = target.stat().st_size
    report = tmp_path / "native-report.json"
    monkeypatch.setattr(entry, "MAX_JSON", limit)
    original_open = Path.open
    reads, consumed = 0, []

    def opened(selected, *args, **kwargs):
        nonlocal reads
        mode = args[0] if args else kwargs.get("mode", "r")
        if selected == target and mode == "rb":
            reads += 1
            if reads == 2:
                with original_open(target, "ab") as stream:
                    stream.write(b" " * (limit + 4096))
                return ObservedReader(original_open(selected, *args, **kwargs), limit, consumed)
        return original_open(selected, *args, **kwargs)

    def unexpected_backend(*args, **kwargs):
        raise AssertionError("Invalid plan must not construct a native backend")

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(entry, "UnrealStaticBackend", unexpected_backend)
    with pytest.raises(ValueError, match="budget|changed|receipt"):
        entry.main(["--plan", str(target), "--report", str(report)])
    assert reads >= 2 and sum(consumed) <= limit + 1
    assert not report.exists()
