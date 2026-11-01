"""Host admission and observation checks for the local technical corpus."""

import copy
import json
from pathlib import Path

import pytest

from scripts import benchmark_production_corpus as corpus


@pytest.fixture
def fixture_manifest(tmp_path):
    folder = tmp_path / "artifacts" / "fixture"
    folder.mkdir(parents=True)
    source = folder / "fixture.blend"
    source.write_bytes(b"independent fixture bytes")
    identity = {
        "path": source.relative_to(tmp_path).as_posix(),
        "sha256": corpus.digest(source),
        "bytes": source.stat().st_size,
    }
    data = {
        "schema_version": "1.0",
        "corpus_id": "technical-fixtures",
        "corpus_version": 1,
        "fixtures": [
            {
                "id": "small-fixture",
                "version": 1,
                "source": identity,
                "dependencies": [],
                "receipts": [],
                "scene": "Fixture",
                "objects": ["Subject"],
                "scene_objects": ["Subject"],
                "provenance": {"artist_accepted": False, "native_verified": False},
                "operations": [
                    {
                        "id": "resources",
                        "requests": [{"command": "scene.resources", "params": {}}],
                        "expectations": [
                            {"path": "/responses/0/result/mesh_objects", "op": "eq", "value": 1}
                        ],
                    }
                ],
            }
        ],
    }
    return tmp_path, data


def test_manifest_verifies_actual_bytes(fixture_manifest):
    root, data = fixture_manifest
    assert corpus.validate_manifest(data, root) == data


@pytest.mark.parametrize("change", ["stale", "missing", "traversal", "absolute", "prefix"])
def test_source_paths_and_hashes_fail_closed(fixture_manifest, change):
    root, data = fixture_manifest
    source = data["fixtures"][0]["source"]
    if change == "stale":
        (root / source["path"]).write_bytes(b"changed")
    elif change == "missing":
        source["path"] = "artifacts/no.blend"
    elif change == "traversal":
        source["path"] = "artifacts/../fixture.blend"
    elif change == "absolute":
        source["path"] = str((root / source["path"]).resolve())
    else:
        source["path"] = "artifacts-sibling/fixture.blend"
    with pytest.raises((ValueError, FileNotFoundError)):
        corpus.validate_manifest(data, root)


@pytest.mark.parametrize(
    "change", ["command", "duplicate", "scope", "empty_checks", "art_label", "version", "nan"]
)
def test_invalid_manifest_contract_is_rejected(fixture_manifest, change):
    root, data = fixture_manifest
    fixture = data["fixtures"][0]
    operation = fixture["operations"][0]
    if change == "command":
        operation["requests"][0]["command"] = "asset.export"
    elif change == "duplicate":
        data["fixtures"].append(copy.deepcopy(fixture))
    elif change == "scope":
        fixture["objects"] = ["Absent"]
    elif change == "empty_checks":
        operation["expectations"] = []
    elif change == "art_label":
        fixture["provenance"]["artist_accepted"] = True
    elif change == "version":
        fixture["version"] = True
    else:
        operation["expectations"][0]["value"] = float("nan")
    with pytest.raises(ValueError):
        corpus.validate_manifest(data, root)


def test_expected_observations_reject_corruption_and_bool_number_alias():
    checks = [{"path": "/responses/0/result/count", "op": "eq", "value": 121}]
    payload = {"responses": [{"ok": True, "result": {"count": 121}}]}
    corpus.check_observations(payload, checks)
    payload["responses"][0]["result"]["count"] = 120
    with pytest.raises(AssertionError):
        corpus.check_observations(payload, checks)
    with pytest.raises(AssertionError):
        corpus.check_observations({"count": True}, [{"path": "/count", "op": "eq", "value": 1}])


def test_rule_length_and_bound_checks_are_explicit():
    payload = {"findings": [{"rule_id": "UV_MISSING"}], "samples": [1, 2], "penetrations": 3}
    checks = [
        {"path": "/findings", "op": "rule", "value": "UV_MISSING"},
        {"path": "/samples", "op": "len", "value": 2},
        {"path": "/penetrations", "op": "gte", "value": 1},
    ]
    corpus.check_observations(payload, checks)
    for check in checks:
        corrupt = {**check, "value": "ABSENT" if check["op"] == "rule" else 99}
        with pytest.raises(AssertionError):
            corpus.check_observations(payload, [corrupt])


