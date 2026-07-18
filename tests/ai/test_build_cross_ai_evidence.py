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
        result = self.run_builder("P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "cross-ai-provider-evidence/v1")
        self.assertEqual(payload["verdict"], "AGREE")
        self.assertEqual(payload["scope_sha256"], SCOPE)

    def test_preserves_revise_without_fabricating_agree(self) -> None:
        result = self.run_builder("P0\nBulgu\nP1\nYok\nP2\nYok\nVERDICT: REVISE")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["verdict"], "REVISE")

    def test_rejects_agree_when_p0_or_p1_contains_a_finding(self) -> None:
        for response in (
            "P0\nCritical finding\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nHigh finding\nP2\nNone\nVERDICT: AGREE",
        ):
            with self.subTest(response=response):
                result = self.run_builder(response)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "provider_agree_contains_p0_or_p1_findings",
                )

    def test_rejects_sensitive_provider_response_before_comment_build(self) -> None:
        values = (
            "person@example.com",
            "+90 532 123 45 67",
            "-----BEGIN " + "PRIVATE KEY-----",
            "Authorization: " + "Bearer " + "abcdefghijklmnop",
            "Bearer " + "abcdefghijklmnop",
        )
        for value in values:
            with self.subTest(value=value):
                result = self.run_builder(
                    f"P0\nNone\nP1\nNone\nP2\n{value}\nVERDICT: AGREE"
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "provider_response_contains_sensitive_data",
                )

    def test_rejects_non_exact_none_sentinel_for_agree(self) -> None:
        for sentinel in ("None.", "none", "nOnE"):
            with self.subTest(sentinel=sentinel):
                result = self.run_builder(
                    f"P0\n{sentinel}\nP1\nNone\nP2\nNone\nVERDICT: AGREE"
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "provider_agree_contains_p0_or_p1_findings",
                )

    def test_rejects_nonterminal_verdict(self) -> None:
        result = self.run_builder("P0\nP1\nP2\nVERDICT: AGREE\nson söz")
        self.assertEqual(result.returncode, 1)

    def test_rejects_non_exact_verdict_case(self) -> None:
        for verdict in ("agree", "Agree", "revise", "Revise"):
            with self.subTest(verdict=verdict):
                result = self.run_builder(
                    f"P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: {verdict}"
                )
                self.assertEqual(result.returncode, 1)

    def test_rejects_priority_names_only_in_prose(self) -> None:
        result = self.run_builder(
            "Bu cevapta P0, P1 ve P2 bolumleri yok.\nVERDICT: AGREE"
        )
        self.assertEqual(result.returncode, 1)

    def test_rejects_empty_duplicate_or_out_of_order_priority_sections(self) -> None:
        for response in (
            "P0\nP1\nP2\nVERDICT: AGREE",
            "P0\nNone\nP1\nNone\nP1\nAgain\nP2\nNone\nVERDICT: AGREE",
            "P1\nNone\nP0\nNone\nP2\nNone\nVERDICT: AGREE",
        ):
            with self.subTest(response=response):
                self.assertEqual(self.run_builder(response).returncode, 1)

    def test_control_and_escape_characters_round_trip_in_json(self) -> None:
        response = (
            "P0\nNone\nP1\nNone\nP2\n"
            "None\u0001 and None\u2028 plus literal \\\\n remains escaped text\n"
            "VERDICT: AGREE"
        )
        result = self.run_builder(response)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["response"], response)

    def test_rejects_response_too_large_for_issue_comment_transport(self) -> None:
        response = "P0\nNone\nP1\nNone\nP2\n" + ("x" * 49_000) + "\nVERDICT: AGREE"
        result = self.run_builder(response)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"], "provider_response_too_large"
        )

    def test_rejects_json_escape_expansion_beyond_comment_limit(self) -> None:
        response = "P0\nNone\nP1\nNone\nP2\n" + ('"' * 35_000) + "\nVERDICT: AGREE"
        result = self.run_builder(response)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"], "evidence_comment_too_large"
        )


if __name__ == "__main__":
    unittest.main()
