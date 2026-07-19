#!/usr/bin/env python3
"""Produce #2373 operator evidence from independently verified GitHub artifacts."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import view_only_viewer_source_common as common


VERIFIER = common.VERIFIER


def fetch_operator_payload(client: object, repository: str, activation_run_id: int, head_sha: str) -> dict:
    run = VERIFIER.fetch_run(
        client, repository, activation_run_id,
        VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_NAME,
        VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_PATH,
        "protected activation",
    )
    VERIFIER.require_equal(run["head_sha"], head_sha, "protected activation head SHA")
    listing = client.get_json(
        f"/repos/{repository}/actions/runs/{activation_run_id}/artifacts?per_page=100"
    )
    expected_name = f"faz22-view-only-pilot-protected-authorization-{activation_run_id}"
    matches = [
        item for item in listing.get("artifacts", [])
        if isinstance(item, dict) and item.get("name") == expected_name and item.get("expired") is False
    ]
    if len(matches) != 1:
        raise VERIFIER.EvidenceError("protected authorization artifact identity is not unique")
    artifact = matches[0]
    if not isinstance(artifact.get("digest"), str) or not VERIFIER.SHA256.fullmatch(artifact["digest"]):
        raise VERIFIER.EvidenceError("protected authorization artifact digest is invalid")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != activation_run_id:
        raise VERIFIER.EvidenceError("protected authorization artifact run binding is invalid")
    raw_archive = client.get_bytes(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
    VERIFIER.require_equal(
        VERIFIER.digest_bytes(raw_archive), artifact["digest"], "protected authorization archive digest"
    )
    files = VERIFIER.safe_archive_files(raw_archive)
    expected_files = {
        "SHA256SUMS",
        "advisory-comment.json",
        "owner-comment.json",
        "protected-authorization.json",
    }
    if set(files) != expected_files:
        raise VERIFIER.EvidenceError("protected authorization artifact file set mismatch")
    VERIFIER.verify_sha256sums(files, expected_files - {"SHA256SUMS"})
    authorization = VERIFIER.load_json_bytes(
        files["protected-authorization.json"], "protected-authorization.json"
    )
    if authorization.get("schemaVersion") != VERIFIER.AUTHORIZATION_SCHEMA:
        raise VERIFIER.EvidenceError("protected authorization is not the minimum accepted v2 schema")
    if not (
        authorization.get("legalTrackStatus") == "tracked_pending"
        and authorization.get("legalClearanceClaimed") is False
        and authorization.get("aiAdvisoryOnly") is True
    ):
        raise VERIFIER.EvidenceError("protected authorization legal/AI boundary is invalid")
    return {
        "onePersonRoster": authorization.get("onePersonRoster"),
        "pilotDeviceConsented": authorization.get("consentingPilotDevice"),
        "exposureApproved": authorization.get("exposureApprovedByProtectedEnvironment"),
        "protectedEnvironment": authorization.get("environment"),
        "activationRunId": activation_run_id,
        "activationRunAttempt": run["run_attempt"],
        "activationHeadSha": run["head_sha"],
        "activationActorLogin": run["actor"]["login"],
        "activationCreatedAt": run["created_at"],
        "activationRunStartedAt": run["run_started_at"],
        "activationUpdatedAt": run["updated_at"],
        "authorizationArtifactId": artifact["id"],
        "authorizationArtifactDigest": artifact["digest"],
        "authorizationSha256": VERIFIER.digest_bytes(files["protected-authorization.json"]),
        "authorizationCarrierBase64": base64.b64encode(
            files["protected-authorization.json"]
        ).decode("ascii"),
        "advisoryCommentCarrierBase64": base64.b64encode(
            files["advisory-comment.json"]
        ).decode("ascii"),
        "ownerDirectiveCarrierBase64": base64.b64encode(
            files["owner-comment.json"]
        ).decode("ascii"),
        "authorizationSchemaVersion": authorization["schemaVersion"],
        "ownerPolicySha256": authorization["ownerPolicySha256"],
        "ownerDirectiveSha256": authorization["ownerDirectiveSha256"],
        "aiAdvisorySha256": authorization["aiAdvisorySha256"],
        "legalTrackStatus": authorization["legalTrackStatus"],
        "legalClearanceClaimed": authorization["legalClearanceClaimed"],
    }


def produce(
    client: object,
    repository: str,
    browser_run_id: int,
    activation_run_id: int,
    head_sha: str,
    *,
    advisory_scope_bytes: bytes | None,
    cross_ai_trust_root: dict,
    cross_ai_revocations: dict,
    expected_cross_ai_trust_root_sha256: str,
    codex_executable_policy: dict,
    issuer_runtime_policy: dict,
    authority_observed_at: datetime | None = None,
    authority_repo_root: Path | None = None,
) -> dict:
    if repository != VERIFIER.EXPECTED_REPOSITORY:
        raise VERIFIER.EvidenceError(f"repository must be exactly {VERIFIER.EXPECTED_REPOSITORY}")
    if browser_run_id < 1 or activation_run_id < 1 or browser_run_id == activation_run_id:
        raise VERIFIER.EvidenceError("browser and activation run IDs must be distinct positive integers")
    if not VERIFIER.re.fullmatch(r"[a-f0-9]{40}", head_sha):
        raise VERIFIER.EvidenceError("head SHA is invalid")
    browser = common.fetch_browser_child(client, repository, browser_run_id, head_sha)
    payload = fetch_operator_payload(client, repository, activation_run_id, head_sha)
    pilot_started = VERIFIER.parse_utc(browser["payload"]["pilotStartedAt"], "browser pilot start")
    pilot_ended = VERIFIER.parse_utc(browser["payload"]["pilotEndedAt"], "browser pilot end")
    VERIFIER.verify_activation_authorization(
        client, payload, head_sha, browser["binding"], pilot_started, pilot_ended,
        advisory_scope_bytes=advisory_scope_bytes,
        cross_ai_trust_root=cross_ai_trust_root,
        cross_ai_revocations=cross_ai_revocations,
        expected_cross_ai_trust_root_sha256=(
            expected_cross_ai_trust_root_sha256
        ),
        codex_executable_policy=codex_executable_policy,
        issuer_runtime_policy=issuer_runtime_policy,
        authority_observed_at=(
            authority_observed_at or datetime.now(timezone.utc)
        ),
        authority_repo_root=authority_repo_root,
    )
    child = {
        "schemaVersion": "faz22.6.viewOnlyViewerProductChildEvidence.v2",
        "evidenceType": "operator",
        "sourceRevision": head_sha,
        "observedAt": browser["payload"]["pilotStartedAt"],
        "binding": browser["binding"],
        "producer": {
            "kind": "protected-authorization",
            "tool": "scripts/faz22-remote-ops/produce-view-only-viewer-operator-evidence.py",
            "toolVersion": "v2",
        },
        "payload": payload,
    }
    VERIFIER.validate_schema(child, VERIFIER.CHILD_SCHEMA, "operator child")
    if VERIFIER.scan_hygiene(child):
        raise VERIFIER.EvidenceError("operator child evidence hygiene failed")
    return child


def load_current_authority_inputs() -> tuple[dict, dict, str, dict, dict]:
    authority = VERIFIER.load_active_authority(VERIFIER.ROOT)
    return (
        authority.trust_root,
        authority.revocations_envelope,
        authority.expected_trust_root_sha256,
        authority.codex_executable_policy,
        authority.issuer_runtime_policy,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--browser-run-id", required=True, type=int)
    parser.add_argument("--activation-run-id", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()
    try:
        trust_root, revocations, expected_root, executable_policy, runtime_policy = (
            load_current_authority_inputs()
        )
        result = produce(
            VERIFIER.GitHubClient(os.environ.get(args.github_token_env, "")),
            args.repository, args.browser_run_id, args.activation_run_id, args.head_sha,
            advisory_scope_bytes=None,
            cross_ai_trust_root=trust_root,
            cross_ai_revocations=revocations,
            expected_cross_ai_trust_root_sha256=expected_root,
            codex_executable_policy=executable_policy,
            issuer_runtime_policy=runtime_policy,
            authority_repo_root=VERIFIER.ROOT,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (
        VERIFIER.AuthorityUnavailable,
        VERIFIER.EvidenceError,
        OSError,
        ValueError,
    ) as exc:
        print(f"operator_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
