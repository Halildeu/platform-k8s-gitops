"""Deterministic signed fixtures for the Cross-AI deployment policy tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    BUNDLE_PAYLOAD_TYPE,
    BUNDLE_PAYLOAD_TYPE_V2,
    BUNDLE_PAYLOAD_TYPE_V3,
    CLOSURE_DOMAIN,
    CLOSURE_DOMAIN_V2,
    CLOSURE_DOMAIN_V3,
    REVIEW_PAYLOAD_TYPE,
    REVIEW_PAYLOAD_TYPE_V2,
    REVOCATIONS_PAYLOAD_TYPE,
    SESSION_DOMAIN,
    SESSION_DOMAIN_V2,
    SESSION_DOMAIN_V3,
)
from scripts.github_apps.cross_ai_deployment_policy.dsse import pae


def digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _key(seed_byte: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([seed_byte]) * 32)


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass
class SignedFixture:
    trust_root: dict[str, Any]
    revocations_envelope: dict[str, Any]
    bundle_envelope: dict[str, Any]
    keys: dict[str, Ed25519PrivateKey]
    now: datetime


class FixtureFactory:
    ANTHROPIC_KEY_ID = "vault-transit://cross-ai/anthropic#v1"
    MINIMAX_KEY_ID = "vault-transit://cross-ai/minimax#v1"
    OPENAI_KEY_ID = "vault-transit://cross-ai/openai#v1"
    COORDINATOR_KEY_ID = "vault-transit://cross-ai/coordinator#v1"
    REVOCATION_KEY_ID = "vault-transit://cross-ai/revocation#v1"
    RUNNER_MANAGEMENT_KEY_ID = "vault-transit://cross-ai/runner-management#v1"
    TRANSACTION_DEVICE_ID = "123e4567-e89b-42d3-a456-426614174000"
    TRANSACTION_DEVICE_HOSTNAME = "denetim-pc"
    TRANSACTION_MASK_RECT_BPS = "7500,7500,2500,2500"
    TRANSACTION_REVIEWED_HEAD_SHA = "708846651bbc99f1995bca470e7a5012fd2dd486"

    TRANSACTION_AUTHORITY_PATHS = (
        ".github/workflows/faz22-6-view-only-viewer-transaction.yml",
        "config/faz22-6-view-only-live-preflight-authority.v1.json",
        "config/faz22-6-view-only-runtime-trust-root.v1.json",
        "docs/adr/0046-faz22-6-view-only-pre-gate-attestor-and-external-checkpoints.md",
        "schema/faz22-6-dsse-envelope-v1.schema.json",
        "schema/faz22-6-view-only-checkpoint-lease-redeem-v1.schema.json",
        "schema/faz22-6-view-only-checkpoint-lease-v1.schema.json",
        "schema/faz22-6-view-only-external-checkpoint-create-v1.schema.json",
        "schema/faz22-6-view-only-external-checkpoint-receipt-v1.schema.json",
        "schema/faz22-6-view-only-live-preflight-attestation-v1.schema.json",
        "schema/faz22-6-view-only-live-preflight-request-v1.schema.json",
        "schema/faz22-6-view-only-preflight-error-v1.schema.json",
        "schema/faz22-6-view-only-runtime-trust-root-v1.schema.json",
        "schema/faz22-6-view-only-transaction-binding-handoff-v1.schema.json",
        "schema/faz22-6-view-only-transaction-binding-request-v1.schema.json",
        "schema/faz22-6-view-only-transaction-binding-v1.schema.json",
        "scripts/faz22-remote-ops/run-view-only-same-job-supervisor.sh",
        "scripts/test/faz22-6-view-only-transaction-static.sh",
        "tests/faz22_remote_ops/test_view_only_preflight_contract.py",
        "tests/faz22_remote_ops/test_view_only_same_job_supervisor.sh",
    )
    TRANSACTION_AUTHORITY_SHA256 = {
        ".github/workflows/faz22-6-view-only-viewer-transaction.yml": (
            "sha256:e44eefb61bee288525fd1f2068c420a7fd10b82958b1a503c9f410cb148a65c4"
        ),
        "config/faz22-6-view-only-live-preflight-authority.v1.json": (
            "sha256:e3db632eff11abedcc18393304ac65ae20cdc5fe9cf00c3def71e3ab91793703"
        ),
        "config/faz22-6-view-only-runtime-trust-root.v1.json": (
            "sha256:4d95852b02de299e9b51e966a2c9ee614ab81c9f12f5d45904803b6e67d68720"
        ),
        "docs/adr/0046-faz22-6-view-only-pre-gate-attestor-and-external-checkpoints.md": (
            "sha256:9bed97306ff78d79aa1a5414ff5d8358b32b6484895a3a2aad8a879c1cec1784"
        ),
        "schema/faz22-6-dsse-envelope-v1.schema.json": (
            "sha256:c4522b277d451f204b3f5cee0cb423f97193129475b7521db3e7a5eef32324ee"
        ),
        "schema/faz22-6-view-only-checkpoint-lease-redeem-v1.schema.json": (
            "sha256:924bb03d4d2cfa1f9427d050bd83f2764d508df00e251e7c62ca4e216a78122e"
        ),
        "schema/faz22-6-view-only-checkpoint-lease-v1.schema.json": (
            "sha256:a9771f265d22c1b339ee4ca94b611de1dfbfd69f3e683c0a565cfc39cc8ea0b7"
        ),
        "schema/faz22-6-view-only-external-checkpoint-create-v1.schema.json": (
            "sha256:0fde68e2d26fe2b3c9bbfbd26024acdf7fb992e85f3aee13a5ff2344d110f0ef"
        ),
        "schema/faz22-6-view-only-external-checkpoint-receipt-v1.schema.json": (
            "sha256:0ea1e79e886cfbeb4b761e9a678516c879b557a7f2bc9043fe3182d8917015be"
        ),
        "schema/faz22-6-view-only-live-preflight-attestation-v1.schema.json": (
            "sha256:3162ecfecdc4d7d6dc1f40936cfefd5d0dbcec1e93489ca87d682c6179ab5cf2"
        ),
        "schema/faz22-6-view-only-live-preflight-request-v1.schema.json": (
            "sha256:2d7fc35b9eb09735f8d250f7027638e1469eb2d7e8889e97a782d72a6b93c79d"
        ),
        "schema/faz22-6-view-only-preflight-error-v1.schema.json": (
            "sha256:024351c2c2c61c34b2ebaf1c71323fcb6c2466c3af4272a110c18efaeb1f7572"
        ),
        "schema/faz22-6-view-only-runtime-trust-root-v1.schema.json": (
            "sha256:d5ca2cb08c8b062d6e0241da63b0c6ec6beeed78180ef1d253de519efc23cec5"
        ),
        "schema/faz22-6-view-only-transaction-binding-handoff-v1.schema.json": (
            "sha256:6cb297d980d9284c696fe6587ce6645e341c71beb9889995e3496b9f1b985aaa"
        ),
        "schema/faz22-6-view-only-transaction-binding-request-v1.schema.json": (
            "sha256:7549c187881909eadfdc6c43fdef874e5c6820b1f7fdf9390c26884de16af624"
        ),
        "schema/faz22-6-view-only-transaction-binding-v1.schema.json": (
            "sha256:1db5ebce2867a2bd003eef4b7480ce3b63f76eb5a405071a3b7d25b84a50cfed"
        ),
        "scripts/faz22-remote-ops/run-view-only-same-job-supervisor.sh": (
            "sha256:84a7e853bd88af0ae4f25005ae0c775766d91a0777fdbb9d4d7555f7cfa32aa3"
        ),
        "scripts/test/faz22-6-view-only-transaction-static.sh": (
            "sha256:bc8ca06242fb3de1a7389ed1e50c21fb3d49843099fe0a4338f0ddc404331fe7"
        ),
        "tests/faz22_remote_ops/test_view_only_preflight_contract.py": (
            "sha256:b15e1babe08e9679340981ee63cca966cdfdf5b22389224d2d93f8b8b72f595d"
        ),
        "tests/faz22_remote_ops/test_view_only_same_job_supervisor.sh": (
            "sha256:e1f672bab42cad0ebc2b3b0fb17bf9f11d4382f4c672a95d60174e6827b7e5bb"
        ),
    }
    TRANSACTION_WORKFLOW_SHA256 = (
        "sha256:e44eefb61bee288525fd1f2068c420a7fd10b82958b1a503c9f410cb148a65c4"
    )
    TRANSACTION_DEPENDENCY_LOCK_SHA256 = (
        "sha256:5ae355c5da79f3ff87f239b9ff2153e27e50b30272a3689390eb996ab51b8642"
    )
    TRANSACTION_CONCURRENCY_SHA256 = (
        "sha256:aaa716b30f77f1d920df5e436196e8f5582f505fe95e6844c27ef9bb7998564d"
    )

    def __init__(self, contract_version: str = "v1") -> None:
        if contract_version not in {"v1", "v2", "v3"}:
            raise ValueError("unsupported fixture contract version")
        self.contract_version = contract_version
        self.day = "2026-07-16" if contract_version == "v1" else "2026-07-18"
        self.bundle_payload_type = {
            "v1": BUNDLE_PAYLOAD_TYPE,
            "v2": BUNDLE_PAYLOAD_TYPE_V2,
            "v3": BUNDLE_PAYLOAD_TYPE_V3,
        }[contract_version]
        self.review_payload_type = (
            REVIEW_PAYLOAD_TYPE if contract_version == "v1" else REVIEW_PAYLOAD_TYPE_V2
        )
        self.session_domain = (
            {
                "v1": SESSION_DOMAIN,
                "v2": SESSION_DOMAIN_V2,
                "v3": SESSION_DOMAIN_V3,
            }[contract_version]
        )
        self.closure_domain = (
            {
                "v1": CLOSURE_DOMAIN,
                "v2": CLOSURE_DOMAIN_V2,
                "v3": CLOSURE_DOMAIN_V3,
            }[contract_version]
        )
        self.keys = {
            self.ANTHROPIC_KEY_ID: _key(1),
            self.MINIMAX_KEY_ID: _key(2),
            self.OPENAI_KEY_ID: _key(3),
            self.COORDINATOR_KEY_ID: _key(4),
            self.REVOCATION_KEY_ID: _key(5),
            self.RUNNER_MANAGEMENT_KEY_ID: _key(6),
        }
        self.now = _utc(f"{self.day}T20:30:00Z")

    def sign(
        self,
        payload_type: str,
        payload: dict[str, Any],
        key_id: str,
    ) -> dict[str, Any]:
        payload_bytes = canonical_bytes(payload)
        signature = self.keys[key_id].sign(pae(payload_type, payload_bytes))
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": key_id,
                    "sig": base64.b64encode(signature).decode("ascii"),
                }
            ],
        }

    def decode_payload(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return json.loads(base64.b64decode(envelope["payload"], validate=True))

    def resign_bundle(self, envelope: dict[str, Any], bundle: dict[str, Any]) -> None:
        replacement = self.sign(
            self.bundle_payload_type,
            bundle,
            self.COORDINATOR_KEY_ID,
        )
        envelope.clear()
        envelope.update(replacement)

    def trust_root(self) -> dict[str, Any]:
        def entry(
            key_id: str,
            role: str,
            family: str | None,
            channels: list[str],
            direct: bool | None,
            model_ids: list[str] | None = None,
            identity_classes: list[str] | None = None,
        ) -> dict[str, Any]:
            return {
                "keyId": key_id,
                "role": role,
                "publicKeyBase64": _public_b64(self.keys[key_id]),
                "notBefore": f"{self.day}T19:00:00Z",
                "notAfter": f"{self.day}T22:00:00Z",
                "providerFamily": family,
                "allowedChannels": channels,
                "allowedModelIds": model_ids or [],
                "allowedModelIdentityClasses": identity_classes or [],
                "directProviderCli": direct,
            }

        providers = ["anthropic", "minimax", "openai"]
        provider_entries: list[dict[str, Any]] = []
        if self.contract_version == "v1":
            provider_entries.append(
                entry(
                    self.ANTHROPIC_KEY_ID,
                    "provider-review",
                    "anthropic",
                    ["direct-anthropic-cli"],
                    True,
                    ["claude-opus-4-8"],
                    ["provider-reported"],
                )
            )
            provider_entries.append(
                entry(
                    self.MINIMAX_KEY_ID,
                    "provider-review",
                    "minimax",
                    ["direct-minimax-cli"],
                    True,
                    ["minimax/MiniMax-M3"],
                    ["provider-reported"],
                )
            )
        else:
            providers = ["openai"]
        provider_entries.append(
            entry(
                self.OPENAI_KEY_ID,
                "provider-review",
                "openai",
                ["openai-codex"],
                True,
                ["gpt-5.6-sol"],
                [
                    "provider-reported"
                    if self.contract_version == "v1"
                    else "trusted-launch-attested"
                ],
            )
        )
        trust_root = {
            "schemaVersion": (
                "acik.cross-ai-deployment-trust-root.v1"
                if self.contract_version == "v1"
                else "acik.cross-ai-deployment-trust-root.v2"
            ),
            "trustRootId": "10000000-0000-4000-8000-000000000001",
            "issuedAt": f"{self.day}T19:00:00Z",
            "expiresAt": f"{self.day}T22:00:00Z",
            "maxClockSkewSeconds": 60,
            "requiredProviderFamilies": providers,
            "minimumProviderFamilies": len(providers),
            "minimumDirectProviderRoutes": len(providers),
            "keys": provider_entries
            + [
                entry(self.COORDINATOR_KEY_ID, "coordinator", None, [], None),
                entry(self.REVOCATION_KEY_ID, "revocation", None, [], None),
                entry(
                    self.RUNNER_MANAGEMENT_KEY_ID,
                    "runner-management",
                    None,
                    [],
                    None,
                ),
            ],
        }
        if self.contract_version in {"v2", "v3"}:
            trust_root["sourcePublicKeysetSha256"] = digest("public-keyset-v2")
        return trust_root

    def revocations(
        self, entries: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload = {
            "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
            "revocationSetId": "20000000-0000-4000-8000-000000000001",
            "issuedAt": f"{self.day}T20:00:00Z",
            "nextUpdate": f"{self.day}T21:30:00Z",
            "entries": entries or [],
        }
        return self.sign(REVOCATIONS_PAYLOAD_TYPE, payload, self.REVOCATION_KEY_ID)

    def _review(
        self,
        *,
        review_id: str,
        chain_id: str,
        key_id: str,
        round_number: int,
        verdict: str,
        previous: str | None,
        closure_root: str,
        finding_ids: list[str] | None = None,
        resolved: list[str] | None = None,
        acknowledged: list[str] | None = None,
        issued_at: str,
        subject_digest: str,
    ) -> dict[str, Any]:
        if key_id == self.ANTHROPIC_KEY_ID:
            family, channel, direct = "anthropic", "direct-anthropic-cli", True
            model = "claude-opus-4-8"
        elif key_id == self.MINIMAX_KEY_ID:
            family, channel, direct = "minimax", "direct-minimax-cli", True
            model = "minimax/MiniMax-M3"
        elif key_id == self.OPENAI_KEY_ID:
            family, channel, direct = "openai", "openai-codex", True
            model = "gpt-5.6-sol"
        else:
            raise ValueError(f"unsupported provider key {key_id}")
        payload = {
            "schemaVersion": (
                "acik.cross-ai-deployment-review.v1"
                if self.contract_version == "v1"
                else "acik.cross-ai-deployment-review.v2"
            ),
            "reviewId": review_id,
            "reviewChainId": chain_id,
            "providerFamily": family,
            "channel": channel,
            "directProviderCli": direct,
            "modelId": model,
            "modelIdentityClass": (
                "trusted-launch-attested"
                if key_id == self.OPENAI_KEY_ID and self.contract_version != "v1"
                else "provider-reported"
            ),
            "capabilitySnapshotSha256": digest(f"capability-{review_id}"),
            "subjectSha256": subject_digest,
            "round": round_number,
            "verdict": verdict,
            "inputSha256": digest(f"input-{review_id}"),
            "outputSha256": digest(f"output-{review_id}"),
            "findingsSha256": digest(f"findings-{review_id}"),
            "previousRoundSha256": previous,
            "findingIds": finding_ids or [],
            "resolvedFindingIds": resolved or [],
            "acknowledgedFindingIds": acknowledged or [],
            "closureRootSha256": closure_root,
            "issuedAt": issued_at,
            "expiresAt": f"{self.day}T21:30:00Z",
            "issuer": f"cross-ai-issuer-{family}",
            "keyId": key_id,
        }
        if self.contract_version != "v1":
            payload.update(
                {
                    "reasoningEffort": "xhigh",
                    "sandbox": "read-only",
                    "ephemeral": True,
                }
            )
        return self.sign(self.review_payload_type, payload, key_id)

    def build(
        self,
        *,
        stage_overrides: dict[str, dict[str, Any]] | None = None,
        policy_digest: str | None = None,
        bootstrap_credential: bytes = b"B" * 64,
        authority_contents: dict[str, bytes] | None = None,
    ) -> SignedFixture:
        request_id = "30000000-0000-4000-8000-000000000001"
        session_id = "30000000-0000-4000-8000-000000000002"
        if authority_contents is None:
            authority_files = [
                {"path": path, "sha256": self.TRANSACTION_AUTHORITY_SHA256[path]}
                for path in sorted(self.TRANSACTION_AUTHORITY_PATHS)
            ]
        else:
            if set(authority_contents) != set(self.TRANSACTION_AUTHORITY_PATHS):
                raise ValueError("authority contents must cover the exact v3 inventory")
            authority_files = [
                {
                    "path": path,
                    "sha256": (
                        "sha256:" + hashlib.sha256(authority_contents[path]).hexdigest()
                    ),
                }
                for path in sorted(self.TRANSACTION_AUTHORITY_PATHS)
            ]
        transaction_scope_sha256 = sha256_digest(
            {
                "domain": "acik.cross-ai-transaction-authority-set.v1",
                "files": authority_files,
            }
        )
        subject: dict[str, Any] = {
            "repositoryId": 123456789,
            "repository": "Halildeu/platform-k8s-gitops",
            "headSha": "0123456789abcdef0123456789abcdef01234567",
            "intentRef": f"refs/tags/cross-ai-intent/{request_id}",
            "environment": "faz22-view-only-pilot",
            "deploymentClass": "reversible-test",
            "productSlice": "Halildeu/platform-k8s-gitops#2373",
            "policySha256": policy_digest or digest("policy"),
            "artifactSetSha256": digest("artifacts"),
            "rollbackPlanSha256": digest("rollback"),
            "postDeployVerifierSha256": digest("verifier"),
            "runnerPolicySha256": digest("runner-policy"),
            "runnerAdmissionLeaseSha256": "",
            "bootstrapCredentialSha256": (
                f"sha256:{hashlib.sha256(bootstrap_credential).hexdigest()}"
            ),
            "sessionSha256": "",
            "endpointIdSha256": digest("endpoint"),
            "operatorIdSha256": digest("operator"),
            "attendedConsentPolicySha256": digest("consent-policy"),
        }
        if self.contract_version == "v3":
            subject.update(
                {
                    "repositoryId": 1211415632,
                    "headSha": self.TRANSACTION_REVIEWED_HEAD_SHA,
                    "endpointIdSha256": digest(self.TRANSACTION_DEVICE_ID),
                    "deviceHostnameSha256": digest(
                        self.TRANSACTION_DEVICE_HOSTNAME.lower()
                    ),
                    "pilotOwnerPolicySha256": digest("pilot-owner-policy"),
                    "maskPolicySha256": digest(self.TRANSACTION_MASK_RECT_BPS),
                    "runtimeImageDigest": digest("runtime-image"),
                    "pilotSeconds": 300,
                    "transactionScopeSha256": transaction_scope_sha256,
                }
            )
            grant = {
                "requestId": request_id,
                "deploymentSessionId": session_id,
                "transactionNonceSha256": digest("transaction-nonce"),
                "triggeringActorId": 424242,
                "triggeringActorLogin": "platform-automation[bot]",
                "registrationPrincipal": "spiffe://acik/platform/trusted-dispatcher",
                "workflowEvent": "workflow_dispatch",
                "notBefore": f"{self.day}T20:00:00Z",
                "expiresAt": f"{self.day}T21:30:00Z",
                "sequence": ["transaction"],
                "failureTransition": "transaction->compensating-rollback-in-run",
                "authorizationMode": "dual-gate",
                "maxRunAttempts": 1,
            }
        else:
            grant = {
                "requestId": request_id,
                "deploymentSessionId": session_id,
                "stageNonceSha256": {
                    "apply": digest("apply-nonce"),
                    "browser-evidence": digest("browser-nonce"),
                    "compensating-rollback": digest("rollback-nonce"),
                },
                "triggeringActorId": 424242,
                "triggeringActorLogin": "platform-automation[bot]",
                "registrationPrincipal": "spiffe://acik/platform/trusted-dispatcher",
                "workflowEvent": "workflow_dispatch",
                "notBefore": f"{self.day}T20:00:00Z",
                "expiresAt": f"{self.day}T21:30:00Z",
                "sequence": ["apply", "browser-evidence"],
                "failureTransition": "apply->compensating-rollback",
            }
        runner_lease = self.sign(
            "application/vnd.acik.cross-ai-runner-admission-lease.v1+json",
            {
                "schemaVersion": "acik.cross-ai-runner-admission-lease.v1",
                "leaseId": "35000000-0000-4000-8000-000000000001",
                "requestId": request_id,
                "repositoryId": subject["repositoryId"],
                "repository": subject["repository"],
                "environment": subject["environment"],
                "headSha": subject["headSha"],
                "intentRef": subject["intentRef"],
                "runnerPolicySha256": subject["runnerPolicySha256"],
                "inventoryGenerationSha256": sha256_digest(
                    {
                        "domain": "acik.cross-ai-runner-inventory-generation.v1",
                        "runners": [
                            {
                                "runnerId": 98765,
                                "runnerNameSha256": digest("testai-deploy-runner"),
                                "labels": [
                                    "self-hosted",
                                    "staging-sw",
                                    "testai-deploy",
                                ],
                            }
                        ],
                    }
                ),
                "issuedAt": f"{self.day}T20:00:00Z",
                "expiresAt": f"{self.day}T21:30:00Z",
                "eligibleRunners": [
                    {
                        "runnerId": 98765,
                        "runnerNameSha256": digest("testai-deploy-runner"),
                        "labels": ["self-hosted", "staging-sw", "testai-deploy"],
                        "attestationClass": "acik-testai-deploy-v1",
                    }
                ],
            },
            self.RUNNER_MANAGEMENT_KEY_ID,
        )
        subject["runnerAdmissionLeaseSha256"] = sha256_digest(runner_lease)
        subject["sessionSha256"] = sha256_digest(
            {
                "domain": self.session_domain,
                "requestId": request_id,
                "deploymentSessionId": session_id,
                "repositoryId": subject["repositoryId"],
                "environment": subject["environment"],
                "headSha": subject["headSha"],
                "intentRef": subject["intentRef"],
                "bootstrapCredentialSha256": subject["bootstrapCredentialSha256"],
                "endpointIdSha256": subject["endpointIdSha256"],
                "operatorIdSha256": subject["operatorIdSha256"],
                **(
                    {
                        "deviceHostnameSha256": subject["deviceHostnameSha256"],
                        "pilotOwnerPolicySha256": subject["pilotOwnerPolicySha256"],
                        "maskPolicySha256": subject["maskPolicySha256"],
                        "runtimeImageDigest": subject["runtimeImageDigest"],
                        "pilotSeconds": subject["pilotSeconds"],
                        "transactionScopeSha256": subject[
                            "transactionScopeSha256"
                        ],
                    }
                    if self.contract_version == "v3"
                    else {}
                ),
            }
        )
        concurrency_group_sha256 = sha256_digest(
            {
                "domain": "acik.cross-ai-workflow-concurrency-group.v1",
                "group": "faz22-view-only-protected-lanes",
            }
        )
        legacy_stages = [
            {
                "stage": "apply",
                "order": 1,
                "dependsOn": [],
                "workflowPath": ".github/workflows/apply-view-only-viewer-pilot-protected.yml",
                "workflowBlobSha256": digest("apply-workflow"),
                "dependencyLockSha256": digest("apply-lock"),
                "runtimeBundleSha256": None,
                "concurrencyGroupSha256": concurrency_group_sha256,
                "runsOnLabels": ["self-hosted", "staging-sw", "testai-deploy"],
                "maxUses": 1,
            },
            {
                "stage": "browser-evidence",
                "order": 2,
                "dependsOn": ["apply"],
                "workflowPath": ".github/workflows/faz22-6-view-only-viewer-browser-evidence-protected.yml",
                "workflowBlobSha256": digest("browser-workflow"),
                "dependencyLockSha256": digest("browser-lock"),
                "runtimeBundleSha256": digest("browser-runtime"),
                "concurrencyGroupSha256": concurrency_group_sha256,
                "priorStageOutcomeSchemaSha256": digest("outcome-schema"),
                "runsOnLabels": ["self-hosted", "staging-sw", "testai-deploy"],
                "runnerGroupId": 1234,
                "runnerAttestationClass": "acik-testai-deploy-v1",
                "maxUses": 1,
            },
            {
                "stage": "compensating-rollback",
                "order": 3,
                "dependsOnFailure": ["apply"],
                "workflowPath": ".github/workflows/rollback-view-only-viewer-pilot-protected.yml",
                "workflowBlobSha256": digest("rollback-workflow"),
                "dependencyLockSha256": digest("rollback-lock"),
                "runtimeBundleSha256": None,
                "concurrencyGroupSha256": concurrency_group_sha256,
                "runsOnLabels": ["self-hosted", "staging-sw", "testai-deploy"],
                "maxUses": 1,
            },
        ]
        stages = (
            [
                {
                    "stage": "transaction",
                    "order": 1,
                    "workflowPath": ".github/workflows/faz22-6-view-only-viewer-transaction.yml",
                    "workflowBlobSha256": next(
                        entry["sha256"]
                        for entry in authority_files
                        if entry["path"]
                        == ".github/workflows/faz22-6-view-only-viewer-transaction.yml"
                    ),
                    "dependencyLockSha256": self.TRANSACTION_DEPENDENCY_LOCK_SHA256,
                    "concurrencyGroupSha256": self.TRANSACTION_CONCURRENCY_SHA256,
                    "authorityFiles": authority_files,
                    "preflightRunsOnLabels": ["ubuntu-24.04"],
                    "runsOnLabels": [
                        "self-hosted",
                        "staging-sw",
                        "testai-deploy",
                    ],
                    "maxUses": 1,
                    "requiresSameRunPreflight": True,
                    "requiresOneProtectedEnvironmentGate": True,
                }
            ]
            if self.contract_version == "v3"
            else legacy_stages
        )
        for stage in stages:
            stage.update((stage_overrides or {}).get(stage["stage"], {}))
        subject_digest = sha256_digest(
            {"subject": subject, "workflowStages": stages, "grant": grant}
        )
        empty_closure = digest("closure-pending")
        chain_a = "40000000-0000-4000-8000-000000000001"
        primary_key = (
            self.ANTHROPIC_KEY_ID
            if self.contract_version == "v1"
            else self.OPENAI_KEY_ID
        )
        a1 = self._review(
            review_id="50000000-0000-4000-8000-000000000001",
            chain_id=chain_a,
            key_id=primary_key,
            round_number=1,
            verdict="REVISE",
            previous=None,
            closure_root=empty_closure,
            finding_ids=["FINDING_A"],
            issued_at=f"{self.day}T20:05:00Z",
            subject_digest=subject_digest,
        )
        a1_digest = sha256_digest(a1)
        a2 = self._review(
            review_id="50000000-0000-4000-8000-000000000002",
            chain_id=chain_a,
            key_id=primary_key,
            round_number=2,
            verdict="PARTIAL",
            previous=a1_digest,
            closure_root=empty_closure,
            resolved=["FINDING_A"],
            acknowledged=["FINDING_A"],
            issued_at=f"{self.day}T20:10:00Z",
            subject_digest=subject_digest,
        )
        a2_digest = sha256_digest(a2)
        closure_entries = [
            {
                "findingId": "FINDING_A",
                "raisedByReviewSha256": a1_digest,
                "fixSha256": digest("fix-a"),
                "acknowledgedByReviewSha256": a2_digest,
            }
        ]
        closure_root = sha256_digest(
            {
                "domain": self.closure_domain,
                "subjectSha256": subject_digest,
                "entries": closure_entries,
            }
        )
        a3 = self._review(
            review_id="50000000-0000-4000-8000-000000000003",
            chain_id=chain_a,
            key_id=primary_key,
            round_number=3,
            verdict="AGREE",
            previous=a2_digest,
            closure_root=closure_root,
            issued_at=f"{self.day}T20:15:00Z",
            subject_digest=subject_digest,
        )
        a3_digest = sha256_digest(a3)
        review_envelopes = [a1, a2, a3]
        provider_families = ["openai"]
        final_review_digests = [a3_digest]
        if self.contract_version == "v1":
            b1 = self._review(
                review_id="60000000-0000-4000-8000-000000000001",
                chain_id="40000000-0000-4000-8000-000000000002",
                key_id=self.MINIMAX_KEY_ID,
                round_number=1,
                verdict="AGREE",
                previous=None,
                closure_root=closure_root,
                issued_at=f"{self.day}T20:16:00Z",
                subject_digest=subject_digest,
            )
            review_envelopes.append(b1)
            c1 = self._review(
                review_id="60000000-0000-4000-8000-000000000002",
                chain_id="40000000-0000-4000-8000-000000000003",
                key_id=self.OPENAI_KEY_ID,
                round_number=1,
                verdict="AGREE",
                previous=None,
                closure_root=closure_root,
                issued_at=f"{self.day}T20:17:00Z",
                subject_digest=subject_digest,
            )
            provider_families = ["anthropic", "minimax", "openai"]
            final_review_digests = [a3_digest, sha256_digest(b1), sha256_digest(c1)]
            review_envelopes.append(c1)
        bundle = {
            "schemaVersion": f"acik.cross-ai-deployment-bundle.{self.contract_version}",
            "bundleId": "70000000-0000-4000-8000-000000000001",
            "subject": subject,
            "workflowStages": stages,
            "runnerAdmissionLeaseEnvelope": runner_lease,
            "reviewEnvelopes": review_envelopes,
            "closure": {
                "entries": closure_entries,
                "closureRootSha256": closure_root,
            },
            "consensus": {
                "providerFamilies": provider_families,
                "finalAgreeReviewSha256": final_review_digests,
                "closureRootSha256": closure_root,
                "openMustFixFindingCount": 0,
            },
            "grant": grant,
        }
        return SignedFixture(
            trust_root=self.trust_root(),
            revocations_envelope=self.revocations(),
            bundle_envelope=self.sign(
                self.bundle_payload_type,
                bundle,
                self.COORDINATOR_KEY_ID,
            ),
            keys=copy.copy(self.keys),
            now=self.now,
        )
