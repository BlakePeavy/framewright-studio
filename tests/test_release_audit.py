import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.audit_release import audit_archive


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.files = {
            "__init__.py": b'__version__ = "0.2.0"\n',
            "blender_manifest.toml": b'id="framewright_studio"\nversion="0.2.0"\nlicense=["SPDX:GPL-3.0-or-later"]\n',
            "LICENSE": b"GNU GENERAL PUBLIC LICENSE",
        }
        for name, data in self.files.items():
            (self.source / name).write_bytes(data)

    def archive(self, changes=None):
        archive = self.root / "release.zip"
        with zipfile.ZipFile(archive, "w") as output:
            for name, data in {**self.files, **(changes or {})}.items():
                output.writestr(name, data)
        return archive

    def test_exact_source_contents_pass(self):
        result = audit_archive(self.archive(), self.source)
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(len(result["files"]), 3)

    def test_private_or_unknown_files_refused(self):
        for extra in [".env", "secret.blend", "../escape.py", "C:/escape.py"]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                audit_archive(self.archive({extra: b"secret"}), self.source)

    def test_stale_archive_cannot_pass(self):
        with self.assertRaises(ValueError):
            audit_archive(self.archive({"__init__.py": b'__version__="0.1.0"'}), self.source)


if __name__ == "__main__":
    unittest.main()
