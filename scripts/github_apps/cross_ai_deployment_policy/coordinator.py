"""Evidence coordinator that can compose but cannot forge provider leaves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical import sha256_digest
from .contract import (
    BUNDLE_PAYLOAD_TYPE,
    BUNDLE_PAYLOAD_TYPE_V2,
    CLOSURE_DOMAIN,
    CLOSURE_DOMAIN_V2,
    EvidenceVerifier,
    VerifiedBundle,
)
from .errors import reject
from .provider import EnvelopeSigner


@dataclass(frozen=True)
class CoordinatedBundle:
    envelope: dict[str, Any]
    verified: VerifiedBundle


class EvidenceCoordinator:
    def __init__(
        self,
        *,
        signer: EnvelopeSigner,
        trust_root: dict[str, Any],
        revocations_envelope: dict[str, Any],
        expected_policy_sha256: str,
    ) -> None:
        self.signer = signer
        self.trust_root = trust_root
        self.revocations_envelope = revocations_envelope
        self.expected_policy_sha256 = expected_policy_sha256
        schema_version = trust_root.get("schemaVersion")
        if schema_version == "acik.cross-ai-deployment-trust-root.v1":
            self.bundle_schema_version = "acik.cross-ai-deployment-bundle.v1"
            self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE
            self.closure_domain = CLOSURE_DOMAIN
        elif schema_version == "acik.cross-ai-deployment-trust-root.v2":
            self.bundle_schema_version = "acik.cross-ai-deployment-bundle.v2"
            self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE_V2
            self.closure_domain = CLOSURE_DOMAIN_V2
        else:
            reject(
                "TRUST_ROOT_SCHEMA_INVALID",
                "trust root contract version is unsupported",
            )

    def coordinate(
        self,
        *,
        bundle_id: str,
        subject: dict[str, Any],
        workflow_stages: list[dict[str, Any]],
        runner_admission_lease_envelope: dict[str, Any],
        grant: dict[str, Any],
        review_envelopes: list[dict[str, Any]],
        closure_entries: list[dict[str, Any]],
        final_agree_review_sha256: list[str],
        provider_families: list[str],
        now: datetime,
    ) -> CoordinatedBundle:
        subject_digest = sha256_digest(
            {
                "subject": subject,
                "workflowStages": workflow_stages,
                "grant": grant,
            }
        )
        closure_root = sha256_digest(
            {
                "domain": self.closure_domain,
                "subjectSha256": subject_digest,
                "entries": sorted(
                    closure_entries,
                    key=lambda item: item["findingId"],
                ),
            }
        )
        payload = {
            "schemaVersion": self.bundle_schema_version,
            "bundleId": bundle_id,
            "subject": subject,
            "workflowStages": workflow_stages,
            "runnerAdmissionLeaseEnvelope": runner_admission_lease_envelope,
            "reviewEnvelopes": review_envelopes,
            "closure": {
                "entries": closure_entries,
                "closureRootSha256": closure_root,
            },
            "consensus": {
                "providerFamilies": provider_families,
                "finalAgreeReviewSha256": final_agree_review_sha256,
                "closureRootSha256": closure_root,
                "openMustFixFindingCount": 0,
            },
            "grant": grant,
        }
        envelope = self.signer.sign_json_envelope(
            payload_type=self.bundle_payload_type,
            payload=payload,
        )
        verified = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_envelope,
            now=now,
            expected_policy_sha256=self.expected_policy_sha256,
        ).verify_bundle(envelope)
        return CoordinatedBundle(envelope=envelope, verified=verified)


__all__ = ["CoordinatedBundle", "EvidenceCoordinator"]
