from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/faz22-remote-ops/extract-cross-ai-browser-runtime.py"
SPEC = importlib.util.spec_from_file_location("cross_ai_browser_runtime", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BrowserRuntimeBundleTest(unittest.TestCase):
    def _archive(self, root: Path, *, symlink: bool = False) -> Path:
        archive = root / "runtime.tar"
        files = {
            "browser-runtime/runtime-manifest.json": json.dumps(
                {
                    "schemaVersion": "acik.cross-ai-browser-runtime.v1",
                    "playwrightVersion": "1.60.0",
                    "packageRoot": "browser-runtime",
                    "browsersPath": "browser-runtime/ms-playwright",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            "browser-runtime/package.json": b'{"private":true}',
            "browser-runtime/node_modules/playwright/package.json": (
                b'{"version":"1.60.0"}'
            ),
            "browser-runtime/ms-playwright/chromium-123/chrome": b"fixed-browser",
        }
        with tarfile.open(archive, "w") as bundle:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.uid = 0
                member.gid = 0
                member.mode = 0o755 if name.endswith("/chrome") else 0o644
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
            if symlink:
                member = tarfile.TarInfo("browser-runtime/escape")
                member.uid = 0
                member.gid = 0
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                bundle.addfile(member)
        os.chmod(archive, 0o600)
        return archive

    @staticmethod
    def _digest(path: Path) -> str:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    def test_extracts_only_exact_signed_runtime_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self._archive(root)
            output = root / "output"
            MODULE.extract_runtime(archive, self._digest(archive), output)
            self.assertEqual(
                (
                    output / "browser-runtime/node_modules/playwright/package.json"
                ).read_text(),
                '{"version":"1.60.0"}',
            )
            self.assertTrue(
                os.access(
                    output / "browser-runtime/ms-playwright/chromium-123/chrome",
                    os.X_OK,
                )
            )

    def test_rejects_digest_mismatch_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self._archive(root)
            with self.assertRaisesRegex(MODULE.RuntimeBundleError, "digest differs"):
                MODULE.extract_runtime(archive, "sha256:" + ("0" * 64), root / "output")
            self.assertFalse((root / "output").exists())

    def test_rejects_links_even_when_archive_digest_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self._archive(root, symlink=True)
            with self.assertRaisesRegex(
                MODULE.RuntimeBundleError, "links or special files"
            ):
                MODULE.extract_runtime(archive, self._digest(archive), root / "output")


if __name__ == "__main__":
    unittest.main()
