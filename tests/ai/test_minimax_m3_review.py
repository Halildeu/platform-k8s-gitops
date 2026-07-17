#!/usr/bin/env python3
"""Unit tests for fail-closed MiniMax response parsing (no provider call)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/minimax_m3_review.py"
SPEC = importlib.util.spec_from_file_location("minimax_m3_review", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VerdictParsingTests(unittest.TestCase):
    def assert_rejected(self, response: str) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.parse_verdict(response)

    def test_accepts_single_terminal_verdict_with_priority_sections(self) -> None:
        response = "# P0\nYok.\n# P1\nYok.\n# P2\nYok.\nVERDICT: AGREE"
        self.assertEqual(MODULE.parse_verdict(response), "AGREE")

    def test_rejects_missing_verdict(self) -> None:
        self.assert_rejected("P0 yok\nP1 yok\nP2 yok")

    def test_rejects_ambiguous_verdict(self) -> None:
        self.assert_rejected(
            "P0 yok\nP1 yok\nP2 yok\nVERDICT: REVISE\nVERDICT: AGREE"
        )

    def test_rejects_non_terminal_verdict(self) -> None:
        self.assert_rejected("P0 yok\nP1 yok\nP2 yok\nVERDICT: AGREE\nson söz")

    def test_rejects_missing_priority_sections(self) -> None:
        self.assert_rejected("İnceleme tamam.\nVERDICT: AGREE")


if __name__ == "__main__":
    unittest.main()
