#!/usr/bin/env python3
"""Prove the Faz 24 canonical Meeting Intelligence result user journey.

This test-only helper runs after the external recorder smoke has created a
meeting owned by the temporary platform-desktop user. It writes one synthetic,
PII-free canonical result with the dedicated Meeting-AI service identity,
reads that result through the public admin API with the same temporary user,
and verifies the metadata-only access-audit row in PostgreSQL.

The user token is read only from a mode-0600 file. Neither the token nor the
canonical response body is written to evidence or subprocess arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


SCHEMA_VERSION = "faz24.meetingAiUserResultAcceptance.v1"
TEST_CONTEXT = "k3d-test"
TEST_NAMESPACE = "platform-test"
TEST_PUBLIC_BASE_URL = "https://testai.acik.com"
TEST_PRIVATE_BASE_URL = "http://127.0.0.1:31080"
TEST_PRIVATE_HOST = "meeting-ai-private.testai.internal"
TEST_PG_CONTAINER = "platform-pg-test"
TEST_PG_DATABASE = "meeting"
MAX_HTTP_TIMEOUT_SECONDS = 20
EXPECTED_SUMMARY = "Synthetic Faz 24 acceptance result; no user transcript or PII."
EXPECTED_AUDIT_COLUMNS = [
    "id",
    "tenant_id",
    "org_id",
    "accessor_subject",
    "meeting_id",
    "analysis_run_id",
    "access_type",
    "result_count",
    "trace_id",
    "accessed_at",
]
FORBIDDEN_RESPONSE_KEYS = {
    "transcriptSha256",
    "payloadHash",
    "tenantId",
    "orgId",
    "accessorSubject",
}


class AcceptanceError(RuntimeError):
    """A bounded, redaction-safe acceptance failure."""


@dataclass(frozen=True)
class UserHttpResult:
    status: int
    headers: dict[str, str]
    body: bytes


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_test_target(
    context: str,
    namespace: str,
    public_base_url: str,
    private_base_url: str,
    private_host: str,
    pg_container: str,
    pg_database: str,
    timeout_seconds: int,
) -> None:
    exact = (
        context == TEST_CONTEXT
        and namespace == TEST_NAMESPACE
        and public_base_url == TEST_PUBLIC_BASE_URL
        and private_base_url == TEST_PRIVATE_BASE_URL
        and private_host == TEST_PRIVATE_HOST
        and pg_container == TEST_PG_CONTAINER
        and pg_database == TEST_PG_DATABASE
    )
    if not exact:
        raise AcceptanceError("refusing target outside the exact platform-test allowlist")
    if timeout_seconds < 1 or timeout_seconds > MAX_HTTP_TIMEOUT_SECONDS:
        raise AcceptanceError(
            f"timeout must be within 1..{MAX_HTTP_TIMEOUT_SECONDS} seconds"
        )


def read_user_token(path: Path) -> str:
    if path.is_symlink():
        raise AcceptanceError("token file must not be a symlink")
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise AcceptanceError("token file cannot be read") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
        raise AcceptanceError("token file must be a mode-0600 regular file")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise AcceptanceError("token file cannot be read") from exc
    if len(token) < 32 or token.count(".") != 2 or any(char.isspace() for char in token):
        raise AcceptanceError("token file does not contain a compact JWT")
    return token


def request_user_result(
    public_base_url: str,
    meeting_id: uuid.UUID,
    token: str,
    timeout_seconds: int,
) -> UserHttpResult:
    parsed = urlsplit(public_base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "testai.acik.com"
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise AcceptanceError("public result URL is outside the test allowlist")
    connection = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port,
        timeout=timeout_seconds,
    )
    path = f"/api/v1/admin/meetings/{meeting_id}/intelligence/result"
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-Correlation-Id": uuid.uuid4().hex,
            },
        )
        response = connection.getresponse()
        body = response.read(1_048_576)
        headers = {name.lower(): value for name, value in response.getheaders()}
        return UserHttpResult(response.status, headers, body)
    except (OSError, http.client.HTTPException) as exc:
        raise AcceptanceError("public canonical-result request failed") from exc
    finally:
        connection.close()


def _load_runtime_smoke_module():
    module_path = Path(__file__).with_name("run_meeting_ai_private_runtime_smoke.py")
    spec = importlib.util.spec_from_file_location("faz24_meeting_ai_runtime_smoke", module_path)
    if spec is None or spec.loader is None:
        raise AcceptanceError("Meeting-AI runtime smoke module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_service_result(
    *,
    context: str,
    namespace: str,
    private_base_url: str,
    private_host: str,
    meeting_id: uuid.UUID,
    timeout_seconds: int,
) -> dict[str, Any]:
    runtime = _load_runtime_smoke_module()
    try:
        evidence, accepted = runtime.run_smoke(
            context=context,
            namespace=namespace,
            secret_name="auth-service-meeting-ai-secret",
            secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
            base_url=private_base_url,
            host_header=private_host,
            meeting_id=meeting_id,
            write_synthetic_result=True,
            timeout_seconds=min(timeout_seconds, 10),
        )
    except runtime.SmokeError as exc:
        raise AcceptanceError("Meeting-AI service-result matrix failed") from exc
    if not accepted:
        raise AcceptanceError("Meeting-AI service-result matrix was not accepted")
    return evidence


def read_access_audit(
    *,
    pg_container: str,
    pg_database: str,
    meeting_id: uuid.UUID,
    analysis_run_id: uuid.UUID,
    started_at: datetime,
    timeout_seconds: int,
) -> dict[str, Any]:
    expected_columns_json = json.dumps(EXPECTED_AUDIT_COLUMNS, separators=(",", ":"))
    sql = r"""
