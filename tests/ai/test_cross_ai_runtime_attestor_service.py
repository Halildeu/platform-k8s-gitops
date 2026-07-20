from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.ai import cross_ai_runtime_attestor_service as MODULE
from scripts.ai.cross_ai_runtime_authorization import (
    AUTHORIZATION_SCHEMA,
    AUTH_AUDIENCE,
)
from scripts.ai.trusted_cross_ai_evidence import canonical_bytes
from scripts.ai.cross_ai_runtime_workload import WorkloadMeasurement
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    ProviderReviewIssuer,
    ReviewCoordinates,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now
from tests.ai.signed_evidence_fixture import (
    StaticSigner,
    execution_receipt,
    make_signed_evidence,
)
from tests.github_apps.cross_ai_policy_fixtures import digest


class StaticRunner:
    def __init__(self, receipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def run(self, **_kwargs):
        self.calls += 1
        return self.receipt


class BlockingRunner(StaticRunner):
    def __init__(self, receipt) -> None:
        super().__init__(receipt)
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, **kwargs):
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test runner release timed out")
        return super().run(**kwargs)


class CountingSigner(StaticSigner):
    def __init__(self, factory, key_id) -> None:
        super().__init__(factory, key_id)
        self.calls = 0
        self.payloads = []

    def sign_json_envelope(self, *, payload_type, payload):
        self.calls += 1
        self.payloads.append(json.loads(json.dumps(payload)))
        return super().sign_json_envelope(
            payload_type=payload_type,
            payload=payload,
        )


class StaticWorkloadVerifier:
    def __init__(self, policy) -> None:
        self.measurement = WorkloadMeasurement(
            workload_identity=policy["workloadIdentity"],
            image_digest=policy["issuerImageDigest"],
            pod_uid="90000000-0000-4000-8000-000000000001",
        )
        self.calls = 0

    def measure(self):
        self.calls += 1
        return self.measurement


