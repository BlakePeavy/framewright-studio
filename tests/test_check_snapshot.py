import json
from pathlib import Path

import pytest

from scripts import check
from scripts.check import source_snapshot


def fixture(root: Path):
    for name in ("framewright", "scripts", "tests", "artifacts", "dist"):
        (root / name).mkdir()
    (root / "framewright/core.py").write_text("VALUE = 1\n")
    (root / "scripts/check.py").write_text("# fixture\n")
    (root / "tests/test_core.py").write_text("assert True\n")
    (root / "pyproject.toml").write_text('[project]\nname="fixture"\n')


def test_snapshot_changes_with_runtime_tests_config_or_added_modules(tmp_path):
    fixture(tmp_path)
    before = source_snapshot(tmp_path)
    for relative in (
        "framewright/core.py",
        "tests/test_core.py",
        "pyproject.toml",
        "framewright/new.py",
    ):
        path = tmp_path / relative
        original = path.read_bytes() if path.exists() else None
        path.write_text("# changed\n")
        assert source_snapshot(tmp_path)["sha256"] != before["sha256"]
        if original is None:
            path.unlink()
        else:
            path.write_bytes(original)
    assert source_snapshot(tmp_path) == before


def test_generated_outputs_caches_and_docs_do_not_change_tested_source_snapshot(tmp_path):
    fixture(tmp_path)
    before = source_snapshot(tmp_path)
    (tmp_path / "artifacts/report.json").write_text("{}")
    (tmp_path / "dist/extension.zip").write_bytes(b"fixture")
    (tmp_path / "readme.md").write_text("Updated evidence")
    cache = tmp_path / "framewright/__pycache__"
    cache.mkdir()
    (cache / "core.pyc").write_bytes(b"cache")
    assert source_snapshot(tmp_path) == before


def test_runner_refuses_complete_receipt_when_source_changes_during_checks(tmp_path, monkeypatch):
    fixture(tmp_path)
    receipt = tmp_path / "verification.json"
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check.sys, "argv", ["check.py", "--receipt", str(receipt)])

    def changed_during_run(args, parser):
        (tmp_path / "framewright/core.py").write_text("VALUE = 2\n")

    monkeypatch.setattr(check, "check", changed_during_run)
    with pytest.raises(RuntimeError, match="changed during verification"):
        check.main()
    result = json.loads(receipt.read_text())
    assert not result["complete"]
    assert not result["source_unchanged"]
