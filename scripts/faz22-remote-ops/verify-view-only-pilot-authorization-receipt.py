#!/usr/bin/env python3
"""Fail closed on a #2373 bounded-pilot authorization receipt."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from view_only_pilot_authorization_common import canonical_bytes, digest_bytes


SCHEMA = "faz22.6-view-only-pilot-protected-authorization-v2"
POLICY_SCHEMA = "faz22.6-view-only-pilot-owner-policy-v1"
REVOCATION_SCHEMA = "faz22.6-view-only-pilot-authorization-revocations-v1"
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
EXPECTED_FIELDS = {
    "schemaVersion", "minimumAcceptedAuthorizationSchema", "environment",
    "onePersonRoster", "operatorSha256", "consentingPilotDevice", "deviceSha256",
    "exposureApprovedByProtectedEnvironment", "protectedEnvironmentPreventSelfReview",
    "protectedEnvironmentReviewerCount", "protectedEnvironmentReviewerSetSha256",
    "ownerPolicySha256", "ownerDirectiveRef", "ownerDirectiveSha256",
    "aiAdvisoryOnly", "aiAdvisoryProvenanceClass", "aiProviderCryptographicAttestation",
    "aiAdvisoryRef", "aiAdvisorySha256", "aiConsensusVerdict",
    "legalTrackingIssueRef", "legalTrackStatus", "legalClearanceClaimed",
    "legalDependencyAcknowledgedBy", "legalDependencyRationaleCode", "recordingMode",
    "screenContentPersisted", "attendedConsentRequired", "pilotAutoConsent",
    "visibleIndicatorRequired", "localAbortRequired", "killSwitchWorkflowRef",
    "revocationLedgerRef", "issuedAt", "expiresAt", "authorizationRunId",
    "authorizationHeadSha",
}


class ReceiptError(Exception):
    pass


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise ReceiptError(f"{label} must be a JSON object")
    return value


def parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReceiptError(f"{label} is missing")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ReceiptError(f"{label} must be RFC3339 UTC without fractional seconds") from exc
    return parsed


def verify(
    receipt: dict[str, Any], receipt_raw: bytes, policy: dict[str, Any],
    revocations: dict[str, Any], expected_run_id: int, expected_head_sha: str,
    now: datetime,
) -> None:
    if set(receipt) != EXPECTED_FIELDS:
        raise ReceiptError("authorization receipt field set mismatch")
    if receipt["schemaVersion"] != SCHEMA or receipt["minimumAcceptedAuthorizationSchema"] != SCHEMA:
        raise ReceiptError("authorization receipt is not strict v2")
    if receipt["authorizationRunId"] != expected_run_id:
        raise ReceiptError("authorization run binding mismatch")
    if not GIT_SHA.fullmatch(expected_head_sha) or receipt["authorizationHeadSha"] != expected_head_sha:
        raise ReceiptError("authorization head SHA binding mismatch")
    for field in (
        "operatorSha256", "deviceSha256", "protectedEnvironmentReviewerSetSha256",
        "ownerPolicySha256", "ownerDirectiveSha256", "aiAdvisorySha256",
    ):
        if not isinstance(receipt[field], str) or not SHA256.fullmatch(receipt[field]):
            raise ReceiptError(f"authorization {field} is invalid")
    if receipt["operatorSha256"] == receipt["deviceSha256"]:
        raise ReceiptError("authorization operator/device bindings are not distinct")
    if not (
        receipt["environment"] == "faz22-view-only-pilot"
        and receipt["onePersonRoster"] is True
        and receipt["consentingPilotDevice"] is True
        and receipt["exposureApprovedByProtectedEnvironment"] is True
        and receipt["protectedEnvironmentPreventSelfReview"] is True
        and isinstance(receipt["protectedEnvironmentReviewerCount"], int)
        and receipt["protectedEnvironmentReviewerCount"] >= 1
        and receipt["aiAdvisoryOnly"] is True
        and receipt["aiAdvisoryProvenanceClass"] == "owner-attested-provider-session"
        and receipt["aiProviderCryptographicAttestation"] is False
        and receipt["aiConsensusVerdict"] == "AGREE"
        and receipt["legalTrackingIssueRef"] == "https://github.com/Halildeu/platform-k8s-gitops/issues/2374"
        and receipt["legalTrackStatus"] == "tracked_pending"
        and receipt["legalClearanceClaimed"] is False
        and receipt["recordingMode"] == "disabled"
        and receipt["screenContentPersisted"] is False
        and receipt["attendedConsentRequired"] is True
        and receipt["pilotAutoConsent"] is False
        and receipt["visibleIndicatorRequired"] is True
        and receipt["localAbortRequired"] is True
        and receipt["killSwitchWorkflowRef"] == ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback"
        and receipt["revocationLedgerRef"] == "config/faz22-6-view-only-pilot-authorization-revocations.v1.json"
    ):
        raise ReceiptError("authorization bounded privacy controls are invalid")
    if policy.get("schemaVersion") != POLICY_SCHEMA or policy.get("status") != "active":
        raise ReceiptError("canonical owner policy is not active v1")
    if receipt["ownerPolicySha256"] != digest_bytes(canonical_bytes(policy)):
        raise ReceiptError("canonical owner policy digest mismatch")
    if revocations.get("schemaVersion") != REVOCATION_SCHEMA:
        raise ReceiptError("authorization revocation ledger schema mismatch")
    revoked = revocations.get("revokedAuthorizationSha256")
    if not isinstance(revoked, list) or any(
        not isinstance(value, str) or not SHA256.fullmatch(value) for value in revoked
    ):
        raise ReceiptError("authorization revocation ledger entries are invalid")
    if digest_bytes(receipt_raw) in set(revoked):
        raise ReceiptError("authorization receipt has been revoked")
    issued = parse_utc(receipt["issuedAt"], "authorization issuedAt")
    expires = parse_utc(receipt["expiresAt"], "authorization expiresAt")
    if not issued < expires or (expires - issued).total_seconds() > 120 * 60:
        raise ReceiptError("authorization absolute TTL is invalid")
    if expires <= now:
        raise ReceiptError("authorization receipt is expired")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--revocations", required=True, type=Path)
    parser.add_argument("--expected-run-id", required=True, type=int)
    parser.add_argument("--expected-head-sha", required=True)
    args = parser.parse_args()
    try:
        receipt_raw = args.receipt.read_bytes()
        receipt = load_object(args.receipt, "authorization receipt")
        policy = load_object(args.policy, "owner policy")
        revocations = load_object(args.revocations, "revocation ledger")
        verify(
            receipt, receipt_raw, policy, revocations, args.expected_run_id,
            args.expected_head_sha, datetime.now(timezone.utc),
        )
        print(f"authorization-receipt=pass schema={SCHEMA}")
        return 0
    except (OSError, ReceiptError) as exc:
        print(f"authorization-receipt=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
