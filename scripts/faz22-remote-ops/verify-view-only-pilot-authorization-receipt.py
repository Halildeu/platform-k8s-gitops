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
POLICY_SCHEMA_V2 = "faz22.6-view-only-pilot-owner-policy-v2"
LEGACY_POLICY_SCHEMA_V1 = "faz22.6-view-only-pilot-owner-policy-v1"
LEGACY_POLICY_CANONICAL_SHA256 = "sha256:6da9283282902ba9bd35df2b730e05eeff5254734b83fb994f7e7c3908fef265"
LEGACY_V1_ISSUANCE_CUTOFF = datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc)
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
CURRENT_V2_ADVISORY_BINDING_FIELDS = {
    "aiAdvisoryCommentId", "aiAdvisoryBaseTipSha", "aiAdvisoryBaseSha",
    "aiAdvisoryHeadSha", "aiAdvisoryScopeSha256",
}
RAW_SHA256 = re.compile(r"^[a-f0-9]{64}$")


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
    now: datetime, allow_legacy_v1: bool = False,
    activation_run_created_at: datetime | None = None,
    activation_run_started_at: datetime | None = None,
) -> None:
    policy_schema = policy.get("schemaVersion")
    legacy_v1 = policy_schema == LEGACY_POLICY_SCHEMA_V1
    expected_fields = (
        EXPECTED_FIELDS if legacy_v1
        else EXPECTED_FIELDS | CURRENT_V2_ADVISORY_BINDING_FIELDS
    )
    if set(receipt) != expected_fields:
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
    if legacy_v1 and not allow_legacy_v1:
        raise ReceiptError("legacy v1 policy is forbidden for this verification mode")
    expected_provenance = (
        "owner-attested-provider-session"
        if legacy_v1 else "signed-direct-codex-launch-attested-v3"
    )
    if not (
        receipt["environment"] == "faz22-view-only-pilot"
        and receipt["onePersonRoster"] is True
        and receipt["consentingPilotDevice"] is True
        and receipt["exposureApprovedByProtectedEnvironment"] is True
        and receipt["protectedEnvironmentPreventSelfReview"] is True
        and isinstance(receipt["protectedEnvironmentReviewerCount"], int)
        and receipt["protectedEnvironmentReviewerCount"] >= 1
        and receipt["aiAdvisoryOnly"] is True
        and receipt["aiAdvisoryProvenanceClass"] == expected_provenance
        and receipt["aiProviderCryptographicAttestation"] is (not legacy_v1)
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
    advisory = policy.get("aiAdvisory")
    if not isinstance(advisory, dict):
        raise ReceiptError("canonical owner policy advisory is missing")
    if legacy_v1:
        if (
            policy.get("status") != "active"
            or digest_bytes(canonical_bytes(policy)) != LEGACY_POLICY_CANONICAL_SHA256
            or advisory.get("providers")
            != ["Anthropic/claude-opus-4-8", "OpenAI/gpt-5.6-sol"]
            or advisory.get("consensusVerdict") != "AGREE"
            or advisory.get("provenanceClass") != "owner-attested-provider-session"
        ):
            raise ReceiptError("legacy v1 policy is not the immutable forensic contract")
    elif (
        policy_schema != POLICY_SCHEMA_V2
        or policy.get("status") != "tracked_pending"
        or advisory.get("providers") != ["OpenAI/gpt-5.6-sol"]
        or advisory.get("consensusVerdict") != "PENDING"
        or advisory.get("provenanceClass") != "signed-direct-codex-launch-attested-v3"
        or advisory.get("providerCryptographicAttestation") is not True
        or any(
            advisory.get(field) is not None
            for field in (
                "commentId", "ref", "bodySha256", "authorLogin",
                "authorAssociation",
            )
        )
        or not isinstance(advisory.get("evidenceBinding"), dict)
        or any(value is not None for value in advisory["evidenceBinding"].values())
    ):
        raise ReceiptError("canonical owner policy is not the stable Codex-only v2 constraint")
    policy_digest = digest_bytes(canonical_bytes(policy))
    if receipt["ownerPolicySha256"] != policy_digest:
        raise ReceiptError("canonical owner policy digest mismatch")
    if legacy_v1:
        for receipt_field, policy_field in (
            ("aiAdvisoryRef", "ref"),
            ("aiAdvisorySha256", "bodySha256"),
        ):
            if receipt[receipt_field] != advisory.get(policy_field):
                raise ReceiptError(
                    f"authorization {receipt_field} policy binding mismatch"
                )
    else:
        if (
            not isinstance(receipt["aiAdvisoryCommentId"], int)
            or receipt["aiAdvisoryCommentId"] < 1
            or receipt["aiAdvisoryRef"] != (
                "https://github.com/Halildeu/platform-k8s-gitops/issues/2373"
                f"#issuecomment-{receipt['aiAdvisoryCommentId']}"
            )
            or any(
                not isinstance(receipt[field], str)
                or not GIT_SHA.fullmatch(receipt[field])
                for field in (
                    "aiAdvisoryBaseTipSha", "aiAdvisoryBaseSha",
                    "aiAdvisoryHeadSha",
                )
            )
            or receipt["aiAdvisoryHeadSha"] != expected_head_sha
            or not isinstance(receipt["aiAdvisoryScopeSha256"], str)
            or not RAW_SHA256.fullmatch(receipt["aiAdvisoryScopeSha256"])
        ):
            raise ReceiptError("authorization runtime advisory binding is invalid")
    owner = policy.get("ownerDirective")
    if not isinstance(owner, dict) or (
        receipt["ownerDirectiveRef"] != owner.get("ref")
        or receipt["ownerDirectiveSha256"] != owner.get("bodySha256")
    ):
        raise ReceiptError("authorization owner directive policy binding mismatch")
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
    if legacy_v1:
        if issued >= LEGACY_V1_ISSUANCE_CUTOFF:
            raise ReceiptError("legacy v1 authorization was issued at or after the migration cutoff")
        if activation_run_created_at is None or activation_run_started_at is None:
            raise ReceiptError("legacy v1 verification requires fetched activation run timestamps")
        if (
            activation_run_created_at >= LEGACY_V1_ISSUANCE_CUTOFF
            or activation_run_started_at >= LEGACY_V1_ISSUANCE_CUTOFF
        ):
            raise ReceiptError("legacy v1 activation run started at or after the migration cutoff")
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
    parser.add_argument(
        "--allow-legacy-v1", action="store_true",
        help="termination/forensic replay only; never authorizes new v1 issuance",
    )
    parser.add_argument("--activation-run-created-at")
    parser.add_argument("--activation-run-started-at")
    args = parser.parse_args()
    try:
        receipt_raw = args.receipt.read_bytes()
        receipt = load_object(args.receipt, "authorization receipt")
        policy = load_object(args.policy, "owner policy")
        revocations = load_object(args.revocations, "revocation ledger")
        activation_run_created_at = (
            parse_utc(args.activation_run_created_at, "activation run created_at")
            if args.activation_run_created_at is not None else None
        )
        activation_run_started_at = (
            parse_utc(args.activation_run_started_at, "activation run run_started_at")
            if args.activation_run_started_at is not None else None
        )
        verify(
            receipt, receipt_raw, policy, revocations, args.expected_run_id,
            args.expected_head_sha, datetime.now(timezone.utc), args.allow_legacy_v1,
            activation_run_created_at, activation_run_started_at,
        )
        print(f"authorization-receipt=pass schema={SCHEMA}")
        return 0
    except (OSError, ReceiptError) as exc:
        print(f"authorization-receipt=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
