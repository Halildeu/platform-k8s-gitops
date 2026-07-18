from __future__ import annotations

import unittest

from scripts.github_apps.cross_ai_deployment_policy.coordinator import (
    EvidenceCoordinator,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory
from tests.github_apps.test_cross_ai_deployment_provider import StaticSigner


class EvidenceCoordinatorTest(unittest.TestCase):
    def test_coordinator_can_only_emit_bundle_that_passes_leaf_verification(
        self,
    ) -> None:
        factory = FixtureFactory()
        fixture = factory.build()
        original = factory.decode_payload(fixture.bundle_envelope)
        coordinator = EvidenceCoordinator(
            signer=StaticSigner(factory, factory.COORDINATOR_KEY_ID),
            trust_root=fixture.trust_root,
            revocations_envelope=fixture.revocations_envelope,
            expected_policy_sha256=original["subject"]["policySha256"],
        )
        coordinated = coordinator.coordinate(
            bundle_id="70000000-0000-4000-8000-000000000002",
            subject=original["subject"],
            workflow_stages=original["workflowStages"],
            runner_admission_lease_envelope=original["runnerAdmissionLeaseEnvelope"],
            grant=original["grant"],
            review_envelopes=original["reviewEnvelopes"],
            closure_entries=original["closure"]["entries"],
            final_agree_review_sha256=original["consensus"]["finalAgreeReviewSha256"],
            provider_families=original["consensus"]["providerFamilies"],
            now=fixture.now,
        )
        self.assertEqual(coordinated.verified.provider_families, ("anthropic", "xai"))
        self.assertEqual(
            coordinated.verified.bundle_id,
            "70000000-0000-4000-8000-000000000002",
        )


if __name__ == "__main__":
    unittest.main()