WITH matched AS (
    SELECT tenant_id, org_id, accessor_subject, access_type, result_count, trace_id
      FROM meeting_service.meeting_intelligence_result_access_audit
     WHERE meeting_id = :'meeting_id'::uuid
       AND analysis_run_id = :'analysis_run_id'::uuid
       AND accessed_at >= :'started_at'::timestamptz
), column_contract AS (
    SELECT jsonb_agg(column_name ORDER BY ordinal_position) = :'expected_columns'::jsonb
               AS exact_columns
      FROM information_schema.columns
     WHERE table_schema = 'meeting_service'
       AND table_name = 'meeting_intelligence_result_access_audit'
)
SELECT json_build_object(
    'rowCount', (SELECT count(*) FROM matched),
    'orgMatchesTenant', COALESCE((SELECT bool_and(org_id = tenant_id) FROM matched), false),
    'subjectPresent', COALESCE((SELECT bool_and(char_length(btrim(accessor_subject)) BETWEEN 1 AND 255) FROM matched), false),
    'accessTypeExact', COALESCE((SELECT bool_and(access_type = 'CANONICAL_RESULT_READ') FROM matched), false),
    'resultCountExact', COALESCE((SELECT bool_and(result_count = 1) FROM matched), false),
    'traceValuesAllowlisted', COALESCE((SELECT bool_and(trace_id IS NULL OR trace_id ~ '^[0-9a-f]{16,64}$') FROM matched), false),
    'metadataColumnsExact', COALESCE((SELECT exact_columns FROM column_contract), false)
)::text;
"""
    command = [
        "docker",
        "exec",
        "-i",
        pg_container,
        "psql",
        "-X",
        "-U",
        "postgres",
        "-d",
        pg_database,
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"meeting_id={meeting_id}",
        "-v",
        f"analysis_run_id={analysis_run_id}",
        "-v",
        f"started_at={_iso8601(started_at)}",
        "-v",
        f"expected_columns={expected_columns_json}",
    ]
    try:
        completed = subprocess.run(
            command,
            input=sql,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceError("metadata-only audit query could not be executed") from exc
    if completed.returncode != 0:
        raise AcceptanceError(
            f"metadata-only audit query failed with exit {completed.returncode}"
        )
    try:
        value = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise AcceptanceError("metadata-only audit query returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceError("metadata-only audit query returned an invalid shape")
    return value


def _user_result_checks(
    result: UserHttpResult,
    meeting_id: uuid.UUID,
    analysis_run_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], bool]:
    checks: list[dict[str, Any]] = [
        {"id": "http-status", "pass": result.status == 200},
        {
            "id": "cache-control-no-store",
            "pass": "no-store" in result.headers.get("cache-control", "").lower(),
        },
    ]
    try:
        document = json.loads(result.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        document = None
    checks.append({"id": "json-object", "pass": isinstance(document, dict)})
    if isinstance(document, dict):
        expected = {
            "meetingId": str(meeting_id),
            "analysisRunId": str(analysis_run_id),
            "schema_version": "5-adr0043",
            "model": "runtime-smoke",
            "backend": "synthetic",
            "persisted": True,
            "storageMode": "canonical",
            "redacted": True,
        }
        checks.extend(
            {"id": f"field-{name}", "pass": document.get(name) == value}
            for name, value in expected.items()
        )
        checks.append(
            {"id": "synthetic-summary-exact", "pass": document.get("summary") == EXPECTED_SUMMARY}
        )
        checks.append(
            {
                "id": "forbidden-envelope-keys-absent",
                "pass": FORBIDDEN_RESPONSE_KEYS.isdisjoint(document),
            }
        )
    return checks, all(bool(item["pass"]) for item in checks)


def _audit_checks(value: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    expected = {
        "rowCount": 1,
        "orgMatchesTenant": True,
        "subjectPresent": True,
        "accessTypeExact": True,
        "resultCountExact": True,
        "traceValuesAllowlisted": True,
        "metadataColumnsExact": True,
    }
    checks = [
        {"id": f"audit-{name}", "pass": value.get(name) == expected_value}
        for name, expected_value in expected.items()
    ]
    return checks, all(bool(item["pass"]) for item in checks)


def run_acceptance(
    *,
    context: str,
    namespace: str,
    public_base_url: str,
    private_base_url: str,
    private_host: str,
    pg_container: str,
    pg_database: str,
    meeting_id: uuid.UUID,
    token: str,
    timeout_seconds: int,
    service_writer: Callable[..., dict[str, Any]] = write_service_result,
    user_request: Callable[..., UserHttpResult] = request_user_result,
    audit_reader: Callable[..., dict[str, Any]] = read_access_audit,
) -> tuple[dict[str, Any], bool]:
    validate_test_target(
        context,
        namespace,
        public_base_url,
        private_base_url,
        private_host,
        pg_container,
        pg_database,
        timeout_seconds,
    )
    started_at = _utc_now()
    service_evidence = service_writer(
        context=context,
        namespace=namespace,
        private_base_url=private_base_url,
        private_host=private_host,
        meeting_id=meeting_id,
        timeout_seconds=timeout_seconds,
    )
    try:
        analysis_run_id = uuid.UUID(service_evidence["syntheticWrite"]["analysisRunId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AcceptanceError("service evidence is missing a valid analysis run id") from exc
    if service_evidence.get("accepted") is not True:
        raise AcceptanceError("service evidence is not accepted")

    user_result = user_request(public_base_url, meeting_id, token, timeout_seconds)
    user_checks, user_accepted = _user_result_checks(
        user_result,
        meeting_id,
        analysis_run_id,
    )
    token = ""

    audit_value = audit_reader(
        pg_container=pg_container,
        pg_database=pg_database,
        meeting_id=meeting_id,
        analysis_run_id=analysis_run_id,
        started_at=started_at,
        timeout_seconds=timeout_seconds,
    )
    audit_checks, audit_accepted = _audit_checks(audit_value)
    accepted = user_accepted and audit_accepted
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _iso8601(_utc_now()),
        "environment": {
            "context": context,
            "namespace": namespace,
            "publicBaseUrlSha256": hashlib.sha256(public_base_url.encode()).hexdigest(),
            "privateBaseUrlSha256": hashlib.sha256(private_base_url.encode()).hexdigest(),
        },
        "ids": {
            "meetingId": str(meeting_id),
            "analysisRunId": str(analysis_run_id),
        },
        "boundaries": {
            "platformTestOnly": True,
            "productionMutation": False,
            "syntheticResult": True,
            "containsUserTranscript": False,
            "containsPii": False,
            "userTokenIncluded": False,
            "canonicalResponseBodyIncluded": False,
            "auditPayloadIncluded": False,
        },
        "serviceWrite": service_evidence,
        "userRead": {
            "actualStatus": user_result.status,
            "responseBodySha256": hashlib.sha256(user_result.body).hexdigest(),
            "checks": user_checks,
            "accepted": user_accepted,
        },
        "metadataOnlyAudit": {
            "checks": audit_checks,
            "accepted": audit_accepted,
        },
        "accepted": accepted,
    }
    return evidence, accepted


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise AcceptanceError("evidence output must not be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
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
    parser.add_argument("--context", default=TEST_CONTEXT)
    parser.add_argument("--namespace", default=TEST_NAMESPACE)
    parser.add_argument("--public-base-url", default=TEST_PUBLIC_BASE_URL)
    parser.add_argument("--private-base-url", default=TEST_PRIVATE_BASE_URL)
    parser.add_argument("--private-host", default=TEST_PRIVATE_HOST)
    parser.add_argument("--pg-container", default=TEST_PG_CONTAINER)
    parser.add_argument("--pg-database", default=TEST_PG_DATABASE)
    parser.add_argument("--meeting-id", required=True, type=uuid.UUID)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--timeout-seconds", default=10, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        validate_test_target(
            args.context,
            args.namespace,
            args.public_base_url,
            args.private_base_url,
            args.private_host,
            args.pg_container,
            args.pg_database,
            args.timeout_seconds,
        )
        token = read_user_token(args.token_file)
        evidence, accepted = run_acceptance(
            context=args.context,
            namespace=args.namespace,
            public_base_url=args.public_base_url,
            private_base_url=args.private_base_url,
            private_host=args.private_host,
            pg_container=args.pg_container,
            pg_database=args.pg_database,
            meeting_id=args.meeting_id,
            token=token,
            timeout_seconds=args.timeout_seconds,
        )
        token = ""
        write_evidence(args.output, evidence)
    except AcceptanceError as exc:
        print(f"Meeting-AI user-result acceptance: {exc}", file=sys.stderr)
        return 2
    print(
        "Meeting-AI user-result acceptance: "
        + ("accepted" if accepted else "not accepted")
    )
    print(f"metadata evidence: {args.output}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
