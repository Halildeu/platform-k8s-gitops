#!/usr/bin/env python3
"""Build the bounded #2373 owner authorization without claiming legal clearance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from view_only_pilot_authorization_common import (
    canonical_bytes,
    canonical_receipt_bytes,
    digest_bytes,
)


SCHEMA = "faz22.6-view-only-pilot-protected-authorization-v3"
POLICY_SCHEMA = "faz22.6-view-only-pilot-owner-policy-v2"
REVOCATION_SCHEMA = "faz22.6-view-only-pilot-authorization-revocations-v1"
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EXPECTED_REPOSITORY = "Halildeu/platform-k8s-gitops"
EXPECTED_ENVIRONMENT = "faz22-view-only-pilot"
REQUIRED_REVIEWER_MODE = "required-reviewer"
TEMPORARY_AUTOMATION_MODE = "temporary-test-automation"
LEGAL_ISSUE_REF = "https://github.com/Halildeu/platform-k8s-gitops/issues/2374"
EXPECTED_ADVISORY_PROVIDERS = [
    "Anthropic/claude-opus-4-8",
    "OpenAI/gpt-5.6-sol",
]


class AuthorizationError(Exception):
    pass


def load_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorizationError(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise AuthorizationError(f"{label} must be a JSON object")
    return value, raw


def require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AuthorizationError(f"{label} field set mismatch")


def parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise AuthorizationError(f"{label} must be RFC3339 UTC without fractional seconds")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AuthorizationError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def verify_comment(
    comment: dict[str, Any], contract: dict[str, Any], label: str, issue_number: int,
) -> None:
    require_keys(
        contract,
        {"commentId", "ref", "bodySha256", "authorLogin", "authorAssociation"},
        f"policy.{label}",
    )
    if comment.get("id") != contract["commentId"]:
        raise AuthorizationError(f"{label} comment ID mismatch")
    if comment.get("html_url") != contract["ref"]:
        raise AuthorizationError(f"{label} comment ref mismatch")
    user = comment.get("user")
    if not isinstance(user, dict) or user.get("login") != contract["authorLogin"]:
        raise AuthorizationError(f"{label} author mismatch")
    if comment.get("author_association") != contract["authorAssociation"]:
        raise AuthorizationError(f"{label} author association mismatch")
    body = comment.get("body")
    if not isinstance(body, str):
        raise AuthorizationError(f"{label} body is missing")
    if digest_bytes(body.encode()) != contract["bodySha256"]:
        raise AuthorizationError(f"{label} body digest mismatch")
    if not str(comment.get("issue_url", "")).endswith(f"/issues/{issue_number}"):
        raise AuthorizationError(f"{label} is not bound to #{issue_number}")


def canonical_reviewer_set(
    environment: dict[str, Any], triggering_actor: str, require_prevent_self_review: bool,
) -> tuple[int, str]:
    if environment.get("name") != EXPECTED_ENVIRONMENT:
        raise AuthorizationError("protected environment name mismatch")
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        raise AuthorizationError("protected environment rules are missing")
    required = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"]
    if len(required) != 1:
        raise AuthorizationError("protected environment must have exactly one required-reviewers rule")
    reviewers = required[0].get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        raise AuthorizationError("protected environment must have at least one configured reviewer")
    if require_prevent_self_review and required[0].get("prevent_self_review") is not True:
        raise AuthorizationError("protected environment must prevent self review")
    identities = []
    for reviewer in reviewers:
        if not isinstance(reviewer, dict) or reviewer.get("type") not in {"User", "Team"}:
            raise AuthorizationError("protected environment reviewer entry is invalid")
        subject = reviewer.get("reviewer")
        if not isinstance(subject, dict) or not isinstance(subject.get("id"), int):
            raise AuthorizationError("protected environment reviewer identity is invalid")
        identity_name = subject.get("login") if reviewer["type"] == "User" else subject.get("slug")
        if not isinstance(identity_name, str) or not identity_name:
            raise AuthorizationError("protected environment reviewer name is invalid")
        if reviewer["type"] == "User" and identity_name.casefold() == triggering_actor.casefold():
            raise AuthorizationError("workflow triggering actor cannot be a protected environment reviewer")
        identities.append({"type": reviewer["type"], "id": subject["id"], "name": identity_name})
    identities.sort(key=lambda item: (item["type"], item["id"], item["name"]))
    return len(identities), digest_bytes(canonical_bytes(identities))


def verify_environment(
    environment: dict[str, Any], require_prevent_self_review: bool, triggering_actor: str,
) -> tuple[int, str]:
    if not isinstance(triggering_actor, str) or not triggering_actor:
        raise AuthorizationError("workflow triggering actor is missing")
    reviewer_count, reviewer_set_sha256 = canonical_reviewer_set(
        environment, triggering_actor, require_prevent_self_review,
    )
    return reviewer_count, reviewer_set_sha256


def verify_restoration(restoration: dict[str, Any]) -> tuple[int, str]:
    if not isinstance(restoration, dict):
        raise AuthorizationError("restoration contract is invalid")
    require_keys(
        restoration,
        {"reviewers", "preventSelfReview", "trackedBy", "trigger"},
        "policy.authorization.environmentApproval.restoration",
    )
    if restoration["preventSelfReview"] is not True:
        raise AuthorizationError("restoration must prevent self review")
    if restoration["trackedBy"] != "https://github.com/Halildeu/platform-k8s-gitops/issues/2502":
        raise AuthorizationError("restoration machine-gate tracker mismatch")
    if restoration["trigger"] != (
        "temporary-window-expiry-or-before-production-or-after-machine-gate-activation"
    ):
        raise AuthorizationError("restoration trigger mismatch")
    reviewers = restoration["reviewers"]
    if not isinstance(reviewers, list) or not reviewers:
        raise AuthorizationError("restoration reviewer set is absent")
    identities: list[dict[str, Any]] = []
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            raise AuthorizationError("restoration reviewer entry is invalid")
        require_keys(reviewer, {"type", "id", "name"}, "restoration reviewer")
        if (
            reviewer["type"] not in {"User", "Team"}
            or not isinstance(reviewer["id"], int)
            or reviewer["id"] < 1
            or not isinstance(reviewer["name"], str)
            or not reviewer["name"]
        ):
            raise AuthorizationError("restoration reviewer identity is invalid")
        identities.append(dict(reviewer))
    identities.sort(key=lambda item: (item["type"], item["id"], item["name"]))
    return len(identities), digest_bytes(canonical_bytes(identities))


def verify_legal_tracking_issue(issue: dict[str, Any], expected_ref: str) -> None:
    if expected_ref != LEGAL_ISSUE_REF:
        raise AuthorizationError("legal tracking ref must remain canonical #2374")
    if issue.get("number") != 2374 or issue.get("html_url") != expected_ref:
        raise AuthorizationError("legal tracking issue identity mismatch")
    if issue.get("state") != "open":
        raise AuthorizationError("legal tracking issue must remain open while tracked_pending")


def build_authorization(
    policy: dict[str, Any], owner_comment: dict[str, Any],
    advisory_comment: dict[str, Any], legal_issue: dict[str, Any],
    environment: dict[str, Any], revocations: dict[str, Any],
    temporary_automation_comment: dict[str, Any],
    operator_sha256: str, device_sha256: str, expires_at: str, issued_at: str,
    run_id: int, head_sha: str, triggering_actor: str,
) -> dict[str, Any]:
    require_keys(policy, {"schemaVersion", "status", "ownerDirective", "aiAdvisory", "legalTracking", "scope", "authorization", "lifecycle"}, "owner policy")
    if policy["schemaVersion"] != POLICY_SCHEMA or policy["status"] != "active":
        raise AuthorizationError("owner policy is not active v2")
    require_keys(policy["aiAdvisory"], {"commentId", "ref", "bodySha256", "authorLogin", "authorAssociation", "advisoryOnly", "consensusVerdict", "providers", "provenanceClass", "providerCryptographicAttestation"}, "policy.aiAdvisory")
    if policy["aiAdvisory"]["advisoryOnly"] is not True or policy["aiAdvisory"]["consensusVerdict"] != "AGREE":
        raise AuthorizationError("provider-distinct AI advisory consensus is not AGREE/advisory-only")
    providers = policy["aiAdvisory"]["providers"]
    if providers != EXPECTED_ADVISORY_PROVIDERS:
        raise AuthorizationError("AI advisory providers are not the reviewed provider-distinct pair")
    if (
        policy["aiAdvisory"]["provenanceClass"] != "owner-attested-provider-session"
        or policy["aiAdvisory"]["providerCryptographicAttestation"] is not False
    ):
        raise AuthorizationError("AI advisory provenance boundary is not explicit")
    verify_comment(owner_comment, policy["ownerDirective"], "ownerDirective", 2373)
    verify_comment(advisory_comment, {key: policy["aiAdvisory"][key] for key in ("commentId", "ref", "bodySha256", "authorLogin", "authorAssociation")}, "aiAdvisory", 2373)

    require_keys(policy["legalTracking"], {"ref", "status", "clearanceClaimed", "dependencyAcknowledgedBy", "dependencyRationaleCode"}, "policy.legalTracking")
    legal = policy["legalTracking"]
    if legal["status"] != "tracked_pending" or legal["clearanceClaimed"] is not False:
        raise AuthorizationError("legal track must remain tracked_pending without clearance")
    if legal["dependencyAcknowledgedBy"] != "owner" or legal["dependencyRationaleCode"] != "bounded-test-owner-risk-acceptance":
        raise AuthorizationError("legal dependency owner acknowledgement is invalid")
    verify_legal_tracking_issue(legal_issue, legal["ref"])

    expected_scope = {
        "environment": "test", "mode": "attended-view-only", "recordingMode": "disabled",
        "screenContentPersisted": False, "pilotAutoConsent": False,
        "attendedConsentRequired": True, "visibleIndicatorRequired": True,
        "localAbortRequired": True, "maxViewers": 1, "productionReady": False,
        "broadRolloutReady": False, "multiViewerFanoutProven": False,
    }
    if policy["scope"] != expected_scope:
        raise AuthorizationError("owner policy scope is not the bounded privacy-safe pilot")

    require_keys(policy["authorization"], {"protectedEnvironment", "environmentApproval", "maxTtlMinutes", "killSwitchWorkflowRef", "revocationLedgerRef"}, "policy.authorization")
    auth_policy = policy["authorization"]
    if auth_policy["protectedEnvironment"] != EXPECTED_ENVIRONMENT:
        raise AuthorizationError("protected environment policy is invalid")
    if auth_policy["maxTtlMinutes"] != 120:
        raise AuthorizationError("owner policy max TTL must be 120 minutes")
    if auth_policy["killSwitchWorkflowRef"] != ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback":
        raise AuthorizationError("kill-switch workflow ref mismatch")
    if auth_policy["revocationLedgerRef"] != "config/faz22-6-view-only-pilot-authorization-revocations.v1.json":
        raise AuthorizationError("revocation ledger ref mismatch")
    approval = auth_policy["environmentApproval"]
    if not isinstance(approval, dict):
        raise AuthorizationError("environment approval policy is invalid")
    require_keys(
        approval,
        {"activeMode", "requiredReviewer", "temporaryTestAutomation", "restoration"},
        "policy.authorization.environmentApproval",
    )
    required_reviewer = approval["requiredReviewer"]
    if not isinstance(required_reviewer, dict):
        raise AuthorizationError("required-reviewer policy is invalid")
    require_keys(required_reviewer, {"requirePreventSelfReview"}, "required-reviewer policy")
    if required_reviewer["requirePreventSelfReview"] is not True:
        raise AuthorizationError("required-reviewer mode must prevent self review")
    restoration_count, restoration_sha256 = verify_restoration(approval["restoration"])

    require_keys(policy["lifecycle"], {"validFrom", "validUntil"}, "policy.lifecycle")
    valid_from = parse_utc(policy["lifecycle"]["validFrom"], "policy validFrom")
    valid_until = parse_utc(policy["lifecycle"]["validUntil"], "policy validUntil")
    issued = parse_utc(issued_at, "issuedAt")
    expires = parse_utc(expires_at, "expiresAt")
    if not valid_from <= issued < expires <= valid_until:
        raise AuthorizationError("authorization is outside owner-policy lifecycle")
    if (expires - issued).total_seconds() > auth_policy["maxTtlMinutes"] * 60:
        raise AuthorizationError("authorization exceeds the absolute TTL limit")

    approval_mode = approval["activeMode"]
    temporary_approved = False
    temporary_ref: str | None = None
    temporary_sha256: str | None = None
    temporary_valid_until: str | None = None
    if approval_mode == REQUIRED_REVIEWER_MODE:
        reviewer_count, reviewer_set_sha256 = verify_environment(
            environment, True, triggering_actor,
        )
        protected_approved = True
        prevent_self_review = True
    elif approval_mode == TEMPORARY_AUTOMATION_MODE:
        temporary = approval["temporaryTestAutomation"]
        if not isinstance(temporary, dict):
            raise AuthorizationError("temporary TEST automation policy is invalid")
        require_keys(
            temporary,
            {"directive", "expectedLiveProtectionRules", "validFrom", "validUntil"},
            "temporary TEST automation policy",
        )
        if temporary["expectedLiveProtectionRules"] != []:
            raise AuthorizationError("temporary TEST automation must expect no protection rules")
        if environment.get("name") != EXPECTED_ENVIRONMENT:
            raise AuthorizationError("protected environment name mismatch")
        if environment.get("protection_rules") != []:
            raise AuthorizationError("temporary TEST automation requires an empty live protection rule set")
        verify_comment(
            temporary_automation_comment,
            temporary["directive"],
            "temporaryAutomationDirective",
            2828,
        )
        temporary_from = parse_utc(temporary["validFrom"], "temporary automation validFrom")
        temporary_until = parse_utc(temporary["validUntil"], "temporary automation validUntil")
        if not temporary_from <= issued < expires <= temporary_until:
            raise AuthorizationError("authorization is outside temporary TEST automation window")
        protected_approved = False
        prevent_self_review = False
        reviewer_count = 0
        reviewer_set_sha256 = digest_bytes(canonical_bytes([]))
        temporary_approved = True
        temporary_ref = temporary["directive"]["ref"]
        temporary_sha256 = temporary["directive"]["bodySha256"]
        temporary_valid_until = temporary["validUntil"]
    else:
        raise AuthorizationError("environment approval mode is unsupported")
    if run_id < 1 or not GIT_SHA.fullmatch(head_sha):
        raise AuthorizationError("authorization run identity is invalid")
    require_sha256(operator_sha256, "operatorSha256")
    require_sha256(device_sha256, "deviceSha256")
    if operator_sha256 == device_sha256:
        raise AuthorizationError("operator and device hashes must be distinct")

    require_keys(revocations, {"schemaVersion", "revokedAuthorizationSha256"}, "revocation ledger")
    if revocations["schemaVersion"] != REVOCATION_SCHEMA or not isinstance(revocations["revokedAuthorizationSha256"], list):
        raise AuthorizationError("revocation ledger is invalid")
    if any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in revocations["revokedAuthorizationSha256"]):
        raise AuthorizationError("revocation ledger contains an invalid digest")

    result = {
        "schemaVersion": SCHEMA,
        "minimumAcceptedAuthorizationSchema": SCHEMA,
        "environment": EXPECTED_ENVIRONMENT,
        "onePersonRoster": True,
        "operatorSha256": operator_sha256,
        "consentingPilotDevice": True,
        "deviceSha256": device_sha256,
        "environmentApprovalMode": approval_mode,
        "exposureApprovedByProtectedEnvironment": protected_approved,
        "temporaryTestAutomationApprovedByOwner": temporary_approved,
        "temporaryAutomationDirectiveRef": temporary_ref,
        "temporaryAutomationDirectiveSha256": temporary_sha256,
        "temporaryAutomationValidUntil": temporary_valid_until,
        "protectedEnvironmentPreventSelfReview": prevent_self_review,
        "protectedEnvironmentReviewerCount": reviewer_count,
        "protectedEnvironmentReviewerSetSha256": reviewer_set_sha256,
        "restorationPreventSelfReview": True,
        "restorationReviewerCount": restoration_count,
        "restorationReviewerSetSha256": restoration_sha256,
        "restorationTrackedBy": approval["restoration"]["trackedBy"],
        "ownerPolicySha256": digest_bytes(canonical_bytes(policy)),
        "ownerDirectiveRef": policy["ownerDirective"]["ref"],
        "ownerDirectiveSha256": policy["ownerDirective"]["bodySha256"],
        "aiAdvisoryOnly": True,
        "aiAdvisoryProvenanceClass": "owner-attested-provider-session",
        "aiProviderCryptographicAttestation": False,
        "aiAdvisoryRef": policy["aiAdvisory"]["ref"],
        "aiAdvisorySha256": policy["aiAdvisory"]["bodySha256"],
        "aiConsensusVerdict": "AGREE",
        "legalTrackingIssueRef": legal["ref"],
        "legalTrackStatus": "tracked_pending",
        "legalClearanceClaimed": False,
        "legalDependencyAcknowledgedBy": "owner",
        "legalDependencyRationaleCode": "bounded-test-owner-risk-acceptance",
        "recordingMode": "disabled",
        "screenContentPersisted": False,
        "attendedConsentRequired": True,
        "pilotAutoConsent": False,
        "visibleIndicatorRequired": True,
        "localAbortRequired": True,
        "killSwitchWorkflowRef": auth_policy["killSwitchWorkflowRef"],
        "revocationLedgerRef": auth_policy["revocationLedgerRef"],
        "issuedAt": issued_at,
        "expiresAt": expires_at,
        "authorizationRunId": run_id,
        "authorizationHeadSha": head_sha,
    }
    if digest_bytes(canonical_receipt_bytes(result)) in set(revocations["revokedAuthorizationSha256"]):
        raise AuthorizationError("new authorization is already revoked")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--owner-comment", required=True, type=Path)
    parser.add_argument("--advisory-comment", required=True, type=Path)
    parser.add_argument("--legal-issue", required=True, type=Path)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--temporary-automation-comment", required=True, type=Path)
    parser.add_argument("--revocations", required=True, type=Path)
    parser.add_argument("--operator-sha256", required=True)
    parser.add_argument("--device-sha256", required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--triggering-actor", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        policy, _ = load_object(args.policy, "owner policy")
        owner, _ = load_object(args.owner_comment, "owner directive comment")
        advisory, _ = load_object(args.advisory_comment, "AI advisory comment")
        legal, _ = load_object(args.legal_issue, "legal tracking issue")
        environment, _ = load_object(args.environment, "protected environment")
        temporary_comment, _ = load_object(
            args.temporary_automation_comment, "temporary automation directive comment",
        )
        revocations, _ = load_object(args.revocations, "revocation ledger")
        result = build_authorization(
            policy, owner, advisory, legal, environment, revocations, temporary_comment,
            args.operator_sha256, args.device_sha256,
            args.expires_at, args.issued_at, args.run_id, args.head_sha,
            args.triggering_actor,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_receipt_bytes(result))
        print(f"authorization=pass schema={SCHEMA} output={args.output}")
        return 0
    except (AuthorizationError, OSError, ValueError) as exc:
        print(f"authorization=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
