import importlib.util
import hashlib
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tests.ai.signed_evidence_fixture import make_signed_evidence

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
ADVISORY_BASE_TIP_SHA = "0" * 40
ADVISORY_BASE_SHA = "9" * 40
ADVISORY_HEAD_SHA = "a" * 40
ADVISORY_FIXTURE = make_signed_evidence(
    base_tip_sha=ADVISORY_BASE_TIP_SHA,
    base_sha=ADVISORY_BASE_SHA,
    head_sha=ADVISORY_HEAD_SHA,
    reference_time=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc),
)
ADVISORY_SCOPE_SHA256 = ADVISORY_FIXTURE.bindings["scope_sha256"]
ADVISORY_BODY = json.dumps(
    ADVISORY_FIXTURE.evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
)


def policy():
    return {
        "schemaVersion": AUTH.POLICY_SCHEMA,
        "status": "tracked_pending",
        "ownerDirective": {
            "commentId": 101,
            "ref": "https://github.com/Halildeu/platform-k8s-gitops/issues/2373#issuecomment-101",
            "bodySha256": AUTH.digest_bytes(OWNER_BODY.encode()),
            "authorLogin": "Halildeu",
            "authorAssociation": "OWNER",
        },
        "aiAdvisory": {
            "commentId": None,
            "ref": None,
            "bodySha256": None,
            "authorLogin": None,
            "authorAssociation": None,
            "advisoryOnly": True,
            "consensusVerdict": "PENDING",
            "providers": ["OpenAI/gpt-5.6-sol"],
            "provenanceClass": "signed-direct-codex-launch-attested-v3",
            "providerCryptographicAttestation": True,
            "evidenceBinding": {
                "baseTipSha": None,
                "baseSha": None,
                "headSha": None,
                "scopeSha256": None,
            },
            "maxAgeHours": 168,
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
            "requirePreventSelfReview": True,
            "maxTtlMinutes": 120,
            "killSwitchWorkflowRef": ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback",
            "revocationLedgerRef": "config/faz22-6-view-only-pilot-authorization-revocations.v1.json",
        },
        "lifecycle": {
            "validFrom": "2026-07-15T00:00:00Z",
            "validUntil": "2027-07-15T00:00:00Z",
        },
    }


