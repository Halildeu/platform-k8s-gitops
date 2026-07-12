import base64
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "faz24"
    / "run_meeting_ai_private_runtime_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("meeting_ai_runtime_smoke", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


def _jwt() -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": "auth-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "svc": "meeting-ai",
        "aud": ["meeting-service"],
        "perm": ["meeting:analysis-result:write"],
        "iat": now,
        "exp": now + 60,
    }

    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment(header)}.{segment(payload)}.signature"


def test_claim_summary_enforces_exact_client_audience_permission_and_ttl():
    summary = smoke.summarize_and_validate_claims(_jwt())
    assert summary == {
        "issuer": "auth-service",
        "subject": "meeting-ai",
        "clientId": "meeting-ai",
        "service": "meeting-ai",
        "audience": ["meeting-service"],
        "permissions": ["meeting:analysis-result:write"],
        "ttlSeconds": 60,
    }


def test_runtime_matrix_records_only_metadata_and_expected_statuses():
    valid_token = _jwt()
    calls = []

    def fake_secret_loader(*_args):
        return "x" * 48

    def fake_request(base_url, host_header, method, path, headers, body, timeout):
        calls.append((base_url, host_header, method, path, headers, body, timeout))
        if path == "/oauth2/token":
            form = body.decode()
            authorization = headers["Authorization"]
            if base64.b64encode(b"meeting-ai:" + (b"x" * 48)).decode() not in authorization:
                return smoke.HttpResult(401, b'{"error":"invalid_client"}')
            if "audience=not-allowed" in form:
                return smoke.HttpResult(400, b'{"error":"invalid_audience"}')
            if "permissions=permissions%3Awrite" in form or "permissions=" not in form:
                return smoke.HttpResult(400, b'{"error":"invalid_permission"}')
            return smoke.HttpResult(
                200,
                json.dumps({"access_token": valid_token, "token_type": "Bearer"}).encode(),
            )
        authorization = headers.get("Authorization")
        if authorization is None or authorization == "Bearer not-a-jwt":
            return smoke.HttpResult(401, b'{"error":"unauthorized"}')
        previous = [call for call in calls[:-1] if call[3] == path and call[4].get("Authorization") == authorization]
        if not previous:
            return smoke.HttpResult(201, b'{"persisted":true}')
        if previous[-1][5] == body:
            return smoke.HttpResult(200, b'{"idempotent_replay":true}')
        return smoke.HttpResult(409, b'{"error":"IDEMPOTENCY_CONFLICT"}')

    meeting_id = uuid.uuid4()
    evidence, accepted = smoke.run_smoke(
        context="k3d-test",
        namespace="platform-test",
        secret_name="auth-service-meeting-ai-secret",
        secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
        base_url="http://127.0.0.1:31080",
        host_header="meeting-ai-private.testai.internal",
        meeting_id=meeting_id,
        write_synthetic_result=True,
        timeout_seconds=10,
        secret_loader=fake_secret_loader,
        request=fake_request,
    )

    assert accepted is True
    assert evidence["accepted"] is True
    assert evidence["syntheticWrite"]["meetingId"] == str(meeting_id)
    assert [item["actualStatus"] for item in evidence["checks"] if isinstance(item["actualStatus"], int)] == [
        401,
        400,
        400,
        400,
        200,
        401,
        401,
        201,
        200,
        409,
    ]
    serialized = json.dumps(evidence)
    assert "x" * 48 not in serialized
    assert valid_token not in serialized
    assert "Authorization" not in serialized


def test_write_evidence_is_mode_0600_and_rejects_symlink(tmp_path):
    output = tmp_path / "evidence.json"
    smoke.write_evidence(output, {"accepted": True})
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text()) == {"accepted": True}

    target = tmp_path / "target.json"
    target.write_text("{}")
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(target)
    try:
        smoke.write_evidence(symlink, {"accepted": False})
    except smoke.SmokeError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlink output must be rejected")


def test_cli_refuses_context_names_that_only_contain_test(tmp_path):
    output = tmp_path / "evidence.json"
    exit_code = smoke.main(
        [
            "--context",
            "production-test",
            "--namespace",
            "platform-test",
            "--meeting-id",
            str(uuid.uuid4()),
            "--write-synthetic-result",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 2
    assert not output.exists()


def test_library_call_refuses_non_test_target_before_secret_read():
    secret_read = False

    def fake_secret_loader(*_args):
        nonlocal secret_read
        secret_read = True
        return "x" * 48

    try:
        smoke.run_smoke(
            context="k3d-prod",
            namespace="platform",
            secret_name="auth-service-meeting-ai-secret",
            secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
            base_url="http://127.0.0.1:31080",
            host_header="meeting-ai-private.internal",
            meeting_id=uuid.uuid4(),
            write_synthetic_result=True,
            timeout_seconds=10,
            secret_loader=fake_secret_loader,
        )
    except smoke.SmokeError as exc:
        assert "non-test" in str(exc)
    else:
        raise AssertionError("library entry point must reject non-test targets")
    assert secret_read is False


def test_ingest_window_rejects_token_that_cannot_cover_bounded_http_calls():
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": "auth-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "svc": "meeting-ai",
        "aud": ["meeting-service"],
        "perm": ["meeting:analysis-result:write"],
        "iat": now,
        "exp": now + 30,
    }

    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = f"{segment(header)}.{segment(payload)}.signature"
    try:
        smoke.require_ingest_token_window(token, timeout_seconds=10)
    except smoke.SmokeError as exc:
        assert "insufficient lifetime" in str(exc)
    else:
        raise AssertionError("short-lived token must not enter the ingest matrix")


def test_token_only_run_cannot_claim_full_acceptance():
    valid_token = _jwt()

    def fake_secret_loader(*_args):
        return "x" * 48

    def fake_request(_base_url, _host_header, _method, _path, headers, body, _timeout):
        form = body.decode()
        expected = base64.b64encode(b"meeting-ai:" + (b"x" * 48)).decode()
        if expected not in headers["Authorization"]:
            return smoke.HttpResult(401, b'{"error":"invalid_client"}')
        if "audience=not-allowed" in form:
            return smoke.HttpResult(400, b'{"error":"invalid_audience"}')
        if "permissions=permissions%3Awrite" in form or "permissions=" not in form:
            return smoke.HttpResult(400, b'{"error":"invalid_permission"}')
        return smoke.HttpResult(200, json.dumps({"access_token": valid_token}).encode())

    evidence, accepted = smoke.run_smoke(
        context="k3d-test",
        namespace="platform-test",
        secret_name="auth-service-meeting-ai-secret",
        secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
        base_url="http://127.0.0.1:31080",
        host_header="meeting-ai-private.testai.internal",
        meeting_id=uuid.uuid4(),
        write_synthetic_result=False,
        timeout_seconds=10,
        secret_loader=fake_secret_loader,
        request=fake_request,
    )
    assert accepted is False
    assert evidence["accepted"] is False
    assert evidence["checks"][-1] == {
        "id": "synthetic-write-required",
        "expectedStatus": "enabled",
        "actualStatus": "disabled",
        "pass": False,
    }
