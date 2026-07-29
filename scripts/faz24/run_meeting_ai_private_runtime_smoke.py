#!/usr/bin/env python3
"""Run the Faz 24 Meeting-AI private backend acceptance matrix.

The smoke is deliberately test-only. It reads the dedicated client secret from
Kubernetes into process memory, never forwards credentials through argv, and
writes metadata-only evidence. A synthetic analysis result can be persisted to
prove the canonical first-write/replay/conflict contract only when the operator
confirms that the supplied transcript finalization is synthetic. Each write
attempt obtains a fresh transcript-service analysis capability bound to the
exact producer-owned finalization occurrence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit


SCHEMA_VERSION = "faz24-meeting-ai-private-runtime-smoke.v2"
WRITE_PERMISSION = "meeting:analysis-result:write"
CAPABILITY_PERMISSION = "transcript:analysis-job-capability:issue"
CAPABILITY_HEADER = "x-analysis-job-capability"
CAPABILITY_EXPIRES_HEADER = "x-analysis-job-capability-expires-at"
DEFAULT_ANALYSIS_SPEC_VERSION = "meeting-intelligence-v1"
SAFE_ERROR_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TEST_CONTEXT = "k3d-test"
TEST_NAMESPACE = "platform-test"
MAX_HTTP_TIMEOUT_SECONDS = 10


class SmokeError(RuntimeError):
    """A redaction-safe smoke failure."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_test_target(context: str, namespace: str, timeout_seconds: int) -> None:
    if context != TEST_CONTEXT or namespace != TEST_NAMESPACE:
        raise SmokeError("refusing non-test context/namespace")
    if timeout_seconds < 1 or timeout_seconds > MAX_HTTP_TIMEOUT_SECONDS:
        raise SmokeError(
            f"timeout must be within 1..{MAX_HTTP_TIMEOUT_SECONDS} seconds"
        )


