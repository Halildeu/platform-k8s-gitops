from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.github_apps.cross_ai_deployment_policy.contract import REVIEW_PAYLOAD_TYPE_V2
from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_MODEL,
    CursorRunner,
    DirectClaudeRunner,
    DirectCodexRunner,
    ProviderExecutionReceipt,
    ProviderReviewIssuer,
    REVIEW_RESULT_SCHEMA_VERSION,
    ReviewCoordinates,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


REVIEW_RESULT = json.dumps(
    {
        "schemaVersion": REVIEW_RESULT_SCHEMA_VERSION,
        "verdict": "PARTIAL",
        "findingIds": [],
        "resolvedFindingIds": ["FINDING_A"],
        "acknowledgedFindingIds": ["FINDING_A"],
    },
    separators=(",", ":"),
)


class StaticSigner:
    def __init__(self, factory: FixtureFactory, key_id: str) -> None:
        self.factory = factory
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign_json_envelope(self, *, payload_type, payload):
        return self.factory.sign(payload_type, payload, self._key_id)


class ProviderExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_direct_claude_uses_provider_reported_model_usage(self) -> None:
        output = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": REVIEW_RESULT,
            "total_cost_usd": 0.1,
            "modelUsage": {"claude-opus-4-6": {"inputTokens": 1}},
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"2.1.0\n", stderr=b""),
            subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(output).encode(), stderr=b""
            ),
        ]
        with patch("subprocess.run", side_effect=calls):
            receipt = DirectClaudeRunner(Path("/bin/sh")).run(
                prompt="review this digest",
                model="claude-opus-4-6",
                workspace=self.workspace,
            )
        self.assertEqual(receipt.model_id, "claude-opus-4-6")
        self.assertEqual(receipt.model_identity_class, "provider-reported")
        self.assertTrue(receipt.direct_provider_cli)

    def test_direct_claude_rejects_requested_reported_model_mismatch(self) -> None:
        output = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": REVIEW_RESULT,
            "modelUsage": {"claude-sonnet-4-6": {}},
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"2.1.0\n", stderr=b""),
            subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(output).encode(), stderr=b""
            ),
        ]
        with patch("subprocess.run", side_effect=calls):
            with self.assertRaisesRegex(
                PolicyError, "PROVIDER_MODEL_IDENTITY_MISMATCH"
            ):
                DirectClaudeRunner(Path("/bin/sh")).run(
                    prompt="review this digest",
                    model="claude-opus-4-6",
                    workspace=self.workspace,
                )

    def test_cursor_attests_live_listed_launch_without_claiming_provider_report(
        self,
    ) -> None:
        output = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": REVIEW_RESULT,
            "request_id": "10000000-0000-4000-8000-000000000001",
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"2026.07\n", stderr=b""),
            subprocess.CompletedProcess(
                [],
                0,
                stdout=b"Available models\n\ncursor-grok-4.5-high - Cursor Grok 4.5\n",
                stderr=b"",
            ),
            subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(output).encode(), stderr=b""
            ),
        ]
        with patch("subprocess.run", side_effect=calls):
            receipt = CursorRunner(Path("/bin/sh")).run(
                prompt="review this digest",
                model="cursor-grok-4.5-high",
                workspace=self.workspace,
                provider_family="xai",
            )
        self.assertEqual(receipt.model_id, "cursor-grok-4.5-high")
        self.assertEqual(receipt.model_identity_class, "trusted-launch-attested")
        self.assertFalse(receipt.direct_provider_cli)

    def test_cursor_rejects_unparseable_live_model_list(self) -> None:
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"2026.07\n", stderr=b""),
            subprocess.CompletedProcess(
                [],
                0,
                stdout=b"Available models\n\ncursor-grok-4.5-high Cursor Grok 4.5\n",
                stderr=b"",
            ),
        ]
        with patch("subprocess.run", side_effect=calls):
            with self.assertRaisesRegex(PolicyError, "PROVIDER_MODEL_UNAVAILABLE"):
                CursorRunner(Path("/bin/sh")).run(
                    prompt="review this digest",
                    model="cursor-grok-4.5-high",
                    workspace=self.workspace,
                    provider_family="xai",
                )

    @staticmethod
    def codex_events(message: str, *, extra_item: dict | None = None) -> bytes:
        events = [
            {"type": "thread.started", "thread_id": "one"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "r", "type": "reasoning", "text": "reviewing"},
            },
        ]
        if extra_item is not None:
            events.append({"type": "item.completed", "item": extra_item})
        events.extend(
            [
                {
                    "type": "item.completed",
                    "item": {"id": "m", "type": "agent_message", "text": message},
                },
                {"type": "turn.completed", "usage": {}},
            ]
        )
        return ("\n".join(json.dumps(item) for item in events) + "\n").encode()

    def test_direct_codex_records_launch_attestation_not_provider_report(self) -> None:
        catalog = {
            "models": [
                {"slug": CODEX_MODEL, "visibility": "list", "supported_in_api": True}
            ]
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"codex-cli 1\n", stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=json.dumps(catalog).encode(), stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=self.codex_events(REVIEW_RESULT), stderr=b""),
        ]
        runner = DirectCodexRunner(Path("/bin/sh"))
        with patch("subprocess.run", side_effect=calls) as run:
            receipt = runner.run(
                prompt="review this digest", model=CODEX_MODEL, workspace=self.workspace
            )
        self.assertEqual(receipt.model_id, CODEX_MODEL)
        self.assertEqual(receipt.model_identity_class, "trusted-launch-attested")
        self.assertTrue(receipt.direct_provider_cli)
        self.assertEqual(
            run.call_args_list[1].args[0], [str(runner.executable), "debug", "models"]
        )
        self.assertIn("--ignore-user-config", run.call_args_list[2].args[0])
        self.assertIn("--ignore-rules", run.call_args_list[2].args[0])

    def test_direct_codex_rejects_tool_or_multiple_terminal_messages(self) -> None:
        with self.assertRaisesRegex(PolicyError, "PROVIDER_TOOL_EVENT_REJECTED"):
            DirectCodexRunner._terminal_result(
                self.codex_events(
                    REVIEW_RESULT,
                    extra_item={"id": "tool", "type": "command_execution", "command": "pwd"},
                )
            )
        duplicated = self.codex_events(REVIEW_RESULT).decode().splitlines()
        duplicated.insert(
            -1,
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "m2", "type": "agent_message", "text": REVIEW_RESULT},
                }
            ),
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_OUTPUT_INVALID"):
            DirectCodexRunner._terminal_result(("\n".join(duplicated) + "\n").encode())


