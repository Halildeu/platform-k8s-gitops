import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
MODULE_PATH = REPO_ROOT / "scripts/faz22-remote-ops/build-view-only-pilot-owner-authorization.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("view_only_pilot_owner_authorization", MODULE_PATH)
AUTH = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = AUTH
SPEC.loader.exec_module(AUTH)

RECEIPT_MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/verify-view-only-pilot-authorization-receipt.py"
RECEIPT_SPEC = importlib.util.spec_from_file_location("view_only_pilot_authorization_receipt", RECEIPT_MODULE_PATH)
RECEIPT = importlib.util.module_from_spec(RECEIPT_SPEC)
assert RECEIPT_SPEC and RECEIPT_SPEC.loader
sys.modules[RECEIPT_SPEC.name] = RECEIPT
RECEIPT_SPEC.loader.exec_module(RECEIPT)


OWNER_BODY = "Owner bounded-pilot directive"
ADVISORY_BODY = "Claude Opus 4.8 and Codex 5.6 SOL AGREE"
TEMPORARY_AUTOMATION_BODY = "Temporary TEST automation owner directive"


def environment_approval(active_mode="required-reviewer"):
    return {
        "activeMode": active_mode,
        "requiredReviewer": {"requirePreventSelfReview": True},
        "temporaryTestAutomation": {
            "directive": {
                "commentId": 103,
                "ref": "https://github.com/Halildeu/platform-k8s-gitops/issues/2828#issuecomment-103",
                "bodySha256": AUTH.digest_bytes(TEMPORARY_AUTOMATION_BODY.encode()),
                "authorLogin": "Halildeu",
                "authorAssociation": "OWNER",
            },
            "expectedLiveProtectionRules": [],
            "validFrom": "2026-08-01T00:00:00Z",
            "validUntil": "2026-08-08T00:00:00Z",
        },
        "restoration": {
            "reviewers": [{"type": "User", "id": 287014213, "name": "gladyatore-lab"}],
            "preventSelfReview": True,
            "trackedBy": "https://github.com/Halildeu/platform-k8s-gitops/issues/2502",
            "trigger": "temporary-window-expiry-or-before-production-or-after-machine-gate-activation",
        },
    }


def policy():
    return {
        "schemaVersion": AUTH.POLICY_SCHEMA,
        "status": "active",
        "ownerDirective": {
            "commentId": 101,
            "ref": "https://github.com/Halildeu/platform-k8s-gitops/issues/2373#issuecomment-101",
            "bodySha256": AUTH.digest_bytes(OWNER_BODY.encode()),
            "authorLogin": "Halildeu",
            "authorAssociation": "OWNER",
        },
        "aiAdvisory": {
            "commentId": 102,
            "ref": "https://github.com/Halildeu/platform-k8s-gitops/issues/2373#issuecomment-102",
            "bodySha256": AUTH.digest_bytes(ADVISORY_BODY.encode()),
            "authorLogin": "Halildeu",
            "authorAssociation": "OWNER",
            "advisoryOnly": True,
            "consensusVerdict": "AGREE",
            "providers": ["Anthropic/claude-opus-4-8", "OpenAI/gpt-5.6-sol"],
            "provenanceClass": "owner-attested-provider-session",
            "providerCryptographicAttestation": False,
        },
        "legalTracking": {
            "ref": AUTH.LEGAL_ISSUE_REF,
            "status": "tracked_pending",
            "clearanceClaimed": False,
            "dependencyAcknowledgedBy": "owner",
            "dependencyRationaleCode": "bounded-test-owner-risk-acceptance",
        },
        "scope": {
            "environment": "test",
            "mode": "attended-view-only",
            "recordingMode": "disabled",
            "screenContentPersisted": False,
            "pilotAutoConsent": False,
            "attendedConsentRequired": True,
            "visibleIndicatorRequired": True,
            "localAbortRequired": True,
            "maxViewers": 1,
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
        },
        "authorization": {
            "protectedEnvironment": AUTH.EXPECTED_ENVIRONMENT,
            "environmentApproval": environment_approval(),
            "maxTtlMinutes": 120,
            "killSwitchWorkflowRef": ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback",
            "revocationLedgerRef": "config/faz22-6-view-only-pilot-authorization-revocations.v1.json",
        },
        "lifecycle": {
            "validFrom": "2026-07-15T00:00:00Z",
            "validUntil": "2027-07-15T00:00:00Z",
        },
    }


def comment(comment_id, body, issue_number=2373):
    return {
        "id": comment_id,
        "html_url": f"https://github.com/Halildeu/platform-k8s-gitops/issues/{issue_number}#issuecomment-{comment_id}",
        "issue_url": f"https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/{issue_number}",
        "author_association": "OWNER",
        "user": {"login": "Halildeu"},
        "body": body,
    }


def environment():
    return {
        "name": AUTH.EXPECTED_ENVIRONMENT,
        "protection_rules": [{
            "type": "required_reviewers",
            "prevent_self_review": True,
            "reviewers": [{
                "type": "User",
                "reviewer": {"id": 700001, "login": "security-reviewer"},
            }],
        }],
    }


