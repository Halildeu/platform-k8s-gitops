from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import unittest
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.dsse import pae
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.runtime_receipts import (
    BINDING_HANDOFF_PAYLOAD_TYPE,
    BINDING_DOMAIN,
    CHECKPOINT_PAYLOAD_TYPE,
    CHECKPOINT_STORED_OBJECT_DOMAIN,
    LEASE_PAYLOAD_TYPE,
    PREFLIGHT_PAYLOAD_TYPE,
    TRANSACTION_ID_DOMAIN,
    RuntimeReceiptVerifier,
    runtime_envelope_sha256,
    runtime_evidence_from_archive,
    runtime_trust_root_sha256,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 18, 20, 24, tzinfo=timezone.utc)
RUN_ID = 987654321


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def sign(
    key: Ed25519PrivateKey,
    key_id: str,
    payload_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw = canonical_bytes(payload)
    signature = key.sign(pae(payload_type, raw))
    return {
        "payloadType": payload_type,
        "payload": base64.b64encode(raw).decode("ascii"),
        "signatures": [
            {
                "keyid": key_id,
                "sig": base64.b64encode(signature).decode("ascii"),
            }
        ],
    }


class RuntimeReceiptVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FixtureFactory("v3")
        self.fixture = self.factory.build()
        self.authorization = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=NOW,
            expected_bundle_contract="v3",
        ).verify_bundle(self.fixture.bundle_envelope)
        bundle = self.authorization.payload
        subject = bundle["subject"]
        stage = bundle["workflowStages"][0]
        self.binding = {
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "deploymentClass": subject["deploymentClass"],
            "productSlice": subject["productSlice"],
            "intentRef": subject["intentRef"],
            "intentBundleSha256": self.authorization.bundle_digest,
            "transactionSessionSha256": subject["sessionSha256"],
            "headSha": subject["headSha"],
            "workflowPath": stage["workflowPath"],
            "workflowRef": (
                f"{subject['repository']}/{stage['workflowPath']}@{subject['intentRef']}"
            ),
            "workflowBlobSha256": stage["workflowBlobSha256"],
            "dependencyLockSha256": stage["dependencyLockSha256"],
            "concurrencySha256": stage["concurrencyGroupSha256"],
            "authoritySetSha256": subject["transactionScopeSha256"],
            "runId": RUN_ID,
            "runAttempt": 1,
            "triggeringActorId": bundle["grant"]["triggeringActorId"],
            "machineAuthorityPolicySha256": subject["policySha256"],
            "artifactSetSha256": subject["artifactSetSha256"],
            "rollbackPlanSha256": subject["rollbackPlanSha256"],
            "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
            "bootstrapCredentialSha256": subject["bootstrapCredentialSha256"],
            "tenantIdSha256": digest("test-tenant"),
            "preflightPersonaIdentitySha256": digest("test-persona"),
            "endpointIdSha256": subject["endpointIdSha256"],
            "operatorIdSha256": subject["operatorIdSha256"],
            "deviceHostnameSha256": subject["deviceHostnameSha256"],
            "attendedConsentPolicySha256": subject[
                "attendedConsentPolicySha256"
            ],
            "pilotOwnerPolicySha256": subject["pilotOwnerPolicySha256"],
            "maskPolicySha256": subject["maskPolicySha256"],
            "runtimeImageDigest": subject["runtimeImageDigest"],
            "pilotSeconds": subject["pilotSeconds"],
            "transactionScopeSha256": subject["transactionScopeSha256"],
            "runnerPolicySha256": subject["runnerPolicySha256"],
            "runnerAdmissionLeaseSha256": subject[
                "runnerAdmissionLeaseSha256"
            ],
        }
        self.binding_sha = sha256_digest(
            {"domain": BINDING_DOMAIN, "binding": self.binding}
        )
        self.transaction_id = sha256_digest(
            {"domain": TRANSACTION_ID_DOMAIN, "binding": self.binding}
        )
        self.attestor_key = Ed25519PrivateKey.from_private_bytes(b"\x0b" * 32)
        self.checkpoint_key = Ed25519PrivateKey.from_private_bytes(b"\x0c" * 32)
        self.attestor_key_id = (
            "vault-transit://endpoint-admin/view-only-runtime-attestor#v1"
        )
        self.checkpoint_key_id = (
            "vault-transit://endpoint-admin/view-only-checkpoint#v1"
        )
        self.trust_root = {
            "schemaVersion": "faz22.6.viewOnlyRuntimeTrustRoot.v1",
            "activationState": "active",
            "trustRootId": "faz22-view-only-runtime-test-v1",
            "digestDomain": "faz22.6/view-only/runtime-trust-root/v1",
            "algorithm": "ed25519",
            "keys": [
                {
                    "keyId": self.attestor_key_id,
                    "role": "runtime-attestor",
                    "version": 1,
                    "publicKeyBase64": public_b64(self.attestor_key),
                    "notBefore": "2026-07-18T19:00:00Z",
                    "notAfter": "2026-07-18T22:00:00Z",
                    "state": "active",
                },
                {
                    "keyId": self.checkpoint_key_id,
                    "role": "checkpoint-signer",
                    "version": 1,
                    "publicKeyBase64": public_b64(self.checkpoint_key),
                    "notBefore": "2026-07-18T19:00:00Z",
                    "notAfter": "2026-07-18T22:00:00Z",
                    "state": "active",
                },
            ],
            "revocations": [],
            "generatedAt": "2026-07-18T19:00:00Z",
        }
        self.authority = json.loads(
            (
                ROOT / "config/faz22-6-view-only-live-preflight-authority.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.authority["activation"] = {"blockers": [], "state": "active"}
        self.authority["runtimeTrustRoot"]["expectedSha256"] = (
            runtime_trust_root_sha256(self.trust_root)
        )
        self.verifier = RuntimeReceiptVerifier(
            authority=self.authority,
            runtime_trust_root=self.trust_root,
            now=NOW,
        )
        coordinator_key = self.fixture.keys[self.factory.COORDINATOR_KEY_ID]
        self.coordinator_public_keys = {
            self.factory.COORDINATOR_KEY_ID: coordinator_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        }
        self.binding_handoff = self.handoff()
        self.evaluation_preflight = self.preflight(
            issued_at="2026-07-18T20:20:00Z",
            expires_at="2026-07-18T20:25:00Z",
            request_id="31000000-0000-4000-8000-000000000001",
        )
        self.redemption_preflight = self.preflight(
            issued_at="2026-07-18T20:21:00Z",
            expires_at="2026-07-18T20:26:00Z",
            request_id="31000000-0000-4000-8000-000000000002",
        )
        self.lease_envelope = self.lease()

    def handoff(self) -> dict[str, Any]:
        workflow_ref = self.binding["workflowRef"]
        intent_ref = self.binding["intentRef"]
        payload = {
            "schemaVersion": "faz22.6.viewOnlyTransactionBindingHandoff.v1",
            "handoffId": "30000000-0000-4000-8000-000000000001",
            "lookupRequestId": "30000000-0000-4000-8000-000000000002",
            "idempotencyKeySha256": digest("binding-idempotency"),
            "binding": self.binding,
            "bindingSha256": self.binding_sha,
            "transactionIdSha256": self.transaction_id,
            "derivation": {
                "bundleSchemaVersion": "acik.cross-ai-deployment-bundle.v3",
                "bundleRequestId": self.authorization.request_id,
                "bundleEnvelopeSha256": self.authorization.bundle_digest,
                "registryState": "DispatchAccepted",
                "intentRefObjectId": "a" * 40,
                "intentRefHeadSha": self.binding["headSha"],
                "intentRefFinalized": True,
                "dispatchAccepted": True,
                "dispatchWatermarkRunId": RUN_ID - 1,
                "dispatchRunId": RUN_ID,
                "dispatchRunAttempt": 1,
                "dispatchTriggeringActorId": self.binding["triggeringActorId"],
                "dispatchHeadBranch": intent_ref.removeprefix("refs/tags/"),
                "dispatchHeadRepository": self.binding["repository"],
                "dispatchRepository": self.binding["repository"],
                "dispatchWorkflowPath": self.binding["workflowPath"],
                "dispatchStatus": "in_progress",
                "dispatchHeadSha": self.binding["headSha"],
                "dispatchWorkflowRef": workflow_ref,
                "correlatedAt": "2026-07-18T20:18:30Z",
            },
            "caller": {
                "profile": "binding",
                "subject": f"repo:{self.binding['repository']}:ref:{intent_ref}",
                "ref": intent_ref,
                "workflowRef": workflow_ref,
                "headSha": self.binding["headSha"],
                "runId": RUN_ID,
                "runAttempt": 1,
                "triggeringActorId": self.binding["triggeringActorId"],
                "runnerEnvironment": "github-hosted",
                "tokenJtiSha256": digest("binding-jti"),
            },
            "issuedAt": "2026-07-18T20:19:00Z",
            "expiresAt": "2026-07-18T20:24:00Z",
            "maxUses": 1,
            "mutationCount": 0,
        }
        return self.factory.sign(
            BINDING_HANDOFF_PAYLOAD_TYPE,
            payload,
            self.factory.COORDINATOR_KEY_ID,
        )

    def caller(self, profile: str) -> dict[str, Any]:
        environment_subject = (
            f"repo:{self.binding['repository']}:environment:"
            f"{self.binding['environment']}"
        )
        ref_subject = (
            f"repo:{self.binding['repository']}:ref:{self.binding['intentRef']}"
        )
        return {
            "profile": profile,
            "subject": environment_subject if profile == "authorization" else ref_subject,
            "runId": RUN_ID,
            "runAttempt": 1,
            "headSha": self.binding["headSha"],
            "tokenJtiSha256": digest(f"{profile}-jti"),
        }

    def preflight(
        self, *, issued_at: str, expires_at: str, request_id: str
    ) -> dict[str, Any]:
        check = {
            "checkVersion": "v1",
            "status": "PASS",
            "source": "attestor-runtime",
            "evidenceSha256": digest(f"evidence-{request_id}"),
            "observedAt": issued_at,
            "expiresAt": expires_at,
        }
        payload = {
            "schemaVersion": "faz22.6.viewOnlyLivePreflightAttestation.v1",
            "receiptId": str(uuid.uuid4()),
            "requestId": request_id,
            "idempotencyKeySha256": digest(f"idempotency-{request_id}"),
            "requestSha256": digest(f"request-{request_id}"),
            "bindingHandoffEnvelopeSha256": runtime_envelope_sha256(
                self.binding_handoff
            ),
            "bindingSha256": self.binding_sha,
            "transactionIdSha256": self.transaction_id,
            "binding": self.binding,
            "caller": {
                "profile": "preflight",
                "issuer": "https://token.actions.githubusercontent.com",
                "audience": "faz22-view-only-preflight",
                "subject": (
                    f"repo:{self.binding['repository']}:ref:"
                    f"{self.binding['intentRef']}"
                ),
                "repository": self.binding["repository"],
                "repositoryId": str(self.binding["repositoryId"]),
                "workflowRef": self.binding["workflowRef"],
                "ref": self.binding["intentRef"],
                "headSha": self.binding["headSha"],
                "runId": RUN_ID,
                "runAttempt": 1,
                "runnerEnvironment": "github-hosted",
                "tokenIssuedAt": issued_at,
                "tokenExpiresAt": expires_at,
                "tokenJtiSha256": digest(f"preflight-jti-{request_id}"),
            },
            "persona": {
                "identitySha256": self.binding["preflightPersonaIdentitySha256"],
                "tenantIdSha256": self.binding["tenantIdSha256"],
                "expiresAt": "2026-07-18T21:00:00Z",
                "preprovisioned": True,
                "adminCredentialUsed": False,
                "userConfigurationMutationCount": 0,
            },
            "checks": {
                name: dict(check)
                for name in (
                    "targetIdentity",
                    "pkceAuthorizationCode",
                    "tokenRefresh",
                    "routeApi",
                    "browserConsole",
                    "replayIsolation",
                    "clusterContext",
                    "portsTunnels",
                    "imageDigests",
                    "policyMask",
                    "runnerCapacity",
                    "watchdogRollback",
                )
            },
            "mutationCount": 0,
            "attendedConsentAttempted": False,
            "issuedAt": issued_at,
            "expiresAt": expires_at,
            "maxUses": 1,
            "replayIdentitySha256": digest(f"replay-{request_id}"),
            "verdict": "PASS",
        }
        return sign(
            self.attestor_key,
            self.attestor_key_id,
            PREFLIGHT_PAYLOAD_TYPE,
            payload,
        )

    def lease(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": "faz22.6.viewOnlyCheckpointLease.v1",
            "leaseId": "32000000-0000-4000-8000-000000000001",
            "redeemRequestId": "32000000-0000-4000-8000-000000000002",
            "idempotencyKeySha256": digest("lease-idempotency"),
            "transactionIdSha256": self.transaction_id,
            "bindingSha256": self.binding_sha,
            "binding": self.binding,
            "evaluationPreflightReceiptEnvelopeSha256": (
                runtime_envelope_sha256(self.evaluation_preflight)
            ),
            "redemptionPreflightReceiptEnvelopeSha256": (
                runtime_envelope_sha256(self.redemption_preflight)
            ),
            "redemptionPreflightIssuedAt": "2026-07-18T20:21:00Z",
            "authorizationEnvelopeSha256": runtime_envelope_sha256(
                self.fixture.bundle_envelope
            ),
            "authorizationPayloadType": (
                "application/vnd.acik.cross-ai-deployment-bundle.v3+json"
            ),
            "authorizationRedemptionCount": 1,
            "authorizationCaller": self.caller("authorization"),
            "executorProfile": {
                "audience": "faz22-view-only-checkpoint",
                "subject": self.caller("executor")["subject"],
                "runnerEnvironment": "self-hosted",
            },
            "issuedAt": "2026-07-18T20:22:00Z",
            "expiresAt": "2026-07-18T21:22:00Z",
            "sequenceMinimumInclusive": 0,
            "sequenceMaximumInclusive": 63,
            "maxWrites": 64,
            "closed": False,
        }
        return sign(
            self.checkpoint_key,
            self.checkpoint_key_id,
            LEASE_PAYLOAD_TYPE,
            payload,
        )

    def checkpoint(
        self,
        *,
        sequence: int,
        state: str,
        previous: Any = None,
        reason_code: str | None = None,
        terminal: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        previous_payload = previous.payload if previous is not None else None
        reason = reason_code or (
            "decision-authorized" if sequence == 0 else "live-revalidated"
        )
        request = {
            "schemaVersion": "faz22.6.viewOnlyExternalCheckpointCreate.v1",
            "requestId": f"33000000-0000-4000-8000-{sequence + 1:012d}",
            "leaseEnvelope": self.lease_envelope,
            "transactionIdSha256": self.transaction_id,
            "bindingSha256": self.binding_sha,
            "sequence": sequence,
            "previousState": (
                previous_payload["state"] if previous_payload is not None else None
            ),
            "state": state,
            "reasonCode": reason,
            "localCheckpointSha256": digest(f"local-checkpoint-{sequence}"),
            "localPayloadSha256": digest(f"local-payload-{sequence}"),
            "previousStoredObjectSha256": (
                previous_payload["storedObjectSha256"]
                if previous_payload is not None
                else None
            ),
            "idempotencyKeySha256": digest(f"checkpoint-idempotency-{sequence}"),
            "terminal": terminal,
        }
        without_lease = dict(request)
        without_lease.pop("leaseEnvelope")
        lease_payload = self.factory.decode_payload(self.lease_envelope)
        payload = {
            "schemaVersion": "faz22.6.viewOnlyExternalCheckpointReceipt.v1",
            "receiptId": str(uuid.uuid4()),
            "leaseId": lease_payload["leaseId"],
            "leaseEnvelopeSha256": runtime_envelope_sha256(self.lease_envelope),
            "transactionIdSha256": self.transaction_id,
            "bindingSha256": self.binding_sha,
            "binding": self.binding,
            "evaluationPreflightReceiptEnvelopeSha256": lease_payload[
                "evaluationPreflightReceiptEnvelopeSha256"
            ],
            "redemptionPreflightReceiptEnvelopeSha256": lease_payload[
                "redemptionPreflightReceiptEnvelopeSha256"
            ],
            "authorizationEnvelopeSha256": lease_payload[
                "authorizationEnvelopeSha256"
            ],
            "sequence": sequence,
            "previousState": request["previousState"],
            "state": state,
            "reasonCode": request["reasonCode"],
            "storedObjectSha256": sha256_digest(
                {
                    "domain": CHECKPOINT_STORED_OBJECT_DOMAIN,
                    "request": without_lease,
                }
            ),
            "previousStoredObjectSha256": request[
                "previousStoredObjectSha256"
            ],
            "localCheckpointSha256": request["localCheckpointSha256"],
            "localPayloadSha256": request["localPayloadSha256"],
            "idempotencyKeySha256": request["idempotencyKeySha256"],
            "executorCaller": self.caller("executor"),
            "createdAt": "2026-07-18T20:23:00Z",
            "expiresAt": "2026-07-18T21:22:00Z",
            "terminal": terminal,
            "credentialMaterialStored": False,
        }
        return request, sign(
            self.checkpoint_key,
            self.checkpoint_key_id,
            CHECKPOINT_PAYLOAD_TYPE,
            payload,
        )

    def terminal_chain(
        self,
    ) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        states = (
            "DECISION_AUTHORIZED",
            "LIVE_REVALIDATED",
            "ACTIVATED",
            "CONSENT_PENDING",
            "EVIDENCE_COLLECTED",
            "EVIDENCE_VERIFIED",
            "ARTIFACTS_STAGED",
            "ROLLBACK_PENDING",
            "ROLLED_BACK",
            "COMPLETED",
        )
        envelopes: list[dict[str, Any]] = []
        local_checkpoints = [
            {
                "state": "INIT",
                "reasonCode": "initialized",
                "checkpointSha256": digest("local-init-checkpoint"),
                "payloadSha256": digest("local-init-payload"),
            },
            {
                "state": "PREFLIGHT_VERIFIED",
                "reasonCode": "preflight-verified",
                "checkpointSha256": digest("local-preflight-checkpoint"),
                "payloadSha256": digest("local-preflight-payload"),
            },
        ]
        previous = None
        for sequence, state in enumerate(states):
            reason = state.lower().replace("_", "-")
            _, envelope = self.checkpoint(
                sequence=sequence,
                state=state,
                previous=previous,
                reason_code=reason,
                terminal=sequence == len(states) - 1,
            )
            previous = self.verifier.verify_checkpoint(
                envelope=envelope,
                lease=self.verified_lease(),
                binding=self.binding,
                previous=previous,
            )
            envelopes.append(envelope)
            local_checkpoints.append(
                {
                    "state": state,
                    "reasonCode": reason,
                    "checkpointSha256": digest(f"local-checkpoint-{sequence}"),
                    "payloadSha256": digest(f"local-payload-{sequence}"),
                }
            )
        final_state = {
            "currentState": "COMPLETED",
            "sequence": len(local_checkpoints) - 1,
            "checkpoints": local_checkpoints,
        }
        return tuple(envelopes), final_state

    def verified_lease(self):
        return self.verifier.verify_lease(
            envelope=self.lease_envelope,
            binding=self.binding,
            evaluation_preflight_envelope=self.evaluation_preflight,
            redemption_preflight_envelope=self.redemption_preflight,
            authorization_envelope=self.fixture.bundle_envelope,
            authorization_bundle=self.authorization,
        )

    def test_accepts_full_preflight_lease_and_checkpoint_chain(self) -> None:
        lease = self.verified_lease()
        request0, envelope0 = self.checkpoint(
            sequence=0,
            state="DECISION_AUTHORIZED",
        )
        receipt0 = self.verifier.verify_checkpoint(
            envelope=envelope0,
            lease=lease,
            binding=self.binding,
            request=request0,
        )
        request1, envelope1 = self.checkpoint(
            sequence=1,
            state="LIVE_REVALIDATED",
            previous=receipt0,
        )
        receipt1 = self.verifier.verify_checkpoint(
            envelope=envelope1,
            lease=lease,
            binding=self.binding,
            request=request1,
            previous=receipt0,
        )
        self.assertEqual(receipt1.payload["sequence"], 1)
        self.assertEqual(receipt1.payload["state"], "LIVE_REVALIDATED")

    def test_rejects_wrong_runtime_trust_pin_and_revoked_signer(self) -> None:
        wrong = copy.deepcopy(self.authority)
        wrong["runtimeTrustRoot"]["expectedSha256"] = digest("wrong-trust-root")
        with self.assertRaisesRegex(PolicyError, "RUNTIME_AUTHORITY_INACTIVE"):
            RuntimeReceiptVerifier(
                authority=wrong,
                runtime_trust_root=self.trust_root,
                now=NOW,
            )
        revoked_root = copy.deepcopy(self.trust_root)
        revoked_root["revocations"] = [
            {
                "keyId": self.attestor_key_id,
                "revokedAt": "2026-07-18T20:00:00Z",
                "reasonCode": "test-revocation",
            }
        ]
        revoked_authority = copy.deepcopy(self.authority)
        revoked_authority["runtimeTrustRoot"]["expectedSha256"] = (
            runtime_trust_root_sha256(revoked_root)
        )
        verifier = RuntimeReceiptVerifier(
            authority=revoked_authority,
            runtime_trust_root=revoked_root,
            now=NOW,
        )
        with self.assertRaisesRegex(PolicyError, "RUNTIME_SIGNER_INACTIVE"):
            verifier.verify_preflight(
                envelope=self.evaluation_preflight,
                binding=self.binding,
            )

    def test_rejects_binding_and_checkpoint_sequence_drift(self) -> None:
        wrong_binding = dict(self.binding)
        wrong_binding["headSha"] = "f" * 40
        with self.assertRaisesRegex(PolicyError, "RUNTIME_BINDING_MISMATCH"):
            self.verifier.verify_preflight(
                envelope=self.evaluation_preflight,
                binding=wrong_binding,
            )
        lease = self.verified_lease()
        request0, envelope0 = self.checkpoint(
            sequence=0,
            state="DECISION_AUTHORIZED",
        )
        receipt0 = self.verifier.verify_checkpoint(
            envelope=envelope0,
            lease=lease,
            binding=self.binding,
            request=request0,
        )
        request, envelope = self.checkpoint(
            sequence=1,
            state="LIVE_REVALIDATED",
            previous=receipt0,
        )
        with self.assertRaisesRegex(
            PolicyError,
            "RUNTIME_CHECKPOINT_SEQUENCE_INVALID",
        ):
            self.verifier.verify_checkpoint(
                envelope=envelope,
                lease=lease,
                binding=self.binding,
                request=request,
            )

    def test_rejects_checkpoint_create_body_digest_drift(self) -> None:
        lease = self.verified_lease()
        request, envelope = self.checkpoint(
            sequence=0,
            state="DECISION_AUTHORIZED",
        )
        request["localPayloadSha256"] = digest("tampered-local-payload")
        with self.assertRaisesRegex(PolicyError, "RUNTIME_CHECKPOINT_MISMATCH"):
            self.verifier.verify_checkpoint(
                envelope=envelope,
                lease=lease,
                binding=self.binding,
                request=request,
            )

    def test_accepts_terminal_chain_after_action_ttl_for_reconciliation(self) -> None:
        checkpoint_envelopes, final_state = self.terminal_chain()
        chain = self.verifier.verify_chain(
            binding_handoff_envelope=self.binding_handoff,
            coordinator_public_keys=self.coordinator_public_keys,
            coordinator_key_id=self.factory.COORDINATOR_KEY_ID,
            evaluation_preflight_envelope=self.evaluation_preflight,
            redemption_preflight_envelope=self.redemption_preflight,
            lease_envelope=self.lease_envelope,
            authorization_envelope=self.fixture.bundle_envelope,
            authorization_bundle=self.authorization,
            checkpoint_envelopes=checkpoint_envelopes,
            final_state=final_state,
            observed_at=datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(chain.terminal.payload["state"], "COMPLETED")
        self.assertTrue(chain.terminal.payload["terminal"])
        self.assertEqual(len(chain.checkpoints), 10)

    def test_rejects_incomplete_or_locally_divergent_terminal_chain(self) -> None:
        checkpoint_envelopes, final_state = self.terminal_chain()
        common = {
            "binding_handoff_envelope": self.binding_handoff,
            "coordinator_public_keys": self.coordinator_public_keys,
            "coordinator_key_id": self.factory.COORDINATOR_KEY_ID,
            "evaluation_preflight_envelope": self.evaluation_preflight,
            "redemption_preflight_envelope": self.redemption_preflight,
            "lease_envelope": self.lease_envelope,
            "authorization_envelope": self.fixture.bundle_envelope,
            "authorization_bundle": self.authorization,
            "final_state": final_state,
            "observed_at": datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc),
        }
        with self.assertRaisesRegex(PolicyError, "RUNTIME_CHAIN_INCOMPLETE"):
            self.verifier.verify_chain(
                checkpoint_envelopes=checkpoint_envelopes[:-1],
                **common,
            )
        tampered = copy.deepcopy(final_state)
        tampered["checkpoints"][-1]["payloadSha256"] = digest(
            "tampered-terminal-payload"
        )
        with self.assertRaisesRegex(PolicyError, "RUNTIME_CHAIN_LOCAL_MISMATCH"):
            self.verifier.verify_chain(
                checkpoint_envelopes=checkpoint_envelopes,
                **{**common, "final_state": tampered},
            )

    def test_parses_only_one_canonical_bounded_runtime_evidence_file(self) -> None:
        request, checkpoint = self.checkpoint(
            sequence=0,
            state="DECISION_AUTHORIZED",
        )
        self.assertEqual(request["sequence"], 0)
        package = {
            "schemaVersion": "faz22.6.viewOnlyRuntimeEvidence.v1",
            "bindingHandoffEnvelope": self.binding_handoff,
            "evaluationPreflightEnvelope": self.evaluation_preflight,
            "redemptionPreflightEnvelope": self.redemption_preflight,
            "leaseEnvelope": self.lease_envelope,
            "checkpointEnvelopes": [checkpoint],
        }
        output = io.BytesIO()
        info = zipfile.ZipInfo(
            "runtime-evidence.json",
            date_time=(2026, 7, 18, 20, 30, 0),
        )
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100600 << 16
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr(info, canonical_bytes(package))
        archive = output.getvalue()
        parsed = runtime_evidence_from_archive(archive)
        self.assertEqual(parsed.checkpoint_envelopes, (checkpoint,))
        self.assertEqual(
            parsed.archive_sha256,
            f"sha256:{hashlib.sha256(archive).hexdigest()}",
        )

        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("other.json", canonical_bytes(package))
        with self.assertRaisesRegex(
            PolicyError,
            "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
        ):
            runtime_evidence_from_archive(unsafe.getvalue())


if __name__ == "__main__":
    unittest.main()
