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
    "openai",
    "--requested-model",
    "gpt-5.6-sol",
    "--actual-model",
    "gpt-5.6-sol",
    "--reasoning-effort",
    "xhigh",
    "--sandbox",
    "read-only",
    "--ephemeral",
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
        self.assertEqual(payload["schema"], "cross-ai-provider-evidence/v2")
        self.assertEqual(payload["provider"], "openai")
        self.assertEqual(payload["reasoning_effort"], "xhigh")
        self.assertEqual(payload["sandbox"], "read-only")
        self.assertIs(payload["ephemeral"], True)
        self.assertEqual(payload["verdict"], "AGREE")
        self.assertEqual(payload["scope_sha256"], SCOPE)

    def test_preserves_revise_without_fabricating_agree(self) -> None:
        result = self.run_builder("P0\nBulgu\nP1\nYok\nP2\nYok\nVERDICT: REVISE")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["verdict"], "REVISE")

    def test_accepts_routine_spark_model_with_same_execution_contract(self) -> None:
        args = [
            "gpt-5.3-codex-spark" if value == "gpt-5.6-sol" else value
            for value in BASE_ARGS
        ]
        result = subprocess.run(
            args,
            input="P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["actual_model"], "gpt-5.3-codex-spark")

    def test_rejects_claude_and_minimax_as_new_evidence_providers(self) -> None:
        provider_index = BASE_ARGS.index("openai")
        for provider in ("anthropic", "minimax"):
            args = list(BASE_ARGS)
            args[provider_index] = provider
            result = subprocess.run(
                args,
                input="P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            with self.subTest(provider=provider):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid choice", result.stderr)

    def test_requires_xhigh_read_only_ephemeral_execution_metadata(self) -> None:
        for removable in ("--reasoning-effort", "--sandbox", "--ephemeral"):
            args = list(BASE_ARGS)
            index = args.index(removable)
            del args[index:index + (1 if removable == "--ephemeral" else 2)]
            result = subprocess.run(
                args,
                input="P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            with self.subTest(removable=removable):
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_agree_when_any_priority_contains_a_finding(self) -> None:
        for response in (
            "P0\nCritical finding\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nHigh finding\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nNone\nP2\nLow finding\nVERDICT: AGREE",
        ):
            with self.subTest(response=response):
                result = self.run_builder(response)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "provider_agree_contains_priority_findings",
                )

    def test_rejects_priority_heading_with_finding_suffix(self) -> None:
        result = self.run_builder(
            "P0: Critical finding is present\nNone\nP1\nNone\nP2\nNone\n"
            "VERDICT: AGREE"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "provider_findings_sections_missing_empty_duplicate_or_out_of_order",
        )

    def test_rejects_text_before_first_priority_heading(self) -> None:
        result = self.run_builder(
            "Critical finding outside priority sections\n"
            "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "provider_findings_sections_missing_empty_duplicate_or_out_of_order",
        )

    def test_rejects_sensitive_provider_response_before_comment_build(self) -> None:
        values = (
            "person@example.com",
            "+90 532 123 45 67",
            "-----BEGIN " + "PRIVATE KEY-----",
            "Authorization: " + "Bearer " + "abcdefghijklmnop",
            "Bearer " + "abcdefghijklmnop",
            "eyJ" + "a" * 16 + "." + "b" * 16 + "." + "c" * 16,
            "AKIA" + "A" * 16,
            "ghp_" + "a" * 30,
            "sk-" + "a" * 30,
            "password=" + "a" * 16,
            "secret_access_key=" + "a" * 32,
            "service_account_key=" + "a" * 32,
            "webhook_url=https://example.invalid/" + "a" * 20,
            "Cookie: session=" + "a" * 20,
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
                    "provider_agree_contains_priority_findings",
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
            "VERDICT: REVISE"
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
        response = "P0\nNone\nP1\nNone\nP2\n" + ('"' * 35_000) + "\nVERDICT: REVISE"
        result = self.run_builder(response)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"], "evidence_comment_too_large"
        )


if __name__ == "__main__":
    unittest.main()