def write_authorization(path, request) -> None:
    now = utc_now()
    bound = {
        key: request[key]
        for key in (
            "requestId",
            "baseTipSha",
            "baseSha",
            "headSha",
            "scopeSha256",
            "subjectSha256",
            "promptSha256",
            "modelId",
            "timeoutSeconds",
        )
    }
    path.write_bytes(
        canonical_bytes(
            {
                "schemaVersion": AUTHORIZATION_SCHEMA,
                "audience": AUTH_AUDIENCE,
                "token": "attestor." + ("a" * 64),
                "issuedAt": (now - timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "expiresAt": (now + timedelta(minutes=30))
                .isoformat()
                .replace("+00:00", "Z"),
                "maxUses": 1,
                **bound,
            }
        )
    )
    path.chmod(0o600)


class FixedRuntimeAttestorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fixture = make_signed_evidence()
        self.now_patcher = patch.object(
            MODULE,
            "utc_now",
            return_value=self.fixture.factory.now,
        )
        self.now_patcher.start()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.receipt = execution_receipt(
            self.fixture.prompt,
            executable_policy=self.fixture.authority.codex_executable_policy,
        )
        self.request = {
            "schemaVersion": MODULE.SESSION_REQUEST_SCHEMA,
            "requestId": "70000000-0000-4000-8000-000000000001",
            "authAudience": MODULE.AUTH_AUDIENCE,
            "baseTipSha": self.fixture.bindings["base_tip_sha"],
            "baseSha": self.fixture.bindings["base_sha"],
            "headSha": self.fixture.bindings["head_sha"],
            "scopeSha256": "sha256:" + self.fixture.bindings["scope_sha256"],
            "subjectSha256": sha256_digest(self.fixture.subject),
            "prompt": self.fixture.prompt,
            "promptSha256": self.fixture.subject["promptSha256"],
            "modelId": self.receipt.model_id,
            "reasoningEffort": "xhigh",
            "sandbox": "read-only",
            "ephemeral": True,
            "toolPolicy": "none-pre-execution",
            "timeoutSeconds": 600,
        }
        self.token = self.root / "authorization"
        write_authorization(self.token, self.request)
        self.trust_root = self.root / "trust-root.json"
        self.trust_root.write_bytes(
            canonical_bytes(self.fixture.authority.trust_root)
        )
        self.revocations = self.root / "revocations.json"
        self.revocations.write_bytes(
            canonical_bytes(self.fixture.authority.revocations_envelope)
        )
        self.runner = StaticRunner(self.receipt)
        self.signer = CountingSigner(
            self.fixture.factory,
            self.fixture.factory.RUNNER_MANAGEMENT_KEY_ID,
        )
        self.store = MODULE.RuntimeSessionStore(self.root / "sessions.sqlite3")
        self.workload_verifier = StaticWorkloadVerifier(
            self.fixture.authority.issuer_runtime_policy
        )
        self.service = MODULE.FixedRuntimeAttestorService(
            runtime_policy=self.fixture.authority.issuer_runtime_policy,
            trust_root_file=self.trust_root,
            expected_trust_root_sha256=(
                self.fixture.authority.expected_trust_root_sha256
            ),
            revocations_file=self.revocations,
            authorization_token_file=self.token,
            store=self.store,
            signer=self.signer,
            runner=self.runner,
            workload_verifier=self.workload_verifier,
            workspace=self.workspace,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.now_patcher.stop()
        self.directory.cleanup()

    @staticmethod
    def _payload(envelope):
        return json.loads(base64.b64decode(envelope["payload"], validate=True))

    def _finalize_request(self, session):
        review = self.fixture.evidence["review_envelope"]
        review_payload = self._payload(review)
        issued = parse_utc(review_payload["issuedAt"], "review.issuedAt")
        return {
            "schemaVersion": MODULE.FINALIZE_REQUEST_SCHEMA,
            "sessionId": session["sessionId"],
            "executionSha256": sha256_digest(session["execution"]),
            "providerReviewEnvelope": review,
            "providerReviewEnvelopeSha256": sha256_digest(review),
            "promptSha256": self.fixture.subject["promptSha256"],
            "issuedAt": review_payload["issuedAt"],
            "expiresAt": (issued + timedelta(minutes=10))
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def test_service_executes_and_attests_only_its_stored_measurement(self) -> None:
        session = self.service.execute(self.request)
        with patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now):
            finalized = self.service.finalize(
                session["sessionId"],
                self._finalize_request(session),
            )
        runtime = self._payload(finalized["runtimeAttestationEnvelope"])
        self.assertEqual(
            runtime["providerSessionId"],
            self.receipt.provider_session_id,
        )
        self.assertEqual(runtime["responseSha256"], self.receipt.output_sha256)
        self.assertEqual(1, self.runner.calls)
        self.assertEqual(1, self.signer.calls)

    def test_exact_session_and_finalize_retries_are_idempotent(self) -> None:
        first = self.service.execute(self.request)
        second = self.service.execute(dict(self.request))
        self.assertEqual(first, second)
        self.assertEqual(1, self.runner.calls)
        finalize = self._finalize_request(first)
        with patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now):
            first_result = self.service.finalize(first["sessionId"], finalize)
            second_result = self.service.finalize(first["sessionId"], dict(finalize))
        self.assertEqual(first_result, second_result)
        self.assertEqual(1, self.signer.calls)

    def test_concurrent_identical_requests_execute_provider_once(self) -> None:
        runner = BlockingRunner(self.receipt)
        self.service.runner = runner
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.execute, dict(self.request))
            self.assertTrue(runner.started.wait(timeout=5))
            second = pool.submit(self.service.execute, dict(self.request))
            runner.release.set()
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)
        self.assertEqual(first_result, second_result)
        self.assertEqual(1, runner.calls)

    def test_durable_preexecution_claim_blocks_restart_replay(self) -> None:
        generation = MODULE.RuntimeAuthorityGeneration(
            trust_root=self.fixture.authority.trust_root,
            revocations=self.fixture.authority.revocations_envelope,
            expected_trust_root_sha256=(
                self.fixture.authority.expected_trust_root_sha256
            ),
            runtime_policy=self.fixture.authority.issuer_runtime_policy,
        )
        session_id, execution, issued_at = self.store.claim_execution(
            request=self.request,
            measurement=self.workload_verifier.measurement,
            generation=generation,
        )
        self.assertIsNone(execution)
        self.assertIsNone(issued_at)
        self.assertRegex(session_id, r"^[0-9a-f-]{36}$")
        with self.assertRaisesRegex(
            PolicyError,
            "PROVIDER_RUNTIME_EXECUTION_UNCERTAIN",
        ):
            self.service.execute(dict(self.request))
        self.assertEqual(0, self.runner.calls)

    def test_concurrent_finalize_signs_once_and_returns_identical_envelope(self) -> None:
        session = self.service.execute(self.request)
        finalize = self._finalize_request(session)
        with (
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(
                self.service.finalize,
                session["sessionId"],
                dict(finalize),
            )
            second = pool.submit(
                self.service.finalize,
                session["sessionId"],
                dict(finalize),
            )
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)
        self.assertEqual(first_result, second_result)
        self.assertEqual(1, self.signer.calls)

    def test_finalize_response_loss_reuses_durable_deterministic_payload(self) -> None:
        session = self.service.execute(self.request)
        finalize = self._finalize_request(session)
        original_finalize = self.store.finalize
        finalize_calls = 0

        def lose_first_response(**kwargs):
            nonlocal finalize_calls
            finalize_calls += 1
            if finalize_calls == 1:
                raise RuntimeError("response lost")
            return original_finalize(**kwargs)

        with (
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
            patch.object(
                self.store,
                "finalize",
                side_effect=lose_first_response,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "response lost"):
                self.service.finalize(session["sessionId"], dict(finalize))
            result = self.service.finalize(session["sessionId"], dict(finalize))
        self.assertEqual(2, self.signer.calls)
        self.assertEqual(self.signer.payloads[0], self.signer.payloads[1])
        payload = self._payload(result["runtimeAttestationEnvelope"])
        self.assertEqual(payload, self.signer.payloads[0])

    def test_authority_rotation_uses_history_for_inflight_session(self) -> None:
        config = self.root / "config/github-apps"
        config.mkdir(parents=True)
        current_root = config / "cross-ai-provider-review-trust-root.v2.json"
        current_revocations = (
            config / "cross-ai-provider-review-revocations.v1.dsse.json"
        )
        current_root.write_bytes(canonical_bytes(self.fixture.authority.trust_root))
        current_revocations.write_bytes(
            canonical_bytes(self.fixture.authority.revocations_envelope)
        )
        authority_file = config / "cross-ai-provider-review-authority.v1.json"
        manifest = {
            "schemaVersion": "acik.cross-ai-provider-review-authority.v1",
            "status": "active",
            "trustRootPath": (
                "config/github-apps/cross-ai-provider-review-trust-root.v2.json"
            ),
            "revocationsPath": (
                "config/github-apps/"
                "cross-ai-provider-review-revocations.v1.dsse.json"
            ),
            "expectedTrustRootSha256": (
                self.fixture.authority.expected_trust_root_sha256
            ),
            "issuerRuntimePolicy": self.fixture.authority.issuer_runtime_policy,
            "historicalAuthorities": [],
        }
        authority_file.write_bytes(canonical_bytes(manifest))
        self.service.authority_file = authority_file
        self.service.authority_root = self.root
        session = self.service.execute(self.request)

        old_digest = self.fixture.authority.expected_trust_root_sha256
        history = config / f"cross-ai-provider-review-history/{old_digest[7:]}"
        history.mkdir(parents=True)
        archived_root = history / "trust-root.v2.json"
        archived_revocations = history / "revocations.v1.dsse.json"
        archived_root.write_bytes(current_root.read_bytes())
        archived_revocations.write_bytes(current_revocations.read_bytes())
        rotated = json.loads(current_root.read_bytes())
        rotated["trustRootId"] = "10000000-0000-4000-8000-000000000088"
        current_root.write_bytes(canonical_bytes(rotated))
        manifest["expectedTrustRootSha256"] = sha256_digest(rotated)
        manifest["historicalAuthorities"] = [
            {
                "trustRootPath": str(archived_root.relative_to(self.root)),
                "revocationsPath": str(archived_revocations.relative_to(self.root)),
                "expectedTrustRootSha256": old_digest,
                "expectedRevocationsSha256": sha256_digest(
                    self.fixture.authority.revocations_envelope
                ),
                "issuerRuntimePolicy": self.fixture.authority.issuer_runtime_policy,
            }
        ]
        authority_file.write_bytes(canonical_bytes(manifest))
        self.assertEqual(
            sha256_digest(rotated),
            self.service._authority_generation().expected_trust_root_sha256,
        )
        with patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now):
            result = self.service.finalize(
                session["sessionId"], self._finalize_request(session)
            )
        self.assertIn("runtimeAttestationEnvelope", result)

    def test_request_scope_authorization_and_workload_measurement_fail_closed(
        self,
    ) -> None:
        changed = dict(self.request)
        changed["modelId"] = "gpt-5.3-codex-spark"
        with self.assertRaisesRegex(
            PolicyError,
            "PROVIDER_RUNTIME_AUTH_SCOPE_MISMATCH",
        ):
            self.service.execute(changed)

        self.workload_verifier.measurement = WorkloadMeasurement(
            workload_identity=self.workload_verifier.measurement.workload_identity,
            image_digest="sha256:" + ("f" * 64),
            pod_uid=self.workload_verifier.measurement.pod_uid,
        )
        with self.assertRaisesRegex(
            PolicyError,
            "PROVIDER_RUNTIME_WORKLOAD_MISMATCH",
        ):
            self.service.execute(self.request)
        self.assertEqual(0, self.runner.calls)

    def test_revocation_authority_is_reloaded_before_finalize(self) -> None:
        session = self.service.execute(self.request)
        self.revocations.write_bytes(canonical_bytes({"invalid": True}))
        finalize = self._finalize_request(session)
        with (
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
            self.assertRaises(PolicyError),
        ):
            self.service.finalize(session["sessionId"], finalize)
        self.assertEqual(0, self.signer.calls)

    def test_caller_execution_and_forged_provider_leaf_are_rejected(self) -> None:
        injected = dict(self.request)
        injected["execution"] = MODULE.execution_document(self.receipt)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_REQUEST_INVALID"):
            self.service.execute(injected)

        session = self.service.execute(self.request)
        forged_receipt = execution_receipt(
            self.fixture.prompt,
            response=(
                "P0\nNone\nP1\n"
                "- P1-FORGED | tests/fixture.py:1 | forged execution\n"
                "P2\nNone\nVERDICT: REVISE"
            ),
            executable_policy=self.fixture.authority.codex_executable_policy,
        )
        review_payload = self._payload(self.fixture.evidence["review_envelope"])
        forged = ProviderReviewIssuer(
            signer=StaticSigner(
                self.fixture.factory,
                self.fixture.factory.OPENAI_KEY_ID,
            ),
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_identity_class="trusted-launch-attested",
            allowed_models=(self.receipt.model_id,),
            issuer="cross-ai-issuer-openai",
        ).issue(
            execution=forged_receipt,
            coordinates=ReviewCoordinates(
                review_id="50000000-0000-4000-8000-000000000099",
                review_chain_id="40000000-0000-4000-8000-000000000099",
                subject_sha256=sha256_digest(self.fixture.subject),
                round=1,
                previous_round_sha256=None,
                closure_root_sha256=digest("forged-closure"),
                issued_at=review_payload["issuedAt"],
                expires_at=review_payload["expiresAt"],
            ),
        )
        finalize = self._finalize_request(session)
        finalize["providerReviewEnvelope"] = forged
        finalize["providerReviewEnvelopeSha256"] = sha256_digest(forged)
        with (
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
            self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_BINDING_MISMATCH"),
        ):
            self.service.finalize(session["sessionId"], finalize)
        self.assertEqual(0, self.signer.calls)

    def test_authorization_is_constant_time_checked_and_fail_closed(self) -> None:
        self.service.authorize("Bearer " + self.service.authorization.token)
        for value in (None, "Bearer wrong", "Basic token"):
            with self.assertRaisesRegex(PolicyError, "PROVIDER_RUNTIME_AUTH_DENIED"):
                self.service.authorize(value)

    def test_session_store_rejects_symlink_and_legacy_schema(self) -> None:
        target = self.root / "target.sqlite3"
        target.write_bytes(b"")
        target.chmod(0o600)
        alias = self.root / "alias.sqlite3"
        alias.symlink_to(target)
        with self.assertRaisesRegex(
            PolicyError,
            "PROVIDER_RUNTIME_STORE_INVALID",
        ):
            MODULE.RuntimeSessionStore(alias)

        legacy = self.root / "legacy.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.execute(
            "CREATE TABLE runtime_sessions (session_id TEXT PRIMARY KEY)"
        )
        connection.commit()
        connection.close()
        legacy.chmod(0o600)
        with self.assertRaisesRegex(
            PolicyError,
            "PROVIDER_RUNTIME_STORE_INVALID",
        ):
            MODULE.RuntimeSessionStore(legacy)

    def test_container_release_pins_match_public_executable_authority(self) -> None:
        root = Path(__file__).resolve().parents[2]
        authority = json.loads(
            (
                root
                / "config/github-apps/cross-ai-provider-review-authority.v1.json"
            ).read_text(encoding="utf-8")
        )
        linux = next(
            entry
            for entry in authority["codexExecutablePolicy"]["allowedExecutables"]
            if entry["platform"] == "linux-x64"
        )
        dockerfile = (root / "scripts/ai/runtime-attestor.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f"ARG CODEX_VERSION={linux['packageVersion']}",
            dockerfile,
        )
        self.assertIn(
            f"ARG CODEX_TARBALL_SHA512={linux['packageTarballSha512'].removeprefix('sha512:')}",
            dockerfile,
        )
        self.assertIn(
            f"ARG CODEX_LINUX_X64_SHA256={linux['cliSha256'].removeprefix('sha256:')}",
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
