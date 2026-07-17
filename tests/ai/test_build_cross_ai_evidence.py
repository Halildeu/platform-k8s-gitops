#!/usr/bin/env python3
"""Regression tests for provider evidence body construction."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/build_cross_ai_evidence.py"
SHA = "a" * 40
SCOPE = "b" * 64
BASE_ARGS = [
    sys.executable,
    str(SCRIPT),
    "--provider",
    "anthropic",
    "--requested-model",
    "claude-opus-4-8",
    "--actual-model",
    "claude-opus-4-8",
    "--base-tip-sha",
    SHA,
    "--base-sha",
    SHA,
    "--head-sha",
    SHA,
    "--scope-sha256",
    SCOPE,
]


class EvidenceBuilderTests(unittest.TestCase):
    def run_builder(self, response: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            BASE_ARGS,
            input=response,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_builds_strict_agree_evidence(self) -> None:
        result = self.run_builder("P0\nYok\nP1\nYok\nP2\nYok\nVERDICT: AGREE")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "cross-ai-provider-evidence/v1")
        self.assertEqual(payload["verdict"], "AGREE")
        self.assertEqual(payload["scope_sha256"], SCOPE)

    def test_preserves_revise_without_fabricating_agree(self) -> None:
        result = self.run_builder("P0\nBulgu\nP1\nYok\nP2\nYok\nVERDICT: REVISE")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["verdict"], "REVISE")

    def test_rejects_nonterminal_verdict(self) -> None:
        result = self.run_builder("P0\nP1\nP2\nVERDICT: AGREE\nson söz")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
