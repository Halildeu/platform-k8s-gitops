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
    CLOSURE_DOMAIN,
    CLOSURE_DOMAIN_V2,
    REVIEW_PAYLOAD_TYPE,
    REVIEW_PAYLOAD_TYPE_V2,
    REVOCATIONS_PAYLOAD_TYPE,
    SESSION_DOMAIN,
    SESSION_DOMAIN_V2,
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

    def __init__(self, contract_version: str = "v1") -> None:
        if contract_version not in {"v1", "v2"}:
            raise ValueError("unsupported fixture contract version")
        self.contract_version = contract_version
        self.day = "2026-07-16" if contract_version == "v1" else "2026-07-18"
        self.bundle_payload_type = (
            BUNDLE_PAYLOAD_TYPE if contract_version == "v1" else BUNDLE_PAYLOAD_TYPE_V2
        )
        self.review_payload_type = (
            REVIEW_PAYLOAD_TYPE if contract_version == "v1" else REVIEW_PAYLOAD_TYPE_V2
        )
        self.session_domain = (
            SESSION_DOMAIN if contract_version == "v1" else SESSION_DOMAIN_V2
        )
        self.closure_domain = (
            CLOSURE_DOMAIN if contract_version == "v1" else CLOSURE_DOMAIN_V2
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
        provider_entries = [
            entry(
                self.ANTHROPIC_KEY_ID,
                "provider-review",
                "anthropic",
                ["direct-anthropic-cli"],
                True,
                ["claude-opus-4-8"],
                ["provider-reported"],
            )
        ]
        if self.contract_version == "v1":
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
            providers = ["anthropic", "openai"]
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
        if self.contract_version == "v2":
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
            "schemaVersion": f"acik.cross-ai-deployment-review.{self.contract_version}",
            "reviewId": review_id,
            "reviewChainId": chain_id,
            "providerFamily": family,
            "channel": channel,
            "directProviderCli": direct,
            "modelId": model,
            "modelIdentityClass": (
                "trusted-launch-attested"
                if key_id == self.OPENAI_KEY_ID and self.contract_version == "v2"
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
        return self.sign(self.review_payload_type, payload, key_id)

    def build(
        self,
        *,
        stage_overrides: dict[str, dict[str, Any]] | None = None,
        policy_digest: str | None = None,
        bootstrap_credential: bytes = b"B" * 64,
    ) -> SignedFixture:
        request_id = "30000000-0000-4000-8000-000000000001"
        session_id = "30000000-0000-4000-8000-000000000002"
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
                                    "aiserver",
                                    "self-hosted",
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
                        "labels": ["self-hosted", "aiserver", "testai-deploy"],
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
            }
        )
        concurrency_group_sha256 = sha256_digest(
            {
                "domain": "acik.cross-ai-workflow-concurrency-group.v1",
                "group": "faz22-view-only-protected-lanes",
            }
        )
        stages = [
            {
                "stage": "apply",
                "order": 1,
                "dependsOn": [],
                "workflowPath": ".github/workflows/apply-view-only-viewer-pilot-protected.yml",
                "workflowBlobSha256": digest("apply-workflow"),
                "dependencyLockSha256": digest("apply-lock"),
                "runtimeBundleSha256": None,
                "concurrencyGroupSha256": concurrency_group_sha256,
                "runsOnLabels": ["self-hosted", "aiserver", "testai-deploy"],
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
                "runsOnLabels": ["self-hosted", "aiserver", "testai-deploy"],
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
                "runsOnLabels": ["self-hosted", "aiserver", "testai-deploy"],
                "maxUses": 1,
            },
        ]
        for stage in stages:
            stage.update((stage_overrides or {}).get(stage["stage"], {}))
        subject_digest = sha256_digest(
            {"subject": subject, "workflowStages": stages, "grant": grant}
        )
        empty_closure = digest("closure-pending")
        chain_a = "40000000-0000-4000-8000-000000000001"
        a1 = self._review(
            review_id="50000000-0000-4000-8000-000000000001",
            chain_id=chain_a,
            key_id=self.ANTHROPIC_KEY_ID,
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
            key_id=self.ANTHROPIC_KEY_ID,
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
            key_id=self.ANTHROPIC_KEY_ID,
            round_number=3,
            verdict="AGREE",
            previous=a2_digest,
            closure_root=closure_root,
            issued_at=f"{self.day}T20:15:00Z",
            subject_digest=subject_digest,
        )
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
        a3_digest = sha256_digest(a3)
        c1_digest = sha256_digest(c1)
        review_envelopes = [a1, a2, a3]
        provider_families = ["anthropic", "openai"]
        final_review_digests = [a3_digest, c1_digest]
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
            provider_families = ["anthropic", "minimax", "openai"]
            final_review_digests = [a3_digest, sha256_digest(b1), c1_digest]
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
