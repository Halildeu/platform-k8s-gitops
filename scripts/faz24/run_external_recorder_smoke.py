#!/usr/bin/env python3
"""Run the Faz 24 external recorder smoke through public testai paths.

This operator helper intentionally keeps token material out of logs and output.
It validates the platform-desktop token contract first, then exercises:

1. POST /api/v1/admin/meetings through api-gateway
2. POST /api/v1/audio-gateway/consents
3. POST /api/v1/audio-gateway/sessions
4. POST /api/v1/audio-gateway/sessions/{sessionId}/chunks
5. POST /api/v1/audio-gateway/sessions/{sessionId}/finish
6. GET  /api/v1/audio-gateway/sessions/{sessionId}/status

The emitted JSON is a redacted evidence envelope. It is not a direct-STT or
compute-plane audit verifier.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import time
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
SCHEMA_VERSION = "faz24.externalRecorderSmoke.v1"
DEFAULT_BASE_URL = "https://testai.acik.com"
DEFAULT_EXPECTED_ISSUER = "https://testai.acik.com/realms/platform-test"
DEFAULT_CONSENT_TEXT = (
    "Faz 24 platform-desktop recorder smoke consent text v1. "
    "No production recording or direct-STT assertion is made by this helper."
)
SENSITIVE_RESPONSE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "bearer",
    "jwt",
    "credential",
    "session_token",
    "auth_token",
    "api_key",
    "cookie",
    "client_secret",
    "password",
    "secret",
    "callback_endpoint",
    "callback_url",
    "destination_endpoint",
    "destination_url",
    "endpoint_url",
    "internal_url",
    "stt_endpoint",
    "stt_url",
    "transcribe_endpoint",
    "transcribe_url",
    "webhook_url",
    "whisper_url",
    "audio_base64",
    "audio_bytes",
    "audio_preview",
    "raw_audio",
    "raw_audio_bytes",
    "transcript",
    "transcript_text",
}
SENSITIVE_RESPONSE_KEYS_COMPACT = {key.replace("_", "") for key in SENSITIVE_RESPONSE_KEYS}
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:https?|wss?)://[^\s\"']+", re.IGNORECASE),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
]


class SmokeError(RuntimeError):
    """Operator-facing smoke failure with a bounded message."""


def _normalized_key(key: str) -> str:
    key = key.replace("-", "_").replace(".", "_").strip()
    key = CAMEL_BOUNDARY_1_RE.sub(r"\1_\2", key)
    key = CAMEL_BOUNDARY_2_RE.sub(r"\1_\2", key)
    return re.sub(r"_+", "_", key).lower()


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in SENSITIVE_RESPONSE_KEYS
        or normalized.replace("_", "") in SENSITIVE_RESPONSE_KEYS_COMPACT
    )


def _is_sensitive_string(value: str) -> bool:
    return any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS)


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
    return validator.validate(
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


def _iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _default_meeting_payload() -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now + dt.timedelta(minutes=5)
    end = start + dt.timedelta(minutes=30)
    return {
        "title": "Faz 24 external recorder smoke",
        "description": "api-gateway meeting create plus audio-gateway lifecycle smoke",
        "scheduledStart": _iso_z(start),
        "scheduledEnd": _iso_z(end),
    }


def _load_json_file(path: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if not path:
        return default
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SmokeError(f"{path} must contain a JSON object")
    return data


def _default_chunk() -> bytes:
    # 512 bytes = 256 whole PCM16 mono frames. The accountant rejects a byte
    # length that is not a whole number of frames, so this length is load
    # bearing for the default (PCM16) format.
    return bytes((idx % 251 for idx in range(512)))


def _load_chunk(path: str | None) -> bytes:
    if not path:
        return _default_chunk()
    data = Path(path).read_bytes()
    if not data:
        raise SmokeError("chunk file is empty")
    return data


def _join_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _safe_json_load(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _truncate(value: str, limit: int = 1000) -> str:
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _response_excerpt(body: Any) -> Any:
    if body is None or isinstance(body, (int, float, bool)):
        return body
    if isinstance(body, str):
        if _is_sensitive_string(body):
            return "<redacted-sensitive-value>"
        return _truncate(body)
    if isinstance(body, list):
        return [_response_excerpt(item) for item in body[:20]]
    if isinstance(body, dict):
        safe: dict[str, Any] = {}
        redacted_count = 0
        for key, value in body.items():
            if _is_sensitive_key(str(key)):
                redacted_count += 1
            else:
                safe[key] = _response_excerpt(value)
        if redacted_count:
            safe["redactedFieldCount"] = redacted_count
        return safe
    return str(body)


def _http_request(
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected_statuses: set[int],
    timeout_seconds: float,
    json_body: dict[str, Any] | None = None,
    binary_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bool, dict[str, Any], Any]:
    req_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Correlation-Id": "faz24-" + uuid.uuid4().hex,
    }
    if headers:
        req_headers.update(headers)

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif binary_body is not None:
        data = binary_body
        req_headers["Content-Type"] = "application/octet-stream"

    url = _join_url(base_url, path)
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)

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

    ok = status_code in expected_statuses
    result = {
        "method": method,
        "path": path,
        "expectedStatus": sorted(expected_statuses),
        "statusCode": status_code,
        "ok": ok,
        "tokenIncluded": False,
    }
    if error_class:
        result["errorClass"] = error_class
    if response_body is not None:
        result["response"] = _response_excerpt(response_body)
    return ok, result, response_body


def _require_field(body: Any, field: str, step: str) -> str:
    if not isinstance(body, dict) or not body.get(field):
        raise SmokeError(f"{step} response missing '{field}'")
    return str(body[field])


def _idempotency(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def run_smoke(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    token = _read_token(args.token_file)
    started_at = _iso_z(dt.datetime.now(dt.timezone.utc))
    failures: list[str] = []
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "running",
        "tokenIncluded": False,
        "startedAt": started_at,
        "steps": [],
        "ids": {},
        "boundaries": {
            "externalMeetingAdminPathExercised": False,
            "recorderLifecycleExercised": False,
            "canonicalRecordingLifecycleSynced": False,
            "directSttProven": False,
            "directSttTranscriptProven": False,
            "directClientToStt": False,
            "computePlaneAuditProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
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

    meeting_payload = _load_json_file(args.meeting_payload_file, _default_meeting_payload())
    chunk_body = _load_chunk(args.chunk_file)
    report["sample"] = {
        "chunkSeq": 0,
        "sampleSha256": hashlib.sha256(chunk_body).hexdigest(),
        "byteLength": len(chunk_body),
        "audioFormat": args.audio_format,
        "sampleRateHz": args.sample_rate_hz,
        "channels": args.channels,
        "rawAudioIncluded": False,
    }
    capture_id = args.capture_id or str(uuid.uuid4())
    consent_hash = "sha256:" + hashlib.sha256(args.consent_text.encode("utf-8")).hexdigest()

    try:
        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path="/api/v1/admin/meetings",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
            json_body=meeting_payload,
        )
        step["name"] = "create_meeting"
        report["steps"].append(step)
        if not ok:
            failures.append("create_meeting did not return HTTP 201")
            report["status"] = "fail"
            return 1, report
        meeting_id = _require_field(response, "id", "create_meeting")
        report["ids"]["meetingId"] = meeting_id
        report["boundaries"]["externalMeetingAdminPathExercised"] = True

        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path="/api/v1/audio-gateway/consents",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
            json_body={
                "meetingId": meeting_id,
                "captureId": capture_id,
                "consentVersion": args.consent_version,
                "consentTextHash": consent_hash,
                "locale": args.consent_locale,
            },
        )
        step["name"] = "record_consent"
        report["steps"].append(step)
        report["ids"]["captureId"] = capture_id
        if not ok:
            failures.append("record_consent did not return HTTP 201")
            report["status"] = "fail"
            return 1, report

        start_session_body = {
            "meetingId": meeting_id,
            "deviceId": args.device_id,
            "language": args.language,
            "audioFormat": args.audio_format,
            "sampleRateHz": args.sample_rate_hz,
            "channels": args.channels,
        }
        if args.stt_provider:
            start_session_body["sttProvider"] = args.stt_provider

        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path="/api/v1/audio-gateway/sessions",
            expected_statuses={200, 201},
            timeout_seconds=args.timeout_seconds,
            json_body=start_session_body,
            headers={"Idempotency-Key": _idempotency("faz24-start")},
        )
        step["name"] = "start_session"
        report["steps"].append(step)
        if not ok:
            failures.append("start_session did not return HTTP 200/201")
            report["status"] = "fail"
            return 1, report
        session_id = _require_field(response, "sessionId", "start_session")
        if not SESSION_ID_RE.match(session_id):
            raise SmokeError("start_session response contains unsafe sessionId")
        report["ids"]["sessionId"] = session_id

        recording_started_at = _iso_z(dt.datetime.now(dt.timezone.utc))
        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="PUT",
            path=f"/api/v1/admin/meetings/{meeting_id}/recording-lifecycle",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            json_body={
                "externalSessionId": session_id,
                "startedAt": recording_started_at,
            },
        )
        step["name"] = "sync_recording_lifecycle_start"
        report["steps"].append(step)
        if not ok:
            failures.append("sync_recording_lifecycle_start did not return HTTP 200")
            report["status"] = "fail"
            return 1, report
        canonical_session_id = _require_field(
            response, "sessionId", "sync_recording_lifecycle_start"
        )
        if not isinstance(response, dict) or response.get("externalSessionId") != session_id:
            failures.append("recording lifecycle start externalSessionId mismatch")
            report["status"] = "fail"
            return 1, report
        report["ids"]["canonicalSessionId"] = canonical_session_id

        now_ms = int(time.time() * 1000)
        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path=f"/api/v1/audio-gateway/sessions/{session_id}/chunks",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            binary_body=chunk_body,
            headers={
                "Idempotency-Key": _idempotency("faz24-chunk"),
                "X-Audio-Chunk-Seq": "0",
                "X-Audio-Chunk-Started-At-Ms": str(now_ms),
                "X-Audio-Format": args.audio_format,
                "X-Audio-Sample-Rate-Hz": str(args.sample_rate_hz),
                "X-Audio-Channels": str(args.channels),
                "X-Audio-Byte-Length": str(len(chunk_body)),
            },
        )
        step["name"] = "upload_chunk"
        report["steps"].append(step)
        if not ok:
            failures.append("upload_chunk did not return HTTP 200")
            report["status"] = "fail"
            return 1, report

        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path=f"/api/v1/audio-gateway/sessions/{session_id}/finish",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            headers={"Idempotency-Key": _idempotency("faz24-finish")},
        )
        step["name"] = "finish_session"
        report["steps"].append(step)
        if not ok:
            failures.append("finish_session did not return HTTP 200")
            report["status"] = "fail"
            return 1, report

        recording_ended_at = _iso_z(dt.datetime.now(dt.timezone.utc))
        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="PUT",
            path=f"/api/v1/admin/meetings/{meeting_id}/recording-lifecycle",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            json_body={
                "externalSessionId": session_id,
                "startedAt": recording_started_at,
                "endedAt": recording_ended_at,
            },
        )
        step["name"] = "sync_recording_lifecycle_finish"
        report["steps"].append(step)
        if not ok:
            failures.append("sync_recording_lifecycle_finish did not return HTTP 200")
            report["status"] = "fail"
            return 1, report
        if (
            not isinstance(response, dict)
            or response.get("externalSessionId") != session_id
            or str(response.get("sessionId", "")) != canonical_session_id
            or response.get("transcriptStatus") not in {"PROCESSING", "COMPLETED"}
        ):
            failures.append("recording lifecycle finish canonical projection mismatch")
            report["status"] = "fail"
            return 1, report
        report["boundaries"]["canonicalRecordingLifecycleSynced"] = True

        ok, step, response = _http_request(
            base_url=args.base_url,
            token=token,
            method="GET",
            path=f"/api/v1/audio-gateway/sessions/{session_id}/status",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
        )
        step["name"] = "session_status"
        report["steps"].append(step)
        if not ok:
            failures.append("session_status did not return HTTP 200")
            report["status"] = "fail"
            return 1, report
        if isinstance(response, dict) and response.get("state") != "FINISHED":
            failures.append("session_status state is not FINISHED")
            report["status"] = "fail"
            return 1, report

        report["boundaries"]["recorderLifecycleExercised"] = True
        report["status"] = "pass"
        return 0, report
    finally:
        report["completedAt"] = _iso_z(dt.datetime.now(dt.timezone.utc))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Faz 24 external meeting-admin plus audio-gateway recorder "
            "lifecycle smoke and emit redacted JSON evidence."
        )
    )
    parser.add_argument("--token-file", default=os.environ.get("TOKEN_FILE"))
    parser.add_argument("--base-url", default=os.environ.get("FAZ24_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--expected-issuer",
        default=os.environ.get("EXPECTED_ISSUER", DEFAULT_EXPECTED_ISSUER),
    )
    parser.add_argument("--meeting-payload-file")
    parser.add_argument("--chunk-file")
    parser.add_argument("--capture-id")
    parser.add_argument("--device-id", default="codex-faz24-smoke")
    parser.add_argument("--language", default="tr")
    parser.add_argument("--stt-provider", choices=("internal", "speechmatics"))
    # PCM16, not WAV: the smoke opens a session without transcriptionMode, so the
    # gateway routes it through DirectSttForwardingDispatcher, and the #257 contract
    # makes direct-STT PCM16-only — a container format's duration cannot be derived
    # without a parser, so the accountant returns Unmeterable and the dispatcher
    # answers 503 AUDIO_GATEWAY_STT_UNAVAILABLE before the chunk is ever forwarded.
    # WAV stays valid on the global API surface; it is simply not a direct-STT input.
    parser.add_argument("--audio-format", default="PCM16")
    parser.add_argument("--sample-rate-hz", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--consent-version", default="recorder-consent-v1")
    parser.add_argument("--consent-locale", default="tr-TR")
    parser.add_argument("--consent-text", default=DEFAULT_CONSENT_TEXT)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
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
            "error": str(exc),
            "completedAt": _iso_z(dt.datetime.now(dt.timezone.utc)),
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