def _b64url_json(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(segment + padding)
        value = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SmokeError("service token payload is not valid base64url JSON") from exc
    if not isinstance(value, dict):
        raise SmokeError("service token payload must be a JSON object")
    return value


def _claim_list(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        result = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        result = value
    else:
        raise SmokeError(f"service token {name} claim has an invalid shape")
    return result


def summarize_and_validate_claims(
    token: str,
    now_epoch: int | None = None,
    *,
    expected_audience: str = "meeting-service",
    expected_permission: str = WRITE_PERMISSION,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise SmokeError("service token must be a compact three-part JWT")
    claims = _b64url_json(parts[1])
    audience = _claim_list(claims.get("aud"), "aud")
    permissions = _claim_list(claims.get("perm"), "perm")

    expected_scalars = {
        "iss": "auth-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "svc": "meeting-ai",
    }
    for name, expected in expected_scalars.items():
        if claims.get(name) != expected:
            raise SmokeError(f"service token {name} claim is not bound to {expected}")
    if audience != [expected_audience]:
        raise SmokeError(f"service token audience is not exactly {expected_audience}")
    if permissions != [expected_permission]:
        raise SmokeError("service token permission set is not least privilege")

    try:
        issued_at = int(claims["iat"])
        expires_at = int(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SmokeError("service token iat/exp claims are missing or invalid") from exc
    ttl_seconds = expires_at - issued_at
    if ttl_seconds <= 0 or ttl_seconds > 60:
        raise SmokeError("service token TTL is outside the 1..60 second boundary")
    effective_now = int(_utc_now().timestamp()) if now_epoch is None else now_epoch
    if expires_at <= effective_now:
        raise SmokeError("service token is already expired")

    return {
        "issuer": "auth-service",
        "subject": "meeting-ai",
        "clientId": "meeting-ai",
        "service": "meeting-ai",
        "audience": audience,
        "permissions": permissions,
        "ttlSeconds": ttl_seconds,
    }


def _parse_instant(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise SmokeError(f"analysis capability {name} claim is missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SmokeError(f"analysis capability {name} claim is missing or invalid") from exc
    if parsed.tzinfo is None:
        raise SmokeError(f"analysis capability {name} claim is missing or invalid")
    return parsed.astimezone(timezone.utc)


def summarize_and_validate_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    finalization_version: int,
    analysis_run_id: uuid.UUID,
    analysis_spec_version: str,
    expires_header: str,
    now_epoch: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        raise SmokeError("analysis capability must be a compact three-part JWT")
    claims = _b64url_json(parts[1])
    audience = _claim_list(claims.get("aud"), "aud")
    expected = {
        "iss": "transcript-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "perm": WRITE_PERMISSION,
        "tenant_id": str(tenant_id),
        "meeting_id": str(meeting_id),
        "session_id": str(session_id),
        "analysis_run_id": str(analysis_run_id),
        "analysis_spec_version": analysis_spec_version,
    }
    for name, value in expected.items():
        if claims.get(name) != value:
            raise SmokeError(f"analysis capability {name} claim is not exactly bound")
    if audience != ["meeting-service"]:
        raise SmokeError("analysis capability audience is not exactly meeting-service")
    try:
        capability_id = uuid.UUID(str(claims["jti"]))
        claim_finalization_version = int(claims["finalization_version"])
        expires_at = int(claims["exp"])
        issued_at = int(claims["iat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SmokeError("analysis capability identity/time claims are invalid") from exc
    if claim_finalization_version != finalization_version:
        raise SmokeError("analysis capability finalization_version claim is not exactly bound")
    ttl_seconds = expires_at - issued_at
    if ttl_seconds <= 0 or ttl_seconds > 300:
        raise SmokeError("analysis capability TTL is outside the 1..300 second boundary")
    effective_now = int(_utc_now().timestamp()) if now_epoch is None else now_epoch
    if expires_at <= effective_now:
        raise SmokeError("analysis capability is already expired")
    header_expiry = _parse_instant(expires_header, "expires header")
    if int(header_expiry.timestamp()) != expires_at:
        raise SmokeError("analysis capability expiry header does not match JWT exp")
    finalized_at_raw = claims.get("finalized_at")
    _parse_instant(finalized_at_raw, "finalized_at")
    transcript_sha256 = claims.get("transcript_sha256")
    if not isinstance(transcript_sha256, str) or not SHA256_RE.fullmatch(
        transcript_sha256
    ):
        raise SmokeError("analysis capability transcript_sha256 claim is invalid")
    binding = {
        "capabilityId": str(capability_id),
        "sessionId": str(session_id),
        "transcriptSha256": transcript_sha256,
        "finalizationVersion": finalization_version,
        "finalizedAt": finalized_at_raw,
        "analysisSpecVersion": analysis_spec_version,
    }
    summary = {
        "issuer": "transcript-service",
        "subject": "meeting-ai",
        "clientId": "meeting-ai",
        "audience": audience,
        "permission": WRITE_PERMISSION,
        "ttlSeconds": ttl_seconds,
        "exactTupleBound": True,
    }
    return binding, summary


def load_kubernetes_secret(
    context: str,
    namespace: str,
    secret_name: str,
    secret_key: str,
    timeout_seconds: int,
) -> str:
    command = [
        "kubectl",
        "--context",
        context,
        "-n",
        namespace,
        "get",
        "secret",
        secret_name,
        "-o",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeError("kubectl secret read could not be executed") from exc
    if result.returncode != 0:
        raise SmokeError(f"kubectl secret read failed with exit {result.returncode}")
    try:
        document = json.loads(result.stdout)
        encoded = document["data"][secret_key]
        raw = base64.b64decode(encoded, validate=True)
        secret = raw.decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeError("Kubernetes secret data is missing or malformed") from exc
    if len(secret) < 32 or "\n" in secret or "\r" in secret:
        raise SmokeError("Meeting-AI client secret does not satisfy the runtime shape")
    return secret


def http_request(
    base_url: str,
    host_header: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: int,
) -> HttpResult:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SmokeError("base URL must be an absolute HTTP(S) URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SmokeError("base URL must not contain a path, query, or fragment")
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(
        parsed.hostname,
        parsed.port,
        timeout=timeout_seconds,
    )
    request_headers = {"Host": host_header, **headers}
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read(1_048_576)
        response_headers = {
            name.lower(): value.strip() for name, value in response.getheaders()
        }
        return HttpResult(
            status=response.status,
            body=response_body,
            headers=response_headers,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise SmokeError("private runtime HTTP request failed") from exc
    finally:
        connection.close()


def _safe_error_code(body: bytes) -> str | None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    for key in ("code", "error"):
        candidate = value.get(key)
        if isinstance(candidate, str) and SAFE_ERROR_RE.fullmatch(candidate):
            return candidate
    return None


def _check(check_id: str, expected: int, result: HttpResult) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": check_id,
        "expectedStatus": expected,
        "actualStatus": result.status,
        "pass": result.status == expected,
        "responseBodySha256": hashlib.sha256(result.body).hexdigest(),
    }
    error_code = _safe_error_code(result.body)
    if error_code is not None:
        item["errorCode"] = error_code
    return item


def _basic(client_id: str, secret: str) -> str:
    raw = f"{client_id}:{secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _token_call(
    request: Callable[..., HttpResult],
    base_url: str,
    host_header: str,
    secret: str,
    audience: str,
    permissions: list[str],
    timeout_seconds: int,
) -> HttpResult:
    fields: list[tuple[str, str]] = [
        ("grant_type", "client_credentials"),
        ("audience", audience),
    ]
    fields.extend(("permissions", permission) for permission in permissions)
    return request(
        base_url,
        host_header,
        "POST",
        "/oauth2/token",
        {
            "Authorization": _basic("meeting-ai", secret),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        urlencode(fields).encode("ascii"),
        timeout_seconds,
    )


def _ingest_call(
    request: Callable[..., HttpResult],
    base_url: str,
    host_header: str,
    meeting_id: uuid.UUID,
    analysis_run_id: uuid.UUID,
    token: str | None,
    job_capability: str | None,
    body: bytes,
    timeout_seconds: int,
) -> HttpResult:
    headers = {
        "Idempotency-Key": str(analysis_run_id),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if job_capability is not None:
        headers["X-Analysis-Job-Capability"] = job_capability
    return request(
        base_url,
        host_header,
        "POST",
        f"/api/v1/internal/meetings/{meeting_id}/analysis-results",
        headers,
        body,
        timeout_seconds,
    )


def _capability_call(
    request: Callable[..., HttpResult],
    base_url: str,
    host_header: str,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    finalization_version: int,
    analysis_run_id: uuid.UUID,
    analysis_spec_version: str,
    token: str,
    timeout_seconds: int,
) -> HttpResult:
    return request(
        base_url,
        host_header,
        "POST",
        (
            f"/api/v1/internal/tenants/{tenant_id}/meetings/{meeting_id}"
            f"/sessions/{session_id}/finalizations/{finalization_version}"
            "/analysis-capability"
        ),
        {
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(tenant_id),
            "X-Analysis-Run-Id": str(analysis_run_id),
            "X-Analysis-Spec-Version": analysis_spec_version,
            "Accept": "application/json",
        },
        None,
        timeout_seconds,
    )


def _synthetic_body(meeting_id: uuid.UUID, binding: dict[str, Any]) -> bytes:
    payload = {
        "meeting_id": str(meeting_id),
        "transcript_session_id": binding["sessionId"],
        "transcript_sha256": binding["transcriptSha256"],
        "finalization_version": binding["finalizationVersion"],
        "finalized_at": binding["finalizedAt"],
        "analysis_spec_version": binding["analysisSpecVersion"],
        "analyzer_contract_version": "5-adr0043",
        "model": "runtime-smoke",
        "backend": "synthetic",
        "prompt_version": "acceptance-v1",
        "summary": "Synthetic Faz 24 acceptance result; no user transcript or PII.",
        "summary_grounding_status": "synthetic",
        "summary_citations": [],
        "citations": [],
        "rejected_claims": [],
        "ungrounded_count": 0,
        "redacted": True,
        "redaction_count": 0,
        "generated_at": _iso8601(_utc_now()),
        "decisions": [],
        "actions": [],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def run_smoke(
    *,
    context: str,
    namespace: str,
    secret_name: str,
    secret_key: str,
    base_url: str,
    host_header: str,
    meeting_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    finalization_version: int | None,
    analysis_run_id: uuid.UUID | None,
    analysis_spec_version: str,
    write_synthetic_result: bool,
    confirm_synthetic_finalization: bool,
    timeout_seconds: int,
    secret_loader: Callable[..., str] = load_kubernetes_secret,
    request: Callable[..., HttpResult] = http_request,
) -> tuple[dict[str, Any], bool]:
    validate_test_target(context, namespace, timeout_seconds)
    if write_synthetic_result:
        if not confirm_synthetic_finalization:
            raise SmokeError(
                "synthetic write requires --confirm-synthetic-finalization"
            )
        if (
            tenant_id is None
            or session_id is None
            or finalization_version is None
            or analysis_run_id is None
        ):
            raise SmokeError(
                "synthetic write requires tenant/session/finalization/analysis-run tuple"
            )
        if finalization_version < 1:
            raise SmokeError("finalization version must be positive")
        if (
            not analysis_spec_version
            or len(analysis_spec_version) > 64
            or not SAFE_ERROR_RE.fullmatch(analysis_spec_version)
        ):
            raise SmokeError("analysis spec version has an invalid shape")
    secret = secret_loader(context, namespace, secret_name, secret_key, timeout_seconds)
    checks: list[dict[str, Any]] = []
    invalid_secret = "invalid-" + uuid.uuid4().hex

    checks.append(
        _check(
            "token-wrong-secret",
            401,
            _token_call(
                request,
                base_url,
                host_header,
                invalid_secret,
                "meeting-service",
                [WRITE_PERMISSION],
                timeout_seconds,
            ),
        )
    )
    checks.append(
        _check(
            "token-wrong-audience",
            400,
            _token_call(
                request,
                base_url,
                host_header,
                secret,
                "not-allowed",
                [WRITE_PERMISSION],
                timeout_seconds,
            ),
        )
    )
    checks.append(
        _check(
            "token-wrong-permission",
            400,
            _token_call(
                request,
                base_url,
                host_header,
                secret,
                "meeting-service",
                ["permissions:write"],
                timeout_seconds,
            ),
        )
    )
    checks.append(
        _check(
            "token-missing-permission",
            400,
            _token_call(
                request,
                base_url,
                host_header,
                secret,
                "meeting-service",
                [],
                timeout_seconds,
            ),
        )
    )

    valid_token_result = _token_call(
        request,
        base_url,
        host_header,
        secret,
        "meeting-service",
        [WRITE_PERMISSION],
        timeout_seconds,
    )
    checks.append(_check("token-valid", 200, valid_token_result))
    claims_summary: dict[str, Any] | None = None
    token: str | None = None
    if valid_token_result.status == 200:
        try:
            token_document = json.loads(valid_token_result.body)
            token = token_document["access_token"]
            if not isinstance(token, str) or not token:
                raise KeyError("access_token")
            claims_summary = summarize_and_validate_claims(token)
        except (KeyError, TypeError, json.JSONDecodeError, SmokeError):
            checks.append(
                {
                    "id": "token-claims",
                    "expectedStatus": "bound",
                    "actualStatus": "invalid",
                    "pass": False,
                }
            )
            token = None
        else:
            checks.append(
                {
                    "id": "token-claims",
                    "expectedStatus": "bound",
                    "actualStatus": "bound",
                    "pass": True,
                }
            )
    else:
        checks.append(
            {
                "id": "token-claims",
                "expectedStatus": "bound",
                "actualStatus": "unavailable",
                "pass": False,
            }
        )

    if write_synthetic_result and token is not None:
        assert tenant_id is not None
        assert session_id is not None
        assert finalization_version is not None
        assert analysis_run_id is not None
        for check_id, expected_status, presented_token in (
            ("ingest-no-token", 401, None),
            ("ingest-malformed-token", 401, "not-a-jwt"),
        ):
            checks.append(
                _check(
                    check_id,
                    expected_status,
                    _ingest_call(
                        request,
                        base_url,
                        host_header,
                        meeting_id,
                        analysis_run_id,
                        presented_token,
                        None,
                        b"{}",
                        timeout_seconds,
                    ),
                )
            )

        base_body: bytes | None = None
        canonical_binding: dict[str, Any] | None = None
        capability_summary: dict[str, Any] | None = None
        used_capability_ids: set[str] = set()
        for phase, ingest_check_id, expected_status in (
            ("first-write", "ingest-first-write", 201),
            ("replay", "ingest-idempotent-replay", 200),
            ("conflict", "ingest-idempotency-conflict", 409),
        ):
            capability_token_result = _token_call(
                request,
                base_url,
                host_header,
                secret,
                "transcript-service",
                [CAPABILITY_PERMISSION],
                timeout_seconds,
            )
            checks.append(
                _check(
                    f"capability-token-{phase}",
                    200,
                    capability_token_result,
                )
            )
            capability_service_token: str | None = None
            if capability_token_result.status == 200:
                try:
                    capability_token_document = json.loads(
                        capability_token_result.body
                    )
                    capability_service_token = capability_token_document[
                        "access_token"
                    ]
                    if (
                        not isinstance(capability_service_token, str)
                        or not capability_service_token
                    ):
                        raise KeyError("access_token")
                    summarize_and_validate_claims(
                        capability_service_token,
                        expected_audience="transcript-service",
                        expected_permission=CAPABILITY_PERMISSION,
                    )
                except (KeyError, TypeError, json.JSONDecodeError, SmokeError):
                    capability_service_token = None
            checks.append(
                {
                    "id": f"capability-token-claims-{phase}",
                    "expectedStatus": "bound",
                    "actualStatus": (
                        "bound"
                        if capability_service_token is not None
                        else "invalid"
                    ),
                    "pass": capability_service_token is not None,
                }
            )
            if capability_service_token is None:
                continue

            capability_result = _capability_call(
                request,
                base_url,
                host_header,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                session_id=session_id,
                finalization_version=finalization_version,
                analysis_run_id=analysis_run_id,
                analysis_spec_version=analysis_spec_version,
                token=capability_service_token,
                timeout_seconds=timeout_seconds,
            )
            checks.append(
                _check(
                    f"capability-issue-{phase}",
                    204,
                    capability_result,
                )
            )
            job_capability = capability_result.headers.get(CAPABILITY_HEADER)
            expires_header = capability_result.headers.get(
                CAPABILITY_EXPIRES_HEADER
            )
            binding: dict[str, Any] | None = None
            summary: dict[str, Any] | None = None
            if (
                capability_result.status == 204
                and job_capability is not None
                and expires_header is not None
            ):
                try:
                    binding, summary = summarize_and_validate_capability(
                        job_capability,
                        tenant_id=tenant_id,
                        meeting_id=meeting_id,
                        session_id=session_id,
                        finalization_version=finalization_version,
                        analysis_run_id=analysis_run_id,
                        analysis_spec_version=analysis_spec_version,
                        expires_header=expires_header,
                    )
                    capability_id = binding["capabilityId"]
                    if capability_id in used_capability_ids:
                        raise SmokeError("analysis capability was reused")
                    used_capability_ids.add(capability_id)
                    comparable = {
                        key: value
                        for key, value in binding.items()
                        if key != "capabilityId"
                    }
                    if canonical_binding is None:
                        canonical_binding = comparable
                    elif canonical_binding != comparable:
                        raise SmokeError(
                            "analysis capability tuple changed between attempts"
                        )
                except SmokeError:
                    binding = None
                    summary = None
            checks.append(
                {
                    "id": f"capability-binding-{phase}",
                    "expectedStatus": "bound",
                    "actualStatus": "bound" if binding is not None else "invalid",
                    "pass": binding is not None,
                }
            )
            if binding is None or job_capability is None:
                continue
            if capability_summary is None:
                capability_summary = summary
            if base_body is None:
                base_body = _synthetic_body(meeting_id, binding)

            fresh_write_token_result = _token_call(
                request,
                base_url,
                host_header,
                secret,
                "meeting-service",
                [WRITE_PERMISSION],
                timeout_seconds,
            )
            checks.append(
                _check(
                    f"write-token-{phase}",
                    200,
                    fresh_write_token_result,
                )
            )
            fresh_write_token: str | None = None
            if fresh_write_token_result.status == 200:
                try:
                    fresh_write_token_document = json.loads(
                        fresh_write_token_result.body
                    )
                    fresh_write_token = fresh_write_token_document["access_token"]
                    if (
                        not isinstance(fresh_write_token, str)
                        or not fresh_write_token
                    ):
                        raise KeyError("access_token")
                    summarize_and_validate_claims(fresh_write_token)
                except (KeyError, TypeError, json.JSONDecodeError, SmokeError):
                    fresh_write_token = None
            checks.append(
                {
                    "id": f"write-token-claims-{phase}",
                    "expectedStatus": "bound",
                    "actualStatus": (
                        "bound" if fresh_write_token is not None else "invalid"
                    ),
                    "pass": fresh_write_token is not None,
                }
            )
            if fresh_write_token is None:
                continue

            request_body = base_body
            if phase == "conflict":
                changed = json.loads(base_body)
                changed["summary"] = (
                    "Synthetic conflict probe; no user transcript or PII."
                )
                request_body = json.dumps(
                    changed,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            checks.append(
                _check(
                    ingest_check_id,
                    expected_status,
                    _ingest_call(
                        request,
                        base_url,
                        host_header,
                        meeting_id,
                        analysis_run_id,
                        fresh_write_token,
                        job_capability,
                        request_body,
                        timeout_seconds,
                    ),
                )
            )
            capability_service_token = None
            fresh_write_token = None
            job_capability = None
        claims_summary = {
            "serviceToken": claims_summary,
            "analysisCapability": capability_summary,
        }
    elif not write_synthetic_result:
        checks.append(
            {
                "id": "synthetic-write-required",
                "expectedStatus": "enabled",
                "actualStatus": "disabled",
                "pass": False,
            }
        )
    else:
        checks.append(
            {
                "id": "ingest-precondition",
                "expectedStatus": "valid-service-token",
                "actualStatus": "unavailable",
                "pass": False,
            }
        )

    del secret
    token = None
    accepted = all(bool(item["pass"]) for item in checks)
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _iso8601(_utc_now()),
        "environment": {
            "context": context,
            "namespace": namespace,
            "hostHeader": host_header,
            "baseUrlSha256": hashlib.sha256(base_url.encode("utf-8")).hexdigest(),
        },
        "syntheticWrite": {
            "requested": write_synthetic_result,
            "meetingId": str(meeting_id) if write_synthetic_result else None,
            "tenantId": str(tenant_id) if write_synthetic_result else None,
            "sessionId": str(session_id) if write_synthetic_result else None,
            "finalizationVersion": (
                finalization_version if write_synthetic_result else None
            ),
            "analysisRunId": (
                str(analysis_run_id) if write_synthetic_result else None
            ),
            "analysisSpecVersion": (
                analysis_spec_version if write_synthetic_result else None
            ),
            "syntheticFinalizationConfirmed": confirm_synthetic_finalization,
            "containsUserTranscript": False,
            "containsPii": False,
        },
        "claims": claims_summary,
        "checks": checks,
        "accepted": accepted,
    }
    return evidence, accepted


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SmokeError("evidence output must not be a symlink")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="k3d-test")
    parser.add_argument("--namespace", default="platform-test")
    parser.add_argument("--secret-name", default="auth-service-meeting-ai-secret")
    parser.add_argument("--secret-key", default="SERVICE_CLIENT_MEETING_AI_SECRET")
    parser.add_argument("--base-url", default="http://127.0.0.1:31080")
    parser.add_argument("--host-header", default="meeting-ai-private.testai.internal")
    parser.add_argument("--meeting-id", required=True, type=uuid.UUID)
    parser.add_argument("--tenant-id", type=uuid.UUID)
    parser.add_argument("--session-id", type=uuid.UUID)
    parser.add_argument("--finalization-version", type=int)
    parser.add_argument("--analysis-run-id", type=uuid.UUID)
    parser.add_argument(
        "--analysis-spec-version",
        default=DEFAULT_ANALYSIS_SPEC_VERSION,
    )
    parser.add_argument("--write-synthetic-result", action="store_true")
    parser.add_argument("--confirm-synthetic-finalization", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        validate_test_target(args.context, args.namespace, args.timeout_seconds)
    except SmokeError as exc:
        print(f"meeting-ai runtime smoke: {exc}", file=sys.stderr)
        return 2
    try:
        evidence, accepted = run_smoke(
            context=args.context,
            namespace=args.namespace,
            secret_name=args.secret_name,
            secret_key=args.secret_key,
            base_url=args.base_url,
            host_header=args.host_header,
            meeting_id=args.meeting_id,
            tenant_id=args.tenant_id,
            session_id=args.session_id,
            finalization_version=args.finalization_version,
            analysis_run_id=args.analysis_run_id,
            analysis_spec_version=args.analysis_spec_version,
            write_synthetic_result=args.write_synthetic_result,
            confirm_synthetic_finalization=args.confirm_synthetic_finalization,
            timeout_seconds=args.timeout_seconds,
        )
        write_evidence(args.output, evidence)
    except SmokeError as exc:
        print(f"meeting-ai runtime smoke: {exc}", file=sys.stderr)
        return 2
    failing = [item["id"] for item in evidence["checks"] if not item["pass"]]
    print(
        "meeting-ai runtime smoke: "
        + ("accepted" if accepted else f"not accepted; failing={','.join(failing)}")
    )
    print(f"metadata evidence: {args.output}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
