from __future__ import annotations

import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/faz22-remote-ops/extract-exact-zip.py"


class ExtractExactZipTest(unittest.TestCase):
    def run_extractor(self, archive: Path, destination: Path, *expected: str) -> subprocess.CompletedProcess[str]:
        command = [
            "python3",
            str(SCRIPT),
            "--archive",
            str(archive),
            "--destination",
            str(destination),
        ]
        for name in expected:
            command.extend(("--expected-file", name))
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_extracts_only_exact_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            destination = root / "out"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("SHA256SUMS", "digest  evidence/item.json\n")
                output.writestr("evidence/item.json", "{}\n")

            result = self.run_extractor(
                archive, destination, "SHA256SUMS", "evidence/item.json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((destination / "evidence/item.json").read_text(), "{}\n")

    def test_rejects_unexpected_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("expected.json", "{}")
                output.writestr("unexpected.txt", "no")
            result = self.run_extractor(archive, root / "out", "expected.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out").exists())

    def test_rejects_missing_expected_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("one.json", "{}")
            result = self.run_extractor(
                archive, root / "out", "one.json", "missing.json"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out").exists())

    def test_rejects_duplicate_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("evidence.json", "one")
                output.writestr("evidence.json", "two")
            result = self.run_extractor(archive, root / "out", "evidence.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out").exists())

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.json", "{}")
            result = self.run_extractor(archive, root / "out", "../escape.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "escape.json").exists())

    def test_rejects_symlink_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            info = zipfile.ZipInfo("evidence.json")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr(info, "target")
            result = self.run_extractor(archive, root / "out", "evidence.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out").exists())

    def test_rejects_member_over_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr("evidence.json", "x" * 4096)
            command = [
                "python3",
                str(SCRIPT),
                "--archive",
                str(archive),
                "--destination",
                str(root / "out"),
                "--expected-file",
                "evidence.json",
                "--max-member-bytes",
                "1024",
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out").exists())

    def test_rejects_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "evidence.zip"
            destination = root / "out"
            destination.mkdir()
            sentinel = destination / "sentinel"
            sentinel.write_text("preserve")
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("evidence.json", "{}")
            result = self.run_extractor(archive, destination, "evidence.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
