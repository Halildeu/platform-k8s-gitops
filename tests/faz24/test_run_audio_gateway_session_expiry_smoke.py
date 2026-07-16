import base64
import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/run_audio_gateway_session_expiry_smoke.py"
MEETING_ID = "22222222-2222-4222-8222-222222222222"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _valid_token() -> str:
    payload = {
        "iss": "https://testai.acik.com/realms/platform-test",
        "sub": "11111111-2222-3333-8444-555555555555",
        "azp": "platform-desktop",
        "aud": ["audio-gateway-service", "meeting-service", "frontend"],
        "org_id": "68c73eb9-c410-37dc-aff7-5ade8fbbcbb7",
        "tenant_id": "68c73eb9-c410-37dc-aff7-5ade8fbbcbb7",
        "tenantId": "1",
        "companyId": "1",
        "userId": "990001",
        "realm_access": {"roles": ["MEETING_ADMIN"]},
        "resource_access": {
            "audio-gateway-service": {"roles": ["audio_record"]}
        },
    }
    return ".".join(
        [_segment({"alg": "none", "typ": "JWT"}), _segment(payload), "signature"]
    )


class _ExpiryHandler(BaseHTTPRequestHandler):
    session_starts = 0
    active = False
    capacity_rejected = False
    expired = 0
    chunks = 0
    negative_after_expiry = False
    buffer_after_finish = False
    finished = False
    bearer_seen = False
    redirect_sessions_to = None

    def log_message(self, *_args):  # pragma: no cover - keep test output clean.
        return

    def _record_auth(self):
        if self.headers.get("Authorization", "").startswith("Bearer "):
            type(self).bearer_seen = True

    def _read_json(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        return json.loads(raw.decode()) if raw else {}

    def _write_json(self, status: int, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _write_metrics(self):
        cls = type(self)
        if cls.capacity_rejected and cls.expired == 0:
            cls.expired = 1
            cls.active = False
        negative = 1 if cls.negative_after_expiry and cls.expired else 0
        active = 1 if cls.active else 0
        reserved = 1600 if cls.active else 0
        buffered_bytes = 3200 * active
        if cls.finished and cls.buffer_after_finish:
            buffered_bytes = 3200
        values = {
            "audio_gateway_session_expired_total": cls.expired,
            "audio_gateway_session_expiry_cleanup_error_total": 0,
            "audio_gateway_direct_stt_aggregation_active_sessions": active,
            "audio_gateway_direct_stt_aggregation_buffered_bytes": buffered_bytes,
            "audio_gateway_direct_stt_audio_bound_reserved_frames": reserved,
            "audio_gateway_direct_stt_audio_bound_active_sessions": active,
            "audio_gateway_direct_stt_audio_bound_negative_invariant_total": negative,
            "audio_gateway_direct_stt_aggregation_chunks_buffered_total": cls.chunks,
            "audio_gateway_direct_stt_aggregation_dropped_capacity_total": 0,
        }
        raw = "".join(f"{name} {value}\n" for name, value in values.items()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self._record_auth()
        cls = type(self)
        if self.path == "/api/v1/admin/meetings":
            assert self._read_json()["title"]
            self._write_json(201, {"id": MEETING_ID, "status": "SCHEDULED"})
            return
        if self.path == "/api/v1/audio-gateway/consents":
            assert self._read_json()["meetingId"] == MEETING_ID
            self._write_json(201, {"meetingId": MEETING_ID, "acceptedAtMs": 1})
            return
        if self.path == "/api/v1/audio-gateway/sessions":
            assert self._read_json()["meetingId"] == MEETING_ID
            if cls.redirect_sessions_to:
                self.send_response(307)
                self.send_header("Location", cls.redirect_sessions_to)
                self.end_headers()
                return
            cls.session_starts += 1
            if cls.session_starts == 2:
                cls.capacity_rejected = True
                self._write_json(
                    503,
                    {"code": "AUDIO_GATEWAY_SESSION_REGISTRY_FULL", "message": "full"},
                )
                return
            cls.active = True
            session_id = "SES-expired-1" if cls.session_starts == 1 else "SES-reused-1"
            self._write_json(201, {"sessionId": session_id, "sessionStartMs": 1})
            return
        if self.path.endswith("/chunks"):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            assert len(raw) == 3200
            assert self.headers["X-Audio-Format"] == "PCM16"
            cls.chunks += 1
            self._write_json(200, {"chunkSeq": 0, "chunkCount": 1})
            return
        if self.path == "/api/v1/audio-gateway/sessions/SES-reused-1/finish":
            cls.active = False
            cls.finished = True
            self._write_json(200, {"sessionId": "SES-reused-1", "finalState": "FINISHED"})
            return
        self._write_json(404, {"code": "NOT_FOUND"})

    def do_GET(self):
        self._record_auth()
        if self.path == "/actuator/prometheus":
            self._write_metrics()
            return
        if self.path == "/api/v1/audio-gateway/sessions/SES-expired-1/status":
            self._write_json(404, {"code": "AUDIO_GATEWAY_SESSION_NOT_FOUND"})
            return
        self._write_json(404, {"code": "NOT_FOUND"})


class _TokenSinkHandler(BaseHTTPRequestHandler):
    bearer_seen = False

    def log_message(self, *_args):  # pragma: no cover - keep test output clean.
        return

    def do_POST(self):
        type(self).bearer_seen = self.headers.get("Authorization", "").startswith("Bearer ")
        self.send_response(200)
        self.end_headers()


def _serve(
    *,
    negative_after_expiry: bool = False,
    buffer_after_finish: bool = False,
    redirect_sessions_to=None,
):
    _ExpiryHandler.session_starts = 0
    _ExpiryHandler.active = False
    _ExpiryHandler.capacity_rejected = False
    _ExpiryHandler.expired = 0
    _ExpiryHandler.chunks = 0
    _ExpiryHandler.negative_after_expiry = negative_after_expiry
    _ExpiryHandler.buffer_after_finish = buffer_after_finish
    _ExpiryHandler.finished = False
    _ExpiryHandler.bearer_seen = False
    _ExpiryHandler.redirect_sessions_to = redirect_sessions_to
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ExpiryHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _run(
    tmp_path: Path,
    server,
    *,
    output_file: Path | None = None,
    env_overrides: dict[str, str] | None = None,
):
    token = _valid_token()
    token_file = tmp_path / "token.jwt"
    token_file.write_text(token, encoding="utf-8")
    base_url = f"http://127.0.0.1:{server.server_port}"
    command = [
        sys.executable,
        str(SCRIPT),
        "--token-file",
        str(token_file),
        "--public-base-url",
        base_url,
        "--audio-base-url",
        base_url,
        "--metrics-base-url",
        base_url,
        "--expected-image",
        "ghcr.io/halildeu/platform-backend-audio-gateway-service@sha256:"
        + "1" * 64,
        "--pod-uid",
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "--timeout-seconds",
        "3",
        "--metric-wait-seconds",
        "2",
        "--expiry-wait-seconds",
        "2",
    ]
    if output_file:
        command.extend(["--output-file", str(output_file)])
    run_env = os.environ.copy()
    if env_overrides:
        run_env.update(env_overrides)
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=run_env,
    )
    return token, proc


def test_expiry_smoke_proves_cleanup_and_capacity_reuse_without_token(tmp_path):
    output_file = tmp_path / "evidence.json"
    server = _serve()
    try:
        token, proc = _run(tmp_path, server, output_file=output_file)
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert report["boundaries"]["managedWorkloadMutated"] is False
    assert report["boundaries"]["sessionRegistryCapacityReused"] is True
    assert report["boundaries"]["aggregationReservationReleased"] is True
    assert report["boundaries"]["negativeInvariantStable"] is True
    assert report["ids"]["captureId"]
    assert report["runtimeEvidence"]["podUid"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert report["runtimeEvidence"]["image"].endswith("@sha256:" + "1" * 64)
    assert report["runtimeEvidence"]["effectiveOverrides"]["dispatcherMode"] == "noop"
    assert report["metrics"]["afterExpiry"]["audio_gateway_session_expired_total"] == 1
    assert report["metrics"]["afterFinish"]["audio_gateway_direct_stt_audio_bound_reserved_frames"] == 0
    assert token not in proc.stdout
    assert token not in proc.stderr
    assert token not in output_file.read_text(encoding="utf-8")
    assert stat.S_IMODE(output_file.stat().st_mode) == 0o600
    assert _ExpiryHandler.bearer_seen is True


def test_expiry_smoke_does_not_follow_authenticated_redirect(tmp_path):
    _TokenSinkHandler.bearer_seen = False
    sink = ThreadingHTTPServer(("127.0.0.1", 0), _TokenSinkHandler)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    redirect_target = f"http://127.0.0.1:{sink.server_port}/token-sink"
    server = _serve(redirect_sessions_to=redirect_target)
    try:
        token, proc = _run(tmp_path, server)
    finally:
        server.shutdown()
        sink.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["steps"][-1]["statusCode"] == 307
    assert report["steps"][-1]["redirectFollowed"] is False
    assert _TokenSinkHandler.bearer_seen is False
    assert token not in proc.stdout
    assert token not in proc.stderr


def test_expiry_smoke_bypasses_hostile_proxy_for_loopback_bearer(tmp_path):
    _TokenSinkHandler.bearer_seen = False
    sink = ThreadingHTTPServer(("127.0.0.1", 0), _TokenSinkHandler)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    server = _serve()
    proxy_url = f"http://127.0.0.1:{sink.server_port}"
    try:
        token, proc = _run(
            tmp_path,
            server,
            env_overrides={
                "HTTP_PROXY": proxy_url,
                "http_proxy": proxy_url,
                "NO_PROXY": "",
                "no_proxy": "",
            },
        )
    finally:
        server.shutdown()
        sink.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert _TokenSinkHandler.bearer_seen is False
    assert token not in proc.stdout
    assert token not in proc.stderr


def test_expiry_smoke_fails_when_negative_invariant_moves(tmp_path):
    server = _serve(negative_after_expiry=True)
    try:
        token, proc = _run(tmp_path, server)
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["boundaries"]["negativeInvariantStable"] is False
    assert "metric convergence timeout" in report["failureReason"]
    assert token not in proc.stdout
    assert token not in proc.stderr


def test_expiry_smoke_fails_when_finish_leaves_buffered_bytes(tmp_path):
    server = _serve(buffer_after_finish=True)
    try:
        token, proc = _run(tmp_path, server)
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["boundaries"]["aggregationReservationReleased"] is False
    assert "metric convergence timeout" in report["failureReason"]
    assert token not in proc.stdout
    assert token not in proc.stderr
