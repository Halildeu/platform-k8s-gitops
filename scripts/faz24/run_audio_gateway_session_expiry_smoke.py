#!/usr/bin/env python3
"""Prove audio-gateway expiry cleanup and capacity reuse with redacted evidence.

The caller supplies a short-lived platform-desktop token file and two URLs:
the public testai URL for canonical meeting creation, and a loopback URL that
port-forwards to an ADR-0022/0023 transient audio-gateway pod. The transient
pod must enforce one active session and a one-minute session age.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from run_external_recorder_smoke import (
    SESSION_ID_RE,
    SmokeError,
    _default_meeting_payload,
    _idempotency,
    _iso_z,
    _join_url,
    _read_token,
    _response_excerpt,
    _require_field,
    _safe_json_load,
    _validate_token_contract,
    _write_output_file,
)


SCHEMA_VERSION = "faz24.audioGatewaySessionExpirySmoke.v1"
DEFAULT_PUBLIC_BASE_URL = "https://testai.acik.com"
DEFAULT_EXPECTED_ISSUER = "https://testai.acik.com/realms/platform-test"
METRIC_NAMES = (
    "audio_gateway_session_expired_total",
    "audio_gateway_session_expiry_cleanup_error_total",
    "audio_gateway_direct_stt_aggregation_active_sessions",
    "audio_gateway_direct_stt_aggregation_buffered_bytes",
    "audio_gateway_direct_stt_audio_bound_reserved_frames",
    "audio_gateway_direct_stt_audio_bound_active_sessions",
    "audio_gateway_direct_stt_audio_bound_negative_invariant_total",
    "audio_gateway_direct_stt_aggregation_chunks_buffered_total",
    "audio_gateway_direct_stt_aggregation_dropped_capacity_total",
)
METRIC_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^\n]*\})?\s+"
    r"(?P<value>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$"
)
IMAGE_RE = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())
LOOPBACK_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler(),
)


def _validate_loopback_base_url(value: str, field: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SmokeError(f"{field} must be an http://127.0.0.1:<port> base URL")


def _http_request_no_redirect(
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected_statuses: set[int],
    timeout_seconds: int,
    json_body: dict[str, Any] | None = None,
    binary_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bool, dict[str, Any], Any]:
    request_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Correlation-Id": "faz24-expiry-" + uuid.uuid4().hex,
    }
    if headers:
        request_headers.update(headers)

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    elif binary_body is not None:
        data = binary_body
        request_headers["Content-Type"] = "application/octet-stream"

    request = urllib.request.Request(
        _join_url(base_url, path),
        data=data,
        headers=request_headers,
        method=method,
    )
    status_code = 0
    response_body: Any = None
    error_class: str | None = None
    request_host = urllib.parse.urlsplit(base_url).hostname
    opener = (
        LOOPBACK_NO_REDIRECT_OPENER
        if request_host == "127.0.0.1"
        else NO_REDIRECT_OPENER
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
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
    result: dict[str, Any] = {
        "method": method,
        "path": path,
        "expectedStatus": sorted(expected_statuses),
        "statusCode": status_code,
        "ok": ok,
        "tokenIncluded": False,
        "redirectFollowed": False,
    }
    if error_class:
        result["errorClass"] = error_class
    if response_body is not None:
        result["response"] = _response_excerpt(response_body)
    return ok, result, response_body


def _metric_value(values: dict[str, float], name: str) -> float:
    if name in values:
        return values[name]
    # Micrometer may append _total to a Counter that already uses that suffix.
    doubled = f"{name}_total"
    if doubled in values:
        return values[doubled]
    raise SmokeError(f"required metric missing: {name}")


def _metrics_snapshot(base_url: str, timeout_seconds: int) -> dict[str, float]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/actuator/prometheus",
        headers={"Accept": "text/plain"},
        method="GET",
    )
    with LOOPBACK_NO_REDIRECT_OPENER.open(
        request, timeout=timeout_seconds
    ) as response:
        if response.status != 200:
            raise SmokeError(f"metrics endpoint returned HTTP {response.status}")
        text = response.read(2_000_000).decode("utf-8", errors="replace")

    parsed: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = METRIC_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        if name in METRIC_NAMES or name.removesuffix("_total") in METRIC_NAMES:
            parsed[name] = parsed.get(name, 0.0) + float(match.group("value"))
    return {name: _metric_value(parsed, name) for name in METRIC_NAMES}


def _request(
    report: dict[str, Any],
    *,
    name: str,
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected_statuses: set[int],
    timeout_seconds: int,
    json_body: dict[str, Any] | None = None,
    binary_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    ok, step, body = _http_request_no_redirect(
        base_url=base_url,
        token=token,
        method=method,
        path=path,
        expected_statuses=expected_statuses,
        timeout_seconds=timeout_seconds,
        json_body=json_body,
        binary_body=binary_body,
        headers=headers,
    )
    step["name"] = name
    report["steps"].append(step)
    if not ok:
        raise SmokeError(
            f"{name} returned HTTP {step.get('statusCode')}; expected "
            f"{sorted(expected_statuses)}"
        )
    return body


def _session_payload(meeting_id: str, suffix: str) -> dict[str, Any]:
    return {
        "meetingId": meeting_id,
        "deviceId": f"codex-expiry-{suffix}",
        "language": "tr",
        "audioFormat": "PCM16",
        "sampleRateHz": 16000,
        "channels": 1,
    }


def _start_session(
    report: dict[str, Any],
    *,
    audio_base_url: str,
    token: str,
    meeting_id: str,
    suffix: str,
    expected_statuses: set[int],
    timeout_seconds: int,
) -> Any:
    return _request(
        report,
        name=f"start_session_{suffix}",
        base_url=audio_base_url,
        token=token,
        method="POST",
        path="/api/v1/audio-gateway/sessions",
        expected_statuses=expected_statuses,
        timeout_seconds=timeout_seconds,
        json_body=_session_payload(meeting_id, suffix),
        headers={"Idempotency-Key": _idempotency(f"faz24-expiry-{suffix}")},
    )


def _upload_chunk(
    report: dict[str, Any],
    *,
    audio_base_url: str,
    token: str,
    session_id: str,
    suffix: str,
    timeout_seconds: int,
) -> None:
    chunk = bytes(3_200)  # 100 ms, mono PCM16 at 16 kHz.
    now_ms = int(time.time() * 1000)
    _request(
        report,
        name=f"upload_chunk_{suffix}",
        base_url=audio_base_url,
        token=token,
        method="POST",
        path=f"/api/v1/audio-gateway/sessions/{session_id}/chunks",
        expected_statuses={200},
        timeout_seconds=timeout_seconds,
        binary_body=chunk,
        headers={
            "Idempotency-Key": _idempotency(f"faz24-expiry-chunk-{suffix}"),
            "X-Audio-Chunk-Seq": "0",
            "X-Audio-Chunk-Started-At-Ms": str(now_ms),
            "X-Audio-Format": "PCM16",
            "X-Audio-Sample-Rate-Hz": "16000",
            "X-Audio-Channels": "1",
            "X-Audio-Byte-Length": str(len(chunk)),
        },
    )


def _wait_for_metrics(
    base_url: str,
    timeout_seconds: int,
    predicate,
) -> dict[str, float]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, float] = {}
    while time.monotonic() < deadline:
        latest = _metrics_snapshot(base_url, min(timeout_seconds, 10))
        if predicate(latest):
            return latest
        time.sleep(1)
    raise SmokeError(f"metric convergence timeout; last={latest}")


def run_smoke(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    started_at = dt.datetime.now(dt.timezone.utc)
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "running",
        "tokenIncluded": False,
        "startedAt": _iso_z(started_at),
        "completedAt": None,
        "ids": {},
        "steps": [],
        "metrics": {},
        "runtimeEvidence": {
            "podUid": args.pod_uid,
            "image": args.expected_image,
            "effectiveOverrides": {
                "maxSessionMinutes": 1,
                "sessionExpirySweepMs": 1000,
                "maxActiveSessions": 1,
                "maxBufferedSessions": 1,
                "dispatcherMode": "noop",
                "auditRedisEnabled": False,
                "redisHealthEnabled": False,
                "transcriptResultStreamEnabled": False,
            },
        },
        "boundaries": {
            "platformTestOnly": True,
            "transientWorkloadRequired": True,
            "managedWorkloadMutated": False,
            "productionMutation": False,
            "rawTokenLogged": False,
            "rawAudioIncluded": False,
            "sessionRegistryCapacityReused": False,
            "aggregationReservationReleased": False,
            "negativeInvariantStable": False,
        },
        "failureReason": None,
    }

    try:
        _validate_loopback_base_url(args.audio_base_url, "audio-base-url")
        _validate_loopback_base_url(args.metrics_base_url, "metrics-base-url")
        if not IMAGE_RE.fullmatch(args.expected_image):
            raise SmokeError("expected-image must be an immutable image@sha256 reference")
        try:
            uuid.UUID(args.pod_uid)
        except ValueError as exc:
            raise SmokeError("pod-uid must be a UUID") from exc

        token = _read_token(args.token_file)
        token_contract = _validate_token_contract(token, args.expected_issuer)
        if token_contract.get("status") != "pass":
            raise SmokeError("platform-desktop token contract failed")
        meeting = _request(
            report,
            name="create_meeting",
            base_url=args.public_base_url,
            token=token,
            method="POST",
            path="/api/v1/admin/meetings",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
            json_body=_default_meeting_payload(),
        )
        meeting_id = _require_field(meeting, "id", "create_meeting")
        report["ids"]["meetingId"] = meeting_id

        consent_text = "Faz 24 isolated audio-gateway session expiry smoke consent v1"
        capture_id = str(uuid.uuid4())
        report["ids"]["captureId"] = capture_id
        _request(
            report,
            name="record_consent",
            base_url=args.audio_base_url,
            token=token,
            method="POST",
            path="/api/v1/audio-gateway/consents",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
            json_body={
                "meetingId": meeting_id,
                "captureId": capture_id,
                "consentVersion": "faz24-expiry-smoke-v1",
                "consentTextHash": "sha256:"
                + hashlib.sha256(consent_text.encode()).hexdigest(),
                "locale": "tr-TR",
            },
        )

        baseline = _metrics_snapshot(args.metrics_base_url, args.timeout_seconds)
        report["metrics"]["baseline"] = baseline
        non_zero_baseline = {
            name: value for name, value in baseline.items() if value != 0
        }
        if non_zero_baseline:
            raise SmokeError(
                f"transient pod metric baseline must be zero; nonZero={non_zero_baseline}"
            )

        first = _start_session(
            report,
            audio_base_url=args.audio_base_url,
            token=token,
            meeting_id=meeting_id,
            suffix="first",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
        )
        first_id = _require_field(first, "sessionId", "start_session_first")
        if not SESSION_ID_RE.match(first_id):
            raise SmokeError("first sessionId has unsafe format")
        report["ids"]["expiredSessionId"] = first_id
        _upload_chunk(
            report,
            audio_base_url=args.audio_base_url,
            token=token,
            session_id=first_id,
            suffix="first",
            timeout_seconds=args.timeout_seconds,
        )

        reserved = _wait_for_metrics(
            args.metrics_base_url,
            args.metric_wait_seconds,
            lambda m: m["audio_gateway_direct_stt_aggregation_active_sessions"] == 1
            and m["audio_gateway_direct_stt_audio_bound_active_sessions"] == 1
            and m["audio_gateway_direct_stt_audio_bound_reserved_frames"] > 0
            and m["audio_gateway_direct_stt_aggregation_buffered_bytes"] > 0
            and m["audio_gateway_direct_stt_aggregation_chunks_buffered_total"] == 1,
        )
        report["metrics"]["firstSessionReserved"] = reserved

        full = _start_session(
            report,
            audio_base_url=args.audio_base_url,
            token=token,
            meeting_id=meeting_id,
            suffix="capacity-full",
            expected_statuses={503},
            timeout_seconds=args.timeout_seconds,
        )
        if not isinstance(full, dict) or full.get("code") != "AUDIO_GATEWAY_SESSION_REGISTRY_FULL":
            raise SmokeError("second start did not prove session registry capacity full")

        expired = _wait_for_metrics(
            args.metrics_base_url,
            args.expiry_wait_seconds,
            lambda m: m["audio_gateway_session_expired_total"] == 1
            and m["audio_gateway_session_expiry_cleanup_error_total"]
            == baseline["audio_gateway_session_expiry_cleanup_error_total"]
            and m["audio_gateway_direct_stt_aggregation_active_sessions"] == 0
            and m["audio_gateway_direct_stt_aggregation_buffered_bytes"] == 0
            and m["audio_gateway_direct_stt_audio_bound_active_sessions"] == 0
            and m["audio_gateway_direct_stt_audio_bound_reserved_frames"] == 0
            and m["audio_gateway_direct_stt_audio_bound_negative_invariant_total"]
            == baseline["audio_gateway_direct_stt_audio_bound_negative_invariant_total"],
        )
        report["metrics"]["afterExpiry"] = expired

        expired_status = _request(
            report,
            name="expired_session_not_found",
            base_url=args.audio_base_url,
            token=token,
            method="GET",
            path=f"/api/v1/audio-gateway/sessions/{first_id}/status",
            expected_statuses={404},
            timeout_seconds=args.timeout_seconds,
        )
        if not isinstance(expired_status, dict) or expired_status.get("code") != "AUDIO_GATEWAY_SESSION_NOT_FOUND":
            raise SmokeError("expired session status did not return the session-not-found contract")

        reused = _start_session(
            report,
            audio_base_url=args.audio_base_url,
            token=token,
            meeting_id=meeting_id,
            suffix="reused",
            expected_statuses={201},
            timeout_seconds=args.timeout_seconds,
        )
        reused_id = _require_field(reused, "sessionId", "start_session_reused")
        if not SESSION_ID_RE.match(reused_id):
            raise SmokeError("reused sessionId has unsafe format")
        report["ids"]["reusedSessionId"] = reused_id
        _upload_chunk(
            report,
            audio_base_url=args.audio_base_url,
            token=token,
            session_id=reused_id,
            suffix="reused",
            timeout_seconds=args.timeout_seconds,
        )
        reused_metrics = _wait_for_metrics(
            args.metrics_base_url,
            args.metric_wait_seconds,
            lambda m: m["audio_gateway_direct_stt_aggregation_active_sessions"] == 1
            and m["audio_gateway_direct_stt_audio_bound_active_sessions"] == 1
            and m["audio_gateway_direct_stt_audio_bound_reserved_frames"] > 0
            and m["audio_gateway_direct_stt_aggregation_dropped_capacity_total"]
            == baseline["audio_gateway_direct_stt_aggregation_dropped_capacity_total"]
            and m["audio_gateway_direct_stt_audio_bound_negative_invariant_total"]
            == baseline["audio_gateway_direct_stt_audio_bound_negative_invariant_total"]
            and m["audio_gateway_direct_stt_aggregation_chunks_buffered_total"] == 2,
        )
        report["metrics"]["reusedSessionReserved"] = reused_metrics

        finish = _request(
            report,
            name="finish_reused_session",
            base_url=args.audio_base_url,
            token=token,
            method="POST",
            path=f"/api/v1/audio-gateway/sessions/{reused_id}/finish",
            expected_statuses={200},
            timeout_seconds=args.timeout_seconds,
            headers={"Idempotency-Key": _idempotency("faz24-expiry-finish-reused")},
        )
        if not isinstance(finish, dict) or finish.get("finalState") != "FINISHED":
            raise SmokeError("reused session finish did not return FINISHED")
        final_metrics = _wait_for_metrics(
            args.metrics_base_url,
            args.metric_wait_seconds,
            lambda m: m["audio_gateway_direct_stt_aggregation_active_sessions"] == 0
            and m["audio_gateway_direct_stt_aggregation_buffered_bytes"] == 0
            and m["audio_gateway_direct_stt_audio_bound_active_sessions"] == 0
            and m["audio_gateway_direct_stt_audio_bound_reserved_frames"] == 0
            and m["audio_gateway_direct_stt_audio_bound_negative_invariant_total"]
            == baseline["audio_gateway_direct_stt_audio_bound_negative_invariant_total"],
        )
        report["metrics"]["afterFinish"] = final_metrics
        report["boundaries"]["sessionRegistryCapacityReused"] = True
        report["boundaries"]["aggregationReservationReleased"] = True
        report["boundaries"]["negativeInvariantStable"] = True
        report["status"] = "pass"
        return 0, report
    except Exception as exc:  # bounded below; no raw token/response is rendered.
        report["status"] = "fail"
        report["failureReason"] = str(exc)[:300]
        return 1, report
    finally:
        report["completedAt"] = _iso_z(dt.datetime.now(dt.timezone.utc))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", default=os.environ.get("TOKEN_FILE"))
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("FAZ24_BASE_URL", DEFAULT_PUBLIC_BASE_URL),
    )
    parser.add_argument("--audio-base-url", required=True)
    parser.add_argument("--metrics-base-url", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--pod-uid", required=True)
    parser.add_argument("--expected-issuer", default=DEFAULT_EXPECTED_ISSUER)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--metric-wait-seconds", type=int, default=15)
    parser.add_argument("--expiry-wait-seconds", type=int, default=90)
    parser.add_argument("--output-file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    exit_code, report = run_smoke(args)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
