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


def _jwt(
    audience: str = "meeting-service",
    permission: str = "meeting:analysis-result:write",
) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": "auth-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "svc": "meeting-ai",
        "aud": [audience],
        "perm": [permission],
        "iat": now,
        "exp": now + 60,
    }

    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment(header)}.{segment(payload)}.signature"


def _capability_jwt(
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    finalization_version: int,
    analysis_run_id: uuid.UUID,
    analysis_spec_version: str,
    capability_id: uuid.UUID,
) -> tuple[str, str]:
    now = int(time.time())
    expires = now + 300
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": "transcript-service",
        "sub": "meeting-ai",
        "client_id": "meeting-ai",
        "aud": ["meeting-service"],
        "perm": "meeting:analysis-result:write",
        "jti": str(capability_id),
        "iat": now,
        "exp": expires,
        "tenant_id": str(tenant_id),
        "meeting_id": str(meeting_id),
        "session_id": str(session_id),
        "finalization_version": finalization_version,
        "finalized_at": "2026-07-29T07:00:00Z",
        "transcript_sha256": "a" * 64,
        "analysis_run_id": str(analysis_run_id),
        "analysis_spec_version": analysis_spec_version,
    }

    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = f"{segment(header)}.{segment(payload)}.signature"
    expires_header = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))
    return token, expires_header


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
    capability_service_token = _jwt(
        "transcript-service",
        "transcript:analysis-job-capability:issue",
    )
    tenant_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    session_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    analysis_spec_version = "meeting-intelligence-v1"
    calls = []
    capability_counter = 0
    ingest_bodies = []

    def fake_secret_loader(*_args):
        return "x" * 48

    def fake_request(base_url, host_header, method, path, headers, body, timeout):
        nonlocal capability_counter
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
            if "audience=transcript-service" in form:
                assert (
                    "permissions=transcript%3Aanalysis-job-capability%3Aissue"
                    in form
                )
                return smoke.HttpResult(
                    200,
                    json.dumps(
                        {
                            "access_token": capability_service_token,
                            "token_type": "Bearer",
                        }
                    ).encode(),
                )
            return smoke.HttpResult(
                200,
                json.dumps({"access_token": valid_token, "token_type": "Bearer"}).encode(),
            )
        if path.endswith("/analysis-capability"):
            assert method == "POST"
            assert body is None
            assert headers["X-Tenant-Id"] == str(tenant_id)
            assert headers["X-Analysis-Run-Id"] == str(analysis_run_id)
            assert headers["X-Analysis-Spec-Version"] == analysis_spec_version
            capability_counter += 1
            capability, expires_header = _capability_jwt(
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                session_id=session_id,
                finalization_version=1,
                analysis_run_id=analysis_run_id,
                analysis_spec_version=analysis_spec_version,
                capability_id=uuid.UUID(int=capability_counter),
            )
            return smoke.HttpResult(
                204,
                b"",
                {
                    "x-analysis-job-capability": capability,
                    "x-analysis-job-capability-expires-at": expires_header,
                },
            )
        authorization = headers.get("Authorization")
        if authorization is None or authorization == "Bearer not-a-jwt":
            return smoke.HttpResult(401, b'{"error":"unauthorized"}')
        assert headers.get("X-Analysis-Job-Capability")
        ingest_bodies.append(body)
        if len(ingest_bodies) == 1:
            return smoke.HttpResult(201, b'{"persisted":true}')
        if ingest_bodies[-2] == body:
            return smoke.HttpResult(200, b'{"idempotent_replay":true}')
        return smoke.HttpResult(409, b'{"error":"IDEMPOTENCY_CONFLICT"}')

    evidence, accepted = smoke.run_smoke(
        context="k3d-test",
        namespace="platform-test",
        secret_name="auth-service-meeting-ai-secret",
        secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
        base_url="http://127.0.0.1:31080",
        host_header="meeting-ai-private.testai.internal",
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        session_id=session_id,
        finalization_version=1,
        analysis_run_id=analysis_run_id,
        analysis_spec_version=analysis_spec_version,
        write_synthetic_result=True,
        confirm_synthetic_finalization=True,
        timeout_seconds=10,
        secret_loader=fake_secret_loader,
        request=fake_request,
    )

    assert accepted is True
    assert evidence["accepted"] is True
    assert evidence["schemaVersion"] == "faz24-meeting-ai-private-runtime-smoke.v2"
    assert evidence["syntheticWrite"]["meetingId"] == str(meeting_id)
    assert evidence["syntheticWrite"]["analysisRunId"] == str(analysis_run_id)
    assert evidence["syntheticWrite"]["syntheticFinalizationConfirmed"] is True
    status_by_id = {
        item["id"]: item["actualStatus"] for item in evidence["checks"]
    }
    assert status_by_id["ingest-first-write"] == 201
    assert status_by_id["ingest-idempotent-replay"] == 200
    assert status_by_id["ingest-idempotency-conflict"] == 409
    assert all(
        status_by_id[f"capability-issue-{phase}"] == 204
        for phase in ("first-write", "replay", "conflict")
    )
    assert capability_counter == 3
    serialized = json.dumps(evidence)
    assert "x" * 48 not in serialized
    assert valid_token not in serialized
    assert capability_service_token not in serialized
    assert "Authorization" not in serialized
    assert "X-Analysis-Job-Capability" not in serialized


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
            tenant_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            finalization_version=1,
            analysis_run_id=uuid.uuid4(),
            analysis_spec_version="meeting-intelligence-v1",
            write_synthetic_result=True,
            confirm_synthetic_finalization=True,
            timeout_seconds=10,
            secret_loader=fake_secret_loader,
        )
    except smoke.SmokeError as exc:
        assert "non-test" in str(exc)
    else:
        raise AssertionError("library entry point must reject non-test targets")
    assert secret_read is False


