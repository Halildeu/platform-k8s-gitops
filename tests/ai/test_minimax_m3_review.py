#!/usr/bin/env python3
"""Unit tests for fail-closed MiniMax response parsing (no provider call)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
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

    def test_rejects_priority_names_embedded_in_prose(self) -> None:
        self.assert_rejected(
            "Bu cevapta P0 ve P1 ile P2 bölümleri yoktur.\nVERDICT: AGREE"
        )


class LocalTrustPathTests(unittest.TestCase):
    def test_accepts_owned_nonwritable_parent_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / ".builtin-skills/llm-call/scripts"
            nested.mkdir(parents=True, mode=0o700)
            target = nested / "llm_call.py"
            target.write_text("x = 1\n", encoding="utf-8")
            os.chmod(target, 0o600)
            previous = MODULE.MAVIS_DATA_DIR
            MODULE.MAVIS_DATA_DIR = root
            try:
                self.assertEqual(
                    MODULE.validate_local_trust_file(target, "test"),
                    target.resolve(),
                )
            finally:
                MODULE.MAVIS_DATA_DIR = previous

    def test_rejects_group_writable_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "unsafe/scripts"
            nested.mkdir(parents=True, mode=0o700)
            target = nested / "llm_call.py"
            target.write_text("x = 1\n", encoding="utf-8")
            os.chmod(target, 0o600)
            os.chmod(nested.parent, 0o770)
            previous = MODULE.MAVIS_DATA_DIR
            MODULE.MAVIS_DATA_DIR = root
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        MODULE.validate_local_trust_file(target, "test")
            finally:
                MODULE.MAVIS_DATA_DIR = previous


class TransportDigestTests(unittest.TestCase):
    def test_accepts_exact_pinned_transport_bytes(self) -> None:
        source = b"reviewed transport bytes"
        previous = MODULE.EXPECTED_TRANSPORT_SHA256
        MODULE.EXPECTED_TRANSPORT_SHA256 = MODULE.hashlib.sha256(source).hexdigest()
        try:
            self.assertEqual(
                MODULE.validate_transport_digest(source),
                MODULE.EXPECTED_TRANSPORT_SHA256,
            )
        finally:
            MODULE.EXPECTED_TRANSPORT_SHA256 = previous

    def test_rejects_unpinned_transport_bytes(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.validate_transport_digest(b"replacement transport")

if __name__ == "__main__":
    unittest.main()