def test_dependency_drift_is_not_hidden_by_unchanged_blend(fixture_manifest):
    root, data = fixture_manifest
    source = data["fixtures"][0]["source"]
    dependency = root / "artifacts/fixture/image.bin"
    dependency.write_bytes(b"texture")
    data["fixtures"][0]["dependencies"] = [
        {
            **source,
            "path": dependency.relative_to(root).as_posix(),
            "bytes": 7,
            "sha256": corpus.digest(dependency),
        }
    ]
    corpus.validate_manifest(data, root)
    dependency.write_bytes(b"changed")
    with pytest.raises(ValueError, match="identity"):
        corpus.validate_manifest(data, root)


def test_report_creation_refuses_overwrite(tmp_path):
    report = tmp_path / "report.json"
    corpus.write_new(report, {"kept": True})
    with pytest.raises(FileExistsError):
        corpus.write_new(report, {"kept": False})
    assert json.loads(report.read_text()) == {"kept": True}


def test_explicit_control_contract_cannot_inject_arbitrary_edits(fixture_manifest):
    root, data = fixture_manifest
    operation = data["fixtures"][0]["operations"][0]
    operation["control"] = {"kind": "python", "code": "anything"}
    with pytest.raises(ValueError):
        corpus.validate_manifest(data, root)


def test_manifest_rejects_symlink_escape(fixture_manifest):
    root, data = fixture_manifest
    external = root / "outside.blend"
    external.write_bytes(b"outside")
    link = root / "artifacts/escape.blend"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("This host cannot create file symlinks")
    data["fixtures"][0]["source"]["path"] = str(Path("artifacts") / link.name)
    with pytest.raises(ValueError):
        corpus.validate_manifest(data, root)


def test_manifest_file_bound_and_duplicate_fields_fail_before_decoding(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"same":1,"same":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        corpus.read_manifest(path)
    path.write_bytes(b" " * (1024**2 + 1))
    with pytest.raises(ValueError, match="bound"):
        corpus.read_manifest(path)


def test_nested_boolean_cannot_masquerade_as_count():
    with pytest.raises(AssertionError):
        corpus.check_observations(
            {"result": {"count": True}}, [{"path": "/result", "op": "eq", "value": {"count": 1}}]
        )


def test_active_blender_guard_records_pids_without_closing_anything(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='"blender.exe","123","Console","1","500 K"\n')

    monkeypatch.setattr(corpus.platform, "system", lambda: "Windows")
    monkeypatch.setattr(corpus.subprocess, "run", fake_run)
    assert corpus.active_blender_processes() == {"status": "measured", "processes": ["123"]}
    assert calls == [["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"]]


def test_allowed_idle_process_rejects_reused_pid_or_cpu_activity():
    before = [
        {"pid": 12, "creation_ticks_100ns": 50, "image_path": "blender.exe", "cpu_seconds": 1.0}
    ]
    after = [{**before[0], "cpu_seconds": 1.01}]
    assert corpus.idle_cpu_evidence(before, after, 0.1)[0]["cpu_seconds_delta"] == pytest.approx(
        0.01
    )
    for row in [
        {**after[0], "creation_ticks_100ns": 51},
        {**after[0], "cpu_seconds": 1.2},
        {**after[0], "image_path": "other.exe"},
    ]:
        with pytest.raises(RuntimeError):
            corpus.idle_cpu_evidence(before, [row], 0.1)


def test_idle_allowance_does_not_admit_unlisted_new_blender_process(monkeypatch):
    monkeypatch.setattr(
        corpus,
        "active_blender_processes",
        lambda: {"status": "measured", "processes": ["12", "13"]},
    )
    with pytest.raises(RuntimeError, match="unlisted"):
        corpus.idle_process_snapshot([12])


def test_windows_existing_process_counter_has_stable_start_and_monotonic_cpu():
    import os
    import platform

    if platform.system() != "Windows":
        pytest.skip("Windows process API")
    before = corpus.process_cpu_identity(os.getpid())
    sum(index * index for index in range(100000))
    after = corpus.process_cpu_identity(os.getpid())
    assert before["creation_ticks_100ns"] == after["creation_ticks_100ns"]
    assert after["cpu_seconds"] >= before["cpu_seconds"]
    assert Path(after["image_path"]).name.lower().endswith(".exe")
