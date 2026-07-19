from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.github_apps.cross_ai_deployment_policy.binding import (
    AUTHORITY_PATH,
    BINDING_IDEMPOTENCY_DOMAIN,
    BINDING_PAYLOAD_TYPE,
    RUNTIME_TRUST_ROOT_PATH,
    WORKFLOW_PATH,
    ViewOnlyBindingAuthority,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import GitHubIntentRef
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.oidc import ISSUER
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


ROOT = Path(__file__).resolve().parents[2]
REQUEST_ID = "30000000-0000-4000-8000-000000000001"
RUN_ID = 987654321
RUN_WATERMARK = RUN_ID - 1
REF_OBJECT_ID = "9" * 40
INSTALLATION_ID = 147158710
NOW = datetime(2026, 7, 18, 20, 30, tzinfo=timezone.utc)


class StaticSigner:
    def __init__(self, factory: FixtureFactory) -> None:
        self.factory = factory
        self.key_id = factory.COORDINATOR_KEY_ID
        self.calls = 0

    def sign_json_envelope(
        self, *, payload_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        return self.factory.sign(payload_type, payload, self.key_id)


class FakeOIDCVerifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def verify_claim_profile(self, token: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"token": token, **kwargs})
        claims = {
            "iss": ISSUER,
            "aud": kwargs["audience"],
            **kwargs["exact_claims"],
            **{
                name: str(value)
                for name, value in kwargs["positive_claims"].items()
            },
            "jti": (
                "20000000-0000-4000-8000-000000000002"
                if token == "second-token"
                else "20000000-0000-4000-8000-000000000001"
            ),
        }
        return claims


class FakeGitHub:
    def __init__(
        self,
        *,
        repository_id: int,
        repository: str,
        head_sha: str,
        intent_ref: str,
        authority_contents: dict[str, bytes],
    ) -> None:
        self.authority_contents = dict(authority_contents)
        self.ref_value = GitHubIntentRef(
            ref_object_id=REF_OBJECT_ID,
            head_sha=head_sha,
            annotated=True,
        )
        self.run_value = {
            "id": RUN_ID,
            "event": "workflow_dispatch",
            "head_sha": head_sha,
            "head_branch": intent_ref.removeprefix("refs/tags/"),
            "repository": {"id": repository_id, "full_name": repository},
            "head_repository": {"id": repository_id, "full_name": repository},
            "triggering_actor": {"id": 424242},
            "run_attempt": 1,
            "status": "queued",
            "path": WORKFLOW_PATH,
            "created_at": "2026-07-18T20:04:00Z",
        }

    def workflow_run(self, *_args: Any) -> dict[str, Any]:
        return copy.deepcopy(self.run_value)

    def intent_ref(self, *_args: Any) -> GitHubIntentRef:
        return self.ref_value

    def workflow_bytes(
        self,
        _installation_id: int,
        _repository: str,
        workflow_path: str,
        _head_sha: str,
    ) -> bytes:
        return self.authority_contents[workflow_path]


def active_authority_contents() -> dict[str, bytes]:
    contents = {
        path: (ROOT / path).read_bytes()
        for path in FixtureFactory.TRANSACTION_AUTHORITY_PATHS
    }
    runtime = json.loads(contents[RUNTIME_TRUST_ROOT_PATH])
    runtime.update(
        {
            "activationState": "active",
            "keys": [
                {
                    "keyId": "vault-transit://endpoint-admin/view-only-runtime-attestor#v1",
                    "role": "runtime-attestor",
                    "version": 1,
                    "publicKeyBase64": base64.b64encode(bytes(range(32))).decode(),
                    "notBefore": "2026-07-18T19:00:00Z",
                    "notAfter": "2026-07-18T22:00:00Z",
                    "state": "active",
                },
                {
                    "keyId": "vault-transit://endpoint-admin/view-only-checkpoint#v1",
                    "role": "checkpoint-signer",
                    "version": 1,
                    "publicKeyBase64": base64.b64encode(bytes(range(1, 33))).decode(),
                    "notBefore": "2026-07-18T19:00:00Z",
                    "notAfter": "2026-07-18T22:00:00Z",
                    "state": "active",
                },
            ],
            "revocations": [],
        }
    )
    runtime_raw = canonical_bytes(runtime)
    contents[RUNTIME_TRUST_ROOT_PATH] = runtime_raw

    authority = json.loads(contents[AUTHORITY_PATH])
    authority["activation"] = {"blockers": [], "state": "active"}
    authority["personaPolicy"]["identitySha256"] = digest("preflight-persona")
    authority["personaPolicy"]["tenantIdSha256"] = digest("test-tenant")
    authority["runtimeTrustRoot"]["expectedSha256"] = sha256_digest(
        {
            "domain": "faz22.6/view-only/runtime-trust-root/v1",
            "trustRoot": runtime,
        }
    )
    contents[AUTHORITY_PATH] = canonical_bytes(authority)
    return contents


class ViewOnlyTransactionBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.factory = FixtureFactory("v3")
        self.authority_contents = active_authority_contents()
        self.fixture = self.factory.build(
            authority_contents=self.authority_contents,
        )
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=NOW,
            expected_policy_sha256=digest("policy"),
            expected_bundle_contract="v3",
        ).verify_bundle(self.fixture.bundle_envelope)
        self.registry = IntentRegistry(
            Path(self.directory.name) / "registry.sqlite3",
            ContentAddressedStore(Path(self.directory.name) / "cas"),
        )
        self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=datetime(2026, 7, 18, 20, 0, tzinfo=timezone.utc),
        )
        self.registry.finalize_ref(
            request_id=REQUEST_ID,
            ref_object_id=REF_OBJECT_ID,
            resolved_head_sha=self.verified.payload["subject"]["headSha"],
            finalized_at=datetime(2026, 7, 18, 20, 1, tzinfo=timezone.utc),
        )
        self.registry.queue_dispatch(
            request_id=REQUEST_ID,
            stage="transaction",
            installation_id=INSTALLATION_ID,
            repository=self.verified.payload["subject"]["repository"],
            queued_at=datetime(2026, 7, 18, 20, 2, tzinfo=timezone.utc),
        )
        self.registry.claim_dispatch(
            request_id=REQUEST_ID,
            stage="transaction",
            claimed_at=datetime(2026, 7, 18, 20, 2, 30, tzinfo=timezone.utc),
        )
        self.registry.record_dispatch_watermark(
            request_id=REQUEST_ID,
            stage="transaction",
            watermark=RUN_WATERMARK,
            snapshot_at=datetime(2026, 7, 18, 20, 3, tzinfo=timezone.utc),
        )
        self.registry.reconcile_dispatch(
            request_id=REQUEST_ID,
            stage="transaction",
            run_id=RUN_ID,
            reconciled_at=datetime(2026, 7, 18, 20, 4, tzinfo=timezone.utc),
        )
        subject = self.verified.payload["subject"]
        self.github = FakeGitHub(
            repository_id=subject["repositoryId"],
            repository=subject["repository"],
            head_sha=subject["headSha"],
            intent_ref=subject["intentRef"],
            authority_contents=self.authority_contents,
        )
        self.oidc = FakeOIDCVerifier()
        self.signer = StaticSigner(self.factory)
        self.authority = ViewOnlyBindingAuthority(
            installation_id=INSTALLATION_ID,
            registry=self.registry,
            github=self.github,
            trust_root=self.fixture.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            expected_policy_sha256=digest("policy"),
            revocations_loader=lambda: self.fixture.revocations_envelope,
            oidc_verifier=self.oidc,
            signer=self.signer,
            now=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def request(self, *, identity: dict[str, str] | None = None) -> dict[str, Any]:
        subject = self.verified.payload["subject"]
        intent_ref = subject["intentRef"]
        stable_identity = identity or {
            "iss": ISSUER,
            "sub": f"repo:{subject['repository']}:ref:{intent_ref}",
            "actor_id": "424242",
            "repository_id": str(subject["repositoryId"]),
            "run_id": str(RUN_ID),
            "run_attempt": "1",
            "ref": intent_ref,
            "sha": subject["headSha"],
        }
        body = {
            "schemaVersion": "faz22.6.viewOnlyTransactionBindingRequest.v1",
            "requestId": REQUEST_ID,
            "requestedPayloadType": BINDING_PAYLOAD_TYPE,
            "workflowPath": WORKFLOW_PATH,
        }
        key = sha256_digest(
            {
                "domain": BINDING_IDEMPOTENCY_DOMAIN,
                "requestId": REQUEST_ID,
                "bodySha256": sha256_digest(body),
                "identity": stable_identity,
            }
        )
        return {**body, "idempotencyKeySha256": key}

    def test_issues_exact_signed_handoff_and_replays_byte_identically(self) -> None:
        first = self.authority.issue(
            request=self.request(),
            oidc_token="first-token",
        )
        second = self.authority.issue(
            request=self.request(),
            oidc_token="second-token",
        )
        self.assertEqual(first.envelope, second.envelope)
        self.assertEqual(first.response_digest, second.response_digest)
        self.assertEqual(self.signer.calls, 1)
        self.assertEqual(len(self.oidc.calls), 2)
        payload = self.factory.decode_payload(first.envelope)
        self.assertEqual(payload["binding"]["headSha"], self.factory.TRANSACTION_REVIEWED_HEAD_SHA)
        self.assertEqual(payload["binding"]["runId"], RUN_ID)
        self.assertEqual(payload["binding"]["authoritySetSha256"], self.verified.payload["subject"]["transactionScopeSha256"])
        self.assertEqual(payload["mutationCount"], 0)

    def test_rejects_bad_idempotency_and_exact_head_authority_tamper(self) -> None:
        request = self.request()
        request["idempotencyKeySha256"] = digest("wrong-idempotency")
        with self.assertRaisesRegex(PolicyError, "BINDING_IDEMPOTENCY_MISMATCH"):
            self.authority.issue(request=request, oidc_token="first-token")
        self.github.authority_contents[WORKFLOW_PATH] += b"\n# drift\n"
        with self.assertRaisesRegex(PolicyError, "BINDING_AUTHORITY_FILE_MISMATCH"):
            self.authority.issue(request=self.request(), oidc_token="first-token")

    def test_rejects_dispatch_identity_and_runtime_trust_expiry(self) -> None:
        self.github.run_value["triggering_actor"] = {"id": 7}
        with self.assertRaisesRegex(PolicyError, "BINDING_DISPATCH_MISMATCH"):
            self.authority.issue(request=self.request(), oidc_token="first-token")
        self.github.run_value["triggering_actor"] = {"id": 424242}
        authority = json.loads(self.github.authority_contents[AUTHORITY_PATH])
        runtime = json.loads(self.github.authority_contents[RUNTIME_TRUST_ROOT_PATH])
        runtime["keys"][0]["notAfter"] = "2026-07-18T20:00:00Z"
        runtime_raw = canonical_bytes(runtime)
        authority["runtimeTrustRoot"]["expectedSha256"] = sha256_digest(
            {
                "domain": "faz22.6/view-only/runtime-trust-root/v1",
                "trustRoot": runtime,
            }
        )
        with self.assertRaisesRegex(
            PolicyError,
            "BINDING_RUNTIME_TRUST_ROOT_INACTIVE",
        ):
            self.authority._authority_config(
                canonical_bytes(authority),
                runtime_raw,
                NOW,
            )


class IdempotentEnvelopeStoreTest(unittest.TestCase):
    def test_conflicting_identity_cannot_reuse_request_or_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = IntentRegistry(
                Path(directory) / "registry.sqlite3",
                ContentAddressedStore(Path(directory) / "cas"),
            )
            try:
                envelope = {"payloadType": "test", "payload": "e30=", "signatures": []}
                registry.record_idempotent_envelope(
                    operation="binding-test",
                    request_id=REQUEST_ID,
                    idempotency_key=digest("key"),
                    request_digest=digest("request"),
                    identity_digest=digest("identity"),
                    envelope=envelope,
                    max_response_bytes=1024,
                    created_at=NOW,
                )
                with self.assertRaisesRegex(PolicyError, "IDEMPOTENCY_CONFLICT"):
                    registry.get_idempotent_envelope(
                        operation="binding-test",
                        request_id=REQUEST_ID,
                        idempotency_key=digest("key"),
                        request_digest=digest("request"),
                        identity_digest=digest("other-identity"),
                    )
            finally:
                registry.close()


if __name__ == "__main__":
    unittest.main()
