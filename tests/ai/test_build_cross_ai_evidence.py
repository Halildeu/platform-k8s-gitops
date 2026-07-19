#!/usr/bin/env python3
"""Regression tests for the shared provider-response validator."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/build_cross_ai_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_cross_ai_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40
SCOPE = "b" * 64


class EvidenceBuilderTests(unittest.TestCase):
    def assert_validation_error(self, response: str, expected: str) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            MODULE.validate_provider_response(response)
        self.assertEqual(json.loads(output.getvalue())["error"], expected)

    def run_disabled_builder(self, provider: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--provider",
                provider,
                "--requested-model",
                "untrusted-model",
                "--actual-model",
                "untrusted-model",
                "--base-tip-sha",
                SHA,
                "--base-sha",
                SHA,
                "--head-sha",
                SHA,
                "--scope-sha256",
                SCOPE,
            ],
            input="P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_accepts_strict_agree_and_revise_responses(self) -> None:
        agree = "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE"
        revise = "P0\nBulgu\nP1\nYok\nP2\nYok\nVERDICT: REVISE"
        self.assertEqual(MODULE.validate_provider_response(agree), "AGREE")
        self.assertEqual(MODULE.validate_provider_response(revise), "REVISE")

    def test_direct_provider_evidence_builder_is_disabled_for_all_providers(self) -> None:
        for provider in ("openai", "anthropic", "minimax", "other"):
            with self.subTest(provider=provider):
                result = self.run_disabled_builder(provider)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "direct_provider_evidence_builder_disabled",
                )

    def test_rejects_agree_when_p0_or_p1_contains_a_finding(self) -> None:
        for response in (
            "P0\nCritical finding\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nHigh finding\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone.\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
        ):
            with self.subTest(response=response):
                self.assert_validation_error(
                    response,
                    "provider_agree_contains_p0_or_p1_findings",
                )

    def test_rejects_sensitive_provider_response(self) -> None:
        values = (
            "person@example.com",
            "+90 532 123 45 67",
            "-----BEGIN " + "PRIVATE KEY-----",
            "Bearer " + "abcdefghijklmnop",
            "eyJ" + "a" * 16 + "." + "b" * 16 + "." + "c" * 16,
            "ghp_" + "a" * 30,
            "password=" + "a" * 16,
            "webhook_url=https://example.invalid/" + "a" * 20,
            "Cookie: session=" + "a" * 20,
        )
        for value in values:
            with self.subTest(value=value):
                self.assert_validation_error(
                    f"P0\nNone\nP1\nNone\nP2\n{value}\nVERDICT: AGREE",
                    "provider_response_contains_sensitive_data",
                )

    def test_rejects_ambiguous_or_malformed_response(self) -> None:
        responses = (
            "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: agree",
            "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE\nson söz",
            "P1\nNone\nP0\nNone\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
        )
        for response in responses:
            with self.subTest(response=response):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                    MODULE.validate_provider_response(response)

    def test_rejects_oversized_response(self) -> None:
        response = "P0\nNone\nP1\nNone\nP2\n" + ("x" * 49_000) + "\nVERDICT: AGREE"
        self.assert_validation_error(response, "provider_response_too_large")


if __name__ == "__main__":
    unittest.main()
