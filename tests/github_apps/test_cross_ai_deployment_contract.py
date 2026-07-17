from __future__ import annotations

import base64
import copy
import unittest

from scripts.github_apps.cross_ai_deployment_policy.canonical import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    BUNDLE_PAYLOAD_TYPE,
    EvidenceVerifier,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class EvidenceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FixtureFactory()
        self.fixture = self.factory.build()

    def verifier(self) -> EvidenceVerifier:
        return EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        )

    def mutate_bundle(self, mutator) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        mutator(bundle)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)

    def test_accepts_provider_distinct_closed_bundle(self) -> None:
        result = self.verifier().verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(result.provider_families, ("anthropic", "xai"))
        self.assertEqual(result.request_id, "30000000-0000-4000-8000-000000000001")
        self.assertEqual(len(result.final_review_digests), 2)

    def test_rejects_trust_root_that_differs_from_deployment_pin(self) -> None:
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_DIGEST_MISMATCH"):
            EvidenceVerifier(
                trust_root=self.fixture.trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
                expected_trust_root_sha256="sha256:" + ("0" * 64),
            )
        EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
        )

    def test_rejects_noncanonical_payload_even_with_valid_signature_shape(self) -> None:
        envelope = copy.deepcopy(self.fixture.bundle_envelope)
        noncanonical = b'{ "schemaVersion": "acik.cross-ai-deployment-bundle.v1" }'
        envelope["payload"] = base64.b64encode(noncanonical).decode()
        with self.assertRaisesRegex(PolicyError, "DSSE_SIGNATURE_INVALID|DSSE_PAYLOAD_NON_CANONICAL"):
            self.verifier().verify_bundle(envelope)

    def test_rejects_provider_family_self_assertion(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        review["providerFamily"] = "anthropic"
        bundle["reviewEnvelopes"][-1] = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.XAI_KEY_ID,
        )
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ATTRIBUTION_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_model_identity_class_outside_key_policy(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][0])
        review["modelIdentityClass"] = "trusted-launch-attested"
        bundle["reviewEnvelopes"][0] = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.ANTHROPIC_KEY_ID,
        )
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ATTRIBUTION_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_session_rebinding(self) -> None:
        self.mutate_bundle(
            lambda bundle: bundle["subject"].__setitem__(
                "endpointIdSha256", "sha256:" + ("0" * 64)
            )
        )
        with self.assertRaisesRegex(PolicyError, "SESSION_BINDING_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_intent_ref_rebinding(self) -> None:
        self.mutate_bundle(
            lambda bundle: bundle["subject"].__setitem__(
                "intentRef",
                "refs/tags/cross-ai-intent/99999999-0000-4000-8000-000000000001",
            )
        )
        with self.assertRaisesRegex(PolicyError, "INTENT_REF_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_open_or_missing_closure(self) -> None:
        self.mutate_bundle(lambda bundle: bundle["closure"].__setitem__("entries", []))
        with self.assertRaisesRegex(PolicyError, "CLOSURE_INCOMPLETE|CLOSURE_ROOT_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_revoked_bundle(self) -> None:
        self.fixture.revocations_envelope = self.factory.revocations(
            [
                {
                    "type": "bundle",
                    "id": "70000000-0000-4000-8000-000000000001",
                    "effectiveAt": "2026-07-16T20:20:00Z",
                    "reasonCode": "COMPROMISE",
                }
            ]
        )
        with self.assertRaisesRegex(PolicyError, "EVIDENCE_REVOKED"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_stale_revocation_set(self) -> None:
        payload = self.factory.decode_payload(self.fixture.revocations_envelope)
        payload["nextUpdate"] = "2026-07-16T20:00:00Z"
        self.fixture.revocations_envelope = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-revocations.v1+json",
            payload,
            self.factory.REVOCATION_KEY_ID,
        )
        with self.assertRaisesRegex(PolicyError, "REVOCATIONS_STALE"):
            self.verifier()

    def test_rejects_legacy_unsigned_owner_receipt(self) -> None:
        legacy = {
            "aiAdvisoryProvenanceClass": "owner-attested-provider-session",
            "aiProviderCryptographicAttestation": False,
            "aiConsensusVerdict": "AGREE",
        }
        with self.assertRaisesRegex(PolicyError, "DSSE_SCHEMA_INVALID"):
            self.verifier().verify_bundle(legacy)

    def test_rejects_bundle_signed_by_provider_key(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.fixture.bundle_envelope = self.factory.sign(
            BUNDLE_PAYLOAD_TYPE,
            bundle,
            self.factory.ANTHROPIC_KEY_ID,
        )
        with self.assertRaisesRegex(PolicyError, "DSSE_KEY_NOT_ALLOWED"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_grant_over_two_hours(self) -> None:
        self.mutate_bundle(
            lambda bundle: bundle["grant"].__setitem__(
                "expiresAt", "2026-07-16T23:00:00Z"
            )
        )
        with self.assertRaisesRegex(
            PolicyError,
            "GRANT_TTL_EXCEEDED|REVIEW_SUBJECT_MISMATCH",
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_payload_is_canonical_in_fixture(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.assertEqual(
            base64.b64decode(self.fixture.bundle_envelope["payload"], validate=True),
            canonical_bytes(bundle),
        )


if __name__ == "__main__":
    unittest.main()
