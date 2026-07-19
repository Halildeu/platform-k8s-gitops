from __future__ import annotations

import unittest

from scripts.github_apps.cross_ai_deployment_policy.coordinator import (
    EvidenceCoordinator,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory
from tests.github_apps.test_cross_ai_deployment_provider import StaticSigner


class EvidenceCoordinatorTest(unittest.TestCase):
    def test_v1_coordinator_is_read_only(self) -> None:
        factory = FixtureFactory()
        fixture = factory.build()
        original = factory.decode_payload(fixture.bundle_envelope)
        with self.assertRaisesRegex(PolicyError, "LEGACY_CONTRACT_READ_ONLY"):
            EvidenceCoordinator(
                signer=StaticSigner(factory, factory.COORDINATOR_KEY_ID),
                trust_root=fixture.trust_root,
                revocations_envelope=fixture.revocations_envelope,
                expected_policy_sha256=original["subject"]["policySha256"],
            )

    def test_v2_coordinator_emits_codex_only_bundle(self) -> None:
        factory = FixtureFactory("v2")
        fixture = factory.build()
        original = factory.decode_payload(fixture.bundle_envelope)
        coordinated = EvidenceCoordinator(
            signer=StaticSigner(factory, factory.COORDINATOR_KEY_ID),
            trust_root=fixture.trust_root,
            revocations_envelope=fixture.revocations_envelope,
            expected_policy_sha256=original["subject"]["policySha256"],
        ).coordinate(
            bundle_id="70000000-0000-4000-8000-000000000003",
            subject=original["subject"],
            workflow_stages=original["workflowStages"],
            runner_admission_lease_envelope=original[
                "runnerAdmissionLeaseEnvelope"
            ],
            grant=original["grant"],
            review_envelopes=original["reviewEnvelopes"],
            review_runtime_attestation_envelopes=original[
                "reviewRuntimeAttestationEnvelopes"
            ],
            closure_entries=original["closure"]["entries"],
            final_agree_review_sha256=original["consensus"][
                "finalAgreeReviewSha256"
            ],
            provider_families=original["consensus"]["providerFamilies"],
            now=fixture.now,
        )
        self.assertEqual(
            coordinated.verified.provider_families,
            ("openai",),
        )


if __name__ == "__main__":
    unittest.main()
