#!/usr/bin/env python3
"""Compose verified provider leaves into one signed v3 deployment bundle."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.github_apps.cross_ai_deployment_policy.canonical import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.coordinator import EvidenceCoordinator
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.provider import EnvelopeSigner
from scripts.github_apps.cross_ai_deployment_policy.secureio import (
    load_private_json,
    write_private_json_exclusive,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import utc_now
from scripts.github_apps.cross_ai_deployment_policy.transit import VaultTransitSigner


REQUEST_FIELDS = {
    "schemaVersion",
    "bundleId",
    "subject",
    "workflowStages",
    "runnerAdmissionLeaseEnvelope",
    "grant",
    "reviewEnvelopes",
    "closureEntries",
    "finalAgreeReviewSha256",
    "providerFamilies",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--trust-root-file", type=Path, required=True)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--revocations-file", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-token-file", type=Path, required=True)
    parser.add_argument("--vault-mount", required=True)
    parser.add_argument("--vault-key-name", required=True)
    parser.add_argument("--vault-key-version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _request(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != REQUEST_FIELDS or value.get("schemaVersion") != (
        "acik.cross-ai-evidence-coordination-request.v1"
    ):
        reject(
            "EVIDENCE_COORDINATION_REQUEST_INVALID",
            "coordination request has missing or unknown fields",
        )
    structural = {
        "subject": dict,
        "workflowStages": list,
        "runnerAdmissionLeaseEnvelope": dict,
        "grant": dict,
        "reviewEnvelopes": list,
        "closureEntries": list,
        "finalAgreeReviewSha256": list,
        "providerFamilies": list,
    }
    if any(not isinstance(value[field], expected) for field, expected in structural.items()):
        reject(
            "EVIDENCE_COORDINATION_REQUEST_INVALID",
            "coordination request contains invalid field types",
        )
    if not isinstance(value.get("bundleId"), str):
        reject("EVIDENCE_COORDINATION_REQUEST_INVALID", "bundleId is invalid")
    return value


def coordinate_bundle(
    args: argparse.Namespace,
    *,
    signer: EnvelopeSigner | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    request = _request(
        load_private_json(
            args.request_file,
            label="evidence coordination request",
            maximum=4 * 1024 * 1024,
        )
    )
    active_signer = signer or VaultTransitSigner(
        vault_origin=args.vault_origin,
        token_file=args.vault_token_file,
        mount=args.vault_mount,
        key_name=args.vault_key_name,
        key_version=args.vault_key_version,
    )
    coordinated = EvidenceCoordinator(
        signer=active_signer,
        trust_root=load_json_file(args.trust_root_file),
        revocations_envelope=load_json_file(args.revocations_file),
        expected_policy_sha256=args.expected_policy_sha256,
        expected_trust_root_sha256=args.expected_trust_root_sha256,
        bundle_contract_version="v3",
    ).coordinate(
        bundle_id=request["bundleId"],
        subject=request["subject"],
        workflow_stages=request["workflowStages"],
        runner_admission_lease_envelope=request["runnerAdmissionLeaseEnvelope"],
        grant=request["grant"],
        review_envelopes=request["reviewEnvelopes"],
        closure_entries=request["closureEntries"],
        final_agree_review_sha256=request["finalAgreeReviewSha256"],
        provider_families=request["providerFamilies"],
        now=observed_at or utc_now(),
    )
    write_private_json_exclusive(args.output, coordinated.envelope)
    return {
        "schemaVersion": "acik.cross-ai-evidence-coordination-summary.v1",
        "bundleId": coordinated.verified.bundle_id,
        "requestId": coordinated.verified.request_id,
        "subjectSha256": coordinated.verified.subject_digest,
        "bundleEnvelopeSha256": coordinated.verified.bundle_digest,
        "providerFamilies": list(coordinated.verified.provider_families),
        "outputPathDisclosed": False,
    }


def main() -> int:
    try:
        sys.stdout.buffer.write(canonical_bytes(coordinate_bundle(parse_args())) + b"\n")
        return 0
    except PolicyError as exc:
        sys.stdout.buffer.write(
            canonical_bytes(
                {
                    "error": exc.code,
                    "message": exc.message,
                    "automaticRetryAllowed": False,
                }
            )
            + b"\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
