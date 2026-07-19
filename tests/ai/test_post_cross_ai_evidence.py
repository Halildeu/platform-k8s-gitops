#!/usr/bin/env python3
"""Unit tests for secret-safe Cross-AI evidence posting validation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/post_cross_ai_evidence.py"
SPEC = importlib.util.spec_from_file_location("post_cross_ai_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def evidence() -> dict:
    response = "## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE"
    return {
        "schema": "cross-ai-provider-evidence/v2",
        "provider": "openai",
        "requested_model": "gpt-5.6-sol",
        "actual_model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "sandbox": "read-only",
        "ephemeral": True,
        "base_tip_sha": "a" * 40,
        "base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "scope_sha256": "d" * 64,
        "verdict": "AGREE",
        "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
        "response": response,
    }


class EvidenceValidationTests(unittest.TestCase):
    def assert_rejected(self, payload: dict) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.validate_evidence_text(json.dumps(payload))

    def test_accepts_exact_builder_schema_and_digest(self) -> None:
        text = json.dumps(evidence(), separators=(",", ":"))
        parsed, digest = MODULE.validate_evidence_text(text)
        self.assertEqual(parsed["provider"], "openai")
        self.assertEqual(digest, hashlib.sha256(text.encode()).hexdigest())

    def test_rejects_extra_schema_key(self) -> None:
        payload = evidence()
        payload["untrusted"] = True
        self.assert_rejected(payload)

    def test_rejects_response_digest_mismatch(self) -> None:
        payload = evidence()
        payload["response_sha256"] = "f" * 64
        self.assert_rejected(payload)

    def test_rejects_external_agree_when_response_terminal_verdict_is_revise(self) -> None:
        payload = evidence()
        payload["response"] = (
            "P0\nConcrete finding\nP1\nNone\nP2\nNone\nVERDICT: REVISE"
        )
        payload["response_sha256"] = hashlib.sha256(
            payload["response"].encode("utf-8")
        ).hexdigest()
        self.assert_rejected(payload)

    def test_rejects_malformed_or_nonterminal_provider_response(self) -> None:
        for response in (
            "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE\nextra",
            "P0\nNone\nP1\nNone\nVERDICT: AGREE",
            "P0\nFinding\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            "P0\nNone\nP1\nNone\nP2\nLow finding\nVERDICT: AGREE",
        ):
            payload = evidence()
            payload["response"] = response
            payload["response_sha256"] = hashlib.sha256(
                response.encode("utf-8")
            ).hexdigest()
            with self.subTest(response=response):
                self.assert_rejected(payload)

    def test_rejects_wrong_provider_model_or_execution_identity(self) -> None:
        mutations = (
            {"provider": "anthropic"},
            {"requested_model": "claude-opus-4-8", "actual_model": "claude-opus-4-8"},
            {"reasoning_effort": "high"},
            {"sandbox": "workspace-write"},
            {"ephemeral": False},
        )
        for mutation in mutations:
            payload = evidence()
            payload.update(mutation)
            with self.subTest(mutation=mutation):
                self.assert_rejected(payload)

    def test_rejects_sensitive_response_before_gh_invocation(self) -> None:
        for value in (
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
        ):
            payload = evidence()
            payload["response"] = (
                f"P0\nNone\nP1\nNone\nP2\n{value}\nVERDICT: AGREE"
            )
            payload["response_sha256"] = hashlib.sha256(
                payload["response"].encode("utf-8")
            ).hexdigest()
            with self.subTest(value=value):
                self.assert_rejected(payload)


if __name__ == "__main__":
    unittest.main()
