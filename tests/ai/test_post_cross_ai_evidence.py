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
        "schema": "cross-ai-provider-evidence/v3",
        "provider": "openai",
        "requested_model": "gpt-5.6-sol",
        "actual_model": "not-provider-attested",
        "execution_profile": "codex-exec-ephemeral-read-only-exact-scope-no-tools-v2",
        "execution_provenance": {
            "schema": "codex-native-execution-provenance/v1",
            "thread_id": "019f7785-c66d-7992-a21a-d4097d9eb3f9",
            "cli_version": "0.144.1",
            "cli_native_target": "codex-linux-x64",
            "cli_native_sha256": "a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902",
            "trust_root": "repo-pinned-codex-native-sha256-v1",
            "stderr_classification": "empty",
        },
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

    def test_accepts_exact_spark_model(self) -> None:
        payload = evidence()
        payload["requested_model"] = "gpt-5.3-codex-spark"
        payload["actual_model"] = "not-provider-attested"
        parsed, _ = MODULE.validate_evidence_text(
            json.dumps(payload, separators=(",", ":"))
        )
        self.assertEqual(parsed["requested_model"], "gpt-5.3-codex-spark")

    def test_rejects_extra_schema_key(self) -> None:
        payload = evidence()
        payload["untrusted"] = True
        self.assert_rejected(payload)

    def test_rejects_response_digest_mismatch(self) -> None:
        payload = evidence()
        payload["response_sha256"] = "f" * 64
        self.assert_rejected(payload)

    def test_rejects_non_isolated_codex_execution_profile(self) -> None:
        payload = evidence()
        payload["execution_profile"] = "codex-current-chat"
        self.assert_rejected(payload)

    def test_rejects_provider_model_mismatch_before_post(self) -> None:
        payload = evidence()
        payload["actual_model"] = "auto"
        self.assert_rejected(payload)

    def test_rejects_requested_model_repeated_as_provider_attested_actual(self) -> None:
        payload = evidence()
        payload["actual_model"] = payload["requested_model"]
        self.assert_rejected(payload)

    def test_rejects_unpinned_native_binary_provenance(self) -> None:
        payload = evidence()
        payload["execution_provenance"]["cli_native_sha256"] = "f" * 64
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
