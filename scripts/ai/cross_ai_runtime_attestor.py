"""Client for the fixed-function provider-review runtime attestor.

The client owns only a short-lived, bounded session API authorization. The
remote workload owns the runner-management Transit capability, executes Codex
itself, persists the measured transcript in a session, and signs only a
provider leaf that matches that session. This process can therefore never
manufacture the second leaf.
"""

from __future__ import annotations

import hashlib
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from scripts.ai.cross_ai_runtime_authorization import (
    AUTH_AUDIENCE,
    load_runtime_authorization,
)
from scripts.ai.trusted_cross_ai_evidence import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.errors import reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import loads_json_bytes
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    ProviderExecutionReceipt,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc


SESSION_PATH = "/api/v1/cross-ai/provider-review-runtime/sessions"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DIGEST_FIELDS = {
    "providerTranscriptSha256",
    "capabilitySnapshotSha256",
    "inputSha256",
    "outputSha256",
}
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        reject("PROVIDER_RUNTIME_ATTESTOR_INVALID", f"{label} is invalid")
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError):
        reject("PROVIDER_RUNTIME_ATTESTOR_INVALID", f"{label} is invalid")
    if parsed != value:
        reject("PROVIDER_RUNTIME_ATTESTOR_INVALID", f"{label} is not canonical")
    return parsed


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemoteRuntimeAttestor:
    """Two-step client for an independently measured provider execution."""

    def __init__(
        self,
        *,
        runtime_policy: dict[str, Any],
        auth_token_file: Path,
        opener: Any | None = None,
    ) -> None:
        required = {
            "schemaVersion",
            "workloadIdentity",
            "issuerImageDigest",
            "launcherSourceSha256",
            "attestorKeyId",
            "maxAttestationLifetimeSeconds",
            "apiOrigin",
            "sessionPath",
            "authAudience",
            "kubernetesNamespace",
            "kubernetesServiceAccount",
            "kubernetesContainerName",
            "kubernetesApiAudience",
            "kubernetesContainerCommand",
            "kubernetesContainerArgsSha256",
            "kubernetesContainerSecurityContextSha256",
            "vaultKubernetesAuthMount",
            "vaultKubernetesRole",
            "vaultTokenPolicy",
            "maxReplicas",
        }
        origin = runtime_policy.get("apiOrigin")
        parsed = urlsplit(origin) if isinstance(origin, str) else None
        if (
            set(runtime_policy) != required
            or runtime_policy.get("schemaVersion")
            != "acik.cross-ai-provider-review-runtime-policy.v1"
            or runtime_policy.get("maxAttestationLifetimeSeconds") != 600
            or parsed is None
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or runtime_policy.get("sessionPath") != SESSION_PATH
            or runtime_policy.get("authAudience") != AUTH_AUDIENCE
            or runtime_policy.get("maxReplicas") != 1
        ):
            reject(
                "PROVIDER_RUNTIME_POLICY_INVALID",
                "runtime attestor differs from the independently pinned policy",
            )
        self.runtime_policy = dict(runtime_policy)
        self._authorization = load_runtime_authorization(auth_token_file)
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self._session_id: str | None = None
        self._execution_sha256: str | None = None
        self._review_issued_at: str | None = None

    @property
    def request_id(self) -> str:
        return str(self._authorization.request["requestId"])

    @property
    def review_issued_at(self) -> str:
        if self._review_issued_at is None:
            reject(
                "PROVIDER_RUNTIME_SESSION_MISSING",
                "runtime review time is unavailable before execution",
            )
        return self._review_issued_at

    def _post(
        self,
        path: str,
        document: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self._authorization.assert_active()
        request = urllib.request.Request(
            self.runtime_policy["apiOrigin"] + path,
            data=canonical_bytes(document),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._authorization.token}",
                "Content-Type": "application/json",
                "User-Agent": "acik-cross-ai-provider-review-client/1",
            },
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise ValueError("runtime attestor rejected request")
                if hasattr(response, "geturl") and response.geturl() != request.full_url:
                    raise ValueError("runtime attestor redirected request")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("runtime attestor response is oversized")
            result = loads_json_bytes(
                raw,
                max_bytes=MAX_RESPONSE_BYTES,
                label="runtime attestor response",
            )
        except (
            OSError,
            UnicodeError,
            ValueError,
            urllib.error.URLError,
        ):
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_UNAVAILABLE",
                "fixed runtime attestor request failed",
            )
        if not isinstance(result, dict):
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_INVALID",
                "fixed runtime attestor response is invalid",
            )
        return result

    def execute(
        self,
        *,
        prompt: str,
        model: str,
        bindings: dict[str, str],
        subject_sha256: str,
        timeout_seconds: int,
    ) -> ProviderExecutionReceipt:
        if self._session_id is not None:
            reject(
                "PROVIDER_RUNTIME_SESSION_REUSED",
                "runtime attestor session can execute only once",
            )
        request = {
            "schemaVersion": "acik.cross-ai-provider-review-runtime-session-request.v1",
            "requestId": self._authorization.request["requestId"],
            "authAudience": self.runtime_policy["authAudience"],
            "baseTipSha": bindings["base_tip_sha"],
            "baseSha": bindings["base_sha"],
            "headSha": bindings["head_sha"],
            "scopeSha256": "sha256:" + bindings["scope_sha256"],
            "subjectSha256": subject_sha256,
            "prompt": prompt,
            "promptSha256": _bytes_digest(prompt.encode("utf-8")),
            "modelId": model,
            "reasoningEffort": "xhigh",
            "sandbox": "read-only",
            "ephemeral": True,
            "toolPolicy": "none-pre-execution",
            "timeoutSeconds": timeout_seconds,
        }
        self._authorization.assert_request(request)
        response = self._post(
            self.runtime_policy["sessionPath"],
            request,
            timeout_seconds=timeout_seconds + 120,
        )
        if (
            set(response)
            != {"schemaVersion", "sessionId", "execution", "reviewIssuedAt"}
            or response.get("schemaVersion")
            != "acik.cross-ai-provider-review-runtime-session-response.v1"
        ):
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_INVALID",
                "runtime attestor session response fields are invalid",
            )
        session_id = _canonical_uuid(response.get("sessionId"), "runtime session")
        review_issued_at = response.get("reviewIssuedAt")
        parse_utc(review_issued_at, "runtime.reviewIssuedAt")
        execution = response.get("execution")
        expected_fields = {
            "providerFamily",
            "channel",
            "directProviderCli",
            "modelId",
            "modelIdentityClass",
            "reasoningEffort",
            "sandbox",
            "ephemeral",
            "providerSessionId",
            "providerTranscriptSha256",
            "capabilitySnapshot",
            "capabilitySnapshotSha256",
            "inputSha256",
            "outputSha256",
            "resultText",
        }
        if not isinstance(execution, dict) or set(execution) != expected_fields:
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_INVALID",
                "runtime attestor execution response fields are invalid",
            )
        if any(
            not isinstance(execution[field], str)
            or DIGEST_RE.fullmatch(execution[field]) is None
            for field in DIGEST_FIELDS
        ):
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_INVALID",
                "runtime attestor execution digest is invalid",
            )
        receipt = ProviderExecutionReceipt(
            provider_family=execution["providerFamily"],
            channel=execution["channel"],
            direct_provider_cli=execution["directProviderCli"],
            model_id=execution["modelId"],
            model_identity_class=execution["modelIdentityClass"],
            reasoning_effort=execution["reasoningEffort"],
            sandbox=execution["sandbox"],
            ephemeral=execution["ephemeral"],
            provider_session_id=execution["providerSessionId"],
            provider_transcript_sha256=execution["providerTranscriptSha256"],
            capability_snapshot=execution["capabilitySnapshot"],
            capability_snapshot_sha256=execution["capabilitySnapshotSha256"],
            input_sha256=execution["inputSha256"],
            output_sha256=execution["outputSha256"],
            result_text=execution["resultText"],
        )
        if receipt.input_sha256 != _bytes_digest(prompt.encode("utf-8")):
            reject(
                "PROVIDER_RUNTIME_BINDING_MISMATCH",
                "runtime attestor execution does not bind the canonical prompt",
            )
        _canonical_uuid(receipt.provider_session_id, "provider session")
        self._session_id = session_id
        self._execution_sha256 = sha256_digest(execution)
        self._review_issued_at = review_issued_at
        return receipt

    def attest(
        self,
        *,
        provider_review_envelope: dict[str, Any],
        prompt_sha256: str,
        issued_at: str,
        expires_at: str,
    ) -> dict[str, Any]:
        if self._session_id is None or self._execution_sha256 is None:
            reject(
                "PROVIDER_RUNTIME_SESSION_MISSING",
                "runtime attestor session must execute before finalization",
            )
        response = self._post(
            f"{self.runtime_policy['sessionPath']}/{self._session_id}/attest",
            {
                "schemaVersion": "acik.cross-ai-provider-review-runtime-finalize-request.v1",
                "sessionId": self._session_id,
                "executionSha256": self._execution_sha256,
                "providerReviewEnvelope": provider_review_envelope,
                "providerReviewEnvelopeSha256": sha256_digest(provider_review_envelope),
                "promptSha256": prompt_sha256,
                "issuedAt": issued_at,
                "expiresAt": expires_at,
            },
            timeout_seconds=90,
        )
        if (
            set(response) != {"schemaVersion", "runtimeAttestationEnvelope"}
            or response.get("schemaVersion")
            != "acik.cross-ai-provider-review-runtime-finalize-response.v1"
            or not isinstance(response.get("runtimeAttestationEnvelope"), dict)
        ):
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_INVALID",
                "runtime attestor finalization response is invalid",
            )
        return response["runtimeAttestationEnvelope"]


__all__ = ["AUTH_AUDIENCE", "RemoteRuntimeAttestor", "SESSION_PATH"]
