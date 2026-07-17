#!/usr/bin/env python3
"""Unit tests for deterministic scope safety predicates."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/prepare_cross_ai_scope.py"
SPEC = importlib.util.spec_from_file_location("prepare_cross_ai_scope", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BinaryScopeTests(unittest.TestCase):
    def test_rejects_standard_binary_diff_marker(self) -> None:
        patch = b"diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n"
        self.assertIsNotNone(MODULE.BINARY_DIFF_RE.search(patch))

    def test_rejects_git_binary_patch_marker(self) -> None:
        patch = b"diff --git a/a.bin b/a.bin\nGIT binary patch\nliteral 3\nabc\n"
        self.assertIsNotNone(MODULE.BINARY_DIFF_RE.search(patch))

    def test_text_diff_does_not_match_binary_marker(self) -> None:
        patch = b"diff --git a/a.txt b/a.txt\n+Binary files are discussed here\n"
        self.assertIsNone(MODULE.BINARY_DIFF_RE.search(patch))


if __name__ == "__main__":
    unittest.main()