class ProviderIssuerTest(unittest.TestCase):
    def test_v1_issuer_is_read_only(self) -> None:
        factory = FixtureFactory()
        with self.assertRaisesRegex(PolicyError, "LEGACY_CONTRACT_READ_ONLY"):
            ProviderReviewIssuer(
                signer=StaticSigner(factory, factory.ANTHROPIC_KEY_ID),
                provider_family="anthropic",
                channel="direct-anthropic-cli",
                direct_provider_cli=True,
                model_identity_class="provider-reported",
                allowed_models=frozenset({"claude-opus-4-8"}),
                issuer="cross-ai-issuer-anthropic",
                contract_version="v1",
            )

    def test_issuer_binds_fixed_provider_policy_and_signer_key(self) -> None:
        factory = FixtureFactory()
        signer = StaticSigner(factory, factory.ANTHROPIC_KEY_ID)
        issuer = ProviderReviewIssuer(
            signer=signer,
            provider_family="anthropic",
            channel="direct-anthropic-cli",
            direct_provider_cli=True,
            model_identity_class="provider-reported",
            allowed_models=frozenset({"claude-opus-4-6"}),
            issuer="cross-ai-issuer-anthropic",
        )
        receipt = ProviderExecutionReceipt(
            provider_family="anthropic",
            channel="direct-anthropic-cli",
            direct_provider_cli=True,
            model_id="claude-opus-4-6",
            model_identity_class="provider-reported",
            capability_snapshot_sha256=digest("capability"),
            input_sha256=digest("input"),
            output_sha256=digest("output"),
            result_text=REVIEW_RESULT,
        )
        envelope = issuer.issue(
            execution=receipt,
            coordinates=ReviewCoordinates(
                review_id="50000000-0000-4000-8000-000000000001",
                review_chain_id="40000000-0000-4000-8000-000000000001",
                subject_sha256=digest("subject"),
                round=2,
                previous_round_sha256=digest("previous"),
                closure_root_sha256=digest("closure"),
                issued_at="2026-07-16T20:00:00Z",
                expires_at="2026-07-16T21:30:00Z",
            ),
        )
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=REVIEW_PAYLOAD_TYPE_V2,
            allowed_keys={
                factory.ANTHROPIC_KEY_ID: factory.keys[factory.ANTHROPIC_KEY_ID]
                .public_key()
                .public_bytes_raw()
            },
        )
        self.assertEqual(verified.payload["modelIdentityClass"], "provider-reported")
        self.assertEqual(verified.payload["keyId"], factory.ANTHROPIC_KEY_ID)
        altered = ProviderExecutionReceipt(
            **{**receipt.__dict__, "model_identity_class": "trusted-launch-attested"}
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ISSUER_POLICY_MISMATCH"):
            issuer.issue(
                execution=altered,
                coordinates=ReviewCoordinates(
                    review_id="50000000-0000-4000-8000-000000000002",
                    review_chain_id="40000000-0000-4000-8000-000000000001",
                    subject_sha256=digest("subject"),
                    round=3,
                    previous_round_sha256=digest("previous"),
                    closure_root_sha256=digest("closure"),
                    issued_at="2026-07-16T20:00:00Z",
                    expires_at="2026-07-16T21:30:00Z",
                ),
            )

    def test_issuer_rejects_unknown_review_result_schema(self) -> None:
        factory = FixtureFactory()
        issuer = ProviderReviewIssuer(
            signer=StaticSigner(factory, factory.OPENAI_KEY_ID),
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_identity_class="trusted-launch-attested",
            allowed_models=frozenset({CODEX_MODEL}),
            issuer="cross-ai-issuer-openai",
        )
        receipt = ProviderExecutionReceipt(
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_id=CODEX_MODEL,
            model_identity_class="trusted-launch-attested",
            capability_snapshot_sha256=digest("capability"),
            input_sha256=digest("input"),
            output_sha256=digest("output"),
            result_text=REVIEW_RESULT.replace(".v1", ".v2"),
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_REVIEW_RESULT_INVALID"):
            issuer.issue(
                execution=receipt,
                coordinates=ReviewCoordinates(
                    review_id="50000000-0000-4000-8000-000000000003",
                    review_chain_id="40000000-0000-4000-8000-000000000001",
                    subject_sha256=digest("subject"),
                    round=1,
                    previous_round_sha256=None,
                    closure_root_sha256=digest("closure"),
                    issued_at="2026-07-16T20:00:00Z",
                    expires_at="2026-07-16T21:30:00Z",
                ),
            )


if __name__ == "__main__":
    unittest.main()