def legal_issue():
    return {"number": 2374, "state": "open", "html_url": AUTH.LEGAL_ISSUE_REF}


def revocations(entries=None):
    return {
        "schemaVersion": AUTH.REVOCATION_SCHEMA,
        "revokedAuthorizationSha256": entries or [],
    }


class ViewOnlyPilotOwnerAuthorizationTest(unittest.TestCase):
    def test_canonical_policy_uses_the_supported_advisory_pair(self):
        policy_path = REPO_ROOT / "config/faz22-6-view-only-pilot-owner-policy.v2.json"
        canonical = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertEqual(
            AUTH.EXPECTED_ADVISORY_PROVIDERS,
            canonical["aiAdvisory"]["providers"],
        )
        self.assertNotIn("MiniMax", json.dumps(canonical, sort_keys=True))
        self.assertEqual(5011715034, canonical["aiAdvisory"]["commentId"])
        self.assertEqual(
            "temporary-test-automation",
            canonical["authorization"]["environmentApproval"]["activeMode"],
        )
        self.assertEqual(
            [{"id": 287014213, "name": "gladyatore-lab", "type": "User"}],
            canonical["authorization"]["environmentApproval"]["restoration"]["reviewers"],
        )
        self.assertEqual(
            "sha256:a5895d569cdf6343cf26872bdd92645ffcc22fdf1006eb09b6f74c1e03694d16",
            canonical["aiAdvisory"]["bodySha256"],
        )

    def build(self, **overrides):
        inputs = {
            "policy": policy(),
            "owner_comment": comment(101, OWNER_BODY),
            "advisory_comment": comment(102, ADVISORY_BODY),
            "legal_issue": legal_issue(),
            "environment": environment(),
            "revocations": revocations(),
            "temporary_automation_comment": {},
            "operator_sha256": "sha256:" + "1" * 64,
            "device_sha256": "sha256:" + "2" * 64,
            "expires_at": "2026-07-15T02:00:00Z",
            "issued_at": "2026-07-15T00:00:00Z",
            "run_id": 123,
            "head_sha": "a" * 40,
            "triggering_actor": "workflow-operator",
        }
        inputs.update(overrides)
        return AUTH.build_authorization(**inputs)

    def test_valid_bounded_authorization_is_advisory_only_and_not_legal_clearance(self):
        result = self.build()
        self.assertEqual(AUTH.SCHEMA, result["schemaVersion"])
        self.assertTrue(result["aiAdvisoryOnly"])
        self.assertEqual("AGREE", result["aiConsensusVerdict"])
        self.assertEqual("tracked_pending", result["legalTrackStatus"])
        self.assertFalse(result["legalClearanceClaimed"])
        self.assertEqual("disabled", result["recordingMode"])
        self.assertFalse(result["screenContentPersisted"])

    def test_revise_or_legal_clearance_claim_fails_closed(self):
        value = policy()
        value["aiAdvisory"]["consensusVerdict"] = "REVISE"
        with self.assertRaisesRegex(AUTH.AuthorizationError, "consensus"):
            self.build(policy=value)

        value = policy()
        value["legalTracking"]["clearanceClaimed"] = True
        with self.assertRaisesRegex(AUTH.AuthorizationError, "tracked_pending"):
            self.build(policy=value)

    def test_legacy_minimax_advisory_cannot_issue_new_authorization(self):
        value = policy()
        value["aiAdvisory"]["providers"] = [
            "MiniMax/minimax-MiniMax-M3",
            "OpenAI/Codex",
        ]
        with self.assertRaisesRegex(AUTH.AuthorizationError, "provider-distinct pair"):
            self.build(policy=value)

    def test_closed_legal_ticket_or_unprotected_environment_fails_closed(self):
        issue = legal_issue()
        issue["state"] = "closed"
        with self.assertRaisesRegex(AUTH.AuthorizationError, "must remain open"):
            self.build(legal_issue=issue)

        protected = environment()
        protected["protection_rules"][0]["prevent_self_review"] = False
        with self.assertRaisesRegex(AUTH.AuthorizationError, "prevent self review"):
            self.build(environment=protected)

    def test_ttl_scope_and_identity_are_strict(self):
        with self.assertRaisesRegex(AUTH.AuthorizationError, "TTL"):
            self.build(expires_at="2026-07-15T02:00:01Z")

        value = policy()
        value["scope"]["recordingMode"] = "enabled"
        with self.assertRaisesRegex(AUTH.AuthorizationError, "bounded privacy-safe"):
            self.build(policy=value)

        with self.assertRaisesRegex(AUTH.AuthorizationError, "must be distinct"):
            self.build(device_sha256="sha256:" + "1" * 64)

    def test_policy_lifecycle_boundaries_fail_closed(self):
        with self.assertRaisesRegex(AUTH.AuthorizationError, "outside owner-policy lifecycle"):
            self.build(
                issued_at="2026-07-14T23:59:59Z",
                expires_at="2026-07-15T00:30:00Z",
            )
        with self.assertRaisesRegex(AUTH.AuthorizationError, "outside owner-policy lifecycle"):
            self.build(
                issued_at="2027-07-14T23:00:01Z",
                expires_at="2027-07-15T00:00:01Z",
            )

    def test_reviewer_identity_is_bound_and_triggering_actor_cannot_review(self):
        result = self.build()
        self.assertEqual(1, result["protectedEnvironmentReviewerCount"])
        self.assertRegex(result["protectedEnvironmentReviewerSetSha256"], r"^sha256:[a-f0-9]{64}$")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "triggering actor"):
            self.build(triggering_actor="security-reviewer")

    def test_temporary_test_automation_is_owner_bound_bounded_and_reversible(self):
        value = policy()
        value["authorization"]["environmentApproval"] = environment_approval(
            "temporary-test-automation"
        )
        result = self.build(
            policy=value,
            environment={"name": AUTH.EXPECTED_ENVIRONMENT, "protection_rules": []},
            temporary_automation_comment=comment(
                103, TEMPORARY_AUTOMATION_BODY, issue_number=2828,
            ),
            issued_at="2026-08-01T01:00:00Z",
            expires_at="2026-08-01T03:00:00Z",
        )
        self.assertEqual("temporary-test-automation", result["environmentApprovalMode"])
        self.assertFalse(result["exposureApprovedByProtectedEnvironment"])
        self.assertTrue(result["temporaryTestAutomationApprovedByOwner"])
        self.assertEqual(0, result["protectedEnvironmentReviewerCount"])
        self.assertEqual(1, result["restorationReviewerCount"])
        self.assertTrue(result["restorationPreventSelfReview"])
        raw = AUTH.canonical_bytes(result) + b"\n"
        RECEIPT.verify(
            result, raw, value, revocations(), 123, "a" * 40,
            datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc),
        )

    def test_temporary_test_automation_fails_closed_on_drift_expiry_or_tamper(self):
        value = policy()
        value["authorization"]["environmentApproval"] = environment_approval(
            "temporary-test-automation"
        )
        temporary_comment = comment(103, TEMPORARY_AUTOMATION_BODY, issue_number=2828)
        with self.assertRaisesRegex(AUTH.AuthorizationError, "empty live protection rule"):
            self.build(
                policy=value,
                temporary_automation_comment=temporary_comment,
                issued_at="2026-08-01T01:00:00Z",
                expires_at="2026-08-01T03:00:00Z",
            )
        with self.assertRaisesRegex(AUTH.AuthorizationError, "temporary TEST automation window"):
            self.build(
                policy=value,
                environment={"name": AUTH.EXPECTED_ENVIRONMENT, "protection_rules": []},
                temporary_automation_comment=temporary_comment,
                issued_at="2026-08-07T23:00:01Z",
                expires_at="2026-08-08T00:00:01Z",
            )
        with self.assertRaisesRegex(AUTH.AuthorizationError, "body digest"):
            self.build(
                policy=value,
                environment={"name": AUTH.EXPECTED_ENVIRONMENT, "protection_rules": []},
                temporary_automation_comment=comment(
                    103, TEMPORARY_AUTOMATION_BODY + " tampered", issue_number=2828,
                ),
                issued_at="2026-08-01T01:00:00Z",
                expires_at="2026-08-01T03:00:00Z",
            )

    def test_comment_body_is_content_bound(self):
        tampered = comment(101, OWNER_BODY + " tampered")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "body digest"):
            self.build(owner_comment=tampered)

    def test_single_authorization_can_be_revoked_without_a_ledger_digest_cycle(self):
        result = self.build()
        receipt_digest = AUTH.digest_bytes(AUTH.canonical_bytes(result) + b"\n")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "already revoked"):
            self.build(revocations=revocations([receipt_digest]))

    def test_shared_receipt_verifier_is_strict_and_revocation_aware(self):
        result = self.build()
        raw = AUTH.canonical_bytes(result) + b"\n"
        RECEIPT.verify(
            result, raw, policy(), revocations(), 123, "a" * 40,
            datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
        )

        tampered = dict(result)
        tampered["unexpected"] = True
        with self.assertRaisesRegex(RECEIPT.ReceiptError, "field set mismatch"):
            RECEIPT.verify(
                tampered, AUTH.canonical_bytes(tampered) + b"\n", policy(), revocations(),
                123, "a" * 40, datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
            )

        with self.assertRaisesRegex(RECEIPT.ReceiptError, "has been revoked"):
            RECEIPT.verify(
                result, raw, policy(), revocations([AUTH.digest_bytes(raw)]), 123,
                "a" * 40, datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
            )

        with self.assertRaisesRegex(RECEIPT.ReceiptError, "expired"):
            RECEIPT.verify(
                result, raw, policy(), revocations(), 123, "a" * 40,
                datetime(2026, 7, 15, 2, 0, 1, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
