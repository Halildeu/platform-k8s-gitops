from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import REVIEW_PAYLOAD_TYPE_V2
from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_ENVIRONMENT_POLICY,
    CODEX_MODEL,
    CursorRunner,
    DirectClaudeRunner,
    DirectCodexRunner,
    MAX_PROMPT_BYTES,
    ProviderExecutionReceipt,
    ProviderReviewIssuer,
    ReviewCoordinates,
    canonical_codex_execution_arguments,
    parse_canonical_review_response,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


REVIEW_RESULT = (
    "P0\nNone\nP1\n"
    "- P1-FINDING_A | scripts/example.py:10 | Concrete example finding.\n"
    "P2\nNone\nVERDICT: REVISE"
)
AGREE_RESULT = "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE"


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
        package_root = self.workspace / "node_modules/@openai/codex"
        wrapper = package_root / "bin/codex.js"
        native = (
            package_root
            / "node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex"
        )
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        wrapper.chmod(0o755)
        native.parent.mkdir(parents=True)
        shutil.copyfile("/bin/sh", native)
        native.chmod(0o755)
        (native.parents[3] / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openai/codex",
                    "version": "9.9.9-darwin-arm64",
                }
            ),
            encoding="utf-8",
        )
        (package_root / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openai/codex",
                    "version": "9.9.9",
                    "optionalDependencies": {
                        "@openai/codex-darwin-arm64": (
                            "npm:@openai/codex@9.9.9-darwin-arm64"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        cli_digest = "sha256:" + hashlib.sha256(native.read_bytes()).hexdigest()
        version = b"codex-cli 9.9.9"
        self.signature = {
            "signatureIdentity": (
                "Developer ID Application: OpenAI OpCo, LLC (2DC432GLL2)"
            ),
            "signatureTeamId": "2DC432GLL2",
            "signatureCdHashSha256": digest("test-cdhash"),
        }
        self.executable_entry = {
            "platform": "darwin-arm64",
            "sourceClass": "official-openai-npm-bundled-native",
            "packageName": "@openai/codex",
            "packageVersion": "9.9.9",
            "cliSha256": cli_digest,
            "cliVersion": version.decode(),
            "cliVersionSha256": (
                "sha256:" + hashlib.sha256(version).hexdigest()
            ),
            "signatureType": "apple-developer-id",
            **self.signature,
        }
        self.executable_policy = {
            "schemaVersion": "acik.codex-executable-policy.v1",
            "allowedExecutables": [self.executable_entry],
        }
        self.wrapper = wrapper
        self.native = native

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_direct_claude_is_retired_before_subprocess_execution(self) -> None:
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(PolicyError, "PROVIDER_ROUTE_RETIRED"):
                DirectClaudeRunner(Path("/bin/sh")).run(
                    prompt="review this digest",
                    model="claude-opus-4-8",
                    workspace=self.workspace,
                )
        run.assert_not_called()

    def test_cursor_is_retired_before_subprocess_execution(self) -> None:
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(PolicyError, "PROVIDER_ROUTE_RETIRED"):
                CursorRunner(Path("/bin/sh")).run(
                    prompt="review this digest",
                    model="cursor-grok-4.5-high",
                    workspace=self.workspace,
                    provider_family="xai",
                )
        run.assert_not_called()

    @staticmethod
    def codex_events(message: str, *, extra_item: dict | None = None) -> bytes:
        events = [
            {
                "type": "thread.started",
                "thread_id": "10000000-0000-4000-8000-000000000001",
            },
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
            subprocess.CompletedProcess([], 0, stdout=b"codex-cli 9.9.9\n", stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=json.dumps(catalog).encode(), stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=self.codex_events(REVIEW_RESULT), stderr=b""),
        ]
        runner = DirectCodexRunner(
            self.wrapper, executable_policy=self.executable_policy
        )
        spoofed = {
            "OPENAI_BASE_URL": "https://attacker.invalid/v1",
            "OPENAI_API_KEY": "attacker-token",
            "AZURE_OPENAI_ENDPOINT": "https://attacker.invalid",
            "HTTP_PROXY": "http://attacker.invalid",
            "HTTPS_PROXY": "http://attacker.invalid",
            "ALL_PROXY": "socks5://attacker.invalid",
            "NO_PROXY": "*",
            "CODEX_HOME": str(self.workspace / "attacker-codex-home"),
        }
        with patch.dict(os.environ, spoofed, clear=False):
            with (
                patch("subprocess.run", side_effect=calls) as run,
                patch.object(
                    DirectCodexRunner,
                    "_apple_signature_identity",
                    return_value=self.signature,
                ),
            ):
                receipt = runner.run(
                    prompt="review this digest", model=CODEX_MODEL, workspace=self.workspace
                )
        self.assertEqual(receipt.model_id, CODEX_MODEL)
        self.assertEqual(receipt.model_identity_class, "trusted-launch-attested")
        self.assertTrue(receipt.direct_provider_cli)
        self.assertEqual(receipt.reasoning_effort, "xhigh")
        self.assertEqual(receipt.sandbox, "read-only")
        self.assertIs(receipt.ephemeral, True)
        self.assertEqual(
            receipt.provider_session_id,
            "10000000-0000-4000-8000-000000000001",
        )
        self.assertTrue(receipt.provider_transcript_sha256.startswith("sha256:"))
        self.assertEqual(
            receipt.capability_snapshot_sha256,
            sha256_digest(receipt.capability_snapshot),
        )
        self.assertEqual(
            receipt.capability_snapshot["officialExecutableProvenance"],
            self.executable_entry,
        )
        dispatched_executables = {
            call.kwargs["executable"] for call in run.call_args_list
        }
        self.assertEqual(len(dispatched_executables), 1)
        dispatched_executable = Path(dispatched_executables.pop())
        self.assertEqual(dispatched_executable.name, "codex")
        self.assertNotEqual(dispatched_executable, runner.executable)
        self.assertFalse(dispatched_executable.exists())
        review_root = Path(run.call_args_list[2].kwargs["cwd"])
        self.assertFalse(review_root.exists())
        self.assertFalse(review_root.is_relative_to(self.workspace.resolve()))
        self.assertTrue(
            all(Path(call.kwargs["cwd"]) == review_root for call in run.call_args_list)
        )
        self.assertTrue(
            all(
                call.args[0][0] == str(dispatched_executable)
                and call.args[0][0] == call.kwargs["executable"]
                for call in run.call_args_list
            )
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [str(dispatched_executable), "debug", "models"],
        )
        self.assertEqual(
            run.call_args_list[2].args[0],
            [
                str(dispatched_executable),
                *canonical_codex_execution_arguments(
                    CODEX_MODEL, str(review_root.resolve())
                ),
            ],
        )
        self.assertEqual(
            receipt.capability_snapshot["toolPolicy"], "none-pre-execution"
        )
        self.assertEqual(
            receipt.capability_snapshot["environmentPolicy"],
            CODEX_ENVIRONMENT_POLICY,
        )
        environments = [call.kwargs["env"] for call in run.call_args_list]
        self.assertTrue(all(environment == environments[0] for environment in environments))
        self.assertEqual(
            set(environments[0]),
            {"HOME", "CODEX_HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "NO_COLOR"},
        )
        self.assertEqual(environments[0]["PATH"], "/usr/bin:/bin")
        for name in spoofed:
            if name != "CODEX_HOME":
                self.assertNotIn(name, environments[0])
        self.assertNotEqual(environments[0]["CODEX_HOME"], spoofed["CODEX_HOME"])
        self.assertIn("shell_tool", run.call_args_list[2].args[0])
        self.assertNotIn(
            str(self.workspace.resolve()), run.call_args_list[2].args[0]
        )

    def test_direct_codex_accepts_prompt_above_legacy_512k_scope_limit(self) -> None:
        prompt = "x" * (512 * 1024 + 1)
        self.assertLess(len(prompt.encode()), MAX_PROMPT_BYTES)
        catalog = {
            "models": [
                {"slug": CODEX_MODEL, "visibility": "list", "supported_in_api": True}
            ]
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"codex-cli 9.9.9\n", stderr=b""),
            subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(catalog).encode(), stderr=b""
            ),
            subprocess.CompletedProcess(
                [], 0, stdout=self.codex_events(AGREE_RESULT), stderr=b""
            ),
        ]
        with (
            patch("subprocess.run", side_effect=calls) as run,
            patch.object(
                DirectCodexRunner,
                "_apple_signature_identity",
                return_value=self.signature,
            ),
        ):
            DirectCodexRunner(
                self.wrapper, executable_policy=self.executable_policy
            ).run(prompt=prompt, model=CODEX_MODEL, workspace=self.workspace)
        self.assertEqual(run.call_args_list[2].kwargs["input"], prompt.encode())

    def test_direct_codex_rejects_tool_or_multiple_terminal_messages(self) -> None:
        disallowed_items = (
            {"id": "tool", "type": "command_execution", "command": "pwd"},
            {"id": "tool", "type": "mcp_tool_call", "server": "repo"},
            {"id": "tool", "type": "web_search", "query": "repository"},
            {"id": "tool", "type": "file_change", "path": "outside-scope"},
            {
                "id": "tool", "type": "agent_message", "text": REVIEW_RESULT,
                "command": "pwd",
            },
            {
                "id": "tool", "type": "reasoning", "text": "reviewing",
                "command": "pwd",
            },
        )
        for item in disallowed_items:
            with self.subTest(item_type=item["type"]):
                with self.assertRaisesRegex(
                    PolicyError, "PROVIDER_TOOL_EVENT_REJECTED"
                ):
                    DirectCodexRunner._terminal_result(
                        self.codex_events(REVIEW_RESULT, extra_item=item)
                    )

        nonterminal = self.codex_events(REVIEW_RESULT).decode().splitlines()
        nonterminal.insert(
            -2,
            json.dumps(
                {
                    "type": "item.started",
                    "item": {"id": "tool", "type": "command_execution"},
                }
            ),
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_TOOL_EVENT_REJECTED"):
            DirectCodexRunner._terminal_result(
                ("\n".join(nonterminal) + "\n").encode()
            )

        disguised = self.codex_events(REVIEW_RESULT).decode().splitlines()
        disguised[1] = json.dumps(
            {
                "type": "turn.started",
                "item": {"id": "tool", "type": "command_execution"},
            }
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_TOOL_EVENT_REJECTED"):
            DirectCodexRunner._terminal_result(
                ("\n".join(disguised) + "\n").encode()
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

    def test_direct_codex_rejects_pinned_executable_mutation(self) -> None:
        catalog = {
            "models": [
                {"slug": CODEX_MODEL, "visibility": "list", "supported_in_api": True}
            ]
        }
        responses = iter(
            [
                subprocess.CompletedProcess([], 0, stdout=b"codex-cli 9.9.9\n", stderr=b""),
                subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(catalog).encode(), stderr=b""
                ),
                subprocess.CompletedProcess(
                    [], 0, stdout=self.codex_events(REVIEW_RESULT), stderr=b""
                ),
            ]
        )
        call_count = 0

        def mutate_after_execution(*args, **kwargs):
            nonlocal call_count
            del args
            call_count += 1
            response = next(responses)
            if call_count == 3:
                executable = Path(kwargs["executable"])
                executable.chmod(0o700)
                executable.write_bytes(b"changed")
            return response

        with (
            patch("subprocess.run", side_effect=mutate_after_execution),
            patch.object(
                DirectCodexRunner,
                "_apple_signature_identity",
                return_value=self.signature,
            ),
        ):
            with self.assertRaisesRegex(PolicyError, "PROVIDER_EXECUTABLE_CHANGED"):
                DirectCodexRunner(
                    self.wrapper, executable_policy=self.executable_policy
                ).run(
                    prompt="review this digest",
                    model=CODEX_MODEL,
                    workspace=self.workspace,
                )

    def test_direct_codex_rejects_path_injected_script_before_launch(self) -> None:
        fake = self.workspace / "codex"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(self.workspace)}):
            with self.assertRaisesRegex(PolicyError, "PROVIDER_EXECUTABLE_INVALID"):
                DirectCodexRunner(executable_policy=self.executable_policy)

    def test_official_hoisted_platform_package_layout_resolves_exact_native(self) -> None:
        package_root = self.wrapper.parent.parent
        nested = self.native.parents[3]
        hoisted = package_root.parent / nested.name
        shutil.move(str(nested), str(hoisted))
        runner = DirectCodexRunner(
            self.wrapper, executable_policy=self.executable_policy
        )
        self.assertEqual(
            runner.executable,
            (hoisted / "vendor/aarch64-apple-darwin/bin/codex").resolve(),
        )

    def test_direct_codex_rejects_unpinned_or_replaced_native_before_launch(self) -> None:
        wrong_policy = json.loads(json.dumps(self.executable_policy))
        wrong_policy["allowedExecutables"][0]["cliSha256"] = digest("wrong-binary")
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(PolicyError, "PROVIDER_EXECUTABLE_NOT_PINNED"):
                DirectCodexRunner(self.wrapper, executable_policy=wrong_policy)
        run.assert_not_called()

        runner = DirectCodexRunner(
            self.wrapper, executable_policy=self.executable_policy
        )
        self.native.write_bytes(b"replacement")
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(PolicyError, "PROVIDER_EXECUTABLE_CHANGED"):
                runner.run(
                    prompt="review this digest",
                    model=CODEX_MODEL,
                    workspace=self.workspace,
                )
        run.assert_not_called()

    def test_direct_codex_rejects_signature_identity_mismatch(self) -> None:
        runner = DirectCodexRunner(
            self.wrapper, executable_policy=self.executable_policy
        )
        wrong_signature = {**self.signature, "signatureTeamId": "WRONGTEAM1"}
        with patch.object(
            DirectCodexRunner,
            "_apple_signature_identity",
            return_value=wrong_signature,
        ):
            with self.assertRaisesRegex(
                PolicyError, "PROVIDER_EXECUTABLE_SIGNATURE_INVALID"
            ):
                runner.run(
                    prompt="review this digest",
                    model=CODEX_MODEL,
                    workspace=self.workspace,
                )

    def test_direct_codex_rejects_self_reported_version_mismatch(self) -> None:
        runner = DirectCodexRunner(
            self.wrapper, executable_policy=self.executable_policy
        )
        catalog = {
            "models": [
                {"slug": CODEX_MODEL, "visibility": "list", "supported_in_api": True}
            ]
        }
        calls = [
            subprocess.CompletedProcess([], 0, stdout=b"codex-cli 9.9.8\n", stderr=b""),
            subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(catalog).encode(), stderr=b""
            ),
        ]
        with (
            patch("subprocess.run", side_effect=calls) as run,
            patch.object(
                DirectCodexRunner,
                "_apple_signature_identity",
                return_value=self.signature,
            ),
        ):
            with self.assertRaisesRegex(
                PolicyError, "PROVIDER_EXECUTABLE_VERSION_INVALID"
            ):
                runner.run(
                    prompt="review this digest",
                    model=CODEX_MODEL,
                    workspace=self.workspace,
                )
        self.assertEqual(run.call_count, 2)

    def test_canonical_response_parser_rejects_every_shape_bypass(self) -> None:
        self.assertEqual(
            parse_canonical_review_response(AGREE_RESULT)["verdict"], "AGREE"
        )
        malformed = {
            "missing section": "P0\nNone\nP1\nNone\nVERDICT: AGREE",
            "duplicate verdict": AGREE_RESULT + "\nVERDICT: AGREE",
            "agree with finding": (
                "P0\nNone\nP1\n"
                "- P1-BAD | scripts/a.py:1 | This finding blocks acceptance.\n"
                "P2\nNone\nVERDICT: AGREE"
            ),
            "case mismatch": "P0\nnone\nP1\nNone\nP2\nNone\nVERDICT: AGREE",
            "file line missing": (
                "P0\nNone\nP1\n- P1-BAD | scripts/a.py | Missing line binding.\n"
                "P2\nNone\nVERDICT: REVISE"
            ),
            "path traversal": (
                "P0\nNone\nP1\n"
                "- P1-BAD | ../scripts/a.py:1 | Traversal is not a repository path.\n"
                "P2\nNone\nVERDICT: REVISE"
            ),
            "caller-authored empty-array JSON AGREE": json.dumps(
                {
                    "schemaVersion": "acik.cross-ai-provider-review-result.v1",
                    "verdict": "AGREE",
                    "findingIds": [],
                    "resolvedFindingIds": [],
                    "acknowledgedFindingIds": [],
                },
                separators=(",", ":"),
            ),
        }
        for label, response in malformed.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    PolicyError, "PROVIDER_REVIEW_RESULT_INVALID"
                ):
                    parse_canonical_review_response(response)


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
        signer = StaticSigner(factory, factory.OPENAI_KEY_ID)
        issuer = ProviderReviewIssuer(
            signer=signer,
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
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            provider_session_id="50000000-0000-4000-8000-000000000010",
            provider_transcript_sha256=digest("transcript"),
            capability_snapshot={"source": "test"},
            capability_snapshot_sha256="",
            input_sha256=digest("input"),
            output_sha256=(
                "sha256:" + hashlib.sha256(REVIEW_RESULT.encode("utf-8")).hexdigest()
            ),
            result_text=REVIEW_RESULT,
        )
        receipt = ProviderExecutionReceipt(
            **{
                **receipt.__dict__,
                "capability_snapshot_sha256": sha256_digest(
                    receipt.capability_snapshot
                ),
            }
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
                factory.OPENAI_KEY_ID: factory.keys[factory.OPENAI_KEY_ID]
                .public_key()
                .public_bytes_raw()
            },
        )
        self.assertEqual(
            verified.payload["modelIdentityClass"], "trusted-launch-attested"
        )
        self.assertEqual(verified.payload["keyId"], factory.OPENAI_KEY_ID)
        altered = ProviderExecutionReceipt(
            **{**receipt.__dict__, "model_identity_class": "provider-reported"}
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

        for field, invalid in (
            ("reasoning_effort", "high"),
            ("sandbox", "workspace-write"),
            ("ephemeral", False),
            ("output_sha256", digest("repackaged-output")),
        ):
            altered = ProviderExecutionReceipt(
                **{**receipt.__dict__, field: invalid}
            )
            with self.assertRaisesRegex(
                PolicyError, "PROVIDER_ISSUER_POLICY_MISMATCH"
            ):
                issuer.issue(
                    execution=altered,
                    coordinates=ReviewCoordinates(
                        review_id="50000000-0000-4000-8000-000000000004",
                        review_chain_id="40000000-0000-4000-8000-000000000001",
                        subject_sha256=digest("subject"),
                        round=3,
                        previous_round_sha256=digest("previous"),
                        closure_root_sha256=digest("closure"),
                        issued_at="2026-07-16T20:00:00Z",
                        expires_at="2026-07-16T21:30:00Z",
                    ),
                )

    def test_issuer_rejects_malformed_canonical_review_result(self) -> None:
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
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            provider_session_id="50000000-0000-4000-8000-000000000011",
            provider_transcript_sha256=digest("transcript-invalid"),
            capability_snapshot={"source": "test-invalid"},
            capability_snapshot_sha256="",
            input_sha256=digest("input"),
            output_sha256=(
                "sha256:"
                + hashlib.sha256(
                    "P0\nNone\nP1\nNone\nVERDICT: AGREE".encode("utf-8")
                ).hexdigest()
            ),
            result_text="P0\nNone\nP1\nNone\nVERDICT: AGREE",
        )
        receipt = ProviderExecutionReceipt(
            **{
                **receipt.__dict__,
                "capability_snapshot_sha256": sha256_digest(
                    receipt.capability_snapshot
                ),
            }
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
