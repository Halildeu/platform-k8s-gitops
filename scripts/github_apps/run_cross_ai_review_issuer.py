#!/usr/bin/env python3
"""Run one exact direct provider review and issue one signed review leaf."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    EvidenceVerifier,
    REVIEW_PAYLOAD_TYPE_V2,
)
from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_MODEL,
    DirectCodexRunner,
    EnvelopeSigner,
    ProviderExecutionReceipt,
    ProviderReviewIssuer,
    ReviewCoordinates,
)
from scripts.github_apps.cross_ai_deployment_policy.secureio import (
    load_private_json,
    read_private_text,
    write_private_json_exclusive,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now
from scripts.github_apps.cross_ai_deployment_policy.transit import VaultTransitSigner


REQUEST_FIELDS = {
    "schemaVersion",
    "reviewId",
    "reviewChainId",
    "subjectSha256",
    "round",
    "previousRoundSha256",
    "closureRootSha256",
    "issuedAt",
    "expiresAt",
}


class ReviewRunner(Protocol):
    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt: ...


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("openai",), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--trust-root-file", type=Path, required=True)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--revocations-file", type=Path, required=True)
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-token-file", type=Path, required=True)
    parser.add_argument("--vault-mount", required=True)
    parser.add_argument("--vault-key-name", required=True)
    parser.add_argument("--vault-key-version", type=int, required=True)
    parser.add_argument("--provider-executable", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _coordinates(value: dict[str, Any]) -> ReviewCoordinates:
    if set(value) != REQUEST_FIELDS or value.get("schemaVersion") != (
        "acik.cross-ai-review-issuance-request.v1"
    ):
        reject(
            "PROVIDER_REVIEW_REQUEST_INVALID",
            "review issuance request has missing or unknown fields",
        )
    try:
        coordinates = ReviewCoordinates(
            review_id=value["reviewId"],
            review_chain_id=value["reviewChainId"],
            subject_sha256=value["subjectSha256"],
            round=value["round"],
            previous_round_sha256=value["previousRoundSha256"],
            closure_root_sha256=value["closureRootSha256"],
            issued_at=value["issuedAt"],
            expires_at=value["expiresAt"],
        )
    except (KeyError, TypeError):
        reject("PROVIDER_REVIEW_REQUEST_INVALID", "review coordinates are invalid")
    ProviderReviewIssuer.validate_coordinates(coordinates)
    return coordinates


def _route(provider: str) -> dict[str, Any]:
    if provider != "openai":
        reject("PROVIDER_ROUTE_RETIRED", "active review accepts direct Codex only")
    return {
        "channel": "openai-codex",
        "direct": True,
        "model": CODEX_MODEL,
        "identity": "trusted-launch-attested",
        "issuer": "cross-ai-issuer-openai",
    }


def issue_review(
    args: argparse.Namespace,
    *,
    runner: ReviewRunner | None = None,
    signer: EnvelopeSigner | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if not 30 <= args.timeout_seconds <= 1200:
        reject("PROVIDER_TIMEOUT_INVALID", "provider timeout must be 30-1200 seconds")
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        reject("PROVIDER_WORKSPACE_INVALID", "provider workspace is not a directory")
    coordinates = _coordinates(
        load_private_json(
            args.request_file,
            label="review issuance request",
            maximum=64 * 1024,
        )
    )
    prompt = read_private_text(
        args.prompt_file,
        label="provider review prompt",
        maximum=512 * 1024,
    )
    trust_root = load_json_file(args.trust_root_file)
    revocations = load_json_file(args.revocations_file)
    route = _route(args.provider)
    active_signer = signer or VaultTransitSigner(
        vault_origin=args.vault_origin,
        token_file=args.vault_token_file,
        mount=args.vault_mount,
        key_name=args.vault_key_name,
        key_version=args.vault_key_version,
    )
    verifier = EvidenceVerifier(
        trust_root=trust_root,
        revocations_envelope=revocations,
        now=observed_at or utc_now(),
        expected_trust_root_sha256=args.expected_trust_root_sha256,
        expected_bundle_contract="v3",
    )
    trust_key = verifier.require_active_signing_key(
        key_id=active_signer.key_id,
        role="provider-review",
        provider_family=args.provider,
        issued_at=parse_utc(coordinates.issued_at, "review.issuedAt"),
    )
    expected_route = (
        (route["channel"],),
        (route["model"],),
        (route["identity"],),
        route["direct"],
    )
    if (
        trust_key.allowed_channels,
        trust_key.allowed_model_ids,
        trust_key.allowed_model_identity_classes,
        trust_key.direct_provider_cli,
    ) != expected_route:
        reject(
            "TRUST_SIGNER_BINDING_MISMATCH",
            "provider signer route differs from the fixed operational route",
        )
    selected_runner = runner
    if selected_runner is None:
        selected_runner = DirectCodexRunner(args.provider_executable)
    execution = selected_runner.run(
        prompt=prompt,
        model=route["model"],
        workspace=workspace,
        timeout_seconds=args.timeout_seconds,
    )
    envelope = ProviderReviewIssuer(
        signer=active_signer,
        provider_family=args.provider,
        channel=route["channel"],
        direct_provider_cli=route["direct"],
        model_identity_class=route["identity"],
        allowed_models=frozenset({route["model"]}),
        issuer=route["issuer"],
        contract_version="v2",
    ).issue(execution=execution, coordinates=coordinates)
    verified = verify_json_envelope(
        envelope,
        expected_payload_type=REVIEW_PAYLOAD_TYPE_V2,
        allowed_keys={trust_key.key_id: trust_key.public_key},
        required_key_ids={trust_key.key_id},
        exactly_one_signature=True,
    )
    write_private_json_exclusive(args.output, envelope)
    return {
        "schemaVersion": "acik.cross-ai-review-issuance-summary.v1",
        "providerFamily": args.provider,
        "modelId": verified.payload["modelId"],
        "modelIdentityClass": verified.payload["modelIdentityClass"],
        "reviewId": verified.payload["reviewId"],
        "verdict": verified.payload["verdict"],
        "reviewEnvelopeSha256": sha256_digest(envelope),
        "outputPathDisclosed": False,
    }


def main() -> int:
    try:
        sys.stdout.buffer.write(canonical_bytes(issue_review(parse_args())) + b"\n")
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
