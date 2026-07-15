#!/usr/bin/env python3

from __future__ import annotations

import copy
import base64
import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/faz23/verify-remote-view-policy.py"
SPEC = importlib.util.spec_from_file_location("remote_view_policy_verifier", MODULE_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class RemoteViewTenantPrivacyPolicyV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(
            (ROOT / "config/remote-view-platform-safety-baseline.v1.json").read_text(encoding="utf-8")
        )
        cls.policy = json.loads(
            (ROOT / "examples/remote-view/example-tr-domestic-tenant-policy.v1.json").read_text(encoding="utf-8")
        )
        cls.at = datetime(2026, 7, 16, tzinfo=timezone.utc)

    def verify(self, baseline=None, policy=None):
        baseline = copy.deepcopy(self.baseline if baseline is None else baseline)
        policy = copy.deepcopy(self.policy if policy is None else policy)
        VERIFIER.validate_schema(baseline, VERIFIER.BASELINE_SCHEMA, "platform baseline")
        VERIFIER.validate_schema(policy, VERIFIER.POLICY_SCHEMA, "tenant policy")
        VERIFIER.validate_baseline_binding(baseline, policy)
        VERIFIER.validate_lifecycle(baseline, policy, self.at)
        VERIFIER.validate_limits(baseline, policy)
        VERIFIER.validate_notice(policy)
        VERIFIER.validate_policy_semantics(baseline, policy)

    def approved_policy(self):
        policy = copy.deepcopy(self.policy)
        decision_digest = "sha256:" + "b" * 64
        policy["deploymentClass"] = "production"
        policy["legalEvidence"].update({
            "status": "approved",
            "decisionRecordRef": "urn:remote-view-legal-decision:" + decision_digest,
            "decisionRecordDigest": decision_digest,
            "approvedAt": "2026-07-15T12:00:00Z",
        })
        return policy

    def test_example_policy_passes(self):
        self.verify()

    def test_example_pins_recomputed_baseline_digest(self):
        self.assertEqual(self.policy["baseline"]["baselineDigest"], VERIFIER.digest(self.baseline))

    def test_unknown_policy_field_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["session"]["unattended"] = True
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_baseline_digest_mismatch_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["baseline"]["baselineDigest"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(VERIFIER.PolicyError, "baselineDigest"):
            self.verify(policy=policy)

    def test_default_locale_without_localization_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["notice"]["defaultLocale"] = "en-US"
        with self.assertRaisesRegex(VERIFIER.PolicyError, "defaultLocale"):
            self.verify(policy=policy)

    def test_notice_text_drift_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["notice"]["localizations"][0]["body"] += " Degisti."
        with self.assertRaisesRegex(VERIFIER.PolicyError, "localization digest mismatch"):
            self.verify(policy=policy)

    def test_session_ttl_above_platform_limit_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["session"]["maxSessionTtlSeconds"] = 7201
        with self.assertRaisesRegex(VERIFIER.PolicyError, "maxSessionTtlSeconds"):
            self.verify(policy=policy)

    def test_recording_disabled_cannot_persist_content(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["retention"]["screenContent"] = {"persisted": True, "ttlSeconds": 60}
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_cross_border_deny_cannot_name_destination(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["dataGovernance"]["destinationRegions"] = ["eu-example-1"]
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_production_requires_approved_legal_evidence(self):
        policy = copy.deepcopy(self.policy)
        policy["deploymentClass"] = "production"
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_approved_legal_evidence_requires_approved_at(self):
        policy = self.approved_policy()
        policy["legalEvidence"]["approvedAt"] = None
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_bounded_test_cannot_add_a_second_viewer(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["session"]["maxViewers"] = 2
        with self.assertRaisesRegex(VERIFIER.PolicyError, "schema invalid"):
            self.verify(policy=policy)

    def test_withdrawn_legal_evidence_denies_bounded_test(self):
        policy = copy.deepcopy(self.policy)
        policy["legalEvidence"]["status"] = "withdrawn"
        with self.assertRaisesRegex(VERIFIER.PolicyError, "cannot authorize"):
            self.verify(policy=policy)

    def test_expired_review_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["lifecycle"]["reviewBy"] = "2026-07-15T12:00:00Z"
        with self.assertRaisesRegex(VERIFIER.PolicyError, "reviewBy has expired"):
            self.verify(policy=policy)

    def test_dlp_failure_action_cannot_be_weakened(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["specialCategory"]["detectionFailureAction"] = "pause-session"
        with self.assertRaisesRegex(VERIFIER.PolicyError, "DLP failure action"):
            self.verify(policy=policy)

    def test_cross_border_destination_cannot_repeat_storage_region(self):
        policy = self.approved_policy()
        governance = policy["policy"]["dataGovernance"]
        governance.update({
            "residencyMode": "regional",
            "crossBorderTransfer": "allow-with-safeguards",
            "destinationRegions": ["tr-example-1"],
            "transferSafeguardRef": "https://privacy.example.invalid/transfer-safeguard",
        })
        with self.assertRaisesRegex(VERIFIER.PolicyError, "must not repeat storage regions"):
            self.verify(policy=policy)

    def test_controller_cannot_repeat_as_processor(self):
        policy = copy.deepcopy(self.policy)
        policy["policy"]["dataGovernance"]["processors"] = [
            copy.deepcopy(policy["policy"]["dataGovernance"]["controller"])
        ]
        with self.assertRaisesRegex(VERIFIER.PolicyError, "organization IDs must be unique"):
            self.verify(policy=policy)

    def test_canonicalizer_rejects_floats_even_before_future_schema_changes(self):
        with self.assertRaisesRegex(VERIFIER.PolicyError, "floats are not permitted"):
            VERIFIER.canonical_bytes({"ttlSeconds": 1.5})


class RemoteViewSessionPolicyEnvelopeV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from jsonschema import Draft202012Validator, FormatChecker

        cls.schema = json.loads(
            (ROOT / "schema/remote-view-session-policy-envelope-v1.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())
        digest = "sha256:" + "a" * 64
        cls.envelope = {
            "schemaVersion": "remote-view-session-policy-envelope-v1",
            "envelopeId": "env:session-1:1",
            "deploymentClass": "bounded-test",
            "session": {
                "sessionId": "session-1",
                "tenantId": "00000000-0000-4000-8000-000000000245",
                "deviceId": "device-1",
                "issuedAt": "2026-07-16T00:00:00Z",
                "expiresAt": "2026-07-16T00:05:00Z",
                "ttlSeconds": 300,
                "nonceBase64": base64.b64encode(bytes(32)).decode("ascii"),
            },
            "policy": {
                "policyId": "example-tr-domestic-view-only",
                "policyVersion": "1.0.0",
                "policyDigest": digest,
                "sourcePolicyRef": "urn:remote-view-tenant-policy:" + digest,
                "baselineId": "remote-view-platform-safety",
                "baselineVersion": "1.0.0",
                "baselineDigest": digest,
                "legalEvidenceStatus": "tracked-pending",
                "legalEvidenceDigest": digest,
            },
            "enforcement": {
                "mode": "attended-view-only",
                "attendedConsentRequired": True,
                "autoConsentAllowed": False,
                "screenViewAllowed": True,
                "keyboardInputAllowed": False,
                "mouseInputAllowed": False,
                "clipboardAllowed": False,
                "fileTransferAllowed": False,
                "tunnelAllowed": False,
                "visibleIndicatorRequired": True,
                "localAbortRequired": True,
                "maxViewers": 1,
                "recordingMode": "disabled",
            },
            "notice": {
                "noticeVersion": "1.0.0",
                "locale": "tr-TR",
                "title": "Ekran görüntüleme isteği",
                "body": "Bu, şema doğrulaması için yeterince uzun ve açık bir örnek bilgilendirme metnidir.",
                "allowLabel": "İzin ver",
                "denyLabel": "Reddet",
                "withdrawalText": "İzin her zaman geri çekilebilir.",
                "localAbortText": "Oturum yerel Durdur denetimiyle sonlandırılır.",
                "contentDigest": digest,
            },
            "dataHandling": {
                "screenContentTtlSeconds": 0,
                "sessionMetadataTtlSeconds": 2592000,
                "auditTtlSeconds": 2592000,
                "storageRegions": ["tr-example-1"],
                "crossBorderTransfer": "deny",
                "specialCategoryAction": "pause-and-mask",
            },
            "integrity": {
                "canonicalization": "JCS-RFC8785",
                "signatureAlgorithm": "Ed25519",
                "keyId": "remote-view-signing-key-1",
                "payloadDigest": digest,
                "signatureBase64": base64.b64encode(bytes(64)).decode("ascii"),
            },
        }

    def assert_valid(self, envelope):
        errors = list(self.validator.iter_errors(envelope))
        self.assertEqual([], [error.message for error in errors])

    def test_structural_envelope_passes(self):
        self.assert_valid(copy.deepcopy(self.envelope))

    def test_envelope_cannot_disable_attended_consent(self):
        envelope = copy.deepcopy(self.envelope)
        envelope["enforcement"]["attendedConsentRequired"] = False
        self.assertTrue(list(self.validator.iter_errors(envelope)))

    def test_envelope_unknown_field_is_rejected(self):
        envelope = copy.deepcopy(self.envelope)
        envelope["session"]["operatorToken"] = "forbidden"
        self.assertTrue(list(self.validator.iter_errors(envelope)))

    def test_production_envelope_requires_approved_legal_evidence(self):
        envelope = copy.deepcopy(self.envelope)
        envelope["deploymentClass"] = "production"
        self.assertTrue(list(self.validator.iter_errors(envelope)))

    def test_bounded_test_envelope_cannot_enable_recording(self):
        envelope = copy.deepcopy(self.envelope)
        envelope["enforcement"]["recordingMode"] = "enabled"
        self.assertTrue(list(self.validator.iter_errors(envelope)))


if __name__ == "__main__":
    unittest.main()
