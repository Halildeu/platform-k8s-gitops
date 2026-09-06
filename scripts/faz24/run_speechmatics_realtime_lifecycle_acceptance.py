#!/usr/bin/env python3
"""Exercise Speechmatics realtime streaming and durable Meeting Intelligence read-back.

The helper keeps bearer, audio, and transcript text in memory only. Its output is a
metadata-only acceptance receipt suitable for the existing Faz 24 evidence workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import ssl
import stat
import struct
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "faz24.speechmaticsRealtimeLifecycleAcceptance.v1"
DEFAULT_BASE_URL = "https://testai.acik.com"
KEYWORDS = ("bütçe", "proje", "görev", "karar", "sorumlu", "tarih", "rapor")
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
EXPECTED_FIXTURE_SHA256 = (
    "a759fd250937a70c4a780c8e6118f0bd5f4ff5f68b40f5d007bbae5bdc08775f"
)


class AcceptanceError(RuntimeError):
    """Bounded acceptance failure that is safe to persist in metadata evidence."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent bearer-bearing requests from following redirects to another origin."""

    def redirect_request(self, request: Any, *args: Any, **kwargs: Any) -> None:
        return None


def iso_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def read_token(path: Path) -> str:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AcceptanceError("token-file-permissions-too-open")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise AcceptanceError("token-empty")
    return token


