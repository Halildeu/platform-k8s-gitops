from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.ai.cross_ai_authority import PublicReviewAuthority
from scripts.ai.trusted_cross_ai_evidence import (
    build_prompt,
    build_subject,
    bytes_digest,
    expected_execution_arguments,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    REVOCATIONS_PAYLOAD_TYPE,
)
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_MODEL,
    CODEX_MODELS,
    REVIEW_RESULT_SCHEMA_VERSION,
    ProviderExecutionReceipt,
    ProviderReviewIssuer,
    ReviewCoordinates,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


AGREE_RESULT = json.dumps(
    {
        "schemaVersion": REVIEW_RESULT_SCHEMA_VERSION,
        "verdict": "AGREE",
        "findingIds": [],
        "resolvedFindingIds": [],
        "acknowledgedFindingIds": [],
    },
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)


class StaticSigner:
    def __init__(self, factory: FixtureFactory, key_id: str) -> None:
        self.factory = factory
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign_json_envelope(self, *, payload_type, payload):
        return self.factory.sign(payload_type, payload, self._key_id)


def capability_snapshot(model: str = CODEX_MODEL) -> dict[str, Any]:
    return {
        "schemaVersion": "acik.direct-codex-launch-attestation.v1",
        "channel": "openai-codex",
        "cliRealpathSha256": digest("codex-native-realpath"),
        "cliSha256": digest("codex-native-bytes"),
        "executableIdentityClass": "private-content-copy",
        "cliVersionSha256": digest("codex-version"),
        "liveModelCatalogSha256": digest("codex-model-catalog"),
        "requestedModel": model,
        "providerReportedModel": None,
        "reasoningEffort": "xhigh",
        "sandbox": "read-only",
        "ephemeral": True,
        "launchConfiguration": {
            "catalogArguments": ["debug", "models"],
            "executionArguments": expected_execution_arguments(model),
        },
    }


def execution_receipt(
    prompt: str, *, response: str = AGREE_RESULT, model: str = CODEX_MODEL,
) -> ProviderExecutionReceipt:
    capability = capability_snapshot(model)
    return ProviderExecutionReceipt(
        provider_family="openai",
        channel="openai-codex",
        direct_provider_cli=True,
        model_id=model,
        model_identity_class="trusted-launch-attested",
        reasoning_effort="xhigh",
        sandbox="read-only",
        ephemeral=True,
        provider_session_id="50000000-0000-4000-8000-000000000010",
        provider_transcript_sha256=digest("codex-json-event-transcript"),
        capability_snapshot=capability,
        capability_snapshot_sha256=sha256_digest(capability),
        input_sha256=bytes_digest(prompt.encode("utf-8")),
        output_sha256=bytes_digest(response.encode("utf-8")),
        result_text=response,
    )


@dataclass(frozen=True)
class SignedEvidenceFixture:
    factory: FixtureFactory
    authority: PublicReviewAuthority
    bindings: dict[str, str]
    scope_bytes: bytes
    prompt: str
    subject: dict[str, Any]
    evidence: dict[str, Any]


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_signed_evidence(
    *,
    base_tip_sha: str = "a" * 40,
    base_sha: str = "b" * 40,
    head_sha: str = "c" * 40,
    scope_bytes: bytes | None = None,
    reference_time: datetime | None = None,
    model: str = CODEX_MODEL,
) -> SignedEvidenceFixture:
    reference_time = (reference_time or datetime(
        2026, 7, 18, 20, 30, tzinfo=timezone.utc,
    )).astimezone(timezone.utc)
    factory = FixtureFactory("v2")
    trust_root = factory.trust_root()
    root_issued = reference_time - timedelta(days=1)
    root_expires = reference_time + timedelta(days=29)
    trust_root["issuedAt"] = _utc(root_issued)
    trust_root["expiresAt"] = _utc(root_expires)
    for key in trust_root["keys"]:
        key["notBefore"] = _utc(root_issued)
        key["notAfter"] = _utc(
            root_issued + timedelta(hours=168)
            if key["role"] == "provider-review"
            else root_expires
        )
    revocation_payload = {
        "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
        "revocationSetId": "20000000-0000-4000-8000-000000000001",
        "issuedAt": _utc(reference_time - timedelta(minutes=10)),
        "nextUpdate": _utc(reference_time + timedelta(minutes=50)),
        "entries": [],
    }
    revocations_envelope = factory.sign(
        REVOCATIONS_PAYLOAD_TYPE,
        revocation_payload,
        factory.REVOCATION_KEY_ID,
    )
    authority = PublicReviewAuthority(
        trust_root=trust_root,
        revocations_envelope=revocations_envelope,
        expected_trust_root_sha256=sha256_digest(trust_root),
    )
    scope_bytes = scope_bytes or (
        b"CROSS_AI_REVIEW_SCOPE_V1\n"
        b"Untrusted canonical test scope.\n"
        b"--- BEGIN UNTRUSTED GIT DIFF ---\n"
        b"diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n"
        b"--- END UNTRUSTED GIT DIFF ---\n"
    )
    bindings = {
        "base_tip_sha": base_tip_sha,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "scope_sha256": bytes_digest(scope_bytes).removeprefix("sha256:"),
    }
    prompt = build_prompt(
        base_tip_sha=bindings["base_tip_sha"],
        base_sha=bindings["base_sha"],
        head_sha=bindings["head_sha"],
        scope_sha256="sha256:" + bindings["scope_sha256"],
        scope_bytes=scope_bytes,
    )
    subject = build_subject(
        base_tip_sha=bindings["base_tip_sha"],
        base_sha=bindings["base_sha"],
        head_sha=bindings["head_sha"],
        scope_sha256="sha256:" + bindings["scope_sha256"],
        prompt=prompt,
    )
    receipt = execution_receipt(prompt, model=model)
    envelope = ProviderReviewIssuer(
        signer=StaticSigner(factory, factory.OPENAI_KEY_ID),
        provider_family="openai",
        channel="openai-codex",
        direct_provider_cli=True,
        model_identity_class="trusted-launch-attested",
        allowed_models=CODEX_MODELS,
        issuer="cross-ai-issuer-openai",
    ).issue(
        execution=receipt,
        coordinates=ReviewCoordinates(
            review_id="50000000-0000-4000-8000-000000000010",
            review_chain_id="40000000-0000-4000-8000-000000000010",
            subject_sha256=sha256_digest(subject),
            round=1,
            previous_round_sha256=None,
            closure_root_sha256=digest("standalone-closure"),
            issued_at=_utc(reference_time - timedelta(minutes=10)),
            expires_at=_utc(reference_time + timedelta(minutes=110)),
        ),
    )
    evidence = {
        "schema": "cross-ai-provider-evidence/v3",
        "subject": subject,
        "capability_snapshot": receipt.capability_snapshot,
        "response": receipt.result_text,
        "review_envelope": envelope,
        "review_envelope_sha256": sha256_digest(envelope),
        "trust_root_sha256": authority.expected_trust_root_sha256,
    }
    return SignedEvidenceFixture(
        factory=factory,
        authority=authority,
        bindings=bindings,
        scope_bytes=scope_bytes,
        prompt=prompt,
        subject=subject,
        evidence=evidence,
    )