def comment(
    comment_id, body, created_at="2026-07-15T00:00:00Z", updated_at=None,
):
    return {
        "id": comment_id,
        "html_url": f"https://github.com/Halildeu/platform-k8s-gitops/issues/2373#issuecomment-{comment_id}",
        "issue_url": "https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/2373",
        "author_association": "OWNER",
        "user": {"login": "Halildeu"},
        "body": body,
        "created_at": created_at,
        "updated_at": created_at if updated_at is None else updated_at,
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
    def test_canonical_v1_is_byte_immutable_and_v2_blocks_until_codex_evidence_is_bound(self):
        legacy_path = REPO_ROOT / "config/faz22-6-view-only-pilot-owner-policy.v1.json"
        legacy_raw = legacy_path.read_bytes()
        legacy = json.loads(legacy_raw)
        self.assertEqual("active", legacy["status"])
        self.assertEqual(
            "7b26a283d0af68451aaba6d9f4c39fba55bff201c4e697567f5db29206f0ae81",
            hashlib.sha256(legacy_raw).hexdigest(),
        )
        self.assertEqual(
            RECEIPT.LEGACY_POLICY_CANONICAL_SHA256,
            AUTH.digest_bytes(AUTH.canonical_bytes(legacy)),
        )
        policy_path = REPO_ROOT / "config/faz22-6-view-only-pilot-owner-policy.v2.json"
        canonical = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertEqual(
            AUTH.EXPECTED_ADVISORY_PROVIDERS,
            canonical["aiAdvisory"]["providers"],
        )
        self.assertEqual(AUTH.POLICY_SCHEMA, canonical["schemaVersion"])
        self.assertEqual("tracked_pending", canonical["status"])
        self.assertEqual("PENDING", canonical["aiAdvisory"]["consensusVerdict"])
        self.assertEqual(168, canonical["aiAdvisory"]["maxAgeHours"])
        self.assertTrue(
            all(value is None for value in canonical["aiAdvisory"]["evidenceBinding"].values())
        )
        self.assertTrue(
            all(
                canonical["aiAdvisory"][field] is None
                for field in (
                    "commentId", "ref", "bodySha256", "authorLogin",
                    "authorAssociation",
                )
            )
        )
        self.assertNotIn("MiniMax", json.dumps(canonical, sort_keys=True))
        self.assertNotIn("Anthropic", json.dumps(canonical, sort_keys=True))

    def build(self, **overrides):
        inputs = {
            "policy": policy(),
            "owner_comment": comment(101, OWNER_BODY),
            "advisory_comment": comment(102, ADVISORY_BODY),
            "legal_issue": legal_issue(),
            "environment": environment(),
            "revocations": revocations(),
            "operator_sha256": "sha256:" + "1" * 64,
            "device_sha256": "sha256:" + "2" * 64,
            "expires_at": "2026-07-15T02:00:00Z",
            "issued_at": "2026-07-15T00:00:00Z",
            "run_id": 123,
            "head_sha": "a" * 40,
            "triggering_actor": "workflow-operator",
            "advisory_scope_bytes": ADVISORY_FIXTURE.scope_bytes,
            "cross_ai_trust_root": ADVISORY_FIXTURE.authority.trust_root,
            "cross_ai_revocations": ADVISORY_FIXTURE.authority.revocations_envelope,
            "expected_cross_ai_trust_root_sha256": (
                ADVISORY_FIXTURE.authority.expected_trust_root_sha256
            ),
            "codex_executable_policy": (
                ADVISORY_FIXTURE.authority.codex_executable_policy
            ),
            "issuer_runtime_policy": (
                ADVISORY_FIXTURE.authority.issuer_runtime_policy
            ),
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
        value["status"] = "active"
        with self.assertRaisesRegex(AUTH.AuthorizationError, "stable Codex-only"):
            self.build(policy=value)

        value = policy()
        value["aiAdvisory"]["consensusVerdict"] = "REVISE"
        with self.assertRaisesRegex(AUTH.AuthorizationError, "stable pending template"):
            self.build(policy=value)

        value = policy()
        value["legalTracking"]["clearanceClaimed"] = True
        with self.assertRaisesRegex(AUTH.AuthorizationError, "tracked_pending"):
            self.build(policy=value)

    def test_retired_provider_or_non_evidence_advisory_cannot_issue_new_authorization(self):
        value = policy()
        value["aiAdvisory"]["providers"] = [
            "Anthropic/claude-opus-4-8",
            "OpenAI/gpt-5.6-sol",
        ]
        with self.assertRaisesRegex(AUTH.AuthorizationError, "Codex-only SOL"):
            self.build(policy=value)

        bad_comment = comment(102, "P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "evidence subject"):
            self.build(advisory_comment=bad_comment)

        downgraded = json.loads(ADVISORY_BODY)
        downgraded["capability_snapshot"]["requestedModel"] = "gpt-5.3-codex-spark"
        downgraded_body = json.dumps(downgraded, separators=(",", ":"))
        downgraded_comment = comment(102, downgraded_body)
        with self.assertRaisesRegex(AUTH.AuthorizationError, "capability differs"):
            self.build(advisory_comment=downgraded_comment)

        immutable_v1 = json.loads(
            (REPO_ROOT / "config/faz22-6-view-only-pilot-owner-policy.v1.json").read_bytes()
        )
        with self.assertRaisesRegex(AUTH.AuthorizationError, "stable Codex-only v2"):
            self.build(policy=immutable_v1)

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

    def test_comment_body_is_content_bound(self):
        tampered = comment(101, OWNER_BODY + " tampered")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "body digest"):
            self.build(owner_comment=tampered)

    def test_advisory_expected_bindings_edit_and_freshness_fail_closed(self):
        with self.assertRaisesRegex(
            AUTH.AuthorizationError, "authorization head does not match Codex advisory"
        ):
            self.build(head_sha="b" * 40)

        value = policy()
        value["aiAdvisory"]["evidenceBinding"]["headSha"] = "3" * 40
        with self.assertRaisesRegex(AUTH.AuthorizationError, "stable pending template"):
            self.build(policy=value)

        edited = comment(
            102, ADVISORY_BODY, updated_at="2026-07-15T00:00:01Z",
        )
        with self.assertRaisesRegex(AUTH.AuthorizationError, "edited or has invalid timestamps"):
            self.build(advisory_comment=edited)

        stale = comment(102, ADVISORY_BODY, created_at="2026-07-07T23:59:59Z")
        with self.assertRaisesRegex(AUTH.AuthorizationError, "comment is stale"):
            self.build(advisory_comment=stale)

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

    def test_immutable_v1_receipt_is_forensic_only_and_can_transition_to_termination(self):
        legacy_policy = json.loads(
            (REPO_ROOT / "config/faz22-6-view-only-pilot-owner-policy.v1.json").read_bytes()
        )
        legacy = self.build()
        for field in RECEIPT.CURRENT_V2_ADVISORY_BINDING_FIELDS:
            legacy.pop(field)
        legacy["ownerPolicySha256"] = AUTH.digest_bytes(AUTH.canonical_bytes(legacy_policy))
        legacy["ownerDirectiveRef"] = legacy_policy["ownerDirective"]["ref"]
        legacy["ownerDirectiveSha256"] = legacy_policy["ownerDirective"]["bodySha256"]
        legacy["aiAdvisoryProvenanceClass"] = "owner-attested-provider-session"
        legacy["aiProviderCryptographicAttestation"] = False
        legacy["aiAdvisoryRef"] = legacy_policy["aiAdvisory"]["ref"]
        legacy["aiAdvisorySha256"] = legacy_policy["aiAdvisory"]["bodySha256"]
        raw = AUTH.canonical_bytes(legacy) + b"\n"

        with self.assertRaisesRegex(RECEIPT.ReceiptError, "forbidden"):
            RECEIPT.verify(
                legacy, raw, legacy_policy, revocations(), 123, "a" * 40,
                datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
            )
        RECEIPT.verify(
            legacy, raw, legacy_policy, revocations(), 123, "a" * 40,
            datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc), True,
            datetime(2026, 7, 14, 23, 59, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 23, 59, 1, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(RECEIPT.ReceiptError, "requires fetched activation run"):
            RECEIPT.verify(
                legacy, raw, legacy_policy, revocations(), 123, "a" * 40,
                datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc), True,
            )

        with self.assertRaisesRegex(RECEIPT.ReceiptError, "activation run started"):
            RECEIPT.verify(
                legacy, raw, legacy_policy, revocations(), 123, "a" * 40,
                datetime(2026, 7, 19, 0, 10, tzinfo=timezone.utc), True,
                datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 19, 0, 0, 1, tzinfo=timezone.utc),
            )

        current_legacy = dict(legacy)
        current_legacy["issuedAt"] = "2026-07-19T00:00:00Z"
        current_legacy["expiresAt"] = "2026-07-19T00:20:00Z"
        current_raw = AUTH.canonical_bytes(current_legacy) + b"\n"
        with self.assertRaisesRegex(RECEIPT.ReceiptError, "migration cutoff"):
            RECEIPT.verify(
                current_legacy, current_raw, legacy_policy, revocations(), 123,
                "a" * 40, datetime(2026, 7, 19, 0, 10, tzinfo=timezone.utc), True,
                datetime(2026, 7, 18, 23, 59, tzinfo=timezone.utc),
                datetime(2026, 7, 18, 23, 59, 1, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
