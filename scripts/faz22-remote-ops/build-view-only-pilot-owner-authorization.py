#!/usr/bin/env python3
"""Build the bounded #2373 owner authorization without claiming legal clearance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from view_only_pilot_authorization_common import (
    CodexEvidenceError,
    canonical_bytes,
    canonical_receipt_bytes,
    digest_bytes,
    validate_codex_advisory_comment_timing,
    validate_codex_advisory_evidence,
)
from cross_ai_authority import AuthorityUnavailable, load_active_authority
from prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope


SCHEMA = "faz22.6-view-only-pilot-protected-authorization-v2"
POLICY_SCHEMA = "faz22.6-view-only-pilot-owner-policy-v2"
REVOCATION_SCHEMA = "faz22.6-view-only-pilot-authorization-revocations-v1"
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EXPECTED_REPOSITORY = "Halildeu/platform-k8s-gitops"
EXPECTED_ENVIRONMENT = "faz22-view-only-pilot"
LEGAL_ISSUE_REF = "https://github.com/Halildeu/platform-k8s-gitops/issues/2374"
EXPECTED_ADVISORY_PROVIDERS = [
    "OpenAI/gpt-5.6-sol",
]
ADVISORY_BINDING_POLICY_KEYS = {
    "baseTipSha", "baseSha", "headSha", "scopeSha256",
}


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


def verify_comment(comment: dict[str, Any], contract: dict[str, Any], label: str) -> str:
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
    if not str(comment.get("issue_url", "")).endswith("/issues/2373"):
        raise AuthorizationError(f"{label} is not bound to #2373")
    return body


def verify_runtime_advisory_comment(
    comment: dict[str, Any], expected_owner_login: str,
) -> tuple[str, dict[str, Any]]:
    comment_id = comment.get("id")
    ref = comment.get("html_url")
    expected_ref = (
        f"https://github.com/{EXPECTED_REPOSITORY}/issues/2373"
        f"#issuecomment-{comment_id}"
    )
    user = comment.get("user")
    body = comment.get("body")
    if not isinstance(comment_id, int) or comment_id < 1 or ref != expected_ref:
        raise AuthorizationError("aiAdvisory runtime comment identity mismatch")
    if comment.get("issue_url") != (
        f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/issues/2373"
    ):
        raise AuthorizationError("aiAdvisory is not bound to canonical #2373")
    if (
        not isinstance(user, dict)
        or user.get("login") != expected_owner_login
        or comment.get("author_association") != "OWNER"
    ):
        raise AuthorizationError("aiAdvisory runtime owner attribution mismatch")
    if not isinstance(body, str):
        raise AuthorizationError("aiAdvisory body is missing")
    return body, {
        "commentId": comment_id,
        "ref": ref,
        "bodySha256": digest_bytes(body.encode()),
        "authorLogin": expected_owner_login,
        "authorAssociation": "OWNER",
    }


def advisory_bindings_from_body(body: str) -> dict[str, str]:
    try:
        evidence = json.loads(body)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise AuthorizationError("Codex advisory evidence subject is unreadable") from exc
    subject = evidence.get("subject") if isinstance(evidence, dict) else None
    if not isinstance(subject, dict):
        raise AuthorizationError("Codex advisory evidence subject is missing")
    values = {
        "base_tip_sha": subject.get("baseTipSha"),
        "base_sha": subject.get("baseSha"),
        "head_sha": subject.get("headSha"),
    }
    scope = subject.get("scopeSha256")
    if any(
        not isinstance(value, str) or not GIT_SHA.fullmatch(value)
        for value in values.values()
    ):
        raise AuthorizationError("Codex advisory git binding is invalid")
    if not isinstance(scope, str) or not SHA256.fullmatch(scope):
        raise AuthorizationError("Codex advisory scope binding is invalid")
    values["scope_sha256"] = scope.removeprefix("sha256:")
    return values


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
    operator_sha256: str, device_sha256: str, expires_at: str, issued_at: str,
    run_id: int, head_sha: str, triggering_actor: str,
    *,
    advisory_scope_bytes: bytes,
    cross_ai_trust_root: dict[str, Any],
    cross_ai_revocations: dict[str, Any],
    expected_cross_ai_trust_root_sha256: str,
    codex_executable_policy: dict[str, Any],
) -> dict[str, Any]:
    require_keys(policy, {"schemaVersion", "status", "ownerDirective", "aiAdvisory", "legalTracking", "scope", "authorization", "lifecycle"}, "owner policy")
    if policy["schemaVersion"] != POLICY_SCHEMA or policy["status"] != "tracked_pending":
        raise AuthorizationError("owner policy is not the stable Codex-only v2 constraint")
    if not isinstance(policy["ownerDirective"], dict) or not isinstance(
        policy["aiAdvisory"], dict
    ):
        raise AuthorizationError("owner/advisory policy entries are invalid")
    verify_comment(owner_comment, policy["ownerDirective"], "ownerDirective")
    require_keys(policy["aiAdvisory"], {"commentId", "ref", "bodySha256", "authorLogin", "authorAssociation", "advisoryOnly", "consensusVerdict", "providers", "provenanceClass", "providerCryptographicAttestation", "evidenceBinding", "maxAgeHours"}, "policy.aiAdvisory")
    advisory_policy = policy["aiAdvisory"]
    advisory_binding = advisory_policy["evidenceBinding"]
    if not isinstance(advisory_binding, dict):
        raise AuthorizationError("Codex advisory policy binding template is missing")
    require_keys(
        advisory_binding, ADVISORY_BINDING_POLICY_KEYS,
        "policy.aiAdvisory.evidenceBinding",
    )
    if not (
        advisory_policy["advisoryOnly"] is True
        and advisory_policy["consensusVerdict"] == "PENDING"
        and all(
            advisory_policy[field] is None
            for field in (
                "commentId", "ref", "bodySha256", "authorLogin",
                "authorAssociation",
            )
        )
        and all(value is None for value in advisory_binding.values())
    ):
        raise AuthorizationError("Codex advisory policy must remain a stable pending template")
    providers = advisory_policy["providers"]
    if providers != EXPECTED_ADVISORY_PROVIDERS:
        raise AuthorizationError("AI advisory provider is not exact Codex-only SOL")
    if (
        advisory_policy["provenanceClass"] != "signed-direct-codex-launch-attested-v3"
        or advisory_policy["providerCryptographicAttestation"] is not True
    ):
        raise AuthorizationError("AI advisory provenance boundary is not explicit")
    advisory_body, advisory_transport = verify_runtime_advisory_comment(
        advisory_comment, policy["ownerDirective"]["authorLogin"],
    )
    expected_advisory_bindings = advisory_bindings_from_body(advisory_body)
    if not isinstance(head_sha, str) or not GIT_SHA.fullmatch(head_sha):
        raise AuthorizationError("authorization run identity is invalid")
    if head_sha != expected_advisory_bindings["head_sha"]:
        raise AuthorizationError(
            "authorization head does not match Codex advisory head binding"
        )
    require_keys(policy["lifecycle"], {"validFrom", "validUntil"}, "policy.lifecycle")
    valid_from = parse_utc(policy["lifecycle"]["validFrom"], "policy validFrom")
    valid_until = parse_utc(policy["lifecycle"]["validUntil"], "policy validUntil")
    issued = parse_utc(issued_at, "issuedAt")
    expires = parse_utc(expires_at, "expiresAt")
    if not valid_from <= issued < expires <= valid_until:
        raise AuthorizationError("authorization is outside owner-policy lifecycle")
    try:
        validate_codex_advisory_evidence(
            advisory_body,
            expected_advisory_bindings,
            scope_bytes=advisory_scope_bytes,
            trust_root=cross_ai_trust_root,
            revocations_envelope=cross_ai_revocations,
            expected_trust_root_sha256=expected_cross_ai_trust_root_sha256,
            codex_executable_policy=codex_executable_policy,
            reference_time=issued,
        )
    except CodexEvidenceError as exc:
        raise AuthorizationError(f"Codex-only AI advisory evidence is invalid: {exc}") from exc

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

    require_keys(policy["authorization"], {"protectedEnvironment", "requirePreventSelfReview", "maxTtlMinutes", "killSwitchWorkflowRef", "revocationLedgerRef"}, "policy.authorization")
    auth_policy = policy["authorization"]
    if auth_policy["protectedEnvironment"] != EXPECTED_ENVIRONMENT or auth_policy["requirePreventSelfReview"] is not True:
        raise AuthorizationError("protected environment policy is invalid")
    if auth_policy["maxTtlMinutes"] != 120:
        raise AuthorizationError("owner policy max TTL must be 120 minutes")
    if auth_policy["killSwitchWorkflowRef"] != ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback":
        raise AuthorizationError("kill-switch workflow ref mismatch")
    if auth_policy["revocationLedgerRef"] != "config/faz22-6-view-only-pilot-authorization-revocations.v1.json":
        raise AuthorizationError("revocation ledger ref mismatch")
    reviewer_count, reviewer_set_sha256 = verify_environment(environment, True, triggering_actor)

    if (expires - issued).total_seconds() > auth_policy["maxTtlMinutes"] * 60:
        raise AuthorizationError("authorization exceeds the absolute TTL limit")
    try:
        validate_codex_advisory_comment_timing(
            advisory_comment, issued, advisory_policy["maxAgeHours"],
        )
    except CodexEvidenceError as exc:
        raise AuthorizationError(f"Codex-only AI advisory evidence is invalid: {exc}") from exc
    if run_id < 1:
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
        "exposureApprovedByProtectedEnvironment": True,
        "protectedEnvironmentPreventSelfReview": True,
        "protectedEnvironmentReviewerCount": reviewer_count,
        "protectedEnvironmentReviewerSetSha256": reviewer_set_sha256,
        "ownerPolicySha256": digest_bytes(canonical_bytes(policy)),
        "ownerDirectiveRef": policy["ownerDirective"]["ref"],
        "ownerDirectiveSha256": policy["ownerDirective"]["bodySha256"],
        "aiAdvisoryOnly": True,
        "aiAdvisoryProvenanceClass": "signed-direct-codex-launch-attested-v3",
        "aiProviderCryptographicAttestation": True,
        "aiAdvisoryCommentId": advisory_transport["commentId"],
        "aiAdvisoryRef": advisory_transport["ref"],
        "aiAdvisorySha256": advisory_transport["bodySha256"],
        "aiAdvisoryBaseTipSha": expected_advisory_bindings["base_tip_sha"],
        "aiAdvisoryBaseSha": expected_advisory_bindings["base_sha"],
        "aiAdvisoryHeadSha": expected_advisory_bindings["head_sha"],
        "aiAdvisoryScopeSha256": expected_advisory_bindings["scope_sha256"],
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
        revocations, _ = load_object(args.revocations, "revocation ledger")
        repo_root = Path(__file__).resolve().parents[2]
        authority = load_active_authority(repo_root)
        advisory_body = advisory.get("body")
        if not isinstance(advisory_body, str):
            raise AuthorizationError("AI advisory comment body is missing")
        binding = advisory_bindings_from_body(advisory_body)
        if binding["head_sha"] != args.head_sha:
            raise AuthorizationError(
                "authorization head does not match Codex advisory head binding"
            )
        advisory_scope_bytes, _, _ = derive_scope(
            repo_root,
            base_tip_sha=binding["base_tip_sha"],
            base_sha=binding["base_sha"],
            head_sha=binding["head_sha"],
            max_scope_bytes=MAX_SCOPE_BYTES,
            scan_secrets=True,
        )
        if hashlib.sha256(advisory_scope_bytes).hexdigest() != binding["scope_sha256"]:
            raise AuthorizationError("canonical advisory scope digest mismatch")
        result = build_authorization(
            policy, owner, advisory, legal, environment, revocations,
            args.operator_sha256, args.device_sha256,
            args.expires_at, args.issued_at, args.run_id, args.head_sha,
            args.triggering_actor,
            advisory_scope_bytes=advisory_scope_bytes,
            cross_ai_trust_root=authority.trust_root,
            cross_ai_revocations=authority.revocations_envelope,
            expected_cross_ai_trust_root_sha256=authority.expected_trust_root_sha256,
            codex_executable_policy=authority.codex_executable_policy,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_receipt_bytes(result))
        print(f"authorization=pass schema={SCHEMA} output={args.output}")
        return 0
    except (AuthorityUnavailable, AuthorizationError, OSError, ValueError) as exc:
        print(f"authorization=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
