import base64
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/run_external_recorder_smoke.py"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(payload: dict) -> str:
    return ".".join(
        [
            _segment({"alg": "none", "typ": "JWT"}),
            _segment(payload),
            "signature",
        ]
    )


def _valid_token() -> str:
    return _token(
        {
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
    )


class _SmokeHandler(BaseHTTPRequestHandler):
    calls = []
    bearer_seen = False

    def log_message(self, *_args):  # pragma: no cover - keeps test output clean.
        return

    def _read_json(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        if not raw:
            return {}
        return json.loads(raw.decode())

    def _write(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _record(self):
        type(self).calls.append((self.command, self.path))
        if self.headers.get("Authorization", "").startswith("Bearer "):
            type(self).bearer_seen = True

    def do_POST(self):
        self._record()
        if self.path == "/api/v1/admin/meetings":
            body = self._read_json()
            assert body["title"]
            self._write(
                201,
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "status": "SCHEDULED",
                    "title": body["title"],
                },
            )
            return

        if self.path == "/api/v1/audio-gateway/consents":
            body = self._read_json()
            assert body["meetingId"] == "22222222-2222-4222-8222-222222222222"
            assert body["consentTextHash"].startswith("sha256:")
            self._write(
                201,
                {
                    "meetingId": body["meetingId"],
                    "captureId": body["captureId"],
                    "correlationId": "corr-consent",
                    "acceptedAtMs": 1782370000000,
                },
            )
            return

        if self.path == "/api/v1/audio-gateway/sessions":
            body = self._read_json()
            assert body["meetingId"] == "22222222-2222-4222-8222-222222222222"
            assert self.headers["Idempotency-Key"].startswith("faz24-start-")
            self._write(
                201,
                {
                    "sessionId": "SES-test-1",
                    "correlationId": "corr-start",
                    "statusUrl": "/api/v1/audio-gateway/sessions/SES-test-1/status",
                    "finishUrl": "/api/v1/audio-gateway/sessions/SES-test-1/finish",
                    "sessionStartMs": 1782370000001,
                },
            )
            return

        if self.path == "/api/v1/audio-gateway/sessions/SES-test-1/chunks":
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            assert self.headers["X-Audio-Chunk-Seq"] == "0"
            assert self.headers["X-Audio-Format"] == "PCM16"
            assert self.headers["X-Audio-Sample-Rate-Hz"] == "16000"
            assert self.headers["X-Audio-Channels"] == "1"
            assert self.headers["X-Audio-Byte-Length"] == str(len(raw))
            self._write(
                200,
                {
                    "sessionId": "SES-test-1",
                    "correlationId": "corr-chunk",
                    "chunkSeq": 0,
                    "chunkCount": 1,
                    "receivedAtMs": 1782370000002,
                    "replayed": False,
                },
            )
            return

        if self.path == "/api/v1/audio-gateway/sessions/SES-test-1/finish":
            assert self.headers["Idempotency-Key"].startswith("faz24-finish-")
            self._write(
                200,
                {
                    "sessionId": "SES-test-1",
                    "correlationId": "corr-finish",
                    "finalState": "FINISHED",
                    "finishedAtMs": 1782370000003,
                    "alreadyFinished": False,
                },
            )
            return

        self._write(404, {"error": "not_found"})

    def do_GET(self):
        self._record()
        if self.path == "/api/v1/audio-gateway/sessions/SES-test-1/status":
            self._write(
                200,
                {
                    "sessionId": "SES-test-1",
                    "correlationId": "corr-status",
                    "state": "FINISHED",
                    "chunkCount": 1,
                    "lastChunkSeq": 0,
                },
            )
            return
        self._write(404, {"error": "not_found"})


class _ForbiddenMeetingHandler(_SmokeHandler):
    def do_POST(self):
        if self.path == "/api/v1/admin/meetings":
            self._record()
            self._write(403, {"error": "forbidden"})
            return
        super().do_POST()


class _MissingMeetingIdHandler(_SmokeHandler):
    def do_POST(self):
        if self.path == "/api/v1/admin/meetings":
            self._record()
            self._write(201, {"status": "SCHEDULED"})
            return
        super().do_POST()


class _ProcessingStatusHandler(_SmokeHandler):
    def do_GET(self):
        self._record()
        if self.path == "/api/v1/audio-gateway/sessions/SES-test-1/status":
            self._write(
                200,
                {
                    "sessionId": "SES-test-1",
                    "correlationId": "corr-status",
                    "state": "PROCESSING",
                    "chunkCount": 1,
                    "lastChunkSeq": 0,
                },
            )
            return
        self._write(404, {"error": "not_found"})


class _SensitiveResponseHandler(_SmokeHandler):
    def do_POST(self):
        if self.path == "/api/v1/admin/meetings":
            self._record()
            body = self._read_json()
            assert body["title"]
            self._write(
                201,
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "status": "SCHEDULED",
                    "accessToken": "should-not-appear",
                    "destinationUrl": "https://internal.example.invalid/callback",
                    "audioPreview": "data:audio/wav;base64,QUJDRA==",
                    "nested": {
                        "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzbW9rZSJ9.signature"
                    },
                },
            )
            return
        super().do_POST()


class _UnsafeSessionIdHandler(_SmokeHandler):
    def do_POST(self):
        if self.path == "/api/v1/audio-gateway/sessions":
            self._record()
            body = self._read_json()
            assert body["meetingId"] == "22222222-2222-4222-8222-222222222222"
            self._write(
                201,
                {
                    "sessionId": "SES-../../secret",
                    "correlationId": "corr-start",
                    "sessionStartMs": 1782370000001,
                },
            )
            return
        super().do_POST()


def _serve(handler_cls):
    handler_cls.calls = []
    handler_cls.bearer_seen = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_external_recorder_smoke_happy_path_redacts_token(tmp_path):
    token = _valid_token()
    token_file = tmp_path / "token.jwt"
    token_file.write_text(token, encoding="utf-8")
    server = _serve(_SmokeHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert token not in proc.stdout
    assert token not in proc.stderr
    assert report["ids"]["meetingId"] == "22222222-2222-4222-8222-222222222222"
    assert report["ids"]["sessionId"] == "SES-test-1"
    assert report["sample"]["chunkSeq"] == 0
    assert report["sample"]["sampleSha256"]
    assert report["sample"]["audioFormat"] == "PCM16"
    assert report["sample"]["sampleRateHz"] == 16000
    assert report["sample"]["rawAudioIncluded"] is False
    assert "audioBytes" not in report["sample"]
    assert report["boundaries"]["externalMeetingAdminPathExercised"] is True
    assert report["boundaries"]["recorderLifecycleExercised"] is True
    assert report["boundaries"]["directSttProven"] is False
    assert report["boundaries"]["directSttTranscriptProven"] is False
    assert report["boundaries"]["directClientToStt"] is False
    assert report["boundaries"]["computePlaneAuditProven"] is False
    assert _SmokeHandler.bearer_seen is True
    assert _SmokeHandler.calls == [
        ("POST", "/api/v1/admin/meetings"),
        ("POST", "/api/v1/audio-gateway/consents"),
        ("POST", "/api/v1/audio-gateway/sessions"),
        ("POST", "/api/v1/audio-gateway/sessions/SES-test-1/chunks"),
        ("POST", "/api/v1/audio-gateway/sessions/SES-test-1/finish"),
        ("GET", "/api/v1/audio-gateway/sessions/SES-test-1/status"),
    ]


def test_output_file_is_written_with_owner_only_permissions(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    output_file = tmp_path / "evidence.json"
    server = _serve(_SmokeHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
                "--output-file",
                str(output_file),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    assert proc.returncode == 0
    assert json.loads(output_file.read_text(encoding="utf-8"))["status"] == "pass"
    assert output_file.stat().st_mode & 0o777 == 0o600


def test_sensitive_response_fields_are_omitted_or_redacted(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    server = _serve(_SensitiveResponseHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 0
    rendered = json.dumps(report)
    assert "accessToken" not in rendered
    assert "destinationUrl" not in rendered
    assert "audioPreview" not in rendered
    assert "Authorization" not in rendered
    assert "should-not-appear" not in rendered
    assert "internal.example.invalid" not in rendered
    assert "data:audio" not in rendered
    assert "Bearer " not in rendered
    assert report["steps"][1]["response"]["redactedFieldCount"] == 3
    assert report["steps"][1]["response"]["nested"]["redactedFieldCount"] == 1


def test_unsafe_session_id_response_returns_error_envelope(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    server = _serve(_UnsafeSessionIdHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert report["status"] == "error"
    assert "unsafe sessionId" in report["error"]


def test_create_meeting_http_failure_stops_before_later_steps(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    server = _serve(_ForbiddenMeetingHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["steps"][-1]["name"] == "create_meeting"
    assert report["steps"][-1]["statusCode"] == 403
    assert _ForbiddenMeetingHandler.calls == [("POST", "/api/v1/admin/meetings")]


def test_missing_meeting_id_response_returns_error_envelope(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    server = _serve(_MissingMeetingIdHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert report["status"] == "error"
    assert "missing 'id'" in report["error"]


def test_non_finished_status_fails(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(_valid_token(), encoding="utf-8")
    server = _serve(_ProcessingStatusHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["steps"][-1]["name"] == "session_status"
    assert any("state is not FINISHED" in failure for failure in report["failures"])


def test_token_contract_failure_stops_before_http(tmp_path):
    token = _token(
        {
            "iss": "https://testai.acik.com/realms/platform-test",
            "azp": "platform-desktop",
            "aud": ["audio-gateway-service", "meeting-service"],
            "tenantId": "1",
            "companyId": "1",
            "userId": "990001",
            "realm_access": {"roles": ["MEETING_ADMIN"]},
        }
    )
    token_file = tmp_path / "token.jwt"
    token_file.write_text(token, encoding="utf-8")
    server = _serve(_SmokeHandler)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-file",
                str(token_file),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "3",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        server.shutdown()

    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["steps"][0]["name"] == "token_contract"
    assert any("api-gateway-compatible" in failure for failure in report["failures"])
    assert _SmokeHandler.calls == []
