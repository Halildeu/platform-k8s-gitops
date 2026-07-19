from __future__ import annotations

import copy
import unittest

from scripts.github_apps.cross_ai_deployment_policy.coordinator import (
    EvidenceCoordinator,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
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

    def test_trust_root_pin_fails_before_consuming_coordinator_signature(self) -> None:
        factory = FixtureFactory("v3")
        fixture = factory.build()
        original = factory.decode_payload(fixture.bundle_envelope)

        class CountingSigner(StaticSigner):
            calls = 0

            def sign_json_envelope(self, *, payload_type, payload):
                self.calls += 1
                return super().sign_json_envelope(
                    payload_type=payload_type,
                    payload=payload,
                )

        signer = CountingSigner(factory, factory.COORDINATOR_KEY_ID)
        coordinator = EvidenceCoordinator(
            signer=signer,
            trust_root=fixture.trust_root,
            revocations_envelope=fixture.revocations_envelope,
            expected_policy_sha256=original["subject"]["policySha256"],
            expected_trust_root_sha256="sha256:" + ("0" * 64),
            bundle_contract_version="v3",
        )
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_DIGEST_MISMATCH"):
            coordinator.coordinate(
                bundle_id="70000000-0000-4000-8000-000000000004",
                subject=original["subject"],
                workflow_stages=original["workflowStages"],
                runner_admission_lease_envelope=original[
                    "runnerAdmissionLeaseEnvelope"
                ],
                grant=original["grant"],
                review_envelopes=original["reviewEnvelopes"],
                closure_entries=original["closure"]["entries"],
                final_agree_review_sha256=original["consensus"][
                    "finalAgreeReviewSha256"
                ],
                provider_families=original["consensus"]["providerFamilies"],
                now=fixture.now,
            )
        self.assertEqual(signer.calls, 0)
        self.assertEqual(
            sha256_digest(fixture.trust_root),
            sha256_digest(factory.trust_root()),
        )

    def test_bad_provider_leaf_fails_before_coordinator_signature(self) -> None:
        factory = FixtureFactory("v3")
        fixture = factory.build()
        original = factory.decode_payload(fixture.bundle_envelope)

        class CountingSigner(StaticSigner):
            calls = 0

            def sign_json_envelope(self, *, payload_type, payload):
                self.calls += 1
                return super().sign_json_envelope(
                    payload_type=payload_type,
                    payload=payload,
                )

        signer = CountingSigner(factory, factory.COORDINATOR_KEY_ID)
        bad_reviews = copy.deepcopy(original["reviewEnvelopes"])
        bad_reviews[0]["signatures"][0]["sig"] = "A" * 88
        coordinator = EvidenceCoordinator(
            signer=signer,
            trust_root=fixture.trust_root,
            revocations_envelope=fixture.revocations_envelope,
            expected_policy_sha256=original["subject"]["policySha256"],
            expected_trust_root_sha256=sha256_digest(fixture.trust_root),
            bundle_contract_version="v3",
        )
        with self.assertRaisesRegex(PolicyError, "DSSE_SIGNATURE_INVALID"):
            coordinator.coordinate(
                bundle_id="70000000-0000-4000-8000-000000000005",
                subject=original["subject"],
                workflow_stages=original["workflowStages"],
                runner_admission_lease_envelope=original[
                    "runnerAdmissionLeaseEnvelope"
                ],
                grant=original["grant"],
                review_envelopes=bad_reviews,
                closure_entries=original["closure"]["entries"],
                final_agree_review_sha256=original["consensus"][
                    "finalAgreeReviewSha256"
                ],
                provider_families=original["consensus"]["providerFamilies"],
                now=fixture.now,
            )
        self.assertEqual(signer.calls, 0)


if __name__ == "__main__":
    unittest.main()
