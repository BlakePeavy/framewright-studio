"""Verify release bytes match intended runtime sources; exclude private artifacts."""

import argparse
import ast
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


def audit_archive(archive, source):
    archive = Path(archive)
    source = Path(source)
    expected = {
        file.relative_to(source).as_posix(): file
        for file in source.rglob("*")
        if file.is_file()
        and "__pycache__" not in file.parts
        and (file.suffix in {".py", ".toml"} or file.name == "LICENSE")
    }
    receipts = []
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP names")
        if set(names) != set(expected):
            raise ValueError("Archive differs from expected runtime file set")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
                raise ValueError("Unsafe archive path")
            data = zipped.read(name)
            if data != expected[name].read_bytes():
                raise ValueError(f"Stale or modified archive member: {name}")
            receipts.append(
                {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            )
        manifest = tomllib.loads(zipped.read("blender_manifest.toml").decode())
        tree = ast.parse(zipped.read("__init__.py").decode())
        version = next(
            (
                node.value.value
                for node in tree.body
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and any(
                    isinstance(target, ast.Name) and target.id == "__version__"
                    for target in node.targets
                )
            ),
            None,
        )
        if version != manifest["version"]:
            raise ValueError("Runtime/manifest version mismatch")
        if manifest.get("license") != ["SPDX:GPL-3.0-or-later"]:
            raise ValueError("Unexpected license declaration")
        if b"GNU GENERAL PUBLIC LICENSE" not in zipped.read("LICENSE"):
            raise ValueError("Missing packaged license")
    return {
        "version": version,
        "archive": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": sorted(receipts, key=lambda item: item["path"]),
        "runtime_dependencies": "Python standard library and Blender bundled modules only",
        "private_asset_files": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--source", default="framewright", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = audit_archive(args.zip, args.source)
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"RELEASE_AUDIT_OK version={result['version']} files={len(result['files'])} sha256={result['sha256']}"
    )


if __name__ == "__main__":
    main()
