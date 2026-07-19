"""Evidence coordinator that can compose but cannot forge provider leaves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical import sha256_digest
from .contract import (
    BUNDLE_PAYLOAD_TYPE_V2,
    BUNDLE_PAYLOAD_TYPE_V3,
    CLOSURE_DOMAIN_V2,
    EvidenceVerifier,
    VerifiedBundle,
)
from .errors import reject
from .provider import EnvelopeSigner
from .timeutil import parse_utc


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
        expected_trust_root_sha256: str | None = None,
        bundle_contract_version: str = "v2",
    ) -> None:
        self.signer = signer
        self.trust_root = trust_root
        self.revocations_envelope = revocations_envelope
        self.expected_policy_sha256 = expected_policy_sha256
        self.expected_trust_root_sha256 = expected_trust_root_sha256
        schema_version = trust_root.get("schemaVersion")
        if schema_version == "acik.cross-ai-deployment-trust-root.v1":
            reject(
                "LEGACY_CONTRACT_READ_ONLY",
                "v1 evidence may be verified for history but cannot be coordinated",
            )
        if schema_version == "acik.cross-ai-deployment-trust-root.v2":
            if bundle_contract_version == "v2":
                self.bundle_schema_version = "acik.cross-ai-deployment-bundle.v2"
                self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE_V2
                self.closure_domain = CLOSURE_DOMAIN_V2
            elif bundle_contract_version == "v3":
                self.bundle_schema_version = "acik.cross-ai-deployment-bundle.v3"
                self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE_V3
                self.closure_domain = "acik.cross-ai-deployment-closure.v3"
            else:
                reject(
                    "BUNDLE_CONTRACT_INVALID",
                    "coordinator bundle contract version is unsupported",
                )
            self.bundle_contract_version = bundle_contract_version
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
        grant_not_before = grant.get("notBefore") if isinstance(grant, dict) else None
        if not isinstance(grant_not_before, str) or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("findingId"), str)
            for entry in closure_entries
        ):
            reject(
                "EVIDENCE_COORDINATION_INPUT_INVALID",
                "grant or closure entries are structurally invalid",
            )
        verifier = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_envelope,
            now=now,
            expected_policy_sha256=self.expected_policy_sha256,
            expected_trust_root_sha256=self.expected_trust_root_sha256,
            expected_bundle_contract=self.bundle_contract_version,
        )
        verifier.require_active_signing_key(
            key_id=self.signer.key_id,
            role="coordinator",
            issued_at=parse_utc(grant_not_before, "grant.notBefore"),
        )
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
        verifier.validate_bundle_payload_for_signing(
            payload,
            coordinator_key_id=self.signer.key_id,
        )
        envelope = self.signer.sign_json_envelope(
            payload_type=self.bundle_payload_type,
            payload=payload,
        )
        verified = verifier.verify_bundle(envelope)
        return CoordinatedBundle(envelope=envelope, verified=verified)


__all__ = ["CoordinatedBundle", "EvidenceCoordinator"]
