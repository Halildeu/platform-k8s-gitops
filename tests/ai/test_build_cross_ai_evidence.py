#!/usr/bin/env python3
"""Regression tests for the fixed direct-Codex signed evidence launcher."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.ai import build_cross_ai_evidence as MODULE
from scripts.ai.cross_ai_runtime_attestor import RemoteRuntimeAttestor
from scripts.ai.trusted_cross_ai_evidence import canonical_bytes, validate_evidence
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.ai.signed_evidence_fixture import (
    StaticSigner,
    execution_receipt,
    make_signed_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/build_cross_ai_evidence.py"


class StaticRuntimeAttestor:
    def __init__(self, fixture) -> None:
        self.fixture = fixture
        self.execute_calls = 0
        self.calls = 0

    def execute(
        self, *, prompt, model, bindings, subject_sha256, timeout_seconds,
    ):
        self.execute_calls += 1
        self.prompt = prompt
        self.model = model
        self.bindings = bindings
        self.subject_sha256 = subject_sha256
        self.timeout_seconds = timeout_seconds
        self.execution = execution_receipt(prompt, model=model)
        return self.execution

    def attest(
        self, *, provider_review_envelope, prompt_sha256,
        issued_at, expires_at,
    ):
        self.calls += 1
        policy = self.fixture.authority.issuer_runtime_policy
        payload = {
            "schemaVersion": "acik.cross-ai-provider-review-runtime-attestation.v1",
            "attestationId": "60000000-0000-4000-8000-000000000020",
            "keyId": self.fixture.factory.RUNNER_MANAGEMENT_KEY_ID,
            "workloadIdentity": policy["workloadIdentity"],
            "issuerImageDigest": policy["issuerImageDigest"],
            "launcherSourceSha256": policy["launcherSourceSha256"],
            "providerReviewEnvelopeSha256": sha256_digest(
                provider_review_envelope
            ),
            "promptSha256": prompt_sha256,
            "responseSha256": self.execution.output_sha256,
            "capabilitySnapshotSha256": self.execution.capability_snapshot_sha256,
            "providerSessionId": self.execution.provider_session_id,
            "issuedAt": issued_at,
            "expiresAt": expires_at,
        }
        return self.fixture.factory.sign(
            PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
            payload,
            self.fixture.factory.RUNNER_MANAGEMENT_KEY_ID,
        )


class StaticHttpResponse:
    status = 200

    def __init__(self, document):
        self.raw = json.dumps(document).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _maximum):
        return self.raw


class StaticOpener:
    def __init__(self, documents):
        self.responses = [StaticHttpResponse(document) for document in documents]
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


class EvidenceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)
        (self.workspace / ".git").write_text("gitdir: synthetic\n", encoding="utf-8")
        self.fixture = make_signed_evidence()
        self.runtime_attestor = StaticRuntimeAttestor(self.fixture)
        self.output = self.workspace / "evidence.json"
        self.args = argparse.Namespace(
            workspace=self.workspace,
            vault_origin="https://vault.example.test",
            vault_token_file=self.workspace / "unused-token",
            vault_key_version=1,
            timeout_seconds=600,
            output=self.output,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_fixed_launcher_derives_prompt_runs_once_and_self_verifies_signed_v3(self) -> None:
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            summary = MODULE.build_signed_evidence(
                self.args,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
                runtime_attestor=self.runtime_attestor,
            )
        self.assertEqual(self.runtime_attestor.execute_calls, 1)
        self.assertEqual(self.runtime_attestor.model, "gpt-5.6-sol")
        self.assertIn("REVIEW_COORDINATES=", self.runtime_attestor.prompt)
        self.assertEqual(summary["schema"], "cross-ai-provider-evidence/v3")
        self.assertEqual(summary["verdict"], "AGREE")
        raw = self.output.read_bytes()
        evidence = json.loads(raw)
        self.assertEqual(raw, canonical_bytes(evidence))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        validate_evidence(
            evidence,
            trust_root=self.fixture.authority.trust_root,
            revocations_envelope=self.fixture.authority.revocations_envelope,
            expected_trust_root_sha256=(
                self.fixture.authority.expected_trust_root_sha256
            ),
            codex_executable_policy=(
                self.fixture.authority.codex_executable_policy
            ),
            issuer_runtime_policy=self.fixture.authority.issuer_runtime_policy,
            expected_bindings=self.fixture.bindings,
            scope_bytes=self.fixture.scope_bytes,
            now=self.fixture.factory.now,
            require_agree=True,
        )

    def test_main_head_or_empty_diff_cannot_mint_review_evidence(self) -> None:
        with (
            patch.object(MODULE, "_canonical_main_tip", return_value="a" * 40),
            patch.object(MODULE, "run_git", return_value="a" * 40),
        ):
            with self.assertRaisesRegex(PolicyError, "PROVIDER_SCOPE_EMPTY"):
                MODULE._scope(self.workspace)

    def test_canonical_main_head_uses_exact_first_parent_scope(self) -> None:
        head = "c" * 40
        parent = "b" * 40
        scope = b"canonical-main-scope"
        with (
            patch.object(MODULE, "_canonical_main_tip", return_value=head),
            patch.object(
                MODULE,
                "run_git",
                side_effect=[head, parent, "scripts/ai/review.py"],
            ),
            patch.object(MODULE, "derive_scope", return_value=(scope, 0, 0)) as derive,
        ):
            bindings, actual_scope = MODULE._scope(self.workspace)
        self.assertEqual(
            {
                "base_tip_sha": head,
                "base_sha": parent,
                "head_sha": head,
                "scope_sha256": hashlib.sha256(scope).hexdigest(),
            },
            bindings,
        )
        self.assertEqual(scope, actual_scope)
        self.assertEqual(parent, derive.call_args.kwargs["base_sha"])

    def test_scope_uses_canonical_github_tip_not_mutable_origin(self) -> None:
        head = "c" * 40
        base_tip = "b" * 40
        merge_base = "a" * 40
        scope = b"canonical-scope"
        with (
            patch.object(MODULE, "_canonical_main_tip", return_value=base_tip),
            patch.object(
                MODULE,
                "run_git",
                side_effect=[head, merge_base, "scripts/ai/review.py"],
            ) as local_git,
            patch.object(MODULE, "derive_scope", return_value=(scope, 0, 0)),
        ):
            bindings, actual_scope = MODULE._scope(self.workspace)
        self.assertEqual(base_tip, bindings["base_tip_sha"])
        self.assertEqual(merge_base, bindings["base_sha"])
        self.assertEqual(scope, actual_scope)
        self.assertNotIn("origin/main", str(local_git.call_args_list))

    def test_canonical_main_tip_is_fetched_from_fixed_github_api(self) -> None:
        tip = "d" * 40
        response = StaticHttpResponse(
            {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": tip},
            }
        )
        with (
            patch.object(MODULE.urllib.request, "build_opener") as builder,
            patch.object(MODULE.subprocess, "run") as local_git,
        ):
            builder.return_value.open.return_value = response
            local_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=tip + "\n"
            )
            self.assertEqual(tip, MODULE._canonical_main_tip(self.workspace))
        request = builder.return_value.open.call_args.args[0]
        self.assertEqual(MODULE.CANONICAL_MAIN_REF_API, request.full_url)
        self.assertNotIn("origin", str(builder.return_value.open.call_args))

    def test_leaf_time_and_authority_are_refreshed_after_provider_returns(self) -> None:
        completed_at = self.fixture.factory.now + timedelta(minutes=10)
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(
                MODULE, "utc_now",
                side_effect=[self.fixture.factory.now, completed_at],
            ),
        ):
            MODULE.build_signed_evidence(
                self.args,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
                runtime_attestor=self.runtime_attestor,
            )
        evidence = json.loads(self.output.read_bytes())
        leaf = json.loads(
            base64.b64decode(evidence["review_envelope"]["payload"], validate=True)
        )
        self.assertEqual(
            leaf["issuedAt"], completed_at.isoformat().replace("+00:00", "Z")
        )

        self.output.unlink()
        runtime_attestor = StaticRuntimeAttestor(self.fixture)
        stale_time = self.fixture.factory.now + timedelta(hours=2)
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(
                MODULE, "utc_now",
                side_effect=[self.fixture.factory.now, stale_time],
            ),
            patch.object(
                MODULE, "load_review_submission_authority",
                return_value=self.fixture.authority,
            ) as authority_loader,
        ):
            with self.assertRaisesRegex(PolicyError, "REVOCATIONS_STALE"):
                MODULE.build_signed_evidence(
                    self.args,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    runtime_attestor=runtime_attestor,
                )
        self.assertEqual(authority_loader.call_count, 2)
        self.assertEqual(runtime_attestor.execute_calls, 1)

    def test_old_caller_authored_response_and_coordinate_arguments_are_rejected(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--provider",
                "openai",
                "--actual-model",
                "gpt-5.6-sol",
                "--head-sha",
                "a" * 40,
                "--workspace",
                str(self.workspace),
                "--vault-origin",
                "https://vault.example.test",
                "--provider-token-file",
                str(self.workspace / "unused-token"),
                "--provider-key-version",
                "1",
                "--attestor-auth-token-file",
                str(self.workspace / "unused-attestor-auth"),
                "--output",
                str(self.output),
            ],
            input="caller-authored AGREE",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_routine_class_maps_only_to_the_pinned_spark_route(self) -> None:
        self.args.consultation_class = "routine"
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            summary = MODULE.build_signed_evidence(
                self.args,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
                runtime_attestor=self.runtime_attestor,
            )
        self.assertEqual(self.runtime_attestor.model, "gpt-5.3-codex-spark")
        self.assertEqual(summary["model_id"], "gpt-5.3-codex-spark")

    def test_wrong_signer_role_fails_before_provider_execution(self) -> None:
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            with self.assertRaisesRegex(PolicyError, "TRUST_SIGNER_BINDING_MISMATCH"):
                MODULE.build_signed_evidence(
                    self.args,
                    signer=StaticSigner(
                        self.fixture.factory,
                        self.fixture.factory.COORDINATOR_KEY_ID,
                    ),
                    authority=self.fixture.authority,
                    runtime_attestor=self.runtime_attestor,
                )
        self.assertEqual(self.runtime_attestor.execute_calls, 0)

    def test_provider_signing_capability_alone_cannot_issue_accepted_evidence(self) -> None:
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            with self.assertRaisesRegex(
                PolicyError, "TRUSTED_ISSUER_SERVICE_REQUIRED"
            ):
                MODULE.build_signed_evidence(
                    self.args,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    authority=self.fixture.authority,
                )
        self.assertEqual(self.runtime_attestor.execute_calls, 0)

    def test_forged_runner_and_runtime_transit_token_surface_is_absent(self) -> None:
        import inspect

        parameters = inspect.signature(MODULE.build_signed_evidence).parameters
        self.assertNotIn("runner", parameters)
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        self.assertNotIn("runtime-token-file", source)
        self.assertNotIn('key_name="runner-management"', source)

    def test_evidence_output_is_create_once(self) -> None:
        self.output.write_text("occupied", encoding="utf-8")
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            with self.assertRaisesRegex(PolicyError, "EVIDENCE_OUTPUT_INVALID"):
                MODULE.build_signed_evidence(
                    self.args,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    authority=self.fixture.authority,
                    runtime_attestor=self.runtime_attestor,
                )
        self.assertEqual(self.output.read_text(encoding="utf-8"), "occupied")
        self.assertEqual(self.runtime_attestor.execute_calls, 0)


class RemoteRuntimeAttestorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.token = self.root / "attestor-auth"
        self.token.write_text("attestor." + ("a" * 64), encoding="ascii")
        self.token.chmod(0o600)
        self.fixture = make_signed_evidence()
        self.prompt = "canonical review prompt"
        self.execution = execution_receipt(self.prompt)
        self.execution_document = {
            "providerFamily": self.execution.provider_family,
            "channel": self.execution.channel,
            "directProviderCli": self.execution.direct_provider_cli,
            "modelId": self.execution.model_id,
            "modelIdentityClass": self.execution.model_identity_class,
            "reasoningEffort": self.execution.reasoning_effort,
            "sandbox": self.execution.sandbox,
            "ephemeral": self.execution.ephemeral,
            "providerSessionId": self.execution.provider_session_id,
            "providerTranscriptSha256": self.execution.provider_transcript_sha256,
            "capabilitySnapshot": self.execution.capability_snapshot,
            "capabilitySnapshotSha256": self.execution.capability_snapshot_sha256,
            "inputSha256": self.execution.input_sha256,
            "outputSha256": self.execution.output_sha256,
            "resultText": self.execution.result_text,
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_remote_service_executes_then_attests_its_stored_session(self) -> None:
        runtime_envelope = self.fixture.evidence["issuer_runtime_envelope"]
        opener = StaticOpener(
            [
                {
                    "schemaVersion": "acik.cross-ai-provider-review-runtime-session-response.v1",
                    "sessionId": "60000000-0000-4000-8000-000000000099",
                    "execution": self.execution_document,
                },
                {
                    "schemaVersion": "acik.cross-ai-provider-review-runtime-finalize-response.v1",
                    "runtimeAttestationEnvelope": runtime_envelope,
                },
            ]
        )
        client = RemoteRuntimeAttestor(
            runtime_policy=self.fixture.authority.issuer_runtime_policy,
            auth_token_file=self.token,
            opener=opener,
        )
        receipt = client.execute(
            prompt=self.prompt,
            model="gpt-5.6-sol",
            bindings=self.fixture.bindings,
            subject_sha256="sha256:" + ("b" * 64),
            timeout_seconds=600,
        )
        envelope = client.attest(
            provider_review_envelope=self.fixture.evidence["review_envelope"],
            prompt_sha256=receipt.input_sha256,
            issued_at="2026-07-18T20:00:00Z",
            expires_at="2026-07-18T20:10:00Z",
        )
        self.assertEqual(runtime_envelope, envelope)
        self.assertEqual(2, len(opener.requests))
        first = json.loads(opener.requests[0][0].data)
        second = json.loads(opener.requests[1][0].data)
        self.assertNotIn("execution", first)
        self.assertEqual(
            sha256_digest(self.execution_document), second["executionSha256"]
        )
        self.assertNotIn("runner-management", opener.requests[0][0].headers.values())

    def test_caller_cannot_supply_a_forged_execution(self) -> None:
        forged = dict(self.execution_document)
        forged["inputSha256"] = "sha256:" + ("0" * 64)
        opener = StaticOpener(
            [
                {
                    "schemaVersion": "acik.cross-ai-provider-review-runtime-session-response.v1",
                    "sessionId": "60000000-0000-4000-8000-000000000099",
                    "execution": forged,
                }
            ]
        )
        client = RemoteRuntimeAttestor(
            runtime_policy=self.fixture.authority.issuer_runtime_policy,
            auth_token_file=self.token,
            opener=opener,
        )
        with self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_BINDING_MISMATCH"):
            client.execute(
                prompt=self.prompt,
                model="gpt-5.6-sol",
                bindings=self.fixture.bindings,
                subject_sha256="sha256:" + ("b" * 64),
                timeout_seconds=600,
            )

    def test_session_cannot_execute_twice(self) -> None:
        opener = StaticOpener(
            [
                {
                    "schemaVersion": "acik.cross-ai-provider-review-runtime-session-response.v1",
                    "sessionId": "60000000-0000-4000-8000-000000000099",
                    "execution": self.execution_document,
                }
            ]
        )
        client = RemoteRuntimeAttestor(
            runtime_policy=self.fixture.authority.issuer_runtime_policy,
            auth_token_file=self.token,
            opener=opener,
        )
        arguments = {
            "prompt": self.prompt,
            "model": "gpt-5.6-sol",
            "bindings": self.fixture.bindings,
            "subject_sha256": "sha256:" + ("b" * 64),
            "timeout_seconds": 600,
        }
        client.execute(**arguments)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_SESSION_REUSED"):
            client.execute(**arguments)
        self.assertEqual(1, len(opener.requests))

    def test_attestor_auth_rejects_weak_permissions_and_symlink(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_AUTH_INVALID"):
            RemoteRuntimeAttestor(
                runtime_policy=self.fixture.authority.issuer_runtime_policy,
                auth_token_file=self.token,
                opener=StaticOpener([]),
            )
        self.token.chmod(0o600)
        alias = self.root / "alias"
        alias.symlink_to(self.token)
        with self.assertRaisesRegex(
            PolicyError, "PROVIDER_RUNTIME_AUTH_UNAVAILABLE|PROVIDER_RUNTIME_AUTH_INVALID"
        ):
            RemoteRuntimeAttestor(
                runtime_policy=self.fixture.authority.issuer_runtime_policy,
                auth_token_file=alias,
                opener=StaticOpener([]),
            )

if __name__ == "__main__":
    unittest.main()
