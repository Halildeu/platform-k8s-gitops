from __future__ import annotations

import base64
import copy
import unittest
from datetime import datetime, timezone

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
        self.assertEqual(
            result.provider_families,
            ("anthropic", "minimax", "openai"),
        )
        self.assertEqual(result.request_id, "30000000-0000-4000-8000-000000000001")
        self.assertEqual(len(result.final_review_digests), 3)

    def test_rejects_new_minimax_review_after_forward_policy_cutoff(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        minimax_envelope = bundle["reviewEnvelopes"][3]
        old_digest = sha256_digest(minimax_envelope)
        review = self.factory.decode_payload(minimax_envelope)
        review["issuedAt"] = "2026-07-18T00:00:00Z"
        review["expiresAt"] = "2026-07-18T00:30:00Z"
        replacement = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.MINIMAX_KEY_ID,
        )
        bundle["reviewEnvelopes"][3] = replacement
        bundle["consensus"]["finalAgreeReviewSha256"] = [
            sha256_digest(replacement) if value == old_digest else value
            for value in bundle["consensus"]["finalAgreeReviewSha256"]
        ]
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "MINIMAX_REVIEW_DEPRECATED"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_minimax_trust_root_valid_after_forward_policy_cutoff(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["expiresAt"] = "2026-07-18T00:00:01Z"
        with self.assertRaisesRegex(PolicyError, "MINIMAX_TRUST_ROOT_DEPRECATED"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_active_time_rejects_backdated_minimax_bundle_after_cutoff(self) -> None:
        with self.assertRaisesRegex(PolicyError, "MINIMAX_PROVIDER_DEPRECATED"):
            EvidenceVerifier(
                trust_root=self.fixture.trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=datetime(2026, 7, 18, tzinfo=timezone.utc),
            )

    def test_current_time_can_forensically_replay_archived_v1_bundle(self) -> None:
        verifier = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=datetime(2026, 7, 19, tzinfo=timezone.utc),
            verification_mode="forensic",
            forensic_reference_time=self.fixture.now,
        )
        result = verifier.verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(
            result.provider_families,
            ("anthropic", "minimax", "openai"),
        )

    def test_forensic_v1_replay_requires_historical_reference_time(self) -> None:
        with self.assertRaisesRegex(PolicyError, "FORENSIC_REFERENCE_REQUIRED"):
            EvidenceVerifier(
                trust_root=self.fixture.trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=datetime(2026, 7, 19, tzinfo=timezone.utc),
                verification_mode="forensic",
            )

    def test_rejects_browser_stage_without_signed_runtime_bundle(self) -> None:
        self.fixture = self.factory.build(
            stage_overrides={"browser-evidence": {"runtimeBundleSha256": None}}
        )
        with self.assertRaisesRegex(PolicyError, "BUNDLE_SCHEMA_INVALID"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_runtime_bundle_on_non_browser_stage(self) -> None:
        self.fixture = self.factory.build(
            stage_overrides={"apply": {"runtimeBundleSha256": "sha256:" + ("1" * 64)}}
        )
        with self.assertRaisesRegex(PolicyError, "BUNDLE_SCHEMA_INVALID"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

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
        with self.assertRaisesRegex(
            PolicyError, "DSSE_SIGNATURE_INVALID|DSSE_PAYLOAD_NON_CANONICAL"
        ):
            self.verifier().verify_bundle(envelope)

    def test_rejects_provider_family_self_assertion(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        review["providerFamily"] = "anthropic"
        envelope = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.OPENAI_KEY_ID,
        )
        bundle["reviewEnvelopes"][-1] = envelope
        bundle["consensus"]["finalAgreeReviewSha256"][-1] = sha256_digest(envelope)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ATTRIBUTION_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_unpinned_model_even_with_valid_provider_signature(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        review["modelId"] = "gpt-5.6"
        bundle["reviewEnvelopes"][-1] = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.OPENAI_KEY_ID,
        )
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ATTRIBUTION_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_trust_key_with_more_than_one_allowed_model(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["allowedModelIds"].append("gpt-5.6-sol-alias")
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_SCHEMA_INVALID"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_provider_identity_class_outside_canonical_route(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][0]["allowedModelIdentityClasses"] = [
            "trusted-launch-attested"
        ]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_KEY_ATTRIBUTION_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_archived_v1_openai_route_requires_provider_reported_identity(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        openai = next(
            entry
            for entry in trust_root["keys"]
            if entry["providerFamily"] == "openai"
        )
        openai["allowedModelIdentityClasses"] = ["trusted-launch-attested"]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_ROUTE_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_provider_issuer_mismatch(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        review["issuer"] = "cross-ai-issuer-anthropic"
        bundle["reviewEnvelopes"][-1] = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.OPENAI_KEY_ID,
        )
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ATTRIBUTION_MISMATCH"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_consensus_without_exact_provider_set(self) -> None:
        self.mutate_bundle(
            lambda bundle: bundle["consensus"].__setitem__(
                "providerFamilies", ["anthropic", "minimax", "xai"]
            )
        )
        with self.assertRaisesRegex(
            PolicyError, "BUNDLE_SCHEMA_INVALID|CONSENSUS_PROVIDER_MISMATCH"
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_wrapper_channel_marked_as_direct_provider(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][1]["allowedChannels"] = ["wrapper-minimax"]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_ROUTE_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_noncanonical_exact_model_in_trust_root(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["allowedModelIds"] = ["gpt-5.6"]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_ROUTE_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_same_provider_wrappers_as_three_provider_trust(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["providerFamily"] = "anthropic"
        trust_root["keys"][2]["allowedChannels"] = ["direct-anthropic-cli-alt"]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_SET_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_schema_rejects_unknown_provider_family_before_verification(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["providerFamily"] = "xai"
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_SCHEMA_INVALID"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_public_key_reuse_across_provider_families(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["publicKeyBase64"] = trust_root["keys"][1][
            "publicKeyBase64"
        ]
        with self.assertRaisesRegex(PolicyError, "TRUST_KEY_REUSED"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_public_key_reuse_across_provider_and_coordinator(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][3]["publicKeyBase64"] = trust_root["keys"][0][
            "publicKeyBase64"
        ]
        with self.assertRaisesRegex(PolicyError, "TRUST_KEY_REUSED"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_rejects_non_agree_review_selected_as_final(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        review["verdict"] = "REVISE"
        envelope = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.OPENAI_KEY_ID,
        )
        bundle["reviewEnvelopes"][-1] = envelope
        bundle["consensus"]["finalAgreeReviewSha256"][-1] = sha256_digest(envelope)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(
            PolicyError, "REVIEW_SCHEMA_INVALID|CONSENSUS_VERDICT_INVALID"
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_hidden_empty_dissent_before_final_agree(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        partial = bundle["reviewEnvelopes"][1]
        subject_digest = self.factory.decode_payload(partial)["subjectSha256"]
        hidden_red = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000004",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=3,
            verdict="RED",
            previous=sha256_digest(partial),
            closure_root=bundle["closure"]["closureRootSha256"],
            finding_ids=[],
            issued_at="2026-07-16T20:14:00Z",
            subject_digest=subject_digest,
        )
        final = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000005",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=4,
            verdict="AGREE",
            previous=sha256_digest(hidden_red),
            closure_root=bundle["closure"]["closureRootSha256"],
            issued_at="2026-07-16T20:15:00Z",
            subject_digest=subject_digest,
        )
        bundle["reviewEnvelopes"][2:3] = [hidden_red, final]
        bundle["consensus"]["finalAgreeReviewSha256"][0] = sha256_digest(final)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(
            PolicyError, "REVIEW_SCHEMA_INVALID|REVIEW_DISSENT_FINDINGS_REQUIRED"
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_partial_without_finding_transition(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        review = self.factory.decode_payload(bundle["reviewEnvelopes"][1])
        review["findingIds"] = []
        review["resolvedFindingIds"] = []
        review["acknowledgedFindingIds"] = []
        bundle["reviewEnvelopes"][1] = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-review.v1+json",
            review,
            self.factory.ANTHROPIC_KEY_ID,
        )
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(
            PolicyError, "REVIEW_SCHEMA_INVALID|REVIEW_PARTIAL_TRANSITION_REQUIRED"
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_unselected_parallel_chain_from_required_provider(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        selected = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        dissent = self.factory._review(
            review_id="60000000-0000-4000-8000-000000000003",
            chain_id="40000000-0000-4000-8000-000000000004",
            key_id=self.factory.OPENAI_KEY_ID,
            round_number=1,
            verdict="AGREE",
            previous=None,
            closure_root=bundle["closure"]["closureRootSha256"],
            issued_at="2026-07-16T20:18:00Z",
            subject_digest=selected["subjectSha256"],
        )
        bundle["reviewEnvelopes"].append(dissent)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "CONSENSUS_UNCOUNTED_CHAIN"):
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

    def test_rejects_required_provider_that_is_not_a_direct_route(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"][2]["directProviderCli"] = False
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_ROUTE_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

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
        with self.assertRaisesRegex(
            PolicyError, "CLOSURE_INCOMPLETE|CLOSURE_ROOT_MISMATCH"
        ):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def _append_reopened_anthropic_finding(self, *, same_round_ack: bool) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        previous = sha256_digest(bundle["reviewEnvelopes"][2])
        subject_digest = self.factory.decode_payload(bundle["reviewEnvelopes"][2])[
            "subjectSha256"
        ]
        closure_root = bundle["closure"]["closureRootSha256"]
        reopened = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000004",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=4,
            verdict="PARTIAL" if same_round_ack else "REVISE",
            previous=previous,
            closure_root=closure_root,
            finding_ids=["FINDING_A"],
            resolved=["FINDING_A"] if same_round_ack else None,
            acknowledged=["FINDING_A"] if same_round_ack else None,
            issued_at="2026-07-16T20:18:00Z",
            subject_digest=subject_digest,
        )
        final = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000005",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=5,
            verdict="AGREE",
            previous=sha256_digest(reopened),
            closure_root=closure_root,
            issued_at="2026-07-16T20:19:00Z",
            subject_digest=subject_digest,
        )
        bundle["reviewEnvelopes"].extend([reopened, final])
        bundle["consensus"]["finalAgreeReviewSha256"][0] = sha256_digest(final)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)

    def test_rejects_finding_id_reopened_after_acknowledgement(self) -> None:
        self._append_reopened_anthropic_finding(same_round_ack=False)
        with self.assertRaisesRegex(PolicyError, "REVIEW_FINDING_REUSED"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_same_round_finding_raise_and_acknowledgement(self) -> None:
        self._append_reopened_anthropic_finding(same_round_ack=True)
        with self.assertRaisesRegex(PolicyError, "REVIEW_FINDING_STATE_INVALID"):
            self.verifier().verify_bundle(self.fixture.bundle_envelope)

    def test_rejects_phantom_resolve_and_acknowledgement(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        previous = sha256_digest(bundle["reviewEnvelopes"][2])
        subject_digest = self.factory.decode_payload(bundle["reviewEnvelopes"][2])[
            "subjectSha256"
        ]
        closure_root = bundle["closure"]["closureRootSha256"]
        phantom = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000004",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=4,
            verdict="PARTIAL",
            previous=previous,
            closure_root=closure_root,
            resolved=["PHANTOM_FINDING"],
            acknowledged=["PHANTOM_FINDING"],
            issued_at="2026-07-16T20:18:00Z",
            subject_digest=subject_digest,
        )
        final = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000005",
            chain_id="40000000-0000-4000-8000-000000000001",
            key_id=self.factory.ANTHROPIC_KEY_ID,
            round_number=5,
            verdict="AGREE",
            previous=sha256_digest(phantom),
            closure_root=closure_root,
            issued_at="2026-07-16T20:19:00Z",
            subject_digest=subject_digest,
        )
        bundle["reviewEnvelopes"].extend([phantom, final])
        bundle["consensus"]["finalAgreeReviewSha256"][0] = sha256_digest(final)
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)
        with self.assertRaisesRegex(PolicyError, "REVIEW_FINDING_REFERENCE_INVALID"):
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


class EvidenceContractV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FixtureFactory("v2")
        self.fixture = self.factory.build()

    def verifier(self) -> EvidenceVerifier:
        return EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        )

    def test_accepts_post_cutoff_codex_only_v2_bundle(self) -> None:
        result = self.verifier().verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(result.provider_families, ("openai",))
        self.assertEqual(len(result.final_review_digests), 1)
        self.assertEqual(
            result.provider_identity_classes,
            (
                ("openai", "trusted-launch-attested"),
            ),
        )
        payload = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.assertEqual(
            payload["schemaVersion"], "acik.cross-ai-deployment-bundle.v2"
        )
        self.assertEqual(
            self.fixture.bundle_envelope["payloadType"],
            "application/vnd.acik.cross-ai-deployment-bundle.v2+json",
        )

    def test_accepts_single_round_direct_agree_v2_bundle(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        prior_tip = self.factory.decode_payload(bundle["reviewEnvelopes"][-1])
        subject_digest = prior_tip["subjectSha256"]
        closure_root = sha256_digest(
            {
                "domain": self.factory.closure_domain,
                "subjectSha256": subject_digest,
                "entries": [],
            }
        )
        direct_agree = self.factory._review(
            review_id="50000000-0000-4000-8000-000000000010",
            chain_id="40000000-0000-4000-8000-000000000010",
            key_id=self.factory.OPENAI_KEY_ID,
            round_number=1,
            verdict="AGREE",
            previous=None,
            closure_root=closure_root,
            issued_at="2026-07-18T20:15:00Z",
            subject_digest=subject_digest,
        )
        direct_agree_digest = sha256_digest(direct_agree)
        bundle["reviewEnvelopes"] = [direct_agree]
        bundle["closure"] = {
            "entries": [],
            "closureRootSha256": closure_root,
        }
        bundle["consensus"] = {
            "providerFamilies": ["openai"],
            "finalAgreeReviewSha256": [direct_agree_digest],
            "closureRootSha256": closure_root,
            "openMustFixFindingCount": 0,
        }
        self.factory.resign_bundle(self.fixture.bundle_envelope, bundle)

        result = self.verifier().verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(result.provider_families, ("openai",))
        self.assertEqual(result.final_review_digests, (direct_agree_digest,))

    def test_rotation_accepts_previous_key_only_while_it_remains_active(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        provider = next(
            item for item in trust_root["keys"] if item["role"] == "provider-review"
        )
        provider["notAfter"] = "2026-07-18T20:31:00Z"
        result = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(result.provider_families, ("openai",))

    def test_review_time_is_separate_from_current_revocation_freshness(self) -> None:
        refreshed_revocations = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-revocations.v1+json",
            {
                "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
                "revocationSetId": "20000000-0000-4000-8000-000000000008",
                "issuedAt": "2026-07-18T20:20:00Z",
                "nextUpdate": "2026-07-18T21:00:00Z",
                "entries": [],
            },
            self.factory.REVOCATION_KEY_ID,
        )
        verifier = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=refreshed_revocations,
            now=self.fixture.now,
            review_reference_time=datetime(
                2026, 7, 18, 20, 15, tzinfo=timezone.utc
            ),
        )
        self.assertEqual(
            ("openai",),
            verifier.verify_bundle(self.fixture.bundle_envelope).provider_families,
        )

    def test_rejects_review_reference_after_authority_observation(self) -> None:
        with self.assertRaisesRegex(PolicyError, "REVIEW_REFERENCE_INVALID"):
            EvidenceVerifier(
                trust_root=self.fixture.trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
                review_reference_time=datetime(
                    2026, 7, 18, 20, 31, tzinfo=timezone.utc
                ),
            )

    def test_active_verification_rejects_expired_key_with_backdated_leaf(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        provider = next(
            item for item in trust_root["keys"] if item["role"] == "provider-review"
        )
        # The existing leaf was signed during this interval, but the key is no
        # longer active at the independent observation time. issuedAt cannot
        # turn the retired key back into an active acceptance authority.
        provider["notAfter"] = "2026-07-18T20:16:00Z"
        with self.assertRaisesRegex(PolicyError, "TRUST_ACTIVE_KEY_MISSING"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            ).verify_bundle(self.fixture.bundle_envelope)

        durable = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
            review_reference_time=datetime(
                2026, 7, 18, 20, 15, tzinfo=timezone.utc
            ),
        ).verify_bundle(self.fixture.bundle_envelope)
        self.assertEqual(durable.provider_families, ("openai",))

    def test_v2_rejects_ephemeral_root_lifetime(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["expiresAt"] = "2026-07-21T19:00:00Z"
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_LIFETIME_INVALID"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

    def test_review_must_be_issued_during_root_and_provider_key_validity(self) -> None:
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        final_leaf = bundle["reviewEnvelopes"][-1]
        subject_digest = self.factory.decode_payload(final_leaf)["subjectSha256"]

        root_after_review = copy.deepcopy(self.fixture.trust_root)
        root_after_review["issuedAt"] = "2026-07-18T20:20:00Z"
        refreshed_revocations = self.factory.sign(
            "application/vnd.acik.cross-ai-deployment-revocations.v1+json",
            {
                "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
                "revocationSetId": "20000000-0000-4000-8000-000000000009",
                "issuedAt": "2026-07-18T20:20:00Z",
                "nextUpdate": "2026-07-18T21:00:00Z",
                "entries": [],
            },
            self.factory.REVOCATION_KEY_ID,
        )
        verifier = EvidenceVerifier(
            trust_root=root_after_review,
            revocations_envelope=refreshed_revocations,
            now=self.fixture.now,
        )
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_NOT_YET_VALID"):
            verifier.verify_provider_review(final_leaf, subject_digest)

        key_after_review = copy.deepcopy(self.fixture.trust_root)
        provider = next(
            item for item in key_after_review["keys"] if item["role"] == "provider-review"
        )
        provider["notBefore"] = "2026-07-18T20:20:00Z"
        verifier = EvidenceVerifier(
            trust_root=key_after_review,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        )
        with self.assertRaisesRegex(PolicyError, "SIGNING_KEY_NOT_YET_VALID"):
            verifier.verify_provider_review(final_leaf, subject_digest)

    def test_v2_rejects_retired_providers_and_openai_provider_report_upgrade(self) -> None:
        trust_root = copy.deepcopy(self.fixture.trust_root)
        openai = next(
            item
            for item in trust_root["keys"]
            if item["providerFamily"] == "openai"
        )
        openai["allowedModelIdentityClasses"] = ["provider-reported"]
        with self.assertRaisesRegex(
            PolicyError, "TRUST_ROOT_SCHEMA_INVALID|TRUST_PROVIDER_ROUTE_INVALID"
        ):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

        minimax = copy.deepcopy(self.factory.trust_root()["keys"][0])
        minimax.update(
            {
                "keyId": self.factory.MINIMAX_KEY_ID,
                "publicKeyBase64": base64.b64encode(b"\x09" * 32).decode("ascii"),
                "providerFamily": "minimax",
                "allowedChannels": ["direct-minimax-cli"],
                "allowedModelIds": ["minimax/MiniMax-M3"],
                "allowedModelIdentityClasses": ["provider-reported"],
            }
        )
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"].append(minimax)
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_SCHEMA_INVALID"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )

        anthropic = copy.deepcopy(self.factory.trust_root()["keys"][0])
        anthropic.update(
            {
                "keyId": self.factory.ANTHROPIC_KEY_ID,
                "publicKeyBase64": base64.b64encode(b"\x08" * 32).decode("ascii"),
                "providerFamily": "anthropic",
                "allowedChannels": ["direct-anthropic-cli"],
                "allowedModelIds": ["claude-opus-4-8"],
                "allowedModelIdentityClasses": ["provider-reported"],
            }
        )
        trust_root = copy.deepcopy(self.fixture.trust_root)
        trust_root["keys"].append(anthropic)
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_SCHEMA_INVALID"):
            EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.fixture.now,
            )


if __name__ == "__main__":
    unittest.main()
