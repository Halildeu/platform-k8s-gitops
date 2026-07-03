#!/usr/bin/env python3
"""Run a redacted Faz 24 Meeting AI analyze smoke through public testai paths.

This helper intentionally keeps token material, source text, and Meeting AI
natural-language output out of the emitted evidence. It proves only that the
authenticated api-gateway -> meeting-service -> meeting-ai analyze path accepts
an ERP-agnostic meeting payload and returns the expected structured envelope.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_VALIDATOR_PATH = (
    REPO_ROOT / "scripts/keycloak/validate_faz24_platform_desktop_token_contract.py"
)
SCHEMA_VERSION = "faz24.meetingAiAnalyzeSmoke.v1"
DEFAULT_BASE_URL = "https://testai.acik.com"
DEFAULT_EXPECTED_ISSUER = "https://testai.acik.com/realms/platform-test"
DEFAULT_SOURCE_TEXT = (
    "Toplantida pilot sonrasi genel ERP CRM adaptor sozlesmesiyle devam "
    "edilmesine karar verildi. Operasyon ekibi cuma gunu rapor taslagini "
    "hazirlayacak. Canli kanitlar redacted evidence olarak issue yorumuna "
    "eklenecek."
)
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class SmokeError(RuntimeError):
    """Operator-facing smoke failure with a bounded message."""


def _iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _truncate(value: str, limit: int = 240) -> str:
    normalized = value.replace("\r", " ").replace("\n", " ")
    return normalized if len(normalized) <= limit else normalized[:limit] + "...[truncated]"


def _safe_error(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return _truncate(text)


def _load_token_validator():
    spec = importlib.util.spec_from_file_location(
        "faz24_platform_desktop_token_validator",
        TOKEN_VALIDATOR_PATH,
    )
    if spec is None or spec.loader is None:
        raise SmokeError(f"could not load token validator: {TOKEN_VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _read_token(path: str | None) -> str:
    token_path = path or os.environ.get("TOKEN_FILE")
    if not token_path:
        raise SmokeError("missing --token-file or TOKEN_FILE")
    token = Path(token_path).read_text(encoding="utf-8").strip()
    if not token:
        raise SmokeError("token file is empty")
    return token


def _validate_token_contract(token: str, expected_issuer: str | None) -> dict[str, Any]:
    validator = _load_token_validator()
    payload = validator._decode_payload(token)  # noqa: SLF001 - repo-local helper reuse.
    report = validator.validate(
        payload,
        required_audiences=list(validator.DEFAULT_REQUIRED_AUDIENCES),
        gateway_audiences=list(validator.DEFAULT_GATEWAY_AUDIENCES),
        required_claims=list(validator.DEFAULT_REQUIRED_CLAIMS),
        resource_client_id=validator.DEFAULT_RESOURCE_CLIENT_ID,
        required_client_roles=list(validator.DEFAULT_REQUIRED_CLIENT_ROLES),
        required_azp="platform-desktop",
        required_role="MEETING_ADMIN",
        expected_issuer=expected_issuer,
    )
    return {
        "status": report.get("status"),
        "failureCount": len(report.get("failures") or []),
        "failures": [_safe_error(item) for item in (report.get("failures") or [])],
    }


def _join_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _safe_json_load(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _http_json(
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected_statuses: set[int],
    timeout_seconds: float,
    body: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Correlation-Id": "faz24-meeting-ai-" + uuid.uuid4().hex,
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        _join_url(base_url, path),
        data=data,
        headers=headers,
        method=method,
    )
    status_code = 0
    response_body: Any = None
    error_class: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.getcode()
            response_body = _safe_json_load(response.read())
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_body = _safe_json_load(exc.read())
        error_class = exc.__class__.__name__
    except urllib.error.URLError as exc:
        error_class = exc.__class__.__name__
        response_body = str(exc.reason)
    except TimeoutError as exc:
        error_class = exc.__class__.__name__
        response_body = str(exc)

    step = {
        "method": method,
        "path": path,
        "expectedStatus": sorted(expected_statuses),
        "statusCode": status_code,
        "ok": status_code in expected_statuses,
        "tokenIncluded": False,
    }
    if error_class:
        step["errorClass"] = error_class
    return status_code in expected_statuses, step, response_body


def _default_meeting_payload() -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now + dt.timedelta(minutes=5)
    end = start + dt.timedelta(minutes=30)
    return {
        "title": "Faz 24 Meeting AI analyze smoke",
        "description": "ERP agnostic analyze path smoke with redacted evidence",
        "scheduledStart": _iso_z(start),
        "scheduledEnd": _iso_z(end),
    }


def _load_source_text(path: str | None) -> str:
    if not path:
        return DEFAULT_SOURCE_TEXT
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise SmokeError("source text file is empty")
    return text


def _meeting_id_from_response(body: Any) -> str:
    if not isinstance(body, dict) or not isinstance(body.get("id"), str):
        raise SmokeError("create meeting response missing id")
    meeting_id = body["id"]
    if not UUID_RE.match(meeting_id):
        raise SmokeError("create meeting response id is not UUID-shaped")
    return meeting_id


def _analyze_response_meta(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"shape": type(body).__name__, "structuredEnvelope": False}

    def count(name: str) -> int:
        value = body.get(name)
        return len(value) if isinstance(value, list) else 0

    meta = {
        "structuredEnvelope": True,
        "schemaVersion": body.get("schema_version"),
        "groundingPolicy": body.get("grounding_policy"),
        "summaryGroundingStatus": body.get("summary_grounding_status"),
        "backend": body.get("backend"),
        "model": body.get("model"),
        "elapsedMs": body.get("elapsed_ms"),
        "redacted": body.get("redacted"),
        "redactionCount": body.get("redaction_count"),
        "summaryCitationCount": count("summary_citations"),
        "decisionCount": count("decisions"),
        "actionItemCount": count("action_items"),
        "citationCount": count("citations"),
        "rejectedClaimCount": count("rejected_claims"),
        "ungroundedCount": body.get("ungrounded_count"),
    }
    return {key: value for key, value in meta.items() if value is not None}


def run_smoke(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    token = _read_token(args.token_file)
    source_text = _load_source_text(args.source_text_file)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    session_id = args.session_id or f"SES-{uuid.uuid4()}"
    started_at = _iso_z(dt.datetime.now(dt.timezone.utc))
    failures: list[str] = []
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "running",
        "tokenIncluded": False,
        "startedAt": started_at,
        "steps": [],
        "ids": {"sessionId": session_id},
        "sample": {
            "sourceTextSha256": source_hash,
            "sourceTextCharLength": len(source_text),
            "segmentCount": 2,
            "rawSourceTextIncluded": False,
            "rawAnalyzeResponseIncluded": False,
        },
        "boundaries": {
            "externalMeetingAdminPathExercised": False,
            "meetingAiAnalyzePathExercised": False,
            "rawSourceTextIncluded": False,
            "rawAnalyzeResponseIncluded": False,
            "rawTokenLogged": False,
            "piiEvidenceIncluded": False,
            "productionReady": False,
            "erpSpecificContract": False,
        },
        "failures": failures,
    }

    token_report = _validate_token_contract(token, args.expected_issuer)
    report["steps"].append(
        {
            "name": "token_contract",
            "ok": token_report.get("status") == "pass",
            "report": token_report,
        }
    )
    if token_report.get("status") != "pass":
        failures.extend(token_report.get("failures") or ["token contract did not pass"])
        report["status"] = "fail"
        report["completedAt"] = _iso_z(dt.datetime.now(dt.timezone.utc))
        return 1, report

    try:
        ok, step, response = _http_json(
            base_url=args.base_url,
            token=token,
            method="POST",
            path="/api/v1/admin/meetings",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
            body=_default_meeting_payload(),
        )
        step["name"] = "create_meeting"
        report["steps"].append(step)
        if not ok:
            failures.append("create_meeting did not return HTTP 201")
            if response is not None:
                step["responseClass"] = type(response).__name__
                step["responseError"] = _safe_error(response)
            report["status"] = "fail"
            return 1, report

        meeting_id = _meeting_id_from_response(response)
        report["ids"]["meetingId"] = meeting_id
        report["boundaries"]["externalMeetingAdminPathExercised"] = True

        midpoint = max(1, len(source_text) // 2)
        analyze_body = {
            "meeting_id": meeting_id,
            "session_id": session_id,
            "transcript": source_text,
            "source_package_version": "faz24-meeting-ai-analyze-smoke-v1",
            "segments": [
                {"text": source_text[:midpoint], "start": 0.0, "end": 4.0},
                {"text": source_text[midpoint:], "start": 4.0, "end": 8.0},
            ],
        }
        ok, step, response = _http_json(
            base_url=args.base_url,
            token=token,
            method="POST",
            path=f"/api/v1/admin/meetings/{meeting_id}/intelligence/analyze",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            body=analyze_body,
        )
        step["name"] = "meeting_ai_analyze"
        step["rawRequestBodyIncluded"] = False
        step["rawResponseBodyIncluded"] = False
        step["responseMeta"] = _analyze_response_meta(response) if ok else {}
        report["steps"].append(step)
        if not ok:
            failures.append("meeting_ai_analyze did not return HTTP 200")
            if response is not None:
                step["responseClass"] = type(response).__name__
                step["responseError"] = _safe_error(response)
            report["status"] = "fail"
            return 1, report

        report["boundaries"]["meetingAiAnalyzePathExercised"] = True
        report["status"] = "pass"
        return 0, report
    finally:
        report["completedAt"] = _iso_z(dt.datetime.now(dt.timezone.utc))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Faz 24 authenticated Meeting AI analyze smoke and emit "
            "redacted JSON evidence."
        )
    )
    parser.add_argument("--token-file", default=os.environ.get("TOKEN_FILE"))
    parser.add_argument("--base-url", default=os.environ.get("FAZ24_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--expected-issuer",
        default=os.environ.get("EXPECTED_ISSUER", DEFAULT_EXPECTED_ISSUER),
    )
    parser.add_argument("--source-text-file")
    parser.add_argument("--session-id")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-file")
    return parser.parse_args(argv)


def _write_output_file(path: str, rendered: str) -> None:
    target = Path(path)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    finally:
        try:
            os.chmod(target, 0o600)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        exit_code, report = run_smoke(args)
    except Exception as exc:
        exit_code = 2
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "error",
            "tokenIncluded": False,
            "error": _safe_error(str(exc)),
            "completedAt": _iso_z(dt.datetime.now(dt.timezone.utc)),
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
