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


class StaticRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, prompt, model, workspace, timeout_seconds=600):
        self.calls += 1
        self.prompt = prompt
        self.model = model
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        return execution_receipt(prompt, model=model)


class StaticRuntimeAttestor:
    def __init__(self, fixture) -> None:
        self.fixture = fixture
        self.calls = 0

    def attest(
        self, *, provider_review_envelope, execution, prompt_sha256,
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
            "responseSha256": execution.output_sha256,
            "capabilitySnapshotSha256": execution.capability_snapshot_sha256,
            "providerSessionId": execution.provider_session_id,
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
        runner = StaticRunner()
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
                runner=runner,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
                runtime_attestor=self.runtime_attestor,
            )
        self.assertEqual(runner.calls, 1)
        self.assertEqual(runner.model, "gpt-5.6-sol")
        self.assertIn("REVIEW_COORDINATES=", runner.prompt)
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
        runner = StaticRunner()
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
                runner=runner,
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
        runner = StaticRunner()
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
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    runtime_attestor=self.runtime_attestor,
                )
        self.assertEqual(authority_loader.call_count, 2)
        self.assertEqual(runner.calls, 1)

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
                "--runtime-token-file",
                str(self.workspace / "unused-runtime-token"),
                "--runtime-key-version",
                "1",
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
        runner = StaticRunner()
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
                runner=runner,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
                runtime_attestor=self.runtime_attestor,
            )
        self.assertEqual(runner.model, "gpt-5.3-codex-spark")
        self.assertEqual(summary["model_id"], "gpt-5.3-codex-spark")

    def test_wrong_signer_role_fails_before_provider_execution(self) -> None:
        runner = StaticRunner()
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
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory,
                        self.fixture.factory.COORDINATOR_KEY_ID,
                    ),
                    authority=self.fixture.authority,
                    runtime_attestor=self.runtime_attestor,
                )
        self.assertEqual(runner.calls, 0)

    def test_provider_signing_capability_alone_cannot_issue_accepted_evidence(self) -> None:
        runner = StaticRunner()
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
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    authority=self.fixture.authority,
                )
        self.assertEqual(runner.calls, 0)

    def test_provider_and_runtime_token_aliases_are_rejected(self) -> None:
        provider_token = self.workspace / "provider-token"
        runtime_token = self.workspace / "runtime-token"
        for alias_kind in ("hardlink", "copied-credential"):
            with self.subTest(alias_kind=alias_kind):
                provider_token.write_text("hvs." + ("a" * 40), encoding="ascii")
                provider_token.chmod(0o600)
                if alias_kind == "hardlink":
                    runtime_token.hardlink_to(provider_token)
                else:
                    runtime_token.write_bytes(provider_token.read_bytes())
                    runtime_token.chmod(0o600)
                self.args.provider_token_file = provider_token
                self.args.provider_key_version = 1
                self.args.runtime_token_file = runtime_token
                self.args.runtime_key_version = 1
                runner = StaticRunner()
                with (
                    patch.object(
                        MODULE,
                        "_scope",
                        return_value=(self.fixture.bindings, self.fixture.scope_bytes),
                    ),
                    patch.object(
                        MODULE, "utc_now", return_value=self.fixture.factory.now
                    ),
                    self.assertRaisesRegex(
                        PolicyError,
                        "VAULT_TOKEN_FILE_INVALID|TRUSTED_ISSUER_SERVICE_REQUIRED",
                    ),
                ):
                    MODULE.build_signed_evidence(
                        self.args,
                        runner=runner,
                        authority=self.fixture.authority,
                    )
                self.assertEqual(runner.calls, 0)
                runtime_token.unlink()
                provider_token.unlink()

    def test_vault_runtime_attestor_binds_live_launcher_and_management_key(self) -> None:
        policy = dict(self.fixture.authority.issuer_runtime_policy)
        policy["launcherSourceSha256"] = "sha256:" + hashlib.sha256(
            Path(MODULE.__file__).read_bytes()
        ).hexdigest()
        signer = StaticSigner(
            self.fixture.factory, self.fixture.factory.RUNNER_MANAGEMENT_KEY_ID
        )
        attestor = MODULE.VaultTransitRuntimeAttestor(
            signer=signer,
            runtime_policy=policy,
        )
        execution = execution_receipt("review prompt")
        envelope = attestor.attest(
            provider_review_envelope=self.fixture.evidence["review_envelope"],
            execution=execution,
            prompt_sha256=execution.input_sha256,
            issued_at="2026-07-18T20:00:00Z",
            expires_at="2026-07-18T20:10:00Z",
        )
        self.assertEqual(
            envelope["signatures"][0]["keyid"],
            self.fixture.factory.RUNNER_MANAGEMENT_KEY_ID,
        )

    def test_evidence_output_is_create_once(self) -> None:
        self.output.write_text("occupied", encoding="utf-8")
        runner = StaticRunner()
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
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    authority=self.fixture.authority,
                    runtime_attestor=self.runtime_attestor,
                )
        self.assertEqual(self.output.read_text(encoding="utf-8"), "occupied")
        self.assertEqual(runner.calls, 0)


if __name__ == "__main__":
    unittest.main()