def bounded_url(base_url: str, path: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "testai.acik.com"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise AcceptanceError("base-url-outside-test-allowlist")
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def auth_headers(token: str, **extra: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Correlation-Id": "faz24-realtime-" + uuid.uuid4().hex,
        **extra,
    }


def http_json(
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected: set[int],
    timeout_seconds: float,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        bounded_url(base_url, path),
        data=payload,
        method=method,
        headers=auth_headers(
            token,
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        ),
    )
    try:
        with urllib.request.build_opener(NoRedirectHandler()).open(
            request, timeout=timeout_seconds
        ) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
    if status not in expected:
        code = f"{method.lower()}-{path.split('/')[-1]}-http-{status}"
        if status == 503:
            try:
                problem = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                problem = {}
            if isinstance(problem, dict):
                for field in ("detail", "reason", "message"):
                    reason = problem.get(field)
                    if reason in ("TRANSCRIPT_AUTHORIZATION_UNAVAILABLE", "TRANSCRIPT_READ_UNAVAILABLE"):
                        code += ":" + reason
                        break
        raise AcceptanceError(code)
    if not raw:
        return status, {}
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise AcceptanceError("http-response-not-object")
    return status, decoded


def create_lifecycle(
    *, base_url: str, token: str, timeout_seconds: float, statuses: dict[str, int]
) -> tuple[str, str, str]:
    now = dt.datetime.now(dt.timezone.utc)
    status, meeting = http_json(
        base_url=base_url,
        token=token,
        method="POST",
        path="/api/v1/admin/meetings",
        expected={201},
        timeout_seconds=timeout_seconds,
        body={
            "title": "Faz 24 Speechmatics realtime lifecycle acceptance",
            "description": "metadata-only synthetic TEST acceptance",
            "scheduledStart": (now + dt.timedelta(minutes=5))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "scheduledEnd": (now + dt.timedelta(minutes=35))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )
    statuses["createMeeting"] = status
    meeting_id = meeting.get("id")
    if not isinstance(meeting_id, str) or not meeting_id:
        raise AcceptanceError("create-meeting-missing-id")

    consent_hash = (
        "sha256:"
        + hashlib.sha256(b"Faz 24 Speechmatics synthetic TEST consent v1").hexdigest()
    )
    status, _ = http_json(
        base_url=base_url,
        token=token,
        method="POST",
        path="/api/v1/audio-gateway/consents",
        expected={201},
        timeout_seconds=timeout_seconds,
        body={
            "meetingId": meeting_id,
            "captureId": str(uuid.uuid4()),
            "consentVersion": "speechmatics-realtime-acceptance-v1",
            "consentTextHash": consent_hash,
            "locale": "tr-TR",
        },
    )
    statuses["recordConsent"] = status

    status, session = http_json(
        base_url=base_url,
        token=token,
        method="POST",
        path="/api/v1/audio-gateway/sessions",
        expected={200, 201},
        timeout_seconds=timeout_seconds,
        headers={"Idempotency-Key": "faz24-realtime-start-" + uuid.uuid4().hex},
        body={
            "meetingId": meeting_id,
            "deviceId": "codex-speechmatics-realtime-acceptance",
            "language": "tr",
            "audioFormat": "PCM16",
            "sampleRateHz": 16000,
            "channels": 1,
            "sttProvider": "speechmatics",
            "transcriptionMode": "realtime",
        },
    )
    statuses["startSession"] = status
    session_id = session.get("sessionId")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        raise AcceptanceError("start-session-missing-id")
    if session.get("sttProvider") != "speechmatics":
        raise AcceptanceError("start-session-provider-mismatch")
    if session.get("transcriptionMode") != "realtime":
        raise AcceptanceError("start-session-mode-mismatch")

    started_at = iso_now()
    status, lifecycle = http_json(
        base_url=base_url,
        token=token,
        method="PUT",
        path=f"/api/v1/admin/meetings/{meeting_id}/recording-lifecycle",
        expected={200},
        timeout_seconds=timeout_seconds,
        body={
            "externalSessionId": session_id,
            "startedAt": started_at,
            "endedAt": None,
        },
    )
    statuses["recordingLifecycleStart"] = status
    if lifecycle.get("externalSessionId") != session_id:
        raise AcceptanceError("recording-lifecycle-start-mismatch")
    return meeting_id, session_id, started_at


async def stream_audio(
    *, base_url: str, token: str, session_id: str, audio_path: Path
) -> dict[str, Any]:
    import websockets

    if hashlib.sha256(audio_path.read_bytes()).hexdigest() != EXPECTED_FIXTURE_SHA256:
        raise AcceptanceError("audio-fixture-sha256-mismatch")
    with wave.open(str(audio_path), "rb") as wav:
        if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (
            1,
            16000,
            2,
        ):
            raise AcceptanceError("audio-contract-mismatch")
        pcm = wav.readframes(wav.getnframes())

    metrics: dict[str, Any] = {
        "ready": False,
        "providerReady": False,
        "audioFrames": 0,
        "audioAcks": 0,
        "partialEvents": 0,
        "finalEvents": 0,
        "firstPartialMs": None,
        "firstFinalMs": None,
        "partialWhileSpeaking": False,
        "eofAck": False,
        "drained": False,
        "terminalTimeout": False,
        "keywordMatches": 0,
        "keywordTotal": len(KEYWORDS),
        "transcriptIncluded": False,
        "audioIncluded": False,
        "tokenIncluded": False,
    }
    transcript_fragments: list[str] = []
    ready = asyncio.Event()
    drained = asyncio.Event()
    started_at = 0.0
    sending_audio = False

    async def receive(socket: Any) -> None:
        nonlocal sending_audio
        async for raw in socket:
            if not isinstance(raw, str):
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            now = time.monotonic()
            if event_type == "ready":
                metrics["ready"] = True
                metrics["providerReady"] = (
                    event.get("live_model") == "speechmatics-realtime-v2"
                )
                ready.set()
            elif event_type == "audio_ack":
                metrics["audioAcks"] += 1
            elif event_type in {"partial", "final"}:
                metric = "partialEvents" if event_type == "partial" else "finalEvents"
                metrics[metric] += 1
                first_metric = (
                    "firstPartialMs" if event_type == "partial" else "firstFinalMs"
                )
                if metrics[first_metric] is None and started_at:
                    metrics[first_metric] = round((now - started_at) * 1000)
                if event_type == "partial":
                    metrics["partialWhileSpeaking"] |= sending_audio
                if isinstance(event.get("text"), str):
                    transcript_fragments.append(event["text"])
            elif event_type == "eof_ack":
                metrics["eofAck"] = True
            elif event_type == "drained":
                metrics["drained"] = True
                drained.set()
                return
            elif event_type == "error":
                raise AcceptanceError("provider-stream-error")

    parsed = urllib.parse.urlsplit(base_url)
    ws_url = urllib.parse.urlunsplit(
        (
            "wss",
            parsed.netloc,
            f"/api/v1/audio-gateway/sessions/{session_id}/stream",
            "",
            "",
        )
    )
    async with websockets.connect(
        ws_url,
        ssl=ssl.create_default_context(),
        additional_headers={
            "Authorization": f"Bearer {token}",
            "X-Correlation-Id": "faz24-realtime-ws-" + uuid.uuid4().hex,
        },
        open_timeout=20,
        close_timeout=5,
        max_size=1_048_576,
        ping_interval=20,
    ) as socket:
        receiver = asyncio.create_task(receive(socket))
        await asyncio.wait_for(ready.wait(), timeout=20)
        await socket.send(json.dumps({"type": "context", "terms": list(KEYWORDS)}))
        frame_bytes = 3200
        started_at = time.monotonic()
        sending_audio = True
        for sequence, offset in enumerate(range(0, len(pcm), frame_bytes)):
            chunk = pcm[offset : offset + frame_bytes]
            if len(chunk) % 2:
                chunk = chunk[:-1]
            frame = (
                struct.pack(">BQQH", 1, sequence, int(time.time() * 1000), len(chunk))
                + chunk
            )
            await socket.send(frame)
            metrics["audioFrames"] += 1
            await asyncio.sleep(len(chunk) / 2 / 16000)
        sending_audio = False
        await socket.send('{"type":"eof"}')
        try:
            await asyncio.wait_for(drained.wait(), timeout=35)
        except (TimeoutError, asyncio.TimeoutError):
            metrics["terminalTimeout"] = True
        if not receiver.done():
            receiver.cancel()
        results = await asyncio.gather(receiver, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                raise result

    normalized = normalize(" ".join(transcript_fragments))
    metrics["keywordMatches"] = sum(
        normalize(keyword) in normalized for keyword in KEYWORDS
    )
    transcript_fragments.clear()
    return metrics


def finish_lifecycle(
    *,
    base_url: str,
    token: str,
    meeting_id: str,
    session_id: str,
    started_at: str,
    timeout_seconds: float,
    statuses: dict[str, int],
) -> tuple[bool, str]:
    status, _ = http_json(
        base_url=base_url,
        token=token,
        method="POST",
        path=f"/api/v1/audio-gateway/sessions/{session_id}/finish",
        expected={200},
        timeout_seconds=timeout_seconds,
        headers={"Idempotency-Key": "faz24-realtime-finish-" + uuid.uuid4().hex},
    )
    statuses["finishSession"] = status
    status, gateway = http_json(
        base_url=base_url,
        token=token,
        method="GET",
        path=f"/api/v1/audio-gateway/sessions/{session_id}/status",
        expected={200},
        timeout_seconds=timeout_seconds,
    )
    statuses["sessionStatus"] = status
    status, lifecycle = http_json(
        base_url=base_url,
        token=token,
        method="PUT",
        path=f"/api/v1/admin/meetings/{meeting_id}/recording-lifecycle",
        expected={200},
        timeout_seconds=timeout_seconds,
        body={
            "externalSessionId": session_id,
            "startedAt": started_at,
            "endedAt": iso_now(),
        },
    )
    statuses["recordingLifecycleFinish"] = status
    canonical_session_id = lifecycle.get("sessionId")
    if not isinstance(canonical_session_id, str) or not canonical_session_id:
        raise AcceptanceError("recording-lifecycle-canonical-session-missing")
    return gateway.get("state") == "FINISHED", canonical_session_id


def product_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Strict requirements for this fixed decision/action-bearing audio fixture."""
    summary = result.get("summary")
    decisions = result.get("decisions")
    actions = result.get("action_items")
    nonempty = lambda value: isinstance(value, str) and bool(value.strip())
    decision_count = sum(nonempty(x) for x in decisions) if isinstance(decisions, list) else 0
    action_count = sum(
        isinstance(x, dict) and nonempty(x.get("text")) for x in actions
    ) if isinstance(actions, list) else 0
    usable = all((
        result.get("persisted") is True,
        nonempty(result.get("analysisRunId")),
        nonempty(summary),
        result.get("summary_grounding_status") == "verified",
        decision_count > 0,
        action_count > 0,
    ))
    return {
        "summaryCharacters": len(summary.strip()) if isinstance(summary, str) else 0,
        "summaryVerified": result.get("summary_grounding_status") == "verified",
        "decisionCount": decision_count,
        "actionCount": action_count,
        "usableProductResult": usable,
    }


def result_fingerprint(result: dict[str, Any]) -> str:
    fields = ("analysisRunId", "meetingId", "sessionId", "summary",
              "summary_grounding_status", "summary_citations", "decisions",
              "action_items", "citations", "persisted")
    encoded = json.dumps({key: result.get(key) for key in fields}, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def durable_readback(
    *,
    base_url: str,
    token: str,
    meeting_id: str,
    canonical_session_id: str,
    timeout_seconds: float,
    poll_timeout_seconds: int,
    statuses: dict[str, int],
) -> dict[str, Any]:
    deadline = time.monotonic() + poll_timeout_seconds
    transcript_count = 0
    transcript_status_counts: dict[str, int] = {}
    result_session_match = False
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, page = http_json(
            base_url=base_url,
            token=token,
            method="GET",
            path=(
                "/api/v1/admin/transcripts?"
                + urllib.parse.urlencode(
                    {"sessionId": canonical_session_id, "page": 0, "size": 200}
                )
            ),
            expected={200},
            timeout_seconds=timeout_seconds,
        )
        statuses["transcriptRead"] = status
        content = page.get("content")
        if isinstance(content, list):
            transcript_count = int(page.get("totalElements", len(content)))
            counts: dict[str, int] = {}
            for item in content:
                if isinstance(item, dict):
                    item_status = str(item.get("status", "UNKNOWN"))
                    counts[item_status] = counts.get(item_status, 0) + 1
            transcript_status_counts = dict(sorted(counts.items()))

        try:
            status, result = http_json(
                base_url=base_url,
                token=token,
                method="GET",
                path=f"/api/v1/admin/meetings/{meeting_id}/intelligence/result",
                expected={200},
                timeout_seconds=timeout_seconds,
            )
            statuses["intelligenceResult"] = status
            result_session_match = (
                str(result.get("sessionId")) == canonical_session_id
                and result.get("meetingId") == meeting_id
            )
        except AcceptanceError as error:
            if not str(error).endswith("http-404"):
                raise
            statuses["intelligenceResult"] = 404
        if transcript_count > 0 and result_session_match:
            break
        time.sleep(5)

    return {
        "canonicalSessionId": canonical_session_id,
        "transcriptCount": transcript_count,
        "transcriptStatusCounts": transcript_status_counts,
        "intelligenceResultSessionMatch": result_session_match,
        "durableApiReadBackProven": result_session_match,
        **product_evidence(result),
        **(reopen_evidence(
            base_url=base_url, token=token, meeting_id=meeting_id,
            canonical_session_id=canonical_session_id, result=result,
            timeout_seconds=timeout_seconds, statuses=statuses,
        ) if result_session_match else {
            "sameResultReopened": False, "canonicalSourceReadBackProven": False,
        }),
        "containsTranscriptText": False,
    }


def reopen_evidence(
    *, base_url: str, token: str, meeting_id: str, canonical_session_id: str,
    result: dict[str, Any], timeout_seconds: float, statuses: dict[str, int],
) -> dict[str, Any]:
    evidence = {"sameResultReopened": False, "canonicalSourceReadBackProven": False}
    try:
        run_id = str(uuid.UUID(str(result.get("analysisRunId"))))
    except (ValueError, TypeError, AttributeError):
        return evidence
    try:
        status, source = http_json(
            base_url=base_url, token=token, method="GET",
            path=f"/api/v1/admin/meetings/{meeting_id}/intelligence/results/{run_id}/transcript",
            expected={200}, timeout_seconds=timeout_seconds,
        )
        statuses["canonicalSource"] = status
    except AcceptanceError as error:
        source = {}
        evidence["canonicalSourceErrorCode"] = str(error)
    transcript = source.get("transcript")
    evidence["canonicalSourceReadBackProven"] = all((
        source.get("analysisRunId") == run_id,
        source.get("meetingId") == meeting_id,
        str(source.get("sessionId")) == canonical_session_id,
        isinstance(transcript, str) and bool(transcript.strip()),
        isinstance(transcript, str) and hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        == source.get("transcriptSha256"),
    ))
    status, reopened = http_json(
        base_url=base_url, token=token, method="GET",
        path=f"/api/v1/admin/meetings/{meeting_id}/intelligence/result",
        expected={200}, timeout_seconds=timeout_seconds,
    )
    statuses["intelligenceReopen"] = status
    evidence["sameResultReopened"] = result_fingerprint(result) == result_fingerprint(reopened)
    evidence["resultFingerprintSha256"] = result_fingerprint(result)
    evidence["browserCitationInteractionProven"] = False
    return evidence


async def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    token = read_token(Path(args.token_file))
    statuses: dict[str, int] = {}
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "running",
        "startedAt": iso_now(),
        "baseUrl": DEFAULT_BASE_URL,
        "provider": "speechmatics",
        "mode": "realtime",
        "tokenIncluded": False,
        "transcriptIncluded": False,
        "audioIncluded": False,
        "http": statuses,
    }
    meeting_id: str | None = None
    session_id: str | None = None
    started_at: str | None = None
    canonical_session_id: str | None = None
    try:
        meeting_id, session_id, started_at = create_lifecycle(
            base_url=args.base_url,
            token=token,
            timeout_seconds=args.timeout_seconds,
            statuses=statuses,
        )
        report["meetingId"] = meeting_id
        report["sessionId"] = session_id
        report["stream"] = await stream_audio(
            base_url=args.base_url,
            token=token,
            session_id=session_id,
            audio_path=Path(args.audio_file),
        )
    finally:
        if meeting_id and session_id and started_at:
            try:
                report["sessionFinished"], canonical_session_id = finish_lifecycle(
                    base_url=args.base_url,
                    token=token,
                    meeting_id=meeting_id,
                    session_id=session_id,
                    started_at=started_at,
                    timeout_seconds=args.timeout_seconds,
                    statuses=statuses,
                )
            except Exception as error:  # noqa: BLE001 - receipt keeps class only.
                report["sessionFinished"] = False
                report["finishErrorClass"] = error.__class__.__name__

    if report.get("sessionFinished") is True and canonical_session_id:
        report["durable"] = durable_readback(
            base_url=args.base_url,
            token=token,
            meeting_id=meeting_id,
            canonical_session_id=canonical_session_id,
            timeout_seconds=args.timeout_seconds,
            poll_timeout_seconds=args.durable_timeout_seconds,
            statuses=statuses,
        )

    stream = report.get("stream", {})
    durable = report.get("durable", {})
    passed = all(
        (
            report.get("sessionFinished") is True,
            stream.get("ready") is True,
            stream.get("providerReady") is True,
            stream.get("partialWhileSpeaking") is True,
            stream.get("partialEvents", 0) > 0,
            stream.get("finalEvents", 0) > 0,
            stream.get("keywordMatches", 0) >= 4,
            stream.get("eofAck") is True,
            stream.get("drained") is True,
            stream.get("terminalTimeout") is False,
            durable.get("transcriptCount", 0) > 0,
            durable.get("intelligenceResultSessionMatch") is True,
            durable.get("durableApiReadBackProven") is True,
            durable.get("usableProductResult") is True,
            durable.get("sameResultReopened") is True,
            durable.get("canonicalSourceReadBackProven") is True,
        )
    )
    report["status"] = "pass" if passed else "fail"
    report["completedAt"] = iso_now()
    return (0 if passed else 1), report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--audio-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--durable-timeout-seconds", type=int, default=720)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        exit_code, report = asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 - output is bounded metadata only.
        exit_code = 2
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "error",
            "errorClass": error.__class__.__name__,
            "errorCode": str(error)[:160],
            "tokenIncluded": False,
            "transcriptIncluded": False,
            "audioIncluded": False,
            "completedAt": iso_now(),
        }
    write_private_json(Path(args.output_file), report)
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
