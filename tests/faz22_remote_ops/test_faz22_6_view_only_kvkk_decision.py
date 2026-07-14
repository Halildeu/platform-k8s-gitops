import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "scripts/faz22-remote-ops/verify-view-only-kvkk-decision.py"
SPEC = importlib.util.spec_from_file_location("kvkk_decision_verifier", MODULE_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def valid_unsigned_record(now: datetime) -> dict:
    owner_signed = now - timedelta(hours=2)
    legal_signed = now - timedelta(hours=1)
    approved = legal_signed
    return {
        "schemaVersion": "faz22.6-view-only-kvkk-decision-v1",
        "status": "approved",
        "processingActivityId": "ropa-remote-screen-observation-test-pilot",
        "scope": {
            "environment": "test",
            "mode": "attended-view-only",
            "recordingMode": "disabled",
            "productChannel": "endpoint-agent-outbound-mtls-remote-bridge",
            "engineeringAcceptanceIssue": "https://github.com/Halildeu/platform-k8s-gitops/issues/1580",
            "viewerProductAcceptanceIssue": "https://github.com/Halildeu/platform-k8s-gitops/issues/2373",
            "kvkkTrackingIssue": "https://github.com/Halildeu/platform-k8s-gitops/issues/2374",
            "viewerProductEvidenceSha256": "sha256:" + "9" * 64,
            "viewerProductEvidenceRef": "protected://kvkk/viewer-product-evidence/opaque-01",
            "pilotOperatorRef": "protected://kvkk/operator/opaque-01",
            "pilotDeviceRef": "protected://kvkk/device/opaque-01",
            "onePersonRosterRef": "protected://kvkk/roster/opaque-01",
        },
        "processing": {
            "purpose": "Provide attended and time-bounded technical support by observing the approved test device screen.",
            "legalBasis": "human-selected-kvkk-legal-basis-recorded-by-legal",
            "legalAuthorityRef": "policy://privacy/legal-basis/remote-observation-v1",
            "screenDataCategories": ["application interface", "session diagnostics"],
            "specialCategoryData": {
                "expected": False,
                "handlingDecision": "Special-category data is outside pilot scope and must not be intentionally displayed.",
                "exposureResponse": "The operator stops viewing, records metadata only, and follows the privacy incident runbook.",
            },
        },
        "noticeAndConsent": {
            "noticeVersion": "remote-observation-notice-v1",
            "noticeRef": "policy://privacy/notices/remote-observation-v1",
            "attendedConsentRequired": True,
            "consentEvidenceRef": "protected://kvkk/consent/opaque-01",
            "withdrawalMethod": "The device user can withdraw consent in the visible session indicator at any time.",
            "localAbortMethod": "The device-local abort control terminates viewing immediately and emits audit metadata.",
            "visibleIndicatorRequired": True,
        },
        "retention": {
            "screenContent": {
                "persisted": False,
                "retentionDays": 0,
                "justification": "Recording is disabled and no screen-content object is persisted by the bounded pilot.",
                "ownerPrincipalId": "person:privacy.owner",
            },
            "sessionMetadata": {
                "retentionDays": 30,
                "justification": "Thirty days supports bounded security investigation while limiting personal-data exposure.",
                "ownerPrincipalId": "person:privacy.owner",
                "effectiveFrom": utc(approved - timedelta(days=1)),
            },
            "auditRecords": {
                "retentionDays": 365,
                "justification": "One year supports audit accountability for the bounded pilot under the approved policy.",
                "ownerPrincipalId": "person:privacy.owner",
                "effectiveFrom": utc(approved - timedelta(days=1)),
            },
            "recordingEnabledChangePolicy": {
                "newDecisionRequired": True,
                "newEngineeringAcceptanceRequired": True,
                "wormRequired": True,
                "recordBeforeFanoutRequired": True,
                "parameterizedRetentionRequired": True,
            },
        },
        "governance": {
            "controller": "Acik Holding approved controller entity",
            "processors": [{
                "name": "Internal platform operations service",
                "role": "Remote observation transport and audit metadata processing",
                "location": "Approved test processing region",
                "dataCategories": ["session metadata", "transient screen frames"],
                "safeguardsRef": "policy://privacy/processors/internal-platform-v1",
            }],
            "subprocessors": [],
            "storageRegion": "Approved test processing region",
            "crossBorderTransfer": {
                "enabled": False,
                "decision": "No cross-border transfer is approved for this bounded test pilot scope.",
                "safeguardRef": "policy://privacy/transfers/no-transfer-test-pilot-v1",
            },
            "accessLogging": {
                "enabled": True,
                "evidenceRef": "artifact://faz22/view-only/access-logging-evidence",
            },
            "decisionRecordStorage": {
                "encryptionAtRest": True,
                "accessLogging": True,
                "writeProtection": True,
                "immutabilityMode": "equivalent-write-once-control",
                "kmsCustodyRef": "policy://privacy/evidence-store/kms-custody-v1",
                "accessPolicyRef": "policy://privacy/evidence-store/access-policy-v1",
                "writeProtectionEvidenceRef": "artifact://privacy/evidence-store/write-protection-proof",
                "recordRetention": {
                    "retentionDays": 365,
                    "justification": "One year preserves the signed pilot decision for audit and rights handling.",
                    "ownerPrincipalId": "person:privacy.owner",
                    "effectiveFrom": utc(approved - timedelta(days=1)),
                },
                "humanReadableExportProcedureRef": "runbook://privacy/decision-record-export-v1",
            },
            "processingActivityRegisterRef": "ropa://remote-screen-observation/test-pilot-v1",
            "dataSubjectRights": {
                "access": "Requests are correlated through the processing activity and protected evidence references.",
                "correction": "Verified correction requests are routed to the controller privacy owner for action.",
                "erasureOrRestriction": "Verified erasure or restriction requests follow the approved retention exceptions.",
                "objection": "Objection immediately prevents a new attended viewing session from starting.",
                "requestPath": "contact://privacy/data-subject-rights",
            },
            "incidentResponse": {
                "contactRef": "contact://privacy/incident-response",
                "notificationWindowHours": 72,
                "runbookRef": "runbook://privacy/screen-observation-incident-v1",
            },
        },
        "pilotApprovals": {
            "allowTest8096ClusterIPExposure": True,
            "onePersonRosterApproved": True,
            "consentingPilotDeviceApproved": True,
        },
        "uxVerification": {
            "verifiedAt": utc(approved - timedelta(hours=1)),
            "verifiedByPrincipalId": "person:human.tester",
            "evidenceRef": "protected://kvkk/ux-verification/opaque-01",
            "noticeDisplayedBeforeStart": True,
            "explicitConsentCaptured": True,
            "withdrawalTerminatesSession": True,
            "localAbortTerminatesSession": True,
            "indicatorVisibleThroughout": True,
        },
        "lifecycle": {
            "approvedAt": utc(approved),
            "reviewExpiresAt": utc(approved + timedelta(days=180)),
            "changeTriggers": [
                "purpose-or-legal-basis-change",
                "recording-mode-change",
                "data-category-change",
                "controller-processor-or-transfer-change",
                "retention-change",
                "security-or-privacy-incident",
                "material-product-scope-change",
                "regulatory-guidance-change",
            ],
        },
        "boundaries": {
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
            "recordingEnabled": False,
            "fiveDeviceReady": False,
            "fiftyDeviceReady": False,
            "eightHundredDeviceReady": False,
        },
        "approvals": {
            "privacyOwner": {
                "principalId": "person:privacy.owner",
                "role": "privacy-owner",
                "signedAt": utc(owner_signed),
                "signatureAlgorithm": "ed25519",
                "signatureBase64": base64.b64encode(b"\0" * 64).decode("ascii"),
            },
            "legalOrDpo": {
                "principalId": "person:legal.reviewer",
                "role": "legal-or-dpo",
                "signedAt": utc(legal_signed),
                "signatureAlgorithm": "ed25519",
                "signatureBase64": base64.b64encode(b"\0" * 64).decode("ascii"),
            },
        },
    }


def policy(now: datetime, owner_key: Ed25519PrivateKey, legal_key: Ed25519PrivateKey) -> dict:
    return {
        "schemaVersion": "faz22.6-view-only-kvkk-approver-policy-v1",
        "policyId": "privacy-approvers-2026-v1",
        "identityDirectoryRef": "policy://privacy/identity-directory/kvkk-approvers-v1",
        "engineeringPrincipalIds": ["person:engineering.owner", "person:human.tester"],
        "authorizedApprovers": [
            {
                "keyId": "kvkk-privacy-owner-2026",
                "principalId": "person:privacy.owner",
                "role": "privacy-owner",
                "ed25519PublicKeyBase64": public_key_b64(owner_key),
                "validFrom": utc(now - timedelta(days=30)),
                "validUntil": utc(now + timedelta(days=365)),
            },
            {
                "keyId": "kvkk-legal-reviewer-2026",
                "principalId": "person:legal.reviewer",
                "role": "legal-or-dpo",
                "ed25519PublicKeyBase64": public_key_b64(legal_key),
                "validFrom": utc(now - timedelta(days=30)),
                "validUntil": utc(now + timedelta(days=365)),
            },
        ],
    }


def signed_fixture(now: datetime):
    owner_key = Ed25519PrivateKey.generate()
    legal_key = Ed25519PrivateKey.generate()
    record = valid_unsigned_record(now)
    approver_policy = policy(now, owner_key, legal_key)
    record["approvals"]["privacyOwner"]["signatureBase64"] = base64.b64encode(
        owner_key.sign(VERIFIER.approval_message(record, record["approvals"]["privacyOwner"], approver_policy))
    ).decode("ascii")
    record["approvals"]["legalOrDpo"]["signatureBase64"] = base64.b64encode(
        legal_key.sign(VERIFIER.approval_message(record, record["approvals"]["legalOrDpo"], approver_policy))
    ).decode("ascii")
    return record, approver_policy


class KvkkDecisionVerifierTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def verify(self, record, approver_policy):
        VERIFIER.validate_schema(record, VERIFIER.DECISION_SCHEMA, "decision")
        VERIFIER.validate_schema(approver_policy, VERIFIER.POLICY_SCHEMA, "approver policy")
        return VERIFIER.validate_semantics(record, approver_policy, self.now, verify_signatures=True)

    def test_two_authorized_human_signatures_emit_content_addressed_marker(self):
        record, approver_policy = signed_fixture(self.now)
        result = self.verify(record, approver_policy)
        marker = VERIFIER.marker_text(result)
        self.assertEqual("pass", result["status"])
        self.assertRegex(result["decisionRecordSha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("decision_record_ref: urn:decision-record:sha256:", marker)
        self.assertIn("status: cleared", marker)
        self.assertNotIn("person:", marker)
        self.assertNotIn("protected://", marker)
        marker_result = VERIFIER.verify_marker(marker, approver_policy, self.now)
        self.assertEqual("pass", marker_result["status"])
        self.assertEqual(2, marker_result["humanSignatureCount"])

    def test_marker_lifecycle_policy_or_signature_tamper_fails(self):
        record, approver_policy = signed_fixture(self.now)
        result = self.verify(record, approver_policy)
        marker = VERIFIER.marker_text(result)

        tampered_expiry = marker.replace(
            result["reviewExpiresAt"],
            utc(datetime.fromisoformat(result["reviewExpiresAt"].replace("Z", "+00:00")) + timedelta(days=1)),
        )
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signature verification failed"):
            VERIFIER.verify_marker(tampered_expiry, approver_policy, self.now)

        tampered_record_digest = marker.replace(
            result["decisionRecordSha256"], "sha256:" + "c" * 64
        )
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signature verification failed"):
            VERIFIER.verify_marker(tampered_record_digest, approver_policy, self.now)

        tampered_policy = json.loads(json.dumps(approver_policy))
        tampered_policy["policyId"] = "different-reviewed-policy"
        with self.assertRaisesRegex(VERIFIER.DecisionError, "policy reference"):
            VERIFIER.verify_marker(marker, tampered_policy, self.now)

        tampered_signature = marker.replace(
            result["approvalAttestations"]["privacyOwner"]["signatureBase64"],
            base64.b64encode(b"x" * 64).decode("ascii"),
        )
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signature verification failed"):
            VERIFIER.verify_marker(tampered_signature, approver_policy, self.now)

        noncanonical = marker.replace("status: cleared", "status:  cleared")
        with self.assertRaisesRegex(VERIFIER.DecisionError, "non-canonical"):
            VERIFIER.verify_marker(noncanonical, approver_policy, self.now)

    def test_signing_request_mode_has_no_marker_and_jcs_matches_jq(self):
        owner_key = Ed25519PrivateKey.generate()
        legal_key = Ed25519PrivateKey.generate()
        record = valid_unsigned_record(self.now)
        approver_policy = policy(self.now, owner_key, legal_key)
        request = VERIFIER.signing_requests(record, approver_policy, self.now)
        self.assertEqual(2, len(request["requests"]))
        self.assertNotIn("marker", request)

        for value in (VERIFIER.decision_payload(record), approver_policy):
            independent = subprocess.run(
                ["jq", "-cS", "."],
                input=json.dumps(value, ensure_ascii=False).encode("utf-8"),
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.rstrip(b"\n")
            self.assertEqual(independent, VERIFIER.canonical_bytes(value))

    def test_openssl_fallback_verifies_same_ed25519_signature(self):
        version = subprocess.run(
            ["openssl", "version"], stdout=subprocess.PIPE, text=True, check=True
        ).stdout
        if not version.startswith("OpenSSL 3"):
            self.skipTest(f"system fallback requires OpenSSL 3, found: {version.strip()}")
        key = Ed25519PrivateKey.generate()
        message = b"faz22.6-openssl-fallback-test\n"
        signature = key.sign(message)
        public_key = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        VERIFIER.verify_signature_with_openssl(message, signature, public_key, "fallback-test")
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signature verification failed"):
            VERIFIER.verify_signature_with_openssl(message + b"tamper", signature, public_key, "fallback-test")

    def test_same_person_or_engineering_principal_cannot_approve(self):
        record, approver_policy = signed_fixture(self.now)
        record["approvals"]["legalOrDpo"]["principalId"] = "person:privacy.owner"
        with self.assertRaisesRegex(VERIFIER.DecisionError, "different people"):
            self.verify(record, approver_policy)

        record, approver_policy = signed_fixture(self.now)
        approver_policy["engineeringPrincipalIds"].append("person:privacy.owner")
        with self.assertRaisesRegex(VERIFIER.DecisionError, "engineering principal"):
            self.verify(record, approver_policy)

    def test_tamper_after_signature_fails(self):
        record, approver_policy = signed_fixture(self.now)
        record["retention"]["sessionMetadata"]["retentionDays"] = 31
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signature verification failed"):
            self.verify(record, approver_policy)

    def test_expired_or_excessive_review_window_fails(self):
        record, approver_policy = signed_fixture(self.now)
        record["lifecycle"]["reviewExpiresAt"] = utc(self.now - timedelta(seconds=1))
        with self.assertRaisesRegex(VERIFIER.DecisionError, "is expired"):
            self.verify(record, approver_policy)

        record, approver_policy = signed_fixture(self.now)
        approved = datetime.fromisoformat(record["lifecycle"]["approvedAt"].replace("Z", "+00:00"))
        record["lifecycle"]["reviewExpiresAt"] = utc(approved + timedelta(days=367))
        with self.assertRaisesRegex(VERIFIER.DecisionError, "must not exceed"):
            self.verify(record, approver_policy)

    def test_future_signed_marker_fails_even_with_valid_signatures(self):
        owner_key = Ed25519PrivateKey.generate()
        legal_key = Ed25519PrivateKey.generate()
        approver_policy = policy(self.now, owner_key, legal_key)
        record = valid_unsigned_record(self.now + timedelta(hours=3))
        record["approvals"]["privacyOwner"]["signatureBase64"] = base64.b64encode(
            owner_key.sign(VERIFIER.approval_message(record, record["approvals"]["privacyOwner"], approver_policy))
        ).decode("ascii")
        record["approvals"]["legalOrDpo"]["signatureBase64"] = base64.b64encode(
            legal_key.sign(VERIFIER.approval_message(record, record["approvals"]["legalOrDpo"], approver_policy))
        ).decode("ascii")
        future_result = VERIFIER.validate_semantics(
            record, approver_policy, self.now + timedelta(hours=4), verify_signatures=True
        )
        with self.assertRaisesRegex(VERIFIER.DecisionError, "signed_at is in the future"):
            VERIFIER.verify_marker(VERIFIER.marker_text(future_result), approver_policy, self.now)

    def test_unknown_or_placeholder_fields_fail_closed(self):
        record, approver_policy = signed_fixture(self.now)
        record["scope"]["productionOverride"] = True
        with self.assertRaisesRegex(VERIFIER.DecisionError, "schema invalid"):
            self.verify(record, approver_policy)

        template = json.loads((ROOT / "docs/templates/faz22-6-view-only-kvkk-decision-v1.template.json").read_text())
        with self.assertRaises(VERIFIER.DecisionError):
            VERIFIER.validate_schema(template, VERIFIER.DECISION_SCHEMA, "decision")

    def test_withdrawal_is_visible_but_not_cleared(self):
        record, approver_policy = signed_fixture(self.now)
        record["status"] = "withdrawn"
        owner_key = Ed25519PrivateKey.generate()
        legal_key = Ed25519PrivateKey.generate()
        approver_policy = policy(self.now, owner_key, legal_key)
        record["approvals"]["privacyOwner"]["signatureBase64"] = base64.b64encode(
            owner_key.sign(VERIFIER.approval_message(record, record["approvals"]["privacyOwner"], approver_policy))
        ).decode("ascii")
        record["approvals"]["legalOrDpo"]["signatureBase64"] = base64.b64encode(
            legal_key.sign(VERIFIER.approval_message(record, record["approvals"]["legalOrDpo"], approver_policy))
        ).decode("ascii")
        result = self.verify(record, approver_policy)
        marker = VERIFIER.marker_text(result)
        self.assertIn("status: withdrawn", marker)
        self.assertNotIn("status: cleared", marker)

    def test_cli_never_emits_marker_on_invalid_signature(self):
        record, approver_policy = signed_fixture(self.now)
        record["approvals"]["privacyOwner"]["signatureBase64"] = base64.b64encode(b"x" * 64).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "record.json"
            policy_path = root / "policy.json"
            result_path = root / "result.json"
            marker_path = root / "marker.txt"
            record_path.write_text(json.dumps(record))
            policy_path.write_text(json.dumps(approver_policy))
            old_argv = sys.argv
            try:
                sys.argv = [
                    str(MODULE_PATH), "--input", str(record_path),
                    "--approver-policy", str(policy_path),
                    "--result-out", str(result_path), "--marker-out", str(marker_path),
                ]
                self.assertEqual(1, VERIFIER.main())
            finally:
                sys.argv = old_argv
            self.assertFalse(marker_path.exists())
            self.assertEqual("fail", json.loads(result_path.read_text())["status"])


if __name__ == "__main__":
    unittest.main()
