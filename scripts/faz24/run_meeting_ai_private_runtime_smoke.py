#!/usr/bin/env python3
"""Run the Faz 24 Meeting-AI private backend acceptance matrix.

The smoke is deliberately test-only. It reads the dedicated client secret from
Kubernetes into process memory, never forwards credentials through argv, and
writes metadata-only evidence. A synthetic analysis result can be persisted to
prove the canonical first-write/replay/conflict contract.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit


SCHEMA_VERSION = "faz24-meeting-ai-private-runtime-smoke.v1"
WRITE_PERMISSION = "meeting:analysis-result:write"
SAFE_ERROR_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
TEST_CONTEXT = "k3d-test"
TEST_NAMESPACE = "platform-test"
MAX_HTTP_TIMEOUT_SECONDS = 10


class SmokeError(RuntimeError):
    """A redaction-safe smoke failure."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


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


def summarize_and_validate_claims(token: str, now_epoch: int | None = None) -> dict[str, Any]:
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
    if audience != ["meeting-service"]:
        raise SmokeError("service token audience is not exactly meeting-service")
    if permissions != [WRITE_PERMISSION]:
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


def require_ingest_token_window(token: str, timeout_seconds: int) -> None:
    parts = token.split(".")
    if len(parts) != 3:
        raise SmokeError("service token must be a compact three-part JWT")
    claims = _b64url_json(parts[1])
    try:
        expires_at = int(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SmokeError("service token exp claim is missing or invalid") from exc
    remaining_seconds = expires_at - int(_utc_now().timestamp())
    required_seconds = (5 * timeout_seconds) + 5
    if remaining_seconds < required_seconds:
        raise SmokeError("service token has insufficient lifetime for the ingest matrix")


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
        return HttpResult(status=response.status, body=response_body)
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
    return request(
        base_url,
        host_header,
        "POST",
        f"/api/v1/internal/meetings/{meeting_id}/analysis-results",
        headers,
        body,
        timeout_seconds,
    )


def _synthetic_body(meeting_id: uuid.UUID, analysis_run_id: uuid.UUID) -> bytes:
    source_marker = f"faz24-runtime-smoke:{analysis_run_id}"
    payload = {
        "meeting_id": str(meeting_id),
        "transcript_session_id": f"SES-F24-{analysis_run_id.hex[:24]}",
        "transcript_sha256": hashlib.sha256(source_marker.encode("ascii")).hexdigest(),
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
    write_synthetic_result: bool,
    timeout_seconds: int,
    secret_loader: Callable[..., str] = load_kubernetes_secret,
    request: Callable[..., HttpResult] = http_request,
) -> tuple[dict[str, Any], bool]:
    validate_test_target(context, namespace, timeout_seconds)
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

    analysis_run_id = uuid.uuid4()
    if write_synthetic_result and token is not None:
        require_ingest_token_window(token, timeout_seconds)
        body = _synthetic_body(meeting_id, analysis_run_id)
        for check_id, expected_status, presented_token in (
            ("ingest-no-token", 401, None),
            ("ingest-malformed-token", 401, "not-a-jwt"),
            ("ingest-first-write", 201, token),
            ("ingest-idempotent-replay", 200, token),
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
                        body,
                        timeout_seconds,
                    ),
                )
            )
        changed = json.loads(body)
        changed["summary"] = "Synthetic conflict probe; no user transcript or PII."
        conflict_body = json.dumps(changed, separators=(",", ":"), sort_keys=True).encode("utf-8")
        checks.append(
            _check(
                "ingest-idempotency-conflict",
                409,
                _ingest_call(
                    request,
                    base_url,
                    host_header,
                    meeting_id,
                    analysis_run_id,
                    token,
                    conflict_body,
                    timeout_seconds,
                ),
            )
        )
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
            "analysisRunId": str(analysis_run_id) if write_synthetic_result else None,
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
    parser.add_argument("--write-synthetic-result", action="store_true")
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
            write_synthetic_result=args.write_synthetic_result,
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