def test_capability_summary_enforces_exact_tuple_and_expiry_header():
    tenant_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    session_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    capability, expires_header = _capability_jwt(
        tenant_id=tenant_id,
        meeting_id=meeting_id,
        session_id=session_id,
        finalization_version=1,
        analysis_run_id=analysis_run_id,
        analysis_spec_version="meeting-intelligence-v1",
        capability_id=uuid.uuid4(),
    )
    binding, summary = smoke.summarize_and_validate_capability(
        capability,
        tenant_id=tenant_id,
        meeting_id=meeting_id,
        session_id=session_id,
        finalization_version=1,
        analysis_run_id=analysis_run_id,
        analysis_spec_version="meeting-intelligence-v1",
        expires_header=expires_header,
    )
    assert binding["sessionId"] == str(session_id)
    assert binding["transcriptSha256"] == "a" * 64
    assert summary["exactTupleBound"] is True

    try:
        smoke.summarize_and_validate_capability(
            capability,
            tenant_id=tenant_id,
            meeting_id=uuid.uuid4(),
            session_id=session_id,
            finalization_version=1,
            analysis_run_id=analysis_run_id,
            analysis_spec_version="meeting-intelligence-v1",
            expires_header=expires_header,
        )
    except smoke.SmokeError as exc:
        assert "meeting_id" in str(exc)
    else:
        raise AssertionError("cross-meeting capability must be rejected")


def test_synthetic_write_requires_explicit_finalization_confirmation_before_secret_read():
    secret_read = False

    def fake_secret_loader(*_args):
        nonlocal secret_read
        secret_read = True
        return "x" * 48

    try:
        smoke.run_smoke(
            context="k3d-test",
            namespace="platform-test",
            secret_name="auth-service-meeting-ai-secret",
            secret_key="SERVICE_CLIENT_MEETING_AI_SECRET",
            base_url="http://127.0.0.1:31080",
            host_header="meeting-ai-private.testai.internal",
            meeting_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            finalization_version=1,
            analysis_run_id=uuid.uuid4(),
            analysis_spec_version="meeting-intelligence-v1",
            write_synthetic_result=True,
            confirm_synthetic_finalization=False,
            timeout_seconds=10,
            secret_loader=fake_secret_loader,
        )
    except smoke.SmokeError as exc:
        assert "confirm-synthetic-finalization" in str(exc)
    else:
        raise AssertionError("unconfirmed finalization must not be mutated")
    assert secret_read is False


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
        tenant_id=None,
        session_id=None,
        finalization_version=None,
        analysis_run_id=None,
        analysis_spec_version="meeting-intelligence-v1",
        write_synthetic_result=False,
        confirm_synthetic_finalization=False,
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
